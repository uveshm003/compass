"""Constraints: a ``Constraints:`` or ``Non-goals:`` label, or a limit in
words ("don't touch the API", "without new dependencies", "keep it
backwards compatible"). Not required by default."""

from __future__ import annotations

import re

FIELD = "constraints"
_SIGNALS = re.compile(
    r"\b(don'?t|do not|must not|mustn'?t|never|without|only|avoid|keep|no new|backwards?[- ]compatible"
    r"|compatib\w*|leave|unchanged|as is)\b",
    re.I,
)


def check(prompt, config) -> list[str]:
    if prompt.labels.get("constraints") or prompt.labels.get("non_goals") or _SIGNALS.search(prompt.body):
        return []
    return [FIELD]
