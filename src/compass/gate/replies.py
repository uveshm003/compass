"""Plain replies that stand for a command (UX-04 to UX-06), so a developer
never needs to learn one: "approve" while a large task's plan waits, "accept"
once a change has been reviewed, and a request to commit while review tags
remain.

Only short messages made of the reply itself count ("approve", "ok, approved",
"I've reviewed it, accept and commit"), never a sentence that merely contains
the word, and never one with a negation or a question. A reply reaches Compass
through UserPromptSubmit, which carries only what the developer typed, so
Claude cannot approve or accept on its own (decision D14).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_LEAD = (
    r"(?:(?:yes|yep|yeah|ok(?:ay)?|sure|great|good|fine|perfect|thanks|thank\s+you|done|lgtm|looks\s+(?:good|great|fine|right)"
    r"|all\s+good|(?:i(?:'ve|\s+have)\s+)?reviewed(?:\s+(?:it|this|that|them|the\s+changes?))?|i\s+read\s+it)[\s,.!;:-]+)*"
)
_TARGET = r"(?:\s+(?:(?P<task>t\d+)|it|this|that|them|(?:the\s+)?(?:plan|spec|changes?|change)(?:\s+(?P<task2>t\d+))?))?"
_TAIL = (
    r"(?P<commit>[\s,.!;:-]+(?:and|then|&)?\s*commit(?:\s+(?:it|this|that|them|the\s+changes?|everything))?)?"
    r"(?:[\s,.!;:-]+(?:please|thanks|thank\s+you|go\s+ahead|proceed|carry\s+on|go\s+on))*[\s.!]*"
)
_REPLIES = {
    "approve": re.compile(rf"^{_LEAD}(?:i\s+)?(?:approve[ds]?|approval\s+given){_TARGET}{_TAIL}$", re.I),
    "accept": re.compile(rf"^{_LEAD}(?:i\s+)?(?:accept(?:ed|s)?){_TARGET}{_TAIL}$", re.I),
}
_NEGATION = re.compile(r"\?|\b(?:not|no|don'?t|dont|do\s+not|never|won'?t|wait|hold|later|until|unless|but)\b", re.I)
_COMMIT = re.compile(r"\bcommit(?:s|ted|ting)?\b", re.I)
MAX_WORDS = 12


@dataclass(frozen=True)
class Reply:
    command: str  # "approve" or "accept"
    task: str | None
    commit: bool  # "accept and commit"


def match(text: str) -> Reply | None:
    """The command a short reply stands for, or None."""
    cleaned = " ".join(text.strip().split())
    if not cleaned or len(cleaned.split()) > MAX_WORDS or _NEGATION.search(cleaned):
        return None
    for command, pattern in _REPLIES.items():
        m = pattern.match(cleaned)
        if m:
            task = m.group("task") or m.group("task2")
            return Reply(command, task.upper() if task else None, bool(m.group("commit")))
    return None


def asks_to_commit(text: str) -> bool:
    """A prompt that asks for a commit, for the reminder that review tags block one."""
    return bool(_COMMIT.search(text)) and not _NEGATION.search(text)
