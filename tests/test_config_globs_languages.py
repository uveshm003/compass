from __future__ import annotations

import pytest

from compass.config import DEFAULTS, default_config, parse_config
from compass.globs import compile_globs
from compass.languages import load_registry, shebang_interpreter


def test_defaults_parse_and_match_the_template():
    config = default_config()
    assert config.warnings == []
    assert config.index.max_file_kb == 1024
    assert config.index.shard_token_limit == 2000
    assert "**/*.lock" in config.index.exclude
    assert DEFAULTS["prompt_gate"]["strictness"] == "warn"


def test_user_values_merge_over_defaults():
    config = parse_config("index:\n  max_file_kb: 64\n  exclude: ['docs/**']\n")
    assert config.warnings == []
    assert config.index.max_file_kb == 64
    assert config.index.exclude == ("docs/**",)  # lists replace
    assert config.index.shard_token_limit == 2000  # untouched keys keep defaults
    assert config.data["telemetry"]["enabled"] is True


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("index: [1, 2", "not valid YAML"),
        ("- a\n- b\n", "must be a mapping"),
        ("index:\n  max_file_kb: big\n", "index.max_file_kb should be a number"),
        ("index:\n  shard_token_limit: 0\n", "must be positive"),
        ("index:\n  exclude: [1, 2]\n", "list of text"),
        ("index:\n  exlude: ['x']\n", "unknown setting index.exlude"),
        ("review:\n  enabled: 'yes'\n", "review.enabled should be true/false"),
        ("version: 2\n", "version 2"),
    ],
)
def test_invalid_config_falls_back_with_a_warning(text, fragment):
    config = parse_config(text)
    assert any(fragment in w for w in config.warnings), config.warnings
    assert config.index.max_file_kb == 1024
    assert config.index.shard_token_limit == 2000


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("**/generated/**", "src/generated/a.ts", True),
        ("**/generated/**", "generated/a.ts", True),
        ("**/generated/**", "src/generatedx/a.ts", False),
        ("**/*.min.js", "a.min.js", True),
        ("**/*.min.js", "public/js/a.min.js", True),
        ("**/*.min.js", "a.js", False),
        ("vendor/**", "vendor/x/y.go", True),
        ("vendor/**", "src/vendor/y.go", False),
        ("*.lock", "deep/dir/Cargo.lock", True),
        ("node_modules", "a/node_modules/b/c.js", True),
        ("docs/", "docs/guide.md", True),
        ("/build", "build/out.txt", True),
        ("/build", "src/build/out.txt", False),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/sub/a.py", False),
        ("file?.txt", "file1.txt", True),
        ("[ab].txt", "a.txt", True),
        ("[!ab].txt", "a.txt", False),
    ],
)
def test_globs(pattern, path, matches):
    assert compile_globs([pattern])(path) is matches


def test_empty_glob_list_matches_nothing():
    assert compile_globs([])("anything") is False


@pytest.mark.parametrize("pattern", ["build[]", "[z-a]", "[", "a[!]b", "x[^]"])
def test_malformed_brackets_match_literally_instead_of_crashing(pattern):
    matches = compile_globs([pattern])
    assert matches(pattern) is True
    assert matches("unrelated/path.py") is False
    assert parse_config(f"index:\n  exclude: ['{pattern}']\n").warnings == []


def test_registry_detects_by_extension_filename_and_shebang():
    registry = load_registry()
    assert {s.name for s in registry} >= {"python", "typescript", "javascript", "go", "rust"}
    assert registry.detect("a/b.py") == "python"
    assert registry.detect("x.TSX") == "typescript"
    assert registry.get("typescript").grammar_for("x.tsx") == "tsx"
    assert registry.detect("lib.mjs") == "javascript"
    assert registry.detect("scripts/run", b"#!/usr/bin/env python3\n") == "python"
    assert registry.detect("scripts/run", b"#!/bin/bash\n") is None
    assert registry.detect("notes.txt") is None
    assert "__init__.py" in registry.index_files and "doc.go" in registry.index_files


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (b"#!/usr/bin/env python3\n", "python3"),
        (b"#!/usr/bin/python3.12 -u\n", "python3"),
        (b"#!/usr/bin/env -S node --flag\n", "node"),
        (b"#!/bin/sh\n", "sh"),
        (b"#!\n", ""),
    ],
)
def test_shebang_interpreter(line, expected):
    assert shebang_interpreter(line) == expected
