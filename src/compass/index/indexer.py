"""Build and update the index (Steps 2–3, IX-07, IX-08).

Every trigger ends up here:

- ``build(full=True)``: re-parse everything, rewrite every shard.
- ``build()``: stat every file; re-hash those whose size or mtime moved;
  re-parse those whose hash changed (IX-07). Used by ``compass index``,
  SessionStart and the git hooks. Catches anything git changed on disk, so
  branch switches never leave stale symbols.
- ``update(paths)``: hash-check specific files; used by the PostToolUse hook.

A change of queries or index settings changes the index fingerprint, and the
next run rebuilds from scratch. ctags availability is deliberately not part of
it: it depends on PATH, which differs between a terminal and an IDE, and a
fingerprint that flips would force a rebuild on every switch. After installing
ctags, run ``compass index --full`` once.

Shards are written inside the same SQLite transaction as the rows they show:
if writing them fails, the rows roll back and the next run retries, so the two
representations never drift apart (ADR 003).
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import time
from dataclasses import dataclass, field

from compass.config import Config, load_config
from compass.files import Skipped, list_paths, scan
from compass.globs import compile_globs
from compass.index import ctags
from compass.index.docs import readme_summary
from compass.index.model import FileInfo, FileParse, is_readme
from compass.index.parser import parse_source
from compass.index.resolve import Resolver, feeds_resolution
from compass.index.shards import INDEX_NAME, ShardWriter
from compass.index.store import IndexUnavailable, Store
from compass.languages import load_registry
from compass.lock import file_lock
from compass.log import log_error
from compass.repo import Repo

# Bump when the parser or shard writer produce different output for the same
# input, so existing indexes rebuild instead of mixing old and new rows.
# 2: call references, resolved imports, test-file flags (M2).
INDEX_FORMAT = 2


class FullBuildNeeded(Exception):
    """The index is missing or was built with other queries or settings."""


@dataclass
class IndexResult:
    mode: str  # "full" or "incremental"
    files: int = 0
    parsed: int = 0
    removed: int = 0
    symbols: int = 0
    seconds: float = 0.0
    changed_dirs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "files": self.files,
            "parsed": self.parsed,
            "removed": self.removed,
            "symbols": self.symbols,
            "seconds": round(self.seconds, 3),
        }


class Indexer:
    def __init__(self, repo: Repo, config: Config | None = None) -> None:
        self.repo = repo
        self.config = config if config is not None else load_config(repo.root)
        self.settings = self.config.index
        self.registry = load_registry()
        self.is_excluded = compile_globs(self.settings.exclude)
        self.feeds_resolution = feeds_resolution(self.registry)

    # -- public entry points --------------------------------------------------

    def fingerprint(self) -> str:
        parts = [
            str(INDEX_FORMAT),
            self.registry.fingerprint,
            json.dumps(self.config.data["index"], sort_keys=True),
        ]
        return hashlib.blake2b("\0".join(parts).encode(), digest_size=16).hexdigest()

    def map_intact(self) -> bool:
        return (self.repo.map_dir / f"{INDEX_NAME}.md").is_file()

    def build(
        self,
        full: bool = False,
        lock_timeout: float = 600.0,
        allow_full: bool = True,
        repair: bool = False,
    ) -> IndexResult:
        """Refresh the index, or rebuild it when ``full`` or when it must.

        With ``allow_full=False`` a needed rebuild raises FullBuildNeeded instead,
        for callers on a latency budget that should hand the work off.
        ``repair`` rewrites every shard from the index even when nothing changed.
        """
        started = time.perf_counter()
        self.repo.ensure_state_dir()
        with file_lock(self.repo.lock_path, lock_timeout):
            store, fresh = self._open_for_write()
            with store:
                if fresh or full or store.get_meta("fingerprint") != self.fingerprint():
                    if not (full or allow_full):
                        raise FullBuildNeeded()
                    result = self._full(store)
                else:
                    result = self._refresh(store, repair)
        result.seconds = time.perf_counter() - started
        return result

    def update(self, paths: list[str], lock_timeout: float = 600.0, allow_full: bool = True) -> IndexResult:
        """Re-index specific repo-relative paths if their content changed."""
        started = time.perf_counter()
        self.repo.ensure_state_dir()
        with file_lock(self.repo.lock_path, lock_timeout):
            store, fresh = self._open_for_write()
            with store:
                if fresh or store.get_meta("fingerprint") != self.fingerprint():
                    if not allow_full:
                        raise FullBuildNeeded()
                    result = self._full(store)
                else:
                    result = self._update(store, paths)
        result.seconds = time.perf_counter() - started
        return result

    def stale_paths(self) -> list[str] | None:
        """Paths a refresh would re-check, without taking the lock; None when the
        index is missing, unreadable or built with other settings."""
        try:
            store = Store.open(self.repo.db_path)
        except IndexUnavailable:
            return None
        with store:
            try:
                if store.get_meta("fingerprint") != self.fingerprint():
                    return None
                files = {p: (s.size, s.mtime_ns) for p, s in store.file_states().items()}
                skipped = store.skipped_states()
            except Exception:
                return None
        candidates, gone = self._changed_since(files, skipped)
        return sorted([path for path, _st in candidates] + gone)

    # -- internals ------------------------------------------------------------

    def _open_for_write(self) -> tuple[Store, bool]:
        path = self.repo.db_path
        existed = path.exists()
        try:
            store = Store.open(path, create=True)
        except IndexUnavailable as exc:
            log_error(self.repo.root, "index", message=f"rebuilding index: {exc}")
            return Store.recreate(path), True
        if not existed:
            return store, True
        try:
            empty = store.get_meta("fingerprint") is None
        except Exception:
            store.close()
            return Store.recreate(path), True
        return store, empty

    def _full(self, store: Store) -> IndexResult:
        result = IndexResult("full")
        items: list[tuple[FileInfo, bytes]] = []
        skipped: list[tuple[str, int, int]] = []
        for path in list_paths(self.repo.root, self.is_excluded):
            scanned = scan(self.repo.root, path, self.registry, self.settings.max_file_bytes)
            if isinstance(scanned, Skipped):
                skipped.append((path, scanned.size, scanned.mtime_ns))
            elif scanned is not None:
                items.append(scanned)
        records = self._parse_all(items)
        with store.write():
            store.clear()
            store.put_skipped(skipped)
            for info, parse in records:
                store.put_file(info, parse)
            self._resolve_imports(store, None)
            store.set_meta("fingerprint", self.fingerprint())
            self._shards(store).write_all()  # before the commit; see the module docstring
        store.compact()
        result.files, result.symbols = store.counts()
        result.parsed = len(records)
        return result

    def _changed_since(
        self, files: dict[str, tuple[int, int]], skipped: dict[str, tuple[int, int]]
    ) -> tuple[list[tuple[str, os.stat_result]], list[str]]:
        """Listed paths whose size or mtime moved (or are new), and paths the
        index knows that are no longer listed."""
        unseen = {**skipped, **files}
        candidates = []
        for path in list_paths(self.repo.root, self.is_excluded):
            known = unseen.pop(path, None)
            try:
                st = os.lstat(self.repo.root / path)
            except OSError:
                if known is not None:
                    unseen[path] = known  # vanished between listing and stat
                continue
            if known != (st.st_size, st.st_mtime_ns):
                candidates.append((path, st))
        return candidates, sorted(unseen)

    def _refresh(self, store: Store, repair: bool = False) -> IndexResult:
        known = store.file_states()
        skipped = store.skipped_states()
        candidates, gone = self._changed_since({p: (s.size, s.mtime_ns) for p, s in known.items()}, skipped)
        # Whatever the index knows but git no longer lists was deleted, ignored or excluded.
        return self._apply(store, IndexResult("incremental"), candidates, gone, known, repair)

    def _update(self, store: Store, paths: list[str]) -> IndexResult:
        wanted = sorted({p.strip("/") for p in paths if p and p.strip("/")})
        listed = set(list_paths(self.repo.root, self.is_excluded, only=wanted))
        candidates: list[tuple[str, os.stat_result]] = []
        gone: set[str] = set()
        for path in sorted(listed):
            try:
                candidates.append((path, os.lstat(self.repo.root / path)))
            except OSError:
                gone.add(path)
        for path in wanted:
            if path not in listed:
                # Deleted, ignored or excluded: drop it (or a whole directory) from the index.
                for table in ("files", "skipped"):
                    gone.update(p for p in store.paths_under(path, table) if p not in listed)
        return self._apply(store, IndexResult("incremental"), candidates, sorted(gone), store.file_states())

    def _apply(self, store, result, candidates, gone, known, repair: bool = False) -> IndexResult:
        changed: list[tuple[FileInfo, bytes]] = []
        touched: list[FileInfo] = []
        skipped: list[tuple[str, int, int]] = []
        removed = [p for p in gone if p in known]
        unskip = list(gone)
        for path, st in candidates:
            scanned = scan(self.repo.root, path, self.registry, self.settings.max_file_bytes, st)
            if scanned is None or isinstance(scanned, Skipped):
                if path in known:
                    removed.append(path)
                if scanned is None:
                    unskip.append(path)
                else:
                    skipped.append((path, scanned.size, scanned.mtime_ns))
                continue
            info, data = scanned
            old = known.get(path)
            if old is not None and old.hash == info.hash:
                if (old.size, old.mtime_ns) != (info.size, info.mtime_ns):
                    touched.append(info)
                continue
            changed.append((info, data))
        records = self._parse_all(changed)
        dirs = sorted({posixpath.dirname(p) for p in removed} | {info.dir for info, _ in records})
        rewrite_all = repair or not self.map_intact()
        if records or removed or touched or skipped or unskip or rewrite_all:
            with store.write():
                store.delete_files(removed)
                store.delete_skipped(unskip)
                store.put_skipped(skipped)
                for info in touched:
                    store.touch(info.path, info.size, info.mtime_ns)
                for info, parse in records:
                    store.put_file(info, parse)
                if records or removed:
                    # A new or deleted file (or a changed go.mod or tsconfig.json)
                    # can change what any import resolves to; an edit of any
                    # other file only affects its own imports.
                    changed = [info.path for info, _ in records]
                    reresolve_all = (
                        bool(removed)
                        or any(p not in known for p in changed)
                        or any(self.feeds_resolution(posixpath.basename(p)) for p in changed)
                    )
                    self._resolve_imports(store, None if reresolve_all else changed)
                writer = self._shards(store)  # before the commit; see the module docstring
                if rewrite_all:
                    writer.write_all()
                elif dirs:
                    writer.write_dirs(dirs)
        result.files, result.symbols = store.counts()
        result.parsed = len(records)
        result.removed = len(removed)
        result.changed_dirs = dirs
        return result

    def _parse_all(self, items: list[tuple[FileInfo, bytes]]) -> list[tuple[FileInfo, FileParse | None]]:
        """Parse with tree-sitter where a query exists, ctags for the rest."""
        records: list[tuple[FileInfo, FileParse | None]] = []
        fallback: dict[str, bytes] = {}
        for info, data in items:
            spec = self.registry.get(info.lang)
            if spec is not None:
                records.append((info, self._parse_one(spec, info, data)))
            elif is_readme(info.path):
                records.append((info, FileParse(doc=readme_summary(data.decode("utf-8", "replace")))))
            else:
                fallback[info.path] = data
                records.append((info, None))
        if fallback:
            try:
                tagged = ctags.ctags_symbols(self.repo.root, fallback)
            except Exception as exc:
                log_error(self.repo.root, "ctags", exc)
                tagged = {}
            records = [(info, tagged.get(info.path, parse)) for info, parse in records]
        records.sort(key=lambda r: r[0].path)
        return self._with_generated_docs(records, items)

    def _with_generated_docs(self, records, items):
        """Summaries `compass enrich` wrote earlier, for symbols still without
        a doc comment (DL-05). Nothing happens unless the cache exists, so a
        repo that never enriched indexes exactly as before (NF-13)."""
        from compass import enrich

        if not enrich.summaries_exist(self.repo.root):
            return records
        data = {info.path: raw for info, raw in items}
        cache = enrich.Cache.open(self.repo)
        try:
            return [(info, enrich.with_cached_docs(cache, info.path, parse, data[info.path])) for info, parse in records]
        except Exception as exc:  # a broken cache must not stop the index
            log_error(self.repo.root, "enrich cache", exc)
            return records
        finally:
            cache.close()

    def apply_generated_docs(self, updates: list[tuple[str, str, str, str, int]], lock_timeout: float = 30.0) -> int:
        """Set ``(summary, path, name, kind, start_line)`` as generated docs on
        symbols that still have none, and rewrite their shards. Returns how
        many symbols changed."""
        self.repo.ensure_state_dir()
        with file_lock(self.repo.lock_path, lock_timeout):
            store, fresh = self._open_for_write()
            with store:
                if fresh:
                    return 0
                changed = 0
                dirs = set()
                with store.write():
                    for summary, path, name, kind, start_line in updates:
                        cur = store.conn.execute(
                            "UPDATE symbols SET doc = ?, doc_source = 'generated'"
                            " WHERE path = ? AND name = ? AND kind = ? AND start_line = ? AND doc IS NULL",
                            (summary, path, name, kind, start_line),
                        )
                        if cur.rowcount:
                            changed += cur.rowcount
                            dirs.add(posixpath.dirname(path))
                    if dirs:
                        self._shards(store).write_dirs(sorted(dirs))
        return changed

    def _resolve_imports(self, store: Store, paths: list[str] | None) -> None:
        """Point each import at the repo file it names (None: every import).
        A resolver bug must not block the index, so failures are logged."""
        try:
            rows = store.import_rows(paths)
            if not rows:
                return
            resolver = Resolver(self.repo.root, store.langs(), self.registry)
            updates = []
            for importer, target, lang, current in rows:
                resolved = resolver.resolve(importer, lang, target)
                if resolved != current:
                    updates.append((importer, target, resolved))
            store.set_resolved(updates)
        except Exception as exc:
            log_error(self.repo.root, "resolve imports", exc)

    def _parse_one(self, spec, info: FileInfo, data: bytes) -> FileParse | None:
        try:
            return parse_source(spec, info.path, data)
        except Exception as exc:  # one bad file must not stop the index
            log_error(self.repo.root, f"parse {info.path}", exc)
            return None

    def _shards(self, store: Store) -> ShardWriter:
        return ShardWriter(store, self.repo.map_dir, self.settings.shard_token_limit, self.registry.index_files)
