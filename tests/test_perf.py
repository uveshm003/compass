"""Latency and footprint targets on a generated 100k LOC repo (run with --perf).

NF-03  full index of 100k LOC              <= 60 s
NF-04  incremental update of one file      <= 500 ms (p95, as the hook runs it:
                                              a fresh `compass` process), also
                                              when the file is new or deleted
                                              and every import is re-resolved
NF-05  largest map shard                   <= 2,000 tokens
NF-15  index plus shards                   <= 50 MB
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time

import pytest

from compass.index.indexer import Indexer
from compass.index.shards import estimate_tokens
from compass.repo import Repo
from conftest import git, run_compass
from gen_repo import generate, generate_packages

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


def test_query_tool_latency(big_repo):
    # In-process, as the long-running MCP server answers; then as a one-off CLI twin.
    from compass.query import Queries

    repo, *_ = big_repo
    queries = Queries(repo)
    calls = {
        "find_symbol": lambda: queries.find_symbol("method_3"),  # a name in every file: the worst case
        "read_symbol": lambda: queries.read_symbol("Service40.method_1"),
        "file_outline": lambda: queries.file_outline(sorted((repo.root / "go").rglob("*.go"))[3].relative_to(repo.root).as_posix()),
        "callers_of": lambda: queries.callers_of("helper_2"),  # hundreds of call sites
        "map": lambda: queries.map("python/area3/mod1"),
        "tests_for": lambda: queries.tests_for("Service7.method_2"),
    }
    calls["find_symbol"]()  # the first call also runs the freshness check
    report = []
    for name, run in calls.items():
        samples = []
        for _ in range(10):
            started = time.perf_counter()
            run()
            samples.append(time.perf_counter() - started)
        report.append(f"{name} {statistics.median(samples) * 1000:.0f} ms")
        assert statistics.median(samples) <= 0.2, name
    cli = []
    for _ in range(5):
        started = time.perf_counter()
        proc = run_compass("-C", str(repo.root), "find-symbol", "method_3")
        cli.append(time.perf_counter() - started)
        assert proc.returncode == 0
    print(f"\nin-process medians: {', '.join(report)}; CLI find-symbol median {statistics.median(cli) * 1000:.0f} ms")
    assert statistics.median(cli) <= 1.0


def test_session_start_staleness_check(big_repo):
    repo, *_ = big_repo
    samples = []
    for _ in range(5):
        started = time.perf_counter()
        proc = run_compass("hook", "session-start", input=json.dumps({"cwd": str(repo.root)}))
        samples.append(time.perf_counter() - started)
        assert (proc.returncode, proc.stderr) == (0, "")
        assert proc.stdout.startswith("[compass] Compass is active") and "being built" not in proc.stdout
    print(f"\nsession-start with nothing stale: median {statistics.median(samples) * 1000:.0f} ms")
    assert statistics.median(samples) <= 1.0


@pytest.fixture(scope="module")
def import_heavy_repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("imports") / "repo"
    loc = generate_packages(root)
    git(root, "init", "-q")
    repo = Repo(root.resolve())
    Indexer(repo).build(full=True)
    return repo, loc


def test_adding_and_removing_a_file_p95_under_500ms(import_heavy_repo):
    # A new or deleted file can change what any import resolves to, so every
    # import is re-resolved inline; that must stay inside the hook budget.
    from compass.index.store import Store

    repo, loc = import_heavy_repo
    with Store.open(repo.db_path) as store:
        imports = len(store.import_rows())
    samples = []
    for n in range(RUNS // 2):
        rel = f"src/app/pkg{n}/new_module.py"
        for create in (True, False):
            path = repo.root / rel
            if create:
                path.write_text("from app.pkg1.mod1 import thing0\n\ndef added() -> None:\n    pass\n", encoding="utf-8")
            else:
                path.unlink()
            payload = json.dumps({"cwd": str(repo.root), "tool_name": "Write", "tool_input": {"file_path": str(path)}})
            started = time.perf_counter()
            proc = run_compass("hook", "post-edit", input=payload)
            samples.append(time.perf_counter() - started)
            assert (proc.returncode, proc.stderr) == (0, "")
            with Store.open(repo.db_path) as store:
                assert (store.file_info(rel) is not None) == create
    print(f"\nadd/remove with {imports} imports ({loc} LOC): median {statistics.median(samples) * 1000:.0f} ms,"
          f" p95 {p95(samples) * 1000:.0f} ms")
    assert p95(samples) <= 0.5


def test_prompt_hook_p95_under_100ms(big_repo):
    # NF-01 is the prompt gate's budget; M3's turn bookkeeping must leave it room.
    # A bare interpreter start is measured too: Windows runners create
    # processes several times slower, which no Compass change can fix, so
    # there the check is on Compass's own share.
    repo, *_ = big_repo
    payload = json.dumps({"session_id": "perf", "cwd": str(repo.root), "prompt": "where is retry handled?"})
    run_compass("hook", "prompt", input=payload)  # the first prompt of a session starts its task
    samples, bare = [], []
    for _ in range(RUNS):
        started = time.perf_counter()
        proc = run_compass("hook", "prompt", input=payload)
        samples.append(time.perf_counter() - started)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
        started = time.perf_counter()
        subprocess.run([sys.executable, "-c", "pass"], check=True)
        bare.append(time.perf_counter() - started)
    own = p95(samples) - p95(bare)
    print(f"\nprompt hook: median {statistics.median(samples) * 1000:.0f} ms, p95 {p95(samples) * 1000:.0f} ms"
          f" (bare interpreter p95 {p95(bare) * 1000:.0f} ms)")
    assert own <= 0.06
    if os.name != "nt":
        assert p95(samples) <= 0.1


def test_stop_hook_with_a_changed_file_p95_under_500ms(big_repo):
    # The Stop hook scans for anchors and rewrites the manifest at the end of every turn that edits files.
    repo, *_ = big_repo
    target = sorted((repo.root / "rust").rglob("*.rs"))[5]
    original = target.read_text(encoding="utf-8")
    task = json.loads(run_compass("-C", str(repo.root), "task", "--json").stdout)["task"]
    tag = "@ai" + f":change {task}"
    samples = []
    try:
        for n in range(RUNS // 2):
            target.write_text(original + f"// {tag} — edit {n}\n", encoding="utf-8")
            edit = json.dumps({"session_id": "perf", "cwd": str(repo.root), "tool_name": "Edit",
                               "tool_input": {"file_path": str(target)}})
            assert run_compass("hook", "post-edit", input=edit).returncode == 0
            payload = json.dumps({"session_id": "perf", "cwd": str(repo.root), "stop_hook_active": False})
            started = time.perf_counter()
            proc = run_compass("hook", "stop", input=payload)
            samples.append(time.perf_counter() - started)
            assert proc.returncode == 0 and "systemMessage" in proc.stdout, proc.stdout + proc.stderr
    finally:
        target.write_text(original, encoding="utf-8")
    print(f"\nstop hook: median {statistics.median(samples) * 1000:.0f} ms, p95 {p95(samples) * 1000:.0f} ms")
    assert p95(samples) <= 0.5


def _fresh_task(repo) -> None:
    """Make the active task wait for its first request again, so the next
    prompt is gated (only a prompt that starts a task is checked)."""
    from compass import state

    with state.transaction(repo) as st:
        task = state.ensure_task(st)
        record = state.task_record(st, task)
        record["brief"], record["size"], record["touched"] = None, None, []


def _timed_prompts(repo, text: str) -> list[float]:
    payload = json.dumps({"session_id": "perf-gate", "cwd": str(repo.root), "prompt": text})
    samples = []
    for _ in range(RUNS):
        _fresh_task(repo)
        started = time.perf_counter()
        proc = run_compass("hook", "prompt", input=payload)
        samples.append(time.perf_counter() - started)
        assert proc.returncode == 0, proc.stderr
    return samples


def _bare_p95() -> float:
    samples = []
    for _ in range(RUNS):
        started = time.perf_counter()
        subprocess.run([sys.executable, "-c", "pass"], check=True)
        samples.append(time.perf_counter() - started)
    return p95(samples)


def test_prompt_gate_p95_under_100ms(big_repo):
    # NF-01: the rules on a request that starts a task, with nothing to look up.
    # As for the plain prompt hook, Windows is judged on Compass's own share.
    repo, *_ = big_repo
    samples = _timed_prompts(repo, "improve the retry handling so it gives up sooner")
    bare = _bare_p95()
    print(f"\nprompt gate: median {statistics.median(samples) * 1000:.0f} ms, p95 {p95(samples) * 1000:.0f} ms"
          f" (bare interpreter p95 {bare * 1000:.0f} ms)")
    assert p95(samples) - bare <= 0.07
    if os.name != "nt":
        assert p95(samples) <= 0.1


def test_context_pack_p95_under_300ms(big_repo):
    # NF-02: the gate plus a pack for five names: symbols, a qualified method, a path, a typo.
    repo, *_ = big_repo
    module = sorted((repo.root / "python").rglob("*.py"))[40].relative_to(repo.root).as_posix()
    text = f"Make Service40.method_1 and helper_2 faster in {module}; keep LIMIT_3 and check `Servce40` too"
    proc = run_compass("check-prompt", text, cwd=repo.root)
    assert "Service40.method_1" in proc.stdout and "did you mean Service40?" in proc.stdout, proc.stdout
    samples = _timed_prompts(repo, text)
    print(f"\ncontext pack: median {statistics.median(samples) * 1000:.0f} ms, p95 {p95(samples) * 1000:.0f} ms")
    assert p95(samples) <= 0.3


def test_pre_edit_hook_p95_under_100ms(big_repo):
    # The spec gate runs before every Write and Edit; with no spec pending it decides from state.json alone.
    repo, *_ = big_repo
    target = sorted((repo.root / "go").rglob("*.go"))[3]
    payload = json.dumps({"session_id": "perf", "cwd": str(repo.root), "tool_name": "Edit",
                          "tool_input": {"file_path": str(target)}})
    samples = []
    for _ in range(RUNS):
        started = time.perf_counter()
        proc = run_compass("hook", "pre-edit", input=payload)
        samples.append(time.perf_counter() - started)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    print(f"\npre-edit hook: median {statistics.median(samples) * 1000:.0f} ms, p95 {p95(samples) * 1000:.0f} ms")
    assert p95(samples) <= 0.1 if os.name != "nt" else p95(samples) <= 0.2
