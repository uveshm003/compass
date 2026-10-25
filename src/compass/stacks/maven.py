"""Maven: pom.xml (modules, properties, dependency management and plugins)."""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir, run_in
from compass.stacks import _jvm

_PROPERTY = re.compile(r"\$\{([^}]+)\}")
_JAVA_PROPERTIES = ("maven.compiler.release", "maven.compiler.target", "maven.compiler.source", "java.version")


def detect(repo: StackRepo) -> dict | None:
    poms = repo.find("pom.xml")
    if not poms:
        return None
    parsed = {path: _parse(repo, path) for path in poms[:MAX_PACKAGES]}
    parsed = {path: pom for path, pom in parsed.items() if pom is not None}
    _inherit(parsed)
    # Which aggregator lists each module directory: `mvn -pl <module>` runs from there.
    aggregator: dict[str, str] = {}
    for path, pom in parsed.items():
        base = posixpath.dirname(path)
        for module in pom["modules"]:
            aggregator.setdefault(posixpath.normpath(in_dir(base, module)), base)
    packages = [_package(repo, path, pom, aggregator) for path, pom in parsed.items()]
    if not packages:
        return None
    out: dict = {"packages": packages}
    if len(poms) > MAX_PACKAGES:
        out["more_packages"] = len(poms) - MAX_PACKAGES
    return out


def _parse(repo: StackRepo, path: str) -> dict | None:
    text = repo.read_text(path)
    if text is None:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    props = {_local(e.tag): (e.text or "").strip() for e in _children(root, "properties")}
    parent = _child(root, "parent")
    for key in ("groupId", "artifactId", "version"):  # a module inherits its parent's group and version
        value = _text(root, key) or (_text(parent, key) if key != "artifactId" else None)
        if value:
            props[f"project.{key}"] = value
        if _text(parent, key):
            props[f"project.parent.{key}"] = _text(parent, key) or ""
    build = _child(root, "build")
    plugins: dict[str, tuple[ET.Element, str | None]] = {}
    for plugin in [*_children(build, "plugins"), *_children(_child(build, "pluginManagement"), "plugins")]:
        plugins.setdefault(_resolve(_text(plugin, "artifactId"), props) or "", (plugin, _text(plugin, "version")))
    boot = parent is not None and _text(parent, "artifactId") == "spring-boot-starter-parent"
    return {
        "root": root,
        "props": props,
        "parent": parent,
        # Versions stay raw until a parent pom's properties are merged in.
        "managed": {_coordinate(d, props): _text(d, "version") or ""
                    for d in _children(_child(root, "dependencyManagement"), "dependencies")},
        "declared": {_coordinate(d, props): _text(d, "version") or "" for d in _children(root, "dependencies")},
        "plugins": plugins,
        "boot_parent": (_text(parent, "version") or "") if boot else None,
        "modules": [(m.text or "").strip() for m in _children(root, "modules") if (m.text or "").strip()],
    }


def _inherit(parsed: dict[str, dict]) -> None:
    """A module pom takes the properties, managed versions and Spring Boot
    parent of a parent pom in the same repository, then resolves its versions."""
    by_coordinate = {f"{p['props'].get('project.groupId', '')}:{_text(p['root'], 'artifactId')}": p
                     for p in parsed.values()}
    done: set[int] = set()

    def merge(pom: dict, depth: int = 0) -> None:
        if id(pom) in done or depth > 5:
            return
        done.add(id(pom))
        parent = pom["parent"]
        found = by_coordinate.get(f"{_text(parent, 'groupId')}:{_text(parent, 'artifactId')}") if parent is not None else None
        if found is None or found is pom:
            return
        merge(found, depth + 1)
        pom["props"] = {**found["props"], **pom["props"]}
        pom["managed"] = {**found["managed"], **pom["managed"]}
        if pom["boot_parent"] is None:
            pom["boot_parent"] = found["boot_parent"]

    for pom in parsed.values():
        merge(pom)
    for pom in parsed.values():
        props = pom["props"]
        managed = {c: _resolve(v, props) or "" for c, v in pom["managed"].items()}
        pom["managed"] = managed
        pom["declared"] = {c: _resolve(v, props) or managed.get(c, "") for c, v in pom["declared"].items()}
        pom["plugins"] = {a: (el, _resolve(v, props)) for a, (el, v) in pom["plugins"].items()}


def _package(repo: StackRepo, path: str, pom: dict, aggregator: dict[str, str]) -> dict:
    root, props = pom["root"], pom["props"]
    base = posixpath.dirname(path)
    frameworks, tools = _jvm.classify(pom["declared"])
    if pom["boot_parent"] is not None:
        frameworks["spring-boot"] = pom["boot_parent"]
    boot_bom = pom["managed"].get("org.springframework.boot:spring-boot-dependencies")
    if boot_bom and not frameworks.get("spring-boot"):  # an imported Spring Boot BOM
        frameworks["spring-boot"] = boot_bom
    for artifact, (_plugin, version) in sorted(pom["plugins"].items()):
        if artifact in _jvm.PLUGINS:
            table, name = _jvm.PLUGINS[artifact]
            target = frameworks if table == "frameworks" else tools
            if not target.get(name):
                target[name] = version or ""
    engines = {"java": _java_version(pom)}
    kotlin = _resolve(props.get("kotlin.version"), props) or (pom["plugins"].get("kotlin-maven-plugin") or (None, None))[1]
    if kotlin:
        engines["kotlin"] = kotlin
    return compact(
        {
            "path": path,
            "name": _resolve(_text(root, "artifactId"), props),
            "version": _resolve(props.get("project.version"), props),
            "packaging": _text(root, "packaging"),
            "engines": compact(engines),
            "modules": pom["modules"],
            "frameworks": dict(sorted(frameworks.items())),
            "tools": dict(sorted(tools.items())),
            "dependencies": len(pom["declared"]),
            "commands": _commands(repo, base, aggregator, tools),
        }
    )


def _commands(repo: StackRepo, base: str, aggregator: dict[str, str], tools: dict[str, str]) -> dict[str, str]:
    home = aggregator.get(base)
    where = home if home is not None else base
    mvn = "./mvnw" if repo.exists(in_dir(where, "mvnw")) or repo.exists("mvnw") else "mvn"
    if home is not None:
        module = posixpath.relpath(base, home) if home else base
        return {"build": run_in(home, f"{mvn} -pl {module} -am package"), "test": run_in(home, f"{mvn} -pl {module} -am test")}
    out = {"build": run_in(base, f"{mvn} package"), "test": run_in(base, f"{mvn} test")}
    if "checkstyle" in tools:
        out["lint"] = run_in(base, f"{mvn} checkstyle:check")
    elif "spotless" in tools:
        out["lint"] = run_in(base, f"{mvn} spotless:check")
    return out


def _java_version(pom: dict) -> str | None:
    props = pom["props"]
    for key in _JAVA_PROPERTIES:
        if props.get(key):
            return _resolve(props[key], props)
    plugin = (pom["plugins"].get("maven-compiler-plugin") or (None, None))[0]
    config = _child(plugin, "configuration") if plugin is not None else None
    for key in ("release", "target", "source"):
        value = _resolve(_text(config, key), props) if config is not None else None
        if value:
            return value
    return None


def _coordinate(dep: ET.Element, props: dict[str, str]) -> str:
    return f"{_resolve(_text(dep, 'groupId'), props) or ''}:{_resolve(_text(dep, 'artifactId'), props) or ''}"


def _resolve(value: str | None, props: dict[str, str], depth: int = 0) -> str | None:
    """``${jackson.version}`` from the pom's properties; unknown ones stay blank."""
    if not value:
        return None
    if depth > 5 or "${" not in value:
        return value
    resolved = _PROPERTY.sub(lambda m: props.get(m.group(1), ""), value)
    return _resolve(resolved, props, depth + 1) or None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    return next((c for c in element if _local(c.tag) == name), None)


def _children(element: ET.Element | None, name: str) -> list[ET.Element]:
    """The elements inside ``element``'s ``name`` child: dependencies/dependency."""
    holder = _child(element, name)
    return list(holder) if holder is not None else []


def _text(element: ET.Element | None, name: str) -> str | None:
    child = _child(element, name)
    return (child.text or "").strip() or None if child is not None else None
