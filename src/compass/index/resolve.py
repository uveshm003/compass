"""Resolve raw import targets to repo files (IX-11), for importers_of and tests_for.

Each language picks a named strategy in its language.yaml ``imports`` section:

- ``path`` (JS, TS): ``./`` and ``../`` specifiers, relative to the importing
  file, trying extensions and index files; bare specifiers through the
  ``compilerOptions.paths`` and ``baseUrl`` of the nearest ``alias_files``
  (tsconfig.json, jsconfig.json). Other bare specifiers are packages.
- ``module`` (Python, Rust): module paths split on a separator. Relative forms
  (Python's leading dots, Rust's ``self``/``super``) are anchored at the
  importing module; absolute ones are matched by path suffix, dropping trailing
  segments that name items rather than modules. A lone module file only
  matches from a directory the importer could have on its import path (the
  repo root, its own ancestors, a ``source_roots`` directory), so a stray
  ``scripts/os.py`` does not capture every ``import os``.
- ``package`` (Go): an import path under a module declared in ``go.mod``
  resolves to that package's directory.

Anything unresolved (standard library, third-party packages) stays NULL, and so
does an import of the importing file itself. Resolution depends only on the
file set and the alias and module files, so it is deterministic.
"""

from __future__ import annotations

import fnmatch
import json
import posixpath
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from compass.languages import ImportRules, Registry

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_EXTENDS_DEPTH = 5


class Resolver:
    def __init__(self, root: Path, langs: dict[str, str | None], registry: Registry) -> None:
        self.root = root
        self.registry = registry
        self.langs = langs
        self.files = frozenset(langs)
        self.by_name: dict[str, list[str]] = {}
        self.by_tail: dict[str, list[str]] = {}  # last two path components: "pkg/__init__.py"
        self.dirs_by_lang: dict[str, set[str]] = {}
        for path in sorted(langs):
            self.by_name.setdefault(posixpath.basename(path), []).append(path)
            if "/" in path:
                self.by_tail.setdefault("/".join(path.rsplit("/", 2)[-2:]), []).append(path)
            lang = langs[path]
            if lang:
                self.dirs_by_lang.setdefault(lang, set()).add(posixpath.dirname(path))
        self._roots: dict[str, list[tuple[str, str]]] = {}
        # Re-resolving every import after a file comes or goes must fit the
        # hook's budget (NF-04), so work is shared: the same target from the
        # same directory resolves once, and the candidates for a module path
        # are found once whoever imports it.
        self._memo: dict[tuple[str | None, str, str, str], str | None] = {}
        self._suffix_found: dict[tuple[str | None, str], list[tuple[str, str, bool]]] = {}
        self._alias_configs: dict[str, _AliasConfig | None] = {}

    def resolve(self, importer: str, lang: str | None, target: str) -> str | None:
        spec = self.registry.get(lang)
        rules = spec.imports if spec else None
        if rules is None or rules.resolver is None:
            return None
        here, _, name = importer.rpartition("/")
        # Only Rust-style self/super anchors depend on the file name (mod.rs or not).
        by_file = name if rules.relative_markers and target.split(rules.separator, 1)[0] in rules.relative_markers else ""
        key = (lang, here, by_file, target)
        if key in self._memo:
            found = self._memo[key]
        else:
            if rules.resolver == "path":
                found = self._path(importer, rules, target)
            elif rules.resolver == "module":
                found = self._module(importer, lang, rules, target)
            elif rules.resolver == "package":
                found = self._package(lang, rules, target)
            else:
                found = None
            self._memo[key] = found
        return None if found == importer else found

    # -- path ------------------------------------------------------------------

    def _path(self, importer: str, rules: ImportRules, target: str) -> str | None:
        if target in (".", "..") or target.startswith(("./", "../")):
            return self._path_file(posixpath.join(posixpath.dirname(importer), target), rules)
        for base in self._alias_bases(importer, rules, target):
            hit = self._path_file(base, rules)
            if hit:
                return hit
        return None

    def _path_file(self, joined: str, rules: ImportRules) -> str | None:
        base = _inside(joined)
        if base is None:
            return None
        stem, ext = posixpath.splitext(base)
        candidates = [base] if base else []
        candidates += [stem + alias for alias in rules.extension_aliases.get(ext, ())]
        candidates += [base + e for e in rules.extensions] if base else []
        candidates += [posixpath.join(base, name) for name in rules.index_files]
        return next((c for c in candidates if c in self.files), None)

    def _alias_bases(self, importer: str, rules: ImportRules, target: str) -> list[str]:
        """Where a bare specifier may live under the nearest alias file's
        ``paths`` (exact pattern first, else the longest ``*`` prefix) and then
        its ``baseUrl``, as TypeScript resolves them."""
        config = self._nearest_alias_config(importer, rules)
        if config is None:
            return []
        best: tuple[int, list[str], str | None] | None = None
        for pattern, substitutions in config.paths:
            if "*" not in pattern:
                if pattern == target:
                    best = (len(pattern) + 1, substitutions, None)
                    break
                continue
            prefix, _, suffix = pattern.partition("*")
            if target.startswith(prefix) and target.endswith(suffix) and len(target) >= len(prefix) + len(suffix):
                if best is None or len(prefix) > best[0]:
                    best = (len(prefix), substitutions, target[len(prefix) : len(target) - len(suffix)])
        bases = []
        if best is not None:
            paths_base = config.base_url if config.base_url is not None else config.paths_dir
            for substitution in best[1]:
                filled = substitution.replace("*", best[2]) if best[2] is not None else substitution
                bases.append(posixpath.join(paths_base, filled))
        if config.base_url is not None:
            bases.append(posixpath.join(config.base_url, target))
        return bases

    def _nearest_alias_config(self, importer: str, rules: ImportRules) -> _AliasConfig | None:
        if not rules.alias_files:
            return None
        directory = posixpath.dirname(importer)
        while True:
            for name in rules.alias_files:
                path = posixpath.join(directory, name)
                if path in self.files:
                    return self._alias_config(path, 0)
            if not directory:
                return None
            directory = posixpath.dirname(directory)

    def _alias_config(self, path: str, depth: int) -> _AliasConfig | None:
        """``compilerOptions.baseUrl`` and ``paths`` of a tsconfig-style file,
        following relative ``extends``; each is relative to the file that sets it."""
        if path in self._alias_configs:
            return self._alias_configs[path]
        self._alias_configs[path] = None  # guards against extends cycles
        try:
            raw = _jsonc((self.root / path).read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        here = posixpath.dirname(path)
        config = _AliasConfig()
        extends = raw.get("extends")
        for parent in [extends] if isinstance(extends, str) else extends if isinstance(extends, list) else []:
            if not (isinstance(parent, str) and parent.startswith(("./", "../")) and depth < _EXTENDS_DEPTH):
                continue  # package extends (@tsconfig/node20) live outside the repo
            parent_path = _inside(posixpath.join(here, parent))
            if parent_path is None:
                continue
            if not parent_path.endswith(".json"):
                parent_path += ".json"
            inherited = self._alias_config(parent_path, depth + 1)
            if inherited is not None:
                config = inherited
        options = raw.get("compilerOptions")
        options = options if isinstance(options, dict) else {}
        base_url, paths = options.get("baseUrl"), options.get("paths")
        if isinstance(base_url, str):
            config = _AliasConfig(_inside(posixpath.join(here, base_url)), config.paths_dir, config.paths)
        if isinstance(paths, dict):
            patterns = [(k, [s for s in v if isinstance(s, str)]) for k, v in paths.items() if isinstance(v, list)]
            config = _AliasConfig(config.base_url, here, patterns)
        self._alias_configs[path] = config
        return config

    # -- module ----------------------------------------------------------------

    def _module(self, importer: str, lang: str | None, rules: ImportRules, target: str) -> str | None:
        anchor: str | None = None
        if rules.leading_dots and target.startswith("."):
            dots = len(target) - len(target.lstrip("."))
            anchor = posixpath.dirname(importer)
            for _ in range(dots - 1):
                anchor = posixpath.dirname(anchor)
            rest = target[dots:]
            segments = rest.split(rules.separator) if rest else []
        else:
            segments = target.split(rules.separator)
            while segments and segments[0] in rules.relative_markers:
                if anchor is None:
                    anchor = self._module_dir(importer, rules)
                for _ in range(rules.relative_markers[segments[0]]):
                    anchor = posixpath.dirname(anchor)
                segments = segments[1:]
            if anchor is None and segments and segments[0] in rules.strip_markers:
                segments = segments[1:]
        names: list[str] = []
        for segment in segments:  # stop at `{a, b}` groups and `*` globs
            if not _IDENTIFIER.fullmatch(segment):
                break
            names.append(segment)

        if anchor is not None:
            for n in range(len(names), 0, -1):
                hit = self._first_existing(posixpath.join(anchor, *names[:n]), rules)
                if hit:
                    return hit
            return self._anchor_file(anchor, rules)

        starts = [0] + (list(range(1, len(names) - 1)) if rules.drop_leading else [])
        for start in starts:
            part = names[start:]
            lowest = 1 if start == 0 else 2  # a lone leftover segment is too weak to trust
            for n in range(len(part), lowest - 1, -1):
                hit = self._suffix_match("/".join(part[:n]), importer, lang, rules)
                if hit:
                    return hit
        return None

    def _module_dir(self, importer: str, rules: ImportRules) -> str:
        """The directory holding a module's children: its own directory for
        mod.rs-style files, ``dir/stem`` for the rest."""
        directory = posixpath.dirname(importer)
        name = posixpath.basename(importer)
        if rules.dir_modules and name not in rules.dir_modules:
            return posixpath.join(directory, posixpath.splitext(name)[0])
        return directory

    def _anchor_file(self, anchor: str, rules: ImportRules) -> str | None:
        """The file of the module that owns directory ``anchor``: its package
        file, else (Rust 2018) the ``anchor.rs`` beside the directory, else a
        crate root such as ``lib.rs``."""
        candidates = [posixpath.join(anchor, pf) for pf in rules.package_files]
        if rules.dir_modules:
            candidates += [anchor + e for e in rules.extensions] if anchor else []
            candidates += [posixpath.join(anchor, m) for m in rules.dir_modules if m not in rules.package_files]
        return next((c for c in candidates if c in self.files), None)

    def _first_existing(self, stem: str, rules: ImportRules) -> str | None:
        for candidate in [stem + e for e in rules.extensions] + [posixpath.join(stem, pf) for pf in rules.package_files]:
            if candidate in self.files:
                return candidate
        return None

    def _suffix_match(self, rel: str, importer: str, lang: str | None, rules: ImportRules) -> str | None:
        """The file whose path ends with ``rel`` (plus an extension or package
        file), preferring the one nearest the importer."""
        candidates = self._suffix_candidates(rel, lang, rules)
        if not candidates:
            return None
        here = importer.rpartition("/")[0]
        found = [path for path, root, nested in candidates if nested or _on_import_path(root, here, rules)]
        if len(found) <= 1:
            return found[0] if found else None
        parts_here = here.split("/")

        def closeness(path: str) -> tuple[int, int, str]:
            shared = 0
            for a, b in zip(posixpath.dirname(path).split("/"), parts_here):
                if a != b:
                    break
                shared += 1
            return (-shared, len(path), path)

        return min(found, key=closeness)

    def _suffix_candidates(self, rel: str, lang: str | None, rules: ImportRules) -> list[tuple[str, str, bool]]:
        """(path, root, nested) for every file of ``lang`` that is module
        ``rel``, whatever imports it. ``root`` is the directory the module path
        starts in; ``nested`` is False for a lone module file there. A root
        that is itself a package is rejected: that file's real module path
        would be longer."""
        key = (lang, rel)
        cached = self._suffix_found.get(key)
        if cached is not None:
            return cached
        found = []
        for candidate in [rel + e for e in rules.extensions] + [posixpath.join(rel, pf) for pf in rules.package_files]:
            nested = "/" in candidate
            pool = self.by_tail.get("/".join(candidate.rsplit("/", 2)[-2:])) if nested else self.by_name.get(candidate)
            for path in pool or ():
                if self.langs.get(path) != lang or not (path == candidate or path.endswith("/" + candidate)):
                    continue
                root = path[: len(path) - len(candidate)].rstrip("/")
                if any(posixpath.join(root, pf) in self.files for pf in rules.package_files):
                    continue
                found.append((path, root, nested))
        self._suffix_found[key] = found
        return found

    # -- package ---------------------------------------------------------------

    def _package(self, lang: str | None, rules: ImportRules, target: str) -> str | None:
        for module, directory in self._module_roots(lang, rules):
            if target == module or target.startswith(module + "/"):
                rest = target[len(module) :].strip("/")
                package = posixpath.normpath(posixpath.join(directory, rest)) if rest else directory
                package = "" if package == "." else package
                return package if package in self.dirs_by_lang.get(lang or "", ()) else None
        return None

    def _module_roots(self, lang: str | None, rules: ImportRules) -> list[tuple[str, str]]:
        key = lang or ""
        if key not in self._roots:
            roots = []
            for filename, pattern in rules.module_files.items():
                for path in self.by_name.get(filename, ()):
                    try:
                        text = (self.root / path).read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    m = re.search(pattern, text, re.MULTILINE)
                    if m:
                        roots.append((m.group(1), posixpath.dirname(path)))
            self._roots[key] = sorted(roots, key=lambda r: (-len(r[0]), r))
        return self._roots[key]


class _AliasConfig:
    """Resolved ``baseUrl`` and ``paths`` of one alias file (repo-relative dirs)."""

    __slots__ = ("base_url", "paths_dir", "paths")

    def __init__(
        self, base_url: str | None = None, paths_dir: str = "", paths: list[tuple[str, list[str]]] | None = None
    ) -> None:
        self.base_url = base_url
        self.paths_dir = paths_dir
        self.paths = paths or []


def feeds_resolution(registry: Registry) -> Callable[[str], bool]:
    """Whether a file name (go.mod, tsconfig.json, ...) is one whose content
    feeds import resolution, so that editing it re-resolves every import.
    ``tsconfig.base.json`` counts too: alias files often extend one."""
    names: set[str] = set()
    patterns: list[str] = []
    for spec in registry:
        names.update(spec.imports.module_files)
        for name in spec.imports.alias_files:
            names.add(name)
            stem, ext = posixpath.splitext(name)
            patterns.append(f"{stem}.*{ext}")
    return lambda name: name in names or any(fnmatch.fnmatchcase(name, p) for p in patterns)


def _on_import_path(root: str, importer_dir: str, rules: ImportRules) -> bool:
    """Whether a lone module file in ``root`` is importable from ``importer_dir``:
    from the repo root, the importer's own directory or its ancestors (a script's
    directory is first on its import path), or a configured source root."""
    if not root or importer_dir == root or importer_dir.startswith(root + "/"):
        return True
    return posixpath.basename(root) in rules.source_roots


def _inside(path: str) -> str | None:
    """``path`` normalised, ``""`` for the repo root, None if it leaves the repo."""
    normalized = posixpath.normpath(path) if path else "."
    if normalized == ".." or normalized.startswith(("../", "/")):
        return None
    return "" if normalized == "." else normalized


def _jsonc(text: str) -> Any:
    """JSON with comments and trailing commas, as tsconfig.json allows."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            if c in "}]":
                k = len(out) - 1
                while k >= 0 and out[k].isspace():
                    k -= 1
                if k >= 0 and out[k] == ",":
                    del out[k]
            out.append(c)
            i += 1
    return json.loads("".join(out))
