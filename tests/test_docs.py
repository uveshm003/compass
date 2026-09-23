from __future__ import annotations

import pytest

from compass.index.docs import clean_comment, clean_docstring, readme_summary, summary
from compass.index.model import is_readme


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("// Delay in ms.", "Delay in ms."),
        ("/// Rust doc line", "Rust doc line"),
        ("# Python comment", "Python comment"),
        ("-- SQL comment", "SQL comment"),
        ("/** Retry strategy. */", "Retry strategy."),
        ("/**\n * Wraps an op.\n *\n * @param op the op\n */", "Wraps an op.\n\n@param op the op"),
        ("/* plain\n   block */", "plain\nblock"),
        ("// Example:\n//\n//     run()", "Example:\n\n    run()"),
    ],
)
def test_clean_comment(raw, expected):
    assert clean_comment(raw) == expected


def test_clean_docstring():
    assert clean_docstring('"""Summary.\n\n    Details here.\n    """') == "Summary.\n\nDetails here."
    assert clean_docstring("r'''raw'''") == "raw"
    assert clean_docstring("not a string") is None


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ("Delay in ms, exponential with jitter.", "Delay in ms, exponential with jitter"),
        ("First sentence. Second sentence.", "First sentence"),
        ("Wraps an op.\n@param op the operation", "Wraps an op"),
        ("Summary line\ncontinues here.\n\nMore detail.", "Summary line continues here"),
        ("Uses v2.0 of the API. Then more.", "Uses v2.0 of the API"),
        ("Is it done? Yes.", "Is it done?"),
        ("Args:\n    x: thing", None),
        ("", None),
    ],
)
def test_summary(doc, expected):
    assert summary(doc) == expected


def test_summary_skips_badges_and_unwraps_links():
    doc = (
        "[![github]](https://github.com/x/y)&ensp;[![docs-rs]](https://docs.rs/y)\n"
        "[github]: https://img.shields.io/badge/github\n\n"
        "This library provides [`anyhow::Error`][Error], a [trait object] for errors.\n"
    )
    assert summary(doc) == "This library provides `anyhow::Error`, a trait object for errors"
    assert summary("Reads a[0] and [the docs](http://x).") == "Reads a[0] and the docs"
    assert readme_summary('[<img alt="ci" src="b.svg">](ci)\n\nFlask is a [WSGI] framework.\n') == (
        "Flask is a [WSGI] framework."
    )


def test_summary_caps_length_at_a_word_boundary():
    text = summary("word " * 60)
    assert len(text) <= 120 and text.endswith("word…")


def test_readme_summary_skips_titles_badges_and_front_matter():
    text = "---\ntitle: x\n---\n# Title\n\n[![CI](b.svg)](ci)\n\nDoes the [thing](http://x).\nWell.\n\n## More\n"
    assert readme_summary(text) == "Does the thing. Well."
    assert readme_summary("Title\n=====\n\nBody text.\n") == "Body text."
    assert readme_summary("# Only a title\n") is None


def test_is_readme():
    assert is_readme("README.md") and is_readme("docs/readme.rst") and is_readme("pkg/README")
    assert not is_readme("README.mdx.bak") and not is_readme("readme_helpers.py")
