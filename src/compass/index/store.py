"""SQLite schema and queries: the source of truth for the code map (IX-05, ADR 003).

Everything is inserted in sorted order and nothing time-dependent is stored
beyond file mtimes, so a fresh build of the same working tree produces a
byte-identical ``index.db`` (NF-13).
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compass.index.model import FileInfo, FileParse, is_readme

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE files (
  path TEXT PRIMARY KEY,
  dir TEXT NOT NULL,
  lang TEXT,
  hash TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  doc TEXT
);
CREATE INDEX files_dir ON files(dir);

CREATE TABLE symbols (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  parent TEXT,
  signature TEXT,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  visibility TEXT,
  doc TEXT,
  doc_source TEXT CHECK (doc_source IN ('author', 'generated'))
);
CREATE INDEX symbols_name ON symbols(name);
CREATE INDEX symbols_path ON symbols(path);

CREATE TABLE imports (
  path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
  target TEXT NOT NULL,
  PRIMARY KEY (path, target)
) WITHOUT ROWID;
CREATE INDEX imports_target ON imports(target);

-- Listed but not indexed (binaries, oversized files, symlinks), remembered so a
-- refresh can skip them on size and mtime instead of re-reading them.
CREATE TABLE skipped (
  path TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL
) WITHOUT ROWID;
"""


class IndexUnavailable(Exception):
    """index.db is missing, unreadable, or from another schema version."""


@dataclass(frozen=True, slots=True)
class FileState:
    hash: str
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class FileRow:
    path: str
    lang: str | None
    doc: str | None


@dataclass(frozen=True, slots=True)
class SymbolRow:
    path: str
    name: str
    kind: str
    parent: str | None
    signature: str | None
    start_line: int
    end_line: int
    doc: str | None
    doc_source: str | None


@dataclass(frozen=True, slots=True)
class DirStat:
    dir: str
    files: int
    symbols: int


class Store:
    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self.conn = conn
        self.path = path

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def open(cls, path: Path, *, create: bool = False) -> Store:
        if not path.exists() and not create:
            raise IndexUnavailable("index not built yet")
        try:
            conn = sqlite3.connect(str(path), isolation_level=None, timeout=10.0)
        except sqlite3.Error as exc:
            raise IndexUnavailable(f"cannot open {path.name}: {exc}") from exc
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
            if tables == 0:
                if not create:
                    raise IndexUnavailable("index is empty")
                _create_schema(conn)
            else:
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version != SCHEMA_VERSION:
                    raise IndexUnavailable(f"index schema {version}, this Compass needs {SCHEMA_VERSION}")
            conn.execute("PRAGMA synchronous = NORMAL")
        except IndexUnavailable:
            conn.close()
            raise
        except sqlite3.DatabaseError as exc:
            conn.close()
            raise IndexUnavailable(f"corrupt index: {exc}") from exc
        return cls(conn, path)

    @classmethod
    def recreate(cls, path: Path) -> Store:
        """Delete an unusable index.db (and its WAL files) and start a new one."""
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(f"{path}{suffix}")
            except FileNotFoundError:
                pass
        return cls.open(path, create=True)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def write(self) -> Iterator[Store]:
        """One write transaction; readers keep seeing the old index until commit."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def compact(self) -> None:
        """VACUUM, so a full rebuild over an old file ends up with the same bytes
        as a fresh one."""
        self.conn.execute("VACUUM")

    # -- meta ---------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    # -- writes -------------------------------------------------------------

    def clear(self) -> None:
        self.conn.execute("DELETE FROM imports")
        self.conn.execute("DELETE FROM symbols")
        self.conn.execute("DELETE FROM files")
        self.conn.execute("DELETE FROM skipped")

    def put_file(self, info: FileInfo, parse: FileParse | None) -> None:
        self.conn.execute("DELETE FROM files WHERE path = ?", (info.path,))
        self.conn.execute("DELETE FROM skipped WHERE path = ?", (info.path,))
        lang = parse.lang if parse is not None and parse.lang else info.lang
        self.conn.execute(
            "INSERT INTO files (path, dir, lang, hash, size, mtime_ns, doc) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (info.path, info.dir, lang, info.hash, info.size, info.mtime_ns, parse.doc if parse else None),
        )
        if parse is None:
            return
        self.conn.executemany(
            "INSERT INTO symbols (path, name, kind, parent, signature, start_line, end_line,"
            " visibility, doc, doc_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    info.path, s.name, s.kind, s.parent, s.signature, s.start_line, s.end_line,
                    s.visibility, s.doc, s.doc_source,
                )
                for s in parse.symbols
            ],
        )
        self.conn.executemany(
            "INSERT OR IGNORE INTO imports (path, target) VALUES (?, ?)",
            [(info.path, target) for target in parse.imports],
        )

    def touch(self, path: str, size: int, mtime_ns: int) -> None:
        self.conn.execute("UPDATE files SET size = ?, mtime_ns = ? WHERE path = ?", (size, mtime_ns, path))

    def delete_files(self, paths: Iterable[str]) -> None:
        self.conn.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in paths])

    def put_skipped(self, entries: Iterable[tuple[str, int, int]]) -> None:
        self.conn.executemany("INSERT OR REPLACE INTO skipped (path, size, mtime_ns) VALUES (?, ?, ?)", entries)

    def delete_skipped(self, paths: Iterable[str]) -> None:
        self.conn.executemany("DELETE FROM skipped WHERE path = ?", [(p,) for p in paths])

    # -- reads --------------------------------------------------------------

    def file_states(self) -> dict[str, FileState]:
        rows = self.conn.execute("SELECT path, hash, size, mtime_ns FROM files")
        return {path: FileState(h, size, mtime) for path, h, size, mtime in rows}

    def skipped_states(self) -> dict[str, tuple[int, int]]:
        return {path: (size, mtime) for path, size, mtime in self.conn.execute("SELECT * FROM skipped")}

    def paths_under(self, prefix: str, table: str = "files") -> list[str]:
        if table not in ("files", "skipped"):
            raise ValueError(table)
        rows = self.conn.execute(
            f"SELECT path FROM {table} WHERE path = ? OR substr(path, 1, ?) = ? ORDER BY path",
            (prefix, len(prefix) + 1, prefix + "/"),
        )
        return [r[0] for r in rows]

    def dirs(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT dir FROM files ORDER BY dir")]

    def dir_files(self, directory: str) -> list[FileRow]:
        rows = self.conn.execute("SELECT path, lang, doc FROM files WHERE dir = ? ORDER BY path", (directory,))
        return [FileRow(*r) for r in rows]

    def dir_symbols(self, directory: str) -> list[SymbolRow]:
        rows = self.conn.execute(
            "SELECT s.path, s.name, s.kind, s.parent, s.signature, s.start_line, s.end_line,"
            " s.doc, s.doc_source FROM symbols s JOIN files f ON f.path = s.path"
            " WHERE f.dir = ? ORDER BY s.path, s.start_line, s.end_line DESC, s.id",
            (directory,),
        )
        return [SymbolRow(*r) for r in rows]

    def dir_stats(self) -> list[DirStat]:
        rows = self.conn.execute(
            "SELECT f.dir, COUNT(*), COALESCE(SUM(n), 0) FROM files f"
            " LEFT JOIN (SELECT path, COUNT(*) AS n FROM symbols GROUP BY path) s ON s.path = f.path"
            " GROUP BY f.dir ORDER BY f.dir"
        )
        return [DirStat(d, files, symbols) for d, files, symbols in rows]

    def purposes(self, index_files: frozenset[str]) -> dict[str, str]:
        """Each folder's description (IX-09): its README, else an index file's header."""
        best: dict[str, tuple[int, str, str]] = {}
        rows = self.conn.execute("SELECT dir, path, doc FROM files WHERE doc IS NOT NULL ORDER BY path")
        for directory, path, doc in rows:
            name = path.rsplit("/", 1)[-1]
            if is_readme(name):
                rank = 0
            elif name in index_files:
                rank = 1
            else:
                continue
            current = best.get(directory)
            if current is None or (rank, path) < (current[0], current[1]):
                best[directory] = (rank, path, doc)
        return {directory: doc for directory, (_rank, _path, doc) in best.items()}

    def counts(self) -> tuple[int, int]:
        files = self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        symbols = self.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        return files, symbols

    def dump(self) -> dict[str, list[dict[str, Any]]]:
        """All rows in a canonical order, without ids or mtimes (tests, diffs)."""
        def rows(sql: str) -> list[dict[str, Any]]:
            cur = self.conn.execute(sql)
            names = [c[0] for c in cur.description]
            return [dict(zip(names, r)) for r in cur]

        return {
            "files": rows("SELECT path, dir, lang, hash, size, doc FROM files ORDER BY path"),
            "symbols": rows(
                "SELECT path, name, kind, parent, signature, start_line, end_line, visibility, doc,"
                " doc_source FROM symbols ORDER BY path, start_line, end_line DESC, kind, name, parent"
            ),
            "imports": rows("SELECT path, target FROM imports ORDER BY path, target"),
            "skipped": [r[0] for r in self.conn.execute("SELECT path FROM skipped ORDER BY path")],
        }


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA page_size = 4096")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(f"BEGIN;{_SCHEMA}PRAGMA user_version = {SCHEMA_VERSION};COMMIT;")
