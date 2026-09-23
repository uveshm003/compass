"""Change manifests (RO-03) and their links, local and hosted (NF-16)."""

from __future__ import annotations

import pytest

from compass import manifest
from compass.manifest import Hosted, parse_remote
from compass.repo import Repo
from conftest import git, write

AI = "@ai" + ":"


@pytest.fixture
def task_repo(make_repo):
    """A committed repo, then a task's edits on top: tagged, untagged, new, exempt."""
    root = make_repo(files={
        "src/api.py": "def get(key):\n    return STORE[key]\n",
        "src/util.ts": "export const a = 1;\n",
        "config/app.json": '{"a": 1}\n',
    })
    git(root, "checkout", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", "base")
    write(root, "src/api.py", (
        "def get(key):\n"
        f"    # {AI}review T1 — a miss returns None instead of raising\n"
        "    return STORE.get(key)\n"
        f"\n\ndef put(key, value):  # {AI}assume T1 — keys are strings\n"
        "    STORE[key] = value\n"
    ))
    write(root, "src/util.ts", f"export const a = 2;  // {AI}change T1 — bumped\n// {AI}todo T1 — drop a\n")
    write(root, "src/new.go", f"package src\n\n// {AI}change T1 — new file\nfunc New() {{}}\n")
    write(root, "src/untagged.py", "x = 1\n")
    write(root, "config/app.json", '{"a": 2}\n')
    return Repo(root)


TOUCHED = ["config/app.json", "src/api.py", "src/new.go", "src/untagged.py", "src/util.ts"]


def test_manifest_groups_anchors_for_the_reviewer(task_repo):
    built = manifest.build(task_repo, "T1", TOUCHED, ("**/*.json",))
    text = manifest.render(built, manifest.relative_linker("../../"))
    assert text.startswith("# Change T1\n\nBranch `main` at `")
    assert text.index("## Review (1)") < text.index("## Assumptions (1)") < text.index("## TODO (1)") < text.index("## Mechanical (2)")
    assert "- [src/api.py:2](../../src/api.py#L2) — a miss returns None instead of raising" in text
    assert "- [src/api.py:6](../../src/api.py#L6) — keys are strings" in text
    assert "## Changed without anchors (2)" in text
    assert "- [config/app.json](../../config/app.json) (exempt: cannot hold comments)" in text
    assert "- [src/untagged.py](../../src/untagged.py)\n" in text
    assert "| [src/new.go](../../src/new.go) | new | 4 | 0 | 1 |" in text
    assert "| [src/api.py](../../src/api.py) | modified | 6 | 1 | 2 |" in text
    assert built.summary() == "1 to review, 1 assumption, 1 todo, 2 mechanical, 1 file without anchors"


def test_manifest_is_written_with_a_json_twin_and_reloads(task_repo):
    built = manifest.build(task_repo, "T1", TOUCHED)
    path = manifest.write(task_repo, built)
    assert path == task_repo.root / ".compass/changes/T1.md"
    assert manifest.load(task_repo, "T1", archived=False) == built
    archived = manifest.write(task_repo, built, archived=True)
    assert "](../../../src/api.py#L2)" in archived.read_text(encoding="utf-8")  # one level deeper


def test_manifest_of_a_task_with_nothing_yet(task_repo):
    text = manifest.render(manifest.build(task_repo, "T9", []), manifest.relative_linker("../../"))
    assert "No changes recorded for T9 yet." in text


def test_manifest_in_a_repo_without_commits(make_repo):
    root = make_repo(files={"a.py": f"x = 1  # {AI}change T1 — first\n"})
    built = manifest.build(Repo(root), "T1", ["a.py"])
    assert (built.base, [f.status for f in built.files]) == (None, ["new"])
    assert "(no commits yet)" in manifest.render(built, manifest.relative_linker("../../"))


@pytest.mark.parametrize(
    ("remote", "kind", "web"),
    [
        ("git@github.com:acme/app.git", "github", "https://github.com/acme/app"),
        ("https://github.com/acme/app", "github", "https://github.com/acme/app"),
        ("https://x-token:secret@github.com/acme/app.git", "github", "https://github.com/acme/app"),
        ("ssh://git@github.com:22/acme/app.git", "github", "https://github.com/acme/app"),
        ("git@github.acme.corp:team/app.git", "github", "https://github.acme.corp/team/app"),
        ("https://dev.azure.com/acme/Payments/_git/api", "azure", "https://dev.azure.com/acme/Payments/_git/api"),
        ("https://acme@dev.azure.com/acme/Payments/_git/api", "azure", "https://dev.azure.com/acme/Payments/_git/api"),
        ("git@ssh.dev.azure.com:v3/acme/Payments/api", "azure", "https://dev.azure.com/acme/Payments/_git/api"),
        ("https://acme.visualstudio.com/Payments/_git/api", "azure", "https://acme.visualstudio.com/Payments/_git/api"),
        ("https://acme.visualstudio.com/DefaultCollection/Payments/_git/api", "azure",
         "https://acme.visualstudio.com/Payments/_git/api"),
        ("acme@vs-ssh.visualstudio.com:v3/acme/Payments/api", "azure", "https://dev.azure.com/acme/Payments/_git/api"),
        ("git@gitlab.com:group/sub/app.git", "gitlab", "https://gitlab.com/group/sub/app"),
    ],
)
def test_remotes_of_every_supported_host(remote, kind, web):
    assert parse_remote(remote) == Hosted(kind, web)


@pytest.mark.parametrize("remote", ["", "/srv/git/app.git", "C:\\repos\\app", "https://bitbucket.org/acme/app.git"])
def test_other_remotes_have_no_hosted_view(remote):
    assert parse_remote(remote) is None


def test_hosted_file_links():
    github = Hosted("github", "https://github.com/acme/app")
    assert github.file_url("feature/x", "src/a b.py", 12) == "https://github.com/acme/app/blob/feature/x/src/a%20b.py#L12"
    azure = Hosted("azure", "https://dev.azure.com/acme/Payments/_git/api")
    assert azure.file_url("feature/x", "src/a.py", 12) == (
        "https://dev.azure.com/acme/Payments/_git/api?path=/src/a.py&version=GBfeature%2Fx"
        "&line=12&lineEnd=12&lineStartColumn=1&lineEndColumn=1&lineStyle=plain&_a=contents"
    )
    assert azure.file_url("0123abc", "src/a.py", None, commit=True).endswith("?path=/src/a.py&version=GC0123abc&_a=contents")
    gitlab = Hosted("gitlab", "https://gitlab.com/group/app")
    assert gitlab.file_url("main", "a.py", 3) == "https://gitlab.com/group/app/-/blob/main/a.py#L3"


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("git@github.com:acme/app.git", "(https://github.com/acme/app/blob/main/src/api.py#L2)"),
        ("https://dev.azure.com/acme/Payments/_git/api",
         "(https://dev.azure.com/acme/Payments/_git/api?path=/src/api.py&version=GBmain&line=2&"),
    ],
)
def test_hosted_manifest_links_to_the_current_branch(task_repo, remote, expected):
    git(task_repo.root, "remote", "add", "origin", remote)
    link, ref = manifest.hosted_linker(task_repo.root, None)
    assert ref == "main"
    text = manifest.render(manifest.build(task_repo, "T1", TOUCHED), link)
    assert expected in text
