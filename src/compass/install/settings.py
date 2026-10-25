"""Non-destructive edits to Claude Code's JSON files (IN-08):
``settings.json`` gets the ``compass hook`` entries, ``.mcp.json`` the
``compass`` server.

Only Compass's own entries are added or removed; every other key and hook
stays as it was. A file that does not parse is refused, never overwritten.
Before the first write the original is kept beside it as ``.compass-bak``, and
uninstall puts those exact bytes back when nothing else changed meanwhile.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

HOOK_PREFIX = "compass hook "
BACKUP_SUFFIX = ".compass-bak"


class SettingsError(Exception):
    """A JSON file Compass must not touch: it does not parse, or is not an object."""


def load(path: Path) -> dict[str, Any] | None:
    """The file's object, or None when it does not exist."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw.decode("utf-8-sig")) if raw.strip() else {}
    except (UnicodeDecodeError, ValueError) as exc:
        raise SettingsError(f"{path} does not parse as JSON ({exc}); fix it, then run the installer again") from exc
    if not isinstance(data, dict):
        raise SettingsError(f"{path} is not a JSON object; fix it, then run the installer again")
    return data


def dumps(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def is_compass_hook(hook: Any) -> bool:
    return isinstance(hook, dict) and str(hook.get("command", "")).startswith(HOOK_PREFIX)


def merge_hooks(settings: dict[str, Any], hooks: dict[str, Any]) -> dict[str, Any]:
    """``settings`` with Compass's hook groups replaced by ``hooks``; other hooks kept."""
    out = remove_hooks(settings)
    table = out.get("hooks") if isinstance(out.get("hooks"), dict) else {}
    for event, groups in hooks.items():
        existing = table.get(event) if isinstance(table.get(event), list) else []
        table[event] = existing + copy.deepcopy(groups)
    out["hooks"] = table
    return out


def remove_hooks(settings: dict[str, Any]) -> dict[str, Any]:
    """``settings`` without any ``compass hook`` command; events and the
    ``hooks`` key that end up empty go too."""
    out = copy.deepcopy(settings)
    table = out.get("hooks")
    if not isinstance(table, dict):
        return out
    for event in list(table):
        groups = table[event]
        if not isinstance(groups, list):
            continue
        kept = []
        for group in groups:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(inner, list):
                kept.append(group)
                continue
            others = [h for h in inner if not is_compass_hook(h)]
            if len(others) == len(inner):
                kept.append(group)
            elif others:
                kept.append({**group, "hooks": others})
        if kept:
            table[event] = kept
        else:
            del table[event]
    if not table:
        del out["hooks"]
    return out


def compass_hook_events(settings: dict[str, Any] | None) -> list[str]:
    """The events whose hooks include a ``compass hook`` command."""
    table = (settings or {}).get("hooks")
    if not isinstance(table, dict):
        return []
    found = []
    for event, groups in table.items():
        for group in groups if isinstance(groups, list) else []:
            inner = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(inner, list) and any(is_compass_hook(h) for h in inner):
                found.append(event)
                break
    return sorted(found)


def merge_server(data: dict[str, Any], name: str, server: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(data)
    servers = out.get("mcpServers") if isinstance(out.get("mcpServers"), dict) else {}
    servers[name] = copy.deepcopy(server)
    out["mcpServers"] = servers
    return out


def remove_server(data: dict[str, Any], name: str) -> dict[str, Any]:
    out = copy.deepcopy(data)
    servers = out.get("mcpServers")
    if isinstance(servers, dict):
        servers.pop(name, None)
        if not servers:
            del out["mcpServers"]
    return out


def remove_plugin(data: dict[str, Any], plugin_id: str, marketplace: str | None) -> dict[str, Any]:
    """Settings without the plugin and, when Compass added it, its marketplace;
    the empty objects Claude Code leaves behind go too."""
    out = copy.deepcopy(data)
    for key, name in (("enabledPlugins", plugin_id), ("extraKnownMarketplaces", marketplace)):
        entries = out.get(key)
        if isinstance(entries, dict):
            if name:
                entries.pop(name, None)
            if not entries:
                del out[key]
    return out


def enabled_plugin(settings: dict[str, Any] | None) -> str | None:
    """The ``compass@…`` plugin these settings enable, if any."""
    plugins = (settings or {}).get("enabledPlugins")
    if isinstance(plugins, dict):
        for key, on in sorted(plugins.items()):
            if key.startswith("compass@") and on:
                return key
    return None


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def restore_or_write(path: Path, data: dict[str, Any], created: bool) -> bytes | None:
    """What uninstall should leave in ``path``: the backup's exact bytes when
    ``data`` equals it, nothing (None) when Compass created the file and
    ``data`` is empty, else ``data`` itself."""
    backup = backup_path(path)
    if backup.is_file():
        try:
            original = load(backup)
        except SettingsError:
            original = None
        if original == data:
            return backup.read_bytes()
    if created and not data:
        return None
    return dumps(data)


def atomic_write(path: Path, content: bytes) -> None:
    from compass.state import _replace

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp.write_bytes(content)
    _replace(temp, path)
