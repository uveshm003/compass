from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures"
SNAPSHOTS = TESTS / "snapshots"
FIXTURE_NAMES = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots", action="store_true", help="rewrite snapshot files instead of comparing them"
    )
    parser.addoption("--perf", action="store_true", help="also run latency checks on a generated 100k LOC repo")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--perf"):
        return
    skip = pytest.mark.skip(reason="latency check; run with --perf")
    for item in items:
        if "perf" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def isolated_env(tmp_path_factory):
    """Keep the developer's git config and installed ctags out of every test,
    including module-scoped fixtures (hence session scope). A test that needs
    ctags overrides COMPASS_CTAGS with its own monkeypatch."""
    patch = pytest.MonkeyPatch()
    empty = tmp_path_factory.getbasetemp() / "empty-gitconfig"
    empty.touch()
    patch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    patch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    patch.setenv("GIT_AUTHOR_NAME", "Compass Tests")
    patch.setenv("GIT_AUTHOR_EMAIL", "tests@example.com")
    patch.setenv("GIT_COMMITTER_NAME", "Compass Tests")
    patch.setenv("GIT_COMMITTER_EMAIL", "tests@example.com")
    patch.setenv("COMPASS_CTAGS", "off")
    patch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    yield
    patch.undo()


@pytest.fixture(autouse=True)
def fresh_ctags_lookup():
    from compass.index import ctags

    ctags.find_ctags.cache_clear()
    yield
    ctags.find_ctags.cache_clear()


def copy_fixture(name: str, dest: Path) -> Path:
    """A fixture repo as a fresh git working tree at ``dest``."""
    junk = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", ".ruff_cache", ".pytest_cache")
    shutil.copytree(FIXTURES / name, dest, ignore=junk)
    git(dest, "init", "-q")
    return dest.resolve()


@pytest.fixture(scope="module")
def indexed_fixtures(tmp_path_factory):
    """Every fixture repo, indexed once per test module (read-only use)."""
    from compass.index.indexer import Indexer
    from compass.repo import Repo

    base = tmp_path_factory.mktemp("indexed")
    repos = {}
    for name in FIXTURE_NAMES:
        repo = Repo(copy_fixture(name, base / name))
        Indexer(repo).build()
        repos[name] = repo
    return repos


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


@pytest.fixture
def make_repo(tmp_path):
    """A fresh git working tree, optionally copied from tests/fixtures/<name>."""
    counter = 0

    def make(fixture: str | None = None, files: dict[str, str] | None = None) -> Path:
        nonlocal counter
        counter += 1
        root = tmp_path / f"{fixture or 'repo'}-{counter}"
        if fixture:
            root = copy_fixture(fixture, root)
        else:
            root.mkdir()
            git(root, "init", "-q")
        for rel, text in (files or {}).items():
            write(root, rel, text)
        return root.resolve()

    return make


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def bump_mtime(path: Path) -> None:
    """Make sure a rewrite is visible to the size+mtime fast path on coarse clocks."""
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


def run_compass(
    *args: str, cwd: Path | None = None, input: str | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "compass", *args],
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, **(env or {})},
    )


posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX-only fixture (shell scripts, chmod, symlinks)")
needs_permissions = pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="needs POSIX permissions that root ignores",
)


def read_tree(root: Path) -> dict[str, str]:
    """Every file under ``root`` as {relative posix path: text}."""
    if not root.exists():
        return {}
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def snapshot(request):
    update = request.config.getoption("--update-snapshots")

    def check_text(rel: str, actual: str) -> None:
        path = SNAPSHOTS / rel
        if update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8", newline="\n")
            return
        if not path.exists():
            pytest.fail(f"missing snapshot {rel}; run `pytest --update-snapshots` to create it")
        expected = path.read_text(encoding="utf-8")
        if actual != expected:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    f"snapshot/{rel}",
                    "actual",
                )
            )
            pytest.fail(f"snapshot {rel} differs (run `pytest --update-snapshots` to accept):\n{diff}")

    def check_tree(rel: str, actual: dict[str, str]) -> None:
        folder = SNAPSHOTS / rel
        if update:
            shutil.rmtree(folder, ignore_errors=True)
            for name, text in actual.items():
                check_text(f"{rel}/{name}", text)
            return
        expected = read_tree(folder)
        assert sorted(actual) == sorted(expected), f"files under snapshot {rel} differ"
        for name, text in actual.items():
            check_text(f"{rel}/{name}", text)

    check_text.tree = check_tree
    return check_text
