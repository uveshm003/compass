"""Node / TypeScript: package.json plus npm, pnpm or yarn lockfiles."""

from __future__ import annotations

import posixpath
import re

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir, pick_versions, run_in

FRAMEWORKS = {
    "@angular/core", "@apollo/server", "@nestjs/core", "@prisma/client", "@remix-run/react",
    "@reduxjs/toolkit", "@sveltejs/kit", "@tanstack/react-query", "astro", "drizzle-orm",
    "electron", "expo", "express", "fastify", "graphql", "hono", "koa", "mongoose", "next",
    "nuxt", "preact", "prisma", "react", "react-native", "redux", "rxjs", "sequelize",
    "socket.io", "solid-js", "svelte", "tailwindcss", "three", "typeorm", "vue", "zod", "zustand",
}
TOOLS = {
    "@biomejs/biome", "@playwright/test", "cypress", "esbuild", "eslint", "jest", "mocha", "nx",
    "prettier", "rollup", "storybook", "tsx", "turbo", "typescript", "vite", "vitest", "webpack",
}
ROLES = {
    "build": ["build"],
    "test": ["test", "test:unit"],
    "lint": ["lint"],
    "typecheck": ["typecheck", "type-check", "check-types", "tsc"],
    "format": ["format", "fmt"],
    "dev": ["dev", "start"],
}
LOCKFILES = [
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lock", "bun"),
    ("bun.lockb", "bun"),
    ("package-lock.json", "npm"),
    ("npm-shrinkwrap.json", "npm"),
]
_PLACEHOLDER_TEST = re.compile(r"no test specified", re.IGNORECASE)


def detect(repo: StackRepo) -> dict | None:
    manifests = repo.find("package.json")
    if not manifests:
        return None
    packages = []
    lock_cache: dict[str, dict[tuple[str, str], str]] = {}
    for manifest in manifests[:MAX_PACKAGES]:
        data = repo.read_json(manifest)
        if not isinstance(data, dict):
            continue
        base = posixpath.dirname(manifest)
        manager, lockfile = _package_manager(repo, base, data)
        if lockfile and lockfile not in lock_cache:
            lock_cache[lockfile] = _lock_versions(repo, lockfile)
        resolved = lock_cache.get(lockfile, {}) if lockfile else {}
        importer = _importer_path(base, lockfile)
        declared = {}
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            if isinstance(data.get(section), dict):
                for name, spec in data[section].items():
                    declared.setdefault(name, str(spec))
        versions = {name: _resolve(resolved, name, spec, importer) for name, spec in declared.items()}
        typescript = "typescript" in declared or repo.exists(in_dir(base, "tsconfig.json"))
        packages.append(
            compact(
                {
                    "path": manifest,
                    "name": data.get("name"),
                    "language": "typescript" if typescript else "javascript",
                    "package_manager": manager,
                    "lockfile": lockfile,
                    "engines": data.get("engines") if isinstance(data.get("engines"), dict) else None,
                    "frameworks": pick_versions(versions, FRAMEWORKS),
                    "tools": pick_versions(versions, TOOLS),
                    "dependencies": len(declared),
                    "workspaces": _workspaces(data),
                    "commands": _commands(data.get("scripts"), manager, base),
                }
            )
        )
    if not packages:
        return None
    out: dict = {"packages": packages}
    if len(manifests) > MAX_PACKAGES:
        out["more_packages"] = len(manifests) - MAX_PACKAGES
    return out


def _package_manager(repo: StackRepo, base: str, data: dict) -> tuple[str, str | None]:
    declared = data.get("packageManager")
    declared_name = declared.split("@", 1)[0] if isinstance(declared, str) else None
    for directory in dict.fromkeys([base, ""]):  # the package, then the workspace root
        for filename, manager in LOCKFILES:
            path = in_dir(directory, filename)
            if repo.exists(path):
                return declared_name or manager, path
    return declared_name or "npm", None


def _importer_path(base: str, lockfile: str | None) -> str:
    """The package's key in a workspace lockfile ('.' for the lockfile's own dir)."""
    if not lockfile:
        return "."
    lock_dir = posixpath.dirname(lockfile)
    if base == lock_dir:
        return "."
    return posixpath.relpath(base or ".", lock_dir or ".")


def _commands(scripts: object, manager: str, base: str) -> dict[str, str]:
    if not isinstance(scripts, dict):
        return {}
    out = {}
    for role, names in ROLES.items():
        for name in names:
            body = scripts.get(name)
            if not isinstance(body, str) or (name == "test" and _PLACEHOLDER_TEST.search(body)):
                continue
            if manager == "npm":
                command = "npm test" if name == "test" else f"npm run {name}"
            elif manager == "bun":
                command = f"bun run {name}"
            else:
                command = f"{manager} {name}"
            out[role] = run_in(base, command)
            break
    return out


def _workspaces(data: dict) -> list[str]:
    ws = data.get("workspaces")
    if isinstance(ws, dict):
        ws = ws.get("packages")
    return [str(w) for w in ws] if isinstance(ws, list) else []


# -- lockfiles ---------------------------------------------------------------
# Each parser returns {(name, importer_or_range): version}; see _resolve.


def _lock_versions(repo: StackRepo, lockfile: str) -> dict[tuple[str, str], str]:
    name = posixpath.basename(lockfile)
    try:
        if name in ("package-lock.json", "npm-shrinkwrap.json"):
            return _npm_lock(repo.read_json(lockfile))
        if name == "pnpm-lock.yaml":
            return _pnpm_lock(repo.read_yaml(lockfile))
        if name == "yarn.lock":
            return _yarn_lock(repo.read_text(lockfile) or "")
    except (AttributeError, TypeError, ValueError):
        return {}
    return {}


def _npm_lock(data: object) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    if not isinstance(data, dict):
        return out
    for key, entry in (data.get("packages") or {}).items():
        if not isinstance(entry, dict) or "version" not in entry or "node_modules/" not in key:
            continue
        owner, _, name = key.rpartition("node_modules/")
        importer = owner.rstrip("/") or "."
        out[(name, importer)] = str(entry["version"])
        out.setdefault((name, "*"), str(entry["version"]))
    for name, entry in (data.get("dependencies") or {}).items():  # lockfile v1
        if isinstance(entry, dict) and "version" in entry:
            out.setdefault((name, "."), str(entry["version"]))
    return out


def _pnpm_lock(data: object) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    if not isinstance(data, dict):
        return out
    importers = data.get("importers") or {".": data}  # pnpm < 7 kept the root inline
    for importer, sections in importers.items():
        if not isinstance(sections, dict):
            continue
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            for name, entry in (sections.get(section) or {}).items():
                version = entry.get("version") if isinstance(entry, dict) else entry
                if version is not None:
                    out[(name, str(importer))] = re.sub(r"\(.*$", "", str(version))
    return out


def _yarn_lock(text: str) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    keys: list[str] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            keys = [k.strip().strip('"') for k in line.rstrip()[:-1].split(",")]
            continue
        m = re.match(r'^\s+version:?\s+"?([^"\s]+)"?', line)
        if m and keys:
            for key in keys:
                name, _, spec = key.rpartition("@")
                if name:
                    out[(name, spec.removeprefix("npm:"))] = m.group(1)
            keys = []
    return out


def _resolve(lock: dict[tuple[str, str], str], name: str, spec: str, importer: str) -> str:
    """Installed version from the lockfile, else the range declared in package.json."""
    for key in ((name, importer), (name, spec), (name, spec.removeprefix("npm:")), (name, "*")):
        if key in lock:
            return lock[key]
    return spec
