"""The install record (IN-05): what the installer wrote, with hashes, so an
upgrade replaces only files nobody edited and uninstall removes exactly what
was installed.

Paths are relative to the scope's base (the repository root, or the home
directory for the user scope), written with ``/`` and sorted, so the file is
deterministic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RECORD_REL = {
    "user": ".claude/compass/install.json",
    "project": ".claude/compass/install.json",
    "local": ".compass/install.local.json",  # next to other untracked state
}
NEW_SUFFIX = ".compass-new"


@dataclass
class Record:
    compass: str
    mode: str
    scope: str
    installed_at: str = ""
    files: dict[str, str] = field(default_factory=dict)  # rel -> sha256
    settings: dict[str, dict[str, Any]] = field(default_factory=dict)  # rel -> {"created": bool}
    mcp: dict[str, dict[str, Any]] = field(default_factory=dict)  # rel or "claude mcp" -> {...}
    plugin: dict[str, Any] = field(default_factory=dict)  # plugin mode: marketplace, id
    init: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        data = asdict(self)
        return json.dumps(data, indent=2, sort_keys=True) + "\n"


def path_for(base: Path, scope: str) -> Path:
    return base / RECORD_REL[scope]


def load(base: Path, scope: str) -> Record | None:
    path = path_for(base, scope)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("scope") != scope:
        return None
    known = {k: data[k] for k in Record.__dataclass_fields__ if k in data}
    try:
        return Record(**known)
    except TypeError:
        return None


def digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class FileAction:
    rel: str
    action: str  # write | add | same | keep-edited | keep-deleted | keep-existing | remove | keep-obsolete
    content: bytes | None = None


def plan_files(base: Path, wanted: dict[str, bytes], previous: Record | None) -> list[FileAction]:
    """What to do with each file, against what the last install wrote.

    - recorded and unchanged on disk: replace it (``write``, or ``same``)
    - recorded but edited: keep the edit, write the new version beside it
    - recorded but deleted: the team removed it; leave it removed
    - not recorded but present: someone else's file; keep it, new version beside it
    - recorded, no longer shipped: remove it if unchanged, else keep it
    """
    recorded = previous.files if previous else {}
    actions = []
    for rel in sorted(wanted):
        content = wanted[rel]
        path = base / rel
        current = path.read_bytes() if path.is_file() else None
        if current is not None and current == content:
            actions.append(FileAction(rel, "same", content))
        elif rel in recorded:
            if current is None:
                actions.append(FileAction(rel, "keep-deleted"))
            elif digest(current) == recorded[rel]:
                actions.append(FileAction(rel, "write", content))
            else:
                actions.append(FileAction(rel, "keep-edited", content))
        elif current is None:
            actions.append(FileAction(rel, "add", content))
        else:
            actions.append(FileAction(rel, "keep-existing", content))
    for rel in sorted(set(recorded) - set(wanted)):
        path = base / rel
        if not path.is_file():
            continue
        same = digest(path.read_bytes()) == recorded[rel]
        actions.append(FileAction(rel, "remove" if same else "keep-obsolete"))
    return actions
