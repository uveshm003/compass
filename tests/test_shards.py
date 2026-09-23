"""Shard rendering: format, nesting and splitting (IX-06, NF-05)."""

from __future__ import annotations

from compass.index.shards import estimate_tokens, render_dir, render_index, render_symbols
from compass.index.store import DirStat, FileRow, SymbolRow


def sym(name, kind, start, end, parent=None, signature=None, doc=None, source=None, path="a.ts"):
    return SymbolRow(path, name, kind, parent, signature or name, start, end, doc, "author" if doc and not source else source)


def test_symbol_lines_follow_the_guide_format():
    rows = [
        sym("ReconnectPolicy", "class", 12, 40, doc="Retry strategy for dropped connections."),
        sym("next", "method", 30, 35, "ReconnectPolicy", "next(attempt: number): number", "Delay in ms."),
        sym("withRetry", "function", 71, 80, signature="withRetry<T>(op, policy): Promise<T>", doc="Wraps.", source="generated"),
    ]
    assert render_symbols(rows) == [
        "- L12  class ReconnectPolicy — Retry strategy for dropped connections",
        "- L30    method next(attempt: number): number — Delay in ms",
        "- L71  fn withRetry<T>(op, policy): Promise<T> ~ Wraps",
    ]


def test_members_defined_outside_their_owner_name_it():
    rows = [
        sym("Exponential", "struct", 3, 6, path="r.go"),
        sym("Next", "method", 9, 12, "Exponential", "Next(n int) time.Duration", path="r.go"),
    ]
    assert render_symbols(rows)[1] == "- L9  method Exponential.Next(n int) time.Duration"


def test_directory_header_counts_and_purpose():
    files = [FileRow("src/a.ts", "typescript", "File doc. More."), FileRow("src/b.json", None, None)]
    text = render_dir("src", files, [sym("f", "function", 1, 2, path="src/a.ts")], "Source code.", 2000)
    assert text == ["# src/  (2 files, 1 symbol) — Source code\n## a.ts — File doc\n- L1  fn f\n## b.json\n"]


def test_large_directories_split_under_the_token_limit():
    files = [FileRow(f"big/f{i:02}.py", "python", None) for i in range(30)]
    symbols = [
        sym(f"function_number_{j}", "function", j + 1, j + 1, signature=f"function_number_{j}(argument_one, argument_two)", path=f.path)
        for f in files
        for j in range(8)
    ]
    parts = render_dir("big", files, symbols, None, 500)
    assert len(parts) > 2
    assert all(estimate_tokens(p) <= 500 for p in parts)
    assert parts[0].startswith(f"# big/  (30 files, 240 symbols; part 1 of {len(parts)})")
    assert parts[0].rstrip().endswith("(continued in big~2.md)")
    body = "".join(parts)
    assert all(f"fn function_number_{j}(" in body for j in range(8))
    assert body.count("## f00.py") == 1  # a file that fits is never split


def test_a_single_huge_file_splits_with_continued_headers():
    rows = [sym(f"s{i}", "function", i, i, signature=f"s{i}(" + "x" * 60 + ")", path="h/huge.py") for i in range(1, 200)]
    parts = render_dir("h", [FileRow("h/huge.py", "python", None)], rows, None, 400)
    assert len(parts) > 3
    assert all(estimate_tokens(p) <= 400 for p in parts)
    assert "## huge.py (cont.)" in parts[1]


def test_an_oversized_file_starts_in_the_current_part():
    small = [FileRow("d/__init__.py", "python", None)]
    big = FileRow("d/app.py", "python", None)
    rows = [sym(f"m{i}", "function", i, i, signature=f"m{i}(" + "x" * 60 + ")", path="d/app.py") for i in range(1, 80)]
    parts = render_dir("d", [*small, big], rows, None, 600)
    assert "## app.py\n- L1  fn m1(" in parts[0]  # part 1 is not left holding only __init__.py


def test_index_orders_by_path_components():
    stats = [DirStat("test", 1, 0), DirStat("test-d", 1, 0), DirStat("test/helpers", 1, 0)]
    lines = render_index(stats, {}, 2000)[0].splitlines()[2:]
    assert lines == ["- test/  (1 file, 0 symbols)", "  - test/helpers/  (1 file, 0 symbols)", "- test-d/  (1 file, 0 symbols)"]


def test_index_is_a_tree_with_purposes():
    stats = [DirStat("", 2, 0), DirStat("src", 1, 3), DirStat("src/transport", 4, 23), DirStat("tests", 1, 1)]
    text = render_index(stats, {"src/transport": "Retry handling."}, 2000)
    assert text == [
        "# Code map  (8 files, 27 symbols)\n"
        "Shards: .compass/map/<dir>.md (repo root: _root.md); `—` author doc, `~` generated summary.\n"
        "- ./  (2 files, 0 symbols)\n"
        "- src/  (1 file, 3 symbols)\n"
        "  - src/transport/  (4 files, 23 symbols) — Retry handling\n"
        "- tests/  (1 file, 1 symbol)\n"
    ]
