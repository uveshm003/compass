"""Rust: Cargo.toml (packages and workspaces) with versions from Cargo.lock."""

from __future__ import annotations

import posixpath

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir, pick_versions, run_in

FRAMEWORKS = {
    "actix-web", "anyhow", "async-std", "axum", "bevy", "clap", "diesel", "hyper", "rayon",
    "reqwest", "rocket", "sea-orm", "serde", "sqlx", "tauri", "thiserror", "tokio", "tonic",
    "tracing", "warp", "wasm-bindgen",
}


def detect(repo: StackRepo) -> dict | None:
    manifests = repo.find("Cargo.toml")
    if not manifests:
        return None
    locked = _lock_versions(repo, manifests)
    packages = []
    workspace_roots = []
    for path in manifests[:MAX_PACKAGES]:
        data = repo.read_toml(path)
        if not isinstance(data, dict):
            continue
        base = posixpath.dirname(path)
        package = data.get("package") if isinstance(data.get("package"), dict) else {}
        workspace = data.get("workspace") if isinstance(data.get("workspace"), dict) else {}
        if workspace:
            workspace_roots.append(base)
        declared: dict[str, str] = {}
        for section in ("dependencies", "dev-dependencies", "build-dependencies"):
            for name, value in (data.get(section) or {}).items():
                declared.setdefault(name, _declared_version(value))
        for name, value in (workspace.get("dependencies") or {}).items():
            declared.setdefault(name, _declared_version(value))
        versions = {name: locked.get(name, spec) for name, spec in declared.items()}
        name = package.get("name")
        in_workspace = any(base.startswith(root + "/") or root == "" for root in workspace_roots if root != base)
        if in_workspace and name:
            commands = {"test": f"cargo test -p {name}", "lint": f"cargo clippy -p {name}"}
        else:
            commands = {
                "build": run_in(base, "cargo build"),
                "test": run_in(base, "cargo test"),
                "lint": run_in(base, "cargo clippy --all-targets"),
                "format": run_in(base, "cargo fmt --check"),
            }
        packages.append(
            compact(
                {
                    "path": path,
                    "name": name,
                    "version": _plain(package.get("version")),
                    "edition": _plain(package.get("edition")),
                    "rust_version": _plain(package.get("rust-version")),
                    "workspace_members": [str(m) for m in workspace.get("members", [])],
                    "frameworks": pick_versions(versions, FRAMEWORKS),
                    "dependencies": len(declared),
                    "commands": commands,
                }
            )
        )
    if not packages:
        return None
    out: dict = {"packages": packages}
    if len(manifests) > MAX_PACKAGES:
        out["more_packages"] = len(manifests) - MAX_PACKAGES
    return out


def _plain(value: object) -> str | None:
    """Skip `{ workspace = true }` style values."""
    return value if isinstance(value, str) else None


def _declared_version(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("workspace"):
            return "workspace"
        return str(value.get("version", value.get("path", value.get("git", ""))))
    return ""


def _lock_versions(repo: StackRepo, manifests: list[str]) -> dict[str, str]:
    for directory in dict.fromkeys([posixpath.dirname(manifests[0]), ""]):
        data = repo.read_toml(in_dir(directory, "Cargo.lock"))
        if data:
            versions: dict[str, set[str]] = {}
            for entry in data.get("package") or []:
                if isinstance(entry, dict) and "name" in entry and "version" in entry:
                    versions.setdefault(str(entry["name"]), set()).add(str(entry["version"]))
            # A crate locked at several versions has no single answer; keep the declared range.
            return {name: next(iter(vs)) for name, vs in versions.items() if len(vs) == 1}
    return {}
