"""Locating the repository and the paths Compass keeps under ``.compass/``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess

COMPASS_DIR = ".compass"

# Written to .compass/.gitignore: everything derived stays out of git and can be
# rebuilt with `compass index --full`. config.yaml, standards/ and specs/ are
# team-owned and stay tracked.
GITIGNORE_HEADER = "# Derived by Compass; rebuild with `compass index --full`."
GITIGNORE = f"""\
{GITIGNORE_HEADER}
index.db*
index.lock
map/
changes/
state.json*
state.lock
stack.json
config.cache.json*
llm.json
summaries.db*
enrich.lock
enrich.again
telemetry.jsonl
logs/
"""


class NotAGitRepo(Exception):
    """Compass was run outside a git working tree."""


@dataclass(frozen=True)
class Repo:
    root: Path

    @property
    def compass_dir(self) -> Path:
        return self.root / COMPASS_DIR

    @property
    def config_path(self) -> Path:
        return self.compass_dir / "config.yaml"

    @property
    def db_path(self) -> Path:
        return self.compass_dir / "index.db"

    @property
    def map_dir(self) -> Path:
        return self.compass_dir / "map"

    @property
    def logs_dir(self) -> Path:
        return self.compass_dir / "logs"

    @property
    def lock_path(self) -> Path:
        return self.compass_dir / "index.lock"

    @property
    def state_path(self) -> Path:
        return self.compass_dir / "state.json"

    @property
    def state_lock_path(self) -> Path:
        return self.compass_dir / "state.lock"

    @property
    def changes_dir(self) -> Path:
        return self.compass_dir / "changes"

    @property
    def initialized(self) -> bool:
        return self.compass_dir.is_dir()

    def ensure_state_dir(self) -> None:
        """Create ``.compass/`` and its ``.gitignore``; never touches config.yaml.
        A ``.gitignore`` Compass wrote earlier is brought up to date; one the
        team replaced is left alone."""
        self.compass_dir.mkdir(exist_ok=True)
        gitignore = self.compass_dir / ".gitignore"
        try:
            current = gitignore.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = None
        except OSError:
            return
        if current is None or (current != GITIGNORE and current.startswith(GITIGNORE_HEADER)):
            gitignore.write_text(GITIGNORE, encoding="utf-8", newline="\n")

    def relpath(self, path: str | os.PathLike[str]) -> str | None:
        """Repo-relative POSIX path: ``""`` for the root itself, None when
        ``path`` lies outside the repo.

        Relative inputs are taken relative to the current directory, like any
        other CLI argument.
        """
        full = Path(os.path.abspath(path))
        try:
            rel = full.relative_to(self.root)
        except ValueError:
            # Symlinked checkouts (/tmp vs /private/tmp) and Windows drive-letter
            # case both land here; compare normalised forms before giving up.
            real = Path(os.path.realpath(full))
            head, tail = os.path.normcase(str(real)), os.path.normcase(str(self.root))
            if head == tail:
                return ""
            if not head.startswith(tail.rstrip(os.sep) + os.sep):
                return None
            rel = Path(str(real)[len(str(self.root).rstrip(os.sep)) + 1 :])
        posix = rel.as_posix()
        return "" if posix == "." else posix


def run_git(cwd: Path, *args: str, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """Run git without raising; callers inspect ``returncode``."""
    import subprocess  # on first use: hooks that never run git skip its import

    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        input=input,
        capture_output=True,
        check=False,
    )


def find_repo(start: str | os.PathLike[str] | None = None) -> Repo:
    """The git working tree containing ``start`` (default: the current directory)."""
    where = Path(start) if start is not None else Path.cwd()
    try:
        proc = run_git(where, "rev-parse", "--show-toplevel")
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise NotAGitRepo(f"cannot run git in {where}: {exc}") from exc
    if proc.returncode != 0:
        raise NotAGitRepo(f"{where} is not inside a git working tree")
    top = proc.stdout.decode("utf-8", "surrogateescape").strip()
    return Repo(Path(os.path.realpath(top)))


def find_initialized_repo(start: str | os.PathLike[str]) -> Repo | None:
    """Nearest ancestor holding both ``.compass/`` and ``.git`` — no subprocess.

    Hooks use this: Compass only acts in repos where someone ran ``compass init``
    (or ``compass index``), and walking up is much cheaper than spawning git.
    """
    here = Path(os.path.realpath(start))
    for candidate in (here, *here.parents):
        if (candidate / COMPASS_DIR).is_dir() and (candidate / ".git").exists():
            return Repo(candidate)
    return None
