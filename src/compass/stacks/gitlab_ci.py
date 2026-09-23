"""GitLab CI: the commands ``.gitlab-ci.yml`` jobs really run."""

from __future__ import annotations

from compass.stack import StackRepo, compact
from compass.stacks._ci import commands

PATH = ".gitlab-ci.yml"


def detect(repo: StackRepo) -> dict | None:
    if not repo.exists(PATH):
        return None
    data = repo.read_yaml(PATH)
    lines: list[str] = []
    for job in (data.values() if isinstance(data, dict) else []):
        script = job.get("script") if isinstance(job, dict) else None
        if isinstance(script, str):
            lines.extend(script.splitlines())
        elif isinstance(script, list):
            lines.extend(s for s in script if isinstance(s, str))
    return compact({"files": [PATH], "commands": commands(lines)})
