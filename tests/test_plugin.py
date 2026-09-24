"""The Claude Code plugin (Step 5, CF-01): plain files that must stay valid and
in step with the core. The plugin holds no logic, so what can go wrong is
drift: a hook naming an event the core does not handle, a version mismatch, a
manifest the plugin loader rejects."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

import compass
from compass.anchors import scan_repo
from compass.hooks import HANDLERS

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugin"
SCHEMAS = ROOT / "tests" / "schemas"


def frontmatter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    head, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(head), body


def check_schema(schema: str, instance: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "check_jsonschema", "--schemafile", str(SCHEMAS / schema), str(instance)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_manifests_match_their_published_schemas(tmp_path):
    check_schema("claude-code-plugin-manifest.json", PLUGIN / ".claude-plugin/plugin.json")
    check_schema("claude-code-marketplace.json", ROOT / ".claude-plugin/marketplace.json")
    # hooks/hooks.json has the shape of a manifest's inline `hooks` object.
    hooks = json.loads((PLUGIN / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
    inline = tmp_path / "plugin.json"
    inline.write_text(json.dumps({"name": "compass", "hooks": hooks}), encoding="utf-8")
    check_schema("claude-code-plugin-manifest.json", inline)


def test_versions_agree():
    plugin = json.loads((PLUGIN / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert plugin["name"] == "compass"
    assert plugin["version"] == compass.__version__ == project["version"]


def test_the_marketplace_serves_this_plugin():
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    [entry] = market["plugins"]
    source = ROOT / entry["source"]
    assert source.resolve() == PLUGIN.resolve()
    assert json.loads((source / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["name"] == entry["name"]


def test_every_hook_is_a_thin_shell_out_to_a_handled_event():
    config = json.loads((PLUGIN / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
    wired = set()
    for event, groups in config.items():
        for group in groups:
            for entry in group["hooks"]:
                assert entry["type"] == "command"
                program, sub, name = entry["command"].split()
                assert (program, sub) == ("compass", "hook")  # no logic in the plugin (Architecture, layer 1)
                assert name in HANDLERS, f"{event} runs `compass hook {name}`, which the core does not handle"
                assert 0 < entry["timeout"] <= 30  # a hung hook must not stall a session for minutes
                wired.add((event, name, group.get("matcher")))
    edits = "Write|Edit|MultiEdit|NotebookEdit"
    assert wired == {
        ("SessionStart", "session-start", None),
        ("UserPromptSubmit", "prompt", None),
        ("PreToolUse", "pre-edit", edits),
        ("PreToolUse", "delegate", "Agent|Task"),  # Task is the Agent tool's older name
        ("PostToolUse", "post-edit", edits),
        ("SubagentStop", "subagent-stop", None),
        ("Stop", "stop", None),
    }
    assert set(HANDLERS) == {name for _event, name, _matcher in wired}  # and every handler is wired


def test_the_mcp_server_is_the_compass_cli():
    servers = json.loads((PLUGIN / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert servers == {"compass": {"command": "compass", "args": ["mcp"]}}


def test_accept_is_the_developers_call_not_claudes():
    meta, body = frontmatter(PLUGIN / "commands/accept.md")
    assert meta["disable-model-invocation"] is True  # accepting a change is the reviewer's decision
    assert meta["allowed-tools"] == "Bash(compass accept:*)"
    assert "```!\ncompass accept $ARGUMENTS\n```" in body


def test_task_and_approve_are_the_developers_too():
    meta, body = frontmatter(PLUGIN / "commands/approve.md")
    assert meta["disable-model-invocation"] is True  # Claude must not approve its own spec
    assert "```!\ncompass approve $ARGUMENTS\n```" in body
    meta, body = frontmatter(PLUGIN / "commands/task.md")
    assert meta["disable-model-invocation"] is True
    assert meta["allowed-tools"] == "Bash(compass task new:*)"
    # The brief goes in through a quoted heredoc, so the shell never expands it.
    assert "```!\ncompass task new --brief - <<'COMPASS_BRIEF'\n$ARGUMENTS\nCOMPASS_BRIEF\n```" in body


def test_subagents_match_their_contracts():
    # DL-01, DL-02: the Step 8 table, and the limits compass.delegation enforces.
    from compass.delegation import CONTRACTS

    expected = {
        "digest": ("Read, Grep, Glob, Bash", "at most 30 lines"),
        "test-runner": ("Bash, Read", "At most 20 lines"),
        "scaffold": ("Read, Write, Edit", "Change only the files your instructions name"),
    }
    for name, (tools, rule) in expected.items():
        meta, body = frontmatter(PLUGIN / f"agents/{name}.md")
        assert (meta["name"], meta["model"], meta["tools"]) == (name, "haiku", tools)
        assert rule.lower() in body.lower(), name
        assert f"compass:{name}" in CONTRACTS
    assert CONTRACTS["compass:digest"].max_lines == 30 and CONTRACTS["compass:test-runner"].max_lines == 20


def test_output_style_is_opt_in_and_keeps_coding_instructions():
    meta, body = frontmatter(PLUGIN / "output-styles/compass-review.md")
    assert meta["keep-coding-instructions"] is True
    assert "force-for-plugin" not in meta  # the default rules come from SessionStart, so config can turn them off
    assert "at most 10 lines" in body


def test_compass_never_asks_for_an_api_key():
    # Compass runs on Claude Code and the developer's own login: its code, plugin,
    # benchmark, e2e checks and CI never use an Anthropic API key.
    places = [ROOT / "src", ROOT / "plugin", ROOT / "bench", ROOT / "tests" / "e2e", ROOT / ".github"]
    files = [p for place in places for p in place.rglob("*") if p.is_file() and "results" not in p.parts]
    files += sorted(ROOT.glob("azure-pipelines*.yml"))
    for path in files:
        if path.suffix in (".py", ".md", ".json", ".yml", ".yaml", ".sh", ".scm"):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "ANTHROPIC_API_KEY" not in text and "apiKeyHelper" not in text, path


def test_compass_itself_carries_no_anchor_tags():
    # Compass's own commits go through its pre-commit check; every example tag
    # in its sources and docs must be quoted (after a backtick) or assembled.
    assert scan_repo(ROOT) == []


@pytest.mark.skipif(shutil.which("claude") is None, reason="Claude Code is not installed")
@pytest.mark.parametrize("target", [PLUGIN, ROOT, PLUGIN / "commands", PLUGIN / "agents"])
def test_claude_code_accepts_the_plugin(target):
    # `claude plugin validate` checks files locally; it makes no model calls.
    proc = subprocess.run(["claude", "plugin", "validate", "--strict", str(target)], capture_output=True, text=True)
    assert proc.returncode == 0 and "Validation passed" in proc.stdout, proc.stdout + proc.stderr
