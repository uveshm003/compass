"""The review output system (C7, RO-01 to RO-05), as the hooks and CLI use it.

- SessionStart hands Claude the rules: look code up through Compass, tag every
  change with an anchor for the active task, keep the final reply short and
  point at the manifest (RO-01, RO-02).
- PostToolUse records each file Claude edits, per task and per turn.
- Stop rewrites the task's manifest (RO-03) and, when files changed this turn
  carry no anchor, sends Claude back once to add them (RO-04).
- ``compass accept`` strips a task's anchors and archives its manifest; the
  git pre-commit hook refuses commits that still add anchors (RO-05).

Nothing here blocks except the Stop check, and that never twice in a row:
``stop_hook_active`` is set when Claude is already continuing because of a
Stop hook, and Compass also remembers its own last block per session.
"""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from compass import manifest, state
from compass.anchors import Anchor, is_binary, scan_file, scan_repo, shift_line, strip_file
from compass.config import Config, ReviewSettings
from compass.globs import compile_globs
from compass.lock import LockTimeout
from compass.repo import Repo

STATE_LOCK_WAIT_S = 1.0  # hooks hold the state lock for milliseconds
# Listed in the instructions and the Stop message, reviewer's reading order.
_KIND_HINTS = (
    ("review", "a judgment call the reviewer should check"),
    ("assume", "an assumption you did not verify"),
    ("todo", "something deliberately left undone"),
    ("change", "a mechanical change: renames, moves, boilerplate"),
)
TOOLS_RULE = (
    "- Code lookups: use the compass MCP tools (find_symbol, read_symbol, file_outline, map, callers_of,"
    " importers_of, tests_for, stack_profile) before Read, Grep or Glob; read a whole file only to edit it."
)


def tag(kind: str, task: str) -> str:
    return f"@ai:{kind} {task}"


def manifest_rel(task: str) -> str:
    return f".compass/changes/{task}.md"


def instructions(settings: ReviewSettings, task: str | None) -> str:
    """The session context Compass adds at SessionStart: the query-tools rule
    (Step 4) and, with review on, the anchor and reply rules (RO-01, RO-02)."""
    lines = ["[compass] Compass is active in this repository.", TOOLS_RULE]
    if settings.enabled and task:
        lines.append(
            f"- Review anchors, task {task}: mark every change with a comment in the file's own syntax,"
            " on the changed line or the line above it, one per logical change, with a short note on why:"
        )
        lines += [f"    {tag(kind, task)} — {hint}" for kind, hint in _KIND_HINTS]
        lines.append("  Files that cannot hold comments (JSON and the like) need no anchor.")
        lines.append(
            f"- When you finish, Compass writes the change manifest {manifest_rel(task)}. Keep the final reply"
            f" to at most {settings.reply_max_lines} lines: what changed, that manifest path, and risks or open"
            " questions. No code in chat; the manifest links every change."
        )
    return "\n".join(lines)


def announcement(task: str) -> str:
    kinds = ", ".join(kind for kind, _hint in _KIND_HINTS)
    return (
        f"[compass] Task {task} is now active: tag changes with {tag('<kind>', task)} ({kinds});"
        f" its manifest is {manifest_rel(task)}."
    )


def taken_ids(repo: Repo) -> set[str]:
    """Task ids in use outside state.json: anchors in files, archived manifests."""
    ids = {a.task for a in scan_repo(repo.root)}
    archive = repo.changes_dir / "archive"
    if archive.is_dir():
        ids |= {p.stem for p in archive.glob("*.md")}
    return ids


def session_task(repo: Repo, settings: ReviewSettings, session: str | None) -> str | None:
    """SessionStart: the active task (started if need be), marked as announced."""
    if not settings.enabled:
        return None
    current = state.read(repo)
    taken = None if state.active_task(current) else taken_ids(repo)
    try:
        with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
            task = state.ensure_task(st, taken)
            if session:
                state.session_record(st, session)["announced"] = task
    except LockTimeout:
        return state.active_task(current)  # the rules still go out, with what is known
    return task


def new_turn(repo: Repo, settings: ReviewSettings, session: str | None) -> str | None:
    """UserPromptSubmit: start the session's turn; returns an announcement
    when the active task changed since this session last heard of it."""
    if not settings.enabled:
        return None
    current = state.read(repo)
    if state.quiet_turn(current, session):
        return None  # nothing to change: skip the lock and the write
    task = state.active_task(current)
    taken = None if task else taken_ids(repo)
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        task = state.ensure_task(st, taken)
        if not session:
            return None
        record = state.session_record(st, session)
        record["turn"] = []
        record["blocked"] = False
        if record["announced"] == task:
            return None
        record["announced"] = task
    return announcement(task)


def record_edit(repo: Repo, settings: ReviewSettings, rel: str, session: str | None) -> None:
    """PostToolUse on Write/Edit: remember ``rel`` for the task and this turn."""
    if not settings.enabled:
        return
    current = state.read(repo)
    taken = None if state.active_task(current) else taken_ids(repo)
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        task = state.ensure_task(st, taken)
        state.touch(st, task, rel, session)


def on_stop(repo: Repo, config: Config, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Stop: refresh the manifest; the hook's JSON answer, or None to stay quiet."""
    settings = config.review
    if not settings.enabled:
        return None
    session = payload.get("session_id") if isinstance(payload.get("session_id"), str) else None
    current = state.read(repo)
    task = state.active_task(current)
    record = current["sessions"].get(session or "")
    turn = list(record["turn"]) if record else []
    if task is None or not turn:
        return None
    exempt = compile_globs(settings.anchor_exempt)
    missing = [
        rel for rel in turn
        if (repo.root / rel).is_file() and not exempt(rel) and not is_binary(repo.root / rel)
        and not scan_file(repo.root, rel, task)
    ]
    if missing:  # an edit that was undone again needs no anchor
        missing = manifest.net_changed(repo.root, missing)
    built = manifest.build(repo, task, state.touched(current, task), settings.anchor_exempt)
    manifest.write(repo, built)
    already_blocked = bool(payload.get("stop_hook_active")) or bool(record and record["blocked"])
    block = bool(missing) and settings.require_anchors and not already_blocked
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        record = state.session_record(st, session) if session else None
        if record is not None:
            record["blocked"] = block
            if not block:
                record["turn"] = []  # passed: the next Stop only looks at new edits
    if block:
        return {"decision": "block", "reason": missing_anchors_reason(task, missing)}
    return {"systemMessage": f"[compass] {task}: {built.summary()} → {manifest_rel(task)}"}


def missing_anchors_reason(task: str, missing: list[str]) -> str:
    shown = ", ".join(missing[:10]) + (f" and {len(missing) - 10} more" if len(missing) > 10 else "")
    kinds = ", ".join(f"{tag(kind, task)} ({hint.split(':')[0]})" for kind, hint in _KIND_HINTS)
    return (
        f"[compass] Changed this turn without a {task} anchor: {shown}. Add one comment per change in each"
        f" file's own comment syntax, on or above the changed line: {kinds}, each followed by a short note."
        f" Then finish your reply; Compass writes {manifest_rel(task)}."
    )


# -- accept (RO-05) -----------------------------------------------------------------


@dataclass
class Accepted:
    task: str
    removed: int
    files: list[str]
    archived: Path
    leftover: list[Anchor]


class NothingToAccept(Exception):
    pass


def accept(repo: Repo, config: Config, task: str | None = None) -> Accepted:
    """Strip ``task``'s anchors (default: the active task) and archive its
    manifest, with lines moved to where the tagged code now sits."""
    current = state.read(repo)
    task = task or state.active_task(current)
    if not task:
        raise NothingToAccept("no active task; pass a task id")
    touched = state.touched(current, task)
    before = manifest.build(repo, task, touched, config.review.anchor_exempt)
    if not before.anchors and not touched:
        known = state.active_task(current)
        hint = f" The active task is {known}." if known and known != task else ""
        raise NothingToAccept(f"{task} has no anchors and no recorded changes.{hint}")
    deleted: dict[str, list[int]] = {}
    removed = 0
    for rel in sorted({a.path for a in before.anchors}):
        result = strip_file(repo.root, rel, task)
        if result is not None:
            removed += result.removed
            deleted[rel] = result.deleted_lines
    after = manifest.build(repo, task, touched, config.review.anchor_exempt)
    counts = {f.path: f.anchors for f in before.files}
    archived = replace(
        after,
        accepted=True,
        anchors=[replace(a, line=shift_line(a.line, deleted.get(a.path, ()))) for a in before.anchors],
        files=[replace(f, anchors=counts.get(f.path, 0)) for f in after.files],
    )
    path = manifest.write(repo, archived, archived=True)
    for stale in (manifest.manifest_path(repo, task), manifest.manifest_path(repo, task).with_suffix(".json")):
        stale.unlink(missing_ok=True)
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        state.close_task(st, task)
    _reindex(repo, sorted(deleted))
    return Accepted(task, removed, sorted(deleted), path, after.anchors)


def _reindex(repo: Repo, paths: list[str]) -> None:
    """Stripped files changed on disk; bring the index along (fail open)."""
    if not paths or not repo.db_path.exists():
        return
    try:
        from compass.index.indexer import Indexer

        Indexer(repo).update(paths, lock_timeout=2.0, allow_full=False)
    except Exception:
        from compass import background

        background.spawn(["-C", str(repo.root), "update", "--", *paths], repo.root)


def relative_to_repo(repo: Repo, target: str, cwd: str | None) -> str | None:
    """Repo-relative path of a hook's ``file_path`` (absolute, or relative to
    ``cwd``); None outside the repo and for Compass's own state."""
    if not os.path.isabs(target):
        target = os.path.join(cwd or str(repo.root), target)
    rel = repo.relpath(target)
    if not rel or rel == ".compass" or rel.startswith(".compass/"):
        return None
    return posixpath.normpath(rel)
