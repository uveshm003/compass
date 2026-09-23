"""Doc-comment attachment and the one-line summaries shown in map shards (IX-04).

The leading-comment rule: walk back from a definition through the comments
directly above it, stopping at a blank line or at anything that is not a
comment. Decorators and attributes may sit between the comment and the
definition, and the walk climbs through wrapper nodes (``export``,
``decorated_definition``) when the definition is their only real child.
Languages can add a docstring rule on top (Python: first string in the body).
"""

from __future__ import annotations

import re
import textwrap

from tree_sitter import Node

from compass.languages import LanguageSpec

SUMMARY_CHARS = 120

_LINE_MARKERS = ("///", "//!", "//", "#", "--", ";;")
_LICENSE = re.compile(
    r"\b(copyright|licen[cs]e[ds]?|spdx-license-identifier|all rights reserved)\b", re.IGNORECASE
)
_PRAGMA = re.compile(
    r"^\s*(-\*-.*-\*-|(vim?|ex):|coding[:=]|type:\s*ignore|noqa|pylint:|mypy:|pyright:|"
    r"eslint|@ts-|prettier-ignore|jshint|istanbul|global\s|<reference\s|go:build|\+build|nolint)",
    re.IGNORECASE,
)
# Lines that end a doc's summary paragraph: tag blocks, section headings, fences.
_SECTION = re.compile(
    r"^\s*(@\w|:(param|type|return|returns|rtype|raises)\b|(Args|Arguments|Returns|Raises|Yields|"
    r"Examples?|Parameters|Notes?|See Also|Attributes)\s*:?\s*$|#{1,6}\s|```|~~~)"
)
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z0-9\"'`(\[])|[.!?]$")
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MD_REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
# [WSGI] or rustdoc's [`Error`], but not indexing like a[0].
_MD_SHORTCUT_LINK = re.compile(r"(?<![\w`\]])\[([^\]\[]+)\](?![(\[:])")
# Badge rows, image links and HTML: nothing a reader would call prose.
_IMAGE = re.compile(r"!\[[^\]]*\](\([^)]*\)|\[[^\]]*\])?")
_LINK_DEFINITION = re.compile(r"^\s*\[[^\]]+\]:\s*\S+")
_HTML_TAG = re.compile(r"<[^>]*>")
_ENTITY = re.compile(r"&(#\d+|[a-zA-Z]+);")
_EMPTY_LINK = re.compile(r"\[\s*\](\([^)]*\)|\[[^\]]*\])?")


def _is_markup_only(line: str) -> bool:
    if _LINK_DEFINITION.match(line):
        return True
    rest = _EMPTY_LINK.sub("", _ENTITY.sub("", _HTML_TAG.sub("", _IMAGE.sub("", line))))
    return re.search(r"[A-Za-z0-9]", rest) is None


def is_comment(node: Node) -> bool:
    return "comment" in node.type


def last_row(node: Node) -> int:
    """Last row a node occupies. Some grammars end line comments at column 0
    of the next row (they include the newline); count those as the row before."""
    row, column = node.end_point[0], node.end_point[1]
    if column == 0 and row > node.start_point[0]:
        return row - 1
    return row


def _starts_line(node: Node, src: bytes) -> bool:
    start = node.start_byte
    line_start = src.rfind(b"\n", 0, start) + 1
    return not src[line_start:start].strip()


def _is_inner_doc(text: str) -> bool:
    """``//!`` and ``/*!`` document the enclosing module, not the next item."""
    return text.lstrip().startswith(("//!", "/*!"))


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", "replace")


def clean_comment(raw: str) -> str:
    """Comment text without its markers (``//``, ``#``, ``/** */``, ``///``, ``--``)."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
    if text.startswith("/*"):
        body = text[2:]
        if body.endswith("*/"):
            body = body[:-2]
        body = body.lstrip("*!")
        lines = []
        for line in body.split("\n"):
            m = re.match(r"^\s*\*(?: |$)", line)
            lines.append(line[m.end() :] if m else line)
        # Like inspect.cleandoc: the first line starts right after `/*`, so only
        # the following lines share an indentation to remove.
        rest = textwrap.dedent("\n".join(lines[1:])).split("\n") if len(lines) > 1 else []
        return _trim([lines[0].strip(), *rest])
    lines = []
    for line in text.split("\n"):
        s = line.strip()
        for marker in _LINE_MARKERS:
            if s.startswith(marker):
                s = s[len(marker) :]
                break
        lines.append(s[1:] if s.startswith(" ") else s)
    return _trim(textwrap.dedent("\n".join(lines)).split("\n"))


def clean_docstring(raw: str) -> str | None:
    """A string literal's value, dedented the way ``inspect.cleandoc`` does."""
    s = raw.strip()
    m = re.match(r"^[rRuUbBfF]{0,2}(\"\"\"|'''|\"|')", s)
    if not m:
        return None
    quote = m.group(1)
    body = s[m.end() :]
    if body.endswith(quote):
        body = body[: -len(quote)]
    lines = body.expandtabs().split("\n")
    margin = min((len(l) - len(l.lstrip()) for l in lines[1:] if l.strip()), default=0)
    cleaned = [lines[0].strip()] + [l[margin:].rstrip() for l in lines[1:]]
    return _trim(cleaned) or None


def _trim(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(line.rstrip() for line in lines)


def climb(node: Node, spec: LanguageSpec) -> list[Node]:
    """``node`` plus each wrapper it is the only real child of, innermost first."""
    path = [node]
    current = node
    while True:
        parent = current.parent
        if parent is None or parent.type not in spec.wrappers:
            return path
        for child in parent.named_children:
            if _same(child, current) or is_comment(child) or child.type in spec.skip_before_doc:
                continue
            return path
        path.append(parent)
        current = parent


def _same(a: Node, b: Node) -> bool:
    return a.start_byte == b.start_byte and a.end_byte == b.end_byte and a.kind_id == b.kind_id


def start_row(path: list[Node], spec: LanguageSpec) -> int:
    """First row of a definition, including decorators and attributes above it."""
    outer = path[-1]
    row = outer.start_point[0]
    sibling = outer.prev_sibling
    while sibling is not None:
        if sibling.is_named:
            if sibling.type not in spec.skip_before_doc:
                break
            row = min(row, sibling.start_point[0])
        sibling = sibling.prev_sibling
    return row


def leading_comment(path: list[Node], src: bytes, spec: LanguageSpec) -> tuple[str | None, list[Node]]:
    """Doc text from the comments directly above a definition, and the nodes used."""
    comments: list[Node] = []
    anchor = path[0].start_point[0]
    for level in path:
        anchor = min(anchor, level.start_point[0])
        sibling = level.prev_sibling
        blocked = False
        while sibling is not None:
            if is_comment(sibling):
                text = _text(sibling)
                if (
                    last_row(sibling) < anchor - 1  # a blank line in between
                    or not _starts_line(sibling, src)  # trails code on its line
                    or _is_inner_doc(text)
                    or (sibling.start_byte == 0 and text.startswith("#!"))
                ):
                    blocked = True
                    break
                comments.append(sibling)
                anchor = sibling.start_point[0]
            elif comments:
                blocked = True  # anything but another comment ends the block
                break
            elif not sibling.is_named:
                pass  # keywords such as `export` or `const`
            elif sibling.type in spec.skip_before_doc:
                anchor = min(anchor, sibling.start_point[0])
            else:
                blocked = True
                break
            sibling = sibling.prev_sibling
        if comments or blocked:
            break
    if not comments:
        return None, []
    comments.reverse()
    # Lint and type-checker directives above a definition are not its doc.
    text = _trim([line for line in clean_comments(comments).split("\n") if not _PRAGMA.match(line)])
    return (text or None), comments


def clean_comments(nodes: list[Node]) -> str:
    """Clean a run of comments together, so line comments keep their relative
    indentation; block comments are cleaned one by one."""
    texts = [_text(n) for n in nodes]
    if not any(t.lstrip().startswith("/*") for t in texts):
        return clean_comment("\n".join(t.rstrip("\r\n") for t in texts))
    return "\n".join(clean_comment(t) for t in texts).strip()


def body_first_string(node: Node) -> str | None:
    """Python-style docstring: the first statement of the body, when it is a string."""
    body = node.child_by_field_name("body")
    return _first_string(body) if body is not None else None


def module_docstring(root: Node) -> str | None:
    return _first_string(root)


def _first_string(block: Node) -> str | None:
    for child in block.named_children:
        if is_comment(child):
            continue
        if child.type == "expression_statement" and child.named_child_count:
            child = child.named_children[0]
        if child.type == "string":
            return clean_docstring(_text(child))
        return None
    return None


def file_header(root: Node, src: bytes, spec: LanguageSpec, used: set[int]) -> str | None:
    """A file's own description: its module docstring or first comment block.

    Skips shebangs, pragmas and license headers, and any comment already taken
    as a symbol's doc (``used`` holds their start bytes).
    """
    if spec.docstring == "body_first_string":
        doc = module_docstring(root)
        if doc:
            return doc
    groups: list[list[Node]] = []
    for child in root.children:
        if not is_comment(child):
            break
        if child.start_byte == 0 and src.startswith(b"#!"):
            continue
        if groups and child.start_point[0] <= last_row(groups[-1][-1]) + 1:
            groups[-1].append(child)
        else:
            groups.append([child])
    for group in groups:
        if any(c.start_byte in used for c in group):
            continue
        lines = clean_comments(group).split("\n")
        text = _trim([line for line in lines if not _PRAGMA.match(line)])
        if text and not _LICENSE.search(text):
            return text
    return None


def readme_summary(text: str) -> str | None:
    """First prose paragraph of a README, skipping titles, badges and front matter."""
    lines = text.replace("\r\n", "\n").split("\n")
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                start = i + 1
                break
    para: list[str] = []
    in_fence = in_comment = False
    i = start
    while i < len(lines):
        s = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        i += 1
        if in_comment:
            in_comment = "-->" not in s
            continue
        if s.startswith(("```", "~~~")):
            if para:
                break
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if s.startswith("<!--"):
            in_comment = "-->" not in s
            continue
        if not s:
            if para:
                break
            continue
        if not para and (
            s.startswith(("#", "<", "![", "[![", "..", "|", ">"))
            or _is_markup_only(s)
            or re.fullmatch(r"[=\-~^*#_+`:.]{3,}", s)
            or (nxt and re.fullmatch(r"[=\-~^*#_+`:.]{3,}", nxt))
        ):
            if nxt and re.fullmatch(r"[=\-~^*#_+`:.]{3,}", nxt):
                i += 1  # setext or reST underline
            continue
        para.append(s)
    if not para:
        return None
    return _MD_LINK.sub(r"\1", " ".join(para)) or None


def summary(doc: str | None, limit: int = SUMMARY_CHARS) -> str | None:
    """First sentence of a doc, as shown after ``—`` in a map shard."""
    if not doc:
        return None
    lines: list[str] = []
    for line in doc.strip().split("\n"):
        if not line.strip():
            if lines:
                break
            continue
        if _SECTION.match(line):
            break  # a doc that opens with `Args:` or `@param` has no summary
        if not lines and _is_markup_only(line):
            continue  # badge rows and link definitions above the prose
        lines.append(line.strip())
    text = " ".join(" ".join(lines).split())
    text = _MD_SHORTCUT_LINK.sub(r"\1", _MD_REF_LINK.sub(r"\1", _MD_LINK.sub(r"\1", text)))
    m = _SENTENCE_END.search(text)
    if m:
        text = text[: m.end()]
    if text.endswith("."):
        text = text[:-1]
    if len(text) > limit:
        cut = text[: limit - 1]
        space = cut.rfind(" ")
        if space > limit * 0.6:
            cut = cut[:space]
        text = cut.rstrip(" ,;:-") + "…"
    return text or None
