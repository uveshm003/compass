"""M5 done-when, checked for real: "test output over 500 lines reaches the
main model as a short digest, and enrichment fills summaries without slowing
commits".

1. Delegation: in a headless Claude Code session with the Compass plugin
   loaded from this checkout, Claude is asked to run a test suite whose output
   runs to 600+ lines with two failures. It must hand the run to
   ``compass:test-runner`` (or ``compass:digest``) rather than run it in the
   main conversation, get back a short answer, and name both failures.
   Telemetry must have recorded the turn with exactly the tokens Claude Code
   reports, and the subagent as delegated work (TM-01).
2. Enrichment, only with ``--local-model``: a commit with local_llm switched
   on returns as fast as one without, and the summaries arrive in the code map
   afterwards. It needs a model already running on this machine (Ollama:
   ``ollama serve``; the script never starts or downloads one).

Part 1 spends a little Claude usage (one short session), so pytest does not run it:

    uv run python tests/e2e/check_delegation.py [--model sonnet] [--local-model gemma3] [--keep]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GIT = ["git", "-c", "user.name=Compass e2e", "-c", "user.email=e2e@example.invalid", "-c", "commit.gpgsign=false"]
PYTHON = "python" if os.name == "nt" else "python3"
TEST_COMMAND = f"{PYTHON} -m unittest -v"
FAILING = (137, 408)
CALC = '''"""Small arithmetic helpers."""


def add(a, b):
    """Returns a + b."""
    return a + b
'''
TESTS = f'''import unittest

from calc import add


class TestAdd(unittest.TestCase):
    pass


def _case(n):
    def test(self):
        expected = n + n + (1 if n in {FAILING!r} else 0)  # two deliberate failures
        self.assertEqual(add(n, n), expected)
    return test


for _n in range(600):
    setattr(TestAdd, f"test_add_{{_n:03d}}", _case(_n))
'''
UNDOCUMENTED = '''def parse_reading(line):
    name, value, unit = line.split(",")
    return name.strip(), float(value), unit.strip()


class Buffer:
    def __init__(self, size):
        self.size = size
        self.items = []

    def push(self, item):
        self.items.append(item)
        del self.items[:-self.size]
'''


def stream(proc_stdout: str) -> list[dict]:
    events = []
    for line in proc_stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content or [] if isinstance(block, dict))


def compass_env(work: Path) -> dict[str, str]:
    """PATH with a `compass` that runs this checkout, as the plugin's hooks call it."""
    bin_dir = work / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "compass"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m compass "$@"\n', encoding="utf-8", newline="\n")
    shim.chmod(0o755)
    (bin_dir / "compass.cmd").write_text(f'@"{sys.executable}" -m compass %*\r\n', encoding="utf-8")
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}


def fresh_repo(work: Path, name: str, env: dict[str, str], files: dict[str, str], config: str | None = None) -> Path:
    repo = work / name
    repo.mkdir()
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
    subprocess.run([*GIT, "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["compass", "init"], cwd=repo, check=True, capture_output=True, env=env)
    if config is not None:
        (repo / ".compass" / "config.yaml").write_text(config, encoding="utf-8")
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "base"], cwd=repo, check=True, env=env)
    return repo


def check_delegation(work: Path, env: dict[str, str], model: str | None) -> tuple[list[tuple[str, bool]], dict]:
    repo = fresh_repo(work, "delegation", env, {"calc.py": CALC, "test_calc.py": TESTS})
    full = subprocess.run(TEST_COMMAND.split(), cwd=repo, capture_output=True, text=True)
    output_lines = len((full.stdout + full.stderr).splitlines())
    mcp = work / "mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"compass": {"command": "compass", "args": ["mcp"]}}}))
    prompt = f"Run the test suite (`{TEST_COMMAND}`) and tell me which tests fail and why. Do not fix anything."
    command = [
        "claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--plugin-dir", str(ROOT / "plugin"),
        "--permission-mode", "acceptEdits", "--mcp-config", str(mcp), "--strict-mcp-config",
        "--allowedTools", "mcp__compass", f"Bash({TEST_COMMAND}:*)", "Bash(compass stack:*)",
    ]
    if model:
        command += ["--model", model]
    proc = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=900, env=env,
                          stdin=subprocess.DEVNULL)
    (work / "delegation.jsonl").write_text(proc.stdout, encoding="utf-8")  # kept with --keep
    delegations, main_runs, answers, finals = {}, [], {}, {}
    result, usage = "", {}
    for event in stream(proc.stdout):
        parent = event.get("parent_tool_use_id")
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if event.get("type") == "assistant" and isinstance(content, list):
            texts = [block.get("text", "") for block in content if block.get("type") == "text"]
            if parent and any(t.strip() for t in texts):
                finals[parent] = "\n".join(texts)  # the subagent's latest words: its answer, at the end
            for block in content:
                if block.get("type") != "tool_use" or parent:
                    continue
                if block.get("name") in ("Agent", "Task"):
                    delegations[block["id"]] = (block.get("input") or {}).get("subagent_type", "")
                elif block.get("name") == "Bash":
                    main_runs.append((block.get("input") or {}).get("command", ""))
        elif event.get("type") == "user" and isinstance(content, list) and not parent:
            for block in content:
                if block.get("type") == "tool_result" and block.get("tool_use_id") in delegations:
                    answers[block["tool_use_id"]] = text_of(block.get("content"))
        elif event.get("type") == "result":
            result, usage = event.get("result", "") or "", event.get("usage", {})
    ours = {tid: kind for tid, kind in delegations.items() if kind in ("compass:test-runner", "compass:digest")}
    # What the main model got back; the subagent's own final message is what its contract covers.
    digest = "\n".join(answers.get(tid, "") for tid in ours)
    own = "\n".join(finals.get(tid) or answers.get(tid, "") for tid in ours)
    digest_lines = [line for line in own.splitlines() if line.strip()]
    # Telemetry (TM-01) read the same session from its transcript: the turn must
    # match Claude Code's own count exactly, and the subagent must show as delegated.
    rows_file = repo / ".compass" / "telemetry.jsonl"
    rows = [json.loads(line) for line in rows_file.read_text(encoding="utf-8").splitlines()] if rows_file.exists() else []
    recorded = sum(sum(u.values()) for r in rows if r["kind"] == "turn" for u in r["main"].values())
    reported = sum(usage.get(k, 0) or 0 for k in (
        "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    delegated_rows = [r for r in rows if r["kind"] == "subagent" and r.get("agent") in ours.values() and r["delegated"]]
    checks = [
        (f"the full test output runs to {output_lines} lines (over 500)", output_lines > 500),
        (f"Claude delegated the run to a Compass subagent ({', '.join(ours.values()) or 'none'})", bool(ours)),
        ("  ... and never ran the tests in the main conversation", not any("unittest" in c for c in main_runs)),
        (f"  ... whose answer came back short ({len(digest_lines)} lines, at most 20)", 0 < len(digest_lines) <= 20),
        ("  ... and named both failures", all(f"test_add_{n}" in digest for n in FAILING)),
        ("Claude's reply names both failures", all(str(n) in result for n in FAILING)),
        (f"telemetry counted the turn as Claude Code did ({recorded:,} tokens)", recorded == reported > 0),
        ("  ... and the subagent as delegated work", bool(delegated_rows) or not ours),
    ]
    return checks, {"result": result, "digest": digest, "usage": usage, "stderr": proc.stderr, "code": proc.returncode}


def check_enrichment(work: Path, env: dict[str, str], url: str, local_model: str) -> list[tuple[str, bool]]:
    config = f"local_llm:\n  enabled: true\n  base_url: {url}\n  model: {local_model}\n"
    timings = {}
    for name, cfg in (("off", None), ("on", config)):
        repo = fresh_repo(work, f"enrich-{name}", env, {"src/calc.py": CALC}, cfg)
        (repo / "src" / "readings.py").write_text(UNDOCUMENTED, encoding="utf-8", newline="\n")
        subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
        started = time.monotonic()
        subprocess.run([*GIT, "commit", "-q", "-m", "readings"], cwd=repo, check=True, env=env)
        timings[name] = time.monotonic() - started
    shard = repo / ".compass" / "map" / "src.md"
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline and shard.read_text(encoding="utf-8").count(" ~ ") < 4:
        time.sleep(1)
    text = shard.read_text(encoding="utf-8")
    print(f"Enrichment, code map after the commit ({local_model}):\n{text}")
    print(f"Commit times: {timings['off']:.2f} s with local_llm off, {timings['on']:.2f} s with it on\n")
    return [
        ("a commit with local_llm on is not slower (within 0.5 s)", timings["on"] <= timings["off"] + 0.5),
        ("the summaries arrive in the code map afterwards", text.count(" ~ ") >= 4),
        ("  ... and the author's doc stays the author's", "fn add(a, b) — Returns a + b" in text),
    ]


def model_answers(url: str, model: str) -> bool:
    from compass.config import LocalLLMSettings
    from compass.llm import LocalModel

    return LocalModel(LocalLLMSettings(True, url, model, 60, 200)).healthy(timeout=3.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", help="Claude model for the session (default: Claude Code's default)")
    parser.add_argument("--local-model", help="also check enrichment with this local model, e.g. gemma3")
    parser.add_argument("--local-url", default="http://localhost:11434/v1", help="its OpenAI-compatible endpoint")
    parser.add_argument("--skip-session", action="store_true", help="only check enrichment (no Claude usage)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary repos")
    args = parser.parse_args()
    if not args.skip_session and shutil.which("claude") is None:
        print("claude (Claude Code) is not on PATH", file=sys.stderr)
        return 2
    if args.local_model and not model_answers(args.local_url, args.local_model):
        print(f"no model {args.local_model} answering at {args.local_url}; start it first", file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix="compass-e2e-delegation-"))
    env = compass_env(work)
    checks: list[tuple[str, bool]] = []
    if not args.skip_session:
        found, session = check_delegation(work, env, args.model)
        checks += found
        print(f"1. The subagent's answer, as the main model got it:\n{session['digest'].strip()[:1500]}\n")
        print(f"   Claude's reply:\n{session['result'].strip()[:1200]}\n")
        if session["code"]:
            print(f"   claude exited {session['code']}: {session['stderr'].strip()[:600]}\n")
        print(f"   Output tokens (main model): {session['usage'].get('output_tokens', 0)}\n")
    if args.local_model:
        checks += check_enrichment(work, env, args.local_url, args.local_model)
    else:
        print("2. Enrichment: skipped (pass --local-model with a model running on this machine)\n")
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    print(f"Kept: {work}" if args.keep else "")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    passed = bool(checks) and all(ok for _name, ok in checks)
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
