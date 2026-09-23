"""File enumeration and hashing (IX-01).

``git ls-files`` gives tracked plus untracked-but-not-ignored files, so
.gitignore is honoured for free; the ``index.exclude`` globs from config.yaml
come on top. Symlinks, submodules, binaries and files over ``max_file_kb`` are
skipped. Paths are repo-relative POSIX strings everywhere.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from compass.index.model import FileInfo
from compass.languages import Registry
from compass.repo import COMPASS_DIR, run_git

BINARY_SNIFF_BYTES = 8000


class GitError(Exception):
    pass


def list_paths(
    root: Path,
    is_excluded: Callable[[str], bool],
    only: Iterable[str] | None = None,
) -> list[str]:
    """Candidate files, sorted; ``only`` limits the listing to those pathspecs."""
    args = ["--literal-pathspecs", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    if only is not None:
        only = list(only)
        if not only:
            return []
        args += ["--", *only]
    proc = run_git(root, *args)
    if proc.returncode != 0:
        raise GitError(proc.stderr.decode("utf-8", "replace").strip() or "git ls-files failed")
    found = set()
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            path = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue  # not representable in the index; skip rather than guess
        if path == COMPASS_DIR or path.startswith(COMPASS_DIR + "/") or is_excluded(path):
            continue
        found.add(path)
    return sorted(found)


@dataclass(frozen=True, slots=True)
class Skipped:
    """A listed path that is deliberately not indexed (binary, too big, symlink).

    The index remembers its size and mtime so refreshes do not re-read it."""

    size: int
    mtime_ns: int


def scan(
    root: Path,
    path: str,
    registry: Registry,
    max_bytes: int,
    st: os.stat_result | None = None,
) -> tuple[FileInfo, bytes] | Skipped | None:
    """Stat, read and hash one file. Skipped when it is not indexable, None
    when it is gone or unreadable."""
    full = root / path
    try:
        st = st if st is not None else os.lstat(full)
    except OSError:
        return None
    skipped = Skipped(st.st_size, st.st_mtime_ns)
    if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
        return skipped
    try:
        with open(full, "rb") as fh:
            head = fh.read(BINARY_SNIFF_BYTES)
            if b"\0" in head:
                return skipped
            data = head + fh.read()
    except OSError:
        return None
    if len(data) > max_bytes:
        return skipped
    info = FileInfo(
        path=path,
        lang=registry.detect(path, data[:256]),
        size=st.st_size,
        hash=hashlib.blake2b(data, digest_size=16).hexdigest(),
        mtime_ns=st.st_mtime_ns,
    )
    return info, data


def enumerate_files(root: Path, is_excluded: Callable[[str], bool], registry: Registry, max_bytes: int) -> list[FileInfo]:
    """Every indexable file with its language and content hash (`compass files`)."""
    out = []
    for path in list_paths(root, is_excluded):
        scanned = scan(root, path, registry, max_bytes)
        if isinstance(scanned, tuple):
            out.append(scanned[0])
    return out
