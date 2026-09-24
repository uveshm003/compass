"""M3 done-when, checked for real: a headless Claude Code session with the
Compass plugin makes a small change, the change gets a manifest with anchors,
a commit that still holds the tags is refused, and one after
``compass accept`` goes through.

It spends a little Claude usage, so pytest does not run it:

    uv run python tests/e2e/check_review_loop.py [--fixture python_app] [--model sonnet] [--keep]

The session loads the plugin from this checkout (``--plugin-dir``), and a
``compass`` shim on PATH runs this checkout's CLI, so no install is needed. It
cannot use ``--bare``, which would skip the plugin's hooks, so your own
user-level settings and plugins load too.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
# Each task needs a real edit in the fixture, with at least one judgment call.
TASKS = {
    "python_app": (
        "Add a StockItem.remove(amount) method in src/inventory/models.py that lowers the quantity, "
        "raising ValueError for a negative amount or one larger than the stock on hand."
    ),
    "ts_app": "Make withRetry in src/transport/reconnect.ts give up after 5 attempts and rethrow the last error.",
    "go_app": "Make Retry in internal/transport/retry.go wrap the last error from op with ErrGiveUp instead of dropping it.",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fixture", default="python_app", choices=sorted(TASKS))
    parser.add_argument("--model", help="Claude model for the session (default: Claude Code's default)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary repo and transcript")
    args = parser.parse_args()
    if shutil.which("claude") is None:
        print("claude (Claude Code) is not on PATH", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="compass-e2e-review-"))
    repo = work / args.fixture
    shutil.copytree(FIXTURES / args.fixture, repo)
    bin_dir = work / "bin"
    bin_dir.mkdir()
    _write_shim(bin_dir)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
    git = ["git", "-c", "user.name=Compass e2e", "-c", "user.email=e2e@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["compass", "init"], cwd=repo, check=True, capture_output=True, env=env)
    subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "base"], cwd=repo, check=True, env=env)

    # Only Compass's MCP server: account-level connectors would otherwise join
    # the session and pad the reply with notes about themselves.
    config = work / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"compass": {"command": "compass", "args": ["mcp"]}}}), encoding="utf-8")
    command = [
        "claude", "-p", TASKS[args.fixture], "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--plugin-dir", str(ROOT / "plugin"), "--permission-mode", "acceptEdits",
        "--mcp-config", str(config), "--strict-mcp-config",
    ]
    if args.model:
        command += ["--model", args.model]
    proc = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=900, env=env)
    (work / "transcript.jsonl").write_text(proc.stdout, encoding="utf-8")
    answer, usage = "", {}
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result":
            answer, usage = event.get("result", ""), event.get("usage", {})

    checks: list[tuple[str, bool]] = []
    manifests = sorted((repo / ".compass" / "changes").glob("T*.md"))
    checks.append(("a manifest was written", bool(manifests)))
    written = manifests[0].read_text(encoding="utf-8") if manifests else ""  # accept archives it below
    listed = subprocess.run(["compass", "check-anchors"], cwd=repo, capture_output=True, text=True, env=env).stdout
    checks.append(("the change carries anchor tags", bool(listed.strip())))
    reply_lines = [line for line in answer.strip().splitlines() if line.strip()]
    checks.append(("the reply is short (at most 12 lines)", 0 < len(reply_lines) <= 12))
    checks.append(("the reply points at the manifest", ".compass/changes/" in answer))
    subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
    refused = subprocess.run([*git, "commit", "-q", "-m", "ai change"], cwd=repo, capture_output=True, text=True, env=env)
    checks.append(("a commit with the tags is refused", refused.returncode != 0 and "commit refused" in refused.stderr))
    accepted = subprocess.run(["compass", "accept"], cwd=repo, capture_output=True, text=True, env=env)
    subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
    committed = subprocess.run([*git, "commit", "-q", "-m", "ai change"], cwd=repo, capture_output=True, text=True, env=env)
    checks.append(("after compass accept the commit goes through", accepted.returncode == 0 and committed.returncode == 0))

    print(f"Task: {TASKS[args.fixture]}\n\nReply:\n{answer.strip() or proc.stderr.strip()}\n")
    if manifests:
        print(f"Manifest ({manifests[0].name}):\n{written}")
    print(f"Anchors before accept:\n{listed.strip() or '(none)'}\n{accepted.stdout.strip()}\n")
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    if usage:
        print(f"Tokens: {usage.get('input_tokens', 0)} in, {usage.get('output_tokens', 0)} out, "
              f"{usage.get('cache_read_input_tokens', 0)} cache read")
    print(f"Kept: {work}" if args.keep else "")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    passed = proc.returncode == 0 and all(ok for _name, ok in checks)
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


def _write_shim(bin_dir: Path) -> None:
    """`compass` on PATH that runs this checkout, for the plugin's hooks and MCP server."""
    python = sys.executable
    (bin_dir / "compass").write_text(f'#!/bin/sh\nexec "{python}" -m compass "$@"\n', encoding="utf-8", newline="\n")
    (bin_dir / "compass").chmod(0o755)
    (bin_dir / "compass.cmd").write_text(f'@"{python}" -m compass %*\r\n', encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
