"""The installer (C10, IN-01 to IN-15): ``compass install``, ``upgrade``,
``doctor`` and the Claude Code half of ``uninstall``.

It only writes files. Nothing it installs runs at session time except the
existing ``compass hook`` and ``compass mcp`` commands, so the hooks' rules
(fail open, no network) are untouched. The installer itself is a CLI command,
never a hook: it may use the network (``uv tool install``) and exit non-zero.

This module stays import-light, because the hooks ask it for the install mode
(IN-11, IN-14); the installer proper lives in the submodules.
"""

from __future__ import annotations

import os
from pathlib import Path

PLUGIN = "plugin"
FILES = "files"
MODES = (PLUGIN, FILES)
SCOPES = ("user", "project", "local")
AGENT_PREFIX = "compass-"  # files mode: .claude/agents/compass-<name>.md
MARKER_AGENT = "agents/compass-digest.md"


def install_mode(repo_root: Path | None) -> str | None:
    """How Compass's hooks reached this session: ``plugin`` when Claude Code
    runs them from a plugin (it sets CLAUDE_PLUGIN_ROOT), ``files`` when its
    agents are installed as files in the project's or the user's ``.claude/``,
    else None. Cheap: one environment lookup and at most two stats."""
    if os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return PLUGIN
    roots = [repo_root / ".claude"] if repo_root is not None else []
    roots.append(Path.home() / ".claude")
    for root in roots:
        try:
            if (root / MARKER_AGENT).is_file():
                return FILES
        except OSError:
            continue
    return None
