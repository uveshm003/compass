"""The benchmark harness (Evaluation Plan): every task run headless with
Compass on and off, in a fresh copy of its repository, and scored by its
hidden acceptance test.

    uv run python bench/run.py --model claude-opus-5-5 [--tasks bench/tasks/examples]
        [--conditions off,on] [--repeats 3] [--only x01,x02] [--seed 1] [--dry-run]
    uv run compass report bench/results/<batch>

One run, as the plan's protocol has it:

1. A fresh copy of the task's repo at its commit, in a temp directory, with
   the task's ``setup`` steps applied and committed.
2. With Compass on: ``compass init`` and a full index, timed on their own;
   ablation conditions (``on-no-map``, ``on-no-gates``, ``on-no-delegation``,
   ``on-no-review``) switch one module group off.
3. ``claude -p`` with the task's prompt, a fixed session id, the pinned model,
   stream-json output and ``--max-turns``. With Compass on, the plugin comes
   from this checkout (``--plugin-dir``) and its MCP server with it; other MCP
   servers and user settings stay out in both conditions.
4. When the spec gate waits for approval, the harness runs ``compass approve``
   and resumes with "proceed with the stated assumptions". The pause is not
   counted: active time comes from the transcript and leaves out the waits
   before prompts, the same measure telemetry uses.
5. The hidden files are copied in, and the acceptance check runs.
6. Everything is kept in ``bench/results/<batch>/<run>/``: the stream, the
   transcript with its subagent transcripts, Compass's logs, the diff, the
   reply, the acceptance output, and ``row.json`` for ``compass report``.

Runs go in a shuffled order (``--seed``), so time-of-day API latency does not
favour one condition. Claude Code's auto-updater is off for the batch, and its
version is recorded with every run. Never compare numbers across Compass or
Claude Code versions.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

BENCH = Path(__file__).resolve().parent
ROOT = BENCH.parent
FIXTURES = ROOT / "tests" / "fixtures"
GIT = ["git", "-c", "user.name=Compass bench", "-c", "user.email=bench@example.invalid", "-c", "commit.gpgsign=false",
       "-c", "init.defaultBranch=main"]
ABLATIONS = {  # condition -> the config sections it switches off
    "on-no-map": ("query", "context_pack"),
    "on-no-gates": ("prompt_gate", "spec_gate"),
    "on-no-delegation": ("delegation",),
    "on-no-review": ("review",),
}
CONDITIONS = ("off", "on", *ABLATIONS)
BASE_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write", "MultiEdit")
COMPASS = [sys.executable, "-m", "compass"]  # the harness's own calls; Claude Code's hooks use the PATH shim
APPROVAL_REPLY = "Approved. Proceed with the stated assumptions for any open question."
MAX_APPROVALS = 2


@dataclass
class Task:
    id: str
    repo: str
    category: str
    prompt: str
    acceptance: dict[str, Any]
    commit: str = "fixture"
    setup: list[dict[str, Any]] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    timeout_min: float = 20
    max_turns: int = 40
    allowed_tools: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> Task:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        acceptance = data.get("acceptance")
        if isinstance(acceptance, str):
            acceptance = {"command": acceptance}
        return cls(
            id=str(data["id"]), repo=str(data["repo"]), category=str(data["category"]), prompt=str(data["prompt"]).strip(),
            acceptance=acceptance or {}, commit=str(data.get("commit", "fixture")), setup=list(data.get("setup") or []),
            hidden=[str(h) for h in data.get("hidden") or []], timeout_min=float(data.get("timeout_min", 20)),
            max_turns=int(data.get("max_turns", 40)), allowed_tools=[str(t) for t in data.get("allowed_tools") or []],
        )


def load_tasks(folder: Path, only: set[str] | None) -> list[Task]:
    tasks = [Task.load(p) for p in sorted(folder.glob("*.yaml"))]
    return [t for t in tasks if not only or t.id in only]


def load_repos() -> dict[str, dict[str, Any]]:
    return yaml.safe_load((BENCH / "repos.yaml").read_text(encoding="utf-8")) or {}


# -- preparing a repository --------------------------------------------------------------------------


def prepare(task: Task, repos: dict[str, dict[str, Any]], dest: Path) -> None:
    """A fresh working tree of the task's repo at its commit, with setup applied and committed."""
    spec = repos.get(task.repo)
    if spec is None:
        raise SystemExit(f"task {task.id}: repo {task.repo!r} is not in bench/repos.yaml")
    if "fixture" in spec:
        junk = shutil.ignore_patterns("__pycache__", "*.pyc", ".ruff_cache", ".pytest_cache", ".DS_Store")
        shutil.copytree(FIXTURES / spec["fixture"], dest, ignore=junk)
        _git(dest, "init", "-q")
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "--no-verify", "-m", "base")
    else:
        mirror = _mirror(task.repo, spec["url"])
        subprocess.run([*GIT, "clone", "-q", "--shared", str(mirror), str(dest)], check=True, capture_output=True)
        _git(dest, "checkout", "-q", task.commit)
    for step in task.setup:
        _setup_step(dest, step)
    if task.setup:
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "--no-verify", "-m", "bench setup")


def _mirror(name: str, url: str) -> Path:
    mirror = BENCH / ".cache" / f"{name}.git"
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([*GIT, "clone", "-q", "--mirror", url, str(mirror)], check=True)
    return mirror


def _setup_step(repo: Path, step: dict[str, Any]) -> None:
    if "replace" in step:
        r = step["replace"]
        path = repo / r["file"]
        text = path.read_text(encoding="utf-8")
        if r["old"] not in text:
            raise SystemExit(f"setup: {r['old']!r} is not in {r['file']}")
        path.write_text(text.replace(r["old"], r["new"], 1), encoding="utf-8", newline="\n")
    elif "write" in step:
        path = repo / step["write"]["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(step["write"]["text"], encoding="utf-8", newline="\n")
    elif "run" in step:
        subprocess.run(_command(step["run"]), shell=True, cwd=repo, check=True)
    else:
        raise SystemExit(f"unknown setup step {step!r}")


def _command(text: str) -> str:
    return text.replace("{python}", _quote(sys.executable))


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path else path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run([*GIT, *args], cwd=repo, check=True, capture_output=True, text=True).stdout


# -- one run -----------------------------------------------------------------------------------------


@dataclass
class Run:
    task: Task
    condition: str
    repeat: int

    @property
    def id(self) -> str:
        return f"{self.task.id}-{self.condition}-{self.repeat}"


def run_one(run: Run, args, batch: str, out: Path, env: dict[str, str], claude_version: str) -> dict[str, Any]:
    from compass import __version__, state
    from compass.config import load_config
    from compass.repo import Repo
    from compass.telemetry import modules_on, session_totals

    work = Path(tempfile.mkdtemp(prefix=f"compass-bench-{run.id}-"))
    repo = work / "repo"
    try:
        prepare(run.task, load_repos(), repo)
        on = run.condition != "off"
        index_s = None
        if on:
            started = time.monotonic()  # init builds the first index; the plan reports it on its own
            subprocess.run([*COMPASS, "init"], cwd=repo, check=True, capture_output=True, env=env)
            index_s = round(time.monotonic() - started, 3)
            sections = ABLATIONS.get(run.condition, ())
            if sections:
                config = "".join(f"{name}:\n  enabled: false\n" for name in sections)
                (repo / ".compass" / "config.yaml").write_text(config, encoding="utf-8")
        session = str(uuid.uuid4())
        mcp = work / "mcp.json"
        servers = {"compass": {"command": "compass", "args": ["mcp"]}} if on else {}
        mcp.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
        tools = [*BASE_TOOLS, *run.task.allowed_tools, *(["mcp__compass"] if on else [])]
        base = [
            args.claude, "-p", "--output-format", "stream-json", "--verbose", "--setting-sources", "project,local",
            "--permission-mode", "acceptEdits", "--mcp-config", str(mcp), "--strict-mcp-config",
            "--max-turns", str(run.task.max_turns), "--allowedTools", *tools,
        ]
        if on:
            base += ["--plugin-dir", str(ROOT / "plugin")]
        if args.model:
            base += ["--model", args.model]
        stream_path = out / "stream.jsonl"
        deadline = time.monotonic() + run.task.timeout_min * 60
        results, wall, approvals, timed_out = [], 0.0, 0, False
        prompt, resume = run.task.prompt, False
        while True:
            command = [*base, "--resume" if resume else "--session-id", session, prompt]
            started = time.monotonic()
            try:
                proc = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8", env=env,
                                      timeout=max(1.0, deadline - time.monotonic()), stdin=subprocess.DEVNULL)
                stdout, code = proc.stdout, proc.returncode
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                code, timed_out = None, True
            wall += time.monotonic() - started
            with open(stream_path, "a", encoding="utf-8") as handle:
                handle.write(stdout)
            results.append(_result(stdout))
            if timed_out or not on or approvals >= MAX_APPROVALS:
                break
            if not state.needs_approval(state.read(Repo(repo))):
                break
            approvals += 1
            subprocess.run([*COMPASS, "approve"], cwd=repo, check=True, capture_output=True, env=env)
            prompt, resume = APPROVAL_REPLY, True
        reply = next((r["result"] for r in reversed(results) if r.get("result")), "")
        (out / "reply.txt").write_text(reply, encoding="utf-8")
        transcript = _transcript(session)
        totals = session_totals(transcript) if transcript else {}
        if transcript:
            shutil.copy2(transcript, out / "transcript.jsonl")
            subagents = transcript.with_suffix("") / "subagents"
            if subagents.is_dir():
                shutil.copytree(subagents, out / "subagents")
        if on and (repo / ".compass" / "logs").is_dir():
            shutil.copytree(repo / ".compass" / "logs", out / "compass-logs")
        _git(repo, "add", "-A", "-N")
        (out / "diff.patch").write_text(_git(repo, "diff", "--", ".", ":(exclude).compass"), encoding="utf-8")
        passed, check_output = accept(run.task, repo, out / "reply.txt")
        (out / "acceptance.txt").write_text(check_output, encoding="utf-8")
        modules = modules_on(load_config(repo)) if on else []
        row = {
            "v": 1, "kind": "turn", "at": _now(), "session": session, "task": None, "category": run.task.category,
            "size": None, "large": False, "compass": on, "modules": modules,
            "main": totals.get("main", {}), "delegated": totals.get("delegated", {}), "tools": totals.get("tools", {}),
            "prompts": totals.get("prompts", 0), "active_s": totals.get("active_s", 0.0),
            "injected_chars": totals.get("injected_chars", 0), "claude_code": totals.get("claude_code") or claude_version,
            "compass_version": __version__,
            "bench": {
                "run": run.id, "batch": batch, "task": run.task.id, "repo": run.task.repo, "category": run.task.category,
                "condition": run.condition, "repeat": run.repeat, "pass": passed, "model": args.model or _model(results),
                "compass_version": __version__, "claude_code": claude_version, "wall_s": round(wall, 3),
                "index_s": index_s, "approvals": approvals, "timed_out": timed_out,
                "cost_usd": _cost(results), "turns": sum(r.get("num_turns") or 0 for r in results),
                "agents": totals.get("agents", []), "delegated_tools": totals.get("delegated_tools", {}),
                "transcript": bool(transcript), "claude_exit": code,
            },
        }
        (out / "row.json").write_text(json.dumps(row, indent=2, sort_keys=True), encoding="utf-8")
        return row
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


def accept(task: Task, repo: Path, reply: Path) -> tuple[bool, str]:
    """Copy the hidden files in, then run the task's check: pass or fail, and what it printed."""
    for rel in task.hidden:
        source = BENCH / "hidden" / task.id / rel
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    lines, passed = [], True
    wanted = task.acceptance.get("reply_contains") or []
    text = reply.read_text(encoding="utf-8")
    for needle in wanted:
        found = needle.lower() in text.lower()
        lines.append(f"reply contains {needle!r}: {'yes' if found else 'no'}")
        passed = passed and found
    command = task.acceptance.get("command")
    if command:
        env = {**os.environ, "BENCH_REPLY": str(reply), **{k: str(v) for k, v in (task.acceptance.get("env") or {}).items()}}
        try:
            proc = subprocess.run(_command(command), shell=True, cwd=repo, env=env, capture_output=True, text=True,
                                  timeout=600)
            lines += [f"$ {command}", proc.stdout, proc.stderr, f"exit {proc.returncode}"]
            passed = passed and proc.returncode == 0
        except subprocess.TimeoutExpired:
            lines.append(f"$ {command}\ntimed out")
            passed = False
    if not wanted and not command:
        return False, "the task has no acceptance check"
    return passed, "\n".join(lines) + "\n"


def _result(stdout: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "system" and event.get("subtype") == "init":
            found["model"] = event.get("model")
        if isinstance(event, dict) and event.get("type") == "result":
            found.update({k: event.get(k) for k in ("result", "total_cost_usd", "num_turns", "is_error", "subtype")})
    return found


def _cost(results: list[dict[str, Any]]) -> float | None:
    costs = [r["total_cost_usd"] for r in results if isinstance(r.get("total_cost_usd"), (int, float))]
    return round(sum(costs), 6) if costs else None


def _model(results: list[dict[str, Any]]) -> str | None:
    return next((r["model"] for r in results if r.get("model")), None)


def _transcript(session: str) -> Path | None:
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return next(iter(sorted((home / "projects").glob(f"*/{session}.jsonl"))), None)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# -- the batch ---------------------------------------------------------------------------------------


def compass_env(work: Path) -> dict[str, str]:
    """PATH with a ``compass`` that runs this checkout, as the plugin's hooks and MCP entry call it."""
    bin_dir = work / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "compass"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m compass "$@"\n', encoding="utf-8", newline="\n")
    shim.chmod(0o755)
    (bin_dir / "compass.cmd").write_text(f'@"{sys.executable}" -m compass %*\r\n', encoding="utf-8")
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "DISABLE_AUTOUPDATER": "1"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tasks", type=Path, default=BENCH / "tasks" / "examples", help="folder of task YAML files")
    parser.add_argument("--conditions", default="off,on", help=f"comma-separated, from {', '.join(CONDITIONS)}")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--only", help="comma-separated task ids")
    parser.add_argument("--model", help="the model to pin for every run (recorded either way)")
    parser.add_argument("--seed", type=int, default=1, help="shuffles the run order")
    parser.add_argument("--batch", help="results folder name (default: the start time)")
    parser.add_argument("--results", type=Path, default=BENCH / "results")
    parser.add_argument("--claude", default="claude", help="the Claude Code executable")
    parser.add_argument("--keep", action="store_true", help="keep each run's working copy")
    parser.add_argument("--dry-run", action="store_true", help="list the runs and exit")
    args = parser.parse_args(argv)
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    unknown = sorted(set(conditions) - set(CONDITIONS))
    if unknown:
        parser.error(f"unknown condition {', '.join(unknown)}")
    tasks = load_tasks(args.tasks, set(args.only.split(",")) if args.only else None)
    if not tasks:
        parser.error(f"no tasks in {args.tasks}")
    runs = [Run(t, c, r) for t in tasks for c in conditions for r in range(1, args.repeats + 1)]
    random.Random(args.seed).shuffle(runs)
    if args.dry_run:
        print("\n".join(r.id for r in runs))
        return 0
    if shutil.which(args.claude) is None:
        print(f"{args.claude} (Claude Code) is not on PATH", file=sys.stderr)
        return 2
    if not args.model:
        print("warning: no --model given; each run records the model Claude Code chose", file=sys.stderr)
    batch = args.batch or datetime.now().strftime("%Y%m%d-%H%M%S")
    folder = args.results / batch
    work = Path(tempfile.mkdtemp(prefix="compass-bench-"))
    env = compass_env(work)
    version = (subprocess.run([args.claude, "--version"], capture_output=True, text=True, env=env).stdout.split() or [""])[0]
    print(f"{len(runs)} runs ({len(tasks)} tasks × {len(conditions)} conditions × {args.repeats}) into {folder}")
    print(f"Claude Code {version or '?'}, model {args.model or '(default)'}")
    try:
        for n, run in enumerate(runs, 1):
            out = folder / run.id
            if (out / "row.json").exists():
                print(f"[{n}/{len(runs)}] {run.id}: done before, skipped")
                continue
            out.mkdir(parents=True, exist_ok=True)
            row = run_one(run, args, batch, out, env, version)
            bench = row["bench"]
            tokens = sum(sum(u.values()) for u in row["main"].values())
            print(f"[{n}/{len(runs)}] {run.id}: {'pass' if bench['pass'] else 'FAIL'}, {tokens:,} main-model tokens,"
                  f" {row['active_s']:.0f} s")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"\nReport: uv run compass report {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
