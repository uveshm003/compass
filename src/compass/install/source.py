"""Where the files the installer copies come from: ``plugin/`` and the
marketplace file, the single source for both install modes (IN-02).

A wheel carries them as package data under ``compass/_bundle/`` (hatch
``force-include`` in pyproject.toml); an editable install or a checkout reads
them from the repository root.
"""

from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent  # .../compass
MARKETPLACE = "compass-marketplace"
PLUGIN_ID = f"compass@{MARKETPLACE}"


class MissingBundle(Exception):
    pass


def bundle_root() -> Path:
    """The folder holding ``.claude-plugin/marketplace.json`` and ``plugin/``."""
    for root in (PACKAGE / "_bundle", PACKAGE.parent.parent):
        if (root / "plugin" / ".claude-plugin" / "plugin.json").is_file():
            return root
    raise MissingBundle(f"the plugin files are missing from this install of compass ({PACKAGE})")


def plugin_root() -> Path:
    return bundle_root() / "plugin"


def plugin_version() -> str | None:
    try:
        return json.loads((plugin_root() / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except (MissingBundle, OSError, ValueError, KeyError):
        return None


def package_source() -> str | None:
    """What this copy of compass was installed from, for ``uv tool install``:
    a ``git+…`` URL or a local path, from the PEP 610 ``direct_url.json``;
    None for an index install (PyPI or a feed), where the version pin is enough."""
    try:
        raw = metadata.distribution("compass").read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return None
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except ValueError:
        return None
    url = info.get("url")
    if not isinstance(url, str):
        return None
    vcs = info.get("vcs_info")
    if isinstance(vcs, dict) and vcs.get("vcs") == "git":
        ref = vcs.get("requested_revision")
        return f"git+{url}" + (f"@{ref}" if ref else "")
    if url.startswith("file://"):
        from urllib.parse import unquote, urlparse

        path = unquote(urlparse(url).path)
        if len(path) > 2 and path[0] == "/" and path[2] == ":":  # file:///C:/... on Windows
            path = path[1:]
        return path
    return url
