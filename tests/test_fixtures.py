"""Snapshot tests over the fixture repos: index rows, map shards, file list and
stack profile. A language counts as supported only with a fixture here."""

from __future__ import annotations

import json

import pytest

from compass.config import load_config
from compass.files import enumerate_files
from compass.globs import compile_globs
from compass.index.indexer import Indexer
from compass.index.store import Store
from compass.languages import load_registry
from compass.repo import Repo
from compass.stack import build_profile
from conftest import FIXTURE_NAMES, read_tree

LANGUAGES = {"python_app": {"python"}, "ts_app": {"typescript", "javascript"}, "go_app": {"go"}, "rust_app": {"rust"}}


def test_fixtures_cover_four_languages():
    assert len(FIXTURE_NAMES) >= 4
    covered = set().union(*(LANGUAGES[name] for name in FIXTURE_NAMES))
    assert {"python", "typescript", "javascript", "go", "rust"} <= covered


@pytest.mark.parametrize("fixture", FIXTURE_NAMES)
def test_index_and_shards_snapshot(fixture, make_repo, snapshot):
    root = make_repo(fixture)
    repo = Repo(root)
    result = Indexer(repo).build()
    assert result.mode == "full"
    with Store.open(repo.db_path) as store:
        dump = store.dump()
    languages = {row["lang"] for row in dump["files"]} - {None}
    assert languages == LANGUAGES[fixture]
    snapshot(f"{fixture}/index.json", json.dumps(dump, indent=1, ensure_ascii=False) + "\n")
    snapshot.tree(f"{fixture}/map", read_tree(repo.map_dir))


@pytest.mark.parametrize("fixture", FIXTURE_NAMES)
def test_files_and_stack_snapshot(fixture, make_repo, snapshot):
    root = make_repo(fixture)
    config = load_config(root)
    files = enumerate_files(root, compile_globs(config.index.exclude), load_registry(), config.index.max_file_bytes)
    rows = [{"path": f.path, "lang": f.lang, "size": f.size, "hash": f.hash} for f in files]
    snapshot(f"{fixture}/files.json", json.dumps(rows, indent=1) + "\n")
    snapshot(f"{fixture}/stack.json", json.dumps(build_profile(root), indent=1) + "\n")
