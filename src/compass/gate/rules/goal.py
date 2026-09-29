"""Goal: a ``Goal:`` label, a clause that opens with a task verb ("add …",
"run the tests and fix …"), or a symptom ("the login page breaks when …"),
whose goal is to make it stop."""

from __future__ import annotations

FIELD = "goal"


def check(prompt, config) -> list[str]:
    from compass.gate import SYMPTOM

    if prompt.labels.get("goal") or prompt.verbs or SYMPTOM.search(prompt.body):
        return []
    return [FIELD]
