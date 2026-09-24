"""Detached ``compass`` subprocesses, for work no one should wait on."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def spawn(args: list[str], cwd: Path) -> bool:
    """Start ``compass <args>`` detached from this process; False if it could not start."""
    import subprocess  # not at import time: every hook imports this module

    kwargs: dict = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, "-m", "compass", *args], **kwargs)
    except OSError:
        return False
    return True
