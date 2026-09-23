"""Shared by the CI detectors (github_actions, azure_pipelines, gitlab_ci).

Keeps the commands a pipeline runs to build, test and lint, and drops setup
steps and shell plumbing. Not a detector itself: modules starting with ``_``
are skipped by discovery.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_COMMANDS = 15
MAX_FILES = 20

_INTERESTING = re.compile(
    r"\b(test|tests|lint|build|check|vet|clippy|pytest|jest|vitest|tox|nox|fmt|format|typecheck|"
    r"mypy|pyright|ruff|eslint|tsc|msbuild|vstest)\b"
    r"|\b(go|cargo|npm|pnpm|yarn|bun|make|gradle|gradlew|mvn|dotnet|swift|flutter)\s"
)
_SKIP = re.compile(
    r"^(echo|cd|export|set|if|fi|then|else|for|done|mkdir|cp|mv|rm|cat|ls|sudo|apt(-get)?|brew|curl|wget)\b"
    # Setup steps, not the build, test or lint commands the profile is after.
    r"|^(npm|pnpm|yarn|bun)\s+(ci|install|i)\b|^(python3?\s+-m\s+)?pip3?\s+install\b|^uv\s+(sync|pip\s+install)\b"
    r"|^go\s+mod\s+download\b|^cargo\s+fetch\b|^(dotnet|nuget)\s+restore\b"
)


def commands(lines: Iterable[str]) -> list[str]:
    """The build, test and lint commands among a pipeline's script lines."""
    kept: list[str] = []
    for line in lines:
        line = line.strip()
        if (
            line
            and not line.startswith(("#", "REM ", "::"))
            and not _SKIP.match(line)
            and _INTERESTING.search(line)
            and line not in kept
        ):
            kept.append(line)
    return kept[:MAX_COMMANDS]


def by_depth(paths: Iterable[str]) -> list[str]:
    return sorted(set(paths), key=lambda p: (p.count("/"), p))
