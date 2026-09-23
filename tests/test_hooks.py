"""Hook contract tests: recorded-style JSON piped into `compass hook <event>`,
asserting exit code, stdout and stderr (Step 9). Every internal failure must
exit 0 (NF-12)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from compass.index.indexer import Indexer
from compass.index.store import Store
from compass.lock import file_lock
from compass.repo import Repo
from conftest import FIXTURES, git, run_compass, write


def post_tool_use(root, file_path, tool="Edit"):
    return json.dumps(
        {
            "session_id": "abc123",
            "transcript_path": str(root / "transcript.jsonl"),
            "cwd": str(root),
            "hook_event_name": "PostToolUse",
            "tool_name": tool,
            "tool_input": {"file_path": str(file_path), "old_string": "a", "new_string": "b"},
            "tool_response": {"filePath": str(file_path), "success": True},
        }
    )


def session_start(root):
    return json.dumps(
        {
            "session_id": "abc123",
            "transcript_path": str(root / "transcript.jsonl"),
            "cwd": str(root),
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
    )


def symbols(repo: Repo) -> set[str]:
    with Store.open(repo.db_path) as store:
        return {s["name"] for s in store.dump()["symbols"]}


def wait_for(predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


@pytest.fixture
def indexed(make_repo):
    repo = Repo(make_repo("python_app"))
    Indexer(repo).build()
    return repo


def test_post_edit_reindexes_the_edited_file(indexed):
    path = write(indexed.root, "src/inventory/alerts.py", '"""Alerts."""\n\ndef raise_alarm():\n    pass\n')
    proc = run_compass("hook", "post-edit", input=post_tool_use(indexed.root, path, "Write"))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert "raise_alarm" in symbols(indexed)
    assert "fn raise_alarm()" in (indexed.map_dir / "src/inventory.md").read_text(encoding="utf-8")


def test_post_edit_with_a_relative_path_and_multiedit(indexed):
    write(indexed.root, "src/inventory/api.py", "def replaced():\n    pass\n")
    payload = json.loads(post_tool_use(indexed.root, "src/inventory/api.py", "MultiEdit"))
    proc = run_compass("hook", "post-edit", input=json.dumps(payload))
    assert proc.returncode == 0
    assert "replaced" in symbols(indexed) and "get_item" not in symbols(indexed)


def test_post_edit_outside_the_repo_or_in_compass_state_is_ignored(indexed, tmp_path):
    before = symbols(indexed)
    outside = write(tmp_path, "elsewhere.py", "def x():\n    pass\n")
    for target in (outside, indexed.compass_dir / "config.yaml"):
        proc = run_compass("hook", "post-edit", input=post_tool_use(indexed.root, target))
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert symbols(indexed) == before


@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]", '{"tool_input": "oops"}', '{"tool_input": {}}'])
def test_malformed_input_fails_open(indexed, stdin):
    proc = run_compass("hook", "post-edit", cwd=indexed.root, input=stdin)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


@pytest.mark.parametrize("event", ["prompt", "pre-edit", "stop", "some-future-event"])
def test_events_without_a_handler_pass_through(indexed, event):
    proc = run_compass("hook", event, input=json.dumps({"cwd": str(indexed.root), "prompt": "hi"}))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


@pytest.mark.parametrize("args", [["hook"], ["hook", "prompt", "--new-flag", "x"], ["hook", "--help"]])
def test_unexpected_hook_arguments_never_exit_2(indexed, args):
    # Exit 2 is Claude Code's "block"; a usage error must never produce it.
    proc = run_compass(*args, input=json.dumps({"cwd": str(indexed.root)}))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_hook_input_is_utf8_whatever_the_locale(tmp_path):
    # Windows decodes piped stdin with the ANSI code page unless told otherwise.
    root = tmp_path / "Jürgen" / "repo"
    shutil.copytree(FIXTURES / "python_app", root)
    git(root, "init", "-q")
    repo = Repo(root.resolve())
    Indexer(repo).build()
    path = write(repo.root, "src/inventory/alerts.py", "def raise_alarm():\n    pass\n")
    payload = post_tool_use(repo.root, path, "Write").encode("utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "compass", "hook", "post-edit"],
        input=payload,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b"")
    assert "raise_alarm" in symbols(repo)


def test_repos_without_compass_are_left_alone(make_repo):
    root = make_repo("python_app")
    for event, payload in (("post-edit", post_tool_use(root, root / "README.md")), ("session-start", session_start(root))):
        proc = run_compass("hook", event, input=payload)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert not (root / ".compass").exists()


def test_internal_errors_exit_zero_and_are_logged(indexed):
    indexed.db_path.unlink()
    indexed.db_path.mkdir()  # an index.db that cannot be opened or replaced
    path = indexed.root / "src/inventory/api.py"
    proc = run_compass("hook", "post-edit", input=post_tool_use(indexed.root, path))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    log = (indexed.logs_dir / "errors.log").read_text(encoding="utf-8")
    assert "[hook post-edit]" in log and "Traceback" in log


def test_session_start_refreshes_stale_files_inline(indexed):
    write(indexed.root, "src/inventory/new_module.py", "def fresh():\n    pass\n")
    proc = run_compass("hook", "session-start", input=session_start(indexed.root))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert "fresh" in symbols(indexed)


def test_session_start_restores_a_deleted_map(indexed):
    shutil.rmtree(indexed.map_dir)
    proc = run_compass("hook", "session-start", input=session_start(indexed.root))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    assert "merge_items" in (indexed.map_dir / "src/inventory.md").read_text(encoding="utf-8")


def test_session_start_hands_off_when_the_index_is_busy(indexed):
    write(indexed.root, "src/inventory/late.py", "def late():\n    pass\n")
    with file_lock(indexed.lock_path, timeout=5):
        started = time.monotonic()
        proc = run_compass("hook", "session-start", input=session_start(indexed.root))
        assert proc.returncode == 0
        assert time.monotonic() - started < 5
        assert "late" not in symbols(indexed)
    # The background run waited for the lock and then caught up.
    assert wait_for(lambda: "late" in symbols(indexed))


def test_session_start_builds_a_missing_index_in_the_background(make_repo):
    repo = Repo(make_repo("python_app"))
    repo.ensure_state_dir()
    proc = run_compass("hook", "session-start", input=session_start(repo.root))
    assert proc.returncode == 0 and proc.stderr == ""
    assert "being built in the background" in proc.stdout
    assert wait_for(lambda: (repo.map_dir / "_index.md").exists() and "merge_items" in symbols(repo))
