"""M6 benchmark harness (Evaluation Plan): the protocol end to end with a
fake ``claude`` (tests/fake_claude.py), so no run spends Claude usage."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from compass import report
from conftest import run_compass

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("bench_run", ROOT / "bench" / "run.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_run"] = module  # dataclasses look their module up by name
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("bench_run", None)


@pytest.fixture
def claude(tmp_path, monkeypatch):
    """A ``claude`` executable that runs tests/fake_claude.py, with its own config dir."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = ROOT / "tests" / "fake_claude.py"
    if os.name == "nt":
        shim = bin_dir / "claude.cmd"
        shim.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        shim = bin_dir / "claude"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    return str(shim)


def run_batch(harness, claude, tmp_path, *extra: str) -> Path:
    results = tmp_path / "results"
    code = harness.main(["--claude", claude, "--results", str(results), "--repeats", "1", "--model", "fake-model",
                         "--batch", "b1", *extra])
    assert code == 0
    return results / "b1"


def rows(folder: Path) -> dict[str, dict]:
    return {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("*/row.json")}


def test_each_task_runs_with_compass_on_and_off(harness, claude, tmp_path):
    batch = run_batch(harness, claude, tmp_path)
    runs = rows(batch)
    assert sorted(runs) == ["x01-off-1", "x01-on-1", "x02-off-1", "x02-on-1"]
    assert all(r["bench"]["pass"] for r in runs.values()), {k: (batch / k / "acceptance.txt").read_text() for k in runs}
    on, off = runs["x02-on-1"], runs["x02-off-1"]
    assert (on["compass"], off["compass"]) == (True, False)
    assert on["modules"] == ["query", "prompt_gate", "context_pack", "spec_gate", "review", "delegation"]
    assert off["modules"] == [] and off["bench"]["index_s"] is None and on["bench"]["index_s"] > 0
    assert on["tools"] == {"Edit": 1, "compass:find_symbol": 1} and off["tools"]["Read"] == 2
    assert on["main"]["claude-opus-5-5"]["output"] == 250 and on["bench"]["model"] == "fake-model"
    assert (on["bench"]["claude_code"], on["bench"]["cost_usd"], on["bench"]["turns"]) == ("2.1.281", 0.02, 2)
    # What the run left behind, for reading later.
    folder = batch / "x02-off-1"
    assert "+        self.quantity += amount" in (folder / "diff.patch").read_text(encoding="utf-8")
    assert "tests/hidden" not in (folder / "diff.patch").read_text(encoding="utf-8")  # copied in after the diff
    assert "2 passed" in (folder / "acceptance.txt").read_text(encoding="utf-8")
    assert (folder / "transcript.jsonl").is_file() and (folder / "stream.jsonl").is_file()
    assert "is_alarm" in (batch / "x01-on-1" / "reply.txt").read_text(encoding="utf-8")

    result = report.bench(report.tasks_from_rows(report.load([batch])))
    assert result["pass"] == {"off": (2, 2), "on": (2, 2)} and result["tokens"]["median"] < 0
    proc = run_compass("report", str(batch))
    assert proc.returncode == 0 and "2 tasks × 2 conditions × 1 runs" in proc.stdout, proc.stderr

    # A second start skips what is done.
    before = {k: r["at"] for k, r in rows(batch).items()}
    run_batch(harness, claude, tmp_path)
    assert {k: r["at"] for k, r in rows(batch).items()} == before


def test_a_failed_check_fails_the_run(harness, claude, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_LAZY", "1")
    runs = rows(run_batch(harness, claude, tmp_path, "--only", "x02", "--conditions", "off"))
    (run,) = runs.values()
    assert run["bench"]["pass"] is False


def test_a_large_task_is_approved_and_resumed(harness, claude, tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "r01.yaml").write_text(
        "id: r01\nrepo: python_app\ncategory: refactor\n"
        "prompt: |\n  Refactor src/inventory/models.py: move Reading and Unit into their own module.\n"
        "  Scope: src/inventory/. Accept when: every import still works.\n"
        "acceptance:\n  reply_contains: [Done]\n",
        encoding="utf-8",
    )
    runs = rows(run_batch(harness, claude, tmp_path, "--tasks", str(tasks)))
    on, off = runs["r01-on-1"], runs["r01-off-1"]
    assert (on["bench"]["approvals"], off["bench"]["approvals"]) == (1, 0)
    assert on["prompts"] == 2 and on["bench"]["pass"] is True  # the resumed turn said Done
    assert off["bench"]["pass"] is False  # without Compass the fake only drafted a plan


def test_ablations_switch_one_module_group_off(harness, claude, tmp_path):
    runs = rows(run_batch(harness, claude, tmp_path, "--only", "x01", "--conditions", "on-no-review,on-no-map"))
    assert "review" not in runs["x01-on-no-review-1"]["modules"]
    assert not {"query", "context_pack"} & set(runs["x01-on-no-map-1"]["modules"])


def test_the_example_tasks_are_well_formed(harness):
    tasks = harness.load_tasks(ROOT / "bench" / "tasks" / "examples", None)
    repos = harness.load_repos()
    assert [t.id for t in tasks] == ["x01", "x02"]
    for task in tasks:
        assert task.repo in repos and task.acceptance and task.category in (
            "explain", "bug_fix", "feature", "refactor", "tests", "triage")
        for rel in task.hidden:
            assert (ROOT / "bench" / "hidden" / task.id / rel).is_file()


def test_unknown_conditions_are_refused(harness, claude, tmp_path):
    with pytest.raises(SystemExit):
        harness.main(["--claude", claude, "--conditions", "sideways", "--dry-run"])
