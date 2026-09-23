"""Stack detector edge cases the fixtures do not cover."""

from __future__ import annotations

from compass.stack import build_profile, render_text
from conftest import write


def test_poetry_multiple_constraint_dependencies(make_repo):
    root = make_repo(
        files={
            "pyproject.toml": (
                '[tool.poetry]\nname = "app"\n\n[tool.poetry.dependencies]\npython = "^3.11"\n'
                'django = "^5.0"\n'
                'numpy = [{version = "^1.26", python = ">=3.9"}, {version = "^1.24", python = "<3.9"}]\n'
                'requests = {version = "^2.31", extras = ["socks"]}\n'
            ),
        }
    )
    package = build_profile(root)["stacks"]["python"]["packages"][0]
    assert package["name"] == "app" and package["runner"] == "poetry"
    assert package["frameworks"] == {"django": "^5.0", "numpy": "^1.26", "requests": "^2.31"}


def test_yarn_and_npm_lockfiles_resolve_versions(make_repo):
    root = make_repo(
        files={
            "package.json": '{"name": "web", "dependencies": {"react": "^18.2.0", "@nestjs/core": "^10"}}',
            "yarn.lock": (
                '# yarn lockfile v1\n\nreact@^18.2.0:\n  version "18.3.1"\n\n'
                '"@nestjs/core@^10":\n  version "10.4.1"\n'
            ),
        }
    )
    package = build_profile(root)["stacks"]["node"]["packages"][0]
    assert package["package_manager"] == "yarn"
    assert package["frameworks"] == {"@nestjs/core": "10.4.1", "react": "18.3.1"}
    (root / "yarn.lock").unlink()
    write(root, "package-lock.json", '{"packages": {"node_modules/react": {"version": "18.2.0"}}}')
    package = build_profile(root)["stacks"]["node"]["packages"][0]
    assert package["package_manager"] == "npm" and package["frameworks"]["react"] == "18.2.0"


AZURE_DOTNET = """\
trigger:
  - main
pool:
  vmImage: windows-latest
stages:
  - stage: build
    jobs:
      - job: build
        steps:
          - task: DotNetCoreCLI@2
            inputs:
              command: restore
          - task: DotNetCoreCLI@2
            displayName: Unit tests
            inputs:
              command: test
              projects: "**/*Tests.csproj"
              arguments: --configuration Release
          - task: PowerShell@2
            inputs:
              targetType: inline
              script: ./build.ps1 -Target Lint
          - task: VSBuild@1
            inputs:
              solution: Gateway.sln
          - template: templates/pack.yml
"""

AZURE_TEMPLATE = """\
steps:
  - bash: |
      npm ci
      npm run build
  - task: Npm@1
    inputs:
      command: custom
      customCommand: run lint
  - task: Gradle@3
    inputs:
      tasks: check
"""


def test_azure_pipelines_scripts_and_tasks(make_repo):
    root = make_repo(
        files={
            "azure-pipelines.yml": AZURE_DOTNET,
            "eng/pipelines/templates/pack.yml": AZURE_TEMPLATE,
            ".azuredevops/pull_request_template.md": "Describe the change.\n",
            "pipelines/not-a-pipeline.yaml": "name: just data\nvalues: [1, 2]\n",
        }
    )
    azure = build_profile(root)["stacks"]["azure_pipelines"]
    assert azure["files"] == ["azure-pipelines.yml", "eng/pipelines/templates/pack.yml"]
    assert azure["commands"] == [
        "dotnet test **/*Tests.csproj --configuration Release",
        "./build.ps1 -Target Lint",
        "msbuild Gateway.sln",
        "npm run build",
        "npm run lint",
        "./gradlew check",
    ]


def test_github_actions_workflows_and_composite_actions(make_repo):
    root = make_repo(
        files={
            ".github/workflows/ci.yml": "on: push\njobs:\n  t:\n    steps:\n      - run: npm ci\n      - run: npm test\n",
            ".github/actions/lint/action.yml": "runs:\n  using: composite\n  steps:\n    - run: npx eslint .\n",
        }
    )
    github = build_profile(root)["stacks"]["github_actions"]
    assert github["files"] == [".github/workflows/ci.yml", ".github/actions/lint/action.yml"]
    assert github["commands"] == ["npm test", "npx eslint ."]


def test_gitlab_ci(make_repo):
    root = make_repo(files={".gitlab-ci.yml": "test:\n  script:\n    - pip install -e .\n    - pytest -q\n"})
    assert build_profile(root)["stacks"]["gitlab_ci"] == {"files": [".gitlab-ci.yml"], "commands": ["pytest -q"]}


def test_ci_text_rendering_covers_every_provider(make_repo):
    root = make_repo(
        files={
            "azure-pipelines.yml": "steps:\n  - script: make test\n",
            ".github/workflows/ci.yml": "jobs:\n  t:\n    steps:\n      - run: make lint\n",
        }
    )
    text = render_text(build_profile(root))
    assert "azure_pipelines:\n    run: make test\n    files: azure-pipelines.yml" in text
    assert "github_actions:\n    run: make lint\n    files: .github/workflows/ci.yml" in text


def test_broken_manifests_do_not_break_the_profile(make_repo):
    root = make_repo(files={"package.json": "{not json", "Cargo.toml": "[package\n", "go.mod": "module x\n"})
    profile = build_profile(root)
    assert "go" in profile["stacks"] and "node" not in profile["stacks"]
    render_text(profile)
