"""Background enrichment (DL-05): one-line summaries for symbols that have no
doc comment, written by the local model and shown in the map with ``~``.

Summaries are cached in ``.compass/summaries.db`` by the symbol's content hash
(kind, name and source text), so an unchanged symbol is summarised once, a
changed one again, and a full rebuild of the index keeps them: the indexer
looks summaries up for undocumented symbols as it parses. ``compass enrich``
runs detached and at low priority, started by the git hooks after a commit
when ``local_llm.enabled``, never by a Claude Code hook (Step 8), and it does
nothing at all when the model is not answering (DL-06).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any

from compass.index.model import FileParse, source_lines
from compass.repo import Repo

KINDS = frozenset({"function", "method", "class", "interface", "struct", "enum", "trait", "type"})
MAX_SOURCE_LINES = 80
MAX_SUMMARY_CHARS = 120
CACHE_NAME = "summaries.db"
AGAIN_NAME = "enrich.again"
MAX_PASSES = 5
SYSTEM = (
    "You write one-line summaries of code for a code map. Reply with the summary only: one sentence of at most"
    " 15 words, no code, no quotes, no preamble. Describe what the code does, not how it is written."
)


def symbol_hash(kind: str, name: str, text: str) -> str:
    digest = hashlib.blake2b(digest_size=16)
    digest.update(f"{kind}\0{name}\0".encode())
    digest.update(text.encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


class Cache:
    """``hash -> summary`` in SQLite; a missing file is an empty cache."""

    def __init__(self, conn: sqlite3.Connection | None) -> None:
        self.conn = conn

    @classmethod
    def open(cls, repo: Repo, create: bool = False) -> Cache:
        path = repo.compass_dir / CACHE_NAME
        if not path.exists() and not create:
            return cls(None)
        conn = sqlite3.connect(str(path), timeout=10.0)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS summaries (hash TEXT PRIMARY KEY, summary TEXT NOT NULL, model TEXT NOT NULL)"
        )
        return cls(conn)

    def get(self, hashes: list[str]) -> dict[str, str]:
        if self.conn is None or not hashes:
            return {}
        found: dict[str, str] = {}
        for start in range(0, len(hashes), 500):
            chunk = hashes[start : start + 500]
            marks = ",".join("?" * len(chunk))
            found.update(self.conn.execute(f"SELECT hash, summary FROM summaries WHERE hash IN ({marks})", chunk))
        return found

    def put(self, entries: list[tuple[str, str, str]]) -> None:
        if self.conn is not None and entries:
            with self.conn:
                self.conn.executemany("INSERT OR REPLACE INTO summaries (hash, summary, model) VALUES (?, ?, ?)", entries)

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()


def _symbol_text(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[start - 1 : min(end, start - 1 + MAX_SOURCE_LINES)])


def with_cached_docs(cache: Cache, path: str, parse: FileParse | None, data: bytes) -> FileParse | None:
    """``parse`` with cached summaries on its undocumented symbols (indexer hook)."""
    if parse is None or cache.conn is None or not parse.symbols:
        return parse
    wanting = [s for s in parse.symbols if s.doc is None and s.kind in KINDS]
    if not wanting:
        return parse
    lines = source_lines(data)
    hashes = {id(s): symbol_hash(s.kind, s.name, _symbol_text(lines, s.start_line, s.end_line)) for s in wanting}
    found = cache.get(sorted(set(hashes.values())))
    if not found:
        return parse
    symbols = tuple(
        replace(s, doc=found[hashes[id(s)]], doc_source="generated") if id(s) in hashes and hashes[id(s)] in found else s
        for s in parse.symbols
    )
    return replace(parse, symbols=symbols)


def clean_summary(text: str) -> str | None:
    """One line, no quotes or markup, capped; None for a non-answer."""
    line = next((part.strip() for part in (text or "").strip().splitlines() if part.strip()), "")
    line = line.strip("`\"'*_ ").removeprefix("Summary:").strip()
    lowered = line.lower()
    if not line or lowered.startswith(("i cannot", "i can't", "sorry", "as an ai", "i'm unable", "i am unable")):
        return None
    if len(line) > MAX_SUMMARY_CHARS:
        line = line[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    return line


def run(repo: Repo, config, limit: int | None = None) -> dict[str, Any]:
    """Summarise up to ``limit`` undocumented symbols; what happened, as a dict.

    One run at a time. A run that finds another going leaves ``enrich.again``
    and exits; the running one then makes another pass, so commits in quick
    succession (or a rebase) cost one extra pass, not a process each."""
    from compass.llm import LocalModel
    from compass.lock import LockTimeout, file_lock

    settings = config.local_llm
    if not settings.enabled:
        return {"skipped": "local_llm is off in .compass/config.yaml"}
    model = LocalModel(settings, repo)
    if not model.healthy(use_cache=False):
        return {"skipped": f"no local model answering at {settings.base_url} (with {settings.model})"}
    limit = settings.enrich_limit if limit is None else limit
    again = repo.compass_dir / AGAIN_NAME
    for attempt in range(2):
        try:
            with file_lock(repo.compass_dir / "enrich.lock", timeout=0.0):
                return _passes(repo, model, limit, again)
        except LockTimeout:
            if attempt == 0:
                again.touch()  # then look once more: that run may have finished meanwhile
    return {"skipped": "another compass enrich is running; it picks this change up when it is done"}


def _passes(repo: Repo, model, limit: int, again: Path) -> dict[str, Any]:
    from compass.index.store import IndexUnavailable, Store
    from compass.llm import Unavailable

    total = {"summarised": 0, "cached": 0, "applied": 0, "left": 0, "failed": 0}
    for _ in range(MAX_PASSES):
        again.unlink(missing_ok=True)
        try:
            store = Store.open(repo.db_path)
        except IndexUnavailable:
            return {"skipped": "no index yet"}
        with store:
            rows = list(store.conn.execute(
                "SELECT s.path, s.name, s.kind, s.parent, s.start_line, s.end_line, f.size, f.mtime_ns"
                " FROM symbols s JOIN files f ON f.path = s.path WHERE s.doc IS NULL"
                f" AND s.kind IN ({','.join('?' * len(KINDS))}) ORDER BY s.path, s.start_line, s.name",
                sorted(KINDS),
            ))
        cache = Cache.open(repo, create=True)
        try:
            result = _summarise(repo, model, cache, rows, limit - total["summarised"], Unavailable)
        finally:
            cache.close()
        for key in ("summarised", "cached", "applied", "failed"):
            total[key] += result[key]
        total["left"] = result["left"]
        if result["failed"] or total["summarised"] >= limit or not again.exists():
            break
    return total


def _summarise(repo: Repo, model, cache: Cache, rows, limit: int, unavailable) -> dict[str, Any]:
    todo: list[tuple[str, str, str, str | None, int, str, str]] = []
    texts: dict[str, list[str]] = {}
    for path, name, kind, parent, start, end, size, mtime_ns in rows:
        if path not in texts:
            try:
                st = os.stat(repo.root / path)
                same = (st.st_size, st.st_mtime_ns) == (size, mtime_ns)  # else lines have moved; next run
                texts[path] = source_lines((repo.root / path).read_bytes()) if same else []
            except OSError:
                texts[path] = []
        if texts[path]:
            text = _symbol_text(texts[path], start, end)
            todo.append((path, name, kind, parent, start, text, symbol_hash(kind, name, text)))
    known = cache.get(sorted({t[-1] for t in todo}))
    fresh, asked = [], set()
    for entry in todo:  # identical symbols (same kind, name and text) are asked about once
        if entry[-1] not in known and entry[-1] not in asked:
            asked.add(entry[-1])
            fresh.append(entry)
    written: list[tuple[str, str, str]] = []
    failed = 0
    for path, name, kind, parent, start, text, digest in fresh[:limit]:
        qualified = f"{parent}.{name}" if parent else name
        try:
            answer = model.complete(SYSTEM, f"{kind} {qualified} in {path}:\n```\n{text}\n```", max_tokens=60)
        except unavailable:
            failed += 1
            if failed >= 3:
                break  # the model went away; try again after the next commit
            continue
        summary = clean_summary(answer)
        if summary:
            written.append((digest, summary, model.settings.model))
    cache.put(written)
    applied = _apply(repo, cache, todo)
    cached = sum(1 for entry in todo if entry[-1] in known)
    return {"summarised": len(written), "cached": cached, "applied": applied,
            "left": max(0, len(fresh) - limit), "failed": failed}


def _apply(repo: Repo, cache: Cache, todo) -> int:
    """Write the summaries into the index and its shards."""
    found = cache.get(sorted({t[-1] for t in todo}))
    updates = [(found[t[-1]], t[0], t[1], t[2], t[4]) for t in todo if t[-1] in found]
    if not updates:
        return 0
    from compass.index.indexer import Indexer

    return Indexer(repo).apply_generated_docs(updates)


def summaries_exist(root: Path) -> bool:
    return (root / ".compass" / CACHE_NAME).is_file()
