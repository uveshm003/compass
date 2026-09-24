"""Telemetry (C9, TM-01, TM-02): what each turn cost, read from Claude Code's
own transcript and kept as one JSON row per turn in ``.compass/telemetry.jsonl``.

The Stop hook reads the session transcript from where the last Stop left off
and appends a ``turn`` row: tokens per model (input, output, cache writes and
cache reads), tool calls by name, prompts, active time, and the characters of
context Compass itself injected. SubagentStop does the same for the
subagent's own transcript, as a ``subagent`` row. Both carry the active task
id and its tags, so ``compass report`` can roll turns up into tasks and
compare tasks run with Compass on and off (TM-03).

Transcripts write one line per content block, and each line of an API message
repeats its ``usage``, with output tokens still growing on the early lines.
A message counts once, at the largest value seen for each field. Active time
leaves out time spent waiting for the developer: the gaps before each prompt
they type. Rows hold counts, timings and task tags only; never prompts, code,
paths or file contents. They stay on this machine unless ``telemetry.export``
names a file to copy them to (TM-02).
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from compass.repo import Repo

ROW_VERSION = 1
ROWS_NAME = "telemetry.jsonl"
OFFSETS_NAME = "telemetry-offsets.json"
LOCK_NAME = "telemetry.lock"
LOCK_WAIT_S = 2.0
MAX_READ_BYTES = 32 * 1024 * 1024  # an unread stretch bigger than this is skipped, not parsed in a hook
RESUME_TAIL_BYTES = 1024 * 1024
SETTLE_WAIT_S = 1.5  # how long a hook waits for the transcript to catch up (it usually takes ~0.1 s)
SETTLE_POLL_S = 0.05
MAX_TRACKED = 200  # sessions and subagents whose read positions are kept
USAGE_FIELDS = (
    ("input", "input_tokens"),
    ("output", "output_tokens"),
    ("cache_creation", "cache_creation_input_tokens"),
    ("cache_read", "cache_read_input_tokens"),
)
# Compass counts as on for a task when any of these is (local_llm is optional extra).
MODULES = ("query", "prompt_gate", "context_pack", "spec_gate", "review", "delegation")
READ_TOOLS = ("Read", "Grep", "Glob")
CATEGORIES = {  # the benchmark's task mix, and the words developers use for it
    "explain": ("explain", "locate", "locate and explain", "question", "understand"),
    "bug_fix": ("bug fix", "bugfix", "bug", "fix"),
    "feature": ("feature", "small feature", "new feature"),
    "refactor": ("refactor", "refactoring", "cross module refactor"),
    "tests": ("tests", "test", "write tests", "testing"),
    "triage": ("triage", "failing tests", "logs", "triage failing tests or logs"),
}
_SYNONYMS = {word: slug for slug, words in CATEGORIES.items() for word in words}
_COMPASS_TOOL = re.compile(r"^mcp__(?:plugin_compass_)?compass__(\w+)$")
_NOT_PROMPTS = ("[Request interrupted", "<task-notification>")


# -- reading transcripts ------------------------------------------------------------------


@dataclass
class Summary:
    """What a stretch of transcript lines cost."""

    main: dict[str, dict[str, int]] = field(default_factory=dict)  # model -> usage
    delegated: dict[str, dict[str, int]] = field(default_factory=dict)  # sidechain lines, by model
    tools: Counter = field(default_factory=Counter)
    prompts: int = 0
    active_s: float = 0.0
    injected_chars: int = 0
    claude_code: str | None = None

    def empty(self) -> bool:
        return not (self.main or self.delegated or self.tools or self.prompts)


def summarize(lines: Iterable[str]) -> Summary:
    out = Summary()
    messages: dict[str, tuple[str, bool, dict[str, int]]] = {}  # id -> (model, sidechain, usage)
    tool_ids: set[str] = set()
    start: float | None = None
    end: float | None = None
    for raw in lines:
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        kind = entry.get("type")
        if isinstance(entry.get("version"), str):
            out.claude_code = entry["version"]
        message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
        stamp = _seconds(entry.get("timestamp"))
        if kind == "assistant":
            _count_message(entry, message, messages)
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    key = block.get("id") or f"{len(tool_ids)}"
                    if key not in tool_ids:
                        tool_ids.add(key)
                        out.tools[tool_name(str(block.get("name") or "?"))] += 1
        elif kind == "user" and is_prompt(entry):
            out.prompts += 1
            if start is not None and end is not None:
                out.active_s += max(0.0, end - start)
            start = end = stamp  # the wait before a prompt is the developer's, not the task's
            continue
        elif kind == "attachment":
            out.injected_chars += _injected(entry.get("attachment"))
        elif kind == "user" and entry.get("isMeta"):
            text = _text(message.get("content"))
            if "[compass]" in text:  # a Compass hook's feedback, fed back to the model
                out.injected_chars += len(text)
        if stamp is None or kind == "queue-operation":  # queued prompts carry the time they were typed
            continue
        if start is None:
            if kind not in ("assistant", "user"):
                continue
            start = stamp  # work that continued without a new prompt (a hook sent Claude back)
        end = stamp if end is None else max(end, stamp)
    if start is not None and end is not None:
        out.active_s += max(0.0, end - start)
    out.active_s = round(out.active_s, 3)
    for model, sidechain, usage in messages.values():
        bucket = out.delegated if sidechain else out.main
        total = bucket.setdefault(model, {name: 0 for name, _ in USAGE_FIELDS})
        for name, _ in USAGE_FIELDS:
            total[name] += usage[name]
    return out


def _count_message(entry: dict, message: dict, messages: dict) -> None:
    usage = message.get("usage")
    model = message.get("model")
    if not isinstance(usage, dict) or not isinstance(model, str) or model.startswith("<"):  # <synthetic>
        return
    key = message.get("id") or entry.get("requestId") or entry.get("uuid")
    if not key:
        return
    values = {name: _int(usage.get(source)) for name, source in USAGE_FIELDS}
    known = messages.get(key)
    if known is not None:  # a later line of the same message: usage only grows
        values = {name: max(values[name], known[2][name]) for name in values}
    messages[key] = (model, bool(entry.get("isSidechain")), values)


def is_prompt(entry: dict[str, Any]) -> bool:
    """A prompt the developer typed: not a tool result, hook feedback, a
    compaction summary, an interruption marker or a background notice."""
    if entry.get("isMeta") or entry.get("isSidechain") or entry.get("isCompactSummary"):
        return False
    message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    text = _text(content).lstrip()
    return bool(text) and not text.startswith(_NOT_PROMPTS)


def tool_name(name: str) -> str:
    """Compass's tools as ``compass:<tool>``, other MCP servers' as ``mcp``."""
    m = _COMPASS_TOOL.match(name)
    if m:
        return f"compass:{m.group(1)}"
    return "mcp" if name.startswith("mcp__") else name


def _injected(attachment: Any) -> int:
    """Characters of context a Compass hook added: SessionStart's text and
    UserPromptSubmit's additional context."""
    if not isinstance(attachment, dict):
        return 0
    kind = attachment.get("type")
    if kind == "hook_success" and attachment.get("hookEvent") == "SessionStart":
        command = str(attachment.get("command") or "")
        return len(str(attachment.get("stdout") or "")) if command.startswith("compass hook") else 0
    if kind == "hook_additional_context":
        content = attachment.get("content")
        items = content if isinstance(content, list) else [content]
        return sum(len(item) for item in items if isinstance(item, str) and item.startswith("[compass]"))
    return 0


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _seconds(stamp: Any) -> float | None:
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def read_from(path: Path, offset: int) -> tuple[list[str], int]:
    """Complete lines after byte ``offset``, and where the next read starts.
    A line still being written stays for the next read."""
    size = path.stat().st_size
    if size < offset:  # replaced or truncated
        offset = 0
    if size - offset > MAX_READ_BYTES:
        return [], size
    with open(path, "rb") as handle:
        handle.seek(offset)
        data = handle.read(size - offset)
    cut = data.rfind(b"\n")
    if cut < 0:
        return [], offset
    return data[: cut + 1].decode("utf-8", "replace").splitlines(), offset + cut + 1


def read_settled(path: Path, offset: int, wait: float | None = None) -> tuple[list[str], int]:
    """Like ``read_from``, once the transcript has caught up: Claude Code
    writes it asynchronously, and a hook can start before the turn's last
    message is on disk. The last model message must have finished (a
    ``stop_reason`` other than ``tool_use``); give up after ``wait`` seconds
    and take what is there."""
    deadline = time.monotonic() + (SETTLE_WAIT_S if wait is None else wait)
    while True:
        lines, end = read_from(path, offset)
        if _settled(lines) or time.monotonic() >= deadline:
            return lines, end
        time.sleep(SETTLE_POLL_S)


def _settled(lines: list[str]) -> bool:
    for raw in reversed(lines):
        if '"assistant"' not in raw:
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("type") == "assistant":
            message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
            return message.get("stop_reason") not in (None, "tool_use")
    return True  # nothing from the model to wait for


def resume_offset(path: Path) -> int:
    """Where a resumed conversation's new part starts: just after the last
    assistant or system line (the old history ends with one)."""
    size = path.stat().st_size
    start = max(0, size - RESUME_TAIL_BYTES)
    with open(path, "rb") as handle:
        handle.seek(start)
        data = handle.read()
    position, after = start, None
    for line in data.split(b"\n"):
        position += len(line) + 1  # just past this line's newline
        try:
            kind = json.loads(line).get("type") if line.strip() else None
        except (ValueError, AttributeError):
            continue  # the tail's first, partial line, or not an entry
        if kind in ("assistant", "system"):
            after = position
    return size if after is None else min(size, after)


def session_totals(transcript: Path) -> dict[str, Any]:
    """A whole session, subagents included: what the benchmark harness records
    for runs with and without Compass alike."""
    main = summarize(transcript.read_text(encoding="utf-8", errors="replace").splitlines())
    delegated: dict[str, dict[str, int]] = {}
    tools: Counter = Counter()
    agents = []
    folder = transcript.with_suffix("") / "subagents"
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        part = summarize(path.read_text(encoding="utf-8", errors="replace").splitlines())
        _add_usage(delegated, part.main)
        _add_usage(delegated, part.delegated)
        tools.update(part.tools)
        agents.append(_agent_type(path))
    _add_usage(delegated, main.delegated)
    return {
        "main": main.main, "delegated": delegated, "tools": dict(sorted(main.tools.items())),
        "delegated_tools": dict(sorted(tools.items())), "agents": sorted(a for a in agents if a),
        "prompts": main.prompts, "active_s": main.active_s, "injected_chars": main.injected_chars,
        "claude_code": main.claude_code,
    }


def _agent_type(path: Path) -> str | None:
    try:
        meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta.get("agentType") if isinstance(meta, dict) and isinstance(meta.get("agentType"), str) else None


def _add_usage(total: dict[str, dict[str, int]], part: dict[str, dict[str, int]]) -> None:
    for model, usage in part.items():
        into = total.setdefault(model, {name: 0 for name, _ in USAGE_FIELDS})
        for name, _ in USAGE_FIELDS:
            into[name] += usage.get(name, 0)


# -- the hooks ------------------------------------------------------------------------------


def on_session_start(repo: Repo, config, payload: dict[str, Any]) -> None:
    """A resumed conversation's history was counted, or predates Compass: its
    rows start from here."""
    if not config.telemetry.enabled or payload.get("source") not in ("resume", "compact"):
        return
    session, transcript = _ids(payload, "session_id", "transcript_path")
    if session is None or transcript is None or not transcript.is_file():
        return
    with _offsets(repo) as offsets:
        if session not in offsets["sessions"]:
            offsets["sessions"][session] = {"offset": resume_offset(transcript), "seen": time.time()}


def on_stop(repo: Repo, config, payload: dict[str, Any]) -> None:
    """Stop: append a ``turn`` row for the transcript lines since the last Stop."""
    if not config.telemetry.enabled:
        return
    session, transcript = _ids(payload, "session_id", "transcript_path")
    if session is None or transcript is None or not transcript.is_file():
        return
    _record(repo, config, "sessions", session, transcript, lambda s: _row(repo, config, "turn", session, s, {}))


def on_subagent_stop(repo: Repo, config, payload: dict[str, Any]) -> None:
    """SubagentStop: a ``subagent`` row for the subagent's transcript, which
    counts as delegated work of the parent task."""
    if not config.telemetry.enabled:
        return
    agent, transcript = _ids(payload, "agent_id", "agent_transcript_path")
    session = payload.get("session_id") if isinstance(payload.get("session_id"), str) else None
    if agent is None or transcript is None or not transcript.is_file():
        return
    kind = payload.get("agent_type") if isinstance(payload.get("agent_type"), str) else None

    def row(summary: Summary) -> dict[str, Any]:
        delegated: dict[str, dict[str, int]] = {}
        _add_usage(delegated, summary.main)
        _add_usage(delegated, summary.delegated)  # every line of a subagent's own transcript is a sidechain
        return _row(repo, config, "subagent", session, Summary(
            delegated=delegated, tools=summary.tools, active_s=summary.active_s, claude_code=summary.claude_code,
        ), {"agent": kind})

    _record(repo, config, "agents", agent, transcript, row)


def _record(repo: Repo, config, table: str, key: str, transcript: Path, make_row) -> None:
    with _offsets(repo) as offsets:
        entry = offsets[table].get(key) or {"offset": 0}
        lines, entry["offset"] = read_settled(transcript, int(entry.get("offset", 0)))
        entry["seen"] = time.time()
        offsets[table][key] = entry
        summary = summarize(lines)
        if not summary.empty():
            append_row(repo, config, make_row(summary))


def _ids(payload: dict[str, Any], key: str, path_key: str) -> tuple[str | None, Path | None]:
    value, path = payload.get(key), payload.get(path_key)
    if not isinstance(value, str) or not value or not isinstance(path, str) or not path:
        return None, None
    return value, Path(path)


class _offsets:
    """The read positions, under the telemetry lock (Stop and SubagentStop
    can run at once), written back on exit."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self.path = repo.compass_dir / OFFSETS_NAME

    def __enter__(self) -> dict[str, Any]:
        from compass.lock import file_lock

        self._lock = file_lock(self.repo.compass_dir / LOCK_NAME, LOCK_WAIT_S)
        self._lock.__enter__()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        self.data = {t: data[t] if isinstance(data.get(t), dict) else {} for t in ("sessions", "agents")}
        return self.data

    def __exit__(self, kind, value, trace) -> None:
        try:
            if kind is None:
                for table in self.data.values():
                    for stale in sorted(table, key=lambda k: table[k].get("seen", 0))[:-MAX_TRACKED]:
                        del table[stale]
                temp = self.path.with_name(self.path.name + ".tmp")
                temp.write_text(json.dumps(self.data, sort_keys=True), encoding="utf-8")
                os.replace(temp, self.path)
        finally:
            self._lock.__exit__(kind, value, trace)


# -- rows -------------------------------------------------------------------------------------


def _row(repo: Repo, config, kind: str, session: str | None, summary: Summary, extra: dict[str, Any]) -> dict[str, Any]:
    from compass import __version__, state

    current = state.read(repo)
    task = state.active_task(current)
    record = current["tasks"].get(task) or {} if task else {}
    category, size = task_tags(record.get("brief"))
    modules = modules_on(config)
    row: dict[str, Any] = {
        "v": ROW_VERSION, "kind": kind, "at": _now(), "session": session, "task": task,
        "category": category, "size": size, "large": record.get("size") == "large",
        "compass": any(m in modules for m in MODULES), "modules": modules,
        "main": summary.main, "delegated": summary.delegated, "tools": dict(sorted(summary.tools.items())),
        "prompts": summary.prompts, "active_s": summary.active_s, "injected_chars": summary.injected_chars,
        "claude_code": summary.claude_code, "compass_version": __version__,
    }
    row.update({k: v for k, v in extra.items() if v is not None})
    return row


def modules_on(config) -> list[str]:
    data = config.data
    names = [name for name in MODULES if data[name]["enabled"]]
    return names + (["local_llm"] if data["local_llm"]["enabled"] else [])


def task_tags(brief: Any) -> tuple[str | None, str | None]:
    """The ``Category:`` and ``Size:`` a developer gave a task (pilot task
    tagging), normalised to the benchmark's categories and S/M/L."""
    if not isinstance(brief, str) or not brief:
        return None, None
    from compass.gate import parse

    labels = parse(brief, "").labels
    return normalise_category(labels.get("category")), normalise_size(labels.get("size"))


def normalise_category(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    words = " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())
    if words in CATEGORIES:
        return words
    slug = words.replace(" ", "_")
    return slug if slug in CATEGORIES else _SYNONYMS.get(words) or slug[:30] or None


def normalise_size(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    word = value.strip().split()[0].lower()
    return {"s": "S", "small": "S", "m": "M", "medium": "M", "l": "L", "large": "L"}.get(word)


def append_row(repo: Repo, config, row: dict[str, Any]) -> None:
    line = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    with open(repo.compass_dir / ROWS_NAME, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
    target = export_path(repo, config.telemetry.export)
    if target is not None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
        except OSError as exc:  # a shared folder that is not mounted: the local row is what counts
            from compass.log import log_error

            log_error(repo.root, "telemetry export", exc)


def export_path(repo: Repo, export: str | None) -> Path | None:
    if not export:
        return None
    path = Path(os.path.expanduser(export))
    return path if path.is_absolute() else repo.root / path


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_rows(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """Rows from telemetry files, each tagged with the file it came from;
    lines that are not rows are skipped."""
    rows = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("v") == ROW_VERSION and row.get("kind") in ("turn", "subagent"):
                row["source"] = str(path)
                rows.append(row)
    return rows
