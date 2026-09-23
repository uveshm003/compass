"""Makefile targets that name the repo's own build, test and lint commands."""

from __future__ import annotations

import re

from compass.stack import StackRepo, compact

ROLES = {
    "build": ["build", "all"],
    "test": ["test", "tests", "check"],
    "lint": ["lint", "vet"],
    "format": ["fmt", "format"],
    "typecheck": ["typecheck", "types"],
    "ci": ["ci"],
}
_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.\-/]*)\s*:(?![=:])")


def detect(repo: StackRepo) -> dict | None:
    path = next((p for p in ("Makefile", "makefile", "GNUmakefile") if repo.exists(p)), None)
    if path is None:
        return None
    targets = set()
    for line in (repo.read_text(path) or "").splitlines():
        m = _TARGET.match(line)
        if m and not m.group(1).startswith("."):
            targets.add(m.group(1))
    commands = {}
    for role, names in ROLES.items():
        name = next((n for n in names if n in targets), None)
        if name:
            commands[role] = f"make {name}"
    return compact({"path": path, "targets": len(targets), "commands": commands}) if targets else None
