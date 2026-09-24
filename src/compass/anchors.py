"""Anchor tags (RO-02): comments that mark each AI change for review.

    x = retry(op)  # @ai:review <id> — retries only idempotent calls

The kinds are ``change`` (mechanical, skim), ``assume`` (an unverified
assumption), ``review`` (a judgment call) and ``todo`` (deliberately left
undone), followed by the task id and a note. Tags are written in each file's
own comment syntax; the scanner is one regex over every line, with no
per-language logic. The comment syntax only matters when ``/accept`` strips a
tag, and even then only a short list of openers and closers is involved.

Two things look like tags but are not: ``@ai:`` right after a backtick (a
Markdown code span quoting a tag, as documentation about anchors does) and
``@ai:`` glued to a preceding word character.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from compass.repo import run_git

KINDS = ("review", "assume", "todo", "change")  # the order a reviewer reads them in
KIND_TITLES = {"review": "Review", "assume": "Assumptions", "todo": "TODO", "change": "Mechanical"}

ANCHOR = re.compile(
    r"(?<![\w`\\])@ai:(change|assume|review|todo)[ \t]+"
    r"([A-Za-z0-9](?:[\w.-]*[A-Za-z0-9])?)\b"  # the task id
    r"[ \t]*(?:[—–:-]+[ \t]*)?(.*)$"  # an optional dash or colon, then the note
)

# Block-comment closers a note may run into, longest first.
_CLOSERS = ("--%>", "-->", "*/", "#}", "-}", "*)", "%>")
_OPENER_OF = {"--%>": "<%--", "-->": "<!--", "*/": "/*", "#}": "{#", "-}": "{-", "*)": "(*", "%>": "<%"}
# Line-comment openers that may follow code on the same line, longest first.
_TRAILING_OPENERS = ("//", "--", "#")
# Openers only trusted at the start of a line: after code, `;` or `*` is code.
_LINE_OPENERS = ("//", "--", "#", ";", "%", "'", "*", "!")
_BINARY_SNIFF = 8192


@dataclass(frozen=True, order=True)
class Anchor:
    path: str
    line: int
    kind: str
    task: str
    note: str


def parse_line(text: str) -> tuple[str, str, str, int] | None:
    """(kind, task, note, column) for the anchor on ``text``, if any."""
    m = ANCHOR.search(text)
    if m is None:
        return None
    return m.group(1), m.group(2), _clean_note(m.group(3)), m.start()


def scan_text(path: str, text: str, task: str | None = None) -> list[Anchor]:
    found = []
    for number, line in enumerate(text.split("\n"), 1):
        if "@ai:" not in line:
            continue
        parsed = parse_line(line.rstrip("\r"))
        if parsed and (task is None or parsed[1] == task):
            found.append(Anchor(path, number, parsed[0], parsed[1], parsed[2]))
    return found


def is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\0" in f.read(_BINARY_SNIFF)
    except OSError:
        return False


def scan_file(root: Path, rel: str, task: str | None = None) -> list[Anchor]:
    """Anchors in one file; nothing for binary, missing or unreadable files."""
    try:
        data = (root / rel).read_bytes()
    except OSError:
        return []
    if b"\0" in data[:_BINARY_SNIFF]:
        return []
    return scan_text(rel, data.decode("utf-8", "replace"), task)


def scan_repo(root: Path, task: str | None = None) -> list[Anchor]:
    """Every anchor in tracked and untracked (not ignored) files, via git grep."""
    proc = run_git(root, "grep", "-z", "-n", "-I", "--untracked", "--no-color", "-F", "-e", "@ai:", "--", ":!.compass")
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"git grep failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    found = []
    for record in proc.stdout.split(b"\n"):
        parts = record.split(b"\0", 2)
        if len(parts) != 3:
            continue
        path = parts[0].decode("utf-8", "surrogateescape")
        parsed = parse_line(parts[2].decode("utf-8", "replace").rstrip("\r"))
        if parsed and (task is None or parsed[1] == task):
            found.append(Anchor(path, int(parts[1]), parsed[0], parsed[1], parsed[2]))
    return sorted(found)


def staged_anchors(root: Path) -> list[Anchor]:
    """Anchors on lines a commit would add (``git diff --cached``), for the
    pre-commit check (RO-05). Only added lines count, so a tag quoted in an
    already committed file never blocks later commits."""
    proc = run_git(
        root, "-c", "core.quotePath=false", "diff", "--cached", "-U0", "--no-color", "--no-ext-diff",
        "--diff-filter=ACMR", "--no-renames",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    found = []
    path: str | None = None
    number = 0
    in_header = False  # between `diff --git` and the first hunk: where `+++ b/path` lives
    for raw in proc.stdout.split(b"\n"):
        line = raw.decode("utf-8", "replace")
        if line.startswith("diff --git "):
            in_header, path = True, None
        elif line.startswith("@@"):
            in_header = False
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            number = int(m.group(1)) if m else 0
        elif in_header:
            if line.startswith("+++ "):
                target = line[4:].rstrip("\r").removesuffix("\t")  # git adds a tab after names with spaces
                path = None if target == "/dev/null" else _diff_path(target)
        elif line.startswith("+") and path is not None:  # an added line, even one reading `++ x`
            parsed = parse_line(line[1:].rstrip("\r"))
            if parsed:
                found.append(Anchor(path, number, parsed[0], parsed[1], parsed[2]))
            number += 1
    return sorted(found)


def _diff_path(target: str) -> str:
    if target.startswith('"') and target.endswith('"'):  # git quotes names with control characters
        target = bytes(target[1:-1], "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8", "replace")
    return target[2:] if target.startswith("b/") else target


def _clean_note(note: str) -> str:
    note = note.strip()
    for closer in _CLOSERS:
        if note.endswith(closer):
            note = note[: -len(closer)].rstrip()
            break
    return note


# -- stripping (for /accept) ------------------------------------------------------


def strip_line(line: str) -> str | None:
    """``line`` without its anchor comment; None when nothing else is left and
    the line should go. ``line`` has no line ending."""
    m = ANCHOR.search(line)
    if m is None:
        return line
    start = m.start()
    head, rest = line[:start], line[start:]
    # A block comment closes on this line only if it also opened on it.
    closer_at = min(
        ((rest.find(c), c) for c in _CLOSERS if c in rest and _OPENER_OF[c] in head), default=None
    )
    if closer_at is not None:
        # Drop the opener too when the comment held only the tag.
        offset, closer = closer_at
        tail = rest[offset + len(closer) :]
        opener = _OPENER_OF[closer]
        where = head.rfind(opener)
        # `/**`, `/*!` and `<!---` open a comment as well as `/*` and `<!--`.
        if where != -1 and not head[where + len(opener) :].strip().strip(opener + "!"):
            kept = head[:where].rstrip() + tail
        else:
            kept = head.rstrip() + " " + closer + tail
    else:
        kept = _without_line_comment(head)
    if not kept.strip() or kept.strip() in ("{}", "{ }"):  # `{/* ... */}` in JSX
        return None
    return kept


def _without_line_comment(head: str) -> str:
    """``head`` minus a comment opener left with nothing after it."""
    stripped = head.rstrip()
    if not stripped.lstrip(" \t").strip(_opener_chars()):
        return ""  # only comment punctuation before the tag (`#`, `///`, `//!`, ` * `): a comment line
    for opener in _TRAILING_OPENERS:
        if stripped.endswith(opener):
            # The whole run goes: `x = 1  /// tag` and `x = 1  ## tag` both leave `x = 1`.
            return stripped.rstrip(opener[0]).rstrip()
    return stripped  # the tag sat inside a longer comment: keep that comment


def _opener_chars() -> str:
    return "".join(sorted(set("".join(_LINE_OPENERS))))


@dataclass
class StripResult:
    path: str
    removed: int  # anchors taken out
    deleted_lines: list[int]  # original line numbers of lines deleted outright


def strip_file(root: Path, rel: str, task: str) -> StripResult | None:
    """Remove ``task``'s anchors from one file, keeping its line endings and
    every other byte. None when the file has none (or cannot be read)."""
    path = root / rel
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:_BINARY_SNIFF]:
        return None
    text = data.decode("utf-8", "surrogateescape")
    lines = text.split("\n")
    out: list[str] = []
    removed = 0
    deleted: list[int] = []
    for number, line in enumerate(lines, 1):
        body, cr = (line[:-1], "\r") if line.endswith("\r") else (line, "")
        parsed = parse_line(body) if "@ai:" in body else None
        if parsed is None or parsed[1] != task:
            out.append(line)
            continue
        removed += 1
        kept = strip_line(body)
        if kept is None:
            deleted.append(number)
        else:
            out.append(kept + cr)
    if not removed:
        return None
    path.write_bytes("\n".join(out).encode("utf-8", "surrogateescape"))
    return StripResult(rel, removed, deleted)


def shift_line(line: int, deleted: Iterable[int]) -> int:
    """Where ``line`` ends up once ``deleted`` lines are gone. A deleted tag
    line maps to the line that moves up into its place: the code it annotated."""
    return line - sum(1 for d in deleted if d < line)
