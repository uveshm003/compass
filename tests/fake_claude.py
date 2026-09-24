"""A stand-in for ``claude -p`` in the benchmark harness tests: it makes the
change a task asks for, writes a transcript the way Claude Code does, and
answers in stream-json, without calling any model.

With ``--plugin-dir`` it also runs Compass's UserPromptSubmit hook, as Claude
Code would, so the spec gate can hold a large task for approval. Runs with
Compass use fewer tokens, so a report over them has something to show.
``FAKE_CLAUDE_LAZY=1`` makes it change nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from transcripts import Transcript  # noqa: E402

VALUE_OPTIONS = {
    "--output-format", "--setting-sources", "--permission-mode", "--mcp-config", "--max-turns", "--plugin-dir",
    "--model", "--session-id", "--resume",
}


def parse(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    options: dict[str, str] = {}
    positional: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--allowedTools":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                i += 1
            continue
        if arg in VALUE_OPTIONS:
            options[arg] = argv[i + 1]
            i += 2
            continue
        if not arg.startswith("-"):
            positional.append(arg)
        i += 1
    return options, positional


def main(argv: list[str]) -> int:
    if argv == ["--version"]:
        print("2.1.281 (Claude Code)")
        return 0
    options, positional = parse(argv)
    prompt = positional[-1]
    session = options.get("--session-id") or options["--resume"]
    compass = "--plugin-dir" in options
    cwd = Path.cwd()
    home = Path(os.environ["CLAUDE_CONFIG_DIR"])
    path = home / "projects" / "".join(c if c.isalnum() else "-" for c in str(cwd)) / f"{session}.jsonl"
    turn = sum(1 for _ in open(path, encoding="utf-8")) if path.exists() else 0
    t = Transcript(path)
    start = turn * 10.0
    if compass:
        payload = {"session_id": session, "cwd": str(cwd), "hook_event_name": "UserPromptSubmit", "prompt": prompt,
                   "transcript_path": str(path)}
        hook = subprocess.run([sys.executable, "-m", "compass", "hook", "prompt"], input=json.dumps(payload),
                              capture_output=True, text=True, cwd=cwd)
        if hook.returncode == 2:
            print(json.dumps({"type": "result", "subtype": "success", "result": "", "is_error": True}))
            return 0
    t.prompt(start, prompt)
    lazy = os.environ.get("FAKE_CLAUDE_LAZY") == "1"
    reply = "Done."
    if "StockItem.restock" in prompt and not lazy:
        models = cwd / "src" / "inventory" / "models.py"
        models.write_text(models.read_text(encoding="utf-8").replace("self.quantity = amount", "self.quantity += amount"),
                          encoding="utf-8")
        reply = "Fixed StockItem.restock in src/inventory/models.py:48 to add to the quantity."
    elif "alarm" in prompt:
        reply = "Reading.is_alarm (src/inventory/models.py:29) compares the value with DEFAULT_THRESHOLD (models.py:8)."
    elif "Refactor" in prompt:
        reply = "I drafted the spec at .compass/specs/T1.md; approve it and I will go on."
    tools = ("mcp__compass__find_symbol", "Edit") if compass else ("Read", "Grep", "Read", "Edit")
    t.assistant(start + 1, output=200 if compass else 400, cache_read=4000 if compass else 9000, tools=tools)
    t.tool_result(start + 2).assistant(start + 3, output=50)
    t.write()
    print(json.dumps({"type": "system", "subtype": "init", "session_id": session,
                      "model": options.get("--model") or "fake-default"}))
    print(json.dumps({"type": "result", "subtype": "success", "result": reply, "is_error": False, "num_turns": 2,
                      "total_cost_usd": 0.02 if compass else 0.03}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
