"""Claude Code as an install target (IN-02, IN-03).

``files`` mode maps ``plugin/`` onto Claude Code's own folders:

    commands/<n>.md        -> .claude/commands/compass/<n>.md   (still /compass:<n>)
    agents/<n>.md          -> .claude/agents/compass-<n>.md     (name: compass-<n>)
    skills/<n>/SKILL.md    -> .claude/skills/compass-<n>/SKILL.md (name: compass-<n>, so /compass-<n>)
    output-styles/<n>.md   -> .claude/output-styles/<n>.md
    hooks/hooks.json       -> merged into .claude/settings.json
    .mcp.json              -> merged into .mcp.json (project) or `claude mcp add --scope user`

``plugin`` mode goes through the public ``claude plugin`` commands.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from compass.install import AGENT_PREFIX

SERVER = "compass"
_NAME_LINE = re.compile(r"^name:\s*(\S+)\s*$", re.M)


def files_for(plugin: Path) -> dict[str, bytes]:
    """The files ``files`` mode installs, by path relative to the scope's base."""
    out: dict[str, bytes] = {}
    for path in sorted((plugin / "commands").glob("*.md")):
        out[f".claude/commands/compass/{path.name}"] = path.read_bytes()
    for path in sorted((plugin / "agents").glob("*.md")):
        out[f".claude/agents/{AGENT_PREFIX}{path.name}"] = rename_agent(path.read_bytes(), path.stem)
    for path in sorted((plugin / "output-styles").glob("*.md")):
        out[f".claude/output-styles/{path.name}"] = path.read_bytes()
    for path in sorted((plugin / "skills").glob("*/SKILL.md")):
        name = path.parent.name
        out[f".claude/skills/{AGENT_PREFIX}{name}/SKILL.md"] = rename_agent(path.read_bytes(), name)
    return out


def rename_agent(content: bytes, stem: str) -> bytes:
    """The agent with its frontmatter ``name:`` set to ``compass-<stem>``."""
    text = content.decode("utf-8")
    if not text.startswith("---"):
        raise ValueError(f"agents/{stem}.md has no frontmatter")
    end = text.find("\n---", 3)
    head, rest = text[:end], text[end:]
    head, count = _NAME_LINE.subn(f"name: {AGENT_PREFIX}{stem}", head, count=1)
    if count != 1:
        raise ValueError(f"agents/{stem}.md has no name: line")
    return (head + rest).encode("utf-8")


def hooks_for(plugin: Path) -> dict[str, Any]:
    return json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]


def server_for(plugin: Path) -> dict[str, Any]:
    return json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][SERVER]


def settings_rel(scope: str) -> str:
    return ".claude/settings.local.json" if scope == "local" else ".claude/settings.json"


def settings_paths(repo_root: Path | None) -> dict[str, Path]:
    """Every settings file Claude Code reads that Compass may be wired into."""
    paths = {"user": Path.home() / ".claude" / "settings.json"}
    if repo_root is not None:
        paths["project"] = repo_root / ".claude" / "settings.json"
        paths["local"] = repo_root / ".claude" / "settings.local.json"
    return paths


def plugin_commands(marketplace: str, scope: str, plugin_id: str) -> list[list[str]]:
    return [
        ["claude", "plugin", "marketplace", "add", marketplace, "--scope", scope],
        ["claude", "plugin", "install", plugin_id, "--scope", scope],
    ]


def plugin_update_commands(marketplace_name: str, scope: str, plugin_id: str) -> list[list[str]]:
    return [
        ["claude", "plugin", "marketplace", "update", marketplace_name],
        ["claude", "plugin", "update", plugin_id, "--scope", scope],
    ]


def plugin_uninstall_commands(scope: str, plugin_id: str, marketplace: str | None = None) -> list[list[str]]:
    """Uninstall the plugin, then remove the marketplace when Compass added it."""
    commands = [["claude", "plugin", "uninstall", plugin_id, "--scope", scope]]
    if marketplace:
        commands.append(["claude", "plugin", "marketplace", "remove", marketplace, "--scope", scope])
    return commands


def user_mcp_add() -> list[str]:
    return ["claude", "mcp", "add", "--scope", "user", SERVER, "--", "compass", "mcp"]


def user_mcp_remove() -> list[str]:
    return ["claude", "mcp", "remove", "--scope", "user", SERVER]
