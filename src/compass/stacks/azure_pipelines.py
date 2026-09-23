"""Azure Pipelines (Azure DevOps): the commands a pipeline really runs.

Pipeline files are ``azure-pipelines*.yml`` (usually at the root) or YAML under
``.azure-pipelines/``, ``.azuredevops/``, ``.pipelines/`` or any ``pipelines/``
folder, which is where templates tend to live. Script steps (``script``,
``bash``, ``pwsh``, ``powershell`` and inline task scripts) are read as written;
the common build tasks are translated to the command they run, so
``DotNetCoreCLI@2`` with ``command: test`` reads as ``dotnet test``.
"""

from __future__ import annotations

from typing import Any

from compass.stack import StackRepo, compact
from compass.stacks._ci import MAX_FILES, by_depth, commands

PIPELINE_DIRS = frozenset({".azure-pipelines", ".azuredevops", ".pipelines", "pipelines"})
# Top-level keys of a pipeline or of a template it includes.
PIPELINE_KEYS = frozenset({"trigger", "pr", "pool", "stages", "jobs", "steps", "extends", "resources", "schedules"})
SCRIPT_KEYS = ("script", "bash", "pwsh", "powershell", "inlineScript")


def detect(repo: StackRepo) -> dict | None:
    files: list[str] = []
    lines: list[str] = []
    for path in by_depth(p for p in repo.files if _looks_like_pipeline(p))[:MAX_FILES]:
        data = repo.read_yaml(path)
        if isinstance(data, dict) and PIPELINE_KEYS & data.keys():
            files.append(path)
            _walk(data, lines)
    if not files:
        return None
    return compact({"files": files, "commands": commands(lines)})


def _looks_like_pipeline(path: str) -> bool:
    if not path.lower().endswith((".yml", ".yaml")):
        return False
    parts = path.split("/")
    return parts[-1].lower().startswith("azure-pipelines") or any(p.lower() in PIPELINE_DIRS for p in parts[:-1])


def _walk(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("task"), str):
            out.extend(_task(node["task"], node.get("inputs")))
        for key in SCRIPT_KEYS:
            if isinstance(node.get(key), str):
                out.extend(node[key].splitlines())
        for value in node.values():
            if isinstance(value, (dict, list)):
                _walk(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk(item, out)


def _task(task: str, inputs: Any) -> list[str]:
    """The command line behind a built-in build or test task."""
    name = task.split("@", 1)[0]
    inputs = inputs if isinstance(inputs, dict) else {}

    def get(key: str, default: str = "") -> str:
        value = inputs.get(key, default)
        return str(value).strip() if isinstance(value, (str, int, float)) else default

    if name == "DotNetCoreCLI":
        command = get("command", "build")
        if command == "custom":
            command = get("custom")
        return [_join("dotnet", command, get("projects"), get("arguments"))]
    if name == "Npm":
        command = get("command", "install")
        return [_join("npm", get("customCommand") if command == "custom" else command)]
    if name == "Maven":
        return [_join("mvn", get("goals", "package"), get("options"))]
    if name == "Gradle":
        return [_join("./gradlew", get("tasks", "build"), get("options"))]
    if name == "VSBuild":
        return [_join("msbuild", get("solution", "**/*.sln"), get("msbuildArgs"))]
    if name == "VSTest":
        return [_join("vstest.console", get("testAssemblyVer2").split("\n", 1)[0])]
    return []


def _join(*parts: str) -> str:
    return " ".join(" ".join(p.split()) for p in parts if p and p.strip())
