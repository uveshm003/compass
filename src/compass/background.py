"""Detached ``compass`` subprocesses, for work no one should wait on."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def spawn(args: list[str], cwd: Path, low_priority: bool = False) -> bool:
    """Start ``compass <args>`` detached from this process; False if it could
    not start. ``low_priority`` runs it below normal CPU priority."""
    import subprocess  # not at import time: every hook imports this module

    kwargs: dict = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    command = [sys.executable, "-m", "compass", *args]
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        if low_priority:
            kwargs["creationflags"] |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
    else:
        kwargs["start_new_session"] = True
        if low_priority:
            import shutil

            nice = shutil.which("nice")  # POSIX; preexec_fn is not safe with threads
            command = [nice, "-n", "10", *command] if nice else command
    try:
        subprocess.Popen(command, **kwargs)
    except OSError:
        return False
    return True
