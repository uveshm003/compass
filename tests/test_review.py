"""The review loop end to end (RO-01 to RO-05): hook contracts with recorded-
style JSON, accept, and real git commits against the pre-commit hook.

Tags are assembled at runtime (``AI``) so this file never trips Compass's own
pre-commit check.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

from compass import state
from compass.index.indexer import Indexer
from compass.index.store import Store
from compass.lock import file_lock
from compass.repo import Repo
from conftest import bump_mtime, git, posix_only, run_compass, write

AI = "@ai" + ":"
EVENT_NAMES = {"session-start": "SessionStart", "prompt": "UserPromptSubmit", "post-edit": "PostToolUse", "stop": "Stop"}


def hook(event: str, root, session: str = "s1", **fields) -> subprocess.CompletedProcess:
    payload = {
        "session_id": session, "transcript_path": str(root / "transcript.jsonl"), "cwd": str(root),
        "hook_event_name": EVENT_NAMES[event], **fields,
    }
    return run_compass("hook", event, input=json.dumps(payload))


def context(proc: subprocess.CompletedProcess) -> str:
    """What a UserPromptSubmit answer adds to Claude's context."""
    assert (proc.returncode, proc.stderr) == (0, "")
    if not proc.stdout.strip():
        return ""
    return json.loads(proc.stdout).get("hookSpecificOutput", {}).get("additionalContext", "")


def edit(root, rel: str, text: str, session: str = "s1") -> None:
    """What Claude's Write tool does, then its PostToolUse hook."""
    path = write(root, rel, text)
    bump_mtime(path)
    proc = hook("post-edit", root, session, tool_name="Write", tool_input={"file_path": str(path), "content": text})
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def stop(root, session: str = "s1", **fields) -> dict | None:
    fields.setdefault("stop_hook_active", False)
    proc = hook("stop", root, session, **fields)
    assert (proc.returncode, proc.stderr) == (0, "")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def committed_repo(make_repo, **files) -> Repo:
    root = make_repo("python_app")
    for rel, text in files.items():
        write(root, rel, text)
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", "base")
    repo = Repo(root)
    Indexer(repo).build()
    return repo


@pytest.fixture
def repo(make_repo):
    return committed_repo(make_repo)


# -- session context and turns (RO-01, RO-02) -----------------------------------


def test_session_start_hands_claude_the_rules_and_the_task(repo):
    proc = hook("session-start", repo.root, source="startup")
    assert (proc.returncode, proc.stderr) == (0, "")
    text = proc.stdout
    assert text.startswith("[compass] Compass is active in this repository.")
    assert "use the compass MCP tools (find_symbol" in text
    assert "Review anchors, task T1:" in text
    for kind in ("review", "assume", "todo", "change"):
        assert f"    {AI}{kind} T1 — " in text
    assert "Keep the final reply to at most 10 lines" in text and ".compass/changes/T1.md" in text
    current = state.read(repo)
    assert current["task"] == "T1" and current["sessions"]["s1"]["announced"] == "T1"


def test_session_rules_follow_the_config(repo):
    write(repo.root, ".compass/config.yaml", "review:\n  reply_max_lines: 6\n")
    assert "at most 6 lines" in hook("session-start", repo.root, source="startup").stdout
    write(repo.root, ".compass/config.yaml", "review:\n  enabled: false\n")
    text = hook("session-start", repo.root, source="compact").stdout
    assert "use the compass MCP tools" in text and "Review anchors" not in text


def test_a_prompt_announces_a_task_only_when_it_is_new(repo):
    hook("session-start", repo.root, source="startup")
    assert hook("prompt", repo.root, prompt="hi").stdout == ""
    assert run_compass("-C", str(repo.root), "task", "new").stdout.startswith("T2 ")
    assert context(hook("prompt", repo.root, prompt="next")).startswith("[compass] Task T2 is now active")
    assert hook("prompt", repo.root, prompt="again").stdout == ""
    assert context(hook("prompt", repo.root, session="other", prompt="hi")).startswith("[compass] Task T2")


def test_tags_already_in_files_keep_their_ids(repo):
    # A lost state.json must not hand out an id that tags in the tree still use.
    write(repo.root, "src/old.py", f"x = 1  # {AI}change T1 — from before\n")
    assert "task T2:" in hook("session-start", repo.root, source="startup").stdout


def test_post_edit_records_the_file_for_the_task_and_the_turn(repo):
    edit(repo.root, "src/inventory/alerts.py", "def alarm():\n    pass\n")
    current = state.read(repo)
    assert current["tasks"]["T1"]["touched"] == ["src/inventory/alerts.py"]
    assert current["sessions"]["s1"]["turn"] == ["src/inventory/alerts.py"]


def test_parallel_post_edit_hooks_lose_no_file(repo):
    procs = []
    for n in range(8):
        path = write(repo.root, f"src/inventory/m{n}.py", f"def f{n}():\n    pass\n")
        payload = json.dumps({
            "session_id": "s1", "cwd": str(repo.root), "hook_event_name": "PostToolUse",
            "tool_name": "Write", "tool_input": {"file_path": str(path)},
        })
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "compass", "hook", "post-edit"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ))
        procs[-1].stdin.write(payload.encode())
        procs[-1].stdin.close()
    assert all(p.wait(60) == 0 for p in procs)
    assert state.read(repo)["tasks"]["T1"]["touched"] == [f"src/inventory/m{n}.py" for n in range(8)]


# -- the Stop hook (RO-03, RO-04) --------------------------------------------------


def test_stop_asks_once_for_missing_anchors_and_writes_the_manifest(repo):
    hook("prompt", repo.root, prompt="add alerts")
    edit(repo.root, "src/inventory/alerts.py", "def alarm():\n    pass\n")
    answer = stop(repo.root)
    assert answer["decision"] == "block"
    assert "Changed this turn without a T1 anchor: src/inventory/alerts.py." in answer["reason"]
    assert f"{AI}review T1 (a judgment call" in answer["reason"]
    assert (repo.root / ".compass/changes/T1.md").is_file()
    # Claude continues, adds the tag, stops again: now it passes.
    edit(repo.root, "src/inventory/alerts.py", f"# {AI}change T1 — new alarm helper\ndef alarm():\n    pass\n")
    answer = stop(repo.root, stop_hook_active=True)
    assert answer == {"systemMessage": "[compass] T1: 1 mechanical → .compass/changes/T1.md"}
    text = (repo.root / ".compass/changes/T1.md").read_text(encoding="utf-8")
    assert "- [src/inventory/alerts.py:1](../../src/inventory/alerts.py#L1) — new alarm helper" in text


def test_stop_never_blocks_twice_in_a_row(repo):
    edit(repo.root, "src/inventory/alerts.py", "def alarm():\n    pass\n")
    assert stop(repo.root)["decision"] == "block"
    edit(repo.root, "src/inventory/more.py", "def more():\n    pass\n")  # still no anchors
    second = stop(repo.root)  # without stop_hook_active: Compass remembers its own block
    assert "decision" not in second and "2 files without anchors" in second["systemMessage"]
    assert stop(repo.root) is None  # nothing new this turn


def test_a_new_prompt_starts_a_new_turn(repo):
    edit(repo.root, "src/inventory/alerts.py", "def alarm():\n    pass\n")
    assert stop(repo.root)["decision"] == "block"
    hook("prompt", repo.root, prompt="now something else")
    edit(repo.root, "src/inventory/other.py", "def other():\n    pass\n")
    answer = stop(repo.root)
    assert answer["decision"] == "block" and "src/inventory/other.py." in answer["reason"]
    assert "alerts.py" not in answer["reason"]


def test_stop_passes_files_that_need_no_anchor(make_repo):
    repo = committed_repo(make_repo, **{"data/app.json": '{"a": 1}\n', "logo.bin": "x"})
    hook("session-start", repo.root, source="startup")
    edit(repo.root, "data/app.json", '{"a": 2}\n')  # JSON cannot hold a comment
    path = repo.root / "logo.bin"
    path.write_bytes(b"\0\1binary")
    edit(repo.root, "src/inventory/api.py", (repo.root / "src/inventory/api.py").read_text(encoding="utf-8"))  # unchanged
    hook("post-edit", repo.root, tool_name="Write", tool_input={"file_path": str(path)})
    edit(repo.root, "src/inventory/tagged.py", f"x = 1  # {AI}assume T1 — one is enough\n")
    answer = stop(repo.root)
    assert answer == {"systemMessage": "[compass] T1: 1 assumption → .compass/changes/T1.md"}


def test_stop_without_required_anchors_or_with_review_off(repo):
    write(repo.root, ".compass/config.yaml", "review:\n  require_anchors: false\n")
    edit(repo.root, "src/inventory/alerts.py", "def alarm():\n    pass\n")
    assert stop(repo.root) == {"systemMessage": "[compass] T1: 1 file without anchors → .compass/changes/T1.md"}
    write(repo.root, ".compass/config.yaml", "review:\n  enabled: false\n")
    edit(repo.root, "src/inventory/more.py", "def more():\n    pass\n")
    assert stop(repo.root) is None


def test_review_hooks_fail_open(repo):
    repo.state_path.write_text("{not json", encoding="utf-8")  # a corrupt state file is treated as empty
    edit(repo.root, "src/inventory/alerts.py", "def alarm():\n    pass\n")
    assert stop(repo.root)["decision"] == "block"
    with file_lock(repo.state_lock_path, timeout=5):  # another hook holds the state
        started = time.monotonic()
        for event in ("prompt", "post-edit", "stop"):
            proc = hook(event, repo.root, prompt="x", tool_name="Write", tool_input={"file_path": "src/x.py"})
            assert (proc.returncode, proc.stderr) == (0, "")
        assert time.monotonic() - started < 20
    assert "LockTimeout" in (repo.logs_dir / "errors.log").read_text(encoding="utf-8")


# -- accept and the manifest command (RO-03, RO-05) ----------------------------------


def test_accept_strips_the_task_and_archives_its_manifest(repo):
    hook("session-start", repo.root, source="startup")
    api = (repo.root / "src/inventory/api.py").read_text(encoding="utf-8")
    edit(repo.root, "src/inventory/api.py", f"# {AI}review T1 — routes are versioned\n" + api)
    edit(repo.root, "src/inventory/alerts.py", f"def alarm():  # {AI}assume T1 — sync is fine\n    pass\n")
    edit(repo.root, "README.md", (repo.root / "README.md").read_text(encoding="utf-8") + f"<!-- {AI}todo T1 — document alarms -->\n")
    assert stop(repo.root)["systemMessage"].startswith("[compass] T1: 1 to review, 1 assumption, 1 todo")
    proc = run_compass("-C", str(repo.root), "accept")
    assert (proc.returncode, proc.stderr) == (0, "")
    assert proc.stdout == "Accepted T1: removed 3 anchors from 3 files; manifest archived at .compass/changes/archive/T1.md.\n"
    assert (repo.root / "src/inventory/api.py").read_text(encoding="utf-8") == api
    assert (repo.root / "src/inventory/alerts.py").read_text(encoding="utf-8") == "def alarm():\n    pass\n"
    assert AI not in (repo.root / "README.md").read_text(encoding="utf-8")
    assert not (repo.root / ".compass/changes/T1.md").exists()
    archived = (repo.root / ".compass/changes/archive/T1.md").read_text(encoding="utf-8")
    assert "accepted; anchors stripped" in archived
    assert "- [src/inventory/api.py:1](../../../src/inventory/api.py#L1) — routes are versioned" in archived
    current = state.read(repo)
    assert current["task"] is None and current["accepted"] == ["T1"] and "T1" not in current["tasks"]
    with Store.open(repo.db_path) as store:  # the index followed the stripped files
        assert store.file_info("src/inventory/alerts.py")["size"] == len("def alarm():\n    pass\n")
    assert context(hook("prompt", repo.root, prompt="next")).startswith("[compass] Task T2 is now active")


def test_accept_without_anything_to_accept(repo):
    proc = run_compass("-C", str(repo.root), "accept")
    assert proc.returncode == 1 and "no active task" in proc.stderr
    run_compass("-C", str(repo.root), "task")
    proc = run_compass("-C", str(repo.root), "accept", "T7")
    assert proc.returncode == 1 and "T7 has no anchors and no recorded changes. The active task is T1." in proc.stderr


def test_manifest_command_live_and_hosted_after_accept(repo):
    hook("session-start", repo.root, source="startup")
    git(repo.root, "remote", "add", "origin", "https://dev.azure.com/acme/Sensors/_git/inventory")
    edit(repo.root, "src/inventory/alerts.py", f"import os\n# {AI}change T1 — helper\ndef alarm():\n    pass\n")
    proc = run_compass("-C", str(repo.root), "manifest")
    assert proc.stdout == ".compass/changes/T1.md: 1 mechanical\n"
    run_compass("-C", str(repo.root), "accept", "T1")
    hosted = run_compass("-C", str(repo.root), "manifest", "T1", "--hosted", "--ref", "release/1.0").stdout
    # Line 2 held the tag; the archive points at the code that moved up into it.
    assert "[src/inventory/alerts.py:2](https://dev.azure.com/acme/Sensors/_git/inventory?path=/src/inventory/alerts.py" in hosted
    assert "&version=GBrelease%2F1.0&line=2&" in hosted
    data = json.loads(run_compass("-C", str(repo.root), "manifest", "T1", "--json").stdout)
    assert data["accepted"] is True and data["anchors"][0]["line"] == 2


def test_check_anchors_lists_the_working_tree(repo):
    write(repo.root, "src/a.py", f"x = 1  # {AI}todo T1 — later\n")
    proc = run_compass("-C", str(repo.root), "check-anchors")
    assert proc.stdout == "src/a.py:1  todo T1 — later\n"


# -- the pre-commit hook (RO-05) ------------------------------------------------------


def commit(root, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "commit", "-q", "-m", "change", *extra], cwd=root, capture_output=True, text=True)


@pytest.fixture
def hooked(make_repo):
    root = make_repo("python_app")
    assert run_compass("init", cwd=root).returncode == 0
    git(root, "add", "-A")
    assert commit(root).returncode == 0
    return Repo(root)


@posix_only
def test_pre_commit_refuses_leftover_anchors_until_accepted(hooked):
    hook("session-start", hooked.root, source="startup")
    api = (hooked.root / "src/inventory/api.py").read_text()
    edit(hooked.root, "src/inventory/api.py", f"# {AI}review T1 — check me\nTIMEOUT_S = 5\n" + api)
    git(hooked.root, "add", "-A")
    refused = commit(hooked.root)
    assert refused.returncode != 0
    assert "commit refused: the staged changes still add 1 AI anchor tag:" in refused.stderr
    assert "src/inventory/api.py:1  review T1 — check me" in refused.stderr
    assert run_compass("-C", str(hooked.root), "accept").returncode == 0
    git(hooked.root, "add", "-A")
    assert commit(hooked.root).returncode == 0
    assert git(hooked.root, "show", "HEAD:src/inventory/api.py") == "TIMEOUT_S = 5\n" + api


@posix_only
def test_pre_commit_lets_through_quoted_tags_bypasses_and_review_off(hooked):
    write(hooked.root, "docs/review.md", f"Tag changes like `{AI}change T3` in comments.\n")
    git(hooked.root, "add", "-A")
    assert commit(hooked.root).returncode == 0  # a Markdown code span is documentation
    write(hooked.root, "src/a.py", f"x = 1  # {AI}change T1 — left in\n")
    git(hooked.root, "add", "-A")
    assert commit(hooked.root, "--no-verify").returncode == 0
    write(hooked.root, "src/b.py", f"y = 2  # {AI}change T1 — left in too\n")
    write(hooked.root, ".compass/config.yaml", "review:\n  enabled: false\n")
    git(hooked.root, "add", "-A")
    assert commit(hooked.root).returncode == 0


@posix_only
def test_pre_commit_runs_a_chained_hook_first(make_repo):
    root = make_repo("python_app")
    hooks = root / ".git/hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    existing = hooks / "pre-commit"
    existing.write_text("#!/bin/sh\necho team-check >&2\nexit 3\n")
    existing.chmod(0o755)
    run_compass("init", cwd=root)
    assert (hooks / "pre-commit.compass-chained").is_file()
    git(root, "add", "-A")
    failed = commit(root)
    assert failed.returncode != 0 and "team-check" in failed.stderr


def test_pre_commit_check_fails_open(make_repo, monkeypatch):
    from compass import anchors, cli

    root = make_repo("python_app")
    run_compass("init", "--no-git-hooks", cwd=root)
    monkeypatch.chdir(root)

    def broken(_root):
        raise RuntimeError("git exploded")

    monkeypatch.setattr(anchors, "staged_anchors", broken)
    assert cli.main(["check-anchors", "--staged"]) == 0
    assert "git exploded" in (Repo(root).logs_dir / "errors.log").read_text(encoding="utf-8")


def test_tag_shaped_text_in_data_files_is_left_alone(make_repo):
    # JSON cannot hold a comment, so a tag-shaped string in it is data: accept
    # must not "strip" it, and neither the manifest nor the pre-commit check counts it.
    data = f'{{"example": "{AI}change T1 — shown in the docs"}}\n'
    repo = committed_repo(make_repo)
    hook("session-start", repo.root, source="startup")
    edit(repo.root, "docs/example.json", data)
    edit(repo.root, "src/inventory/alerts.py", f"# {AI}change T1 — helper\ndef alarm():\n    pass\n")
    assert run_compass("-C", str(repo.root), "manifest").stdout == ".compass/changes/T1.md: 1 mechanical\n"
    assert run_compass("-C", str(repo.root), "accept").returncode == 0
    assert (repo.root / "docs/example.json").read_text(encoding="utf-8") == data
    run_compass("init", "--no-index", cwd=repo.root)  # installs the pre-commit hook
    git(repo.root, "add", "-A")
    assert commit(repo.root).returncode == 0


@pytest.mark.parametrize("command", [["task"], ["manifest"], ["accept", "T1"]])
def test_review_commands_need_compass_init(make_repo, command):
    root = make_repo("python_app")
    write(root, "a.py", f"x = 1  # {AI}change T1 — note\n")
    proc = run_compass("-C", str(root), *command)
    assert proc.returncode == 1 and "run `compass init` first" in proc.stderr
    assert not (root / ".compass").exists()  # and nothing starts acting in this repo
