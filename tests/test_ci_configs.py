"""Compass's own CI runs on both GitHub Actions and Azure Pipelines (NF-16).

The two definitions cannot be exercised here, so these tests pin down what
must stay identical between them: the platform matrix and the commands run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from compass.stack import build_profile

ROOT = Path(__file__).resolve().parents[1]


def github() -> tuple[set[tuple[str, str]], list[str]]:
    job = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]["test"]
    matrix = job["strategy"]["matrix"]
    legs = {(image, python) for image in matrix["os"] for python in matrix["python"]}
    return legs, [step["run"] for step in job["steps"] if "run" in step]


def azure() -> tuple[set[tuple[str, str]], list[str]]:
    job = yaml.safe_load((ROOT / "azure-pipelines.yml").read_text(encoding="utf-8"))["jobs"][0]
    legs = {(leg["imageName"], leg["UV_PYTHON"]) for leg in job["strategy"]["matrix"].values()}
    return legs, [step["script"] for step in job["steps"] if "script" in step]


def uv_commands(commands: list[str]) -> list[str]:
    """The project commands, without Azure's extra test-report argument."""
    return [re.sub(r"\s+--junitxml=\S+", "", c) for c in commands if c.startswith("uv ")]


def test_both_ci_systems_test_the_same_platforms():
    legs = github()[0]
    assert legs == azure()[0]
    assert {image.split("-")[0] for image, _ in legs} == {"ubuntu", "macos", "windows"}  # NF-08
    assert {python for _, python in legs} == {"3.11", "3.12"}


def test_both_ci_systems_run_the_same_commands():
    assert uv_commands(github()[1]) == uv_commands(azure()[1]) == [
        "uv sync --locked",
        "uv run compass --help",
        "uv run pytest --perf",
    ]
    for _, commands in (github(), azure()):
        assert any("universal-ctags" in c for c in commands)


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs the Compass checkout to be a git repo")
def test_the_stack_profile_sees_both_pipelines_of_this_repo():
    stacks = build_profile(ROOT)["stacks"]
    assert ".github/workflows/ci.yml" in stacks["github_actions"]["files"]
    assert "azure-pipelines.yml" in stacks["azure_pipelines"]["files"]
    assert "uv run pytest --perf --junitxml=$(Common.TestResultsDirectory)/pytest.xml" in (
        stacks["azure_pipelines"]["commands"]
    )
