"""M4: the prompt gate (PG-01 to PG-05), the context pack (CP-01 to CP-03)
and the spec gate (SG-01 to SG-05), from the rules up to the hook contracts."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from compass import spec, state
from compass.config import default_config, parse_config
from compass.gate import ask_first, developer_notice, missing_fields, parse
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
        ("Run the tests and fix what fails", "task"),  # a change, even after a run
        ("Why does test_alarm fail? Fix it.", "task"),
        ("Where is retry handled and what calls it?", "question"),
        ("explain how `ReconnectPolicy.next` computes jitter", "question"),
        ("does this still pass on Windows", "question"),
        ("Run the tests and tell me what fails.", "action"),  # changes no code
        ("look at the logs and tell me why the deploy failed", "action"),
        ("commit the changes with a good message", "action"),
        ("start the dev server", "action"),
        ("yes", "reply"),
        ("go ahead", "reply"),
        ("looks good, thanks", "reply"),
        ("yes, and keep the old name as an alias", "reply"),  # an answer to Claude
        ("no, use the other one", "reply"),
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
        ("clean up the code", ["acceptance"]),  # all of it, but what done looks like is still open
        ("The login page breaks when the session expires", []),  # a symptom: fix it, and it says where
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


# Realistic first prompts. The gate only speaks up when Claude would otherwise
# have to guess; anything Claude can find on its own counts as stated.
VAGUE = [
    "improve the error handling", "make it faster", "fix it", "clean up the code", "refactor this", "add some tests",
    "fix the bug", "improve performance", "optimize this", "update the docs", "add error handling",
    "support Windows", "handle the edge cases", "improve the exception handling", "make it more robust",
    "Add logging to the API", "add a feature to export readings as CSV",
]
CLEAR = [
    "Run the tests and fix what fails", "run the linter and fix the warnings", "Fix the failing tests",
    "fix the type errors", "the build is broken, fix it", "debug why the login test fails",
    "Add a --json flag to compass report", "add input validation to POST /readings so negative values get a 422",
    "Update the README to mention Windows support", "bump fastapi to 0.115", "Change the default port to 8080",
    "add a docstring to StockItem.restock", "implement the TODO in src/inventory/api.py", "Fix the typo in the README",
    "remove the unused imports", "upgrade all dependencies", "install the dependencies", "format the code",
    "write a commit message for these changes", "set up the project so I can run it locally",
    "Make the CLI print the version with --version", "generate a .gitignore",
    "improve the error handling so the app doesn't crash on bad input",
    'Traceback (most recent call last):\n  File "src/inventory/api.py", line 20\nValueError: negative value',
]


@pytest.mark.parametrize("text", VAGUE)
def test_vague_requests_get_a_question(text):
    parsed = parse(text)
    assert parsed.kind == "task" and missing_fields(parsed, default_config()), text


@pytest.mark.parametrize("text", CLEAR)
def test_clear_requests_go_straight_through(text):
    parsed = parse(text)
    assert parsed.kind != "task" or missing_fields(parsed, default_config()) == [], text


@pytest.mark.parametrize("text", ["fix it", "now add a test for it", "fix the bug", "do that for the other endpoint too"])
def test_a_conversation_under_way_supplies_it_and_that(text):
    parsed = parse(text)
    parsed.followup = True  # the session has had earlier prompts
    assert parsed.kind != "task" or missing_fields(parsed, default_config()) == [], text
    assert missing_fields(parse("make it faster"), default_config())  # a new session: which code, how fast?


def test_what_claude_and_the_developer_are_told():
    text = ask_first(["scope", "acceptance"])
    assert text.startswith("[compass] Before you change any code, check with the developer: the request does not say"
                           " which code this is about and what done looks like.")
    assert "offer your best guess" in text and "Skip the question if the conversation already answers it" in text
    assert ask_first(["scope"], hold=True).endswith("Compass holds file edits until they reply.")
    assert developer_notice(["scope"]) == (
        "[compass] Before changing code, Claude will check with you which code this is about. (!quick skips this check.)"
    )
    assert "; edits wait for your answer." in developer_notice(["scope"], hold=True)


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


@pytest.mark.parametrize(
    ("text", "size"),
    [
        ("Refactor `withRetry` to take an options object", "small"),  # one function the map knows
        ("refactor ReconnectPolicy.next so jitter never exceeds the cap", "small"),  # one method
        ("Refactor withRetry in src/transport/reconnect.ts to return a promise", "small"),  # its own file is fine
        ("Refactor `withRetry` so every caller passes an options object", "large"),  # its callers change too
        ("Refactor `withRetry` into its own module", "large"),
        ("Refactor ReconnectPolicy to use a strategy object", "large"),  # a class
        ("Refactor `retryForever` to stop sooner", "large"),  # not in the map
        ("Refactor withRetry and ReconnectPolicy.next together", "large"),  # two names
    ],
)
def test_a_refactor_of_one_function_needs_no_plan(repo, text, size):
    parsed = parse(text)
    with Store.open(repo.db_path) as store:
        resolve(store, parsed)
    assert spec.classify(parsed, default_config())[0] == size, text
    assert missing_fields(parsed, default_config()) == [] or size == "large"  # "to take …" says what done is


def test_the_one_function_exception_can_be_switched_off(repo):
    parsed = parse("Refactor `withRetry` to take an options object")
    with Store.open(repo.db_path) as store:
        resolve(store, parsed)
    config = parse_config("spec_gate:\n  large_task_when:\n    except_one_function: false\n")
    assert spec.classify(parsed, config) == ("large", 'keyword "refactor"')


def test_only_files_a_task_touches_count_towards_its_size(repo):
    # Three paths, but one is a directory named as a filter and one is Compass's
    # own state: a small task. (Found dogfooding: it was sized large.)
    text = "Make `on_stop` in src/transport/socket.ts skip files under .compass/ and lib/ and add tests in x.test.ts"
    parsed = parse(text)
    assert ".compass/" in [c.text for c in parsed.candidates]  # the leading dot survives
    with Store.open(repo.db_path) as store:
        resolve(store, parsed)
    assert spec.classify(parsed, default_config()) == ("small", "")
    parsed = parse("touch ./compass/a.py, ./compass/b.py and src/c.py")  # a project's own compass/ package counts
    assert spec.classify(parsed, default_config()) == ("large", "3 files mentioned")


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


def test_ask_mode_has_claude_check_before_assuming(repo):
    hook("session-start", repo.root, source="startup")
    context, message = answer(hook("prompt", repo.root, prompt="fix it"))  # answer() also asserts exit 0
    assert "the request does not say which code this is about and what done looks like" in context
    assert "Ask in one short message and offer your best guess" in context
    assert message == developer_notice(["scope", "acceptance"])
    assert state.read(repo)["tasks"]["T1"]["brief"] == "fix it"
    assert pre_edit(repo.root, repo.root / "src/transport/socket.ts").returncode == 0  # nothing is held back
    # The answer to Claude's question is a follow-up, not a new request: no nagging.
    context, message = answer(hook("prompt", repo.root, prompt="the crash is in the reconnect loop on Windows"))
    assert (context, message) == ("", "")
    assert [row["outcome"] for row in gate_log(repo)] == ["ask", "pass"]
    assert gate_log(repo)[0]["excerpt"] == "fix it" and "excerpt" not in gate_log(repo)[1]


def test_strict_mode_holds_edits_until_the_developer_answers(repo):
    write(repo.root, ".compass/config.yaml", "prompt_gate:\n  strictness: strict\n")
    context, message = answer(hook("prompt", repo.root, prompt="improve performance"))  # the prompt goes through
    assert context.count("Compass holds file edits until they reply.") == 1 and "edits wait for your answer" in message
    assert gate_log(repo)[0]["outcome"] == "ask" and gate_log(repo)[0]["hold"] is True
    source = repo.root / "src/transport/socket.ts"
    held = pre_edit(repo.root, source)
    assert held.returncode == 2 and held.stderr.startswith(
        "[compass] Check with the developer before changing src/transport/socket.ts: their request does not say"
        " which code this is about and what done looks like."
    )
    assert pre_edit(repo.root, repo.root.parent / "elsewhere.txt").returncode == 0  # outside the repo
    assert pre_edit(repo.root, source, session="s2").returncode == 0  # another session was not asked anything
    answer(hook("prompt", repo.root, prompt="the reconnect loop in src/transport; it should stop spinning the CPU"))
    assert pre_edit(repo.root, source).returncode == 0  # answered: edits go ahead


def test_off_mode_and_non_tasks_are_never_checked(repo):
    write(repo.root, ".compass/config.yaml", "prompt_gate:\n  strictness: off\n")
    assert answer(hook("prompt", repo.root, prompt="fix it"))[1] == ""
    write(repo.root, ".compass/config.yaml", "prompt_gate:\n  strictness: strict\n")
    source = repo.root / "src/transport/socket.ts"
    for text in ("where does this break?", "yes", "go ahead", "/compass:accept", "run the tests and tell me what fails"):
        assert answer(hook("prompt", repo.root, session="s2", prompt=text))[1] == "", text
        assert pre_edit(repo.root, source, session="s2").returncode == 0, text


def test_quick_skips_the_check_and_is_logged_for_tuning(repo):
    write(repo.root, ".compass/config.yaml", "prompt_gate:\n  strictness: strict\n")
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
    assert refused.returncode == 2 and (
        "T1 is a large task and its spec is not approved yet, so Compass holds the edit to src/transport/reconnect.ts"
    ) in refused.stderr
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
    big = brief(repo, 'Goal: migrate the transport onto WebSockets $(rm -rf ~) "quoted"')
    assert big.stdout.startswith('[compass] Task T2 started from the brief (large: keyword "migrate").')
    assert "The previous task, T1, stays open" in big.stdout
    assert '$(rm -rf ~) "quoted"' in spec.spec_path(repo, "T2").read_text(encoding="utf-8")  # taken literally
    assert "does not say what done looks like" in big.stdout  # WebSockets names the scope
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
    text = "refactor withRetry and every caller in src/transport/reconnect.ts"
    out = run_compass("-C", str(repo.root), "check-prompt", text).stdout
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
    assert "Claude will check with you" in message


@pytest.mark.parametrize(
    ("value", "strictness"),
    [("off", "off"), ('"off"', "off"), ("strict", "strict"), ("ask", "ask"), ("loud", "ask"),
     ("warn", "ask"), ("block", "strict")],  # the earlier names still read, and block no longer turns prompts away
)
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


def test_follow_ups_in_a_session_lean_on_earlier_turns(repo):
    hook("session-start", repo.root, source="startup")
    answer(hook("prompt", repo.root, prompt="where is the reconnect backoff computed?"))
    run_compass("-C", str(repo.root), "task", "new")  # a fresh task, in the same conversation
    context, message = answer(hook("prompt", repo.root, prompt="fix it"))
    assert message == "" and "check with the developer" not in context  # "it" is what was just discussed
    run_compass("-C", str(repo.root), "task", "new")
    hook("session-start", repo.root, source="clear")  # /clear: the earlier turns are gone
    assert "Claude will check with you" in answer(hook("prompt", repo.root, prompt="fix it"))[1]


def test_approving_a_large_task_whose_spec_went_missing(repo):
    answer(hook("prompt", repo.root, prompt="Refactor src/transport into smaller files"))
    spec.spec_path(repo, "T1").unlink()
    proc = run_compass("-C", str(repo.root), "approve")
    assert proc.returncode == 1 and "wrote a new draft at .compass/specs/T1.md" in proc.stderr
    assert "Refactor src/transport" in spec.spec_path(repo, "T1").read_text(encoding="utf-8")
    assert pre_edit(repo.root, repo.root / "src/transport/socket.ts").returncode == 2  # still not approved
