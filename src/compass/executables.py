"""Programs Compass starts, found on PATH and never in the current directory
(NF-11: hooks never run code from the repository).

On Windows, ``CreateProcess`` and ``shutil.which`` look in the current
directory before PATH, and an empty PATH entry (a stray ``;;``, common on
Windows) means the current directory as well. Hooks and git hooks run with
the repository root as their current directory, so a ``git.exe`` or
``ctags.exe`` committed to a repository would run in place of the real one.
Every program Compass starts is resolved here, to an absolute path, from
absolute PATH entries only.
"""

from __future__ import annotations

import os

_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def which(name: str) -> str | None:
    """The absolute path of ``name`` from PATH, or None. A name that already
    holds a directory (``COMPASS_CTAGS=C:\\tools\\ctags.exe``) is the
    developer's explicit choice and is only checked for existence."""
    return next(_found(name), None)


def which_all(name: str) -> list[str]:
    """Every ``name`` on PATH, one per folder, in the order PATH searches
    them: the first is the one that runs. A folder listed twice counts once."""
    found: list[str] = []
    seen: set[str] = set()
    for path in _found(name):
        key = os.path.normcase(os.path.realpath(os.path.dirname(path)))
        if key not in seen:
            seen.add(key)
            found.append(path)
    return found


def _found(name: str):
    if os.path.dirname(name):
        if _runnable(name):
            yield os.path.abspath(name)
        return
    if os.name == "nt":
        pathext = [e.lower() for e in (os.environ.get("PATHEXT") or _DEFAULT_PATHEXT).split(os.pathsep) if e]
        names = ([name] if os.path.splitext(name)[1].lower() in pathext else []) + [name + e for e in pathext]
    else:
        names = [name]
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        folder = folder.strip().strip('"')
        if not folder or not os.path.isabs(folder):  # "", "." and relative entries are the current directory's
            continue
        for candidate in names:
            path = os.path.join(folder, candidate)
            if _runnable(path):
                yield path
                break  # compass.exe and compass.cmd in one folder are one program


def _runnable(path: str) -> bool:
    return os.path.isfile(path) and (os.name == "nt" or os.access(path, os.X_OK))
