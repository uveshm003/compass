"""Synthetic Claude Code transcripts in the 2.1 line format, for the
telemetry tests. Real transcripts hold the developer's email, system prompt
and code, so none are committed; these reproduce the parts telemetry reads.

- One JSONL line per content block. Every line of an API message repeats its
  ``usage``, and output tokens are still growing on the early lines.
- A prompt the developer typed is a ``user`` line with text content. Tool
  results are ``user`` lines with ``tool_result`` blocks. Hook feedback (a
  Stop hook's block reason) is a ``user`` line with ``isMeta``.
- Queued prompts leave ``queue-operation`` lines stamped when they were typed,
  and every Stop leaves a ``system``/``stop_hook_summary`` line.
- Subagents write their own file, ``<session>/subagents/agent-<id>.jsonl``,
  with ``isSidechain`` on every line and a ``.meta.json`` naming the agent type.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = datetime(2026, 9, 24, 2, 0, 0, tzinfo=timezone.utc)
MAIN = "claude-opus-5-5"
HAIKU = "claude-haiku-4-5-20251001"


def at(seconds: float) -> str:
    return (BASE + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Transcript:
    """Lines appended in order; ``write`` saves them (or the new ones) to ``path``."""

    def __init__(self, path: Path, sidechain: bool = False, version: str = "2.1.281") -> None:
        self.path = path
        self.sidechain = sidechain
        self.version = version
        self.lines: list[str] = []
        self.written = 0
        self._ids = 0

    def _add(self, entry: dict) -> Transcript:
        entry.setdefault("isSidechain", self.sidechain)
        entry.setdefault("version", self.version)
        self.lines.append(json.dumps(entry, separators=(",", ":")))  # compact, as Claude Code writes them
        return self

    def _next(self, prefix: str) -> str:
        self._ids += 1
        return f"{prefix}_{self._ids:04d}"

    def queued(self, t: float) -> Transcript:
        self.lines.append(json.dumps({"type": "queue-operation", "operation": "enqueue", "timestamp": at(t)},
                                     separators=(",", ":")))
        return self

    def prompt(self, t: float, text: str = "Fix the retry loop in src/retry.py") -> Transcript:
        return self._add({"type": "user", "timestamp": at(t), "promptId": self._next("prompt"),
                          "message": {"role": "user", "content": text}})

    def assistant(self, t: float, output: int, cache_read: int = 1000, cache_creation: int = 100, input: int = 3,
                  tools: tuple[str, ...] = (), model: str = MAIN, steps: float = 0.5) -> Transcript:
        """One API message: a thinking line with partial usage and no stop reason yet, then a
        line per tool call (stop reason ``tool_use``) or a text line (``end_turn``)."""
        mid = self._next("msg")
        usage = {"input_tokens": input, "cache_creation_input_tokens": cache_creation,
                 "cache_read_input_tokens": cache_read}
        blocks = [{"type": "tool_use", "id": self._next("toolu"), "name": name, "input": {}} for name in tools]
        blocks = blocks or [{"type": "text", "text": "Done."}]
        stop = "tool_use" if tools else "end_turn"
        self._add({"type": "assistant", "timestamp": at(t), "requestId": "req_" + mid,
                   "message": {"id": mid, "model": model, "role": "assistant", "content": [{"type": "thinking"}],
                               "stop_reason": None, "usage": {**usage, "output_tokens": max(1, output // 10)}}})
        for i, block in enumerate(blocks, 1):
            self._add({"type": "assistant", "timestamp": at(t + i * steps / len(blocks)), "requestId": "req_" + mid,
                       "message": {"id": mid, "model": model, "role": "assistant", "content": [block],
                                   "stop_reason": stop, "usage": {**usage, "output_tokens": output}}})
        return self

    def tool_result(self, t: float) -> Transcript:
        return self._add({"type": "user", "timestamp": at(t), "promptId": "p",
                          "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x",
                                                                   "content": "ok"}]}})

    def hook_feedback(self, t: float, reason: str) -> Transcript:
        return self._add({"type": "user", "timestamp": at(t), "isMeta": True, "promptId": "p",
                          "message": {"role": "user", "content": f"Stop hook feedback:\n{reason}"}})

    def stop(self, t: float) -> Transcript:
        return self._add({"type": "system", "subtype": "stop_hook_summary", "timestamp": at(t), "hookErrors": []})

    def session_start_context(self, t: float, text: str) -> Transcript:
        return self._add({"type": "attachment", "timestamp": at(t), "attachment": {
            "type": "hook_success", "hookEvent": "SessionStart", "hookName": "SessionStart:startup",
            "command": "compass hook session-start", "stdout": text, "exitCode": 0}})

    def prompt_context(self, t: float, *texts: str) -> Transcript:
        return self._add({"type": "attachment", "timestamp": at(t), "attachment": {
            "type": "hook_additional_context", "hookEvent": "UserPromptSubmit", "content": list(texts)}})

    def raw(self, entry: dict) -> Transcript:
        return self._add(entry)

    def write(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
            for line in self.lines[self.written:]:
                handle.write(line + "\n")
        self.written = len(self.lines)
        return self.path


def subagent(session_file: Path, agent_id: str, agent_type: str) -> Transcript:
    folder = session_file.with_suffix("") / "subagents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"agent-{agent_id}.meta.json").write_text(json.dumps({"agentType": agent_type}), encoding="utf-8")
    return Transcript(folder / f"agent-{agent_id}.jsonl", sidechain=True)
