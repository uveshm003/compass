"""GitHub Actions: workflows and local composite actions, and the commands
they really run (``run:`` steps)."""

from __future__ import annotations

from compass.stack import StackRepo, compact
from compass.stacks._ci import MAX_FILES, by_depth, commands


def detect(repo: StackRepo) -> dict | None:
    workflows = [p for p in repo.files if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))]
    actions = [
        p for p in repo.files if p.startswith(".github/actions/") and p.rsplit("/", 1)[-1] in ("action.yml", "action.yaml")
    ]
    files = by_depth(workflows + actions)[:MAX_FILES]
    if not files:
        return None
    lines: list[str] = []
    for path in files:
        data = repo.read_yaml(path)
        if not isinstance(data, dict):
            continue
        steps = []
        for job in (data.get("jobs") or {}).values():  # workflows
            if isinstance(job, dict):
                steps.extend(job.get("steps") or [])
        runs = data.get("runs")  # composite actions
        if isinstance(runs, dict):
            steps.extend(runs.get("steps") or [])
        for step in steps:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                lines.extend(step["run"].splitlines())
    return compact({"files": files, "commands": commands(lines)})
