"""The spec gate (C3, SG-01 to SG-05): large tasks get a written spec, and
code stays untouched until the developer approves it.

- ``classify`` sorts a task into small or large from its brief, by the
  ``spec_gate.large_task_when`` heuristics (SG-01).
- A large task gets ``.compass/specs/<id>.md`` from the template below, with
  ``status: draft`` and an Open questions section that Claude fills in before
  anything is built (SG-02, SG-03). Specs are team documents; committing them
  is the team's choice.
- The PreToolUse hook refuses Write and Edit calls while the active task is
  large and unapproved, except on the spec itself (SG-04).
- ``approve`` records who approved and when, in the spec's front matter for
  people and in ``state.json`` for the gate (SG-05). Claude may edit the spec
  file while it drafts, so the front matter alone never counts as approval;
  and ``state.json`` is one of the files the gate keeps Claude away from.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from compass.repo import Repo

if TYPE_CHECKING:
    from compass.config import Config
    from compass.gate import ParsedPrompt

SPEC_DIR = "specs"

TEMPLATE = """\
---
task: {task}
status: draft
size: large
reason: {reason}
created: {created}
---

# {task}: {title}

<!-- Drafted by Claude for the developer to review. Code edits stay blocked
until the developer runs /compass:approve {task}. -->

## Goal

{goal}

## Scope

{scope}

## Non-goals

{non_goals}

## Acceptance

{acceptance}

## Open questions

<!-- One checkbox per question for the developer. Tick it once it is answered,
and write the answer after it. -->
- [ ]

## Plan

<!-- Optional: the steps, in order. -->
"""
_PLACEHOLDERS = {
    "goal": "<what should change, and why>",
    "scope": "<files, modules and behaviour in scope>",
    "non_goals": "<what this task will not do>",
    "acceptance": "<how the reviewer will know it is done: behaviour, tests>",
}


def classify(prompt: ParsedPrompt, config: Config) -> tuple[str, str]:
    """("large" | "small", why) from ``spec_gate.large_task_when`` (SG-01)."""
    rules = config.data["spec_gate"]["large_task_when"]
    text = prompt.text.lower()
    for keyword in rules["keywords"]:
        if re.search(rf"\b{re.escape(keyword.lower())}\w*", text):  # "refactor" also finds "refactoring"
            return "large", f'keyword "{keyword}"'
    paths = {c.text.rstrip("/") for c in prompt.candidates if _counts_as_a_file(c, prompt)}
    if len(paths) >= rules["files_mentioned_gte"]:
        return "large", f"{len(paths)} files mentioned"
    return "small", ""


def _counts_as_a_file(candidate, prompt: ParsedPrompt) -> bool:
    """A path the task will touch: one the code map knows, or a new file named
    with an extension. A directory named only as a filter ("under .compass/")
    or Compass's own state is not a file the task changes."""
    path = candidate.text.removeprefix("./")
    if candidate.kind != "path" or path == ".compass" or path.startswith(".compass/"):
        return False
    if candidate.text in prompt.resolved:
        return True
    tail = candidate.text.rstrip("/").rsplit("/", 1)[-1]
    return not candidate.text.endswith("/") and "." in tail.lstrip(".")


def spec_rel(task: str) -> str:
    return f".compass/{SPEC_DIR}/{task}.md"


def spec_path(repo: Repo, task: str) -> Path:
    return repo.compass_dir / SPEC_DIR / f"{task}.md"


def create(repo: Repo, task: str, prompt: ParsedPrompt, reason: str) -> Path:
    """Write the spec draft from the brief, unless one exists already."""
    path = spec_path(repo, task)
    if path.exists():
        return path
    values = {name: prompt.labels.get(name) or placeholder for name, placeholder in _PLACEHOLDERS.items()}
    if not prompt.labels.get("goal") and prompt.body:
        values["goal"] = prompt.body  # an unlabelled brief is its own goal
    title = values["goal"].split("\n", 1)[0].strip()
    title = title if len(title) <= 80 else title[:79] + "…"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        TEMPLATE.format(task=task, reason=reason or "marked large", created=_now(), title=title, **values),
        encoding="utf-8", newline="\n",
    )
    return path


def front_matter(text: str) -> dict[str, str]:
    """``key: value`` lines between the leading ``---`` fences."""
    if not text.startswith("---\n"):
        return {}
    head = text[4:].split("\n---", 1)[0]
    found = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            found[key.strip()] = value.strip()
    return found


def open_questions(text: str) -> list[str]:
    """Unticked questions in the spec's Open questions section."""
    section = re.search(r"(?ms)^## Open questions\s*$(.*?)(?=^## |\Z)", text)
    if not section:
        return []
    body = re.sub(r"<!--.*?-->", "", section.group(1), flags=re.S)
    return [m.group(1).strip() for m in re.finditer(r"(?m)^\s*[-*]\s+\[ \]\s*(\S.*)$", body)]


def approve(repo: Repo, task: str, by: str) -> dict[str, Any]:
    """Mark the spec approved in its front matter; the caller records the
    approval in ``state.json``. Returns what happened, for the message."""
    path = spec_path(repo, task)
    text = path.read_text(encoding="utf-8")
    at = _now()
    fields = {"status": "approved", "approved_by": by, "approved_at": at}
    if text.startswith("---\n") and "\n---" in text[4:]:
        head, rest = text[4:].split("\n---", 1)
        kept = [line for line in head.splitlines() if line.partition(":")[0].strip() not in fields]
        head = "\n".join([*kept, *(f"{k}: {v}" for k, v in fields.items())])
        text = f"---\n{head}\n---{rest}"
    else:
        text = "---\n" + "".join(f"{k}: {v}\n" for k, v in fields.items()) + "---\n\n" + text
    path.write_text(text, encoding="utf-8", newline="\n")
    return {"by": by, "at": at, "open_questions": open_questions(text)}


def approver(repo: Repo) -> str:
    """Who is approving: git's user.name, else the login name."""
    import getpass

    from compass.repo import run_git

    proc = run_git(repo.root, "config", "user.name")
    name = proc.stdout.decode("utf-8", "replace").strip() if proc.returncode == 0 else ""
    if name:
        return name
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
