"""Acceptance: an ``Accept when:`` label, or a clause that says what done
looks like: a ``should``/``must`` or ``when``/``if`` clause, a test, or a
behaviour such as raising, returning or rejecting something. Mechanical
requests carry their own end state ("rename a to b", "bump x to 2.0",
"delete the cache"), so they pass too."""

from __future__ import annotations

import re

FIELD = "acceptance"
_SIGNALS = re.compile(
    r"\b(should|must|so that|when|if|unless|until|expect(?:s|ed)?|ensure[sd]?|make sure|verify|pass(?:es|ing)?"
    r"|succeed(?:s)?|fail(?:s|ing)?|rais(?:e|es|ing)|return(?:s|ing)?|reject(?:s|ing)?|throw(?:s|ing)?"
    r"|error(?:s)?|tests?|instead of|rather than|no longer|at most|at least|within|without|after|before"
    r"|give up|rethrow(?:s|ing)?|timeout|cap(?:ped)? at|limit(?:ed)? to|up to)\b"
    r"|\d",  # a number is a concrete target: "5 attempts", "under 50 ms"
    re.I,
)
# The request itself is the acceptance criterion.
_SELF_EVIDENT = frozenset("rename move delete remove revert bump format sort reorder extract inline dedupe deduplicate drop".split())
# "<verb> … to/into <target>" names the end state.
_TO_VERBS = frozenset("rename move convert change upgrade downgrade bump migrate switch set update port split".split())


def check(prompt, config) -> list[str]:
    first = prompt.words[0] if prompt.words else ""
    if prompt.labels.get("acceptance") or _SIGNALS.search(prompt.body) or first in _SELF_EVIDENT:
        return []
    if first in _TO_VERBS and re.search(r"\b(?:to|into)\b", prompt.body, re.I):
        return []
    return [FIELD]
