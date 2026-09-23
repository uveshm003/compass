"""Anchor tags (RO-02): the scanner, the stripper used by accept, and the
staged-lines check behind the pre-commit hook (RO-05).

Tags in this file are assembled at runtime (``AI + "change T3"``): a literal
tag in Compass's own sources would trip its own pre-commit check.
"""

from __future__ import annotations

import pytest

from compass.anchors import Anchor, parse_line, scan_repo, scan_text, shift_line, staged_anchors, strip_file, strip_line
from conftest import git, write

AI = "@ai" + ":"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (f"# {AI}change T3 — renamed for clarity", ("change", "T3", "renamed for clarity")),
        (f"// {AI}review T3 - picked the cheaper query", ("review", "T3", "picked the cheaper query")),
        (f"x = 1  # {AI}assume T3: amounts are in cents", ("assume", "T3", "amounts are in cents")),
        (f"<!-- {AI}todo T3 — add a diagram -->", ("todo", "T3", "add a diagram")),
        (f"/* {AI}change T12 — moved */", ("change", "T12", "moved")),
        (f"-- {AI}review JIRA-42 — index added", ("review", "JIRA-42", "index added")),
        (f"# {AI}change T3", ("change", "T3", "")),
    ],
)
def test_anchors_are_found_in_any_comment_syntax(line, expected):
    kind, task, note, _column = parse_line(line)
    assert (kind, task, note) == expected


@pytest.mark.parametrize(
    "line",
    [
        f"A comment such as `{AI}assume T12` marks it",  # a Markdown code span quoting a tag
        f"| `{AI}change <id>` | Mechanical change |",
        f"mail me at someone{AI}change T1",  # glued to a word
        f"# {AI}Change T3 — kinds are lowercase",
        f"# {AI}refactor T3 — not a kind",
        f"# {AI}change <id> — a placeholder",
        f"# {AI}change — no task id",
    ],
)
def test_text_that_only_looks_like_an_anchor_is_ignored(line):
    assert parse_line(line) is None


@pytest.mark.parametrize(
    ("line", "kept"),
    [
        (f"# {AI}change T3 — note", None),
        (f"    // {AI}review T3 — note", None),
        (f"x = 1  # {AI}change T3 — note", "x = 1"),
        (f"x = 1;  // {AI}change T3 — note", "x = 1;"),
        (f"/* {AI}change T3 — note */", None),
        (f"foo(); /* {AI}change T3 — note */", "foo();"),
        (f"foo(); /* {AI}change T3 — note */ bar();", "foo(); bar();"),
        (f"<!-- {AI}review T3 — note -->", None),
        (f"<p>x</p> <!-- {AI}change T3 — note -->", "<p>x</p>"),
        (f" * {AI}assume T3 — inside a doc block", None),
        (f"-- {AI}change T3 — note", None),
        (f"select 1; -- {AI}change T3", "select 1;"),
        (f"; {AI}change T3", None),
        (f"% {AI}change T3", None),
        (f"{{/* {AI}change T3 — JSX */}}", None),
        (f"# compute totals {AI}change T3 — note", "# compute totals"),  # the tag joined a longer comment
        (f"x = 1  # noqa: E501 {AI}change T3 — note", "x = 1  # noqa: E501"),
        (f"/* keep this {AI}change T3 — note */", "/* keep this */"),
        (f"# {AI}assume T3 — handles (a*) globs", None),  # `*)` without `(*` is just text
        (f"<%-- {AI}change T3 — note --%>", None),
    ],
)
def test_strip_line_removes_the_tag_and_its_comment(line, kept):
    assert strip_line(line) == kept


def test_strip_file_keeps_everything_else_byte_for_byte(tmp_path):
    source = (
        "import os\r\n"
        f"# {AI}change T3 — added the helper\r\n"
        "def helper():\r\n"
        f"    return os.sep  # {AI}assume T3 — POSIX only\r\n"
        f"    # {AI}review T9 — another task's tag stays\r\n"
        "\r\n"
    )
    path = tmp_path / "a.py"
    path.write_bytes(source.encode())
    result = strip_file(tmp_path, "a.py", "T3")
    assert (result.removed, result.deleted_lines) == (2, [2])
    assert path.read_bytes().decode() == (
        "import os\r\n"
        "def helper():\r\n"
        "    return os.sep\r\n"
        f"    # {AI}review T9 — another task's tag stays\r\n"
        "\r\n"
    )
    assert strip_file(tmp_path, "a.py", "T3") is None  # nothing left to strip


def test_strip_file_leaves_binary_and_missing_files_alone(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"\0" + f"# {AI}change T3".encode())
    assert strip_file(tmp_path, "blob.bin", "T3") is None
    assert strip_file(tmp_path, "missing.py", "T3") is None


def test_shift_line_follows_deleted_tag_lines():
    deleted = [2, 5]
    assert [shift_line(n, deleted) for n in (1, 2, 3, 5, 6, 9)] == [1, 2, 2, 4, 4, 7]


def test_scan_text_numbers_lines_like_editors():
    text = f"a\r\n\x0cb\n# {AI}todo T1 — later\n"
    assert scan_text("f.py", text) == [Anchor("f.py", 3, "todo", "T1", "later")]


def test_scan_repo_covers_untracked_files_and_skips_ignored_ones(make_repo):
    root = make_repo(files={
        ".gitignore": "build/\n",
        "tracked.py": f"x = 1  # {AI}change T1 — tracked\n",
        "build/out.py": f"# {AI}change T1 — ignored\n",
        ".compass/changes/T1.md": f"# {AI}change T1 — Compass's own state\n",
        "docs/tags.md": f"Write `{AI}change T1` to mark a change.\n",
    })
    git(root, "add", "tracked.py", ".gitignore")
    write(root, "new file.ts", f"// {AI}review T2 — untracked, with a space in its name\n")
    found = scan_repo(root)
    assert [(a.path, a.task) for a in found] == [("new file.ts", "T2"), ("tracked.py", "T1")]
    assert [a.path for a in scan_repo(root, "T2")] == ["new file.ts"]


def test_staged_anchors_are_only_the_added_lines(make_repo):
    root = make_repo(files={"old.py": f"# {AI}change T1 — committed long ago\nx = 1\n"})
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", "old")
    write(root, "old.py", f"# {AI}change T1 — committed long ago\nx = 2  # {AI}assume T4 — new\n")
    write(root, "naïve dir/new.go", f"package p\n\n// {AI}review T4 — fresh file\n")
    write(root, "unstaged.py", f"# {AI}change T4 — not staged\n")
    git(root, "add", "old.py", "naïve dir/new.go")
    found = staged_anchors(root)
    assert [(a.path, a.line, a.kind) for a in found] == [("naïve dir/new.go", 3, "review"), ("old.py", 2, "assume")]
