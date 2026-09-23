"""Latency and footprint targets on a generated 100k LOC repo (run with --perf).

NF-03  full index of 100k LOC              <= 60 s
NF-04  incremental update of one file      <= 500 ms (p95, as the hook runs it:
                                              a fresh `compass` process)
NF-05  largest map shard                   <= 2,000 tokens
NF-15  index plus shards                   <= 50 MB
"""

from __future__ import annotations

import json
import statistics
import time

import pytest

from compass.index.indexer import Indexer
from compass.index.shards import estimate_tokens
from compass.repo import Repo
from conftest import git, run_compass
from gen_repo import generate

pytestmark = pytest.mark.perf
RUNS = 20


def p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[-1]


@pytest.fixture(scope="module")
def big_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("big") / "repo"
    loc = generate(root, 100_000)
    git(root, "init", "-q")
    repo = Repo(root.resolve())
    started = time.perf_counter()
    result = Indexer(repo).build(full=True)
    elapsed = time.perf_counter() - started
    return repo, loc, result, elapsed


def test_full_index_within_60_seconds(big_repo):
    repo, loc, result, elapsed = big_repo
    print(f"\nfull index: {loc} LOC, {result.files} files, {result.symbols} symbols in {elapsed:.1f} s")
    assert loc >= 100_000
    assert elapsed <= 60.0


def test_footprint_and_shard_size(big_repo):
    repo, *_ = big_repo
    size = repo.db_path.stat().st_size + sum(p.stat().st_size for p in repo.map_dir.rglob("*.md"))
    largest = max(estimate_tokens(p.read_text(encoding="utf-8")) for p in repo.map_dir.rglob("*.md"))
    print(f"\nindex + shards: {size / 1e6:.1f} MB; largest shard ~{largest} tokens")
    assert size <= 50e6
    assert largest <= 2000


def test_single_file_update_p95_under_500ms(big_repo):
    repo, *_ = big_repo
    target = sorted((repo.root / "python").rglob("*.py"))[7]
    rel = target.relative_to(repo.root).as_posix()
    shard = repo.map_dir / (target.parent.relative_to(repo.root).as_posix() + ".md")
    original = target.read_text(encoding="utf-8")
    samples = []
    try:
        for n in range(RUNS):
            target.write_text(original + f"\n\ndef added_{n}() -> None:\n    pass\n", encoding="utf-8")
            started = time.perf_counter()
            proc = run_compass("-C", str(repo.root), "update", rel)
            samples.append(time.perf_counter() - started)
            assert proc.returncode == 0, proc.stderr
        assert f"fn added_{RUNS - 1}() -> None" in shard.read_text(encoding="utf-8")
    finally:
        target.write_text(original, encoding="utf-8")
    print(f"\n`compass update <file>`: median {statistics.median(samples) * 1000:.0f} ms, p95 {p95(samples) * 1000:.0f} ms")
    assert p95(samples) <= 0.5


def test_post_edit_hook_p95_under_500ms(big_repo):
    repo, *_ = big_repo
    target = sorted((repo.root / "typescript").rglob("*.ts"))[11]
    original = target.read_text(encoding="utf-8")
    samples = []
    try:
        for n in range(RUNS):
            target.write_text(original + f"\nexport function added{n}(): void {{}}\n", encoding="utf-8")
            payload = json.dumps({"cwd": str(repo.root), "tool_name": "Edit", "tool_input": {"file_path": str(target)}})
            started = time.perf_counter()
            proc = run_compass("hook", "post-edit", input=payload)
            samples.append(time.perf_counter() - started)
            assert (proc.returncode, proc.stderr) == (0, "")
    finally:
        target.write_text(original, encoding="utf-8")
    print(f"\npost-edit hook: median {statistics.median(samples) * 1000:.0f} ms, p95 {p95(samples) * 1000:.0f} ms")
    assert p95(samples) <= 0.5


def test_manual_index_with_nothing_changed(big_repo):
    # `compass index` re-renders every shard as a repair pass; it should stay quick.
    repo, *_ = big_repo
    started = time.perf_counter()
    proc = run_compass("-C", str(repo.root), "index")
    elapsed = time.perf_counter() - started
    assert proc.returncode == 0, proc.stderr
    print(f"\n`compass index` with nothing changed: {elapsed * 1000:.0f} ms")
    assert elapsed <= 5.0


def test_session_start_staleness_check(big_repo):
    repo, *_ = big_repo
    samples = []
    for _ in range(5):
        started = time.perf_counter()
        proc = run_compass("hook", "session-start", input=json.dumps({"cwd": str(repo.root)}))
        samples.append(time.perf_counter() - started)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    print(f"\nsession-start with nothing stale: median {statistics.median(samples) * 1000:.0f} ms")
    assert statistics.median(samples) <= 1.0
