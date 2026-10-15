"""Gradle: build.gradle(.kts), settings.gradle(.kts), the version catalog
(gradle/libs.versions.toml) and the wrapper's Gradle version.

Build scripts are code; they are read with patterns, never run, so a version
computed in the script stays blank.
"""

from __future__ import annotations

import posixpath
import re

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir, run_in
from compass.stacks import _jvm

BUILD_FILES = ("build.gradle.kts", "build.gradle")
SETTINGS_FILES = ("settings.gradle.kts", "settings.gradle")
_QUOTED = r"""(?:"([^"\n]*)"|'([^'\n]*)')"""
_CONFIGURATION = re.compile(
    r"^\s*(\w*(?:[iI]mplementation|[aA]pi|[cC]ompileOnly|[rR]untimeOnly|[aA]nnotationProcessor|kapt|ksp)\w*)\s*[ (]\s*"
    r"(?:(?:platform|enforcedPlatform)\s*\(\s*)?"
    rf"(?:{_QUOTED}|(libs\.[\w.]+)|kotlin\s*\(\s*{_QUOTED})",
    re.MULTILINE,
)
_PLUGIN_ID = re.compile(rf"\bid\s*\(?\s*{_QUOTED}\s*\)?(?:\s*version\s*\(?\s*{_QUOTED})?")
_PLUGIN_KOTLIN = re.compile(rf"\bkotlin\s*\(\s*{_QUOTED}\s*\)(?:\s*version\s*\(?\s*{_QUOTED})?")
_PLUGIN_ALIAS = re.compile(r"\balias\s*\(\s*libs\.plugins\.([\w.]+)\s*\)")
_PLUGIN_BARE = re.compile(r"^\s*`?(java|java-library|application|checkstyle|jacoco)`?\s*$", re.MULTILINE)
_TOOLCHAIN = re.compile(r"(?:jvmToolchain\s*\(\s*|JavaLanguageVersion\.of\s*\(\s*)(\d+)")
_COMPATIBILITY = re.compile(r"\b(?:source|target)Compatibility\s*=\s*(?:JavaVersion\.VERSION_([\d_]+)|['\"]?([\d.]+))")
_ROOT_NAME = re.compile(rf"rootProject\.name\s*=\s*{_QUOTED}")
_INCLUDE = re.compile(r"^\s*include\s*\(?(.*)$", re.MULTILINE)
_VERSION = re.compile(rf"^\s*version\s*=\s*{_QUOTED}", re.MULTILINE)
_WRAPPER = re.compile(r"distributionUrl=.*gradle-([\w.\-]+?)-(?:bin|all)\.zip")


def detect(repo: StackRepo) -> dict | None:
    builds = repo.find(*BUILD_FILES)
    settings = repo.find(*SETTINGS_FILES)
    if not builds and not settings:
        return None
    roots = sorted({posixpath.dirname(p) for p in settings} or {posixpath.dirname(builds[0])},
                   key=lambda d: (d.count("/") if d else -1, d))
    projects = {root: _settings(repo, root) for root in roots}
    packages = []
    for path in builds[:MAX_PACKAGES]:
        base = posixpath.dirname(path)
        root = _root_for(base, roots)
        packages.append(_package(repo, path, base, root, projects.get(root, {})))
    if not packages:  # settings alone: a build with no scripts of its own
        return None
    out: dict = {"packages": packages}
    if len(builds) > MAX_PACKAGES:
        out["more_packages"] = len(builds) - MAX_PACKAGES
    return out


def _root_for(base: str, roots: list[str]) -> str:
    inside = [r for r in roots if not r or base == r or base.startswith(r + "/")]
    return max(inside, key=len) if inside else base


def _settings(repo: StackRepo, root: str) -> dict:
    text = next((t for t in (repo.read_text(in_dir(root, f)) for f in SETTINGS_FILES) if t is not None), "")
    name = _ROOT_NAME.search(text)
    includes = []
    for m in _INCLUDE.finditer(text):
        includes += [a or b for a, b in re.findall(_QUOTED, m.group(1))]
    wrapper = repo.read_text(in_dir(root, "gradle/wrapper/gradle-wrapper.properties")) or ""
    gradle = _WRAPPER.search(wrapper)
    return {
        "name": (name.group(1) or name.group(2)) if name else None,
        "includes": [i.lstrip(":") for i in includes],
        "catalog": _catalog(repo.read_toml(in_dir(root, "gradle/libs.versions.toml")) or {}),
        "gradle": gradle.group(1) if gradle else None,
        "wrapper": repo.exists(in_dir(root, "gradlew")) or repo.exists(in_dir(root, "gradlew.bat")),
    }


def _catalog(data: dict) -> dict:
    """Version-catalog aliases, normalised the way Gradle builds accessors
    (``ktor-client-core`` is ``libs.ktor.client.core``)."""
    versions = {k: v for k, v in (data.get("versions") or {}).items() if isinstance(v, str)}

    def version_of(entry: dict) -> str:
        version = entry.get("version")
        if isinstance(version, dict):
            return versions.get(str(version.get("ref")), str(version.get("strictly") or version.get("require") or ""))
        return str(version or "")

    libraries = {}
    for alias, entry in (data.get("libraries") or {}).items():
        if isinstance(entry, str):
            group, artifact, *rest = (entry.split(":") + [""])[:3]
            libraries[_accessor(alias)] = (f"{group}:{artifact}", rest[0])
        elif isinstance(entry, dict):
            module = entry.get("module") or f"{entry.get('group', '')}:{entry.get('name', '')}"
            libraries[_accessor(alias)] = (str(module), version_of(entry))
    plugins = {}
    for alias, entry in (data.get("plugins") or {}).items():
        if isinstance(entry, str):
            plugin_id, _, version = entry.partition(":")
            plugins[_accessor(alias)] = (plugin_id, version)
        elif isinstance(entry, dict):
            plugins[_accessor(alias)] = (str(entry.get("id", "")), version_of(entry))
    return {"libraries": libraries, "plugins": plugins}


def _accessor(alias: str) -> str:
    return re.sub(r"[-_.]", ".", alias).lower()


def _package(repo: StackRepo, path: str, base: str, root: str, project: dict) -> dict:
    text = repo.read_text(path) or ""
    catalog = project.get("catalog") or {"libraries": {}, "plugins": {}}
    declared: dict[str, str] = {}
    for m in _CONFIGURATION.finditer(text):
        notation, accessor, kotlin_module = m.group(2) or m.group(3), m.group(4), m.group(5) or m.group(6)
        if accessor:
            found = catalog["libraries"].get(_accessor(accessor[len("libs."):]))
            if found:
                declared.setdefault(found[0], found[1])
        elif kotlin_module:
            declared.setdefault(f"org.jetbrains.kotlin:kotlin-{kotlin_module}", "")
        elif notation and notation.count(":") >= 1:
            group, artifact, *rest = notation.split(":")
            declared.setdefault(f"{group}:{artifact}", rest[0] if rest else "")
    plugins = _plugins(text, catalog)
    frameworks, tools = _jvm.classify(declared)
    for plugin_id, version in sorted(plugins.items()):
        if plugin_id in _jvm.PLUGINS:
            table, name = _jvm.PLUGINS[plugin_id]
            target = frameworks if table == "frameworks" else tools
            if not target.get(name):
                target[name] = version
    engines = {"java": _java_version(text), "gradle": project.get("gradle")}
    kotlin = next((plugins[p] for p in _jvm.KOTLIN_PLUGINS if plugins.get(p)), None)
    if kotlin is None and any(p in plugins for p in _jvm.KOTLIN_PLUGINS):
        kotlin = ""
    if kotlin:
        engines["kotlin"] = kotlin
    version = _VERSION.search(text)
    sub = posixpath.relpath(base, root) if base != root else None
    name = sub.replace("/", ":") if sub else project.get("name") or posixpath.basename(base) or None
    return compact(
        {
            "path": path,
            "name": name,
            "version": (version.group(1) or version.group(2)) if version else None,
            "engines": compact(engines),
            "modules": project.get("includes") if not sub else None,
            "frameworks": dict(sorted(frameworks.items())),
            "tools": dict(sorted(tools.items())),
            "dependencies": len(declared),
            "commands": _commands(root, sub, project, tools, plugins),
        }
    )


def _plugins(text: str, catalog: dict) -> dict[str, str]:
    found: dict[str, str] = {}
    for m in _PLUGIN_ID.finditer(text):
        found.setdefault(m.group(1) or m.group(2), m.group(3) or m.group(4) or "")
    for m in _PLUGIN_KOTLIN.finditer(text):
        found.setdefault(f"org.jetbrains.kotlin.{m.group(1) or m.group(2)}", m.group(3) or m.group(4) or "")
    for m in _PLUGIN_ALIAS.finditer(text):
        plugin = catalog["plugins"].get(_accessor(m.group(1)))
        if plugin:
            found.setdefault(plugin[0], plugin[1])
    for m in _PLUGIN_BARE.finditer(text):
        found.setdefault(m.group(1), "")
    return found


def _java_version(text: str) -> str | None:
    m = _TOOLCHAIN.search(text)
    if m:
        return m.group(1)
    m = _COMPATIBILITY.search(text)
    if m:
        return m.group(1).replace("_", ".") if m.group(1) else m.group(2)
    return None


def _commands(root: str, sub: str | None, project: dict, tools: dict[str, str], plugins: dict[str, str]) -> dict[str, str]:
    gradle = "./gradlew" if project.get("wrapper") else "gradle"
    prefix = f":{sub.replace('/', ':')}:" if sub else ""
    out = {"build": run_in(root, f"{gradle} {prefix}build"), "test": run_in(root, f"{gradle} {prefix}test")}
    lint = next((task for tool, task in (("detekt", "detekt"), ("ktlint", "ktlintCheck"), ("spotless", "spotlessCheck"),
                                          ("checkstyle", "checkstyleMain")) if tool in tools), None)
    if lint is None and any(p.startswith("com.android.") for p in plugins):
        lint = "lint"
    if lint:
        out["lint"] = run_in(root, f"{gradle} {prefix}{lint}")
    return out
