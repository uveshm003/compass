"""What the M4 hooks do: UserPromptSubmit (the prompt gate and the context
pack), PreToolUse (the spec gate), and the session and task context they
share. ``compass.hooks`` only dispatches here.

The prompt hook runs on every prompt, so it is ordered cheapest first: a reply,
a question or a follow-up that names no code is logged and let through
without loading config or opening the index; only a prompt that starts a task,
or names something to look up, pays for more.

Answers go back as Claude Code reads them: exit 2 with stderr blocks (the
prompt in block mode, an edit under the spec gate); otherwise JSON on stdout,
``additionalContext`` for Claude and ``systemMessage`` for the developer.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from compass import state
from compass.gate import ParsedPrompt, parse
from compass.repo import Repo

BRIEF_CHARS = 2000
EXCERPT_CHARS = 300
STATE_LOCK_WAIT_S = 1.0
_CI_STACKS = frozenset({"github_actions", "azure_pipelines", "gitlab_ci"})
_STACK_COMMANDS = ("test", "lint", "typecheck", "build")


@dataclass
class Answer:
    code: int = 0
    stdout: str = ""
    stderr: str = ""


# -- UserPromptSubmit ----------------------------------------------------------------


def on_prompt(repo: Repo, payload: dict[str, Any]) -> Answer:
    text = payload.get("prompt") if isinstance(payload.get("prompt"), str) else ""
    session = _session(payload)
    snapshot = state.read(repo)
    parsed = parse(text)
    task = state.active_task(snapshot)
    fresh = task is not None and state.is_fresh(snapshot, task)
    quiet = state.quiet_turn(snapshot, session)
    pending = state.needs_approval(snapshot)
    idle = parsed.kind in ("reply", "question") or (parsed.kind in ("task", "command") and not fresh)
    if quiet and not pending and not parsed.candidates and idle:
        _log(repo, session, parsed.kind, "pass")
        return Answer()  # the common prompt: nothing to check, announce or look up

    from compass import review
    from compass.config import load_config
    from compass.gate import ask_first, checklist, missing_fields

    config = load_config(repo.root)
    gate = config.data["prompt_gate"]
    if gate["bypass_prefix"] != "!quick":
        parsed = parse(text, gate["bypass_prefix"])
    context: list[str] = []
    messages: list[str] = []
    notice = review.new_turn(repo, config.review, session)
    if notice:
        context.append(notice)
    if parsed.kind in ("empty", "command"):
        _log(repo, session, parsed.kind, "pass")
        return Answer(stdout=_json(context, messages))

    store = _open_store(repo)
    try:
        from compass.gate.pack import load_stack, resolve, stack_mentions

        if store is not None and parsed.candidates:
            resolve(store, parsed)
        stack = load_stack(repo)
        parsed.stack = stack_mentions(stack, parsed)
        snapshot = state.read(repo)
        task = state.active_task(snapshot)
        fresh = task is not None and state.is_fresh(snapshot, task)
        outcome, missing, drafted = "pass", [], False
        if parsed.kind == "bypass":
            outcome = "bypass"
            missing = missing_fields(parsed, config) if gate["enabled"] else []  # what it would have said, for tuning
            _mark_quick(repo, session)
        elif parsed.kind == "task" and fresh:
            if gate["enabled"] and gate["strictness"] != "off":
                missing = missing_fields(parsed, config)
            if missing and gate["strictness"] == "block":
                _log(repo, session, parsed.kind, "block", missing, parsed.text)
                if notice:
                    _unannounce(repo, session)  # the prompt never reaches Claude, so neither did the notice
                return Answer(code=2, stderr=checklist(missing))
            instructions = _define_task(repo, config, task, parsed, messages)
            drafted = bool(instructions)
            context += instructions
            if missing:
                outcome = "warn"
                context.append(ask_first(missing))
                messages.append(
                    f"[compass] The request does not state its {_names(missing)}, so Claude will ask."
                    " /compass:task has every field; a prompt starting with !quick skips the check."
                )
        waiting = state.needs_approval(state.read(repo))
        if waiting and parsed.kind != "bypass" and not drafted:
            context.append(_waiting(waiting))
        if config.data["context_pack"]["enabled"] and store is not None and parsed.kind != "reply":
            from compass.gate.pack import build

            pack = build(store, parsed, config.data["context_pack"]["token_budget"], stack)
            if pack:
                context.append(pack)
        _log(repo, session, parsed.kind, outcome, missing, parsed.text if outcome != "pass" else None)
        return Answer(stdout=_json(context, messages))
    finally:
        if store is not None:
            store.close()


def _define_task(repo: Repo, config, task: str, parsed: ParsedPrompt, messages: list[str]) -> list[str]:
    """The first request of a task becomes its brief and sets its size; a
    large task gets its spec draft (SG-01 to SG-03)."""
    from compass import spec

    size, reason = spec.classify(parsed, config) if config.data["spec_gate"]["enabled"] else ("small", "")
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        record = state.task_record(st, task)
        record["brief"] = parsed.text[:BRIEF_CHARS]
        record["size"], record["reason"] = size, reason or None
    if size != "large":
        return []
    spec.create(repo, task, parsed, reason)
    messages.append(
        f"[compass] {task} looks large ({reason}), so Claude drafts a spec first. Approve it with"
        f" /compass:approve {task}, or start a prompt with !quick to skip the spec for that turn."
    )
    return [spec_instructions(task, reason)]


def spec_instructions(task: str, reason: str) -> str:
    from compass.spec import spec_rel

    return (
        f"[compass] Task {task} is large ({reason}), so it needs an approved spec before any code changes."
        f" Compass created {spec_rel(task)} from the request: fill in its Goal, Scope, Non-goals and Acceptance,"
        " and list every open question as a checkbox under Open questions. Then stop: show the developer the"
        f" questions, and ask them to answer and run /compass:approve {task}. Until then Compass refuses edits"
        " to any other file."
    )


def _waiting(task: str) -> str:
    from compass.spec import spec_rel

    return (
        f"[compass] {task}'s spec ({spec_rel(task)}) is not approved yet: change nothing but the spec until"
        f" the developer runs /compass:approve {task}."
    )


# -- PreToolUse on Write/Edit: the spec gate (SG-04) -----------------------------------


def on_pre_edit(repo: Repo, payload: dict[str, Any]) -> Answer:
    snapshot = state.read(repo)
    task = state.needs_approval(snapshot)
    if task is None:
        return Answer()  # the usual case, decided from state.json alone
    session = _session(payload)
    record = snapshot["sessions"].get(session or "")
    if record and record["quick"]:
        return Answer()
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(target, str) or not target:
        return Answer()
    if not os.path.isabs(target):
        target = os.path.join(payload.get("cwd") or str(repo.root), target)
    rel = repo.relpath(target)
    from compass.spec import spec_rel

    if rel is None or rel == spec_rel(task):
        return Answer()  # outside the repo, or the spec being drafted
    from compass.config import load_config

    if not load_config(repo.root).data["spec_gate"]["enabled"]:
        return Answer()
    return Answer(
        code=2,
        stderr=(
            f"[compass] {task}'s spec is not approved yet, so {rel} cannot change. Finish {spec_rel(task)}"
            f" (answer or list its open questions), then ask the developer to run /compass:approve {task}."
            " The developer can also start a prompt with !quick to allow edits for one turn."
        ),
    )


# -- /compass:task and /compass:approve ------------------------------------------------


def start_task(repo: Repo, brief: str) -> str:
    """``compass task new --brief -``: a new task from a /compass:task brief."""
    from compass import review, spec
    from compass.config import load_config
    from compass.gate import TASK_TEMPLATE, ask_first, missing_fields

    parsed = parse(brief, "")
    if not parsed.text:
        return (
            "[compass] No brief given. Ask the developer for one in this shape, then start the task with it:\n"
            f"{TASK_TEMPLATE}"
        )
    config = load_config(repo.root)
    store = _open_store(repo)
    try:
        from compass.gate.pack import load_stack, resolve, stack_mentions

        if store is not None and parsed.candidates:
            resolve(store, parsed)
        parsed.stack = stack_mentions(load_stack(repo), parsed)
    finally:
        if store is not None:
            store.close()
    size, reason = spec.classify(parsed, config) if config.data["spec_gate"]["enabled"] else ("small", "")
    current = state.read(repo)
    previous = state.active_task(current)
    reuse = previous is not None and state.is_fresh(current, previous)
    taken = None if reuse else review.taken_ids(repo)  # the repo-wide scan only when an id is handed out
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        previous = state.active_task(st)
        if previous is not None and not state.is_fresh(st, previous):
            st["task"] = None  # the old task stays acceptable by its id
        task = state.ensure_task(st, taken)
        record = state.task_record(st, task)
        record["brief"] = parsed.text[:BRIEF_CHARS]
        record["size"], record["reason"] = size, reason or None
    lines = [f"[compass] Task {task} started from the brief ({size}{': ' + reason if reason else ''})."]
    if previous and previous != task and not state.is_fresh(current, previous):
        lines.append(f"The previous task, {previous}, stays open: /compass:accept {previous} when it is reviewed.")
    if size == "large":
        spec.create(repo, task, parsed, reason)
        lines.append(spec_instructions(task, reason))
    else:
        lines.append(f"Small task: go ahead, and tag each change with {review.tag('<kind>', task)}.")
    missing = missing_fields(parsed, config) if config.data["prompt_gate"]["enabled"] else []
    if missing:
        lines.append(ask_first(missing))
    return "\n".join(lines)


def approve_task(repo: Repo, task: str | None) -> tuple[int, str]:
    """``compass approve``: (exit code, message)."""
    from compass import spec

    current = state.read(repo)
    task = task or state.active_task(current)
    if not task:
        return 1, "no active task; pass a task id"
    path = spec.spec_path(repo, task)
    record = current["tasks"].get(task) or {}
    if not path.exists():
        if record.get("size") == "large":
            spec.create(repo, task, parse(record.get("brief") or "", ""), record.get("reason") or "")
            return 1, f"{task}'s spec was missing; Compass wrote a new draft at {spec.spec_rel(task)}. Review it, then approve again."
        return 0, f"{task} is a small task; it needs no spec."
    result = spec.approve(repo, task, spec.approver(repo))
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        task_record = state.task_record(st, task)
        task_record["approved"] = {"by": result["by"], "at": result["at"]}
        task_record["size"] = task_record.get("size") or "large"
    message = f"Approved {task}'s spec ({spec.spec_rel(task)}) as {result['by']}; Claude may now change code for it."
    questions = result["open_questions"]
    if questions:
        shown = "; ".join(questions[:5]) + (" …" if len(questions) > 5 else "")
        message += f" Note: {len(questions)} open question{'s are' if len(questions) != 1 else ' is'} still unticked: {shown}"
    return 0, message


def dry_run(repo: Repo, text: str) -> str:
    """``compass check-prompt``: what the prompt hook would decide, changing
    nothing. For tuning rules against real prompts from ``gate.jsonl``."""
    from compass import spec
    from compass.config import load_config
    from compass.gate import missing_fields

    config = load_config(repo.root)
    gate = config.data["prompt_gate"]
    parsed = parse(text, gate["bypass_prefix"])
    lines = [f"kind: {parsed.kind}"]
    if parsed.labels:
        lines.append("labels: " + ", ".join(f"{k}={v[:40]!r}" for k, v in sorted(parsed.labels.items())))
    if parsed.candidates:
        lines.append("names: " + ", ".join(f"{c.text} ({c.kind})" for c in parsed.candidates))
    store = _open_store(repo)
    try:
        from compass.gate.pack import load_stack, resolve, stack_mentions

        if store is not None and parsed.candidates:
            resolve(store, parsed)
        stack = load_stack(repo)
        parsed.stack = stack_mentions(stack, parsed)
        if parsed.kind in ("task", "bypass"):
            missing = missing_fields(parsed, config) if gate["enabled"] else []
            action = "pass" if not missing else ("block" if gate["strictness"] == "block" else gate["strictness"])
            lines.append(f"missing: {', '.join(missing) or 'nothing'} -> {action} (strictness {gate['strictness']};"
                         " only a prompt that starts a task is checked)")
            size, reason = spec.classify(parsed, config)
            lines.append(f"size: {size}" + (f" ({reason})" if reason else ""))
        if store is not None and parsed.kind != "reply":
            from compass.gate.pack import build

            pack = build(store, parsed, config.data["context_pack"]["token_budget"], stack)
            lines += ["context pack:", pack] if pack else ["context pack: (nothing to add)"]
        elif store is None:
            lines.append("context pack: (no index yet)")
    finally:
        if store is not None:
            store.close()
    return "\n".join(lines)


# -- SessionStart extras -----------------------------------------------------------------


def session_lines(repo: Repo) -> list[str]:
    """The stack, with installed versions (ST-02), and a pending approval."""
    lines = _stack_lines(repo)
    waiting = state.needs_approval(state.read(repo))
    if waiting:
        lines.append(_waiting(waiting))
    return lines


def _stack_lines(repo: Repo) -> list[str]:
    from compass.config import load_config
    from compass.stack import build_profile

    profile = build_profile(repo.root, load_config(repo.root))
    entries = []
    for name, result in sorted(profile.get("stacks", {}).items()):
        if name in _CI_STACKS:
            continue
        for entry in result.get("packages") or result.get("modules") or [result]:
            entries.append({"stack": name, **entry})
    cache = {"entries": [
        {"stack": e["stack"], "path": e.get("path"), "frameworks": e.get("frameworks") or {}, "tools": e.get("tools") or {}}
        for e in entries
    ]}
    try:
        (repo.compass_dir / "stack.json").write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    rendered = [_stack_entry(e) for e in entries]
    rendered = [line for line in rendered if line][:8]
    if not rendered:
        return []
    return ["[compass] Stack in use, with the versions installed (from manifests and lockfiles); use these APIs:",
            *rendered]


def _stack_entry(entry: dict[str, Any]) -> str | None:
    parts = []
    runtime = [f"{k} {v}" for k, v in (("python", entry.get("requires_python")), ("go", entry.get("go")),
                                        ("edition", entry.get("edition"))) if v]
    runtime += [f"{k} {v}" for k, v in sorted((entry.get("engines") or {}).items())]
    manager = entry.get("package_manager") or entry.get("runner")
    if manager or runtime:
        parts.append(", ".join([*([manager] if manager else []), *runtime]))
    for key in ("frameworks", "tools"):
        values = entry.get(key) or {}
        if values:
            parts.append(", ".join(f"{k} {v}" if v else k for k, v in sorted(values.items())))
    commands = entry.get("commands") if isinstance(entry.get("commands"), dict) else {}
    shown = [f"{role} `{commands[role]}`" for role in _STACK_COMMANDS if commands.get(role)]
    if shown:
        parts.append(", ".join(shown))
    if not parts:
        return None
    where = entry.get("path") or entry["stack"]
    label = f"{entry['stack']} {where}" + (f" ({entry['name']})" if entry.get("name") else "")
    return f"- {label}: " + "; ".join(parts)


# -- plumbing ----------------------------------------------------------------------------


def _session(payload: dict[str, Any]) -> str | None:
    session = payload.get("session_id")
    return session if isinstance(session, str) and session else None


def _open_store(repo: Repo):
    from compass.index.store import IndexUnavailable, Store

    try:
        store = Store.open(repo.db_path)
    except IndexUnavailable:
        return None
    try:
        if store.get_meta("fingerprint") is None:  # a first build still running
            store.close()
            return None
    except Exception:
        store.close()
        return None
    return store


def _unannounce(repo: Repo, session: str | None) -> None:
    if not session:
        return
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        state.session_record(st, session)["announced"] = None


def _mark_quick(repo: Repo, session: str | None) -> None:
    if not session:
        return
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        state.session_record(st, session)["quick"] = True


def _json(context: list[str], messages: list[str]) -> str:
    if not context and not messages:
        return ""
    out: dict[str, Any] = {}
    if messages:
        out["systemMessage"] = "\n".join(messages)
    if context:
        out["hookSpecificOutput"] = {"hookEventName": "UserPromptSubmit", "additionalContext": "\n\n".join(context)}
    return json.dumps(out)


def _names(missing: list[str]) -> str:
    from compass.gate import FIELD_TITLES

    names = [FIELD_TITLES.get(m, m).lower() for m in missing]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _log(repo: Repo, session: str | None, kind: str, outcome: str, missing=(), text: str | None = None) -> None:
    """One line per prompt in ``logs/gate.jsonl``: the bypass log that gate
    rules are tuned from (PG-03), and the bypass rate's denominator. Prompt
    text is kept only for the prompts the gate spoke up about, and cut short;
    the file stays on this machine (TM-02)."""
    row: dict[str, Any] = {"t": round(time.time(), 3), "session": session, "kind": kind, "outcome": outcome}
    if missing:
        row["missing"] = list(missing)
    if text:
        row["excerpt"] = text[:EXCERPT_CHARS]
    try:
        repo.logs_dir.mkdir(parents=True, exist_ok=True)
        with open(repo.logs_dir / "gate.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
