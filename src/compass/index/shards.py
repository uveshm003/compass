"""Markdown map shards: the LLM's view of the index (IX-06, IX-09, ADR 003).

One shard per directory at ``.compass/map/<dir>.md`` (the repo root is
``_root.md``) plus ``_index.md``, the folder tree with counts and purposes.
A shard over the token limit continues in ``<dir>~2.md``, ``<dir>~3.md``…
(NF-05). Output is sorted throughout so identical input gives byte-identical
files (NF-13), and files are only rewritten when their content changes.

Line format, from the Getting Started guide::

    # src/transport/  (4 files, 23 symbols) — Retry and reconnect handling
    ## reconnect.ts
    - L12  class ReconnectPolicy — Retry strategy for dropped connections
    - L30    method next(attempt: number): number — Delay in ms, exponential with jitter
    - L71  fn withRetry<T>(op, policy): Promise<T> ~ Wraps an async op with retries

``—`` marks an author-written doc and ``~`` a generated summary.
"""

from __future__ import annotations

import os
import posixpath
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from compass.index.docs import summary
from compass.index.store import DirStat, FileRow, Store, SymbolRow

INDEX_NAME = "_index"
ROOT_NAME = "_root"
PART_SEP = "~"

KIND_LABELS = {"function": "fn", "constant": "const", "variable": "var"}


def estimate_tokens(text: str) -> int:
    """Deliberately generous (about 3 characters per token), so a shard under
    the limit here stays under it for real tokenizers too."""
    return (len(text) + 2) // 3


_RESERVED = re.compile(r"_+(index|root)")


def _escape(component: str) -> str:
    """Keep directory names from colliding with ``_index``/``_root`` or with a
    sibling's ``~N`` parts: ``_index`` becomes ``__index`` and ``x~2`` becomes
    ``x~~2``. Every other name maps to itself."""
    escaped = component.replace(PART_SEP, PART_SEP * 2)
    return f"_{escaped}" if _RESERVED.fullmatch(component) else escaped


def shard_stem(directory: str) -> str:
    """Path of a directory's shard under map/, without ``.md``."""
    return "/".join(_escape(c) for c in directory.split("/")) if directory else ROOT_NAME


def shard_files(stem: str, parts: int) -> list[str]:
    return [f"{stem}.md"] + [f"{stem}{PART_SEP}{n}.md" for n in range(2, parts + 1)]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _display_dir(directory: str) -> str:
    return f"{directory}/" if directory else "./"


def _doc_suffix(doc: str | None, source: str | None) -> str:
    text = summary(doc)
    if not text:
        return ""
    return f" ~ {text}" if source == "generated" else f" — {text}"


def render_symbols(rows: list[SymbolRow]) -> list[str]:
    """One line per symbol; members indent under the container they sit in."""
    lines = []
    stack: list[tuple[SymbolRow, str]] = []  # open containers and their qualified names
    for row in rows:
        while stack and not (stack[-1][0].start_line <= row.start_line and row.end_line <= stack[-1][0].end_line):
            stack.pop()
        depth = None
        if row.parent:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][1] == row.parent:
                    depth = i + 1
                    del stack[depth:]
                    break
        signature = row.signature or row.name
        if depth is None:
            depth = 0
            stack.clear()
            if row.parent:
                # Owned but defined elsewhere (a Go method): name the owner.
                signature = f"{row.parent}.{signature}"
        label = KIND_LABELS.get(row.kind, row.kind)
        indent = "  " * depth
        line = f"- L{row.start_line}  {indent}{label} {signature}{_doc_suffix(row.doc, row.doc_source)}"
        if not lines or lines[-1] != line:  # `var a, b int` is one line for two symbols
            lines.append(line)
        qualified = f"{row.parent}.{row.name}" if row.parent else row.name
        stack.append((row, qualified))
    return lines


def render_dir(
    directory: str,
    files: list[FileRow],
    symbols: list[SymbolRow],
    purpose: str | None,
    token_limit: int,
) -> list[str]:
    """The text of each shard part for one directory."""
    by_file: dict[str, list[SymbolRow]] = {}
    for row in symbols:
        by_file.setdefault(row.path, []).append(row)
    sections = []
    for f in files:
        head = f"## {posixpath.basename(f.path)}{_doc_suffix(f.doc, 'author')}"
        sections.append([head, *render_symbols(by_file.get(f.path, []))])
    counts = f"{_plural(len(files), 'file')}, {_plural(len(symbols), 'symbol')}"
    about = _doc_suffix(purpose, "author")

    def header(part: int, total: int) -> str:
        which = f"; part {part} of {total}" if total > 1 else ""
        return f"# {_display_dir(directory)}  ({counts}{which}){about}"

    stem = posixpath.basename(shard_stem(directory))
    return _paginate(header, sections, token_limit, stem)


def render_index(stats: list[DirStat], purposes: dict[str, str], token_limit: int) -> list[str]:
    listed = {s.dir for s in stats}
    lines = []
    # Sort by path components so test/helpers/ stays under test/, not after test-d/.
    for s in sorted(stats, key=lambda s: s.dir.split("/") if s.dir else []):
        depth = 0
        up = posixpath.dirname(s.dir)
        while up:
            depth += up in listed
            up = posixpath.dirname(up)
        counts = f"{_plural(s.files, 'file')}, {_plural(s.symbols, 'symbol')}"
        lines.append(
            f"{'  ' * depth}- {_display_dir(s.dir)}  ({counts}){_doc_suffix(purposes.get(s.dir), 'author')}"
        )
    total = f"{_plural(sum(s.files for s in stats), 'file')}, {_plural(sum(s.symbols for s in stats), 'symbol')}"
    legend = (
        "Shards: .compass/map/<dir>.md (repo root: _root.md); "
        "`—` author doc, `~` generated summary."
    )

    def header(part: int, n: int) -> str:
        which = f"; part {part} of {n}" if n > 1 else ""
        return f"# Code map  ({total}{which})\n{legend}"

    return _paginate(header, [[line] for line in lines], token_limit, INDEX_NAME)


def _paginate(
    header: Callable[[int, int], str],
    sections: list[list[str]],
    token_limit: int,
    stem: str,
) -> list[str]:
    """Pack sections into parts under the token limit. A section that fits in a
    part is never split; one too big for any part fills the current part and
    continues in the next ones under a "(cont.)" heading."""
    reserve = estimate_tokens(header(99, 99) + "\n") + estimate_tokens(f"(continued in {stem}~99.md)\n")
    budget = max(token_limit - reserve, 50)
    parts: list[list[str]] = []
    current: list[str] = []
    used = 0
    for section in sections:
        costs = [estimate_tokens(line + "\n") for line in section]
        size = sum(costs)
        if size <= budget:
            if used + size > budget:
                parts.append(current)
                current, used = [], 0
            current.extend(section)
            used += size
            continue
        head, cont = section[0], f"{section[0]} (cont.)"
        if current and used + sum(costs[:2]) > budget:
            parts.append(current)
            current, used = [], 0
        current.append(head)
        used += costs[0]
        for line, cost in zip(section[1:], costs[1:]):
            if used + cost > budget:
                parts.append(current)
                current, used = [cont], estimate_tokens(cont + "\n")
            current.append(line)
            used += cost
    if current or not parts:
        parts.append(current)
    total = len(parts)
    names = shard_files(stem, total)
    out = []
    for i, body in enumerate(parts):
        lines = [header(i + 1, total), *body]
        if i + 1 < total:
            lines.append(f"(continued in {names[i + 1]})")
        out.append("\n".join(lines) + "\n")
    return out


def write_if_changed(path: Path, text: str) -> bool:
    data = text.encode("utf-8")
    try:
        if path.read_bytes() == data:
            return False
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return True


class ShardWriter:
    def __init__(self, store: Store, map_dir: Path, token_limit: int, index_files: frozenset[str]) -> None:
        self.store = store
        self.map_dir = map_dir
        self.token_limit = token_limit
        self.index_files = index_files

    def write_all(self) -> None:
        """Every shard plus the index; anything else under map/ is removed."""
        purposes = self.store.purposes(self.index_files)
        keep = set()
        for directory in self.store.dirs():
            keep.update(self._write_dir(directory, purposes))
        keep.update(self._write_index(purposes))
        for path in sorted(self.map_dir.rglob("*"), reverse=True):
            if path.is_file() and path not in keep:
                path.unlink()
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()

    def write_dirs(self, directories: Iterable[str]) -> None:
        """Rewrite the shards of ``directories`` (removing those now empty) and the index."""
        purposes = self.store.purposes(self.index_files)
        for directory in sorted(set(directories)):
            self._write_dir(directory, purposes)
        self._write_index(purposes)

    def _write_dir(self, directory: str, purposes: dict[str, str]) -> set[Path]:
        files = self.store.dir_files(directory)
        texts = []
        if files:
            symbols = self.store.dir_symbols(directory)
            texts = render_dir(directory, files, symbols, purposes.get(directory), self.token_limit)
        return self._put(shard_stem(directory), texts)

    def _write_index(self, purposes: dict[str, str]) -> set[Path]:
        return self._put(INDEX_NAME, render_index(self.store.dir_stats(), purposes, self.token_limit))

    def _put(self, stem: str, texts: list[str]) -> set[Path]:
        """Write ``stem``'s parts and delete parts left over from a longer version."""
        paths = [self.map_dir / name for name in shard_files(stem, len(texts))] if texts else []
        for path, text in zip(paths, texts):
            write_if_changed(path, text)
        folder = (self.map_dir / stem).parent
        base = posixpath.basename(stem)
        stale = re.compile(rf"^{re.escape(base)}(?:{re.escape(PART_SEP)}\d+)?\.md$")
        if folder.is_dir():
            keep = {p.name for p in paths}
            for entry in folder.iterdir():
                if entry.is_file() and stale.match(entry.name) and entry.name not in keep:
                    entry.unlink()
            self._prune(folder)
        return set(paths)

    def _prune(self, folder: Path) -> None:
        while folder != self.map_dir and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
