"""git hooks: keep the index current after commits, checkouts and merges
(IX-08), and refuse commits that still add AI anchor tags (RO-05).

``compass init`` installs them and chains to any hook already there: the old
file moves to ``<hook>.compass-chained`` and still runs first, with the same
arguments and stdin, and its exit status is preserved. Re-running init only
refreshes Compass's own script.

Nothing is installed, and init prints the line to add instead, when:
- ``core.hooksPath`` points elsewhere (husky 5+, lefthook, pre-commit setups):
  that directory usually belongs to the team;
- the existing hook works out which hook it is from its own file name
  (symlinked dispatchers such as overcommit, ``basename "$0"``, husky 4's
  ``husky.sh``): renaming it would silently change what it runs.
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import sys
from pathlib import Path

from compass.repo import Repo, run_git

UPDATE_HOOKS = ("post-commit", "post-checkout", "post-merge", "post-rewrite")
PRE_COMMIT = "pre-commit"
HOOKS = (*UPDATE_HOOKS, PRE_COMMIT)
MARKER = "# compass-managed-hook"
CHAIN_SUFFIX = ".compass-chained"
UPDATE_COMMAND = "compass update --from-git"
CHECK_COMMAND = "compass check-anchors --staged"


def hooks_dir(repo: Repo) -> tuple[Path | None, str | None]:
    """The hooks directory to install into, or None and the reason why not."""
    configured = run_git(repo.root, "config", "--get", "core.hooksPath")
    if configured.returncode == 0 and configured.stdout.strip():
        where = configured.stdout.decode("utf-8", "replace").strip()
        return None, f"core.hooksPath is set to {where}"
    proc = run_git(repo.root, "rev-parse", "--git-path", "hooks")
    if proc.returncode != 0:
        return None, "cannot locate the git hooks directory"
    path = Path(proc.stdout.decode("utf-8", "surrogateescape").strip())
    return (path if path.is_absolute() else repo.root / path), None


def script(hook: str, python: str) -> str:
    if hook == PRE_COMMIT:
        return pre_commit_script(python)
    python = shlex.quote(python)
    return f"""#!/bin/sh
{MARKER} ({hook})
# Keeps the Compass code map current when git changes the working tree.
# Written by `compass init`; re-running it rewrites this file. A hook that was
# here before lives on as {hook}{CHAIN_SUFFIX} and still runs first.
hook_dir=$(dirname "$0")
status=0
if [ -x "$hook_dir/{hook}{CHAIN_SUFFIX}" ]; then
  "$hook_dir/{hook}{CHAIN_SUFFIX}" "$@" || status=$?
fi
unset GIT_INDEX_FILE
if [ -x {python} ]; then
  {python} -m compass update --from-git </dev/null >/dev/null 2>&1
elif command -v compass >/dev/null 2>&1; then
  compass update --from-git </dev/null >/dev/null 2>&1
fi
exit $status
"""


def pre_commit_script(python: str) -> str:
    python = shlex.quote(python)
    return f"""#!/bin/sh
{MARKER} ({PRE_COMMIT})
# Refuses a commit that still adds AI anchor tags (@ai:<kind> <task>); once a
# change is reviewed, `compass accept <task>` strips them. Written by
# `compass init`; re-running it rewrites this file. A hook that was here before
# lives on as {PRE_COMMIT}{CHAIN_SUFFIX} and runs first: if it fails, so does
# the commit. To commit anyway: git commit --no-verify.
hook_dir=$(dirname "$0")
if [ -x "$hook_dir/{PRE_COMMIT}{CHAIN_SUFFIX}" ]; then
  "$hook_dir/{PRE_COMMIT}{CHAIN_SUFFIX}" "$@" || exit $?
fi
if [ -x {python} ]; then
  exec {python} -m compass {CHECK_COMMAND.removeprefix("compass ")} </dev/null
elif command -v compass >/dev/null 2>&1; then
  exec {CHECK_COMMAND} </dev/null
fi
exit 0
"""


def install(repo: Repo, python: str | None = None) -> list[str]:
    """Install or refresh the hooks; returns one message per hook."""
    directory, reason = hooks_dir(repo)
    if directory is None:
        return [
            f"git hooks not installed: {reason}.",
            f"  Add `{UPDATE_COMMAND}` to your post-commit, post-checkout, post-merge and post-rewrite hooks,",
            f"  and `{CHECK_COMMAND}` to your pre-commit hook.",
        ]
    python = Path(python or sys.executable).as_posix()
    directory.mkdir(parents=True, exist_ok=True)
    messages = []
    for hook in HOOKS:
        path = directory / hook
        chained = directory / f"{hook}{CHAIN_SUFFIX}"
        command = CHECK_COMMAND if hook == PRE_COMMIT else UPDATE_COMMAND
        if os.path.lexists(path) and not _is_ours(path):
            if _depends_on_its_name(path):
                messages.append(f"{hook}: left alone (it dispatches on its own name); add `{command}` to it")
                continue
            if os.path.lexists(chained):
                messages.append(f"{hook}: left alone ({hook} and {chained.name} both exist)")
                continue
            os.replace(path, chained)
            messages.append(f"{hook}: installed; existing hook kept as {chained.name}")
        else:
            messages.append(f"{hook}: installed")
        path.write_text(script(hook, python), encoding="utf-8", newline="\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return messages


def uninstall(repo: Repo) -> list[str]:
    """Remove Compass's hooks and put back any hook they chained; one message
    per hook touched. Hooks Compass did not write are left alone."""
    directory, reason = hooks_dir(repo)
    if directory is None:
        return [f"git hooks: nothing to remove ({reason}); take `{UPDATE_COMMAND}` and `{CHECK_COMMAND}` out by hand."]
    messages = []
    for hook in HOOKS:
        path = directory / hook
        chained = directory / f"{hook}{CHAIN_SUFFIX}"
        if not (os.path.lexists(path) and _is_ours(path)):
            continue
        path.unlink()
        if os.path.lexists(chained):
            os.replace(chained, path)
            messages.append(f"{hook}: removed; the earlier hook is back in place")
        else:
            messages.append(f"{hook}: removed")
    return messages or ["git hooks: none of Compass's were installed"]


def _is_ours(path: Path) -> bool:
    try:
        return not path.is_symlink() and MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _depends_on_its_name(path: Path) -> bool:
    """True for hooks that would run something else under another file name."""
    if path.is_symlink():
        return True
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True  # unreadable: do not touch
    return "husky.sh" in text or re.search(r"basename\s+[\"']?\$\{?0", text) is not None
