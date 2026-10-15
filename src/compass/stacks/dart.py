"""Dart and Flutter: pubspec.yaml, with versions from pubspec.lock."""

from __future__ import annotations

import posixpath

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir, pick_versions, run_in

FRAMEWORKS = {
    "bloc", "cloud_firestore", "dart_frog", "dio", "drift", "equatable", "firebase_core", "flutter_bloc",
    "flutter_hooks", "flutter_riverpod", "freezed", "get", "get_it", "go_router", "grpc", "hive",
    "hooks_riverpod", "http", "injectable", "isar", "json_serializable", "provider", "riverpod", "rxdart",
    "shelf", "sqflite",
}
TOOLS = {
    "build_runner", "coverage", "flutter_lints", "lints", "mockito", "mocktail", "test",
    "very_good_analysis",
}
_FORMAT = "dart format --output=none --set-exit-if-changed ."


def detect(repo: StackRepo) -> dict | None:
    manifests = repo.find("pubspec.yaml")
    if not manifests:
        return None
    packages = []
    for path in manifests[:MAX_PACKAGES]:
        data = repo.read_yaml(path)
        if not isinstance(data, dict):
            continue
        base = posixpath.dirname(path)
        lockfile, locked = _lock_versions(repo, base)
        declared: dict[str, str] = {}
        for section in ("dependencies", "dev_dependencies"):
            entries = data.get(section)
            for name, value in (entries.items() if isinstance(entries, dict) else ()):
                declared.setdefault(str(name), _declared_version(value))
        environment = data.get("environment") if isinstance(data.get("environment"), dict) else {}
        flutter = declared.get("flutter") == "sdk" or "flutter" in environment
        versions = {name: locked.get(name, spec) for name, spec in declared.items()}
        packages.append(
            compact(
                {
                    "path": path,
                    "name": _plain(data.get("name")),
                    "version": _plain(data.get("version")),
                    "package_manager": "flutter pub" if flutter else "dart pub",
                    "lockfile": lockfile,
                    "engines": compact({"dart": _plain(environment.get("sdk")), "flutter": _plain(environment.get("flutter"))}),
                    "frameworks": pick_versions(versions, FRAMEWORKS),
                    "tools": pick_versions(versions, TOOLS),
                    "dependencies": len([n for n in declared if n not in ("flutter", "flutter_test")]),
                    "commands": _commands(repo, base, flutter, declared),
                }
            )
        )
    if not packages:
        return None
    out: dict = {"packages": packages}
    if len(manifests) > MAX_PACKAGES:
        out["more_packages"] = len(manifests) - MAX_PACKAGES
    return out


def _commands(repo: StackRepo, base: str, flutter: bool, declared: dict[str, str]) -> dict[str, str]:
    tool = "flutter" if flutter else "dart"
    commands: dict[str, str] = {}
    if not flutter:
        entry = next((p for p in repo.files if posixpath.dirname(p) == in_dir(base, "bin") and p.endswith(".dart")), None)
        if entry:
            commands["build"] = run_in(base, f"dart compile exe {entry[len(base) + 1:] if base else entry}")
    if flutter or "test" in declared:
        commands["test"] = run_in(base, f"{tool} test")
    commands["lint"] = run_in(base, f"{tool} analyze")
    commands["format"] = run_in(base, _FORMAT)
    return commands


def _plain(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _declared_version(value: object) -> str:
    """`^1.2.0`, or for `{sdk: flutter}`, `{path: ...}` and `{git: ...}` the source."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "sdk" in value:
            return "sdk"
        version = value.get("version")
        if isinstance(version, str):
            return version
        return next((key for key in ("path", "git", "hosted") if key in value), "")
    return "any" if value is None else ""


def _lock_versions(repo: StackRepo, base: str) -> tuple[str | None, dict[str, str]]:
    """The package's own pubspec.lock, else the one at the repository root (a pub workspace)."""
    for directory in dict.fromkeys([base, ""]):
        path = in_dir(directory, "pubspec.lock")
        data = repo.read_yaml(path)
        if isinstance(data, dict) and isinstance(data.get("packages"), dict):
            versions = {
                str(name): str(entry["version"])
                for name, entry in data["packages"].items()
                if isinstance(entry, dict) and entry.get("source") != "sdk" and entry.get("version") is not None
            }
            return path, versions
    return None, {}
