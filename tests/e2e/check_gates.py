"""M4 done-when, checked for real: "vague prompts get a checklist; large
tasks need an approved spec", in headless Claude Code sessions with the
Compass plugin loaded from this checkout.

1. Block mode: a vague prompt is refused with the checklist, before the model runs.
2. Warn mode: a vague request makes Claude ask instead of changing code.
3. A large task: Claude drafts the spec and edits nothing else; after
   ``compass approve`` and a resumed session, it changes the code.

It spends a little Claude usage (three short sessions), so pytest does not run it:

    uv run python tests/e2e/check_gates.py [--model sonnet] [--keep]
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
GIT = ["git", "-c", "user.name=Compass e2e", "-c", "user.email=e2e@example.invalid", "-c", "commit.gpgsign=false"]
VAGUE = "improve the error handling"
LARGE = (
    "Refactor src/inventory/models.py: move Reading and Unit into their own module, "
    "keeping every existing import working."
)


class Session:
    def __init__(self, repo: Path, work: Path, env: dict[str, str], model: str | None) -> None:
        self.repo, self.work, self.env, self.model = repo, work, env, model
        config = work / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {"compass": {"command": "compass", "args": ["mcp"]}}}))
        self.mcp = config

    def run(self, prompt: str, resume: str | None = None) -> dict:
        command = [
            "claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--plugin-dir", str(ROOT / "plugin"),
            "--permission-mode", "acceptEdits", "--mcp-config", str(self.mcp), "--strict-mcp-config",
            "--allowedTools", "mcp__compass",  # read-only lookups; a developer allows them once
        ]
        if resume:
            command += ["--resume", resume]
        if self.model:
            command += ["--model", self.model]
        proc = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, encoding="utf-8",
                              timeout=900, env=self.env, stdin=subprocess.DEVNULL)
        out = {"code": proc.returncode, "stderr": proc.stderr, "raw": proc.stdout, "result": "", "session": None,
               "assistant": 0, "usage": {}}
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "system" and event.get("subtype") == "init":
                out["session"] = event.get("session_id")
            elif event.get("type") == "assistant":
                out["assistant"] += 1
            elif event.get("type") == "result":
                out["result"], out["usage"] = event.get("result", "") or "", event.get("usage", {})
        return out


def fresh_repo(work: Path, name: str, env: dict[str, str], config: str | None = None) -> Path:
    repo = work / name
    shutil.copytree(FIXTURES / "python_app", repo)
    subprocess.run([*GIT, "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["compass", "init"], cwd=repo, check=True, capture_output=True, env=env)
    if config is not None:
        (repo / ".compass" / "config.yaml").write_text(config, encoding="utf-8")
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "base"], cwd=repo, check=True, env=env)
    return repo


def changed_sources(repo: Path) -> list[str]:
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo,
                            capture_output=True, text=True).stdout
    return sorted(line[3:] for line in status.splitlines() if not line[3:].startswith(".compass/"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", help="Claude model for the sessions (default: Claude Code's default)")
    parser.add_argument("--keep", action="store_true", help="keep the temporary repos and transcripts")
    args = parser.parse_args()
    if shutil.which("claude") is None:
        print("claude (Claude Code) is not on PATH", file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix="compass-e2e-gates-"))
    bin_dir = work / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "compass"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m compass "$@"\n', encoding="utf-8", newline="\n")
    shim.chmod(0o755)
    (bin_dir / "compass.cmd").write_text(f'@"{sys.executable}" -m compass %*\r\n', encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
    checks: list[tuple[str, bool]] = []
    tokens = 0

    # 1. Block mode: the vague prompt never reaches the model.
    repo = fresh_repo(work, "block", env, "prompt_gate:\n  strictness: block\n")
    blocked = Session(repo, work, env, args.model).run(VAGUE)
    said = blocked["stderr"] + blocked["raw"] + blocked["result"]
    checks.append(("block mode refuses a vague prompt with the checklist", "does not state its" in said))
    checks.append(("  ... before the model says anything", blocked["assistant"] == 0))

    # 2. Warn mode: Claude asks instead of guessing.
    repo = fresh_repo(work, "warn", env)
    warned = Session(repo, work, env, args.model).run(VAGUE)
    tokens += warned["usage"].get("output_tokens", 0)
    checks.append(("warn mode: Claude asks before changing code", "?" in warned["result"]))
    checks.append(("  ... and changes nothing yet", changed_sources(repo) == []))

    # 3. A large task: the spec first, the code only after approval.
    repo = fresh_repo(work, "large", env)
    session = Session(repo, work, env, args.model)
    drafted = session.run(LARGE)
    tokens += drafted["usage"].get("output_tokens", 0)
    spec = repo / ".compass" / "specs" / "T1.md"
    text = spec.read_text(encoding="utf-8") if spec.exists() else ""
    checks.append(("a large task gets a spec draft", "status: draft" in text))
    checks.append(("  ... which Claude fills in", "<what should change" not in text and "## Open questions" in text))
    checks.append(("  ... without touching the code", changed_sources(repo) == []))
    checks.append(("  ... and asks for approval", "approve" in drafted["result"].lower()))
    approved = subprocess.run(["compass", "approve", "T1"], cwd=repo, capture_output=True, text=True, env=env)
    checks.append(("compass approve records the approval", approved.returncode == 0 and "Approved T1" in approved.stdout))
    built = session.run(
        "Approved. Go ahead with the spec; where it left a question open, take the simplest option that keeps "
        "every existing import working.",
        resume=drafted["session"],
    )
    tokens += built["usage"].get("output_tokens", 0)
    touched = changed_sources(repo)
    checks.append(("after approval Claude changes the code", any(p.startswith("src/") for p in touched)))
    listed = subprocess.run(["compass", "check-anchors", "T1"], cwd=repo, capture_output=True, text=True, env=env).stdout
    checks.append(("  ... with anchor tags for review", bool(listed.strip())))

    print(f"1. Block mode, {VAGUE!r}:\n{(blocked['stderr'] or blocked['result']).strip()[:600]}\n")
    print(f"2. Warn mode, {VAGUE!r}:\n{warned['result'].strip()[:900]}\n")
    print(f"3. Large task, spec draft reply:\n{drafted['result'].strip()[:900]}\n")
    print(f"   Spec ({spec.relative_to(repo) if spec.exists() else 'missing'}):\n{text[:1500]}\n")
    print(f"   After approval:\n{built['result'].strip()[:700]}\n   Changed: {', '.join(touched) or 'nothing'}\n")
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    print(f"Output tokens across the sessions: {tokens}")
    print(f"Kept: {work}" if args.keep else "")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    passed = all(ok for _name, ok in checks)
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
