"""Acceptance: an ``Accept when:`` label, or a clause that says what done
looks like: a ``should``/``must`` or ``when``/``if`` clause, a test, a
behaviour such as raising, returning or rejecting something, or a purpose
("so I can run it locally"). Some requests carry their own end state: a
mechanical one ("rename a to b", "bump x to 2.0", "delete the cache"), fixing
what a run reports ("fix the lint warnings", "implement the TODO"), or adding
one well-defined thing ("add a docstring to …", "add a --json flag"). In a
conversation already under way, "fix it" means the problem just discussed,
and done means it is gone."""

from __future__ import annotations

import re

FIELD = "acceptance"
_SIGNALS = re.compile(
    r"\b(should|must|so that|when|if|unless|until|expect(?:s|ed)?|ensure[sd]?|make sure|verify|pass(?:es|ing)?"
    r"|succeed(?:s)?|fail(?:s|ing)?|rais(?:e|es|ing)|return(?:s|ing)?|reject(?:s|ing)?|throw(?:s|ing)?"
    r"|error(?:s)?|tests?|instead of|rather than|no longer|at most|at least|within|without|after|before"
    r"|give up|rethrow(?:s|ing)?|timeout|cap(?:ped)? at|limit(?:ed)? to|up to"
    r"|warnings?|broken|crash(?:es|ed|ing)?|flaky|todos?|fixmes?|typos?|compil(?:e|es|ed|ing)|in order to"
    r"|prints?|printing|outputs?|displays?|shows?|never|always"  # "so jitter never exceeds the cap"
    r"|so\s+(?:that\s+)?(?:i|we|you|they|users?|people|it)\s+can)\b"
    r"|\d",  # a number is a concrete target: "5 attempts", "under 50 ms"
    re.I,
)
# The request itself is the acceptance criterion.
_SELF_EVIDENT = frozenset(
    "rename move delete remove revert bump format sort reorder extract inline dedupe deduplicate drop install"
    " uninstall upgrade downgrade".split()
)
# "<verb> … to/into <target>" names the end state.
_TO_VERBS = frozenset(
    "rename move convert change upgrade downgrade bump migrate switch set update port split refactor rewrite"
    " restructure simplify rework redesign".split()
)
# Fixing a problem the conversation already named: done is when it is gone.
_FIXES = frozenset("fix repair resolve address correct handle debug patch".split())
# Adding one well-defined thing: its being there is the end state.
_ARTIFACT = re.compile(
    r"\b(?:add|write|insert|append|include|put|create|generate)\s+(?:(?:a|an|the|some|missing|more|proper|short|brief"
    r"|new|basic)\s+){0,3}"
    r"(?:docstrings?|doc\s*comments?|comments?|type\s*hints?|type\s+annotations?|annotations?|flags?|options?"
    r"|arguments?|args?|parameters?|params?|fields?|columns?|log\s+(?:lines?|messages?|statements?)|badges?"
    r"|sections?|notes?|entr(?:y|ies)|headers?|licen[cs]e\s+headers?|copyright\s+headers?|links?|aliases?"
    r"|shebang|examples?|commit\s+messages?|release\s+notes|changelog\s+entr(?:y|ies)|pr\s+descriptions?"
    r"|pull\s+request\s+descriptions?|readme|\.?gitignore|\.?dockerignore|\.?editorconfig|dockerfile|makefile"
    r"|--[a-z][\w-]*)",
    re.I,
)


def check(prompt, config) -> list[str]:
    if prompt.labels.get("acceptance") or _SIGNALS.search(prompt.body) or _ARTIFACT.search(prompt.body):
        return []
    first = prompt.verbs[0] if prompt.verbs else ""
    if first in _SELF_EVIDENT:
        return []
    if first in _TO_VERBS and re.search(r"\b(?:to|into)\b", prompt.body, re.I):
        return []
    if prompt.followup and first in _FIXES:
        from compass.gate import REFERS_BACK

        if REFERS_BACK.search(prompt.body):
            return []
    return [FIELD]
