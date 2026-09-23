"""gitignore-style globs for the ``index.exclude`` list.

Rules, matched against repo-relative POSIX paths:

- ``*`` and ``?`` never cross a ``/``; ``**`` does.
- ``**/`` at the start or in the middle matches zero or more directories.
- A pattern containing a slash (other than a trailing one) is anchored at the
  repo root; one without a slash matches a file or directory name at any depth.
- A pattern that matches a directory also matches everything below it.

Negation (``!pattern``) is not supported; exclude lists only ever add.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable


def glob_to_regex(pattern: str) -> str:
    pat = pattern.strip()
    if pat.startswith("/"):
        pat = pat[1:]
        anchored = True
    else:
        anchored = "/" in pat.rstrip("/")
    pat = pat.rstrip("/")
    out: list[str] = []
    i, n = 0, len(pat)
    while i < n:
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        elif pat[i] == "[":
            end = pat.find("]", i + 2 if pat.startswith("[!", i) or pat.startswith("[^", i) else i + 1)
            body = pat[i + 1 : end] if end != -1 else ""
            if body[:1] in ("!", "^"):
                body = "^" + body[1:]
            cls = "[" + body.replace("\\", "\\\\") + "]"
            if end == -1 or body in ("", "^") or not _valid(cls):
                out.append(re.escape("["))  # not a usable class: match it literally
                i += 1
                continue
            out.append(cls)
            i = end + 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    body = "".join(out)
    if not anchored:
        body = "(?:.*/)?" + body
    # Matching a directory excludes everything inside it.
    return body + "(?:/.*)?"


def _valid(regex: str) -> bool:
    try:
        re.compile(regex)
    except re.error:
        return False
    return True


def invalid_globs(patterns: Iterable[str]) -> list[str]:
    """Patterns that cannot be used (for config warnings)."""
    return [p for p in patterns if p and p.strip() and not _valid(glob_to_regex(p))]


def compile_globs(patterns: Iterable[str]) -> Callable[[str], bool]:
    """A predicate that is true when a path matches any of ``patterns``;
    unusable patterns are ignored rather than failing every command."""
    parts = [f"(?:{rx})" for p in patterns if p and p.strip() and _valid(rx := glob_to_regex(p))]
    if not parts:
        return lambda _path: False
    rx = re.compile("^(?:" + "|".join(parts) + ")$", re.DOTALL)
    return lambda path: rx.match(path) is not None
