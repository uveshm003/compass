"""Delegation (C6, DL-01 to DL-03): the Haiku subagents, when to use them,
and the output contract each must keep.

The main model makes every delegation call itself, from the rules SessionStart
gives it (DL-03, the "CLAUDE.md fragment"): hand a subagent work that reads a
lot and answers briefly, keep small or judgment-heavy work inline.

The contracts (DL-02) are enforced by hooks, not only asked for:

- SubagentStop reads the subagent's answer and, when it is too long, carries a
  code block over the limit or cites nothing, sends it back once with the
  reason (``stop_hook_active`` marks the retry, which always passes).
- ``scaffold`` may only change files named in its instructions or in the
  task's spec: the PreToolUse hook on the Agent tool notes the files a
  delegation names, and the PreToolUse hook on Write/Edit refuses anything
  else. At SubagentStop every file it changed must carry a tag for the task.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from compass import state
from compass.repo import Repo

DIGEST = "compass:digest"
TEST_RUNNER = "compass:test-runner"
SCAFFOLD = "compass:scaffold"
STATE_LOCK_WAIT_S = 1.0
MAX_PENDING = 10
PENDING_TTL_S = 3600
MAX_AGENTS = 50

_FENCE = re.compile(r"^\s*```")
_LINE_SUFFIX = re.compile(r":\d+(?:[-:]\d+)?$")  # src/app.py:12, src/app.py:12-20
_CITATION = re.compile(r"[\w./\\-]+\.[A-Za-z0-9]+:\d+|\bL\d+\b|\blines?\s+\d+", re.I)


@dataclass(frozen=True)
class Contract:
    max_lines: int | None = None
    max_code_block_lines: int | None = None
    cites: bool = False  # a multi-line answer points at file:line (or a log line)
    tags_changes: bool = False  # every file it changed carries a tag for the task
    named_files_only: bool = False


CONTRACTS = {
    DIGEST: Contract(max_lines=30, max_code_block_lines=5, cites=True),
    TEST_RUNNER: Contract(max_lines=20),
    SCAFFOLD: Contract(tags_changes=True, named_files_only=True),
}


def rules(threshold: int, local_tools: bool) -> list[str]:
    """The delegation rules SessionStart adds to Claude's context (DL-03)."""
    lines = [
        "- Delegation: a subagent works in its own context, and only its short answer reaches yours.",
        f"    {TEST_RUNNER}: run test suites and builds through it, not Bash (tail or grep still load the output"
        " into your context); it returns only the failures. Run one test inline only to see its full output.",
        f"    {DIGEST}: to read more than about {threshold} lines (logs, large or generated files) for a short answer",
        f"    {SCAFFOLD}: for mechanical edits you can spell out; name every file it may change and the task id",
        "  Keep small work (under about 50 lines) and anything that needs judgment in this conversation:"
        " a subagent starts from an empty context.",
    ]
    if local_tools:
        lines.append(
            "- The local-model tools summarize_file and classify_files run on this machine at no cost; use them"
            " for the gist of a large file before reading it or delegating."
        )
    return lines


# -- SubagentStop (DL-02) --------------------------------------------------------------


def answer_problems(contract: Contract, text: str) -> list[str]:
    """What is wrong with an answer, against its contract; ``[]`` when it keeps it."""
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    problems = []
    if contract.max_lines is not None and len(lines) > contract.max_lines:
        problems.append(f"it has {len(lines)} lines (at most {contract.max_lines})")
    if contract.max_code_block_lines is not None:
        longest = _longest_code_block(text or "")
        if longest > contract.max_code_block_lines:
            problems.append(f"a code block runs {longest} lines (at most {contract.max_code_block_lines})")
    if contract.cites and len(lines) > 1 and not _CITATION.search(text or ""):
        problems.append("it cites no file:line (or log line) for its claims")
    return problems


def _longest_code_block(text: str) -> int:
    longest, inside, count = 0, False, 0
    for line in text.splitlines():
        if _FENCE.match(line):
            if inside:
                longest = max(longest, count)
            inside, count = not inside, 0
        elif inside:
            count += 1
    return max(longest, count) if inside else longest


def on_subagent_stop(repo: Repo, config, payload: dict[str, Any]) -> dict[str, Any] | None:
    """The hook's JSON answer: a block with the reason, or None to let it finish."""
    agent_type = payload.get("agent_type")
    contract = CONTRACTS.get(agent_type) if isinstance(agent_type, str) else None
    settings = config.delegation
    if contract is None or not settings.enabled or not settings.enforce_contracts:
        return None
    if payload.get("stop_hook_active"):
        return None  # the retry after a block always goes through
    problems = answer_problems(contract, payload.get("last_assistant_message") or "")
    tags = contract.tags_changes and config.review.enabled  # tags belong to review (RO-01)
    untagged = _untagged_changes(repo, config, payload.get("agent_id")) if tags else []
    if not problems and not untagged:
        return None
    name = agent_type.split(":", 1)[-1]
    reasons = []
    if problems:
        reasons.append(f"your answer breaks the {name} contract: {'; '.join(problems)}. Rewrite it within the contract.")
    if untagged:
        from compass.review import tag

        task = state.active_task(state.read(repo)) or "<task>"
        shown = ", ".join(untagged[:10]) + (f" and {len(untagged) - 10} more" if len(untagged) > 10 else "")
        reasons.append(
            f"every change you make carries a tag: add a {tag('change', task)} — <note> comment, in each file's"
            f" own syntax, to {shown}."
        )
    return {"decision": "block", "reason": "[compass] " + " Also, ".join(reasons)}


def _untagged_changes(repo: Repo, config, agent_id: Any) -> list[str]:
    from compass.anchors import is_binary, scan_file
    from compass.globs import compile_globs

    current = state.read(repo)
    task = state.active_task(current)
    record = current["agents"].get(agent_id) if isinstance(agent_id, str) else None
    if not task or not record:
        return []
    exempt = compile_globs(config.review.anchor_exempt)
    return [
        rel for rel in record["touched"]
        if (repo.root / rel).is_file() and not exempt(rel) and not is_binary(repo.root / rel)
        and not scan_file(repo.root, rel, task)
    ]


# -- scaffold's files (DL-02) -------------------------------------------------------------


def on_delegate(repo: Repo, payload: dict[str, Any]) -> None:
    """PreToolUse on the Agent tool: remember which files a scaffold
    delegation names, for the scaffold agent that is about to start."""
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if tool_input.get("subagent_type") != SCAFFOLD:
        return
    session = payload.get("session_id")
    if not isinstance(session, str):
        return
    paths = named_paths(str(tool_input.get("prompt") or ""))
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        queue = st["pending"].setdefault(session, [])
        queue.append({"paths": paths, "t": time.time()})
        del queue[:-MAX_PENDING]


def named_paths(text: str) -> list[str]:
    from compass.gate import parse

    names = (c.text.removeprefix("./").rstrip("/") for c in parse(text, "").candidates if c.kind == "path")
    return sorted({_LINE_SUFFIX.sub("", name) for name in names} - {""})


def scaffold_denial(repo: Repo, payload: dict[str, Any], rel: str) -> str | None:
    """Why the scaffold agent may not change ``rel``, or None when it may.
    Without a recorded delegation (the Agent hook did not run) nothing is refused."""
    agent_id, session = payload.get("agent_id"), payload.get("session_id")
    if not isinstance(agent_id, str) or not isinstance(session, str):
        return None
    with state.transaction(repo, STATE_LOCK_WAIT_S) as st:
        record = st["agents"].get(agent_id)
        if record is None:
            record = st["agents"][agent_id] = {
                "type": SCAFFOLD, "session": session, "touched": [], "seen": time.time(),
                "allowed": _bind(st, session, rel),
            }
            _prune_agents(st)
        allowed = record.get("allowed")
        task = state.active_task(st)
    if allowed is None:
        return None
    named = list(allowed) + _spec_paths(repo, task)
    if any(_matches(rel, name) for name in named):
        return None
    listed = ", ".join(named[:8]) if named else "none"
    return (
        f"[compass] The scaffold contract: change only the files your instructions or the task's spec name"
        f" ({listed}); {rel} is not one of them. Report back instead, and name the file if it should change."
    )


def _bind(st: dict[str, Any], session: str, rel: str) -> list[str] | None:
    """Take the delegation a scaffold agent is running, at its first edit: the
    oldest pending one that names ``rel``, else the oldest. Parallel agents may
    start editing in any order, and one that edits only its own files always
    finds its own delegation. None when none is pending."""
    queue = [e for e in st["pending"].get(session) or [] if time.time() - e["t"] < PENDING_TTL_S]
    if not queue:
        st["pending"].pop(session, None)
        return None
    chosen = next((e for e in queue if any(_matches(rel, name) for name in e["paths"])), queue[0])
    queue.remove(chosen)
    if queue:
        st["pending"][session] = queue
    else:
        del st["pending"][session]
    return chosen["paths"]


def _spec_paths(repo: Repo, task: str | None) -> list[str]:
    if not task:
        return []
    from compass.spec import spec_path

    try:
        return named_paths(spec_path(repo, task).read_text(encoding="utf-8"))
    except OSError:
        return []


def _matches(rel: str, name: str) -> bool:
    """``models.py`` names src/inventory/models.py; ``src/api`` names everything below it."""
    name = name.strip("/")
    return bool(name) and (rel == name or rel.endswith("/" + name) or rel.startswith(name + "/"))


def record_agent_edit(st: dict[str, Any], agent_id: str, agent_type: str, session: str | None, rel: str) -> None:
    record = st["agents"].setdefault(
        agent_id, {"type": agent_type, "session": session, "touched": [], "allowed": None, "seen": time.time()}
    )
    if rel not in record["touched"]:
        record["touched"].append(rel)
    record["seen"] = time.time()
    _prune_agents(st)


def _prune_agents(st: dict[str, Any]) -> None:
    agents = st["agents"]
    for stale in sorted(agents, key=lambda a: agents[a].get("seen", 0))[:-MAX_AGENTS]:
        del agents[stale]
