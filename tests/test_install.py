"""M7, the installer (IN-01 to IN-15): files mode against Claude Code's
folders and settings, plugin mode against a fake ``claude``, upgrade and
uninstall by the install record, the install mode the hooks see, and the npm
wrapper against fake ``uv`` and ``compass`` executables.

Every test runs with a temporary home directory (conftest), so the user scope
never touches the developer's own ``~/.claude``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import compass
from compass.install import install_mode
from compass.install import record as rec
from compass.install import settings as js
from compass.install.installer import InstallError, Options, config_text, install, uninstall, upgrade
from compass.install.source import bundle_root, plugin_root
from compass.install.targets import claude_code as cc
from conftest import git, run_compass, write

ROOT = Path(__file__).resolve().parents[1]
OTHER_HOOK = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo mine", "timeout": 5}]}


def files_opts(**kw) -> Options:
    return Options(**{"scope": "project", "mode": "files", "yes": True, "skip_cli": True, "init": False, **kw})


@pytest.fixture
def repo(make_repo, monkeypatch):
    root = make_repo(files={"app.py": "def f():\n    return 1\n"})
    git(root, "add", ".")
    git(root, "commit", "-qm", "init")
    monkeypatch.chdir(root)
    return root


def quiet(opts: Options) -> list[str]:
    lines: list[str] = []
    assert install(opts, out=lines.append) == 0
    return lines


def tree(root: Path, below: str = ".claude") -> dict[str, bytes]:
    base = root / below
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()} if base.is_dir() else {}


# -- files mode (IN-02) ------------------------------------------------------------------------


def test_files_mode_maps_every_plugin_file():
    plugin = plugin_root()
    files = cc.files_for(plugin)
    commands = sorted(p.name for p in (plugin / "commands").glob("*.md"))
    agents = sorted(p.stem for p in (plugin / "agents").glob("*.md"))
    assert sorted(files) == sorted(
        [f".claude/commands/compass/{n}" for n in commands]
        + [f".claude/agents/compass-{n}.md" for n in agents]
        + [f".claude/output-styles/{p.name}" for p in (plugin / "output-styles").glob("*.md")]
        + [f".claude/skills/compass-{p.parent.name}/SKILL.md" for p in (plugin / "skills").glob("*/SKILL.md")]
    )
    for path in (plugin / "skills").glob("*/SKILL.md"):  # skills are renamed like agents: /compass-<name>
        name = path.parent.name
        installed = files[f".claude/skills/compass-{name}/SKILL.md"].decode("utf-8")
        assert installed == path.read_text(encoding="utf-8").replace(f"name: {name}\n", f"name: compass-{name}\n", 1)
    for name in agents:
        original = (plugin / "agents" / f"{name}.md").read_text(encoding="utf-8")
        installed = files[f".claude/agents/compass-{name}.md"].decode("utf-8")
        assert installed == original.replace(f"name: {name}\n", f"name: compass-{name}\n", 1)
    for name in commands:  # the folder keeps the /compass:<name> command names
        assert files[f".claude/commands/compass/{name}"] == (plugin / "commands" / name).read_bytes()


def test_a_project_install_writes_files_hooks_mcp_and_record(repo):
    quiet(files_opts())
    installed = tree(repo)
    assert set(cc.files_for(plugin_root())) <= set(installed)
    settings = json.loads((repo / ".claude/settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"] == cc.hooks_for(plugin_root())
    assert json.loads((repo / ".mcp.json").read_text(encoding="utf-8")) == {
        "mcpServers": {"compass": {"command": "compass", "args": ["mcp"]}}
    }
    record = rec.load(repo, "project")
    assert (record.compass, record.mode, record.scope) == (compass.__version__, "files", "project")
    assert record.settings == {".claude/settings.json": {"created": True}}
    assert record.mcp == {".mcp.json": {"created": True}}
    assert sorted(record.files) == sorted(cc.files_for(plugin_root()))
    assert install_mode(repo) == "files"


def test_install_keeps_other_settings_and_uninstall_restores_the_exact_bytes(repo):
    original = json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}, "hooks": {"PreToolUse": [OTHER_HOOK]}}, indent=4)
    raw = ("\ufeff" + original.replace("\n", "\r\n") + "\r\n").encode("utf-8")  # BOM and CRLF, as Windows editors write
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_bytes(raw)
    (repo / ".mcp.json").write_text('{"mcpServers": {"other": {"command": "x"}}}\n', encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "settings")

    quiet(files_opts())
    merged = json.loads((repo / ".claude/settings.json").read_text(encoding="utf-8"))
    assert merged["permissions"] == {"allow": ["Bash(ls:*)"]}
    assert merged["hooks"]["PreToolUse"][0] == OTHER_HOOK
    assert len(merged["hooks"]["PreToolUse"]) == 1 + len(cc.hooks_for(plugin_root())["PreToolUse"])
    servers = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert sorted(servers) == ["compass", "other"]
    assert (repo / ".claude/settings.json.compass-bak").read_bytes() == raw

    assert uninstall(repo, "project", out=lambda _: None)
    assert (repo / ".claude/settings.json").read_bytes() == raw
    assert git(repo, "status", "--porcelain") == ""


def test_a_settings_file_that_does_not_parse_is_never_overwritten(repo):
    write(repo, ".claude/settings.json", '{"hooks": [oops')
    with pytest.raises(js.SettingsError, match="does not parse"):
        quiet(files_opts())
    assert (repo / ".claude/settings.json").read_text(encoding="utf-8") == '{"hooks": [oops'
    assert not (repo / ".claude/commands").exists()  # the files written before the failure were rolled back


def test_upgrade_keeps_edits_and_deletions(repo):
    quiet(files_opts())
    task = repo / ".claude/commands/compass/task.md"
    task.write_bytes(task.read_bytes() + b"\nOur team's note.\n")
    (repo / ".claude/agents/compass-digest.md").unlink()
    style = repo / ".claude/output-styles/compass-review.md"
    style.write_bytes(b"stale\n")
    record = rec.load(repo, "project")
    record.files[".claude/output-styles/compass-review.md"] = rec.digest(b"stale\n")  # as if an older release wrote it
    rec.path_for(repo, "project").write_text(record.to_json(), encoding="utf-8")

    lines: list[str] = []
    assert upgrade(Options(skip_cli=True, yes=True), out=lines.append) == 0
    assert task.read_text(encoding="utf-8").endswith("Our team's note.\n")  # the edit survives
    assert (repo / ".claude/commands/compass/task.md.compass-new").read_bytes() == (plugin_root() / "commands/task.md").read_bytes()
    assert not (repo / ".claude/agents/compass-digest.md").exists()  # deleted on purpose, stays deleted
    assert style.read_bytes() == (plugin_root() / "output-styles/compass-review.md").read_bytes()  # unedited: replaced
    assert any("task.md (edited)" in line for line in lines)

    assert uninstall(repo, "project", out=lines.append)
    assert task.exists() and not (repo / ".claude/commands/compass/task.md.compass-new").exists()
    assert sorted(tree(repo)) == [".claude/commands/compass/task.md"]  # only the team's edited file is left


def test_a_user_install_goes_to_the_home_directory(repo, monkeypatch, tmp_path):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    claude = fake_claude(tmp_path, monkeypatch)
    quiet(files_opts(scope="user"))
    assert (home / ".claude/agents/compass-digest.md").is_file()
    assert js.compass_hook_events(js.load(home / ".claude/settings.json")) == sorted(cc.hooks_for(plugin_root()))
    assert ["mcp", "add", "--scope", "user", "compass", "--", "compass", "mcp"] in claude.calls()
    assert not (repo / ".claude").exists()
    assert uninstall(home, "user", out=lambda _: None)
    assert ["mcp", "remove", "--scope", "user", "compass"] in claude.calls()
    assert tree(home) == {}  # every file it wrote is gone


def test_files_mode_has_no_local_scope(repo):
    with pytest.raises(InstallError, match="no local scope"):
        quiet(files_opts(scope="local"))


def test_a_dry_run_changes_nothing(repo):
    lines = quiet(files_opts(dry_run=True, init=True))
    assert not (repo / ".claude").exists() and not (repo / ".compass").exists()
    assert any("would write" in line and "compass-digest.md" in line for line in lines)


# -- one install mode at a time ----------------------------------------------------------------


def test_files_mode_is_refused_next_to_the_plugin(repo):
    write(repo, ".claude/settings.json", json.dumps({"enabledPlugins": {"compass@compass-marketplace": True}}))
    with pytest.raises(InstallError, match="every\\s+hook would run twice"):
        quiet(files_opts())


def test_a_second_files_install_in_another_scope_is_refused(repo):
    quiet(files_opts())
    with pytest.raises(InstallError, match="already installed as files for the project scope"):
        quiet(files_opts(scope="user"))


def test_the_plugin_is_refused_next_to_files(repo, tmp_path, monkeypatch):
    quiet(files_opts())
    fake_claude(tmp_path, monkeypatch)
    with pytest.raises(InstallError, match="already installed as files"):
        quiet(files_opts(mode="plugin"))


# -- plugin mode -------------------------------------------------------------------------------


class FakeClaude:
    def __init__(self, log: Path) -> None:
        self.log = log

    def calls(self) -> list[list[str]]:
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


def fake_claude(tmp_path: Path, monkeypatch) -> FakeClaude:
    """A ``claude`` on PATH that records its arguments and succeeds."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "claude-calls.jsonl"
    script = bin_dir / "fake_claude.py"
    script.write_text(
        "import json, os, sys\n"
        "with open(os.environ['FAKE_CLAUDE_LOG'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "print(os.environ.get('FAKE_CLAUDE_SAYS', 'ok'))\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        (bin_dir / "claude.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        shim = bin_dir / "claude"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    return FakeClaude(log)


def test_plugin_mode_goes_through_the_claude_cli(repo, tmp_path, monkeypatch):
    claude = fake_claude(tmp_path, monkeypatch)
    quiet(files_opts(mode="plugin", scope="local", marketplace="owner/repo"))
    assert claude.calls() == [
        ["plugin", "marketplace", "add", "owner/repo", "--scope", "local"],
        ["plugin", "install", "compass@compass-marketplace", "--scope", "local"],
    ]
    record = rec.load(repo, "local")
    assert record.plugin == {
        "id": "compass@compass-marketplace", "marketplace": "owner/repo", "marketplace_added": True,
        "settings": {"path": ".claude/settings.local.json", "created": True},
    }
    assert rec.path_for(repo, "local") == repo / ".compass/install.local.json"
    assert not (repo / ".claude").exists()
    assert uninstall(repo, "local", out=lambda _: None)
    assert claude.calls()[-2:] == [
        ["plugin", "uninstall", "compass@compass-marketplace", "--scope", "local"],
        ["plugin", "marketplace", "remove", "compass-marketplace", "--scope", "local"],
    ]


def test_plugin_mode_defaults_to_the_bundled_marketplace(repo, tmp_path, monkeypatch):
    claude = fake_claude(tmp_path, monkeypatch)
    lines = quiet(files_opts(mode="plugin", scope="project"))
    assert claude.calls()[0] == ["plugin", "marketplace", "add", str(bundle_root()), "--scope", "project"]
    assert any("teammates won't have" in line for line in lines)


CLAUDE_CODE_WROTE = {
    "enabledPlugins": {"compass@compass-marketplace": True},
    "extraKnownMarketplaces": {"compass-marketplace": {"source": {"source": "directory", "path": "/b"}}},
}


def test_plugin_mode_uninstall_removes_a_settings_file_claude_code_created(repo, tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch)
    quiet(files_opts(mode="plugin", scope="project"))
    write(repo, ".claude/settings.json", json.dumps(CLAUDE_CODE_WROTE))  # as `claude plugin install` would
    assert uninstall(repo, "project", out=lambda _: None)
    assert not (repo / ".claude/settings.json").exists()


def test_plugin_mode_uninstall_restores_the_original_settings_bytes(repo, tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch)
    original = b'{\r\n    "model": "opus"\r\n}\r\n'
    (repo / ".claude").mkdir()
    (repo / ".claude/settings.json").write_bytes(original)
    quiet(files_opts(mode="plugin", scope="project"))
    write(repo, ".claude/settings.json", json.dumps({"model": "opus", **CLAUDE_CODE_WROTE}))
    assert uninstall(repo, "project", out=lambda _: None)
    assert (repo / ".claude/settings.json").read_bytes() == original
    assert not (repo / ".claude/settings.json.compass-bak").exists()


def test_plugin_mode_keeps_a_marketplace_the_developer_already_had(repo, tmp_path, monkeypatch):
    claude = fake_claude(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_CLAUDE_SAYS", "Marketplace 'compass-marketplace' is already installed")
    quiet(files_opts(mode="plugin", scope="local", marketplace="owner/repo"))
    assert rec.load(repo, "local").plugin["marketplace_added"] is False
    assert uninstall(repo, "local", out=lambda _: None)
    assert claude.calls()[-1] == ["plugin", "uninstall", "compass@compass-marketplace", "--scope", "local"]


# -- init and presets (IN-15) ------------------------------------------------------------------


def test_presets_set_the_module_switches():
    import yaml

    full = yaml.safe_load(config_text("full", {}))
    assert all(full[m]["enabled"] for m in ("query", "prompt_gate", "review", "delegation"))
    baseline = yaml.safe_load(config_text("baseline", {}))
    assert not any(baseline[m]["enabled"] for m in ("query", "prompt_gate", "context_pack", "spec_gate", "review",
                                                    "delegation", "local_llm"))
    assert baseline["telemetry"]["enabled"] is True
    custom = yaml.safe_load(config_text("custom", {"query": True, "prompt_gate": False, "local_llm": True}))
    assert (custom["query"]["enabled"], custom["prompt_gate"]["enabled"], custom["local_llm"]["enabled"]) == (True, False, True)


def test_install_runs_init_with_the_preset(repo):
    quiet(files_opts(init=True, modules="baseline", git_hooks=False))
    from compass.config import load_config

    config = load_config(repo)
    assert not config.query.enabled and not config.review.enabled and config.telemetry.enabled
    assert (repo / ".compass/index.db").is_file()
    assert not (repo / ".git/hooks/pre-commit").exists()
    assert rec.load(repo, "project").init == {"modules": "baseline", "git_hooks": False}
    # An existing config is the team's: a second install keeps it.
    write(repo, ".compass/config.yaml", "review:\n  enabled: true\n")
    quiet(files_opts(init=True, modules="baseline", git_hooks=False))
    assert (repo / ".compass/config.yaml").read_text(encoding="utf-8") == "review:\n  enabled: true\n"


def test_the_cli_installs_and_uninstalls(repo):
    proc = run_compass("install", "--yes", "--scope", "project", "--mode", "files", "--skip-cli", "--no-init", cwd=repo)
    assert proc.returncode == 0, proc.stderr
    assert "record" in proc.stdout
    proc = run_compass("install", "--yes", "--scope", "local", "--mode", "files", "--skip-cli", cwd=repo)
    assert proc.returncode == 1 and "install stopped: files mode has no local scope" in proc.stderr
    proc = run_compass("uninstall", cwd=repo)
    assert proc.returncode == 0, proc.stderr
    assert "removed Compass's files install (project scope)" in proc.stdout
    assert git(repo, "status", "--porcelain") == ""


def test_doctor_reports_a_doubled_install(repo):
    quiet(files_opts())
    write(repo, ".claude/settings.local.json", json.dumps({"enabledPlugins": {"compass@compass-marketplace": True}}))
    proc = run_compass("doctor", "--no-mcp", cwd=repo)
    assert proc.returncode == 1
    assert "Compass is installed twice" in proc.stdout


# -- what the hooks see (IN-11, IN-14) ---------------------------------------------------------


def test_the_install_mode(repo, monkeypatch):
    assert install_mode(repo) is None
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root()))
    assert install_mode(repo) == "plugin"
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT")
    write(repo, ".claude/agents/compass-digest.md", "---\nname: compass-digest\n---\n")
    assert install_mode(repo) == "files"


def test_files_mode_subagents_are_held_to_the_same_contracts(repo):
    from compass.delegation import canonical_agent

    assert canonical_agent("compass-digest") == "compass:digest"
    assert canonical_agent("compass-scaffold") == "compass:scaffold"
    assert canonical_agent("compass-unknown") == "compass-unknown"
    assert canonical_agent("general-purpose") == "general-purpose"
    run_compass("init", "--no-git-hooks", "--no-index", cwd=repo)
    payload = {
        "session_id": "s1", "cwd": str(repo), "hook_event_name": "SubagentStop", "agent_id": "a1",
        "agent_type": "compass-test-runner", "stop_hook_active": False,
        "agent_transcript_path": str(repo / "agent.jsonl"),
        "last_assistant_message": "\n".join(f"FAILED test_{n}" for n in range(25)),
    }
    proc = run_compass("hook", "subagent-stop", input=json.dumps(payload), cwd=repo)
    assert "breaks the test-runner contract" in json.loads(proc.stdout)["reason"]


def test_session_start_names_the_agents_as_the_install_mode_does(repo):
    run_compass("init", "--no-git-hooks", "--no-index", cwd=repo)
    payload = json.dumps({"session_id": "s1", "cwd": str(repo), "hook_event_name": "SessionStart", "source": "startup"})
    assert "compass:test-runner: run test suites" in run_compass("hook", "session-start", input=payload, cwd=repo).stdout
    quiet(files_opts())
    out = run_compass("hook", "session-start", input=payload, cwd=repo).stdout
    assert "compass-test-runner: run test suites" in out and "compass:test-runner" not in out


# -- versions and packaging (IN-10, IN-12) -----------------------------------------------------


def test_the_npm_package_is_in_step():
    package = json.loads((ROOT / "npm/package.json").read_text(encoding="utf-8"))
    assert package["version"] == compass.__version__
    assert package["bin"] == {"compass-cc": "bin/compass-cc.js"}
    assert not package.get("dependencies")  # the wrapper holds no logic


def test_the_wheel_carries_the_plugin():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    include = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert include == {"plugin": "compass/_bundle/plugin", ".claude-plugin": "compass/_bundle/.claude-plugin"}
    assert bundle_root() == ROOT  # a checkout reads plugin/ directly


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_the_npm_wrapper_installs_the_cli_then_hands_over(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.jsonl"
    recorder = bin_dir / "record.py"
    recorder.write_text(
        "import json, os, sys\n"
        "with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps([os.path.basename(sys.argv[1])] + sys.argv[2:]) + '\\n')\n",
        encoding="utf-8",
    )
    # Node refuses to spawn .cmd files without a shell, so the fakes are real executables:
    # copies of this interpreter's launcher are not portable, so build tiny ones with a shebang on POSIX
    # and skip on Windows, where only .exe can be spawned directly.
    if os.name == "nt":
        pytest.skip("the fakes need to be .exe files on Windows")
    for name in ("uv", "compass"):
        shim = bin_dir / name
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{recorder}" "$0" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_LOG": str(log)}
    proc = subprocess.run(["node", str(ROOT / "npm/bin/compass-cc.js"), "install", "--yes", "--mode", "files"],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls == [
        ["uv", "tool", "install", "--force", "--compile-bytecode", f"compass=={compass.__version__}"],
        ["compass", "install", "--skip-cli", "--yes", "--mode", "files"],
    ]
