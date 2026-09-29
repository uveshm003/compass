"""Scope: a ``Scope:`` label, a path, anything in backticks, a code name
(``StockItem``, ``parse_config``, ``Retry()``), or one of the project's own
frameworks or tools by name ("upgrade react"). A resolved name is best, but an
unresolved one still says where to look, so it counts too.

So does anything Claude can find on its own: a symptom or the failures of a
run ("fix the failing tests", "fix the type errors"), a well-known file ("the
README"), a command-line flag, the working tree ("these changes"), the whole
repository, the dependencies. In a conversation already under way, "it",
"this" and "that" point at what was just discussed."""

from __future__ import annotations

import re

FIELD = "scope"
_SELF_LOCATING = re.compile(
    r"(?:failing|failed|broken|flaky|red)\s+(?:\w+\s+)?(?:tests?|specs?|builds?|checks?|jobs?|pipelines?|ci)\b"
    r"|\b(?:tests?|builds?|ci|pipeline|lint(?:er|ing)?|type[- ]?check(?:er|ing)?|mypy|pyright|tsc|eslint|ruff"
    r"|flake8|clippy|compil(?:e|er|ation)|type|syntax|import|runtime|deprecation)\s+(?:failures?|errors?|warnings?"
    r"|issues?|problems?|output)\b"
    r"|\bwhat(?:ever)?\s+(?:fails|failed|is\s+failing|breaks|broke)\b"
    r"|\bthe\s+(?:tests?|test\s+suite|suite|build|linter|type\s*checker)\b"
    r"|\b(?:this|that|the)\s+(?:error|exception|traceback|stack\s*trace|crash|warning|failure)s?\b"
    r"(?!\s+(?:handling|handlers?|messages?|codes?|types?|classes?|reporting|pages?|paths?|cases?|states?|logging))"
    r"|\b(?:todos?|fixmes?)\b"
    r"|\b(?:readme|changelog|licen[cs]e|contributing|dockerfile|makefile|jenkinsfile|procfile|gemfile|rakefile"
    r"|codeowners|gitignore|dockerignore|editorconfig|pyproject|tsconfig|docker-compose|vagrantfile)\b"
    r"|(?<![\w-])--[a-z][\w-]+"
    r"|\b(?:this|these|those|the|my|our|current)\s+(?:branch|diff|changes|commits?|pr|pull\s+request|merge\s+request"
    r"|working\s+tree|stash)\b|\b(?:uncommitted|staged|unstaged|local)\s+changes\b"
    r"|\b(?:the\s+(?:whole|entire)\s+(?:repo(?:sitory)?|project|codebase)|(?:this|the)\s+(?:repo(?:sitory)?|project"
    r"|codebase|code)|all\s+(?:the\s+)?code|everywhere|every\s+file|all\s+(?:the\s+)?files"
    r"|across\s+the\s+(?:repo|codebase|project))\b"
    r"|\b(?:unused|all\s+the|all)\s+(?:imports?|variables?|code|functions?|dependencies)\b|\bdead\s+code\b"
    r"|\b(?:to|from)\s+(?:v?\d[\w.:-]*|\"[^\"]+\"|'[^']+')"  # a concrete value to find: "the port to 8080", "to 0.115"
    r"|\b(?:dependencies|deps|requirements|lock\s*file|lockfile|node_modules|virtualenv|venv)\b"
    r"|\bversion(?:\s+number)?\b",
    re.I,
)


def check(prompt, config) -> list[str]:
    from compass.gate import REFERS_BACK, SYMPTOM

    if prompt.labels.get("scope") or prompt.candidates or prompt.stack:
        return []
    if SYMPTOM.search(prompt.body) or _SELF_LOCATING.search(prompt.body):
        return []
    if prompt.followup and REFERS_BACK.search(prompt.body):
        return []
    return [FIELD]
