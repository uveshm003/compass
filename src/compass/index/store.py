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

SCHEMA_VERSION = 2

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
  doc TEXT,
  is_test INTEGER NOT NULL DEFAULT 0
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

-- `resolved` is the repo file (or, for Go, package directory) an import points
-- at, or NULL for external packages; recomputed when files come and go.
CREATE TABLE imports (
  path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
  target TEXT NOT NULL,
  resolved TEXT,
  PRIMARY KEY (path, target)
) WITHOUT ROWID;
CREATE INDEX imports_target ON imports(target);
CREATE INDEX imports_resolved ON imports(resolved);

-- Call sites by callee name, for callers_of; the caller is found by line range.
CREATE TABLE refs (
  path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
  name TEXT NOT NULL,
  line INTEGER NOT NULL,
  kind TEXT NOT NULL,
  PRIMARY KEY (path, line, name, kind)
) WITHOUT ROWID;
CREATE INDEX refs_name ON refs(name);

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


@dataclass(frozen=True, slots=True)
class SymbolHit:
    """A symbol row with what the query tools show about its file."""

    path: str
    name: str
    kind: str
    parent: str | None
    signature: str | None
    start_line: int
    end_line: int
    visibility: str | None
    doc: str | None
    doc_source: str | None
    is_test: bool

    def as_row(self) -> SymbolRow:
        return SymbolRow(
            self.path, self.name, self.kind, self.parent, self.signature,
            self.start_line, self.end_line, self.doc, self.doc_source,
        )


_HIT_COLUMNS = (
    "s.path, s.name, s.kind, s.parent, s.signature, s.start_line, s.end_line,"
    " s.visibility, s.doc, s.doc_source, f.is_test"
)


def like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
        self.conn.execute("DELETE FROM refs")
        self.conn.execute("DELETE FROM imports")
        self.conn.execute("DELETE FROM symbols")
        self.conn.execute("DELETE FROM files")
        self.conn.execute("DELETE FROM skipped")

    def put_file(self, info: FileInfo, parse: FileParse | None) -> None:
        self.conn.execute("DELETE FROM files WHERE path = ?", (info.path,))
        self.conn.execute("DELETE FROM skipped WHERE path = ?", (info.path,))
        lang = parse.lang if parse is not None and parse.lang else info.lang
        self.conn.execute(
            "INSERT INTO files (path, dir, lang, hash, size, mtime_ns, doc, is_test)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                info.path, info.dir, lang, info.hash, info.size, info.mtime_ns,
                parse.doc if parse else None, int(info.is_test),
            ),
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
        self.conn.executemany(
            "INSERT OR IGNORE INTO refs (path, name, line, kind) VALUES (?, ?, ?, ?)",
            [(info.path, r.name, r.line, r.kind) for r in parse.refs],
        )

    def import_rows(self, paths: Iterable[str] | None = None) -> list[tuple[str, str, str | None, str | None]]:
        """(importer, target, importer language, current resolution), for resolving."""
        sql = "SELECT i.path, i.target, f.lang, i.resolved FROM imports i JOIN files f ON f.path = i.path"
        if paths is None:
            return list(self.conn.execute(sql + " ORDER BY i.path, i.target"))
        rows = []
        for path in sorted(set(paths)):
            rows.extend(self.conn.execute(sql + " WHERE i.path = ? ORDER BY i.target", (path,)))
        return rows

    def set_resolved(self, rows: Iterable[tuple[str, str, str | None]]) -> None:
        self.conn.executemany(
            "UPDATE imports SET resolved = ? WHERE path = ? AND target = ?",
            [(resolved, path, target) for path, target, resolved in rows],
        )

    def langs(self) -> dict[str, str | None]:
        return dict(self.conn.execute("SELECT path, lang FROM files"))

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

    # -- query tools ----------------------------------------------------------

    def find_symbols(
        self,
        needle: str,
        kind: str | None = None,
        path: str | None = None,
        parent: str | None = None,
        limit: int = 50,
    ) -> list[SymbolHit]:
        """Names containing ``needle`` (case-insensitive), exact matches first,
        then symbols whose doc mentions it; tests rank after sources."""
        esc = like_escape(needle)
        params = {
            "n": needle, "prefix": esc + "%", "contains": "%" + esc + "%", "kind": kind,
            "path": path, "pathprefix": like_escape(path or "") + "/%",
            "parent": parent, "parentsuffix": "%." + like_escape(parent or ""), "limit": limit,
        }
        sql = (
            f"SELECT {_HIT_COLUMNS} FROM symbols s JOIN files f ON f.path = s.path"
            " WHERE (s.name LIKE :contains ESCAPE '\\' OR s.doc LIKE :contains ESCAPE '\\')"
            " AND (:kind IS NULL OR s.kind = :kind)"
            " AND (:path IS NULL OR s.path = :path OR s.path LIKE :pathprefix ESCAPE '\\')"
            " AND (:parent IS NULL OR s.parent = :parent OR s.parent LIKE :parentsuffix ESCAPE '\\')"
            " ORDER BY CASE"
            "   WHEN s.name = :n THEN 0 WHEN s.name = :n COLLATE NOCASE THEN 1"
            "   WHEN s.name LIKE :prefix ESCAPE '\\' THEN 2 WHEN s.name LIKE :contains ESCAPE '\\' THEN 3"
            "   ELSE 4 END,"
            " f.is_test, length(s.name), s.path, s.start_line, s.id LIMIT :limit"
        )
        return [SymbolHit(*r[:10], bool(r[10])) for r in self.conn.execute(sql, params)]

    def exact_symbols(self, name: str, parent: str | None = None) -> list[SymbolHit]:
        """Symbols named exactly ``name`` (falling back to any case)."""
        for collate in ("", " COLLATE NOCASE"):
            sql = (
                f"SELECT {_HIT_COLUMNS} FROM symbols s JOIN files f ON f.path = s.path"
                f" WHERE s.name = ?{collate}"
                " AND (? IS NULL OR s.parent = ? OR s.parent LIKE ? ESCAPE '\\')"
                " ORDER BY f.is_test, s.path, s.start_line, s.id"
            )
            suffix = "%." + like_escape(parent or "")
            rows = [SymbolHit(*r[:10], bool(r[10])) for r in self.conn.execute(sql, (name, parent, parent, suffix))]
            if rows:
                return rows
        return []

    def file_symbols(self, path: str) -> list[SymbolHit]:
        sql = (
            f"SELECT {_HIT_COLUMNS} FROM symbols s JOIN files f ON f.path = s.path"
            " WHERE s.path = ? ORDER BY s.start_line, s.end_line DESC, s.id"
        )
        return [SymbolHit(*r[:10], bool(r[10])) for r in self.conn.execute(sql, (path,))]

    def file_info(self, path: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT path, dir, lang, doc, is_test, size, mtime_ns FROM files WHERE path = ?", (path,)
        ).fetchone()
        if row is None:
            return None
        keys = ("path", "dir", "lang", "doc", "is_test", "size", "mtime_ns")
        info = dict(zip(keys, row))
        info["is_test"] = bool(info["is_test"])
        return info

    def paths_named(self, name: str, limit: int = 10) -> list[str]:
        """Indexed paths ending in ``name``, for "did you mean" answers."""
        rows = self.conn.execute(
            "SELECT path FROM files WHERE path = ? OR path LIKE ? ESCAPE '\\' ORDER BY length(path), path LIMIT ?",
            (name, "%/" + like_escape(name), limit),
        )
        return [r[0] for r in rows]

    def has_dir(self, directory: str) -> bool:
        """Whether any indexed file lies in ``directory`` or below it."""
        row = self.conn.execute(
            "SELECT 1 FROM files WHERE dir = ? OR dir LIKE ? ESCAPE '\\' LIMIT 1",
            (directory, like_escape(directory) + "/%"),
        ).fetchone()
        return row is not None

    def source_files_under(self, directory: str) -> list[str]:
        """Non-test files with a language in ``directory`` or below it."""
        rows = self.conn.execute(
            "SELECT path FROM files WHERE is_test = 0 AND lang IS NOT NULL"
            " AND (dir = ? OR dir LIKE ? ESCAPE '\\') ORDER BY path",
            (directory, like_escape(directory) + "/%"),
        )
        return [r[0] for r in rows]

    def sources_with_stem(self, stem: str, lang: str | None) -> list[str]:
        """Non-test files of ``lang`` named ``stem`` plus an extension."""
        rows = self.conn.execute(
            "SELECT path FROM files WHERE is_test = 0 AND lang IS ?"
            " AND (path LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\') ORDER BY path",
            (lang, like_escape(stem) + ".%", "%/" + like_escape(stem) + ".%"),
        )
        return [p for (p,) in rows if p.rsplit("/", 1)[-1].rsplit(".", 1)[0] == stem]

    def dirs_like(self, fragment: str, limit: int = 10) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT dir FROM files WHERE dir LIKE ? ESCAPE '\\' ORDER BY length(dir), dir LIMIT ?",
            ("%" + like_escape(fragment) + "%", limit),
        )
        return [r[0] for r in rows]

    def imports_of(self, path: str) -> list[tuple[str, str | None]]:
        return list(self.conn.execute("SELECT target, resolved FROM imports WHERE path = ? ORDER BY target", (path,)))

    def importers_of(self, resolved: Iterable[str]) -> list[tuple[str, str, str]]:
        """(importer, raw target, resolved) for imports that resolve to one of ``resolved``."""
        targets = sorted(set(resolved))
        marks = ",".join("?" * len(targets))
        sql = f"SELECT path, target, resolved FROM imports WHERE resolved IN ({marks}) ORDER BY path, target"
        return list(self.conn.execute(sql, targets)) if targets else []

    def importers_under(self, directory: str) -> list[tuple[str, str, str]]:
        """(importer, raw target, resolved) for imports that resolve to
        ``directory`` or anything below it, from files anywhere."""
        rows = self.conn.execute(
            "SELECT path, target, resolved FROM imports WHERE resolved = ? OR resolved LIKE ? ESCAPE '\\'"
            " ORDER BY path, target",
            (directory, like_escape(directory) + "/%"),
        )
        return list(rows)

    def imports_starting(self, prefix: str) -> list[tuple[str, str, str | None]]:
        """(importer, raw target, importer language) for targets equal to or
        starting with ``prefix``; the caller checks the separator per language."""
        rows = self.conn.execute(
            "SELECT i.path, i.target, f.lang FROM imports i JOIN files f ON f.path = i.path"
            " WHERE i.target = ? OR i.target LIKE ? ESCAPE '\\' ORDER BY i.path, i.target",
            (prefix, like_escape(prefix) + "%"),
        )
        return list(rows)

    def refs_named(self, name: str, limit: int = 500) -> list[tuple[str, int, str]]:
        rows = self.conn.execute(
            "SELECT path, line, kind FROM refs WHERE name = ? ORDER BY path, line LIMIT ?", (name, limit)
        )
        return list(rows)

    def refs_in_tests(self, name: str, inline_modules: Iterable[tuple[str, str]] = ()) -> list[tuple[str, int]]:
        """Call sites of ``name`` in test files, and in the inline test modules
        (``(language, module name)``, like Rust's ``mod tests``) of source files."""
        rows = set(
            self.conn.execute(
                "SELECT r.path, r.line FROM refs r JOIN files f ON f.path = r.path WHERE r.name = ? AND f.is_test = 1",
                (name,),
            )
        )
        for lang, module in sorted(set(inline_modules)):
            rows.update(
                self.conn.execute(
                    "SELECT r.path, r.line FROM refs r JOIN files f ON f.path = r.path"
                    " WHERE r.name = ? AND f.is_test = 0 AND f.lang = ? AND EXISTS ("
                    "   SELECT 1 FROM symbols s WHERE s.path = r.path AND s.kind = 'module' AND s.name = ?"
                    "   AND s.parent IS NULL AND r.line BETWEEN s.start_line AND s.end_line)",
                    (name, lang, module),
                )
            )
        return sorted(rows)

    def ref_count(self, name: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM refs WHERE name = ?", (name,)).fetchone()[0]

    def symbol_names(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT name FROM symbols ORDER BY name")]

    def test_files(self) -> list[tuple[str, str | None]]:
        return list(self.conn.execute("SELECT path, lang FROM files WHERE is_test = 1 ORDER BY path"))

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
            "files": rows("SELECT path, dir, lang, hash, size, doc, is_test FROM files ORDER BY path"),
            "symbols": rows(
                "SELECT path, name, kind, parent, signature, start_line, end_line, visibility, doc,"
                " doc_source FROM symbols ORDER BY path, start_line, end_line DESC, kind, name, parent"
            ),
            "imports": rows("SELECT path, target, resolved FROM imports ORDER BY path, target"),
            "refs": rows("SELECT path, line, name, kind FROM refs ORDER BY path, line, name, kind"),
            "skipped": [r[0] for r in self.conn.execute("SELECT path FROM skipped ORDER BY path")],
        }


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA page_size = 4096")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(f"BEGIN;{_SCHEMA}PRAGMA user_version = {SCHEMA_VERSION};COMMIT;")
