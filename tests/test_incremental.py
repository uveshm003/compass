"""Determinism (NF-13) and incremental updates (IX-07, IX-08, Step 3 done-when)."""

from __future__ import annotations

import json
import time

import pytest

from compass.index.indexer import Indexer
from compass.index.store import Store
from compass.repo import Repo
from conftest import bump_mtime, git, needs_permissions, read_tree, write


def state(repo: Repo) -> tuple[dict, dict[str, str]]:
    with Store.open(repo.db_path) as store:
        return store.dump(), read_tree(repo.map_dir)


def fresh_state(root) -> tuple[dict, dict[str, str]]:
    """What a from-scratch build of the current working tree looks like."""
    repo = Repo(root)
    for suffix in ("", "-wal", "-shm"):
        repo.db_path.with_name(repo.db_path.name + suffix).unlink(missing_ok=True)
    Indexer(repo).build(full=True)
    return state(repo)


def test_fresh_builds_are_byte_identical(make_repo):
    repo = Repo(make_repo("ts_app"))
    Indexer(repo).build(full=True)
    first_db = repo.db_path.read_bytes()
    first_map = read_tree(repo.map_dir)
    repo.db_path.unlink()
    Indexer(repo).build(full=True)
    assert repo.db_path.read_bytes() == first_db
    assert read_tree(repo.map_dir) == first_map


def without_sqlite_counters(data: bytes) -> bytes:
    """Mask the header fields SQLite bumps on every write (file change counter,
    schema cookie, version-valid-for); everything else is index content."""
    out = bytearray(data)
    for offset in (24, 40, 92):
        out[offset : offset + 4] = b"\0\0\0\0"
    return bytes(out)


def test_full_rebuild_over_an_existing_index_matches_a_fresh_one(make_repo):
    repo = Repo(make_repo("python_app"))
    indexer = Indexer(repo)
    indexer.build(full=True)
    fresh = repo.db_path.read_bytes()
    write(repo.root, "src/inventory/extra.py", "def extra():\n    pass\n")
    indexer.build()
    (repo.root / "src/inventory/extra.py").unlink()
    indexer.build(full=True)
    rebuilt = repo.db_path.read_bytes()
    assert len(rebuilt) == len(fresh)
    assert without_sqlite_counters(rebuilt) == without_sqlite_counters(fresh)


def test_editing_a_file_updates_its_shard(make_repo):
    repo = Repo(make_repo("ts_app"))
    indexer = Indexer(repo)
    indexer.build()
    shard = repo.map_dir / "src/transport.md"
    before = shard.read_text(encoding="utf-8")
    other = (repo.map_dir / "src/legacy.md").stat().st_mtime_ns

    path = repo.root / "src/transport/socket.ts"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n/** Closes the feed. */\nexport function closeAll(): void {}\n",
        encoding="utf-8",
    )
    started = time.perf_counter()
    result = indexer.update(["src/transport/socket.ts"])
    elapsed = time.perf_counter() - started

    after = shard.read_text(encoding="utf-8")
    assert "fn closeAll(): void — Closes the feed" in after and after != before
    assert result.parsed == 1 and result.changed_dirs == ["src/transport"]
    assert (repo.map_dir / "src/legacy.md").stat().st_mtime_ns == other  # untouched shards stay put
    assert elapsed < 0.5  # NF-04, in-process; the subprocess figure is checked with --perf
    assert state(repo) == fresh_state(repo.root)


def test_unchanged_content_is_not_reparsed(make_repo):
    repo = Repo(make_repo("go_app"))
    indexer = Indexer(repo)
    indexer.build()
    bump_mtime(repo.root / "internal/transport/retry.go")
    result = indexer.update(["internal/transport/retry.go"])
    assert result.parsed == 0
    assert indexer.build().parsed == 0


def test_refresh_handles_added_deleted_and_excluded_files(make_repo):
    repo = Repo(make_repo("python_app"))
    indexer = Indexer(repo)
    indexer.build()
    write(repo.root, "src/newpkg/__init__.py", '"""A new package."""\n\ndef hello():\n    pass\n')
    (repo.root / "src/inventory/api.py").unlink()
    (repo.root / "tests/test_models.py").unlink()  # empties tests/
    write(repo.root, "src/generated/out.py", "def gen():\n    pass\n")  # excluded by config
    write(repo.root, ".gitignore", "ignored/\n")
    write(repo.root, "ignored/skip.py", "def nope():\n    pass\n")

    result = indexer.build()
    assert result.mode == "incremental"
    dump, shards = state(repo)
    paths = {f["path"] for f in dump["files"]}
    assert "src/newpkg/__init__.py" in paths
    assert "src/inventory/api.py" not in paths
    assert not any(p.startswith(("src/generated/", "ignored/", "tests/")) for p in paths)
    assert "tests.md" not in shards
    assert "src/newpkg.md" in shards
    assert "src/newpkg/  (1 file, 1 symbol) — A new package" in shards["_index.md"]
    assert (dump, shards) == fresh_state(repo.root)


def test_skipped_files_are_remembered_not_reread(make_repo):
    repo = Repo(make_repo("python_app"))
    logo = repo.root / "logo.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\n\x00" * 200)
    indexer = Indexer(repo)
    indexer.build()
    assert indexer.stale_paths() == []  # nothing left to re-check on the next session start
    with Store.open(repo.db_path) as store:
        assert store.dump()["skipped"] == ["logo.png"]
    assert indexer.build().parsed == 0

    logo.write_text("now it is text\n", encoding="utf-8")
    bump_mtime(logo)
    assert indexer.stale_paths() == ["logo.png"]
    indexer.build()
    dump, _ = state(repo)
    assert "logo.png" in {f["path"] for f in dump["files"]} and dump["skipped"] == []

    logo.unlink()
    indexer.build()
    dump, _ = state(repo)
    assert "logo.png" not in {f["path"] for f in dump["files"]} and dump["skipped"] == []


def test_update_of_a_deleted_directory_drops_its_files(make_repo):
    repo = Repo(make_repo("go_app"))
    indexer = Indexer(repo)
    indexer.build()
    for path in (repo.root / "pkg/api").iterdir():
        path.unlink()
    (repo.root / "pkg/api").rmdir()
    indexer.update(["pkg/api"])
    dump, shards = state(repo)
    assert not any(f["path"].startswith("pkg/") for f in dump["files"])
    assert "pkg/api.md" not in shards and not (repo.map_dir / "pkg").exists()


def test_switching_branches_leaves_no_stale_symbols(make_repo):
    root = make_repo("go_app")
    repo = Repo(root)
    (root / ".git/info/exclude").write_text(".compass/\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    Indexer(repo).build()

    git(root, "checkout", "-qb", "feature")
    retry = root / "internal/transport/retry.go"
    retry.write_text(retry.read_text().replace("func Retry(", "func RetryWith("), encoding="utf-8")
    (root / "pkg/api/types.go").unlink()
    write(root, "internal/metrics/metrics.go", "package metrics\n\n// Count counts.\nfunc Count() int { return 0 }\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "feature")

    for branch in ("main", "feature", "main"):
        git(root, "checkout", "-q", branch)
        Indexer(repo).build()
        dump, shards = state(repo)
        names = {s["name"] for s in dump["symbols"]}
        if branch == "main":
            assert "Retry" in names and "RetryWith" not in names and "Count" not in names
            assert "pkg/api.md" in shards
        else:
            assert "RetryWith" in names and "Retry" not in names and "Count" in names
            assert "pkg/api.md" not in shards
        assert (dump, shards) == fresh_state(root), f"stale index after checkout of {branch}"


@needs_permissions
def test_a_failed_shard_write_rolls_the_index_back(make_repo):
    repo = Repo(make_repo("python_app"))
    indexer = Indexer(repo)
    indexer.build()
    write(repo.root, "src/inventory/api.py", "def replaced():\n    pass\n")
    shards = repo.map_dir / "src"
    shards.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            indexer.build()
    finally:
        shards.chmod(0o755)
    # Nothing was committed, so the change is still pending rather than lost.
    assert indexer.stale_paths() == ["src/inventory/api.py"]
    indexer.build()
    assert "fn replaced()" in (repo.map_dir / "src/inventory.md").read_text(encoding="utf-8")
    assert state(repo) == fresh_state(repo.root)


def test_repair_rewrites_hand_edited_shards(make_repo):
    repo = Repo(make_repo("rust_app"))
    indexer = Indexer(repo)
    indexer.build()
    expected = read_tree(repo.map_dir)
    (repo.map_dir / "src.md").write_text("garbage\n", encoding="utf-8")
    (repo.map_dir / "stray.md").write_text("left over\n", encoding="utf-8")
    assert indexer.build().parsed == 0
    assert read_tree(repo.map_dir) != expected  # a plain refresh trusts the shards
    indexer.build(repair=True)
    assert read_tree(repo.map_dir) == expected


def test_shard_names_never_collide(make_repo):
    functions = "".join(f"def function_{i}(argument_one, argument_two):\n    pass\n\n" for i in range(40))
    repo = Repo(
        make_repo(
            files={
                ".compass/config.yaml": "index:\n  shard_token_limit: 300\n",
                "_index/a.py": "def in_index_dir():\n    pass\n",
                "_root/b.py": "def in_root_dir():\n    pass\n",
                "lib/x/big.py": functions,
                "lib/x~2/c.py": "def in_tilde_dir():\n    pass\n",
                "top.py": "def at_top():\n    pass\n",
            }
        )
    )
    Indexer(repo).build()
    shards = read_tree(repo.map_dir)
    assert shards["_index.md"].startswith("# Code map")
    assert shards["_root.md"].startswith("# ./")
    assert "in_index_dir" in shards["__index.md"] and "in_root_dir" in shards["__root.md"]
    assert "in_tilde_dir" in shards["lib/x~~2.md"]
    x_parts = [name for name in shards if name.startswith("lib/x") and "big.py" in shards[name]]
    assert len(x_parts) > 1 and "lib/x~2.md" in x_parts
    assert all(f"function_{i}(" in "".join(shards[n] for n in x_parts) for i in range(40))


def test_query_or_settings_change_triggers_a_full_rebuild(make_repo):
    repo = Repo(make_repo("rust_app"))
    Indexer(repo).build()
    write(repo.root, ".compass/config.yaml", "index:\n  shard_token_limit: 300\n")
    result = Indexer(repo).build()
    assert result.mode == "full"
    shards = read_tree(repo.map_dir)
    assert "src~2.md" in shards  # the smaller limit split the src/ shard


def test_corrupt_index_is_rebuilt(make_repo):
    repo = Repo(make_repo("python_app"))
    Indexer(repo).build()
    repo.db_path.write_bytes(b"this is not a database" * 100)
    for suffix in ("-wal", "-shm"):
        repo.db_path.with_name(repo.db_path.name + suffix).unlink(missing_ok=True)
    result = Indexer(repo).build()
    assert result.mode == "full" and result.symbols > 0
    assert "rebuilding index" in (repo.logs_dir / "errors.log").read_text(encoding="utf-8")


def test_index_result_json_shape(make_repo):
    repo = Repo(make_repo("python_app"))
    data = Indexer(repo).build().as_dict()
    assert set(data) == {"mode", "files", "parsed", "removed", "symbols", "seconds"}
    json.dumps(data)
