"""M4: the prompt gate (PG-01 to PG-05), the context pack (CP-01 to CP-03)
and the spec gate (SG-01 to SG-05), from the rules up to the hook contracts."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from compass import spec, state
from compass.config import default_config, parse_config
from compass.gate import checklist, missing_fields, parse
from compass.gate.pack import build, resolve, stack_mentions
from compass.index.indexer import Indexer
from compass.index.store import Store
from compass.repo import Repo
from conftest import git, run_compass, write

EVENTS = {"prompt": "UserPromptSubmit", "pre-edit": "PreToolUse", "session-start": "SessionStart"}


def hook(event: str, root, session: str = "s1", **fields) -> subprocess.CompletedProcess:
    payload = {"session_id": session, "cwd": str(root), "hook_event_name": EVENTS[event], **fields}
    return run_compass("hook", event, input=json.dumps(payload))


def answer(proc: subprocess.CompletedProcess) -> tuple[str, str]:
    """(context for Claude, message for the developer) from a prompt hook."""
    assert (proc.returncode, proc.stderr) == (0, "")
    data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return data.get("hookSpecificOutput", {}).get("additionalContext", ""), data.get("systemMessage", "")


def pre_edit(root, path, session: str = "s1") -> subprocess.CompletedProcess:
    return hook("pre-edit", root, session, tool_name="Edit", tool_input={"file_path": str(path)})


def gate_log(repo: Repo) -> list[dict]:
    path = repo.logs_dir / "gate.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.fixture
def repo(make_repo):
    root = make_repo("ts_app")
    git(root, "add", "-A")
    git(root, "commit", "-q", "--no-verify", "-m", "base")
    repo = Repo(root)
    Indexer(repo).build()
    return repo


# -- parsing and kinds ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("fix it", "task"),
        ("Can you add retry to the HTTP client?", "task"),  # a polite request, not a question
        ("please rename parse_config to load_config", "task"),
        ("Goal: cache lookups", "task"),
        ("The login page breaks when the session expires", "task"),
        ("Where is retry handled and what calls it?", "question"),
        ("explain how `ReconnectPolicy.next` computes jitter", "question"),
        ("does this still pass on Windows", "question"),
        ("yes", "reply"),
        ("go ahead", "reply"),
        ("looks good, thanks", "reply"),
        ("/compass:task Goal: x", "command"),
        ("!quick bump the version", "bypass"),
        ("   ", "empty"),
    ],
)
def test_prompt_kinds(text, kind):
    assert parse(text).kind == kind


def test_candidates_are_code_names_not_words():
    parsed = parse(
        "Make `withRetry` in src/transport/reconnect.ts honour ReconnectPolicy.next and MAX_DELAY; "
        "call reset() and see https://example.com/docs and version 1.2.3 of the README.md"
    )
    assert [(c.text, c.kind) for c in parsed.candidates] == [
        ("withRetry", "symbol"), ("src/transport/reconnect.ts", "path"), ("ReconnectPolicy.next", "symbol"),
        ("MAX_DELAY", "symbol"), ("reset", "symbol"), ("README.md", "path"),
    ]


def test_labels_inline_and_on_their_own_lines():
    parsed = parse("Goal: cache get_item. Scope: src/api.py\nNon-goals: eviction\nAccept when: one DB hit; Constraints: no new deps")
    assert parsed.labels == {
        "goal": "cache get_item", "scope": "src/api.py", "non_goals": "eviction", "acceptance": "one DB hit",
        "constraints": "no new deps",
    }
    assert parse("Done when: tests pass").labels == {"acceptance": "tests pass"}


# -- the rules (PG-01) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "missing"),
    [
        ("fix it", ["scope", "acceptance"]),
        ("improve performance", ["scope", "acceptance"]),
        ("clean up the code", ["scope", "acceptance"]),
        ("The login page breaks when the session expires", ["goal", "scope"]),
        ("Add remove() to StockItem so that negative amounts raise ValueError", []),
        ("Make withRetry give up after 5 attempts and rethrow the last error", []),
        ("rename parse_config to load_config everywhere", []),  # the end state is in the request
        ("delete src/legacy/util.js", []),
        ("Goal: speed up startup. Scope: `cli.py`. Accept when: `compass --help` runs in under 50 ms", []),
    ],
)
def test_missing_fields(text, missing):
    assert missing_fields(parse(text), default_config()) == missing


def test_required_fields_come_from_config():
    config = parse_config("prompt_gate:\n  required_fields: [goal, constraints]\n")
    assert missing_fields(parse("add retries to `fetch`"), config) == ["constraints"]
    assert missing_fields(parse("add retries to `fetch` without new dependencies"), config) == []


def test_a_new_rule_is_a_module_in_gate_rules(tmp_path, monkeypatch):
    import compass.gate.rules as rules

    (tmp_path / "ticket.py").write_text(
        'FIELD = "ticket"\n\ndef check(prompt, config):\n    return [] if "JIRA-" in prompt.text else [FIELD]\n'
    )
    monkeypatch.setattr(rules, "__path__", [*rules.__path__, str(tmp_path)])
    config = parse_config("prompt_gate:\n  required_fields: [goal, ticket]\n")
    assert missing_fields(parse("fix the crash"), config) == ["ticket"]
    assert missing_fields(parse("fix the crash in JIRA-12"), config) == []


def test_checklist_names_the_fields_and_the_template():
    text = checklist(["scope", "acceptance"])
    assert text.startswith("[compass] This prompt does not state its scope and accept when.")
    assert "/compass:task Goal:" in text and "!quick" in text


# -- sizing (SG-01) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "size", "reason"),
    [
        ("refactoring the transport layer", "large", 'keyword "refactor"'),
        ("add a new module for alerts", "large", 'keyword "new module"'),
        ("touch a.ts, b.ts and src/c.ts", "large", "3 files mentioned"),
        ("fix the typo in README.md", "small", ""),
    ],
)
def test_size_classification(text, size, reason):
    assert spec.classify(parse(text), default_config()) == (size, reason)


# -- the context pack (CP-01 to CP-03) ------------------------------------------------------


def pack_for(repo: Repo, text: str, budget: int = 1500, stack=None) -> str:
    parsed = parse(text)
    with Store.open(repo.db_path) as store:
        resolve(store, parsed)
        parsed.stack = stack_mentions(stack, parsed)
        return build(store, parsed, budget, stack)


def test_the_pack_resolves_symbols_files_and_directories(repo):
    text = pack_for(repo, "Make `withRetri` honour ReconnectPolicy.next; see src/transport/socket.ts and src/components")
    assert text.startswith("[compass] From the code map")
    assert "- `ReconnectPolicy.next`: src/transport/reconnect.ts:10-13  method ReconnectPolicy.next(attempt: number): number" in text
    assert "- src/transport/socket.ts (typescript," in text
    assert "- src/components/: Button.tsx" in text
    assert "Tests: src/transport/reconnect.test.ts (for src/transport/reconnect.ts)" in text
    assert "Not in the code map: `withRetri` (did you mean withRetry?)" in text


def test_the_pack_is_silent_about_names_that_are_not_the_projects(repo):
    assert pack_for(repo, "throw a ValueError from JSONDecoder like React does") == ""


def test_the_pack_keeps_to_its_budget(repo):
    text = pack_for(repo, "see src/transport/reconnect.ts and src/transport/socket.ts and ReconnectPolicy", budget=60)
    assert len(text) <= 60 * 3 + 120 and "left out to stay within the pack's budget" in text


def test_the_pack_names_stack_versions(repo):
    stack = {"entries": [{"stack": "node", "frameworks": {"react": "18.3.1"}, "tools": {"vitest": "2.1.5"}}]}
    assert "Stack versions in use: react 18.3.1, vitest 2.1.5" in pack_for(repo, "upgrade React and vitest", stack=stack)


# -- specs (SG-02, SG-03, SG-05) -------------------------------------------------------------


def test_a_spec_draft_starts_from_the_brief(repo):
    parsed = parse("Goal: split reconnect.ts. Scope: src/transport/. Accept when: tests pass")
    path = spec.create(repo, "T3", parsed, 'keyword "refactor"')
    text = path.read_text(encoding="utf-8")
    assert spec.front_matter(text)["status"] == "draft"
    assert "# T3: split reconnect.ts" in text and "## Open questions" in text
    assert "\n## Scope\n\nsrc/transport/\n" in text and "\n## Acceptance\n\ntests pass\n" in text
    assert spec.open_questions(text) == []  # the empty checkbox is a placeholder, not a question
    path.write_text(text.replace("- [ ]", "- [ ] Keep the old export?\n- [x] Node 20 only? Yes"), encoding="utf-8")
    assert spec.open_questions(path.read_text(encoding="utf-8")) == ["Keep the old export?"]
    assert spec.create(repo, "T3", parse("another brief"), "") == path  # never overwritten


def test_approve_records_who_and_when(repo):
    spec.create(repo, "T3", parse("refactor it"), 'keyword "refactor"')
    result = spec.approve(repo, "T3", "Dana")
    meta = spec.front_matter(spec.spec_path(repo, "T3").read_text(encoding="utf-8"))
    assert (meta["status"], meta["approved_by"]) == ("approved", "Dana") and meta["approved_at"] == result["at"]


# -- the prompt hook (PG-02 to PG-04, CP-02) -------------------------------------------------


def test_warn_mode_asks_before_assuming(repo):
    hook("session-start", repo.root, source="startup")
    context, message = answer(hook("prompt", repo.root, prompt="fix it"))
    assert "does not state its scope and accept when" in context and "ask one short question" in context
    assert message.startswith("[compass] The request does not state its scope and accept when, so Claude will ask.")
    assert state.read(repo)["tasks"]["T1"]["brief"] == "fix it"
    # The answer to Claude's question is a follow-up, not a new request: no nagging.
    context, message = answer(hook("prompt", repo.root, prompt="the crash is in the reconnect loop on Windows"))
    assert (context, message) == ("", "")
    assert [row["outcome"] for row in gate_log(repo)] == ["warn", "pass"]
    assert gate_log(repo)[0]["excerpt"] == "fix it" and "excerpt" not in gate_log(repo)[1]


def test_block_mode_refuses_the_prompt_with_the_checklist(repo):
    write(repo.root, ".compass/config.yaml", "prompt_gate:\n  strictness: block\n")
    proc = hook("prompt", repo.root, prompt="improve performance")
    assert proc.returncode == 2 and proc.stdout == ""
    assert proc.stderr.startswith("[compass] This prompt does not state its scope and accept when.")
    assert state.is_fresh(state.read(repo), state.active_task(state.read(repo)))  # still waiting for a real request
    ok = hook("prompt", repo.root, prompt="Make withRetry in src/transport/reconnect.ts give up after 5 attempts")
    assert ok.returncode == 0 and "withRetry" in answer(ok)[0]


def test_off_mode_and_non_tasks_are_never_checked(repo):
    write(repo.root, ".compass/config.yaml", "prompt_gate:\n  strictness: off\n")
    assert answer(hook("prompt", repo.root, prompt="fix it"))[1] == ""
    write(repo.root, ".compass/config.yaml", "prompt_gate:\n  strictness: block\n")
    for text in ("where does this break?", "yes", "go ahead", "/compass:accept"):
        assert hook("prompt", repo.root, session="s2", prompt=text).returncode == 0, text


def test_quick_skips_the_check_and_is_logged_for_tuning(repo):
    write(repo.root, ".compass/config.yaml", "prompt_gate:\n  strictness: block\n")
    proc = hook("prompt", repo.root, prompt="!quick fix it")
    assert (proc.returncode, proc.stderr) == (0, "")
    [row] = gate_log(repo)
    assert (row["kind"], row["outcome"], row["missing"], row["excerpt"]) == (
        "bypass", "bypass", ["scope", "acceptance"], "!quick fix it",
    )


def test_the_pack_rides_along_on_questions(repo):
    context, _ = answer(hook("prompt", repo.root, prompt="where is withRetry used?"))
    assert "- `withRetry`: src/transport/reconnect.ts:24-32  fn withRetry" in context


# -- the spec gate end to end (SG-01 to SG-05) ------------------------------------------------


def test_a_large_task_edits_nothing_but_its_spec_until_approved(repo):
    hook("session-start", repo.root, source="startup")
    context, message = answer(hook("prompt", repo.root, prompt="Refactor src/transport so reconnect and socket share one backoff"))
    assert "Task T1 is large (keyword \"refactor\")" in context and ".compass/specs/T1.md" in context
    assert "/compass:approve T1" in message
    assert spec.front_matter(spec.spec_path(repo, "T1").read_text(encoding="utf-8"))["status"] == "draft"

    source = repo.root / "src/transport/reconnect.ts"
    refused = pre_edit(repo.root, source)
    assert refused.returncode == 2 and "T1's spec is not approved yet, so src/transport/reconnect.ts cannot change" in refused.stderr
    assert pre_edit(repo.root, spec.spec_path(repo, "T1")).returncode == 0  # drafting the spec is the point
    assert pre_edit(repo.root, repo.root.parent / "elsewhere.txt").returncode == 0  # outside the repo
    assert pre_edit(repo.root, repo.compass_dir / "state.json").returncode == 2  # nor the approval record

    # Faking the approval in the spec itself does not count.
    path = spec.spec_path(repo, "T1")
    path.write_text(path.read_text(encoding="utf-8").replace("status: draft", "status: approved"), encoding="utf-8")
    assert pre_edit(repo.root, source).returncode == 2
    assert "not approved yet" in answer(hook("prompt", repo.root, prompt="anything else?"))[0]

    approved = run_compass("-C", str(repo.root), "approve")
    assert approved.returncode == 0 and approved.stdout.startswith("Approved T1's spec (.compass/specs/T1.md) as ")
    assert pre_edit(repo.root, source).returncode == 0
    assert state.read(repo)["tasks"]["T1"]["approved"]["by"]
    assert "T1  (large; spec approved by " in run_compass("-C", str(repo.root), "task").stdout


def test_quick_lifts_the_spec_gate_for_one_turn(repo):
    answer(hook("prompt", repo.root, prompt="Refactor src/transport into smaller files"))
    source = repo.root / "src/transport/socket.ts"
    assert pre_edit(repo.root, source).returncode == 2
    hook("prompt", repo.root, prompt="!quick just fix the typo in socket.ts")
    assert pre_edit(repo.root, source).returncode == 0
    hook("prompt", repo.root, prompt="now carry on with the refactor plan")
    assert pre_edit(repo.root, source).returncode == 2


def test_the_spec_gate_can_be_switched_off(repo):
    write(repo.root, ".compass/config.yaml", "spec_gate:\n  enabled: false\n")
    context, _ = answer(hook("prompt", repo.root, prompt="Refactor src/transport into smaller files"))
    assert "is large" not in context
    assert pre_edit(repo.root, repo.root / "src/transport/socket.ts").returncode == 0


# -- /compass:task, approve, check-prompt, SessionStart ------------------------------------------


def brief(repo: Repo, text: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "compass", "-C", str(repo.root), "task", "new", "--brief", "-"],
        input=text, capture_output=True, text=True, encoding="utf-8",
    )


def test_task_briefs_start_small_and_large_tasks(repo):
    small = brief(repo, "Goal: cap jitter. Scope: `ReconnectPolicy.next`. Accept when: never above maxDelayMs")
    assert small.stdout.startswith("[compass] Task T1 started from the brief (small).")
    assert "Small task: go ahead" in small.stdout
    big = brief(repo, 'Goal: migrate the transport to WebSockets $(rm -rf ~) "quoted"')
    assert big.stdout.startswith('[compass] Task T2 started from the brief (large: keyword "migrate").')
    assert "The previous task, T1, stays open" in big.stdout
    assert '$(rm -rf ~) "quoted"' in spec.spec_path(repo, "T2").read_text(encoding="utf-8")  # taken literally
    assert "does not state its accept when" in big.stdout  # WebSockets names the scope
    assert brief(repo, "").stdout.startswith("[compass] No brief given.")


def test_approving_a_small_task_or_nothing(repo):
    run_compass("-C", str(repo.root), "task")
    assert run_compass("-C", str(repo.root), "approve").stdout.startswith("T1 is a small task; it needs no spec.")
    proc = run_compass("-C", str(repo.root), "approve", "T9")
    assert proc.returncode == 0 and "T9 is a small task" in proc.stdout


def test_approve_warns_about_unticked_questions(repo):
    answer(hook("prompt", repo.root, prompt="Refactor src/transport into smaller files"))
    path = spec.spec_path(repo, "T1")
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ]", "- [ ] Keep index.ts as the entry point?"), encoding="utf-8")
    out = run_compass("-C", str(repo.root), "approve", "T1").stdout
    assert "Note: 1 open question is still unticked: Keep index.ts as the entry point?" in out


def test_check_prompt_is_a_dry_run(repo):
    before = repo.state_path.read_text(encoding="utf-8") if repo.state_path.exists() else None
    out = run_compass("-C", str(repo.root), "check-prompt", "refactor withRetry in src/transport/reconnect.ts").stdout
    assert out.startswith("kind: task\nnames: withRetry (symbol), src/transport/reconnect.ts (path)\n")
    assert 'size: large (keyword "refactor")' in out and "context pack:" in out
    after = repo.state_path.read_text(encoding="utf-8") if repo.state_path.exists() else None
    assert before == after and not (repo.logs_dir / "gate.jsonl").exists()


def test_session_start_adds_the_stack_and_a_pending_spec(repo):
    out = hook("session-start", repo.root, source="startup").stdout
    assert "[compass] Stack in use, with the versions installed" in out
    assert "- node package.json (sensor-dashboard): pnpm, node >=20; react 18.3.1, zod 3.23.8;" in out
    assert json.loads((repo.compass_dir / "stack.json").read_text(encoding="utf-8"))["entries"][0]["stack"] == "node"
    answer(hook("prompt", repo.root, prompt="Refactor src/transport into smaller files"))
    assert "T1's spec (.compass/specs/T1.md) is not approved yet" in hook("session-start", repo.root, source="resume").stdout


def test_the_gates_fail_open(repo):
    repo.state_path.write_text("{broken", encoding="utf-8")
    write(repo.root, ".compass/config.yaml", "prompt_gate: [not, a, mapping]\n")
    for event, fields in (("prompt", {"prompt": "fix it"}), ("pre-edit", {"tool_input": {"file_path": "src/x.ts"}})):
        proc = hook(event, repo.root, **fields)
        assert proc.returncode == 0, (event, proc.stderr)
    repo.db_path.unlink()  # no index: no pack, but the gate still works
    write(repo.root, ".compass/config.yaml", "")
    run_compass("-C", str(repo.root), "task", "new")  # the prompt above defined T1; start afresh
    context, message = answer(hook("prompt", repo.root, session="s3", prompt="fix it"))
    assert "does not state" in message


@pytest.mark.parametrize(("value", "strictness"), [("off", "off"), ('"off"', "off"), ("block", "block"), ("loud", "warn")])
def test_strictness_values(value, strictness):
    # A bare `off` is YAML for false; it still means off.
    assert parse_config(f"prompt_gate:\n  strictness: {value}\n").data["prompt_gate"]["strictness"] == strictness


def test_the_gates_work_with_review_switched_off(repo):
    write(repo.root, ".compass/config.yaml", "review:\n  enabled: false\n")
    context, message = answer(hook("prompt", repo.root, prompt="Refactor src/transport into smaller files"))
    assert "Task T1 is large" in context and "Task T1 is now active" not in context  # no review notice
    source = repo.root / "src/transport/socket.ts"
    assert pre_edit(repo.root, source).returncode == 2
    hook("prompt", repo.root, prompt="!quick just this once")
    assert pre_edit(repo.root, source).returncode == 0
    hook("prompt", repo.root, prompt="and now the rest of the plan")
    assert pre_edit(repo.root, source).returncode == 2  # !quick lasted one turn


def test_a_blocked_prompt_keeps_the_task_notice_for_the_next_one(repo):
    write(repo.root, ".compass/config.yaml", "prompt_gate:\n  strictness: block\n")
    assert hook("prompt", repo.root, prompt="fix it").returncode == 2
    context, _ = answer(hook("prompt", repo.root, prompt="Make withRetry in src/transport/reconnect.ts stop after 5 tries"))
    assert "Task T1 is now active" in context


def test_approving_a_large_task_whose_spec_went_missing(repo):
    answer(hook("prompt", repo.root, prompt="Refactor src/transport into smaller files"))
    spec.spec_path(repo, "T1").unlink()
    proc = run_compass("-C", str(repo.root), "approve")
    assert proc.returncode == 1 and "wrote a new draft at .compass/specs/T1.md" in proc.stderr
    assert "Refactor src/transport" in spec.spec_path(repo, "T1").read_text(encoding="utf-8")
    assert pre_edit(repo.root, repo.root / "src/transport/socket.ts").returncode == 2  # still not approved
