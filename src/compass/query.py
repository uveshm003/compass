"""The query tools (QT-01 to QT-05): one engine behind the MCP server and the
``compass <tool>`` CLI twins.

Each query returns a Result: text lines for the model, in the map-shard format
(far fewer tokens than JSON), and structured data for ``--json``. MCP answers
are capped at ``query.max_response_chars`` and continue with a cursor (``page``).

The engine keeps the index fresh by itself, because edits made through Bash or
an editor never reach the Claude Code hooks: every tool runs the same
staleness check as SessionStart at most every ``REFRESH_S`` seconds, and a tool
about one file re-indexes that file first if it changed on disk. read_symbol
and file_outline go further and take line numbers from the file as it is now,
so they are right even when another process holds the index lock.

The MCP server calls one Queries from several worker threads at once; each
call opens its own SQLite connection, and the little shared state is locked.
"""

from __future__ import annotations

import difflib
import os
import posixpath
import re
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from compass import background
from compass.config import Config, load_config
from compass.index.docs import summary
from compass.index.model import source_lines
from compass.index.shards import KIND_LABELS, render_dir, render_index, render_symbols
from compass.index.store import IndexUnavailable, Store, SymbolHit
from compass.languages import load_registry
from compass.log import log_error
from compass.repo import Repo

REFRESH_S = 20.0
LOCK_WAIT_S = 0.5
FIND_LIMIT = 50
CALLER_LIMIT = 500
CANDIDATES_SHOWN = 20
TEST_NAMES_SHOWN = 8
DIR_SOURCES_LIMIT = 200
LINE_TEXT_CHARS = 120
NO_LIMIT = 10**9
FOOTER_ROOM = 80  # the cursor line at the end of a cut-off page
MIN_PAGE_CHARS = 200

KIND_ALIASES = {
    "fn": "function", "func": "function", "def": "function", "const": "constant",
    "var": "variable", "mod": "module", "iface": "interface",
}
CALLABLE = frozenset({"function", "method"})


class NotReady(Exception):
    """No usable index yet; the message says what to do about it."""


@dataclass
class Result:
    lines: list[str]
    data: Any = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def parse_cursor(cursor: object) -> int | None:
    """The line index a cursor points at: 0 for none, None if it is not one."""
    if cursor is None or cursor == "":
        return 0
    text = str(cursor).strip()
    return int(text) if re.fullmatch(r"[0-9]+", text) else None


def page(lines: list[str], cursor: object, max_chars: int) -> str:
    """At most ``max_chars`` of ``lines`` from ``cursor`` on (QT-05), footer
    included. A cut-off answer ends with the cursor that continues it; lines
    are never split, and one longer than a whole page is shortened."""
    start = parse_cursor(cursor)
    if start is None:
        return f'[compass] {cursor!r} is not a cursor; pass the cursor="N" an earlier answer ended with.'
    if lines and start >= len(lines):
        return "[compass] No more results."
    max_chars = max(max_chars, MIN_PAGE_CHARS)
    widest = max_chars - FOOTER_ROOM
    out: list[str] = []
    used = 0
    i = start
    while i < len(lines):
        text = lines[i] if len(lines[i]) <= widest else lines[i][: widest - 1] + "…"
        cost = len(text) + (1 if out else 0)
        room = max_chars if i + 1 == len(lines) else widest  # keep room for the footer
        if out and used + cost > room:
            break
        out.append(text)
        used += cost
        i += 1
    if i < len(lines):
        out.append(f'[compass] {len(lines) - i} more lines; call again with cursor="{i}".')
    return "\n".join(out)


def split_qualified(name: str) -> tuple[str, str | None]:
    """``ReconnectPolicy.next`` or ``Point::new`` -> (name, parent)."""
    cleaned = name.strip().removesuffix("()").strip()
    parts = [p for p in re.split(r"\.|::|#", cleaned) if p]
    if len(parts) <= 1:
        return cleaned, None
    return parts[-1], ".".join(parts[:-1])


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _qualified(hit: SymbolHit) -> str:
    return f"{hit.parent}.{hit.name}" if hit.parent else hit.name


def hit_line(hit: SymbolHit) -> str:
    label = KIND_LABELS.get(hit.kind, hit.kind)
    signature = hit.signature or hit.name
    if hit.parent:
        signature = f"{hit.parent}.{signature}"
    doc = summary(hit.doc)
    mark = (" ~ " if hit.doc_source == "generated" else " — ") + doc if doc else ""
    test = "  [test]" if hit.is_test else ""
    return f"{hit.path}:{hit.start_line}-{hit.end_line}  {label} {signature}{mark}{test}"


def hit_data(hit: SymbolHit) -> dict[str, Any]:
    return {
        "name": hit.name, "kind": hit.kind, "parent": hit.parent, "signature": hit.signature,
        "path": hit.path, "start_line": hit.start_line, "end_line": hit.end_line,
        "visibility": hit.visibility, "doc": summary(hit.doc), "is_test": hit.is_test,
    }


@dataclass
class _Snapshot:
    """One read of a file: its lines, and its symbols parsed from those same
    bytes (None when no tree-sitter query covers the language)."""

    lines: list[str]
    hits: list[SymbolHit] | None
    doc: str | None


class Queries:
    def __init__(self, repo: Repo, config: Config | None = None) -> None:
        self.repo = repo
        self._config_key = self._config_stat()
        self.config = config if config is not None else load_config(repo.root)
        self.settings = self.config.query
        self.registry = load_registry()
        self._lock = threading.Lock()
        self._local = threading.local()
        self._last_refresh: float | None = None
        self._build_started = False

    @contextmanager
    def continuing(self, active: bool = True) -> Iterator[None]:
        """While ``active`` (a later page of an answer), skip the freshness
        checks so the pages come from the same index state."""
        previous = getattr(self._local, "hold", False)
        self._local.hold = active
        try:
            yield
        finally:
            self._local.hold = previous

    # -- the tools ---------------------------------------------------------------

    def find_symbol(self, name: str, kind: str | None = None, path: str | None = None, limit: int = FIND_LIMIT) -> Result:
        self._prepare()
        needle, parent = split_qualified(name)
        if not needle:
            return Result(["[compass] find_symbol needs a name."], [])
        kind = KIND_ALIASES.get(kind, kind) if kind else None
        scope = self._scope(path)
        with self._store() as store:
            hits = store.find_symbols(needle, kind, scope, parent, limit + 1)
            if not hits and parent:  # `models.StockItem`: the parent was a module, not a class
                hits = store.find_symbols(needle, kind, scope, None, limit + 1)
            close = [] if hits else _close_matches(store, needle)
        more = len(hits) > limit
        hits = hits[:limit]
        if not hits:
            lines = [f'[compass] No symbol named like "{name}"' + (f" under {scope}" if scope else "") + "."]
            lines += ["Similar names:"] + [hit_line(h) for h in close] if close else ["Try part of the name, or map() to browse."]
            return Result(lines, [])
        lines = [f'{len(hits)}{"+" if more else ""} {"symbol" if len(hits) == 1 else "symbols"} matching "{name}":']
        lines += [hit_line(h) for h in hits]
        if more:
            lines.append("[compass] More matches exist; narrow with kind= or path=.")
        return Result(lines, [hit_data(h) for h in hits])

    def file_outline(self, path: str) -> Result:
        self._prepare()
        rel = self._rel(path)
        if not rel:
            return Result(["[compass] file_outline needs a file; map() shows the folder tree."], None)
        if self._is_dir_on_disk(rel):
            return Result([f'[compass] {rel}/ is a directory; map("{rel}") lists its files and symbols.'], None)
        self._refresh_file(rel)
        with self._store() as store:
            info = store.file_info(rel)
            if info is None:
                return self._missing_file(store, rel)
            hits = store.file_symbols(rel)
            imports = store.imports_of(rel)
        doc = info["doc"]
        if not self._index_matches_disk(rel, info):
            # The index could not catch up (another process holds its lock):
            # describe the file as it is now rather than as it was.
            snapshot = self._snapshot(rel, info["lang"], info["is_test"])
            if snapshot is not None and snapshot.hits is not None:
                hits, doc = snapshot.hits, snapshot.doc
        head = f"{rel}  ({info['lang'] or 'no parser'}, {_plural(len(hits), 'symbol')}"
        head += ", test file)" if info["is_test"] else ")"
        doc_line = summary(doc)
        lines = [head + (f" — {doc_line}" if doc_line else "")]
        lines += render_symbols([h.as_row() for h in hits])
        lines += _import_lines(imports, self._separator_for(rel))
        data = {
            "path": rel, "lang": info["lang"], "doc": doc, "is_test": info["is_test"],
            "symbols": [hit_data(h) for h in hits],
            "imports": [{"target": t, "resolved": r} for t, r in imports],
        }
        return Result(lines, data)

    def read_symbol(self, name: str, path: str | None = None, context: int | None = None) -> Result:
        self._prepare()
        context = self.settings.context_lines if context is None else max(0, int(context))
        needle, parent = split_qualified(name)
        if not needle:
            return Result(["[compass] read_symbol needs a name."], None)
        scope = self._scope(path)
        rel = scope if scope and self._is_file_on_disk(scope) else None
        with self._store() as store:
            if rel is None:
                hits = self._named(store, needle, parent, scope)
                if not hits:
                    close = _close_matches(store, needle)
                    lines = [f'[compass] No symbol named "{name}"' + (f" under {scope}" if scope else "") + "."]
                    if close:
                        lines += ["Close matches:"] + [hit_line(h) for h in close]
                    return Result(lines, {"candidates": [hit_data(h) for h in close]})
                files = sorted({h.path for h in hits})
                if len(files) > 1:
                    lines = [f'"{name}" is defined in {len(files)} files; pass path= to pick one:']
                    lines += [hit_line(h) for h in hits[:CANDIDATES_SHOWN]]
                    return Result(lines, {"candidates": [hit_data(h) for h in hits]})
                rel = files[0]
            info = store.file_info(rel)
        self._refresh_file(rel)
        snapshot = self._snapshot(rel, info["lang"] if info else None, info["is_test"] if info else None)
        if snapshot is None:
            return Result([f"[compass] Cannot read {rel}; it may have been moved or deleted."], None)
        symbols = snapshot.hits
        if symbols is None:  # no tree-sitter query: the index rows, refreshed above
            with self._store() as store:
                symbols = store.file_symbols(rel)
        source = snapshot.lines
        chosen = [h for h in _pick(symbols, needle, parent) if h.start_line <= len(source)]
        if not chosen:
            if rel == scope:
                lines = [f'[compass] No symbol named "{name}" in {rel}.']
            else:
                lines = [f'[compass] "{name}" is no longer defined in {rel}; the file changed since it was indexed.']
            close = difflib.get_close_matches(needle, sorted({s.name for s in symbols}), n=5, cutoff=0.6)
            if close:
                lines.append(f"Defined there now: {', '.join(close)}.")
            return Result(lines, {"candidates": close})
        chosen.sort(key=lambda h: (h.start_line, -h.end_line))
        spans: list[list[int]] = []
        for hit in chosen:
            start = max(1, min(hit.start_line - context, _comment_start(source, hit.start_line)))
            end = min(len(source), hit.end_line + context)
            if spans and start <= spans[-1][1] + 1:
                spans[-1][1] = max(spans[-1][1], end)
            else:
                spans.append([start, end])
        width = len(str(spans[-1][1]))
        lines: list[str] = []
        blocks = []
        for start, end in spans:
            inside = [h for h in chosen if start <= h.start_line and h.end_line <= end]
            titles = "; ".join(f"{KIND_LABELS.get(h.kind, h.kind)} {_qualified(h)}" for h in inside)
            lines.append(f"{rel}:{start}-{end}  {titles}")
            lines += [f"{n:>{width}}\t{source[n - 1]}" for n in range(start, end + 1)]
            blocks.append({"start": start, "end": end, "lines": source[start - 1 : end]})
        return Result(lines, {"path": rel, "symbols": [hit_data(h) for h in chosen], "blocks": blocks})

    def map(self, directory: str = "") -> Result:
        self._prepare()
        d = self._rel(directory) if directory else ""
        with self._store() as store:
            purposes = store.purposes(self.registry.index_files)
            stats = store.dir_stats()
            if not d:
                lines = "".join(render_index(stats, purposes, NO_LIMIT)).splitlines()
                return Result(lines, {"dirs": [_stat(s) for s in stats]})
            files = store.dir_files(d)
            below = [s for s in stats if s.dir.startswith(d + "/")]
            if not files and not below:
                if store.file_info(d) is not None:
                    return Result([f'[compass] {d} is a file; file_outline("{d}") lists what it defines.'], None)
                close = store.dirs_like(posixpath.basename(d))
                hint = f" Did you mean: {', '.join(c + '/' for c in close)}?" if close else ""
                return Result([f"[compass] No directory {d}/ in the code map.{hint}"], None)
            lines: list[str] = []
            symbols = store.dir_symbols(d) if files else []
            if files:
                lines += "".join(render_dir(d, files, symbols, purposes.get(d), NO_LIMIT)).splitlines()
            if below:
                lines.append("Subdirectories:" if files else f"# {d}/ holds no files itself; subdirectories:")
                for s in below:
                    doc = summary(purposes.get(s.dir))
                    counts = f"{_plural(s.files, 'file')}, {_plural(s.symbols, 'symbol')}"
                    lines.append(f"- {s.dir}/  ({counts})" + (f" — {doc}" if doc else ""))
        data = {
            "dir": d,
            "files": [{"path": f.path, "lang": f.lang, "doc": summary(f.doc)} for f in files],
            "symbols": [
                {"path": s.path, "name": s.name, "kind": s.kind, "parent": s.parent, "start_line": s.start_line}
                for s in symbols
            ],
            "subdirs": [_stat(s) for s in below],
        }
        return Result(lines, data)

    def stack_profile(self) -> Result:
        from compass.stack import build_profile, render_text

        self._sync_config()
        profile = build_profile(self.repo.root, self.config)
        return Result(render_text(profile).splitlines(), profile)

    def tests_for(self, target: str) -> Result:
        self._prepare()
        rel = self._rel(target)
        if not rel:
            return Result(["[compass] tests_for needs a file, a directory or a symbol name."], None)
        with self._store() as store:
            info = store.file_info(rel)
            is_dir = info is None and store.has_dir(rel)
            if info is None and not is_dir:
                named = store.paths_named(rel, CANDIDATES_SHOWN + 1)
                if len(named) == 1:  # `models.py` for src/inventory/models.py
                    rel, info = named[0], store.file_info(named[0])
                elif named:
                    lines = [f"[compass] {target} matches several files; pass the path of one:"]
                    lines += named[:CANDIDATES_SHOWN] + (["…"] if len(named) > CANDIDATES_SHOWN else [])
                    return Result(lines, {"candidates": named[:CANDIDATES_SHOWN]})
            if info is not None:
                found = self._tests_for_file(store, rel, info, store.test_files())
                lines = [f"Tests for {rel}:"] if found else [
                    f"[compass] No tests found for {rel} by name, imports or package."
                    " callers_of(<function>) finds tests that call it."
                ]
                lines += [self._test_line(store, path, reasons) for path, reasons in found]
                return Result(lines, {"target": rel, "tests": [self._test_data(store, p, r) for p, r in found]})
            if is_dir:
                return self._tests_for_dir(store, rel)
            return self._tests_for_symbol(store, target)

    def importers_of(self, target: str) -> Result:
        self._prepare()
        rel = self._rel(target)
        if not rel:
            return Result(["[compass] importers_of needs a file, a directory or a module name."], [])
        with self._store() as store:
            info = store.file_info(rel)
            rows: list[tuple[str, str, str | None]] = []
            inside, what, is_dir = 0, rel, False
            if info is not None:
                keys = [rel] + ([info["dir"]] if self._imports_resolve_to_dirs(info["lang"]) else [])
                rows = [row for row in store.importers_of(keys) if row[0] != rel]
            elif store.has_dir(rel):
                # A directory's importers are the files outside it that import something in it.
                every = store.importers_under(rel)
                rows = [row for row in every if not row[0].startswith(rel + "/")]
                inside = len({row[0] for row in every}) - len({row[0] for row in rows})
                what, is_dir = rel + "/", True
            if info is None and not rows and not inside:  # a module: `react`, `requests`, `serde`
                what = target.strip()
                rows = [(p, t, None) for p, t in self._module_importers(store, what)]
        grouped: dict[str, list[tuple[str, str | None]]] = {}
        for path, raw, resolved in rows:
            grouped.setdefault(path, []).append((raw, resolved))
        left_out = f"; imports from {_plural(inside, 'file')} inside it are left out" if inside else ""
        if not grouped:
            return Result([f"[compass] Nothing outside {what} imports it{left_out}." if inside
                           else f"[compass] Nothing imports {what}."], [])
        verb = "imports" if len(grouped) == 1 else "import"
        lines = [f"{_plural(len(grouped), 'file')} {verb} {what}{left_out}:"]
        data = []
        for path, imports in grouped.items():
            targets = [raw for raw, _resolved in imports]
            if is_dir:  # which of the directory's files it uses
                used = sorted({self._inside_name(r, rel, path) for _raw, r in imports if r is not None})
                lines.append(f"{path}  (uses {', '.join(used)})")
                data.append({"path": path, "targets": targets, "uses": used})
            else:
                lines.append(f"{path}  ({_compact(targets, self._separator_for(path))})")
                data.append({"path": path, "targets": targets})
        return Result(lines, data)

    def callers_of(self, name: str) -> Result:
        self._prepare()
        needle, parent = split_qualified(name)
        if not needle:
            return Result(["[compass] callers_of needs a name."], [])
        with self._store() as store:
            rows = store.refs_named(needle, CALLER_LIMIT)
            total = store.ref_count(needle)
            symbols = {path: store.file_symbols(path) for path in sorted({r[0] for r in rows})}
            tests = {p for p, _lang in store.test_files()}
        if not rows:
            return Result([f"[compass] No call sites of {needle} in the code map."], [])
        note = f" (matched by name {needle!r}, so same-named methods of other types appear too)" if parent else ""
        lines = [f"{_plural(total, 'call site')} of {needle}{note}:"]
        data = []
        sources: dict[str, list[str]] = {}
        for path, line, _kind in rows:
            if path not in sources:
                try:
                    sources[path] = source_lines((self.repo.root / path).read_bytes())
                except OSError:
                    sources[path] = []
            text = sources[path][line - 1].strip() if 0 < line <= len(sources[path]) else ""
            if len(text) > LINE_TEXT_CHARS:
                text = text[: LINE_TEXT_CHARS - 1] + "…"
            caller = _enclosing(symbols.get(path, []), line)
            where = f"in {_qualified(caller)}" if caller else "at top level"
            mark = "  [test]" if path in tests else ""
            lines.append(f"{path}:{line}  {where} — {text}{mark}")
            data.append({"path": path, "line": line, "caller": _qualified(caller) if caller else None,
                         "text": text, "is_test": path in tests})
        if total > len(rows):
            lines.append(f"[compass] Showing the first {len(rows)} of {total}.")
        return Result(lines, data)

    # -- tests_for helpers -------------------------------------------------------

    def _tests_for_file(
        self, store: Store, rel: str, info: dict[str, Any], test_files: list[tuple[str, str | None]]
    ) -> list[tuple[str, list[str]]]:
        spec = self.registry.get(info["lang"])
        convention = spec.tests if spec else None
        reasons: dict[str, set[str]] = {}
        if info["is_test"]:
            reasons.setdefault(rel, set()).add("is a test file")
        test_set = {p for p, _lang in test_files}
        stem = posixpath.splitext(posixpath.basename(rel))[0]
        same_stem: list[str] | None = None
        for path, lang in test_files:
            if path == rel or lang != info["lang"]:
                continue
            if self._test_stem(path, lang) == stem:
                # `b/utils.test.ts` is about b/utils.ts, not every utils.ts in the repo
                if same_stem is None:
                    same_stem = store.sources_with_stem(stem, info["lang"])
                if rel in _closest(path, same_stem):
                    reasons.setdefault(path, set()).add("name")
            if convention and convention.same_package and posixpath.dirname(path) == info["dir"]:
                reasons.setdefault(path, set()).add("package")
        keys = [rel] + ([info["dir"]] if self._imports_resolve_to_dirs(info["lang"]) else [])
        for importer, _target, _resolved in store.importers_of(keys):
            if importer in test_set and importer != rel:
                reasons.setdefault(importer, set()).add("imports")
        if convention and convention.inline_module:
            if any(h.name == convention.inline_module and h.kind == "module" for h in store.file_symbols(rel)):
                reasons.setdefault(rel, set()).add("inline tests")
        order = {"inline tests": 0, "is a test file": 0, "name": 1, "imports": 2, "package": 3}
        ranked = sorted(reasons.items(), key=lambda kv: (-len(kv[1]), min(order[r] for r in kv[1]), kv[0]))
        return [(path, sorted(r, key=order.__getitem__)) for path, r in ranked]

    def _tests_for_dir(self, store: Store, directory: str) -> Result:
        sources = store.source_files_under(directory)
        if not sources:
            return Result([f"[compass] No source files under {directory}/."], None)
        shown = sources[:DIR_SOURCES_LIMIT]
        test_files = store.test_files()
        reasons: dict[str, set[str]] = {}
        covers: dict[str, set[str]] = {}
        for path in shown:
            info = store.file_info(path)
            if info is None:
                continue
            for test, why in self._tests_for_file(store, path, info, test_files):
                reasons.setdefault(test, set()).update(why)
                covers.setdefault(test, set()).add(path)
        what = f"{directory}/ ({_plural(len(sources), 'source file')}"
        what += f", first {len(shown)} checked)" if len(shown) < len(sources) else ")"
        if not reasons:
            return Result([f"[compass] No tests found for {what} by name, imports or package."], None)
        order = {"inline tests": 0, "name": 1, "imports": 2, "package": 3}
        ranked = sorted(reasons, key=lambda t: (-len(covers[t]), t))
        lines = [f"Tests for {what}:"]
        data = []
        for test in ranked:
            why = sorted(reasons[test], key=lambda r: order.get(r, 9))
            names = sorted(posixpath.relpath(p, directory) for p in covers[test])
            covered = ", ".join(names[:5]) + (f", … ({len(names)} in all)" if len(names) > 5 else "")
            tests = self._test_names(store, test)
            listed = ", ".join(tests[:TEST_NAMES_SHOWN]) + (f", … ({len(tests)} in all)" if len(tests) > TEST_NAMES_SHOWN else "")
            lines.append(f"{test}  ({', '.join(why)}; for {covered})" + (f" — {listed}" if listed else ""))
            data.append({"path": test, "reasons": why, "sources": sorted(covers[test]), "tests": tests})
        return Result(lines, {"target": directory + "/", "tests": data})

    def _tests_for_symbol(self, store: Store, target: str) -> Result:
        needle, parent = split_qualified(target)
        hits = store.exact_symbols(needle, parent) or store.exact_symbols(needle)
        inline = [(spec.name, spec.tests.inline_module) for spec in self.registry if spec.tests.inline_module]
        calls = store.refs_in_tests(needle, inline)
        if not hits and not calls:
            return Result([f"[compass] {target} is neither an indexed file nor a known symbol."], None)
        lines: list[str] = []
        data: dict[str, Any] = {"target": target, "calling_tests": [], "file_tests": {}}
        if calls:
            lines.append(f"Tests that call {needle}:")
            symbols: dict[str, list[SymbolHit]] = {}
            for path, line in calls:
                if path not in symbols:
                    symbols[path] = store.file_symbols(path)
                caller = _enclosing(symbols[path], line)
                lines.append(f"{path}:{line}  in {_qualified(caller) if caller else 'top level'}")
                data["calling_tests"].append({"path": path, "line": line, "caller": _qualified(caller) if caller else None})
        test_files = store.test_files()
        for source in sorted({h.path for h in hits if not h.is_test})[:3]:
            info = store.file_info(source)
            found = self._tests_for_file(store, source, info, test_files) if info else []
            if found:
                lines.append(f"Tests for {source} (where {needle} is defined):")
                lines += [self._test_line(store, path, reasons) for path, reasons in found]
                data["file_tests"][source] = [self._test_data(store, p, r) for p, r in found]
        if not lines:
            lines = [f"[compass] No tests found for {target}."]
        return Result(lines, data)

    def _test_stem(self, path: str, lang: str | None) -> str:
        spec = self.registry.get(lang)
        stem = posixpath.splitext(posixpath.basename(path))[0]
        if spec is None:
            return stem
        for prefix in spec.tests.name_prefixes:
            if stem.startswith(prefix):
                return stem[len(prefix) :]
        for suffix in spec.tests.name_suffixes:
            if stem.endswith(suffix):
                return stem[: -len(suffix)]
        return stem

    def _test_names(self, store: Store, path: str) -> list[str]:
        info = store.file_info(path)
        spec = self.registry.get(info["lang"] if info else None)
        inline = spec.tests.inline_module if spec else None
        names = []
        for hit in store.file_symbols(path):
            if hit.kind not in CALLABLE:
                continue
            if info and not info["is_test"] and inline:
                # a source file with inline tests: only what sits in the tests module
                if not (hit.parent == inline or (hit.parent or "").startswith(inline + ".")):
                    continue
            names.append(hit.name)
        return names

    def _test_line(self, store: Store, path: str, reasons: list[str]) -> str:
        names = self._test_names(store, path)
        shown = ", ".join(names[:TEST_NAMES_SHOWN]) + (f", … ({len(names)} in all)" if len(names) > TEST_NAMES_SHOWN else "")
        return f"{path}  ({', '.join(reasons)})" + (f" — {shown}" if shown else "")

    def _test_data(self, store: Store, path: str, reasons: list[str]) -> dict[str, Any]:
        return {"path": path, "reasons": reasons, "tests": self._test_names(store, path)}

    # -- plumbing ----------------------------------------------------------------

    def _imports_resolve_to_dirs(self, lang: str | None) -> bool:
        spec = self.registry.get(lang)
        return bool(spec and spec.imports.resolver == "package")

    def _separator_for(self, path: str) -> str:
        """How the language of ``path`` separates module path segments."""
        spec = self.registry.get(self.registry.detect_by_name(path))
        return spec.imports.separator if spec and spec.imports.resolver == "module" else "/"

    def _inside_name(self, resolved: str, directory: str, importer: str) -> str:
        """``resolved`` relative to ``directory``; Go packages (directories) end in /."""
        name = posixpath.relpath(resolved, directory) if resolved != directory else "."
        return name + "/" if self._imports_resolve_to_dirs(self.registry.detect_by_name(importer)) else name

    def _module_importers(self, store: Store, module: str) -> list[tuple[str, str]]:
        """Imports of ``module`` itself or of anything inside it, where inside
        means after the importing language's separator: ``requests`` matches
        ``requests.adapters`` in Python and ``react/jsx-runtime`` in TS, but
        not ``requests_toolbelt``."""
        rows = []
        for path, raw, lang in store.imports_starting(module):
            spec = self.registry.get(lang)
            if spec is None or spec.imports.resolver is None:
                separators: tuple[str, ...] = ("/", ".", "::")
            elif spec.imports.resolver == "module":
                separators = (spec.imports.separator,)
            else:
                separators = ("/",)
            if raw == module or raw[len(module) :].startswith(separators):
                rows.append((path, raw))
        return rows

    def _named(self, store: Store, needle: str, parent: str | None, scope: str | None) -> list[SymbolHit]:
        hits = store.exact_symbols(needle, parent)
        if not hits and parent:
            hits = store.exact_symbols(needle)
        if scope:
            # The path itself or a directory above it; a path ending only as a
            # fallback (`index.ts` would also match packages/app/src/index.ts).
            under = [h for h in hits if h.path == scope or h.path.startswith(scope + "/")]
            hits = under or [h for h in hits if h.path.endswith("/" + scope)]
        return hits

    def _missing_file(self, store: Store, rel: str) -> Result:
        close = store.paths_named(posixpath.basename(rel))
        hint = f" Did you mean: {', '.join(close)}?" if close else ""
        return Result(
            [f"[compass] {rel} is not in the code map (untracked by git, excluded, binary or missing).{hint}"],
            None,
        )

    def _rel(self, path: str) -> str:
        """Repo-relative POSIX path; ``""`` for the root. A path outside the
        repo comes back unchanged, so it matches nothing."""
        text = (path or "").strip().replace("\\", "/")
        if os.path.isabs(text) or re.match(r"^[A-Za-z]:/", text):
            rel = self.repo.relpath(text)
            return rel if rel is not None else text
        normalized = posixpath.normpath(text) if text else ""
        return "" if normalized == "." else normalized.lstrip("/")

    def _scope(self, path: str | None) -> str | None:
        """A path filter; None (the whole repo) for no path or the root."""
        rel = self._rel(path) if path else ""
        return rel or None

    def _full_path(self, rel: str):
        return None if os.path.isabs(rel) or rel.startswith("../") else self.repo.root / rel

    def _is_file_on_disk(self, rel: str) -> bool:
        full = self._full_path(rel)
        return full is not None and full.is_file()

    def _is_dir_on_disk(self, rel: str) -> bool:
        full = self._full_path(rel)
        return full is not None and full.is_dir()

    def _snapshot(self, rel: str, lang: str | None, is_test: bool | None) -> _Snapshot | None:
        """Read ``rel`` once; parse those bytes when a tree-sitter query covers it."""
        full = self._full_path(rel)
        try:
            data = full.read_bytes() if full is not None else None
        except OSError:
            data = None
        if data is None:
            return None
        lines = source_lines(data)
        if lang is None:
            lang = self.registry.detect(rel, data[:256])
        spec = self.registry.get(lang)
        if spec is None:
            return _Snapshot(lines, None, None)
        try:
            from compass.index.parser import parse_source

            parsed = parse_source(spec, rel, data)
        except Exception as exc:
            log_error(self.repo.root, f"parse {rel}", exc)
            return _Snapshot(lines, None, None)
        flag = bool(self.registry.is_test(rel, lang) if is_test is None else is_test)
        hits = [
            SymbolHit(rel, s.name, s.kind, s.parent, s.signature, s.start_line, s.end_line,
                      s.visibility, s.doc, s.doc_source, flag)
            for s in parsed.symbols
        ]
        return _Snapshot(lines, hits, parsed.doc)

    def _index_matches_disk(self, rel: str, info: dict[str, Any]) -> bool:
        try:
            st = os.stat(self.repo.root / rel)
        except OSError:
            return False
        return (info["size"], info["mtime_ns"]) == (st.st_size, st.st_mtime_ns)

    def _prepare(self) -> None:
        """Before each tool: pick up config edits, then the freshness check."""
        self._sync_config()
        self._refresh_repo()

    def _config_stat(self) -> tuple[int, int] | None:
        try:
            st = os.stat(self.repo.config_path)
        except OSError:
            return None
        return (st.st_size, st.st_mtime_ns)

    def _sync_config(self) -> None:
        """Reload config.yaml when it changed: the MCP server lives for a whole
        session, and a stale ``index`` section would make every refresh look
        like it needs a full rebuild."""
        key = self._config_stat()
        if key == self._config_key:
            return
        try:
            config = load_config(self.repo.root)
        except Exception as exc:
            log_error(self.repo.root, "query config", exc)
            return
        self.config, self.settings, self._config_key = config, config.query, key

    def _store(self) -> Store:
        if not self.repo.initialized:
            raise NotReady(
                "[compass] This repository has no code map yet. Run `compass init` in it to build one."
            )
        try:
            store = Store.open(self.repo.db_path)
        except IndexUnavailable:
            store = None
        if store is not None:
            try:
                built = store.get_meta("fingerprint") is not None
            except Exception:
                built = False
            if built:
                self._build_started = False
                return store
            store.close()  # the first build has created the schema but not committed any rows
        with self._lock:
            start, self._build_started = not self._build_started, True
        if start:
            background.spawn(["-C", str(self.repo.root), "index"], self.repo.root)
        raise NotReady("[compass] The code map is being built; ask again in a minute.")

    def _holding(self) -> bool:
        return getattr(self._local, "hold", False)

    def _refresh_repo(self) -> None:
        """At most every REFRESH_S: bring the index up to date, as SessionStart does."""
        if self._holding() or not self.repo.initialized:
            return
        with self._lock:
            now = time.monotonic()
            if self._last_refresh is not None and now - self._last_refresh < REFRESH_S:
                return
            self._last_refresh = now
        try:
            from compass.hooks import refresh_or_hand_off

            refresh_or_hand_off(self.repo, LOCK_WAIT_S)
        except Exception as exc:
            log_error(self.repo.root, "query refresh", exc)

    def _refresh_file(self, rel: str) -> bool:
        """Re-index file ``rel`` if it changed on disk since it was indexed."""
        if not rel or self._holding() or not self.repo.initialized or self._full_path(rel) is None:
            return False
        try:
            st = os.lstat(self.repo.root / rel)
        except OSError:
            st = None
        if st is not None and stat.S_ISDIR(st.st_mode):
            return False  # a directory: re-checking everything below it is the repo refresh's job
        try:
            with Store.open(self.repo.db_path) as store:
                info = store.file_info(rel)
        except IndexUnavailable:
            return False
        if st is None and info is None:
            return False
        if st is not None and info is not None and (info["size"], info["mtime_ns"]) == (st.st_size, st.st_mtime_ns):
            return False
        try:
            from compass.index.indexer import FullBuildNeeded, Indexer
            from compass.lock import LockTimeout

            try:
                result = Indexer(self.repo, self.config).update([rel], lock_timeout=LOCK_WAIT_S, allow_full=False)
            except (LockTimeout, FullBuildNeeded):
                return False
            return result.parsed > 0 or result.removed > 0
        except Exception as exc:
            log_error(self.repo.root, f"refresh {rel}", exc)
            return False


def _pick(symbols: list[SymbolHit], needle: str, parent: str | None) -> list[SymbolHit]:
    """``needle``'s definitions among ``symbols``, as Store.exact_symbols and
    Queries._named choose them: the parent narrows when it can, and an exact
    case match beats a case-insensitive one."""
    def named(fold: bool) -> list[SymbolHit]:
        if fold:
            return [s for s in symbols if s.name.casefold() == needle.casefold()]
        return [s for s in symbols if s.name == needle]

    if parent:
        for fold in (False, True):
            scoped = [s for s in named(fold) if s.parent == parent or (s.parent or "").endswith("." + parent)]
            if scoped:
                return scoped
    for fold in (False, True):
        found = named(fold)
        if found:
            return found
    return []


def _closest(test_path: str, sources: list[str]) -> set[str]:
    """The sources nearest a test by directory: shared leading components
    (``src/x/__tests__``) plus shared trailing ones (``tests/x`` mirrors ``src/x``)."""
    if not sources:
        return set()
    here = [p for p in posixpath.dirname(test_path).split("/") if p]

    def score(path: str) -> int:
        there = [p for p in posixpath.dirname(path).split("/") if p]
        lead = 0
        while lead < min(len(here), len(there)) and here[lead] == there[lead]:
            lead += 1
        a, b = here[lead:], there[lead:]
        trail = 0
        while trail < min(len(a), len(b)) and a[-1 - trail] == b[-1 - trail]:
            trail += 1
        return lead + trail

    best = max(score(p) for p in sources)
    return {p for p in sources if score(p) == best}


def _import_lines(imports: list[tuple[str, str | None]], separator: str) -> list[str]:
    """One line per imported repo file (with the names imported from it),
    then one per external module, so a long list pages instead of being cut."""
    if not imports:
        return []
    local: dict[str, list[str]] = {}
    external: dict[str, list[str]] = {}
    for target, resolved in imports:
        if resolved is None:
            external.setdefault(target.split(separator, 1)[0], []).append(target)
        else:
            local.setdefault(resolved, []).append(target)
    lines = ["imports:"]
    lines += [f"- {path or '.'}  ({_compact(targets, separator)})" for path, targets in sorted(local.items())]
    lines += [f"- {_compact(targets, separator)}" for _module, targets in sorted(external.items())]
    return lines


def _compact(targets: list[str], separator: str) -> str:
    """``compass.query.{NotReady, Queries}`` for targets that share a module
    path; a plain list otherwise."""
    if len(targets) < 2:
        return ", ".join(targets)
    split = [t.split(separator) for t in targets]
    shared = 0
    while all(len(parts) > shared + 1 for parts in split) and len({parts[shared] for parts in split}) == 1:
        shared += 1
    prefix = separator.join(split[0][:shared])
    if not prefix.strip("."):
        return ", ".join(targets)
    rest = [separator.join(parts[shared:]) for parts in split]
    return f"{prefix}{separator}{{{', '.join(rest)}}}"


def _close_matches(store: Store, needle: str, n: int = 5) -> list[SymbolHit]:
    """Symbols to suggest after a miss: names containing ``needle``, else
    near-spellings (``withRetri`` -> ``withRetry``)."""
    hits = store.find_symbols(needle, limit=n)
    if hits:
        return hits
    names = difflib.get_close_matches(needle, store.symbol_names(), n=n, cutoff=0.75)
    out: list[SymbolHit] = []
    for name in names:
        out.extend(store.exact_symbols(name)[:2])
    return out[:n]


def _stat(s) -> dict[str, Any]:
    return {"dir": s.dir, "files": s.files, "symbols": s.symbols}


_COMMENT_LINE = re.compile(r"^\s*(#(?!\[)|//|/\*|\*|--|;;)")


def _comment_start(source: list[str], line: int) -> int:
    """First line of the comment block directly above ``line`` (its doc),
    or ``line`` itself; context lines alone can cut a long doc in half."""
    first = min(line, len(source))
    while first > 1 and _COMMENT_LINE.match(source[first - 2]):
        first -= 1
    return first


def _enclosing(symbols: list[SymbolHit], line: int) -> SymbolHit | None:
    """The innermost symbol whose line range contains ``line``."""
    best = None
    for hit in symbols:
        if hit.start_line <= line <= hit.end_line:
            if best is None or (hit.end_line - hit.start_line) <= (best.end_line - best.start_line):
                best = hit
    return best
