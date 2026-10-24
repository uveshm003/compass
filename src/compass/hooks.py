"""``compass hook <event>``: the one entry point for Claude Code hooks.

Reads the hook's JSON from stdin and dispatches. It fails open: an internal
error is logged to ``.compass/logs/`` and the hook exits 0, so Compass never
makes Claude Code worse than stock. Deliberate decisions are the only way a
hook holds anything up: the Stop hook's request for missing anchors is a JSON
answer on exit 0, and M4's gates will add the rest. Hooks only act in repos
that have a ``.compass/`` directory, and never touch the network.

Handled so far:

- SessionStart: the index staleness check (IX-08), then the session context:
  the query-tools rule and, with review on, the anchor and reply rules for the
  active task (RO-01, RO-02).
- UserPromptSubmit: starts the session's turn and announces a new task id.
- PostToolUse on Write/Edit: re-indexes the edited file and records it for
  the task's manifest.
- Stop: rewrites the manifest and asks once for missing anchors (RO-03, RO-04).
- UserPromptSubmit also runs the prompt gate and adds the context pack, and
  PreToolUse on Write/Edit is the spec gate (M4, in ``compass.gate.hook``).
- PreToolUse on the Agent tool notes which files a scaffold delegation names,
  and SubagentStop holds each Compass subagent to its output contract (M5, in
  ``compass.delegation``).
- Stop and SubagentStop also append a telemetry row for the turn or the
  subagent (M6, in ``compass.telemetry``).
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

EVENTS = ("session-start", "prompt", "pre-edit", "post-edit", "stop", "delegate", "subagent-stop")

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
        start = cwd or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        repo = find_initialized_repo(start)
        if repo is None:
            if event == "session-start" and isinstance(payload, dict) and payload.get("source", "startup") == "startup":
                offer = setup_offer(start)
                if offer:
                    print(offer)
            return 0
        if not isinstance(payload, dict):
            log_error(repo.root, f"hook {event}", message="hook input is not a JSON object")
            return 0
        handler = HANDLERS.get(event)
        return handler(repo, payload) if handler else 0
    except Exception as exc:
        log_error(repo.root if repo else None, f"hook {event}", exc)
        return 0


SETUP_OFFER = (
    "[compass] Compass is installed but not switched on in this repository. In your first reply, add one short line"
    " offering it, for example: \"Compass isn't set up in this repo yet; say 'set up Compass' and I'll build its code"
    " map, so I find code faster and spend fewer tokens.\" Offer it this once only. If the developer agrees, run"
    " /compass:setup (or `compass init --modules essentials`). If they decline or ignore it, don't mention it again."
)
OFFERED_MARKER = "compass-offered"


def setup_offer(start: str | os.PathLike[str]) -> str | None:
    """SessionStart in a git repository without ``.compass/`` (UX-01, decision
    D15): offer Compass once per repository. The marker lives inside the git
    directory, so it never shows up in the working tree; no subprocess."""
    from pathlib import Path

    here = Path(os.path.realpath(start))
    for candidate in (here, *here.parents):
        dot_git = candidate / ".git"
        if dot_git.exists():
            break
    else:
        return None
    if candidate == Path.home():
        return None  # a dotfiles repository, not a project
    git_dir = dot_git
    if dot_git.is_file():  # a worktree or submodule: "gitdir: <path>"
        line = dot_git.read_text(encoding="utf-8", errors="replace").strip()
        if not line.startswith("gitdir:"):
            return None
        git_dir = (candidate / line[len("gitdir:"):].strip()).resolve()
    marker = git_dir / OFFERED_MARKER
    if marker.exists():
        return None
    try:
        marker.write_text("Compass offered itself here once; delete this file to be asked again.\n", encoding="utf-8")
    except OSError:
        return None  # if it cannot be remembered, it is not offered: never every session
    return SETUP_OFFER


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
    notices = []
    try:
        if refresh_or_hand_off(repo, SESSION_LOCK_WAIT_S):
            notices.append(NOT_READY)
    except Exception as exc:  # the context below still matters
        log_error(repo.root, "hook session-start refresh", exc)
    from compass import review

    config = _config(repo)
    try:
        task = review.session_task(repo, config.review, _session(payload))
    except Exception as exc:  # the query-tools rule still goes out
        log_error(repo.root, "hook session-start task", exc)
        task = None
    extra: list[str] = []
    try:
        from compass.gate.hook import conversation_cleared, session_lines

        if payload.get("source") == "clear":
            conversation_cleared(repo, _session(payload))
        extra = session_lines(repo, config)
    except Exception as exc:
        log_error(repo.root, "hook session-start stack", exc)
    if config.delegation.enabled:
        from compass.delegation import rules

        local = False
        if config.local_llm.enabled:  # urllib only when there may be a model to ask
            from compass import llm

            local = llm.available(repo, config)
        from compass.install import install_mode

        mode = install_mode(repo.root)
        extra = [*rules(config.delegation.digest_threshold_lines, local, mode), *extra]
    try:
        from compass import telemetry

        telemetry.on_session_start(repo, config, payload)
    except Exception as exc:
        log_error(repo.root, "hook session-start telemetry", exc)
    tools = config.query.enabled
    lines = [*review.instructions(config.review, task, tools), *extra, *(notices if tools else [])]
    if lines:  # with every module off (a telemetry-only baseline) Claude gets nothing extra
        print("\n".join([review.SESSION_HEADER, *lines]))
    return 0


def on_prompt(repo: Repo, payload: dict[str, Any]) -> int:
    from compass.gate.hook import on_prompt as gate

    return _answer(gate(repo, payload))


def on_pre_edit(repo: Repo, payload: dict[str, Any]) -> int:
    from compass.gate.hook import on_pre_edit as gate

    return _answer(gate(repo, payload))


def _answer(answer) -> int:
    if answer.stdout:
        print(answer.stdout)
    if answer.stderr:
        print(answer.stderr, file=sys.stderr)
    return answer.code


def on_post_edit(repo: Repo, payload: dict[str, Any]) -> int:
    from compass import review
    from compass.index.indexer import FullBuildNeeded, Indexer
    from compass.lock import LockTimeout

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(target, str) or not target:
        return 0
    rel = review.relative_to_repo(repo, target, payload.get("cwd"))
    if rel is None:
        return 0
    agent_id = payload.get("agent_id") if isinstance(payload.get("agent_id"), str) else None
    from compass.delegation import canonical_agent

    agent_type = canonical_agent(payload.get("agent_type"))
    try:
        review.record_edit(repo, _config(repo).review, rel, _session(payload), agent_id, agent_type)
    except Exception as exc:  # the re-index below still matters
        log_error(repo.root, "hook post-edit record", exc)
    try:
        Indexer(repo).update([rel], lock_timeout=POST_EDIT_LOCK_WAIT_S, allow_full=False)
    except LockTimeout:
        background.spawn(["-C", str(repo.root), "update", "--", rel], repo.root)
    except FullBuildNeeded:
        background.spawn(["-C", str(repo.root), "index"], repo.root)
    return 0


def on_stop(repo: Repo, payload: dict[str, Any]) -> int:
    from compass import review

    config = _config(repo)
    _telemetry(repo, config, payload, "on_stop")  # first: a review failure must not lose the turn's row
    answer = review.on_stop(repo, config, payload)
    if answer:
        print(json.dumps(answer))  # ASCII escapes: the answer is read whatever the console code page
    return 0


def on_delegate(repo: Repo, payload: dict[str, Any]) -> int:
    from compass.delegation import on_delegate as note

    note(repo, payload)
    return 0


def on_subagent_stop(repo: Repo, payload: dict[str, Any]) -> int:
    from compass.delegation import on_subagent_stop as check

    config = _config(repo)
    _telemetry(repo, config, payload, "on_subagent_stop")
    answer = check(repo, config, payload)
    if answer:
        print(json.dumps(answer))
    return 0


def _telemetry(repo: Repo, config, payload: dict[str, Any], handler: str) -> None:
    """Record the turn's cost (TM-01); a failure here never changes the hook's answer."""
    try:
        from compass import telemetry

        getattr(telemetry, handler)(repo, config, payload)
    except Exception as exc:
        log_error(repo.root, f"hook telemetry {handler}", exc)


def _config(repo: Repo):
    from compass.config import load_config

    return load_config(repo.root)


def _session(payload: dict[str, Any]) -> str | None:
    session = payload.get("session_id")
    return session if isinstance(session, str) and session else None


HANDLERS: dict[str, Callable[[Repo, dict[str, Any]], int]] = {
    "session-start": on_session_start,
    "prompt": on_prompt,
    "pre-edit": on_pre_edit,
    "post-edit": on_post_edit,
    "stop": on_stop,
    "delegate": on_delegate,
    "subagent-stop": on_subagent_stop,
}
