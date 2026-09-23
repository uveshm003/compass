"""universal-ctags fallback (IX-02). Uses a real Universal Ctags when one is
available (COMPASS_TEST_CTAGS or PATH), and a stand-in script otherwise."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap

import pytest

from compass.index import ctags
from compass.index.indexer import Indexer
from compass.index.store import Store
from compass.repo import Repo

RUBY = textwrap.dedent(
    """\
    # Handles billing.
    module Billing
      # An invoice.
      class Invoice
        def total(items)
          items.sum
        end
      end
    end
    """
)


def real_ctags():
    for candidate in (os.environ.get("COMPASS_TEST_CTAGS"), shutil.which("ctags"), shutil.which("universal-ctags")):
        if candidate:
            try:
                out = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=5).stdout
            except OSError:
                continue
            if "Universal Ctags" in out:
                return candidate
    return None


FAKE = textwrap.dedent(
    """\
    #!{python}
    import json, sys
    if "--version" in sys.argv:
        print("Universal Ctags 6.1.0, Copyright (C) 2015-2023 Universal Ctags Team")
    elif "--list-features" in sys.argv:
        print("json                supports json format output")
    else:
        for path in sys.stdin.read().split():
            if path.endswith(".rb"):
                for tag in [
                    {{"name": "Billing", "line": 2, "end": 9, "kind": "module"}},
                    {{"name": "Invoice", "line": 4, "end": 8, "kind": "class", "scope": "Billing", "scopeKind": "module"}},
                    {{"name": "total", "line": 5, "end": 7, "kind": "method", "signature": "(items)",
                      "scope": "Billing.Invoice", "scopeKind": "class"}},
                ]:
                    print(json.dumps({{"_type": "tag", "path": path, "language": "Ruby", **tag}}))
            elif path.endswith(".md"):
                print(json.dumps({{"_type": "tag", "name": "Title", "path": path, "language": "Markdown",
                                   "line": 1, "kind": "chapter"}}))
    """
)


@pytest.fixture(params=["real", "fake"])
def ctags_exe(request, tmp_path, monkeypatch):
    if request.param == "real":
        exe = real_ctags()
        if exe is None:
            pytest.skip("Universal Ctags not installed")
    else:
        if os.name == "nt":
            pytest.skip("the stand-in ctags is a POSIX script")
        exe = tmp_path / "fake-ctags"
        exe.write_text(FAKE.format(python=sys.executable))
        exe.chmod(0o755)
    monkeypatch.setenv("COMPASS_CTAGS", str(exe))
    ctags.find_ctags.cache_clear()
    return str(exe)


def test_ctags_covers_languages_without_a_query(ctags_exe, make_repo):
    root = make_repo(files={"app/billing.rb": RUBY, "README.md": "# Title\n\nBilling tools.\n"})
    repo = Repo(root)
    Indexer(repo).build()
    with Store.open(repo.db_path) as store:
        dump = store.dump()
    rows = {(s["name"], s["kind"], s["parent"]) for s in dump["symbols"]}
    assert ("Invoice", "class", "Billing") in rows
    assert ("total", "method", "Billing.Invoice") in rows
    assert not any(s["path"] == "README.md" for s in dump["symbols"])  # documents are not code
    langs = {f["path"]: f["lang"] for f in dump["files"]}
    assert langs["app/billing.rb"] == "ruby"
    shard = (repo.map_dir / "app.md").read_text(encoding="utf-8")
    assert "- L4    class Invoice — An invoice" in shard
    assert "- L5      method total(items)" in shard


def test_ctags_availability_never_forces_a_rebuild(ctags_exe, make_repo, monkeypatch):
    # A terminal and an IDE often have different PATHs; switching between them
    # must not flip the index fingerprint.
    repo = Repo(make_repo(files={"app/billing.rb": RUBY, "tool.py": "def f():\n    pass\n"}))
    assert Indexer(repo).build().mode == "full"
    monkeypatch.setenv("COMPASS_CTAGS", "off")
    ctags.find_ctags.cache_clear()
    result = Indexer(repo).build()
    assert (result.mode, result.parsed) == ("incremental", 0)


def test_without_ctags_other_languages_are_listed_without_symbols(make_repo):
    root = make_repo(files={"app/billing.rb": RUBY})
    repo = Repo(root)
    Indexer(repo).build()
    shard = (repo.map_dir / "app.md").read_text(encoding="utf-8")
    assert shard == "# app/  (1 file, 0 symbols)\n## billing.rb\n"


def test_non_universal_ctags_is_ignored(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX script")
    exe = tmp_path / "bsd-ctags"
    exe.write_text("#!/bin/sh\necho 'usage: ctags [-BFTaduwvx] [-f tagsfile] file ...'\n")
    exe.chmod(0o755)
    monkeypatch.setenv("COMPASS_CTAGS", str(exe))
    ctags.find_ctags.cache_clear()
    assert ctags.find_ctags() is None
