"""Stack profile from manifest files (IX-10).

Only manifests, lockfiles and tool configs are read, never source code. Each
module in ``compass/stacks/`` is a detector with ``detect(repo) -> dict | None``
that reads one manifest type; the profile keys each result by the module name.
Adding a stack means adding a module there. A detector that fails is logged
and left out, like every other Compass failure.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import posixpath
import tomllib
from collections import Counter
from collections.abc import Iterable
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from compass import stacks
from compass.config import Config, load_config
from compass.files import list_paths
from compass.globs import compile_globs
from compass.languages import load_registry
from compass.log import log_error

MAX_PACKAGES = 10


class StackRepo:
    """What a detector sees: the file list plus safe readers.

    ``files`` is the enumerated list (gitignore and ``index.exclude`` applied).
    Lockfiles are usually excluded from the code map, so ``exists`` and the
    readers look at the working tree directly.
    """

    def __init__(self, root: Path, files: list[str]) -> None:
        self.root = root
        self.files = files

    @cached_property
    def _by_name(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for path in self.files:
            out.setdefault(posixpath.basename(path), []).append(path)
        return out

    def find(self, *names: str) -> list[str]:
        """Enumerated files with one of these names, shallowest first."""
        found = [p for n in names for p in self._by_name.get(n, [])]
        return sorted(set(found), key=lambda p: (p.count("/"), p))

    def find_suffix(self, suffix: str) -> list[str]:
        return sorted((p for p in self.files if p.endswith(suffix)), key=lambda p: (p.count("/"), p))

    def exists(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def read_text(self, rel: str, limit: int = 4_000_000) -> str | None:
        try:
            path = self.root / rel
            if not path.is_file() or path.stat().st_size > limit:
                return None
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def read_json(self, rel: str) -> Any:
        text = self.read_text(rel)
        try:
            return json.loads(text) if text is not None else None
        except ValueError:
            return None

    def read_toml(self, rel: str) -> dict[str, Any] | None:
        text = self.read_text(rel)
        try:
            return tomllib.loads(text) if text is not None else None
        except tomllib.TOMLDecodeError:
            return None

    def read_yaml(self, rel: str) -> Any:
        text = self.read_text(rel)
        try:
            return yaml.safe_load(text) if text is not None else None
        except yaml.YAMLError:
            return None


def in_dir(directory: str, name: str) -> str:
    return posixpath.join(directory, name) if directory else name


def run_in(directory: str, command: str) -> str:
    """A command as typed from the repo root."""
    return f"cd {directory} && {command}" if directory else command


def compact(value: dict[str, Any]) -> dict[str, Any]:
    """Drop empty entries so the profile stays small."""
    return {k: v for k, v in value.items() if v not in (None, "", [], {}, ())}


def pick_versions(deps: dict[str, str], wanted: Iterable[str]) -> dict[str, str]:
    wanted = set(wanted)
    return {name: deps[name] for name in sorted(deps) if name in wanted}


def detectors() -> list[tuple[str, Any]]:
    out = []
    for info in sorted(pkgutil.iter_modules(stacks.__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{stacks.__name__}.{info.name}")
        if callable(getattr(module, "detect", None)):
            out.append((info.name, module.detect))
    return out


def build_profile(root: Path, config: Config | None = None) -> dict[str, Any]:
    config = config if config is not None else load_config(root)
    registry = load_registry()
    files = list_paths(root, compile_globs(config.index.exclude))
    counts = Counter(lang for lang in (registry.detect_by_name(p) for p in files) if lang)
    repo = StackRepo(root, files)
    found: dict[str, Any] = {}
    for name, detect in detectors():
        try:
            result = detect(repo)
        except Exception as exc:
            log_error(root, f"stack detector {name}", exc)
            continue
        if result:
            found[name] = result
    return {"languages": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))), "stacks": found}


def render_text(profile: dict[str, Any]) -> str:
    """A short human-readable view of the profile."""
    lines = []
    langs = ", ".join(f"{k} ({v})" for k, v in profile["languages"].items()) or "none detected"
    lines.append(f"Languages: {langs}")
    for name, result in profile["stacks"].items():
        lines.append(f"{name}:")
        entries = result.get("packages") or result.get("modules") or [result]
        for entry in entries:
            where = entry.get("path", "")
            label = entry.get("name") or where
            if label:
                lines.append(f"  {label}" + (f"  [{where}]" if where and where != label else ""))
            for key in ("version", "requires_python", "go", "edition", "package_manager", "runner"):
                if entry.get(key):
                    lines.append(f"    {key}: {entry[key]}")
            for key in ("frameworks", "tools"):
                if entry.get(key):
                    joined = ", ".join(f"{k} {v}" if v else k for k, v in entry[key].items())
                    lines.append(f"    {key}: {joined}")
            commands = entry.get("commands") or {}
            if isinstance(commands, dict):
                for role, command in commands.items():
                    lines.append(f"    {role}: {command}")
            else:  # CI detectors list the commands a pipeline runs
                lines.extend(f"    run: {command}" for command in commands)
            for key in ("files", "images", "compose"):
                if entry.get(key):
                    lines.append(f"    {key}: {', '.join(entry[key])}")
    return "\n".join(lines)
