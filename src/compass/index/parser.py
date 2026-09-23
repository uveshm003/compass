"""Symbol extraction with tree-sitter tags queries (IX-02, IX-03).

py-tree-sitter's query API changed across releases (``Query.captures`` became
``QueryCursor``); this module is the only place that touches it, against the
version pinned in pyproject.toml.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from tree_sitter import Node, Parser, Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

from compass.index import docs
from compass.index.model import FileParse, Ref, Symbol
from compass.languages import LanguageSpec

SIGNATURE_CHARS = 160

# A function nested in one of these becomes a method.
CONTAINER_KINDS = frozenset({"class", "interface", "struct", "enum", "trait", "impl"})
# Members of these are not module-level declarations for visibility purposes.
MEMBER_OF_KINDS = CONTAINER_KINDS | {"type"}
# Definitions inside these are local and left out of the map.
CALLABLE_KINDS = frozenset({"function", "method"})
# Members without their own modifier inherit these containers' visibility.
INHERIT_VISIBILITY_KINDS = frozenset({"interface", "trait"})
# Groupings that have no visibility of their own (their members do).
UNSCOPED_KINDS = frozenset({"impl"})

_TRAILING = re.compile(r"\s*(\{|:|=>|=|;|,)\s*$")


@dataclass
class _Compiled:
    parser: Parser
    tags: Query
    imports: Query | None


@dataclass
class _Def:
    pattern: int
    kind: str
    node: Node
    name: Node
    parent_name: str | None = None
    visibility_node: Node | None = None
    visibility_fixed: str | None = None
    signature_node: Node | None = None
    params: list[Node] = field(default_factory=list)
    body: Node | None = None


_COMPILED: dict[tuple[str, str], _Compiled] = {}
# A tree-sitter parser is not safe to share between threads, and the MCP server
# runs tool calls on worker threads.
_PARSE_LOCK = threading.Lock()


def _compiled(spec: LanguageSpec, grammar: str) -> _Compiled:
    key = (spec.name, grammar)
    found = _COMPILED.get(key)
    if found is None:
        language = get_language(grammar)
        imports_src = spec.imports_query()
        found = _Compiled(
            parser=get_parser(grammar),
            tags=Query(language, spec.tags_query()),
            imports=Query(language, imports_src) if imports_src else None,
        )
        _COMPILED[key] = found
    return found


def _key(node: Node) -> tuple[int, int, int]:
    return (node.start_byte, node.end_byte, node.kind_id)


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", "replace")


def parse_source(spec: LanguageSpec, path: str, src: bytes) -> FileParse:
    with _PARSE_LOCK:
        compiled = _compiled(spec, spec.grammar_for(path))
        root = compiled.parser.parse(src).root_node
    found_defs, refs = _collect(compiled.tags, root)
    ordered = sorted(
        found_defs,
        key=lambda d: (d.node.start_byte, -d.node.end_byte, d.name.start_byte, d.pattern),
    )
    by_node: dict[tuple[int, int, int], _Def] = {}
    for d in ordered:
        by_node.setdefault(_key(d.node), d)  # `var a, b int`: one node, several names
    enclosing: dict[tuple[int, int, int], _Def | None] = {}
    for d in ordered:
        ancestor = d.node.parent
        found = None
        while ancestor is not None:
            found = by_node.get(_key(ancestor))
            if found is not None:
                break
            ancestor = ancestor.parent
        enclosing[_key(d.node)] = found

    symbols: list[Symbol] = []
    visibility_of: dict[tuple[int, int, int], str | None] = {}
    kind_of: dict[tuple[int, int, int], str] = {}
    used_comments: set[int] = set()
    for d in ordered:
        chain: list[_Def] = []
        outer = enclosing[_key(d.node)]
        local = False
        while outer is not None:
            if kind_of.get(_key(outer.node), outer.kind) in CALLABLE_KINDS:
                local = True
                break
            chain.append(outer)
            outer = enclosing[_key(outer.node)]
        if local:
            continue
        nearest = chain[0] if chain else None
        nearest_kind = kind_of.get(_key(nearest.node), nearest.kind) if nearest else None
        kind = d.kind
        if kind == "function" and nearest_kind in CONTAINER_KINDS:
            kind = "method"
        kind_of[_key(d.node)] = kind

        name = _clean_name(_text(d.name))
        if chain:
            parent = ".".join(_clean_name(_text(c.name)) for c in reversed(chain))
        else:
            parent = d.parent_name
        path_nodes = docs.climb(d.node, spec)
        wrapper_types = {n.type for n in path_nodes[1:]}
        visibility = _visibility(
            spec,
            d,
            name,
            nearest_kind,
            visibility_of.get(_key(nearest.node)) if nearest else None,
            wrapper_types,
        )
        visibility_of[_key(d.node)] = visibility

        doc = None
        if spec.docstring == "body_first_string":
            doc = docs.body_first_string(d.node)
        if doc is None:
            doc, used = docs.leading_comment(path_nodes, src, spec)
            used_comments.update(c.start_byte for c in used)
        symbols.append(
            Symbol(
                name=name,
                kind=kind,
                parent=parent,
                signature=_signature(d, src, by_node[_key(d.node)].name) or name,
                start_line=docs.start_row(path_nodes, spec) + 1,
                end_line=docs.last_row(d.node) + 1,
                visibility=visibility,
                doc=doc,
                doc_source="author" if doc else None,
            )
        )

    symbols.sort(key=Symbol.sort_key)
    return FileParse(
        symbols=tuple(symbols),
        imports=_imports(compiled.imports, root, spec.imports.separator),
        doc=docs.file_header(root, src, spec, used_comments),
        refs=tuple(sorted(refs, key=lambda r: (r.line, r.name, r.kind))),
    )


def _collect(query: Query, root: Node) -> tuple[list[_Def], set[Ref]]:
    """Definitions and call references, from one pass over the tags query."""
    defs: dict[tuple[int, int, int, int], _Def] = {}
    refs: set[Ref] = set()
    for pattern, caps in QueryCursor(query).matches(root):
        kind = node = None
        ref_kind = None
        for capture, nodes in caps.items():
            if capture.startswith("definition."):
                kind, node = capture[len("definition.") :], nodes[0]
                break
            if capture.startswith("reference."):
                ref_kind = capture[len("reference.") :]
        names = caps.get("name")
        if node is None and ref_kind and names:
            refs.add(Ref(_clean_name(_text(names[0])), names[0].start_point[0] + 1, ref_kind))
            continue
        if node is None or not names:
            continue
        key = (*_key(node), names[0].start_byte)
        existing = defs.get(key)
        if existing is not None and existing.pattern <= pattern:
            continue  # the earlier pattern is the more specific one
        fixed = next((c.split(".", 1)[1] for c in caps if c.startswith("visibility.")), None)
        defs[key] = _Def(
            pattern=pattern,
            kind=kind,
            node=node,
            name=names[0],
            parent_name=_clean_name(_text(caps["parent"][0])) if "parent" in caps else None,
            visibility_node=caps["visibility"][0] if "visibility" in caps else None,
            visibility_fixed=fixed,
            signature_node=caps["signature"][0] if "signature" in caps else None,
            params=list(caps.get("params", [])),
            body=caps["body"][0] if "body" in caps else None,
        )
    return list(defs.values()), refs


def _clean_name(name: str) -> str:
    return " ".join(name.split()).strip("\"'`")


def _signature(d: _Def, src: bytes, first_name: Node) -> str:
    """Name, parameters and return type, from the name up to the body.

    Every name of a multi-name declaration (``var a, b int``) gets the whole
    declaration, starting at its first name."""
    prefix = ""
    if d.params:
        start = min(n.start_byte for n in d.params)
        prefix = _clean_name(_text(d.name))
    elif d.signature_node is not None:
        start = d.signature_node.start_byte
    else:
        start = min(d.name.start_byte, first_name.start_byte)
    end = None
    body = d.body if d.body is not None else d.node.child_by_field_name("body")
    if body is not None and body.start_byte > start:
        end = body.start_byte
    if end is None:
        newline = src.find(b"\n", start)
        end = min(d.node.end_byte, len(src) if newline == -1 else newline)
    text = normalize_signature(_without_comments(d.node, src, start, end).decode("utf-8", "replace"))
    if prefix and not text.startswith(("(", "<", "[")):
        text = f"({text})"  # a bare arrow-function parameter: x => ...
    return normalize_signature(prefix + text)


def _without_comments(node: Node, src: bytes, start: int, end: int) -> bytes:
    """``src[start:end]`` minus any comments inside it (a comment between a
    Python signature and its body, or inside a parameter list)."""
    cuts = []
    pending = [node]
    while pending:
        current = pending.pop()
        if current.end_byte <= start or current.start_byte >= end:
            continue
        if docs.is_comment(current):
            cuts.append((max(current.start_byte, start), min(current.end_byte, end)))
        else:
            pending.extend(current.children)
    if not cuts:
        return src[start:end]
    out, pos = [], start
    for cut_start, cut_end in sorted(cuts):
        out.append(src[pos:cut_start])
        pos = max(pos, cut_end)
    out.append(src[pos:end])
    return b" ".join(out)


def normalize_signature(text: str) -> str:
    s = " ".join(text.split())
    s = re.sub(r"([(\[{])\s+", r"\1", s)
    s = re.sub(r"\s+([)\]}])", r"\1", s)
    s = re.sub(r",\s*([)\]}])", r"\1", s)
    while True:
        stripped = _TRAILING.sub("", s)
        if stripped == s:
            break
        s = stripped
    if len(s) > SIGNATURE_CHARS:
        s = s[: SIGNATURE_CHARS - 1].rstrip() + "…"
    return s


def _visibility(
    spec: LanguageSpec,
    d: _Def,
    name: str,
    parent_kind: str | None,
    parent_visibility: str | None,
    wrapper_types: set[str],
) -> str | None:
    rule = spec.visibility
    if d.visibility_fixed:
        return d.visibility_fixed
    if d.kind in UNSCOPED_KINDS:
        return None
    if d.visibility_node is not None:
        text = " ".join(_text(d.visibility_node).split())
        for pattern, value in rule.modifiers:
            if pattern.search(text):
                return value
    for pattern, value in rule.names:
        if pattern.search(name):
            return value
    if rule.exported_by and parent_kind not in MEMBER_OF_KINDS:
        return "public" if wrapper_types & rule.exported_by else "private"
    if parent_kind in INHERIT_VISIBILITY_KINDS and parent_visibility:
        return parent_visibility
    return rule.default


def _imports(query: Query | None, root: Node, separator: str) -> tuple[str, ...]:
    """Import targets. With an ``@import.member`` capture (``from pkg import
    mod``) the target is the module and the member joined by ``separator``."""
    if query is None:
        return ()
    found: set[str] = set()
    for _pattern, caps in QueryCursor(query).matches(root):
        members = [_clean_name(_text(n)) for n in caps.get("import.member", [])]
        for node in caps.get("import", []):
            module = _clean_name(_text(node))
            if not module:
                continue
            if not members:
                found.add(module)
            for member in filter(None, members):
                joiner = "" if module.endswith(separator) else separator
                found.add(f"{module}{joiner}{member}")
    return tuple(sorted(found))
