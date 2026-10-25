"""NF-11: programs Compass starts come from PATH, never from the current
directory, which for hooks and git hooks is the repository root; and when
Compass starts itself with ``python -m compass``, the repository stays off
``sys.path``."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import compass
from compass import background, githooks
from compass.executables import which, which_all
from compass.githooks import HOOKS, script
from compass.repo import Repo, run_git


def plant(folder: Path, name: str) -> Path:
    """A file that looks runnable and must never be run."""
    if os.name == "nt":
        path = folder / f"{name}.exe"
        path.write_bytes(b"MZ")  # not a real program: starting it would fail the test
    else:
        path = folder / name
        path.write_text("#!/bin/sh\necho planted\n", encoding="utf-8")
        path.chmod(0o755)
    return path


@pytest.fixture
def planted_repo(tmp_path, monkeypatch):
    real_git = shutil.which("git")
    assert real_git, "the tests need git"
    repo = tmp_path / "repo"
    repo.mkdir()
    plant(repo, "git")
    plant(repo, "ctags")
    monkeypatch.chdir(repo)
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    # An empty entry, "." and a relative entry all mean the current directory.
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", "bin", str(Path(real_git).parent)]))
    return repo, Path(real_git).parent


def test_a_program_in_the_working_directory_is_never_found(planted_repo):
    repo, real = planted_repo
    found = which("git")
    assert found is not None and Path(found).parent == real
    # Never the planted one; macOS also ships /usr/bin/ctags beside git.
    ctags = which("ctags")
    assert ctags is None or Path(ctags).parent == real


def test_git_runs_from_path_even_inside_a_repository_that_carries_one(planted_repo):
    repo, _ = planted_repo
    proc = run_git(repo, "--version")
    assert proc.returncode == 0 and proc.stdout.startswith(b"git version")


def test_an_explicit_path_is_taken_as_given(tmp_path):
    tool = plant(tmp_path, "ctags")
    assert which(str(tool)) == str(tool)
    assert which(str(tmp_path / "missing" / "ctags")) is None


def test_doctor_names_a_compass_shadowed_on_path(tmp_path, monkeypatch):
    from compass.install import doctor

    sandbox, real = tmp_path / "sandbox", tmp_path / "real"
    for folder in (sandbox, real):
        folder.mkdir()
        plant(folder, "compass")
    monkeypatch.setenv("PATH", os.pathsep.join([str(sandbox), str(real), str(sandbox)]))  # listed twice, counted once
    found = which_all("compass")
    assert [Path(p).parent for p in found] == [sandbox, real] and which("compass") == found[0]
    monkeypatch.chdir(tmp_path)
    lines: list[str] = []
    doctor.run(out=lines.append, check_mcp=False)
    [line] = [text for text in lines if "more than one compass on PATH" in text]
    assert line.split()[0] == "warn" and f"run the first ({found[0]}), not {found[1]}." in line


def test_without_git_on_path_starting_it_fails_like_a_missing_program(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        run_git(tmp_path, "--version")


# -- `python -m compass` from inside a repository -------------------------------------------------


@pytest.fixture
def shadowing_repo(tmp_path):
    """A repository whose root holds a ``compass`` package of its own."""
    repo = tmp_path / "repo"
    (repo / "compass").mkdir(parents=True)
    (repo / "compass" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "compass" / "__main__.py").write_text("print('the repository ran')\n", encoding="utf-8")
    return repo


def test_minus_p_keeps_the_repository_off_sys_path(shadowing_repo):
    plain = subprocess.run([sys.executable, "-m", "compass", "--version"], cwd=shadowing_repo,
                           capture_output=True, text=True)
    assert plain.stdout.strip() == "the repository ran"  # the hazard: -m puts the working directory first
    safe = subprocess.run([sys.executable, "-P", "-m", "compass", "--version"], cwd=shadowing_repo,
                          capture_output=True, text=True)
    assert safe.stdout.strip() == f"compass {compass.__version__}"


def test_every_way_compass_starts_itself_uses_minus_p(tmp_path, monkeypatch):
    for hook in HOOKS:
        text = script(hook, "/usr/bin/python3")
        assert "/usr/bin/python3 -P -m compass" in text and " -m compass" not in text.replace(" -P -m compass", "")
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda command, **kw: started.append(command))
    assert background.spawn(["enrich"], tmp_path)
    assert started[0][started[0].index(sys.executable):][:4] == [sys.executable, "-P", "-m", "compass"]


def test_doctor_points_hooks_from_before_minus_p_at_init(make_repo):
    root = make_repo(files={"a.py": "x = 1\n"})
    repo = Repo(root)
    assert any("installed" in m for m in githooks.install(repo))
    directory, _ = githooks.hooks_dir(repo)
    assert githooks.outdated(directory) == []
    old = directory / "post-commit"
    old.write_text(old.read_text(encoding="utf-8").replace(" -P -m compass", " -m compass"), encoding="utf-8")
    assert githooks.outdated(directory) == ["post-commit"]
    githooks.install(repo)
    assert githooks.outdated(directory) == []
