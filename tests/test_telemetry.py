"""M6 telemetry (TM-01, TM-02): transcripts read into rows, and the Stop,
SubagentStop and SessionStart hook contracts that write them."""

from __future__ import annotations

import json
import subprocess
import threading
import time

import pytest

from compass import telemetry
from compass.config import parse_config
from compass.repo import Repo
from conftest import run_compass, write
from transcripts import HAIKU, MAIN, Transcript, subagent

BASELINE = "".join(
    f"{name}:\n  enabled: false\n"
    for name in ("query", "prompt_gate", "context_pack", "spec_gate", "review", "delegation")
)


def hook(event: str, repo: Repo, session: str = "s1", **fields) -> subprocess.CompletedProcess:
    names = {"stop": "Stop", "subagent-stop": "SubagentStop", "session-start": "SessionStart", "prompt": "UserPromptSubmit"}
    payload = {"session_id": session, "cwd": str(repo.root), "hook_event_name": names[event], **fields}
    return run_compass("hook", event, input=json.dumps(payload))


def stop(repo: Repo, transcript: Transcript, session: str = "s1") -> subprocess.CompletedProcess:
    transcript.write()
    proc = hook("stop", repo, session, transcript_path=str(transcript.path), stop_hook_active=False)
    assert proc.returncode == 0, proc.stderr
    return proc


def rows(repo: Repo) -> list[dict]:
    path = repo.compass_dir / "telemetry.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.fixture
def repo(make_repo):
    return Repo(make_repo(files={".compass/config.yaml": "", "src/retry.py": "def retry():\n    pass\n"}))


@pytest.fixture
def transcript(tmp_path):
    return Transcript(tmp_path / "claude" / "s1.jsonl")


# -- reading a transcript -----------------------------------------------------------------------


def test_each_message_counts_once_at_its_final_usage(transcript):
    transcript.prompt(0).assistant(2, output=300, tools=("Read", "Grep")).tool_result(3).tool_result(4)
    transcript.assistant(5, output=120, cache_read=5000, cache_creation=0).stop(6)
    s = telemetry.summarize(transcript.lines)
    # Two messages: the thinking lines' partial output (30, 12) never count, nor do repeats.
    assert s.main == {MAIN: {"input": 6, "output": 420, "cache_creation": 100, "cache_read": 6000}}
    assert s.tools == {"Read": 1, "Grep": 1} and s.prompts == 1 and s.claude_code == "2.1.281"


def test_tools_are_counted_by_name_and_compass_tools_by_their_own():
    lines = Transcript(None).assistant(1, output=10, tools=(
        "mcp__compass__find_symbol", "mcp__plugin_compass_compass__read_symbol", "mcp__claude_ai_Docs__read",
        "Agent", "Bash",
    )).lines
    assert telemetry.summarize(lines).tools == {
        "compass:find_symbol": 1, "compass:read_symbol": 1, "mcp": 1, "Agent": 1, "Bash": 1,
    }


def test_only_prompts_the_developer_typed_count(transcript):
    transcript.prompt(0).assistant(1, output=10).tool_result(2)
    transcript.hook_feedback(3, "[compass] Changed this turn without a T1 anchor: src/retry.py.")
    transcript.raw({"type": "user", "timestamp": "2026-09-24T02:00:04.000Z", "isCompactSummary": True,
                    "message": {"content": "This session is being continued from a previous conversation"}})
    transcript.prompt(5, "[Request interrupted by user]").prompt(6, "<task-notification> done")
    transcript.raw({"type": "user", "timestamp": "2026-09-24T02:00:07.000Z",
                    "message": {"content": [{"type": "text", "text": "and also the timeout"}]}})
    assert telemetry.summarize(transcript.lines).prompts == 2


def test_active_time_leaves_out_the_developers_wait(transcript):
    transcript.prompt(0).assistant(10, output=10).stop(11)
    transcript.queued(290).prompt(300).assistant(320, output=10).stop(321)  # typed after five minutes
    s = telemetry.summarize(transcript.lines)
    assert s.active_s == pytest.approx(11 + 21)  # 0-11 and 300-321; the queued line stretches nothing
    assert s.prompts == 2


def test_work_after_a_hook_sent_claude_back_counts_from_the_feedback(transcript):
    transcript.hook_feedback(100, "[compass] tag the change").assistant(104, output=10).stop(106)
    s = telemetry.summarize(transcript.lines)
    assert s.active_s == pytest.approx(6.0) and s.prompts == 0
    assert s.injected_chars == len("Stop hook feedback:\n[compass] tag the change")


def test_context_compass_injected_is_measured(transcript):
    transcript.session_start_context(0, "[compass] Compass is active in this repository.")
    transcript.prompt(1).prompt_context(1, "[compass] Task T1 is now active", "from another plugin")
    assert telemetry.summarize(transcript.lines).injected_chars == len(
        "[compass] Compass is active in this repository.") + len("[compass] Task T1 is now active")


def test_sidechain_lines_count_as_delegated_and_synthetic_messages_not_at_all(transcript):
    transcript.prompt(0).assistant(1, output=10)
    transcript.raw({"type": "assistant", "isSidechain": True, "timestamp": "2026-09-24T02:00:02.000Z",
                    "message": {"id": "side", "model": HAIKU, "usage": {"input_tokens": 5, "output_tokens": 7}}})
    transcript.raw({"type": "assistant", "timestamp": "2026-09-24T02:00:03.000Z",
                    "message": {"id": "err", "model": "<synthetic>", "usage": {"output_tokens": 0}}})
    s = telemetry.summarize(transcript.lines)
    assert set(s.main) == {MAIN} and s.delegated == {HAIKU: {"input": 5, "output": 7, "cache_creation": 0, "cache_read": 0}}


def test_reads_leave_a_half_written_line_for_later(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b'{"a": 1}\n{"b": 2}\n{"c": ')
    lines, offset = telemetry.read_from(path, 0)
    assert lines == ['{"a": 1}', '{"b": 2}'] and offset == len(b'{"a": 1}\n{"b": 2}\n')
    with open(path, "ab") as handle:
        handle.write(b'3}\n')
    assert telemetry.read_from(path, offset) == (['{"c": 3}'], path.stat().st_size)
    path.write_bytes(b'{"new": 1}\n')  # replaced by a shorter file: start again
    assert telemetry.read_from(path, offset)[0] == ['{"new": 1}']


def test_a_hook_waits_for_the_transcript_to_catch_up(transcript):
    # Claude Code writes the transcript asynchronously: the turn's last message can land
    # on disk a little after the Stop hook starts.
    transcript.prompt(0).assistant(1, output=100, tools=("Read",)).tool_result(2).write()
    lines, _ = telemetry.read_settled(transcript.path, 0, wait=0.2)  # gives up, takes what is there
    assert len(lines) == 4

    def finish():
        time.sleep(0.3)
        transcript.assistant(3, output=40).write()

    threading.Thread(target=finish).start()
    lines, _ = telemetry.read_settled(transcript.path, 0, wait=5)
    assert telemetry.summarize(lines).main[MAIN]["output"] == 140


def test_a_resumed_session_starts_after_its_history(transcript):
    transcript.prompt(0).assistant(1, output=10).stop(2).write()
    history = transcript.path.stat().st_size
    transcript.queued(50).prompt(50, "carry on").write()  # the resumed prompt may already be on disk
    assert telemetry.resume_offset(transcript.path) == history


def test_task_tags_come_from_the_brief():
    assert telemetry.task_tags("Goal: fix it. Scope: src/. Category: Bug fix. Size: m") == ("bug_fix", "M")
    assert telemetry.task_tags("Category: cross-module refactor Size: Large") == ("refactor", "L")
    assert telemetry.task_tags("Category: Triage failing tests or logs") == ("triage", None)
    assert telemetry.task_tags("Category: docs, Size: huge") == ("docs", None)
    assert telemetry.task_tags("fix the retry loop") == (None, None)


def test_modules_and_the_compass_flag():
    assert telemetry.modules_on(parse_config("")) == [
        "query", "prompt_gate", "context_pack", "spec_gate", "review", "delegation",
    ]
    assert telemetry.modules_on(parse_config(BASELINE)) == []
    assert telemetry.modules_on(parse_config(BASELINE + "local_llm:\n  enabled: true\n")) == ["local_llm"]


# -- the hooks ---------------------------------------------------------------------------------------


def test_every_stop_appends_the_turn_since_the_last_one(repo, transcript):
    transcript.session_start_context(0, "[compass] Compass is active in this repository.")
    transcript.prompt(1, "Fix the retry loop in src/retry.py; a secret prompt").assistant(3, output=200, tools=("Read",))
    transcript.tool_result(4).assistant(5, output=20)  # a turn ends with a message that ends it
    stop(repo, transcript)
    (row,) = rows(repo)
    assert {k: row[k] for k in ("v", "kind", "session", "task", "compass", "prompts", "claude_code")} == {
        "v": 1, "kind": "turn", "session": "s1", "task": None, "compass": True, "prompts": 1, "claude_code": "2.1.281",
    }
    assert row["main"] == {MAIN: {"input": 6, "output": 220, "cache_creation": 200, "cache_read": 2000}}
    assert row["tools"] == {"Read": 1} and row["active_s"] == pytest.approx(4.5)
    assert row["injected_chars"] == len("[compass] Compass is active in this repository.")
    assert "secret" not in (repo.compass_dir / "telemetry.jsonl").read_text(encoding="utf-8")  # counts, never prompts

    stop(repo, transcript.stop(6))  # nothing new happened: no row
    assert len(rows(repo)) == 1
    transcript.prompt(60).assistant(61, output=50)
    stop(repo, transcript)
    assert rows(repo)[1]["main"][MAIN]["output"] == 50 and len(rows(repo)) == 2


def test_rows_carry_the_task_and_its_tags(repo, transcript):
    brief = "Goal: retry timeouts. Scope: src/retry.py. Accept when: a timeout is retried. Category: bug fix Size: S"
    run = run_compass("-C", str(repo.root), "task", "new", "--brief", "-", input=brief)
    assert run.returncode == 0, run.stderr
    stop(repo, transcript.prompt(0).assistant(1, output=10))
    row = rows(repo)[0]
    assert (row["task"], row["category"], row["size"], row["large"]) == ("T1", "bug_fix", "S", False)


def test_a_subagent_is_the_parent_tasks_delegated_work(repo, transcript):
    agent = subagent(transcript.path, "a1", "compass:test-runner")
    agent.prompt(0, "Run the tests").assistant(2, output=80, model=HAIKU, tools=("Bash",)).assistant(5, output=40, model=HAIKU)
    agent.write()
    payload = {"agent_id": "a1", "agent_type": "compass:test-runner", "agent_transcript_path": str(agent.path),
               "stop_hook_active": False, "last_assistant_message": "All 12 passed."}
    assert hook("subagent-stop", repo, **payload).returncode == 0
    (row,) = rows(repo)
    assert (row["kind"], row["agent"], row["main"], row["tools"]) == ("subagent", "compass:test-runner", {}, {"Bash": 1})
    assert row["delegated"] == {HAIKU: {"input": 6, "output": 120, "cache_creation": 200, "cache_read": 2000}}
    assert row["active_s"] == pytest.approx(5.5)
    hook("subagent-stop", repo, **payload)  # sent back and stopping again: only new lines count
    assert len(rows(repo)) == 1


def test_a_resumed_session_does_not_count_its_history_again(repo, transcript):
    transcript.prompt(0).assistant(1, output=999).stop(2).write()  # counted before, or before Compass
    proc = hook("session-start", repo, source="resume", transcript_path=str(transcript.path))
    assert proc.returncode == 0
    stop(repo, transcript.prompt(100, "carry on").assistant(101, output=7))
    (row,) = rows(repo)
    assert row["main"][MAIN]["output"] == 7 and row["prompts"] == 1


def test_a_telemetry_only_baseline(repo, transcript):
    # The pilot's first weeks: every module off but telemetry, so Claude gets nothing extra.
    write(repo.root, ".compass/config.yaml", BASELINE)
    assert hook("session-start", repo, source="startup", transcript_path=str(transcript.path)).stdout == ""
    stop(repo, transcript.prompt(0).assistant(1, output=10))
    (row,) = rows(repo)
    assert row["compass"] is False and row["modules"] == []


def test_telemetry_can_be_off_or_exported(repo, transcript):
    write(repo.root, ".compass/config.yaml", "telemetry:\n  enabled: false\n")
    stop(repo, transcript.prompt(0).assistant(1, output=10))
    assert rows(repo) == [] and not (repo.compass_dir / telemetry.OFFSETS_NAME).exists()
    write(repo.root, ".compass/config.yaml", "telemetry:\n  export: shared/pilot.jsonl\n")
    stop(repo, transcript.prompt(5).assistant(6, output=20))
    exported = (repo.root / "shared/pilot.jsonl").read_text(encoding="utf-8")
    assert exported == (repo.compass_dir / "telemetry.jsonl").read_text(encoding="utf-8") and exported.count("\n") == 1


def test_telemetry_fails_open(repo, transcript):
    (repo.compass_dir / telemetry.OFFSETS_NAME).write_text("{broken", encoding="utf-8")
    stop(repo, transcript.prompt(0).assistant(1, output=10))
    assert len(rows(repo)) == 1  # a broken offsets file reads as empty
    proc = hook("stop", repo, transcript_path=str(transcript.path.parent / "gone.jsonl"))
    assert (proc.returncode, proc.stdout) == (0, "")
    write(repo.root, ".compass/config.yaml", "telemetry:\n  export: /dev/null/not-a-folder/x.jsonl\n")
    stop(repo, transcript.prompt(5).assistant(6, output=20))  # an unwritable export only logs
    assert len(rows(repo)) == 2
