"""M7 done-when, checked for real: one `compass install` gives a working
Claude Code session in both modes, upgrade keeps an edited file, uninstall
leaves the repository and the user's settings as they were, and doctor
reports a deliberately doubled install.

It spends a little Claude usage (one short session per mode), so pytest does
not run it:

    uv run python tests/e2e/check_install.py [--mode files|plugin] [--model sonnet] [--keep]

Everything happens in a sandbox: a temporary HOME (and USERPROFILE), Claude
Code config dir and uv tool dir, so your own Claude Code setup, plugins and
compass install are never touched. With uv on PATH the install runs as a
developer would, `uvx --from <this checkout> compass install …`, which also
installs the CLI persistently into the sandbox's uv tool dir; without uv it
runs `python -m compass install --skip-cli` with a PATH shim. The npm entry
point (`npx compass-cc install`) needs a published package and is not
covered here.

Login: CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`, as in CI) when it
is set. Otherwise your credentials file is copied into the sandbox, but only
when its access token has more than 20 minutes left, so Claude Code never
refreshes (and rotates) your login from inside the sandbox; on macOS, where
the login lives in the keychain, set the token instead.
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
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "go_app"
QUESTION = "Where is retry handled in this repo, and what calls it?"
FRESH_FOR_S = 20 * 60


class Failed(Exception):
    pass


class Sandbox:
    def __init__(self, work: Path, model: str | None) -> None:
        self.work = work
        self.model = model
        self.home = work / "home"
        self.config = self.home / ".claude"
        self.config.mkdir(parents=True)
        self.bin = work / "bin"
        self.bin.mkdir()
        self.uv = shutil.which("uv")
        self.env = self._env()
        self.login = self._login()

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_PLUGIN_", "CLAUDECODE"))}
        tool_bin = self.work / "uv-bin"
        env.update({
            "HOME": str(self.home), "USERPROFILE": str(self.home), "CLAUDE_CONFIG_DIR": str(self.config),
            "UV_TOOL_DIR": str(self.work / "uv-tools"), "UV_TOOL_BIN_DIR": str(tool_bin),
            "DISABLE_AUTOUPDATER": "1", "GIT_CONFIG_NOSYSTEM": "1",
            "PATH": os.pathsep.join([str(tool_bin), str(self.bin), os.environ.get("PATH", "")]),
        })
        if self.uv:  # keep uv's real cache: a fresh one would download every dependency again
            cache = subprocess.run([self.uv, "cache", "dir"], capture_output=True, text=True).stdout.strip()
            if cache:
                env["UV_CACHE_DIR"] = cache
        else:  # no uv: hooks and the MCP entry reach this checkout through a shim
            shim = self.bin / "compass"
            shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m compass "$@"\n', encoding="utf-8", newline="\n")
            shim.chmod(0o755)
            (self.bin / "compass.cmd").write_text(f'@"{sys.executable}" -m compass %*\r\n', encoding="utf-8")
        return env

    def _login(self) -> str:
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return "token"
        real = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / ".credentials.json"
        try:
            expires = json.loads(real.read_text(encoding="utf-8"))["claudeAiOauth"]["expiresAt"] / 1000
        except (OSError, ValueError, KeyError, TypeError):
            raise Failed("no login for the sandbox: set CLAUDE_CODE_OAUTH_TOKEN (run `claude setup-token` once)")
        if expires - time.time() < FRESH_FOR_S:
            raise Failed("your access token expires within 20 minutes; run any `claude -p hi` to refresh it, "
                         "or set CLAUDE_CODE_OAUTH_TOKEN")
        shutil.copyfile(real, self.config / ".credentials.json")
        return "copied credentials"

    def forget_login(self) -> None:
        (self.config / ".credentials.json").unlink(missing_ok=True)

    def run(self, command: list[str], cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess:
        return subprocess.run(command, cwd=cwd, env=self.env, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)

    def compass(self, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        exe = shutil.which("compass", path=self.env["PATH"])
        return self.run([exe or "compass", *args], cwd)

    def install(self, repo: Path, mode: str) -> subprocess.CompletedProcess:
        flags = ["install", "--yes", "--scope", "project", "--mode", mode]
        if self.uv:  # pyproject.toml's cache-keys make uv rebuild this checkout when its sources change
            return self.run([self.uv, "tool", "run", "--python", "3.12", "--from", str(ROOT), "compass", *flags], repo)
        return self.run([sys.executable, "-m", "compass", *flags, "--skip-cli"], repo)

    def session(self, repo: Path) -> dict:
        command = [
            "claude", "-p", QUESTION, "--output-format", "stream-json", "--verbose", "--no-session-persistence",
            "--allowedTools", "mcp__compass", "mcp__plugin_compass_compass",
        ]
        if self.model:
            command += ["--model", self.model]
        proc = self.run(command, repo, timeout=900)
        (self.work / f"transcript-{repo.name}.jsonl").write_text(proc.stdout, encoding="utf-8")
        init, tools, answer = {}, Counter(), ""
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "system" and event.get("subtype") == "init":
                init = event
            elif event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        tools[block.get("name", "?")] += 1
            elif event.get("type") == "result":
                answer = event.get("result", "")
        return {"code": proc.returncode, "init": init, "tools": tools, "answer": answer, "stderr": proc.stderr}


def make_repo(work: Path, name: str) -> Path:
    repo = work / name
    shutil.copytree(FIXTURE, repo)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=e2e", "-c", "user.email=e2e@example.com",
                                                 "commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


def git_status(repo: Path) -> list[str]:
    """Porcelain status, leaving out .compass/: uninstall keeps it by design (CF-04)."""
    out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    return sorted(line for line in out.splitlines() if not line[3:].startswith(".compass/"))


def expect(ok: bool, what: str, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}" + (f"\n        {detail.strip()[:600]}" if detail and not ok else ""))
    if not ok:
        raise Failed(what)


def check_mode(box: Sandbox, mode: str) -> None:
    print(f"\n--- {mode} mode")
    repo = make_repo(box.work, f"repo-{mode}")
    user_settings = box.config / "settings.json"
    before_user = user_settings.read_bytes() if user_settings.exists() else None
    before_status = git_status(repo)

    proc = box.install(repo, mode)
    expect(proc.returncode == 0, f"compass install --mode {mode} ({'uvx' if box.uv else 'shim'})", proc.stdout + proc.stderr)
    doctor = box.compass("doctor", cwd=repo)
    expect(doctor.returncode == 0, "compass doctor is happy", doctor.stdout + doctor.stderr)

    result = box.session(repo)
    servers = {s.get("name"): s.get("status") for s in result["init"].get("mcp_servers", [])}
    compass_server = next((name for name in servers if name and "compass" in name), None)
    expect(compass_server is not None and servers[compass_server] == "connected",
           f"the Compass MCP server connected ({compass_server}: {servers.get(compass_server)})", json.dumps(servers))
    agents = result["init"].get("agents", [])
    wanted_agent = "compass:digest" if mode == "plugin" else "compass-digest"
    expect(wanted_agent in agents, f"subagent {wanted_agent} is available", json.dumps(agents))
    commands = result["init"].get("slash_commands", [])
    expect(any(c.endswith("task") and "compass" in c for c in commands), "/compass:task is available", json.dumps(commands))
    expect(any("code-review" in c for c in commands), "the code-review skill is available", json.dumps(commands))
    used = {name: n for name, n in result["tools"].items() if "compass" in name}
    expect(result["code"] == 0 and used and result["tools"].get("Read", 0) == 0,
           f"Claude answered through Compass with zero Read calls {used}", result["answer"] or result["stderr"])
    print(f"        find_symbol used: {'yes' if any(n.endswith('find_symbol') for n in used) else 'no'}")

    if mode == "files":
        task = repo / ".claude" / "commands" / "compass" / "task.md"
        original = task.read_bytes()
        task.write_bytes(original + b"\nTeam note: always tag the ticket.\n")
        up = box.compass("upgrade", "--skip-cli", "--yes", cwd=repo)
        expect(up.returncode == 0 and task.read_bytes().endswith(b"Team note: always tag the ticket.\n"),
               "compass upgrade keeps an edited command", up.stdout + up.stderr)
        task.write_bytes(original)
    else:
        up = box.compass("upgrade", "--skip-cli", "--yes", cwd=repo)
        expect(up.returncode == 0, "compass upgrade updates the plugin", up.stdout + up.stderr)

    gone = box.compass("uninstall", cwd=repo)
    expect(gone.returncode == 0, "compass uninstall", gone.stdout + gone.stderr)
    expect(git_status(repo) == before_status, "uninstall leaves git status as it was (.compass/ aside)",
           "\n".join(git_status(repo)))
    after_user = user_settings.read_bytes() if user_settings.exists() else None
    expect(after_user == before_user, "uninstall leaves the user's settings as they were")


def check_doubled(box: Sandbox) -> None:
    print("\n--- doubled install")
    repo = make_repo(box.work, "repo-doubled")
    proc = box.install(repo, "files")
    expect(proc.returncode == 0, "files-mode install", proc.stdout + proc.stderr)
    refused = box.install(repo, "plugin")
    expect(refused.returncode != 0, "compass install refuses a second mode", refused.stdout)
    # Wire the plugin in behind the installer's back, as a developer might by hand.
    for command in (["claude", "plugin", "marketplace", "add", str(ROOT), "--scope", "project"],
                    ["claude", "plugin", "install", "compass@compass-marketplace", "--scope", "project"]):
        step = box.run(command, repo)
        expect(step.returncode == 0, " ".join(command[:3]), step.stdout + step.stderr)
    doctor = box.compass("doctor", "--no-mcp", cwd=repo)
    expect(doctor.returncode == 1 and "installed twice" in doctor.stdout, "compass doctor reports the doubled install",
           doctor.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mode", choices=("files", "plugin"), help="check one mode only (default: both, then the doubled install)")
    parser.add_argument("--model", help="Claude model for the sessions (default: Claude Code's default)")
    parser.add_argument("--keep", action="store_true", help="keep the sandbox (the copied login is still removed)")
    args = parser.parse_args()
    if shutil.which("claude") is None:
        print("claude (Claude Code) is not on PATH", file=sys.stderr)
        return 2
    # which a headless session cannot answer
    work = Path(tempfile.mkdtemp(prefix="compass-install-e2e-")).resolve()
    box = None
    try:
        box = Sandbox(work, args.model)
        print(f"Sandbox {work} (login: {box.login}; install via {'uvx' if box.uv else 'python -m compass --skip-cli'})")
        for mode in ([args.mode] if args.mode else ["files", "plugin"]):
            check_mode(box, mode)
        if not args.mode:
            check_doubled(box)
    except Failed as failure:
        print(f"FAIL: {failure}")
        return 1
    finally:
        if box is not None:
            box.forget_login()
        if args.keep:
            print(f"Kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    print("\nPASS: install, session, upgrade, uninstall and doctor behave in "
          + (f"{args.mode} mode" if args.mode else "both modes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
