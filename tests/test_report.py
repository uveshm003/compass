"""M6 ``compass report`` (TM-03): telemetry rolled up into tasks and compared
with Compass on and off, and the benchmark report the Evaluation Plan asks for."""

from __future__ import annotations

import json

import pytest

from compass import report
from conftest import run_compass, write

HAIKU = "claude-haiku-4-5-20251001"
OPUS = "claude-opus-5-5"


def usage(total: int, cache_read: int = 0) -> dict:
    return {"input": 0, "output": total - cache_read, "cache_creation": 0, "cache_read": cache_read}


def turn(task, tokens, on=True, active=60.0, prompts=1, category=None, source="t.jsonl", at="2026-09-10T10:00:00Z",
         tools=None, session="s1", delegated=None):
    return {"v": 1, "kind": "turn", "at": at, "session": session, "task": task, "category": category, "size": None,
            "compass": on, "modules": ["query"] if on else [], "main": {OPUS: usage(tokens, tokens // 2)},
            "delegated": delegated or {}, "tools": tools or {}, "prompts": prompts, "active_s": active,
            "injected_chars": 400 if on else 0, "claude_code": "2.1.281", "source": source}


def run_row(task, condition, repeat, tokens, passed=True, active=100.0, category="bug_fix", cost=None):
    bench = {"run": f"{task}-{condition}-{repeat}", "task": task, "category": category, "condition": condition,
             "repeat": repeat, "pass": passed, "model": OPUS, "compass_version": "0.1.0"}
    if cost is not None:
        bench["cost_usd"] = cost
    return {**turn(None, tokens, condition != "off", active), "bench": bench, "source": f"results/{bench['run']}"}


# -- telemetry -------------------------------------------------------------------------------------


def test_turns_roll_up_into_tasks():
    rows = [
        turn("T1", 1000, tools={"Read": 2, "compass:find_symbol": 3}),
        turn("T1", 500, prompts=1, active=30, tools={"Grep": 1}),
        {**turn("T1", 0), "kind": "subagent", "main": {}, "delegated": {HAIKU: usage(800)}, "prompts": 0},
        turn(None, 50, session="s2"),  # a question outside any task
        turn("T1", 70, source="other.jsonl"),  # another developer's T1
    ]
    tasks = report.tasks_from_rows(rows)
    t1 = next(t for t in tasks if t.task == "T1" and t.source == "t.jsonl")
    assert (t1.tokens, t1.corrections, t1.reads, t1.compass_calls, t1.active_s) == (1500, 1, 3, 3, 90.0)  # not the subagent's
    assert dict(t1.delegated) == {"haiku": 800} and t1.main["cache_read"] == 750 and t1.on is True
    assert len(tasks) == 3


def test_a_task_that_changed_modes_is_mixed_and_left_out():
    tasks = report.tasks_from_rows([turn("T1", 100, on=True), turn("T1", 100, on=False)])
    assert tasks[0].on is None and report.pilot(tasks)["mixed"] == 1


def test_the_pilot_comparison():
    rows = [turn(f"T{i}", tokens, on=False, category="bug_fix") for i, tokens in enumerate((1000, 1200, 1400))]
    rows += [turn(f"T{i}", tokens, on=True, category="bug_fix" if i < 13 else None, at="2026-09-20T10:00:00Z")
             for i, tokens in enumerate((600, 700, 900, 5000), start=10)]
    summary = report.pilot(report.tasks_from_rows(rows))
    assert (summary["off"], summary["on"]) == (3, 4)
    tokens = summary["medians"]["tokens"]
    assert (tokens["off"], tokens["on"]) == (1200, 800) and tokens["change"] == pytest.approx(-1 / 3)
    bug = next(c for c in summary["categories"] if c["category"] == "bug_fix")
    assert (bug["off"], bug["on"], bug["tokens_on"]) == (3, 3, 700)
    text = report.pilot_text(report.tasks_from_rows(rows), ["t.jsonl"])
    assert "7 tasks (3 with Compass off, 4 on) from 1 file, 2026-09-10 to 2026-09-20" in text
    assert "Main-model tokens" in text and "−33.3%" in text and "(untagged)" in text


def test_without_a_baseline_the_report_says_how_to_get_one():
    text = report.pilot_text(report.tasks_from_rows([turn("T1", 100)]), ["t.jsonl"])
    assert "No tasks with Compass off yet" in text and "Off (n=0)" in text


def test_since_filters_by_date():
    rows = [turn("T1", 100, at="2026-09-01T00:00:00Z"), turn("T2", 100, at="2026-09-15T00:00:00Z")]
    assert [t.task for t in report.tasks_from_rows(rows, since="2026-09-10")] == ["T2"]


# -- the benchmark --------------------------------------------------------------------------------


def bench_rows():
    rows = []
    # Task a: ON saves half; task b: a quarter; task c: nothing. Three runs each.
    for task, off, on in (("a", 1000, 500), ("b", 2000, 1500), ("c", 800, 800)):
        for repeat in (1, 2, 3):
            rows.append(run_row(task, "off", repeat, off + repeat, active=100))
            rows.append(run_row(task, "on", repeat, on + repeat, active=102, passed=not (task == "c" and repeat == 1)))
    for task in ("a", "b", "c"):
        rows.append(run_row(task, "on-no-query", 1, 1100))
    return rows


def test_each_task_is_compared_with_itself():
    result = report.bench(report.tasks_from_rows(bench_rows()))
    assert (result["tasks"], result["runs"], result["repeats"]) == (3, 21, 3)
    assert result["conditions"] == ["off", "on", "on-no-query"]
    tokens = result["tokens"]
    assert tokens["median"] == pytest.approx((1502 - 2002) / 2002)  # b's change is the median of the three
    assert tokens["low"] <= tokens["median"] <= tokens["high"] and tokens["n"] == 3
    assert result["pass"] == {"off": (9, 9), "on": (8, 9), "on-no-query": (3, 3)}
    assert result["active_s"]["median"] == pytest.approx(0.02)
    assert [a["module"] for a in result["ablations"]] == ["query"]
    assert result["failures"] == [{"run": "c-on-1", "task": "c", "condition": "on", "path": "results/c-on-1"}]


def test_the_bootstrap_is_seeded():
    values = [-0.5, -0.25, 0.0, -0.1, -0.4]
    assert report.bootstrap(values) == report.bootstrap(values)
    low, high = report.bootstrap(values)
    assert min(values) <= low <= high <= max(values)


@pytest.mark.parametrize(
    ("tokens", "time", "on", "off", "verdict"),
    [(-0.30, 0.02, (10, 10), (9, 10), "go"), (-0.30, 0.07, (10, 10), (10, 10), "narrow"),
     (-0.15, 0.00, (10, 10), (10, 10), "narrow"), (-0.30, 0.00, (8, 10), (9, 10), "narrow"),
     (-0.05, 0.00, (10, 10), (10, 10), "stop"), (-0.40, 0.12, (10, 10), (10, 10), "stop")],
)
def test_the_decision_rule(tokens, time, on, off, verdict):
    result = {"tokens": {"median": tokens}, "active_s": {"median": time}, "pass": {"on": on, "off": off}}
    assert report.decision(result) == verdict


def test_the_benchmark_report_follows_the_template():
    text = report.bench_text(report.tasks_from_rows(bench_rows()))
    assert text.startswith("# Compass evaluation — 0.1.0, 2026-09-10\nClaude Code 2.1.281 · model claude-opus-5-5 ·"
                           " 3 tasks × 3 conditions × 3 runs")
    for heading in ("## Result", "## By category", "## Module ablation", "## Runs", "## Notable failures"):
        assert heading in text
    assert "Main-model tokens: −25.0% (95% CI " in text and "Pass rate: ON 8/9 vs OFF 9/9" in text
    assert "| bug_fix | 3 | −25.0% | +2.0% | 8/9 / 9/9 |" in text


def test_compass_report_reads_telemetry_and_benchmark_folders(make_repo, tmp_path):
    root = make_repo(files={".compass/config.yaml": ""})
    lines = [turn("T1", 1000, on=False), turn("T2", 600)]
    write(root, ".compass/telemetry.jsonl", "".join(json.dumps(r) + "\n" for r in lines) + "not a row\n")
    proc = run_compass("-C", str(root), "report")
    assert proc.returncode == 0 and "2 tasks (1 with Compass off, 1 on)" in proc.stdout, proc.stderr
    data = json.loads(run_compass("-C", str(root), "report", "--json").stdout)
    assert data["pilot"]["medians"]["tokens"]["change"] == pytest.approx(-0.4) and data["gate"] is None

    # The bypass rate comes from the gate's own log.
    log = [{"t": 1790000000, "kind": "task", "outcome": o} for o in ("pass", "warn", "bypass", "pass", "pass")]
    write(root, ".compass/logs/gate.jsonl", "".join(json.dumps(r) + "\n" for r in log))
    proc = run_compass("-C", str(root), "report")
    assert "Prompt gate: 5 prompts, 1 with !quick (20.0%; the target is under 20%), 1 warned, 0 blocked" in proc.stdout

    results = tmp_path / "results" / "batch1"
    for row in bench_rows():
        folder = results / row["bench"]["run"]
        folder.mkdir(parents=True)
        (folder / "row.json").write_text(json.dumps(row), encoding="utf-8")
    proc = run_compass("report", str(results))
    assert proc.returncode == 0 and proc.stdout.startswith("# Compass evaluation"), proc.stderr
    missing = run_compass("report", str(tmp_path / "nowhere"))
    assert missing.returncode == 1 and "no such file or folder" in missing.stderr
