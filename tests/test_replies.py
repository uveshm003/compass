"""Plain replies instead of commands (UX-04 to UX-06): "approve" while a plan
waits, "accept" once a change is reviewed, and a reminder when the developer
asks for a commit while review tags remain. Tags are assembled at runtime."""

from __future__ import annotations

import json

import pytest

from compass import spec, state
from compass.gate.replies import Reply, asks_to_commit, match
from test_review import AI, committed_repo, edit, hook

# -- the matcher ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "reply"),
    [
        ("approve", Reply("approve", None, False)),
        ("Approved.", Reply("approve", None, False)),
        ("ok, approve the plan", Reply("approve", None, False)),
        ("yes approve T3", Reply("approve", "T3", False)),
        ("looks good, approve, go ahead", Reply("approve", None, False)),
        ("accept", Reply("accept", None, False)),
        ("accept t2", Reply("accept", "T2", False)),
        ("I have reviewed it, accept and commit", Reply("accept", None, True)),
        ("reviewed, accepted, thanks", Reply("accept", None, False)),
        ("accept the changes", Reply("accept", None, False)),
    ],
)
def test_short_replies_stand_for_the_command(text, reply):
    assert match(text) == reply


@pytest.mark.parametrize(
    "text",
    [
        "do not approve",
        "approve?",
        "why did you approve that",
        "accept this but rename foo first",
        "don't accept yet",
        "approve the plan and also add a test for the parser module please",  # a new request rides along
        "accepting files in the upload form should validate size",
        "the approve button is broken",
    ],
)
def test_sentences_that_merely_mention_the_word_do_not(text):
    assert match(text) is None


def test_commit_requests():
    assert asks_to_commit("commit the changes with a good message")
    assert asks_to_commit("ok, commit it")
    assert not asks_to_commit("don't commit yet")
    assert not asks_to_commit("what did the last commit change?")


# -- the hook ------------------------------------------------------------------------------


def prompt(repo, text: str, session: str = "s1") -> tuple[str, str]:
    proc = hook("prompt", repo.root, session, prompt=text)
    assert (proc.returncode, proc.stderr) == (0, "")
    data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return data.get("hookSpecificOutput", {}).get("additionalContext", ""), data.get("systemMessage", "")


@pytest.fixture
def repo(make_repo):
    return committed_repo(make_repo)


def test_replying_approve_approves_the_waiting_plan(repo):
    hook("session-start", repo.root, source="startup")
    prompt(repo, "Refactor src/inventory so the api and alerts share one validator")
    assert state.needs_approval(state.read(repo)) == "T1"
    context, message = prompt(repo, "looks good, approve")
    assert message.startswith("[compass] Approved T1's spec (.compass/specs/T1.md) as ")
    assert "Go ahead and implement the plan in .compass/specs/T1.md" in context
    assert state.read(repo)["tasks"]["T1"]["approved"]["by"]
    assert spec.front_matter(spec.spec_path(repo, "T1").read_text(encoding="utf-8"))["status"] == "approved"


def test_approve_with_nothing_waiting_is_an_ordinary_prompt(repo):
    hook("session-start", repo.root, source="startup")
    context, message = prompt(repo, "approve")
    assert "Approved" not in message and "approved" not in context
    assert not state.read(repo)["tasks"].get("T1", {}).get("approved")


def test_replying_accept_strips_the_tags_and_can_commit(repo):
    hook("session-start", repo.root, source="startup")
    prompt(repo, "add a docstring to the api module")
    api = (repo.root / "src/inventory/api.py").read_text(encoding="utf-8")
    edit(repo.root, "src/inventory/api.py", f"# {AI}review T1 — routes are versioned\n" + api)
    context, message = prompt(repo, "reviewed it, accept and commit")
    assert message == ("[compass] Accepted T1: removed 1 review tag from 1 file;"
                       " the notes are kept in .compass/changes/archive/T1.md.")
    assert "stage and commit the changes now" in context
    assert (repo.root / "src/inventory/api.py").read_text(encoding="utf-8") == api
    assert state.read(repo)["accepted"] == ["T1"]


def test_accept_with_nothing_to_accept_is_an_ordinary_prompt(repo):
    hook("session-start", repo.root, source="startup")
    context, message = prompt(repo, "accept")
    assert "Accepted" not in message and state.read(repo)["accepted"] == []


def test_asking_for_a_commit_while_tags_remain_gets_a_reminder(repo):
    hook("session-start", repo.root, source="startup")
    prompt(repo, "add a docstring to the api module")
    api = (repo.root / "src/inventory/api.py").read_text(encoding="utf-8")
    edit(repo.root, "src/inventory/api.py", f"# {AI}review T1 — routes are versioned\n" + api)
    context, _ = prompt(repo, "commit this please")
    assert "git refuses a commit that adds them" in context and 'reply "accept"' in context
    assert "never remove the tags yourself" in context.lower()


def test_replies_do_nothing_with_review_off(repo):
    (repo.compass_dir / "config.yaml").write_text("review:\n  enabled: false\n", encoding="utf-8")
    hook("session-start", repo.root, source="startup")
    edit(repo.root, "src/inventory/api.py", f"# {AI}review T1 — x\n")
    _, message = prompt(repo, "accept")
    assert "Accepted" not in message


# -- /compass:status (UX-07) ----------------------------------------------------------------


def test_status_says_what_waits_and_what_to_reply(repo, make_repo):
    from conftest import run_compass

    hook("session-start", repo.root, source="startup")
    prompt(repo, "Refactor src/inventory so the api and alerts share one validator")
    out = run_compass("status", cwd=repo.root).stdout
    assert out.startswith("Compass is on in ") and "Task T1: Refactor src/inventory" in out
    assert 'Plan waiting for you: .compass/specs/T1.md. Reply "approve"' in out
    prompt(repo, "approve")
    edit(repo.root, "src/inventory/api.py", f"# {AI}review T1 — x\n")
    out = run_compass("status", cwd=repo.root).stdout
    assert "1 file changed, 1 review note: .compass/changes/T1.md" in out and '"accept and commit"' in out
    bare = make_repo()
    assert "isn't set up in this repository" in run_compass("status", cwd=bare).stdout
