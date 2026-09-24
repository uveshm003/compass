"""M2 done-when, checked for real: a headless Claude Code session answers
"where is retry handled and what calls it?" through the Compass tools, with
zero Read calls.

It spends a little Claude usage, so pytest does not run it:

    uv run python tests/e2e/check_query_tools.py [--fixture go_app] [--model sonnet] [--keep]

The session sees only the Compass MCP server (--strict-mcp-config), started
from this checkout. Read, Grep and Glob stay available, so Claude really
chooses between them and Compass. It cannot use --bare: that mode accepts only
an API key, never a claude.ai login, so your own user-level hooks and plugins
load too.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
QUESTION = "Where is retry handled in this repo, and what calls it?"
BUILTIN_READERS = ("Read", "Grep", "Glob", "Bash")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fixture", default="go_app", help="fixture repo to ask about (default: go_app)")
    parser.add_argument("--model", help="Claude model for the session (default: Claude Code's default)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary repo and transcript")
    args = parser.parse_args()
    if shutil.which("claude") is None:
        print("claude (Claude Code) is not on PATH", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="compass-e2e-"))
    repo = work / args.fixture
    shutil.copytree(FIXTURES / args.fixture, repo)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run([sys.executable, "-m", "compass", "init", "--no-git-hooks"], cwd=repo, check=True, capture_output=True)
    config = work / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"compass": {"command": sys.executable, "args": ["-m", "compass", "mcp"]}}}))

    command = [
        "claude", "-p", QUESTION, "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--mcp-config", str(config), "--strict-mcp-config",
        "--allowedTools", "mcp__compass",
    ]
    if args.model:
        command += ["--model", args.model]
    proc = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=900)
    (work / "transcript.jsonl").write_text(proc.stdout, encoding="utf-8")

    tools: Counter[str] = Counter()
    answer, usage = "", {}
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tools[block.get("name", "?")] += 1
        elif event.get("type") == "result":
            answer, usage = event.get("result", ""), event.get("usage", {})

    compass = {name: n for name, n in tools.items() if name.startswith("mcp__compass__")}
    others = {name: tools[name] for name in BUILTIN_READERS if tools.get(name)}
    print(f"Question: {QUESTION}\n\n{answer.strip() or proc.stderr.strip()}\n")
    print(f"Compass tool calls: {sum(compass.values())} {compass}")
    print(f"Built-in read tools: {others or 'none'}")
    if usage:
        print(f"Tokens: {usage.get('input_tokens', 0)} in, {usage.get('output_tokens', 0)} out, "
              f"{usage.get('cache_read_input_tokens', 0)} cache read")
    print(f"Transcript: {work / 'transcript.jsonl'}" if args.keep else "")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    passed = proc.returncode == 0 and sum(compass.values()) > 0 and tools.get("Read", 0) == 0
    print("PASS: answered through Compass with zero Read calls" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
