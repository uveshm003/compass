"""Swift: Package.swift (Swift Package Manager) with versions from Package.resolved.

Package.swift is Swift code, so only plain facts are read from it with
patterns: the tools version, the package name, targets and dependencies.
"""

from __future__ import annotations

import posixpath
import re

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir, pick_versions, run_in

# Package identities (the repository name, lower-cased), as SwiftPM names them.
FRAMEWORKS = {
    "alamofire", "async-http-client", "firebase-ios-sdk", "fluent", "grdb.swift", "grpc-swift",
    "hummingbird", "kingfisher", "realm-swift", "rxswift", "sdwebimage", "snapkit",
    "swift-algorithms", "swift-argument-parser", "swift-async-algorithms", "swift-collections",
    "swift-composable-architecture", "swift-crypto", "swift-dependencies", "swift-log", "swift-nio",
    "swift-openapi-runtime", "swift-protobuf", "swift-syntax", "vapor",
}
TOOLS = {"nimble", "quick", "swift-docc-plugin", "swift-format", "swift-snapshot-testing", "swiftformat", "swiftlint"}
_TOOLS_VERSION = re.compile(r"^\s*//\s*swift-tools-version\s*:\s*([0-9][0-9.]*)", re.IGNORECASE)
_NAME = re.compile(r"\bPackage\s*\(\s*name\s*:\s*\"([^\"]+)\"")
_TARGET = re.compile(r"\.(?:target|executableTarget|testTarget|macro|plugin|systemLibrary|binaryTarget)\s*\(\s*name\s*:\s*\"([^\"]+)\"")
_REQUIREMENT = [
    (re.compile(r"\bexact\s*:\s*\"([^\"]+)\""), "{}"),
    (re.compile(r"\bfrom\s*:\s*\"([^\"]+)\""), ">={}"),
    (re.compile(r"\bbranch\s*:\s*\"([^\"]+)\""), "branch {}"),
    (re.compile(r"\brevision\s*:\s*\"([^\"]+)\""), "revision {}"),
    (re.compile(r"\"([^\"]+)\"\s*\.\.[.<]\s*\"[^\"]+\""), ">={}"),
]


def detect(repo: StackRepo) -> dict | None:
    manifests = repo.find("Package.swift")
    if not manifests:
        return None
    packages = [p for p in (_package(repo, path) for path in manifests[:MAX_PACKAGES]) if p]
    if not packages:
        return None
    out: dict = {"packages": packages}
    if len(manifests) > MAX_PACKAGES:
        out["more_packages"] = len(manifests) - MAX_PACKAGES
    return out


def _package(repo: StackRepo, path: str) -> dict | None:
    text = repo.read_text(path)
    if text is None:
        return None
    base = posixpath.dirname(path)
    first = text.lstrip("﻿").split("\n", 1)[0]
    tools = _TOOLS_VERSION.match(first)
    name = _NAME.search(text)
    declared = _dependencies(text)
    locked = _resolved(repo, base)
    versions = {identity: locked.get(identity, spec) for identity, spec in declared.items()}
    commands = {"build": run_in(base, "swift build"), "test": run_in(base, "swift test")}
    if any(repo.exists(in_dir(d, ".swiftlint.yml")) for d in dict.fromkeys([base, ""])):
        commands["lint"] = run_in(base, "swiftlint lint")
    if any(repo.exists(in_dir(d, ".swift-format")) for d in dict.fromkeys([base, ""])):
        commands["format"] = run_in(base, "swift format lint --recursive .")
    return compact(
        {
            "path": path,
            "name": name.group(1) if name else None,
            "package_manager": "swiftpm",
            "engines": {"swift": f">={tools.group(1)}"} if tools else {},
            "targets": list(dict.fromkeys(_TARGET.findall(text))),
            "frameworks": pick_versions(versions, FRAMEWORKS),
            "tools": pick_versions(versions, TOOLS),
            "dependencies": len(declared),
            "commands": commands,
        }
    )


def _dependencies(text: str) -> dict[str, str]:
    """Identity -> declared requirement for each `.package(...)` call."""
    out: dict[str, str] = {}
    for m in re.finditer(r"\.package\s*\(", text):
        call = _balanced(text, m.end())
        source = re.search(r"\b(url|path|id)\s*:\s*\"([^\"]+)\"", call)
        if not source:
            continue
        kind, value = source.groups()
        identity = value.lower() if kind == "id" else _identity(value)
        if not identity:
            continue
        spec = "local" if kind == "path" else ""
        for pattern, template in _REQUIREMENT:
            req = pattern.search(call, source.end())
            if req:
                spec = template.format(req.group(1))
                break
        out.setdefault(identity, spec)
    return out


def _balanced(text: str, start: int) -> str:
    """The argument text of a call whose opening parenthesis ends at ``start``."""
    depth = 1
    for i in range(start, min(len(text), start + 2000)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return text[start : start + 2000]


def _identity(location: str) -> str:
    """SwiftPM's package identity: the last path component, lower-cased, without `.git`."""
    last = location.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"\.git$", "", last).lower()


def _resolved(repo: StackRepo, base: str) -> dict[str, str]:
    """Pinned versions from Package.resolved (format 1, 2 or 3), by identity."""
    data = repo.read_json(in_dir(base, "Package.resolved"))
    if not isinstance(data, dict):
        return {}
    pins = data.get("pins")
    if pins is None and isinstance(data.get("object"), dict):  # format 1
        pins = data["object"].get("pins")
    out: dict[str, str] = {}
    for pin in pins if isinstance(pins, list) else []:
        if not isinstance(pin, dict):
            continue
        identity = pin.get("identity") or _identity(str(pin.get("repositoryURL") or pin.get("location") or ""))
        state = pin.get("state") if isinstance(pin.get("state"), dict) else {}
        version = state.get("version") or (f"branch {state['branch']}" if state.get("branch") else None)
        if not version and state.get("revision"):
            version = f"revision {str(state['revision'])[:12]}"
        if identity and version:
            out[str(identity).lower()] = str(version)
    return out
