"""Row shapes shared by the parsers, the store and the shard writer."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

_README = re.compile(r"(?i)readme(\.(md|markdown|rst|txt|adoc))?")


def is_readme(path: str) -> bool:
    return _README.fullmatch(posixpath.basename(path)) is not None


def source_lines(data: bytes) -> list[str]:
    """A file's lines as tree-sitter and ctags number them: split on ``\\n``
    only. ``str.splitlines`` also splits on form feeds, U+2028 and lone ``\\r``,
    which would shift every line number after one."""
    lines = data.decode("utf-8", "replace").split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


@dataclass(frozen=True, slots=True)
class FileInfo:
    """One enumerated file. ``path`` is repo-relative POSIX."""

    path: str
    lang: str | None
    size: int
    hash: str
    mtime_ns: int
    is_test: bool = False

    @property
    def dir(self) -> str:
        return posixpath.dirname(self.path)


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    kind: str
    parent: str | None
    signature: str
    start_line: int
    end_line: int
    visibility: str | None
    doc: str | None
    doc_source: str | None = None

    def sort_key(self) -> tuple[int, int, int, str, str, str, str, str, str]:
        # Same range (one-liners): the container sorts before its members. The
        # key is total, so overloads on one line keep a fixed order (NF-13).
        nesting = self.parent.count(".") + 1 if self.parent else 0
        return (
            self.start_line, -self.end_line, nesting, self.kind, self.name, self.parent or "",
            self.signature, self.visibility or "", self.doc or "",
        )


@dataclass(frozen=True, slots=True)
class Ref:
    """A call site: ``name`` is called on ``line`` (for callers_of)."""

    name: str
    line: int
    kind: str = "call"


@dataclass(frozen=True, slots=True)
class FileParse:
    symbols: tuple[Symbol, ...] = ()
    imports: tuple[str, ...] = ()
    doc: str | None = None
    lang: str | None = None  # set when the parser, not the extension, decided it (ctags)
    refs: tuple[Ref, ...] = ()
