"""``.compass/state.json``: the active task and what each task touched.

Not committed; every clone numbers its own tasks. A task is the unit a review
manifest covers (RO-03). It starts explicitly with ``/compass:task`` or
implicitly the first time Compass needs an id; the prompt that first asks for
work becomes its brief, and sets its size (small or large, SG-01). It collects
every file Claude edits and ends with ``compass accept``. A large task carries
its spec approval here (SG-05), where the spec gate reads it.

Hooks run in parallel (one PostToolUse per tool call), so every change goes
through ``transaction``: a lock file plus an atomic replace. A reader never
sees half a file, and a state file that cannot be parsed is treated as empty
rather than stopping anything (fail open, NF-12).
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from compass.lock import file_lock
from compass.repo import Repo

STATE_VERSION = 1
MAX_SESSIONS = 20
_TASK_ID = re.compile(r"T(\d+)")


def empty() -> dict[str, Any]:
    return {"version": STATE_VERSION, "task": None, "next": 1, "tasks": {}, "sessions": {}, "accepted": []}


def read(repo: Repo) -> dict[str, Any]:
    """The current state, without taking the lock (a snapshot is enough to read)."""
    try:
        raw = json.loads(repo.state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty()
    return _normalised(raw)


@contextmanager
def transaction(repo: Repo, timeout: float = 2.0) -> Iterator[dict[str, Any]]:
    """Read, modify and write the state under the state lock."""
    repo.ensure_state_dir()
    with file_lock(repo.state_lock_path, timeout):
        state = read(repo)
        before = json.dumps(state, sort_keys=True)
        yield state
        if json.dumps(state, sort_keys=True) != before:
            tmp = repo.state_path.with_name(f"{repo.state_path.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(state, sort_keys=True, indent=1) + "\n", encoding="utf-8", newline="\n")
            _replace(tmp, repo.state_path)


def _replace(source, target, attempts: int = 25) -> None:
    """os.replace, retried: on Windows it fails while a lock-free reader has
    the target open."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.02)


def active_task(state: dict[str, Any]) -> str | None:
    task = state.get("task")
    return task if isinstance(task, str) and task else None


def ensure_task(state: dict[str, Any], taken: set[str] | None = None) -> str:
    """The active task id, starting a new task when there is none. ``taken``
    holds ids still in use elsewhere (anchors in files, archived manifests),
    so a lost state file never reuses one."""
    task = active_task(state)
    if task is not None:
        return task
    used = set(state["tasks"]) | set(state["accepted"]) | set(taken or ())
    numbers = [int(m.group(1)) for t in used if (m := _TASK_ID.fullmatch(t))]
    task = f"T{max([state['next'] - 1, *numbers]) + 1}"
    state["next"] = int(task[1:]) + 1
    state["task"] = task
    state["tasks"][task] = new_task_record()
    return task


def new_task_record() -> dict[str, Any]:
    return {"started": _now(), "touched": [], "brief": None, "size": None, "reason": None, "approved": None}


def task_record(state: dict[str, Any], task: str) -> dict[str, Any]:
    return state["tasks"].setdefault(task, new_task_record())


def is_fresh(state: dict[str, Any], task: str) -> bool:
    """Nothing asked for and nothing changed yet: the next request defines it."""
    record = state["tasks"].get(task) or {}
    return not record.get("brief") and not record.get("touched")


def needs_approval(state: dict[str, Any]) -> str | None:
    """The active task, when it is large and its spec is not approved yet."""
    task = active_task(state)
    record = state["tasks"].get(task) if task else None
    if record and record.get("size") == "large" and not record.get("approved"):
        return task
    return None


def touch(state: dict[str, Any], task: str, rel: str, session: str | None) -> None:
    """Record that ``rel`` changed in ``task`` (and this turn of ``session``)."""
    record = task_record(state, task)
    if rel not in record["touched"]:
        record["touched"] = sorted([*record["touched"], rel])
    if session:
        turn = session_record(state, session)["turn"]
        if rel not in turn:
            turn.append(rel)


def touched(state: dict[str, Any], task: str) -> list[str]:
    return list(state["tasks"].get(task, {}).get("touched", []))


def session_record(state: dict[str, Any], session: str) -> dict[str, Any]:
    sessions = state["sessions"]
    record = sessions.get(session)
    if record is None:
        record = sessions[session] = {"turn": [], "announced": None, "blocked": False, "quick": False}
        # Keep the newest sessions only; old ones are finished.
        for stale in sorted(sessions, key=lambda s: sessions[s].get("seen", 0))[:-MAX_SESSIONS]:
            del sessions[stale]
    record["seen"] = time.time()
    return record


def quiet_turn(state: dict[str, Any], session: str | None) -> bool:
    """True when a new prompt changes nothing: this session already knows the
    active task, its last turn left nothing behind and no block is pending."""
    record = state["sessions"].get(session) if session else None
    task = active_task(state)
    busy = record and (record["turn"] or record["blocked"] or record["quick"])
    return bool(record and task and record["announced"] == task and not busy)


def close_task(state: dict[str, Any], task: str) -> None:
    """``task`` is accepted: forget what it touched, never reuse its id."""
    state["tasks"].pop(task, None)
    if task not in state["accepted"]:
        state["accepted"].append(task)
    if state.get("task") == task:
        state["task"] = None
    for record in state["sessions"].values():
        record["turn"] = []


def _normalised(raw: Any) -> dict[str, Any]:
    """Whatever was on disk, coerced into the current shape."""
    state = empty()
    if not isinstance(raw, dict):
        return state
    if isinstance(raw.get("task"), str):
        state["task"] = raw["task"]
    if isinstance(raw.get("next"), int) and raw["next"] > 0:
        state["next"] = raw["next"]
    for task, record in (raw.get("tasks") or {}).items() if isinstance(raw.get("tasks"), dict) else ():
        if isinstance(task, str) and isinstance(record, dict):
            files = [f for f in record.get("touched", []) if isinstance(f, str)]
            approved = record.get("approved")
            state["tasks"][task] = {
                "started": str(record.get("started", "")),
                "touched": sorted(set(files)),
                "brief": record.get("brief") if isinstance(record.get("brief"), str) else None,
                "size": record.get("size") if record.get("size") in ("small", "large") else None,
                "reason": record.get("reason") if isinstance(record.get("reason"), str) else None,
                "approved": approved if isinstance(approved, dict) and approved.get("by") else None,
            }
    for session, record in (raw.get("sessions") or {}).items() if isinstance(raw.get("sessions"), dict) else ():
        if isinstance(session, str) and isinstance(record, dict):
            state["sessions"][session] = {
                "turn": [f for f in record.get("turn", []) if isinstance(f, str)],
                "announced": record.get("announced") if isinstance(record.get("announced"), str) else None,
                "blocked": bool(record.get("blocked", False)),
                "quick": bool(record.get("quick", False)),
                "seen": record.get("seen", 0) if isinstance(record.get("seen"), (int, float)) else 0,
            }
    accepted = raw.get("accepted")
    state["accepted"] = [t for t in accepted if isinstance(t, str)] if isinstance(accepted, list) else []
    if state["task"] is not None and state["task"] not in state["tasks"]:
        state["tasks"][state["task"]] = new_task_record()
    return state


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
