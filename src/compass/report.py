"""``compass report`` (TM-03): tasks run with Compass on and off.

From telemetry rows (``.compass/telemetry.jsonl``, or files developers
exported), turns roll up into tasks, and the report compares median tasks
with Compass off (the pilot's telemetry-only baseline) and on, overall and by
category. From benchmark results (``bench/results/<batch>/``) it writes the
Evaluation Plan's report instead: each task against itself, the median of
per-task changes with a bootstrap interval, pass counts, categories, module
ablations and the decision rule.

Main-model tokens are input + output + cache writes + cache reads on the
main session's turns; cache reads are also shown on their own. The bootstrap
is seeded, so the same results always give the same report.
"""

from __future__ import annotations

import json
import random
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from compass.telemetry import READ_TOOLS, USAGE_FIELDS, read_rows

SUITE_TASKS, SUITE_REPEATS = 20, 3  # the Evaluation Plan's benchmark
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20260923
TIERS = ("opus", "sonnet", "haiku", "fable")


@dataclass
class Task:
    key: str
    task: str | None
    source: str
    category: str | None = None
    size: str | None = None
    compass: set[bool] = field(default_factory=set)
    modules: set[str] = field(default_factory=set)
    main: dict[str, int] = field(default_factory=lambda: {name: 0 for name, _ in USAGE_FIELDS})
    delegated: Counter = field(default_factory=Counter)  # tier -> tokens
    tools: Counter = field(default_factory=Counter)
    prompts: int = 0
    active_s: float = 0.0
    injected_chars: int = 0
    first: str = ""
    last: str = ""
    versions: set[str] = field(default_factory=set)
    bench: dict[str, Any] | None = None

    @property
    def tokens(self) -> int:
        return sum(self.main.values())

    @property
    def delegated_tokens(self) -> int:
        return sum(self.delegated.values())

    @property
    def corrections(self) -> int:
        return max(0, self.prompts - 1)

    @property
    def reads(self) -> int:
        return sum(self.tools.get(name, 0) for name in READ_TOOLS)

    @property
    def compass_calls(self) -> int:
        return sum(n for name, n in self.tools.items() if name.startswith("compass:"))

    @property
    def on(self) -> bool | None:
        return next(iter(self.compass)) if len(self.compass) == 1 else None  # None: mixed

    def metric(self, name: str) -> float:
        return {
            "tokens": self.tokens, "cache_read": self.main["cache_read"], "active_s": self.active_s,
            "corrections": self.corrections, "reads": self.reads, "compass_calls": self.compass_calls,
            "delegated": self.delegated_tokens, "injected": self.injected_chars / 4,
            "cost_usd": (self.bench or {}).get("cost_usd") or 0.0,
        }[name]


def tier(model: str) -> str:
    lowered = model.lower()
    return next((t for t in TIERS if t in lowered), model)


def tasks_from_rows(rows: list[dict[str, Any]], since: str | None = None) -> list[Task]:
    """Rows rolled up into tasks: by task id per file, or by session for turns
    outside any task; a benchmark run is one task on its own."""
    tasks: dict[str, Task] = {}
    for row in rows:
        at = str(row.get("at") or "")
        if since and at[:10] < since:
            continue
        bench = row.get("bench") if isinstance(row.get("bench"), dict) else None
        if bench:
            key = f"run:{bench.get('run')}"
        elif row.get("task"):
            key = f"{row.get('source')}:{row['task']}"
        else:
            key = f"{row.get('source')}:session:{row.get('session')}"
        t = tasks.get(key) or tasks.setdefault(key, Task(key, row.get("task"), str(row.get("source") or "")))
        t.bench = bench or t.bench
        t.category = row.get("category") or t.category
        t.size = row.get("size") or t.size
        if isinstance(row.get("compass"), bool):
            t.compass.add(row["compass"])
        t.modules.update(m for m in row.get("modules") or [] if isinstance(m, str))
        for usage in (row.get("main") or {}).values():
            for name, _ in USAGE_FIELDS:
                t.main[name] += _int(usage.get(name))
        for model, usage in (row.get("delegated") or {}).items():
            t.delegated[tier(model)] += sum(_int(usage.get(name)) for name, _ in USAGE_FIELDS)
        t.tools.update({k: _int(v) for k, v in (row.get("tools") or {}).items()})
        t.prompts += _int(row.get("prompts"))
        if row.get("kind") == "turn":  # a subagent works inside a turn: its time is already counted
            t.active_s += float(row.get("active_s") or 0)
        t.injected_chars += _int(row.get("injected_chars"))
        t.first = min(filter(None, [t.first, at]), default="")
        t.last = max(t.last, at)
        if row.get("claude_code"):
            t.versions.add(str(row["claude_code"]))
    return sorted(tasks.values(), key=lambda t: (t.first, t.key))


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def load(paths: list[Path]) -> list[dict[str, Any]]:
    """Telemetry files, and benchmark result folders (their ``row.json`` files)."""
    rows: list[dict[str, Any]] = []
    for path in paths:
        if path.is_dir():
            for row_file in sorted(path.rglob("row.json")):
                try:
                    row = json.loads(row_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(row, dict) and isinstance(row.get("bench"), dict):
                    row["source"] = str(row_file.parent)
                    rows.append(row)
        else:
            rows += read_rows([path])
    return rows


# -- the pilot comparison (TM-03) ---------------------------------------------------------------


def pilot(tasks: list[Task]) -> dict[str, Any]:
    off = [t for t in tasks if t.on is False]
    on = [t for t in tasks if t.on is True]
    metrics = ("tokens", "cache_read", "active_s", "corrections", "reads", "compass_calls", "delegated", "injected")
    summary = {
        "tasks": len(tasks), "off": len(off), "on": len(on), "mixed": len(tasks) - len(off) - len(on),
        "from": min((t.first for t in tasks if t.first), default=None), "to": max((t.last for t in tasks), default=None),
        "claude_code": sorted({v for t in tasks for v in t.versions}),
        "medians": {m: {"off": _median(off, m), "on": _median(on, m), "change": _change(_median(off, m), _median(on, m))}
                    for m in metrics},
        "categories": [],
    }
    for category in sorted({t.category or "" for t in tasks}, key=lambda c: (not c, c)):  # untagged last
        group_off = [t for t in off if (t.category or "") == category]
        group_on = [t for t in on if (t.category or "") == category]
        summary["categories"].append({
            "category": category or None, "off": len(group_off), "on": len(group_on),
            "tokens_off": _median(group_off, "tokens"), "tokens_on": _median(group_on, "tokens"),
            "change": _change(_median(group_off, "tokens"), _median(group_on, "tokens")),
        })
    return summary


def gate_summary(path: Path, since: str | None = None) -> dict[str, Any] | None:
    """The prompt gate's decisions from ``logs/gate.jsonl``: the bypass rate
    (``!quick`` prompts over all prompts) the plan's adoption target uses."""
    from datetime import datetime, timezone

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    outcomes: Counter = Counter()
    for line in lines:
        try:
            row = json.loads(line)
            day = datetime.fromtimestamp(float(row["t"]), timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, KeyError, TypeError):
            continue
        if not since or day >= since:
            outcomes[str(row.get("outcome"))] += 1
    total = sum(outcomes.values())
    if not total:
        return None
    return {"prompts": total, "bypass": outcomes["bypass"], "warn": outcomes["warn"], "block": outcomes["block"],
            "rate": outcomes["bypass"] / total}


def pilot_text(tasks: list[Task], sources: list[str], gate: dict[str, Any] | None = None) -> str:
    s = pilot(tasks)
    if not tasks:
        return (
            "No telemetry yet. Compass records one row per turn in .compass/telemetry.jsonl while"
            " telemetry.enabled is on; run some tasks, then compass report again."
        )
    span = f", {s['from'][:10]} to {s['to'][:10]}" if s["from"] else ""
    lines = [
        f"Compass telemetry: {_plural(s['tasks'], 'task')} ({s['off']} with Compass off, {s['on']} on"
        + (f", {s['mixed']} mixed" if s["mixed"] else "") + f") from {len(sources)} file{'s' if len(sources) != 1 else ''}{span}",
    ]
    if s["claude_code"]:
        lines.append(f"Claude Code {', '.join(s['claude_code'])}")
    lines.append("")
    rows = [
        ("Main-model tokens", "tokens", _count), ("  cache reads", "cache_read", _count),
        ("Active time", "active_s", _duration), ("Correction prompts", "corrections", _decimal),
        ("Read, Grep, Glob calls", "reads", _decimal), ("Compass tool calls", "compass_calls", _decimal),
        ("Delegated tokens", "delegated", _count), ("Injected by Compass (tokens)", "injected", _count),
    ]
    width = max(len(label) for label, _, _ in rows)
    lines.append(f"{'Median per task':<{width}}  {'Off (n=' + str(s['off']) + ')':>12}  {'On (n=' + str(s['on']) + ')':>12}  {'Change':>8}")
    for label, key, fmt in rows:
        m = s["medians"][key]
        lines.append(f"{label:<{width}}  {_or_dash(m['off'], fmt):>12}  {_or_dash(m['on'], fmt):>12}  {_pct(m['change']):>8}")
    if len(s["categories"]) > 1 or (s["categories"] and s["categories"][0]["category"]):
        lines += ["", "By category (median main-model tokens):"]
        for c in s["categories"]:
            name = c["category"] or "(untagged)"
            lines.append(
                f"  {name:<12} off {_or_dash(c['tokens_off'], _count):>10} (n={c['off']})"
                f"   on {_or_dash(c['tokens_on'], _count):>10} (n={c['on']})   {_pct(c['change'])}"
            )
    if gate:
        lines += ["", f"Prompt gate: {_plural(gate['prompts'], 'prompt')}, {gate['bypass']} with !quick"
                      f" ({gate['rate'] * 100:.1f}%; the target is under 20%), {gate['warn']} warned, {gate['block']} blocked"]
    if not s["off"]:
        lines += ["", "No tasks with Compass off yet: the baseline comes from a run with every module off"
                      " but telemetry (see the Evaluation Plan's pilot weeks 1-2)."]
    lines += ["", "Tokens are input + output + cache writes + cache reads on the main session's turns."
                  " Tag tasks with Category: and Size: in /compass:task to compare like with like."]
    return "\n".join(lines)


# -- the benchmark report (Evaluation Plan) -------------------------------------------------------


def bench(tasks: list[Task]) -> dict[str, Any]:
    runs = [t for t in tasks if t.bench]
    by = _group(runs)
    names = sorted(by)
    conditions = sorted({c for per in by.values() for c in per})
    result: dict[str, Any] = {
        "runs": len(runs), "tasks": len(names), "conditions": conditions,
        "repeats": max((len(v) for per in by.values() for v in per.values()), default=0),
        "claude_code": sorted({v for t in runs for v in t.versions}),
        "models": sorted({str(t.bench.get("model")) for t in runs if t.bench.get("model")}),
        "compass_version": sorted({str(t.bench.get("compass_version")) for t in runs if t.bench.get("compass_version")}),
    }
    for metric in ("tokens", "cache_read", "active_s", "cost_usd"):
        result[metric] = _headline(by, names, metric, "on", "off")
        result[metric + "_passing"] = _headline(by, names, metric, "on", "off", passing=True)
    result["pass"] = {c: _passes(by, names, c) for c in conditions}
    result["categories"] = []
    for category in sorted({t.bench.get("category") or "" for t in runs}):
        chosen = [n for n in names if _category(by[n]) == category]
        result["categories"].append({
            "category": category or None, "tasks": len(chosen),
            "tokens": _headline(by, chosen, "tokens", "on", "off")["median"],
            "active_s": _headline(by, chosen, "active_s", "on", "off")["median"],
            "pass_on": _passes(by, chosen, "on"), "pass_off": _passes(by, chosen, "off"),
        })
    result["ablations"] = [
        {"condition": c, "module": c.removeprefix("on-no-"), "tokens": _headline(by, names, "tokens", c, "on")}
        for c in conditions if c.startswith("on-no-")
    ]
    result["decision"] = decision(result)
    result["failures"] = [
        {"run": t.bench.get("run"), "task": t.bench.get("task"), "condition": t.bench.get("condition"), "path": t.source}
        for t in runs if not t.bench.get("pass")
    ]
    result["rows"] = [
        {"run": t.bench.get("run"), "task": t.bench.get("task"), "condition": t.bench.get("condition"),
         "repeat": t.bench.get("repeat"), "pass": bool(t.bench.get("pass")), "tokens": t.tokens,
         "active_s": round(t.active_s, 1), "delegated": t.delegated_tokens}
        for t in sorted(runs, key=lambda t: (str(t.bench.get("task")), str(t.bench.get("condition")), t.bench.get("repeat") or 0))
    ]
    return result


def decision(result: dict[str, Any]) -> str | None:
    """The Evaluation Plan's rule, for the benchmark's half of the evidence."""
    tokens, time = result["tokens"]["median"], result["active_s"]["median"]
    if tokens is None or time is None:
        return None
    on, off = result["pass"].get("on"), result["pass"].get("off")
    no_drop = on is None or off is None or on[0] * off[1] >= off[0] * on[1]
    if -tokens < 0.10 or time > 0.10:
        return "stop"
    if -tokens >= 0.20 and time <= 0.05 and no_drop:
        return "go"
    return "narrow"


def bench_text(tasks: list[Task]) -> str:
    r = bench(tasks)
    if not r["runs"]:
        return "No benchmark runs found (bench/results/<batch>/<run>/row.json)."
    day = max(t.last for t in tasks if t.bench)[:10]
    version = ", ".join(r["compass_version"]) or "?"
    lines = [
        f"# Compass evaluation — {version}, {day}",
        f"Claude Code {', '.join(r['claude_code']) or '?'} · model {', '.join(r['models']) or '?'} · "
        f"{r['tasks']} tasks × {len(r['conditions'])} conditions × {r['repeats']} runs",
        "",
        "## Result",
        f"Main-model tokens: {_interval(r['tokens'])}; passing runs only: {_interval(r['tokens_passing'])}",
        f"Cache reads: {_interval(r['cache_read'])}",
        f"Wall-clock: {_pct(r['active_s']['median'])} · Pass rate: {_pass_pair(r['pass'])}",
    ]
    if r["cost_usd"]["median"] is not None:
        lines.append(f"Cost at list prices (Claude Code's estimate, not a bill on a subscription): {_interval(r['cost_usd'])}")
    lines.append(f"Decision: {r['decision'] or 'n/a'} (the benchmark's half; the pilot is the other)")
    if r["tasks"] < SUITE_TASKS or r["repeats"] < SUITE_REPEATS:
        lines.append(
            f"Note: {_plural(r['tasks'], 'task')} × {_plural(r['repeats'], 'run')} is not the Evaluation Plan's suite"
            f" ({SUITE_TASKS} tasks × {SUITE_REPEATS} runs on two repos of 50k+ LOC); read it as a check of the"
            " harness, not as a result."
        )
    lines += [
        "",
        "## By category",
        "| Category | Tasks | Tokens Δ | Time Δ | Pass ON / OFF |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in r["categories"]:
        lines.append(
            f"| {c['category'] or '(none)'} | {c['tasks']} | {_pct(c['tokens'])} | {_pct(c['active_s'])} |"
            f" {_frac(c['pass_on'])} / {_frac(c['pass_off'])} |"
        )
    if r["ablations"]:
        lines += ["", "## Module ablation", "| Module off | Tokens Δ vs full ON |", "| --- | --- |"]
        lines += [f"| {a['module']} | {_interval(a['tokens'])} |" for a in r["ablations"]]
    lines += ["", "## Runs", "| Task | Condition | Run | Pass | Main tokens | Active time | Delegated |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in r["rows"]:
        lines.append(
            f"| {row['task']} | {row['condition']} | {row['repeat']} | {'yes' if row['pass'] else 'no'} |"
            f" {_count(row['tokens'])} | {_duration(row['active_s'])} | {_count(row['delegated'])} |"
        )
    if r["failures"]:
        lines += ["", "## Notable failures"]
        lines += [f"- {f['task']} ({f['condition']}): {f['path']}" for f in r["failures"][:5]]
    lines += ["", "Δ is each task against itself: (median ON − median OFF) / median OFF over its runs, then the"
                  f" median across tasks, with a 95% interval from {BOOTSTRAP_RESAMPLES:,} bootstrap resamples of the tasks."]
    return "\n".join(lines)


def _group(runs: list[Task]) -> dict[str, dict[str, list[Task]]]:
    by: dict[str, dict[str, list[Task]]] = {}
    for t in runs:
        by.setdefault(str(t.bench.get("task")), {}).setdefault(str(t.bench.get("condition")), []).append(t)
    return by


def _category(per: dict[str, list[Task]]) -> str:
    return next((t.bench.get("category") or "" for runs in per.values() for t in runs), "")


def _headline(by, names, metric: str, a: str, b: str, passing: bool = False) -> dict[str, Any]:
    """Median over tasks of (median a − median b) / median b, with its bootstrap interval."""
    deltas = []
    for name in names:
        runs_a = [t for t in by[name].get(a, []) if not passing or t.bench.get("pass")]
        runs_b = [t for t in by[name].get(b, []) if not passing or t.bench.get("pass")]
        if not runs_a or not runs_b:
            continue
        base = statistics.median(t.metric(metric) for t in runs_b)
        if base:
            deltas.append((statistics.median(t.metric(metric) for t in runs_a) - base) / base)
    if not deltas:
        return {"median": None, "low": None, "high": None, "n": 0}
    low, high = bootstrap(deltas)
    return {"median": statistics.median(deltas), "low": low, "high": high, "n": len(deltas)}


def bootstrap(values: list[float], resamples: int = BOOTSTRAP_RESAMPLES) -> tuple[float, float]:
    rng = random.Random(BOOTSTRAP_SEED)
    medians = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(resamples))
    return medians[int(0.025 * (resamples - 1))], medians[int(0.975 * (resamples - 1))]


def _passes(by, names, condition: str) -> tuple[int, int] | None:
    runs = [t for n in names for t in by[n].get(condition, [])]
    return (sum(1 for t in runs if t.bench.get("pass")), len(runs)) if runs else None


def _median(tasks: list[Task], metric: str) -> float | None:
    return statistics.median(t.metric(metric) for t in tasks) if tasks else None


def _change(before: float | None, after: float | None) -> float | None:
    return None if before in (None, 0) or after is None else (after - before) / before


# -- formatting ---------------------------------------------------------------------------------


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _count(value: float) -> str:
    return f"{round(value):,}"


def _decimal(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") if value != int(value) else str(int(value))


def _duration(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}m {seconds % 60:02d}s" if seconds >= 60 else f"{seconds}s"


def _or_dash(value: float | None, fmt) -> str:
    return "–" if value is None else fmt(value)


def _pct(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value * 100:+.1f}%".replace("-", "−")


def _interval(h: dict[str, Any]) -> str:
    if h["median"] is None:
        return "n/a"
    return f"{_pct(h['median'])} (95% CI {_pct(h['low'])} to {_pct(h['high'])}, {h['n']} tasks)"


def _frac(pair: tuple[int, int] | None) -> str:
    return "–" if pair is None else f"{pair[0]}/{pair[1]}"


def _pass_pair(passes: dict[str, Any]) -> str:
    return f"ON {_frac(passes.get('on'))} vs OFF {_frac(passes.get('off'))}"


def as_json(tasks: list[Task], gate: dict[str, Any] | None = None) -> dict[str, Any]:
    if any(t.bench for t in tasks):
        return {"benchmark": bench(tasks)}
    return {"pilot": pilot(tasks), "gate": gate, "tasks": [
        {"task": t.task, "source": t.source, "category": t.category, "size": t.size, "compass": t.on,
         "modules": sorted(t.modules), "tokens": t.tokens, "main": t.main, "delegated": dict(t.delegated),
         "active_s": round(t.active_s, 3), "prompts": t.prompts, "reads": t.reads, "compass_calls": t.compass_calls,
         "injected_chars": t.injected_chars, "first": t.first, "last": t.last}
        for t in tasks
    ]}

