"""Compass's own CI runs on both GitHub Actions and Azure Pipelines (NF-16).

The two definitions cannot be exercised here, so these tests pin down what
must stay identical between them: the platform matrix and the commands run.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from compass.stack import build_profile

ROOT = Path(__file__).resolve().parents[1]


def github_job() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]["test"]


def github() -> tuple[set[tuple[str, str]], list[str]]:
    """Legs as a public repo runs them (a private repo drops one macOS leg)."""
    job = github_job()
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


def test_private_repos_trim_only_macos_legs():
    # Free plans bill macOS at about ten times Linux, so private repos skip one
    # macOS leg; every OS must still be covered (NF-08).
    exclude = github_job()["strategy"]["matrix"]["exclude"]
    assert "github.event.repository.private" in exclude
    assert "macos" in exclude and "ubuntu" not in exclude and "windows" not in exclude


def test_third_party_actions_pin_exact_versions():
    # Not every action publishes a moving major tag (setup-uv has no `v10`), so
    # third-party actions pin a full release tag or a commit SHA.
    uses = [
        step["uses"]
        for workflow in sorted((ROOT / ".github/workflows").glob("*.yml"))
        for job in yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"].values()
        for step in job.get("steps", [])
        if "uses" in step
    ]
    assert uses
    for ref in uses:
        owner, version = ref.split("/", 1)[0], ref.rsplit("@", 1)[1]
        if owner == "actions":
            assert re.fullmatch(r"v\d+(\.\d+){0,2}", version), ref
        else:
            assert re.fullmatch(r"v\d+\.\d+\.\d+|[0-9a-f]{40}", version), ref


def test_both_ci_systems_run_the_same_commands():
    assert uv_commands(github()[1]) == uv_commands(azure()[1]) == [
        "uv sync --locked",
        "uv run compass --help",
        "uv run pytest --perf",
    ]
    for _, commands in (github(), azure()):
        assert any("universal-ctags" in c for c in commands)


def weekly() -> tuple[dict, dict]:
    github = yaml.safe_load((ROOT / ".github/workflows/e2e.yml").read_text(encoding="utf-8"))
    azure = yaml.safe_load((ROOT / "azure-pipelines-e2e.yml").read_text(encoding="utf-8"))
    return github, azure


def test_both_ci_systems_run_the_weekly_claude_code_checks():
    # NF-14: the latest Claude Code every week, on both systems, the same way.
    github, azure = weekly()
    on = github[True] if True in github else github["on"]  # YAML 1.1 reads a bare `on` key as true
    assert [s["cron"] for s in on["schedule"]] == [s["cron"] for s in azure["schedules"]] == ["17 6 * * 1"]
    assert azure["trigger"] == "none" and azure["pr"] == "none" and azure["schedules"][0]["always"] == "true"
    job, pipeline = github["jobs"]["e2e"], azure["jobs"][0]
    commands = [step["run"] for step in job["steps"] if "run" in step]
    scripts = [step["script"] for step in pipeline["steps"] if "script" in step][1:]  # after the key check
    assert commands == [s for s in scripts if not s.startswith("python -m pip")] == [
        "npm install -g @anthropic-ai/claude-code",
        "uv sync --locked",
        "claude --version",
        "uv run python tests/e2e/run_all.py",
    ]
    assert job["runs-on"] == pipeline["pool"]["vmImage"] == "ubuntu-latest"  # one cheap leg a week


def test_the_weekly_checks_run_on_a_claude_code_login_or_not_at_all():
    # Compass is built on Claude Code: CI logs it in with the subscription token
    # `claude setup-token` prints, never an API key, and runs nothing without it.
    github, azure = weekly()
    assert github["jobs"]["e2e"]["if"] == "needs.login.outputs.present == 'true'"
    assert github["jobs"]["login"]["steps"][0]["env"]["TOKEN"] == "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"
    assert github["jobs"]["e2e"]["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"
    first, *rest = azure["jobs"][0]["steps"]
    assert "HAS_LOGIN" in first["script"] and "$''(CLAUDE_CODE_OAUTH_TOKEN)" in first["script"]
    assert all(step["condition"] == "eq(variables['HAS_LOGIN'], 'true')" for step in rest)
    assert rest[-1]["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "$(CLAUDE_CODE_OAUTH_TOKEN)"


@pytest.mark.parametrize(
    ("path", "schema_args"),
    [
        (".github/workflows/ci.yml", ["--builtin-schema", "vendor.github-workflows"]),
        (".github/workflows/e2e.yml", ["--builtin-schema", "vendor.github-workflows"]),
        # Azure's parser treats every scalar as a string, and so does its schema;
        # the transform also resolves ${{ }} template syntax before checking.
        ("azure-pipelines.yml", ["--builtin-schema", "vendor.azure-pipelines", "--data-transform", "azure-pipelines"]),
        ("azure-pipelines-e2e.yml", ["--builtin-schema", "vendor.azure-pipelines", "--data-transform", "azure-pipelines"]),
    ],
)
def test_ci_files_match_their_published_schemas(path, schema_args):
    proc = subprocess.run(
        [sys.executable, "-m", "check_jsonschema", *schema_args, "--regex-variant", "python", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs the Compass checkout to be a git repo")
def test_the_stack_profile_sees_both_pipelines_of_this_repo():
    stacks = build_profile(ROOT)["stacks"]
    assert ".github/workflows/ci.yml" in stacks["github_actions"]["files"]
    assert "azure-pipelines.yml" in stacks["azure_pipelines"]["files"]
    assert "uv run pytest --perf --junitxml=$(Common.TestResultsDirectory)/pytest.xml" in (
        stacks["azure_pipelines"]["commands"]
    )
