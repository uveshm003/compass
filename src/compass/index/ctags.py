"""universal-ctags fallback for languages without a tags query (IX-02).

Optional: when no Universal Ctags build with JSON output is on PATH, files in
other languages are still enumerated and mapped, just without symbols.
Set ``COMPASS_CTAGS`` to point at a specific executable.
"""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from compass.index.docs import clean_comment
from compass.index.model import FileParse, Symbol, source_lines
from compass.index.parser import normalize_signature

CTAGS_ENV = "COMPASS_CTAGS"
TIMEOUT_S = 120

# Documents and data formats: ctags can tag them, but their headings and keys
# are not code symbols.
SKIP_LANGUAGES = frozenset(
    {
        "asciidoc", "bibtex", "dtd", "glade", "iniconf", "json", "man", "markdown",
        "passwd", "plist", "rst", "restructuredtext", "svg", "tex", "toml", "txt2tags",
        "xml", "xslt", "yaml", "relaxng", "maven2", "ant", "systemdunit", "diff", "org",
    }
)
_CONTAINER_SCOPES = frozenset({"class", "interface", "struct", "trait", "enum", "module"})
_COMMENT_LINE = re.compile(r"^\s*(#|//|--|;|%|\*|/\*|\*/|')")
_FIELDS = "{name}{input}{line}{end}{kind}{scope}{scopeKind}{signature}{language}{access}"


@functools.cache
def find_ctags() -> tuple[str, str] | None:
    """(executable, version line) of a Universal Ctags that writes JSON, or None.

    ``COMPASS_CTAGS`` overrides the PATH lookup; ``off`` (or empty) disables ctags.
    """
    override = os.environ.get(CTAGS_ENV)
    if override is not None:
        candidates = [] if override.strip().lower() in ("", "off", "0", "none") else [override]
    else:
        candidates = [shutil.which(n) for n in ("universal-ctags", "uctags", "ctags")]
    for exe in candidates:
        if not exe:
            continue
        try:
            version = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
            if "Universal Ctags" not in version.stdout:
                continue
            features = subprocess.run([exe, "--list-features"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if re.search(r"^json\b", features.stdout, re.MULTILINE):
            return exe, version.stdout.splitlines()[0].strip()
    return None


def ctags_symbols(root: Path, sources: dict[str, bytes]) -> dict[str, FileParse]:
    """Symbols for the given files, keyed by path; files ctags skips are absent."""
    found = find_ctags()
    if found is None or not sources:
        return {}
    exe, _version = found
    proc = subprocess.run(
        [exe, "--output-format=json", f"--fields={_FIELDS}", "--sort=no", "-f", "-", "-L", "-"],
        cwd=root,
        input="\n".join(sorted(sources)).encode("utf-8"),
        capture_output=True,
        timeout=TIMEOUT_S,
        check=False,
    )
    tags: dict[str, list[dict]] = {}
    languages: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        try:
            tag = json.loads(line)
        except ValueError:
            continue
        if tag.get("_type") != "tag" or not tag.get("name") or not tag.get("path"):
            continue
        language = str(tag.get("language", "")).lower()
        if language in SKIP_LANGUAGES:
            continue
        path = str(tag["path"]).replace("\\", "/")
        if path not in sources:
            continue
        tags.setdefault(path, []).append(tag)
        languages[path] = language
    out = {}
    for path, entries in tags.items():
        lines = source_lines(sources[path])
        symbols = {_symbol(tag, lines) for tag in entries}
        out[path] = FileParse(symbols=tuple(sorted(symbols, key=Symbol.sort_key)), lang=languages[path])
    return out


def _symbol(tag: dict, lines: list[str]) -> Symbol:
    name = str(tag["name"])
    kind = str(tag.get("kind", "symbol")).lower()
    if kind == "function" and tag.get("scopeKind") in _CONTAINER_SCOPES - {"module"}:
        kind = "method"
    start = int(tag.get("line", 1))
    end = max(start, int(tag.get("end", start)))
    signature = normalize_signature(name + str(tag.get("signature", "")))
    doc = _comment_above(lines, start)
    return Symbol(
        name=name,
        kind=kind,
        parent=tag.get("scope") or None,
        signature=signature,
        start_line=start,
        end_line=end,
        visibility=tag.get("access") or None,
        doc=doc,
        doc_source="author" if doc else None,
    )


def _comment_above(lines: list[str], line_no: int) -> str | None:
    """The leading-comment rule on raw lines, for parsers that give no tree."""
    block: list[str] = []
    i = line_no - 2
    while i >= 0 and lines[i].strip() and _COMMENT_LINE.match(lines[i]):
        block.append(lines[i])
        i -= 1
    if not block:
        return None
    block.reverse()
    return clean_comment("\n".join(block)) or None
