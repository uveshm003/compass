# Compass benchmark

The harness for the Evaluation Plan's benchmark. Every task runs headless with Compass on and off, each time in a fresh copy of its repository. The task's hidden acceptance check scores each run. `compass report` then turns the results into the plan's report.

```bash
uv run python bench/run.py --model claude-opus-5-5 --tasks bench/tasks/<suite> --repeats 3
uv run compass report bench/results/<batch>
```

Runs go through Claude Code on your own login, so they count against your Claude subscription's usage like any session; no API key is involved. The suite (20 tasks × 2 conditions × 3 runs = 120 sessions) is a deliberate, budgeted step. `--dry-run` lists the runs without starting any. `--only x01,x02` and `--conditions` narrow a batch. A batch that stops can be started again: runs that already have a `row.json` are skipped.

## What a run does

1. It copies the task's repository at its commit into a temp directory, applies the task's `setup` steps, and commits them.
2. With Compass on, it runs `compass init`, which builds the index. The index time is recorded separately.
3. It starts `claude -p` with the prompt, a fixed session id, the pinned model, `--max-turns` and stream-json output. User settings and other MCP servers stay out in both conditions. With Compass on, the plugin comes from this checkout.
4. If the spec gate holds a large task, the harness runs `compass approve` and resumes the session with "proceed with the stated assumptions". Active time comes from the transcript and leaves out the wait before each prompt, so the pause costs nothing.
5. It copies the hidden files in and runs the acceptance check.
6. It saves everything to `bench/results/<batch>/<run>/`: `stream.jsonl`, `transcript.jsonl` with `subagents/`, `compass-logs/`, `diff.patch`, `reply.txt`, `acceptance.txt` and `row.json`. The cost in `row.json` is Claude Code's own estimate at list prices, the plan's cost weighting; a subscription is not billed per token.

Runs go in shuffled order (`--seed`). Claude Code's auto-updater is off for the batch, and its version is recorded with every run. Never compare numbers across Compass or Claude Code versions.

| Condition | Setup |
| --- | --- |
| `off` | Stock Claude Code: no plugin, no `.compass/` |
| `on` | The plugin and its MCP server, default config |
| `on-no-map` | `on` without the query tools and the context pack |
| `on-no-gates` | `on` without the prompt gate and the spec gate |
| `on-no-delegation` | `on` without the delegation rules and contracts |
| `on-no-review` | `on` without anchors and manifests |

## Tasks

One YAML file per task, as in the plan:

```yaml
id: b07
repo: repo-b                 # a name from bench/repos.yaml
commit: 3f2a9c1
category: bug_fix            # explain | bug_fix | feature | refactor | tests | triage
prompt: |
  Goal: Requests that time out are not retried.
  Scope: src/http/
  Accept when: a timed-out request is retried up to max_retries.
  Constraints: no new dependencies.
setup:                       # optional; applied and committed before the run
  - replace: {file: src/http/retry.py, old: "...", new: "..."}
hidden: [tests/hidden/test_b07.py]   # copied from bench/hidden/b07/ after the run
acceptance:
  command: "{python} -m pytest -q tests/hidden/test_b07.py"   # {python}: this Python
  env: {PYTHONPATH: src}
  # or, for a question: reply_contains: [is_alarm, DEFAULT_THRESHOLD]
allowed_tools: ["Bash(python -m pytest:*)"]
timeout_min: 20
max_turns: 40
```

`bench/tasks/examples/` holds two tasks on a fixture repo. They check the harness itself: a five-file repo shows what Compass costs, not what it saves.

## The real suite

The Evaluation Plan's suite is not written yet. It needs:

- Two repositories of at least 50k LOC in different stacks, listed in `repos.yaml`: an internal repo from the pilot team, and a public open-source repo whose results can be shared.
- 20 tasks in the plan's mix, drawn from real closed tickets by someone who did not build Compass, and fixed before any run with Compass on.
- A budget for 120 sessions, plus the ablations on 6 tasks.
