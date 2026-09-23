"""Language registry, loaded from ``queries/<lang>/language.yaml``.

Adding a language means adding a directory under ``src/compass/queries/``:
a ``language.yaml`` (grammar, file matching, doc and visibility rules), a
``tags.scm`` query, and optionally an ``imports.scm`` query. Nothing in the core
changes. See ``queries/README.md`` for the capture conventions.
"""

from __future__ import annotations

import functools
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path, PurePosixPath

import yaml

# Named docstring rules a language.yaml may select (implemented in index/docs.py).
DOCSTRING_RULES = frozenset({"body_first_string"})


@dataclass(frozen=True)
class VisibilityRule:
    """How a language spells visibility; see queries/README.md."""

    modifiers: tuple[tuple[re.Pattern[str], str], ...] = ()
    names: tuple[tuple[re.Pattern[str], str], ...] = ()
    exported_by: frozenset[str] = frozenset()
    default: str | None = None


@dataclass(frozen=True)
class LanguageSpec:
    name: str
    grammar: str
    extensions: tuple[str, ...]
    grammar_by_extension: Mapping[str, str]
    filenames: tuple[str, ...]
    shebangs: tuple[str, ...]
    wrappers: frozenset[str]
    skip_before_doc: frozenset[str]
    docstring: str | None
    visibility: VisibilityRule
    index_files: tuple[str, ...]
    directory: Path = field(compare=False)

    def grammar_for(self, path: str) -> str:
        suffix = PurePosixPath(path).suffix.lower()
        return self.grammar_by_extension.get(suffix, self.grammar)

    def tags_query(self) -> str:
        return (self.directory / "tags.scm").read_text(encoding="utf-8")

    def imports_query(self) -> str | None:
        path = self.directory / "imports.scm"
        return path.read_text(encoding="utf-8") if path.exists() else None


class Registry:
    def __init__(self, specs: list[LanguageSpec], fingerprint: str) -> None:
        self._specs = {spec.name: spec for spec in specs}
        self.fingerprint = fingerprint
        self._by_ext: dict[str, str] = {}
        self._by_name: dict[str, str] = {}
        self._by_shebang: dict[str, str] = {}
        for spec in sorted(specs, key=lambda s: s.name):
            for ext in spec.extensions:
                self._by_ext.setdefault(ext.lower(), spec.name)
            for filename in spec.filenames:
                self._by_name.setdefault(filename, spec.name)
            for interpreter in spec.shebangs:
                self._by_shebang.setdefault(interpreter, spec.name)
        self.index_files = frozenset(f for spec in specs for f in spec.index_files)

    def __iter__(self):
        return iter(sorted(self._specs.values(), key=lambda s: s.name))

    def get(self, name: str | None) -> LanguageSpec | None:
        return self._specs.get(name) if name else None

    def detect(self, path: str, head: bytes | None = None) -> str | None:
        """Language for ``path``: by file name, then extension, then shebang."""
        name = PurePosixPath(path).name
        if name in self._by_name:
            return self._by_name[name]
        suffix = PurePosixPath(name).suffix.lower()
        if suffix:
            return self._by_ext.get(suffix)
        if head and head.startswith(b"#!"):
            return self._by_shebang.get(shebang_interpreter(head))
        return None

    def detect_by_name(self, path: str) -> str | None:
        """Extension-only detection, for callers that must not read files."""
        return self.detect(path, None)


def shebang_interpreter(head: bytes) -> str:
    """``python3`` for ``#!/usr/bin/env -S python3 -u``, ``bash`` for ``#!/bin/bash``."""
    line = head.split(b"\n", 1)[0][2:].decode("utf-8", "replace").strip()
    parts = line.split()
    if not parts:
        return ""
    program = PurePosixPath(parts[0]).name
    if program == "env":
        args = [p for p in parts[1:] if not p.startswith("-") and "=" not in p]
        program = PurePosixPath(args[0]).name if args else ""
    # python3.12 -> python3, node18 stays node18 (list it explicitly if needed)
    return re.sub(r"(\d)\.\d+$", r"\1", program)


def queries_root() -> Path:
    return Path(str(resources.files("compass") / "queries"))


@functools.cache
def load_registry() -> Registry:
    root = queries_root()
    specs = []
    digest = hashlib.blake2b(digest_size=16)
    for directory in sorted(p for p in root.iterdir() if (p / "language.yaml").is_file()):
        specs.append(_load_spec(directory))
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix in (".yaml", ".scm"):
                digest.update(f"{directory.name}/{path.name}\0".encode())
                digest.update(path.read_bytes())
    return Registry(specs, digest.hexdigest())


def _load_spec(directory: Path) -> LanguageSpec:
    raw = yaml.safe_load((directory / "language.yaml").read_text(encoding="utf-8")) or {}
    name = raw.get("name", directory.name)
    if name != directory.name:
        raise ValueError(f"{directory}/language.yaml: name {name!r} must match the directory")
    docstring = raw.get("docstring")
    if docstring is not None and docstring not in DOCSTRING_RULES:
        raise ValueError(f"{directory}/language.yaml: unknown docstring rule {docstring!r}")
    vis = raw.get("visibility") or {}
    return LanguageSpec(
        name=name,
        grammar=raw.get("grammar", name),
        extensions=tuple(e.lower() for e in raw.get("extensions", [])),
        grammar_by_extension={k.lower(): v for k, v in (raw.get("grammar_by_extension") or {}).items()},
        filenames=tuple(raw.get("filenames", [])),
        shebangs=tuple(raw.get("shebangs", [])),
        wrappers=frozenset(raw.get("wrappers", [])),
        skip_before_doc=frozenset(raw.get("skip_before_doc", [])),
        docstring=docstring,
        visibility=VisibilityRule(
            modifiers=tuple((re.compile(p), v) for p, v in vis.get("modifiers", [])),
            names=tuple((re.compile(p), v) for p, v in vis.get("names", [])),
            exported_by=frozenset(vis.get("exported_by", [])),
            default=vis.get("default"),
        ),
        index_files=tuple(raw.get("index_files", [])),
        directory=directory,
    )
