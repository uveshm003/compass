"""Error log under ``.compass/logs/``.

Fail-open paths write here instead of stderr, so a Compass bug never shows up
as noise in a Claude Code session.
"""

from __future__ import annotations

import datetime
import os
import traceback
from pathlib import Path

MAX_LOG_BYTES = 1_000_000


def log_error(
    repo_root: Path | None,
    where: str,
    exc: BaseException | None = None,
    message: str = "",
) -> None:
    """Append one entry to ``.compass/logs/errors.log``; never raises."""
    if repo_root is None:
        return
    try:
        compass_dir = repo_root / ".compass"
        if not compass_dir.is_dir():
            return
        logs = compass_dir / "logs"
        logs.mkdir(exist_ok=True)
        path = logs / "errors.log"
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            os.replace(path, logs / "errors.log.1")
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [f"{stamp} [{where}] {message}".rstrip()]
        if exc is not None:
            lines.append("".join(traceback.format_exception(exc)).rstrip())
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass
