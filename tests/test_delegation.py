"""M5 delegation (DL-01 to DL-03): the rules SessionStart hands Claude, the
output contracts SubagentStop enforces, and the scaffold agent's files through
PreToolUse, as hook contracts with recorded-style JSON (Claude Code 2.1: the
delegation tool is ``Agent``, and a subagent's tool hooks carry its
``agent_id`` and ``agent_type``).

Tags are assembled at runtime (``AI``) so this file never trips Compass's own
pre-commit check.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from compass import state
from compass.delegation import CONTRACTS, DIGEST, SCAFFOLD, TEST_RUNNER, _matches, answer_problems, named_paths
from compass.index.indexer import Indexer
from compass.repo import Repo
from conftest import bump_mtime, git, run_compass, write
from fake_llm import FakeLLM

AI = "@ai" + ":"
EVENT_NAMES = {
    "session-start": "SessionStart", "prompt": "UserPromptSubmit", "pre-edit": "PreToolUse",
    "post-edit": "PostToolUse", "delegate": "PreToolUse", "subagent-stop": "SubagentStop",
}
API = "src/inventory/api.py"
MODELS = "src/inventory/models.py"


def hook(event: str, root, session: str = "s1", **fields) -> subprocess.CompletedProcess:
    payload = {
        "session_id": session, "transcript_path": str(root / "transcript.jsonl"), "cwd": str(root),
        "hook_event_name": EVENT_NAMES[event], **fields,
    }
    return run_compass("hook", event, input=json.dumps(payload))


def subagent_stop(root, agent_type: str, message: str, agent_id: str = "a1", **fields) -> dict | None:
    fields.setdefault("stop_hook_active", False)
    proc = hook(
        "subagent-stop", root, agent_id=agent_id, agent_type=agent_type,
        agent_transcript_path=str(root / f"agent-{agent_id}.jsonl"), last_assistant_message=message, **fields,
    )
    assert (proc.returncode, proc.stderr) == (0, "")
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def delegate(root, prompt: str, subagent_type: str = SCAFFOLD, session: str = "s1") -> None:
    """PreToolUse on the Agent tool, as the main model hands work over."""
    tool_input = {"description": "mechanical edit", "prompt": prompt, "subagent_type": subagent_type}
    proc = hook("delegate", root, session, tool_name="Agent", tool_input=tool_input)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def agent_write(root, rel: str, text: str, agent_id: str = "a1", agent_type: str = SCAFFOLD) -> subprocess.CompletedProcess:
    """A subagent's Write: PreToolUse, then the write and PostToolUse when it is allowed."""
    fields = {
        "agent_id": agent_id, "agent_type": agent_type, "tool_name": "Write",
        "tool_input": {"file_path": str(root / rel), "content": text},
    }
    proc = hook("pre-edit", root, **fields)
    if proc.returncode == 0:
        bump_mtime(write(root, rel, text))
        assert hook("post-edit", root, **fields).returncode == 0
    return proc


def start_task(root) -> None:
    proc = hook("prompt", root, prompt=f"Rename get_item to fetch_item in {API}; the tests still pass")
    assert proc.returncode == 0 and "Task T1 is now active" in proc.stdout


@pytest.fixture
def repo(make_repo):
    root = make_repo("python_app")
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", "base")
    repo = Repo(root)
    Indexer(repo).build()
    return repo


# -- the contracts (DL-02) --------------------------------------------------------------


CITED = "The retry loop gives up after 5 tries (src/transport/retry.py:42).\nBackoff doubles each time (L50)."


@pytest.mark.parametrize(
    ("agent", "text", "problems"),
    [
        (DIGEST, CITED, []),
        (DIGEST, "One line needs no citation.", []),
        (DIGEST, "log line 812: the socket closed\nthen it retried twice", []),
        (DIGEST, "Two lines,\nand no citations.", ["it cites no file:line (or log line) for its claims"]),
        (DIGEST, "\n".join(f"src/a.py:{n} does a thing" for n in range(31)), ["it has 31 lines (at most 30)"]),
        (DIGEST, "See src/a.py:3\n```\n" + "x\n" * 6 + "```", ["a code block runs 6 lines (at most 5)"]),
        (DIGEST, "See src/a.py:3\n```py\n" + "x\n" * 6, ["a code block runs 6 lines (at most 5)"]),  # never closed
        (DIGEST, "See src/a.py:3\n```\n" + "x\n" * 5 + "```\n\n\n", []),
        (TEST_RUNNER, "uv run pytest: 214 passed in 12 s", []),
        (TEST_RUNNER, "\n".join(f"FAILED tests/test_x.py::test_{n}" for n in range(21)), ["it has 21 lines (at most 20)"]),
        (SCAFFOLD, "\n".join(["changed a file"] * 40), []),  # its contract is about files and tags
    ],
)
def test_answers_against_their_contracts(agent, text, problems):
    assert answer_problems(CONTRACTS[agent], text) == problems


def test_named_paths_are_the_files_a_delegation_names():
    prompt = "Task T1: in src/inventory/api.py rename get_item; also ./models.py:12 and all of src/transport/."
    assert named_paths(prompt) == ["models.py", "src/inventory/api.py", "src/transport"]


@pytest.mark.parametrize(
    ("rel", "name", "matches"),
    [(API, API, True), (API, "api.py", True), (API, "src/inventory", True), (API, "src", True),
     (API, "i.py", False), (API, "src/inv", False), (API, "inventory/api.py", True), (API, "", False)],
)
def test_a_named_file_or_directory_covers_a_path(rel, name, matches):
    assert _matches(rel, name) is matches


# -- SubagentStop (DL-02) -------------------------------------------------------------------


def test_an_answer_over_its_contract_is_sent_back_once(repo):
    long_answer = "\n".join(f"src/a.py:{n} a finding" for n in range(40))
    assert subagent_stop(repo.root, DIGEST, long_answer) == {
        "decision": "block",
        "reason": "[compass] your answer breaks the digest contract: it has 40 lines (at most 30)."
                  " Rewrite it within the contract.",
    }
    assert subagent_stop(repo.root, DIGEST, long_answer, stop_hook_active=True) is None  # the retry goes through
    failures = "\n".join(f"FAILED test_{n}" for n in range(25))
    assert "breaks the test-runner contract: it has 25 lines (at most 20)" in subagent_stop(repo.root, TEST_RUNNER, failures)["reason"]
    assert subagent_stop(repo.root, DIGEST, CITED) is None


@pytest.mark.parametrize("agent_type", ["general-purpose", "Explore", "other-plugin:digest", ""])
def test_other_subagents_are_left_alone(repo, agent_type):
    assert subagent_stop(repo.root, agent_type, "\n".join(["no citations"] * 100)) is None


@pytest.mark.parametrize("setting", ["enforce_contracts: false", "enabled: false"])
def test_contracts_can_be_switched_off(repo, setting):
    write(repo.root, ".compass/config.yaml", f"delegation:\n  {setting}\n")
    assert subagent_stop(repo.root, DIGEST, "\n".join(["no citations"] * 100)) is None
    delegate(repo.root, f"Change {API} only")
    assert agent_write(repo.root, MODELS, "x = 1\n").returncode == 0


# -- scaffold's files and tags (DL-02) ---------------------------------------------------------


def test_scaffold_changes_only_the_files_it_was_given(repo):
    start_task(repo.root)
    delegate(repo.root, f"Task T1: in {API} rename get_item to fetch_item. Change nothing else.")
    assert agent_write(repo.root, API, f"# {AI}change T1 — renamed get_item\ndef fetch_item(): ...\n").returncode == 0
    refused = agent_write(repo.root, MODELS, "x = 1\n")
    assert refused.returncode == 2
    assert refused.stderr == (
        "[compass] The scaffold contract: change only the files your instructions or the task's spec name"
        f" ({API}); {MODELS} is not one of them. Report back instead, and name the file if it should change.\n"
    )
    # The main model itself, and other subagents, are not held to scaffold's list.
    assert hook("pre-edit", repo.root, tool_name="Edit", tool_input={"file_path": str(repo.root / MODELS)}).returncode == 0
    assert agent_write(repo.root, MODELS, "x = 1\n", agent_id="g1", agent_type="general-purpose").returncode == 0


def test_the_tasks_spec_names_files_too(repo):
    start_task(repo.root)
    write(repo.root, ".compass/specs/T1.md", f"# T1\n\nScope: {API} and {MODELS}.\n")
    delegate(repo.root, f"Task T1: apply the spec's plan to {API}.")
    assert agent_write(repo.root, MODELS, f"# {AI}change T1 — per the spec\n").returncode == 0
    assert agent_write(repo.root, "src/inventory/__init__.py", "").returncode == 2


def test_parallel_scaffolds_each_find_their_own_delegation(repo):
    start_task(repo.root)
    delegate(repo.root, f"Task T1: add a docstring to {API}.")
    delegate(repo.root, f"Task T1: add a docstring to {MODELS}.")
    # The second agent starts editing first.
    assert agent_write(repo.root, MODELS, '"""Models."""\n', agent_id="a2").returncode == 0
    assert agent_write(repo.root, API, '"""API."""\n', agent_id="a1").returncode == 0
    assert agent_write(repo.root, API, '"""API."""\n', agent_id="a2").returncode == 2
    assert agent_write(repo.root, MODELS, '"""Models."""\n', agent_id="a1").returncode == 2
    assert state.read(Repo(repo.root))["pending"] == {}


def test_without_a_recorded_delegation_nothing_is_refused(repo):
    # The Agent hook did not run (an older Claude Code, or it failed): fail open.
    assert agent_write(repo.root, MODELS, "x = 1\n").returncode == 0
    delegate(repo.root, "Task T1: do something", subagent_type="compass:digest")  # not a scaffold delegation
    assert state.read(Repo(repo.root))["pending"] == {}


def test_every_scaffold_change_carries_a_tag(repo):
    start_task(repo.root)
    delegate(repo.root, f"Task T1: in {API} and {MODELS}, rename get_item to fetch_item.")
    agent_write(repo.root, API, f"def fetch_item(): ...  # {AI}change T1 — renamed\n")
    agent_write(repo.root, MODELS, "def fetch_item(): ...\n")
    answer = subagent_stop(repo.root, SCAFFOLD, f"Renamed get_item in {API} and {MODELS}.")
    assert answer == {
        "decision": "block",
        "reason": f"[compass] every change you make carries a tag: add a {AI}change T1 — <note> comment, in each"
                  f" file's own syntax, to {MODELS}.",
    }
    agent_write(repo.root, MODELS, f"def fetch_item(): ...  # {AI}change T1 — renamed\n")
    assert subagent_stop(repo.root, SCAFFOLD, "Renamed get_item in both files.") is None
    # Its edits are the task's too: the manifest and the Stop hook see them.
    assert {API, MODELS} <= set(state.touched(state.read(Repo(repo.root)), "T1"))


def test_tags_are_not_asked_for_with_review_off(repo):
    write(repo.root, ".compass/config.yaml", "review:\n  enabled: false\n")
    delegate(repo.root, f"Change {MODELS}.")
    agent_write(repo.root, MODELS, "x = 1\n")
    assert subagent_stop(repo.root, SCAFFOLD, "Changed models.py.") is None
    current = state.read(Repo(repo.root))
    assert current["agents"]["a1"]["touched"] == [MODELS] and current["tasks"] == {}  # no task was started


def test_the_delegation_hooks_fail_open(repo):
    (repo.compass_dir / "state.json").write_text("{broken", encoding="utf-8")
    for event, fields in (
        ("delegate", {"tool_name": "Agent", "tool_input": {"subagent_type": SCAFFOLD, "prompt": f"edit {API}"}}),
        ("pre-edit", {"agent_id": "a1", "agent_type": SCAFFOLD, "tool_name": "Write", "tool_input": {"file_path": API}}),
        ("subagent-stop", {"agent_id": "a1", "agent_type": SCAFFOLD, "last_assistant_message": "done"}),
        ("subagent-stop", {"agent_type": DIGEST}),  # no answer at all
        ("delegate", {"tool_name": "Agent", "tool_input": "not a mapping"}),
    ):
        proc = hook(event, repo.root, **fields)
        assert proc.returncode == 0, (event, proc.stderr)


def test_state_keeps_only_well_formed_agent_records(repo):
    raw = {
        "agents": {"a1": {"type": SCAFFOLD, "touched": [API, 3], "allowed": "all", "seen": "x"}, "a2": "junk"},
        "pending": {"s1": [{"paths": [API, None], "t": 5}, "junk"], "s2": "junk"},
    }
    (repo.compass_dir / "state.json").write_text(json.dumps(raw), encoding="utf-8")
    current = state.read(Repo(repo.root))
    assert current["agents"] == {"a1": {"type": SCAFFOLD, "session": None, "touched": [API], "allowed": None, "seen": 0}}
    assert current["pending"] == {"s1": [{"paths": [API], "t": 5}]}


# -- the rules (DL-03) -------------------------------------------------------------------------


def test_session_start_hands_claude_the_delegation_rules(repo):
    out = hook("session-start", repo.root, source="startup").stdout
    assert f"    {DIGEST}: to read more than about 500 lines" in out
    assert f"    {TEST_RUNNER}: run test suites and builds through it, not Bash" in out
    assert f"    {SCAFFOLD}: for mechanical edits you can spell out; name every file it may change" in out
    assert "Keep small work (under about 50 lines) and anything that needs judgment in this conversation" in out
    assert "summarize_file" not in out  # no local model configured
    write(repo.root, ".compass/config.yaml", "delegation:\n  digest_threshold_lines: 800\n")
    assert "to read more than about 800 lines" in hook("session-start", repo.root, source="startup").stdout
    write(repo.root, ".compass/config.yaml", "delegation:\n  enabled: false\n")
    assert DIGEST not in hook("session-start", repo.root, source="startup").stdout


def test_session_start_offers_the_local_tools_only_when_a_model_answers(repo):
    fake = FakeLLM().start()
    try:
        write(repo.root, ".compass/config.yaml", fake.config())
        assert "The local-model tools summarize_file and classify_files" in hook("session-start", repo.root).stdout
    finally:
        fake.stop()
    (repo.compass_dir / "llm.json").unlink()  # the cached answer would last a few minutes
    assert "summarize_file" not in hook("session-start", repo.root).stdout
