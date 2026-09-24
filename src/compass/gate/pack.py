"""The context pack (C2, CP-01 to CP-03): what the code map already knows
about the names a prompt mentions, added to Claude's context so it can start
from ``path:line`` instead of searching.

It resolves each candidate name from the prompt against the index (a file, a
directory, a symbol), adds the tests for the files involved and a stack line
when the prompt names a framework or tool, and lists misspelt names with the
closest match (CP-03). An unresolved name with no close match says nothing
(``ValueError``, ``React``: not the project's own). Everything is read-only
SQLite, sorted, and cut at ``context_pack.token_budget``; it runs on every
prompt, inside NF-02's 300 ms.
"""

from __future__ import annotations

import difflib
import json
import posixpath
import re
from typing import Any

from compass.gate import ParsedPrompt
from compass.index.store import Store, SymbolHit, like_escape
from compass.repo import Repo

MAX_SYMBOL_HITS = 4
MAX_OUTLINE_LINES = 12
MAX_DIR_FILES = 12
MAX_TESTS = 3
MAX_SUGGESTIONS = 3
KIND_LABELS = {
    "function": "fn", "method": "method", "class": "class", "interface": "interface", "struct": "struct",
    "enum": "enum", "trait": "trait", "impl": "impl", "type": "type", "constant": "const", "variable": "var",
    "module": "module", "namespace": "namespace", "macro": "macro",
}
HEADER = "[compass] From the code map, for the names in this prompt (start here rather than searching):"


def estimate_tokens(text: str) -> int:
    return (len(text) + 2) // 3  # generous, like the shard writer's


def resolve(store: Store, parsed: ParsedPrompt) -> None:
    """Fill ``parsed.resolved``: candidate text -> {"file"|"dir"|"files"|"symbols": …}."""
    for candidate in parsed.candidates:
        found = _resolve_path(store, candidate.text) if candidate.kind == "path" else None
        if found is None and (candidate.kind == "symbol" or candidate.quoted):
            found = _resolve_symbol(store, candidate.text)
        if found is None and candidate.kind == "symbol" and candidate.quoted:
            found = _resolve_path(store, candidate.text)
        if found:
            parsed.resolved[candidate.text] = found


def _resolve_path(store: Store, text: str) -> dict[str, Any] | None:
    rel = posixpath.normpath(text.replace("\\", "/")).lstrip("/")
    rel = "" if rel == "." else rel.removeprefix("./")
    if not rel:
        return None
    if store.file_info(rel) is not None:
        return {"file": rel}
    if store.has_dir(rel):
        return {"dir": rel}
    named = store.paths_named(rel, MAX_TESTS + 1)
    if named:
        return {"files": named[:MAX_TESTS]}
    return None


def _resolve_symbol(store: Store, text: str) -> dict[str, Any] | None:
    cleaned = text.strip().removesuffix("()")
    parts = [p for p in re.split(r"\.|::|#", cleaned) if p]
    needle, parent = (parts[-1], ".".join(parts[:-1])) if len(parts) > 1 else (cleaned, None)
    hits = store.exact_symbols(needle, parent)
    if not hits and parent:
        hits = store.exact_symbols(needle)
    return {"symbols": hits[:MAX_SYMBOL_HITS]} if hits else None


def build(store: Store, parsed: ParsedPrompt, budget: int, stack: dict[str, Any] | None = None) -> str:
    """The pack as text, or ``""`` when the prompt names nothing the map knows."""
    sections: list[list[str]] = []
    files: list[str] = []
    for text, found in parsed.resolved.items():
        if "symbols" in found:
            sections.append([f"- `{text}`: {_hit_line(h)}" for h in found["symbols"]])
            files += [h.path for h in found["symbols"] if not h.is_test]
    for text, found in parsed.resolved.items():
        if "file" in found:
            sections.append(_outline(store, found["file"]))
            files.append(found["file"])
        elif "files" in found:
            sections.append([f"- `{text}` matches: {', '.join(found['files'])}"])
            files += found["files"]
        elif "dir" in found:
            sections.append(_dir_listing(store, found["dir"]))
    tests = _tests(store, list(dict.fromkeys(files)))
    if tests:
        sections.append(["Tests: " + "; ".join(tests)])
    stack_line = _stack_line(stack, parsed)
    if stack_line:
        sections.append([stack_line])
    misspelt = _suggestions(store, parsed)
    if misspelt:
        sections.append(["Not in the code map: " + "; ".join(misspelt)])
    if not sections:
        return ""
    lines = [HEADER]
    left = budget - estimate_tokens(HEADER)
    dropped = 0
    for section in sections:
        for line in section:
            cost = estimate_tokens(line) + 1
            if cost > left:
                dropped += 1
                continue
            lines.append(line)
            left -= cost
    if dropped:
        lines.append(f"[compass] {dropped} more lines left out to stay within the pack's budget; ask find_symbol or map.")
    return "\n".join(lines)


def _hit_line(hit: SymbolHit) -> str:
    label = KIND_LABELS.get(hit.kind, hit.kind)
    signature = hit.signature or hit.name
    if hit.parent:
        signature = f"{hit.parent}.{signature}"
    doc = _summary(hit.doc)
    return f"{hit.path}:{hit.start_line}-{hit.end_line}  {label} {signature}" + (f" — {doc}" if doc else "")


def _outline(store: Store, rel: str) -> list[str]:
    info = store.file_info(rel) or {}
    symbols = store.file_symbols(rel)
    doc = _summary(info.get("doc"))
    head = f"- {rel} ({info.get('lang') or 'no parser'}, {len(symbols)} symbols)" + (f" — {doc}" if doc else "")
    lines = [head]
    for hit in symbols[:MAX_OUTLINE_LINES]:
        indent = "    " if hit.parent else "  "
        name = f"{hit.parent}.{hit.signature or hit.name}" if hit.parent else (hit.signature or hit.name)
        lines.append(f"{indent}L{hit.start_line} {KIND_LABELS.get(hit.kind, hit.kind)} {name}")
    if len(symbols) > MAX_OUTLINE_LINES:
        lines.append(f"  … {len(symbols) - MAX_OUTLINE_LINES} more (file_outline has them all)")
    return lines


def _dir_listing(store: Store, directory: str) -> list[str]:
    names = [posixpath.basename(f.path) for f in store.dir_files(directory)]
    shown = ", ".join(names[:MAX_DIR_FILES]) + (f", … ({len(names)} in all)" if len(names) > MAX_DIR_FILES else "")
    return [f"- {directory}/: {shown or 'only subdirectories'} (map has the symbols)"]


def _tests(store: Store, files: list[str]) -> list[str]:
    """For each file, the test files that import it or are named after it."""
    if not files:
        return []
    test_paths = [p for p, _lang in store.test_files()]
    by_stem: dict[str, list[str]] = {}
    for path in test_paths:
        by_stem.setdefault(_test_stem(path), []).append(path)
    tests_set = set(test_paths)
    out = []
    for rel in files[:MAX_TESTS * 2]:
        if rel in tests_set:
            continue
        stem = posixpath.splitext(posixpath.basename(rel))[0]
        found = list(by_stem.get(stem, []))
        found += [p for p, _t, _r in store.importers_of([rel]) if p in tests_set and p not in found]
        if found:
            out.append(f"{', '.join(sorted(found)[:MAX_TESTS])} (for {rel})")
    return out[:MAX_TESTS]


def _test_stem(path: str) -> str:
    stem = posixpath.splitext(posixpath.basename(path))[0]
    for affix in ("test_", "tests_"):
        if stem.startswith(affix):
            return stem[len(affix) :]
    for affix in ("_test", "_tests", ".test", ".spec", "Test", "Tests", "_spec"):
        if stem.endswith(affix):
            return stem[: -len(affix)]
    return stem


def stack_mentions(stack: dict[str, Any] | None, parsed: ParsedPrompt) -> list[str]:
    """The project's frameworks and tools the prompt names, with versions."""
    if not stack:
        return []
    words = set(parsed.words) | {c.text.lower() for c in parsed.candidates}
    named = set()
    for entry in stack.get("entries", []):
        for name, version in {**entry.get("frameworks", {}), **entry.get("tools", {})}.items():
            if name.lower() in words or name.lower().split("/")[-1] in words:
                named.add(f"{name} {version}" if version else name)
    return sorted(named)


def _stack_line(stack: dict[str, Any] | None, parsed: ParsedPrompt) -> str | None:
    """Versions for the frameworks and tools the prompt names (ST-02 again,
    where it matters)."""
    named = parsed.stack or stack_mentions(stack, parsed)
    return f"Stack versions in use: {', '.join(named)}" if named else None


def _suggestions(store: Store, parsed: ParsedPrompt) -> list[str]:
    """Names that look misspelt: unresolved, with a close match in the map.
    Candidates share the first two letters, so the lookup stays small."""
    out = []
    for candidate in parsed.candidates:
        if candidate.text in parsed.resolved or candidate.kind != "symbol" or len(out) >= MAX_SUGGESTIONS:
            continue
        name = re.split(r"\.|::|#", candidate.text.removesuffix("()"))[-1]
        if len(name) < 4:
            continue
        rows = store.conn.execute(
            "SELECT DISTINCT name FROM symbols WHERE name LIKE ? ESCAPE '\\' LIMIT 2000",
            (like_escape(name[:2]) + "%",),
        )
        close = difflib.get_close_matches(name, [r[0] for r in rows], n=1, cutoff=0.8)
        if close and close[0] != name:
            out.append(f"`{candidate.text}` (did you mean {close[0]}?)")
    return out


def _summary(doc: str | None, limit: int = 100) -> str | None:
    if not doc:
        return None
    first = doc.strip().split("\n\n", 1)[0].replace("\n", " ")
    first = re.split(r"(?<=[.!?])\s", first, maxsplit=1)[0].rstrip(".")
    return first if len(first) <= limit else first[: limit - 1] + "…"


def load_stack(repo: Repo) -> dict[str, Any] | None:
    """The stack summary SessionStart cached in ``.compass/stack.json``."""
    try:
        return json.loads((repo.compass_dir / "stack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
