"""``compass hook <event>``: the one entry point for Claude Code hooks.

Reads the hook's JSON from stdin and dispatches. It fails open: an internal
error is logged to ``.compass/logs/`` and the hook exits 0, so Compass never
makes Claude Code worse than stock. Deliberate gate decisions (M3/M4) will be
the only non-zero exits. Hooks only act in repos that have a ``.compass/``
directory, and never touch the network.

M1 handles the index triggers (IX-08): SessionStart runs a staleness check and
PostToolUse on Write/Edit re-indexes the edited file. The other events are
accepted and ignored until their milestones land.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

from compass import background
from compass.log import log_error
from compass.repo import Repo, find_initialized_repo

EVENTS = ("session-start", "prompt", "pre-edit", "post-edit", "stop")

# Budgets for work done inline; anything bigger moves to a background process.
INLINE_REFRESH_LIMIT = 100
SESSION_LOCK_WAIT_S = 0.5
POST_EDIT_LOCK_WAIT_S = 0.3

NOT_READY = (
    "[compass] The code map is being built in the background; "
    ".compass/map/ and index queries will be ready shortly."
)


def run(event: str, stdin: TextIO | None = None) -> int:
    repo: Repo | None = None
    try:
        raw = stdin.read() if stdin is not None else _read_stdin()
        try:
            payload: Any = json.loads(raw) if raw.strip() else {}
        except ValueError:
            payload = None
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
        repo = find_initialized_repo(cwd or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        if repo is None:
            return 0
        if not isinstance(payload, dict):
            log_error(repo.root, f"hook {event}", message="hook input is not a JSON object")
            return 0
        handler = HANDLERS.get(event)
        return handler(repo, payload) if handler else 0
    except Exception as exc:
        log_error(repo.root if repo else None, f"hook {event}", exc)
        return 0


def _read_stdin() -> str:
    """Hook input is UTF-8 JSON whatever the platform's locale; on Windows the
    text-mode stdin would decode it with the ANSI code page."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.read()
    return buffer.read().decode("utf-8-sig", errors="replace")


def refresh_or_hand_off(repo: Repo, lock_wait: float) -> bool:
    """Bring the index up to date: inline when the change is small, in a
    background process otherwise. True when a full build was started, which
    means index queries are not ready yet. Shared by SessionStart and the git
    hooks."""
    from compass.index.indexer import FullBuildNeeded, Indexer
    from compass.lock import LockTimeout

    indexer = Indexer(repo)
    stale = indexer.stale_paths()
    if stale is None:
        background.spawn(["-C", str(repo.root), "index"], repo.root)
        return True
    if not stale and indexer.map_intact():
        return False
    if len(stale) > INLINE_REFRESH_LIMIT:
        background.spawn(["-C", str(repo.root), "index"], repo.root)
        return False
    try:
        indexer.build(lock_timeout=lock_wait, allow_full=False)
    except LockTimeout:
        # The lock holder may be a single-file update; a background run waits
        # for it and then catches everything else up.
        background.spawn(["-C", str(repo.root), "index"], repo.root)
    except FullBuildNeeded:
        background.spawn(["-C", str(repo.root), "index"], repo.root)
        return True
    return False


def on_session_start(repo: Repo, payload: dict[str, Any]) -> int:
    if refresh_or_hand_off(repo, SESSION_LOCK_WAIT_S):
        print(NOT_READY)
    return 0


def on_post_edit(repo: Repo, payload: dict[str, Any]) -> int:
    from compass.index.indexer import FullBuildNeeded, Indexer
    from compass.lock import LockTimeout

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(target, str) or not target:
        return 0
    if not os.path.isabs(target):
        target = os.path.join(payload.get("cwd") or str(repo.root), target)
    rel = repo.relpath(target)
    if not rel or rel == ".compass" or rel.startswith(".compass/"):
        return 0
    try:
        Indexer(repo).update([rel], lock_timeout=POST_EDIT_LOCK_WAIT_S, allow_full=False)
    except LockTimeout:
        background.spawn(["-C", str(repo.root), "update", "--", rel], repo.root)
    except FullBuildNeeded:
        background.spawn(["-C", str(repo.root), "index"], repo.root)
    return 0


HANDLERS: dict[str, Callable[[Repo, dict[str, Any]], int]] = {
    "session-start": on_session_start,
    "post-edit": on_post_edit,
}
