"""Goal: a ``Goal:`` label, or a request that opens with a verb ("add …", "fix …")."""

from __future__ import annotations

FIELD = "goal"


def check(prompt, config) -> list[str]:
    from compass.gate import TASK_VERBS

    if prompt.labels.get("goal"):
        return []
    first = prompt.words[0] if prompt.words else ""
    return [] if first in TASK_VERBS else [FIELD]
