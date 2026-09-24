# Compass — Evaluation & Metrics Plan

Sep 23, 2026 · @Uvesh

## Summary

We judge Compass on net main-model tokens, wall-clock time and output quality. Each is measured two ways: a controlled benchmark with Compass on and off, and telemetry from the 8-week pilot.

- **Benchmark:** 20 fixed tasks across 2 stacks, each run 3 times per condition, scored by automated acceptance tests.
- **Pilot:** 2 weeks of baseline telemetry, then 6 weeks with Compass, plus a short developer survey.

**Decision rule.** Compass passes when both sources show at least 20% fewer main-model tokens, with no more than 5% extra wall-clock time and no drop in task pass rate. The pilot then goes to a wider rollout. Results between 10% and 20% lead to narrowing Compass to the modules that clearly helped. Below 10%, or a speed regression above 10%, we stop.

## Metric definitions

The primary metric is main-model tokens per task. It also counts cache reads, because cheap cached tokens still consume context and usage limits. Every other metric either guards against a regression or explains the result.

| Metric | Type | Definition | Source |
| --- | --- | --- | --- |
| Main-model tokens | Primary | Input + output + cache-creation + cache-read tokens on main-session assistant turns, per task | Transcript `usage` fields |
| Delegated tokens | Explanatory | Same sum for subagent transcripts, reported separately by model tier | Subagent transcripts |
| Net cost-weighted tokens | Primary (cost) | Tokens × the current list price per tier, summed across main and delegated | Transcripts + price table |
| Wall-clock time | Guard | First prompt to final Stop, excluding time spent waiting on the human | Hook timestamps |
| Pass rate | Guard | Share of tasks whose acceptance test passes at the end | Benchmark harness |
| Correction turns | Quality | Prompts after the first before the task passes or is accepted | Transcript |
| Read calls | Explanatory | Count of Read, Grep and Glob calls versus Compass query tool calls | Transcript tool calls |
| Context pack overhead | Explanatory | Tokens injected by Compass hooks | Hook logs |
| Review time | Quality (pilot) | Minutes from manifest open to accept or reject | Self-reported |
| Gate bypass rate | Adoption | `!quick` prompts ÷ all prompts | Bypass log |

Human wait time is excluded from wall-clock time. Otherwise the spec gate's approval pause would look like a slowdown, when it is a deliberate step.

## Benchmark suite

The suite has 20 tasks, split evenly across two repositories in different stacks. Each task is pinned to a git commit and has a hidden acceptance test that decides pass or fail.

### Repositories

- **Repo A:** one internal repo from the pilot team, at least 50k LOC
- **Repo B:** one public open-source repo in a different language, at least 50k LOC, so results can be shared and reproduced

### Task mix

| Category | Tasks | What it stresses |
| --- | --- | --- |
| Locate and explain | 4 | Code map and query tools versus file reading |
| Bug fix | 4 | Context pack and targeted reads |
| Small feature | 4 | Prompt gate and spec quality |
| Cross-module refactor | 3 | Import graph, spec gate and scope control |
| Write tests | 3 | Test map and scaffold subagent |
| Triage failing tests or logs | 2 | Digest and test-runner delegation |

### Task definition

```yaml
# bench/tasks/b07-retry-timeout.yaml
id: b07
repo: repo-b
commit: 3f2a9c1
category: bug_fix
prompt: |
  Goal: Requests that time out are not retried.
  Scope: src/http/
  Accept when: a timed-out request is retried up to max_retries.
  Constraints: no new dependencies.
acceptance: "pytest tests/hidden/test_b07.py"
timeout_min: 20
```

Every prompt is written in the structured `/task` format for both conditions. That isolates Compass's machinery from the separate question of whether developers write better prompts, which the pilot measures instead.

## Benchmark run protocol

The full benchmark is 120 runs: 20 tasks × 2 conditions × 3 repeats. All runs are headless and scripted, so nothing depends on who runs them.

| Condition | Setup |
| --- | --- |
| OFF (baseline) | Stock Claude Code; Compass plugin not installed; no `.compass/` folder |
| ON | Compass plugin installed; index prebuilt before the timer starts; default config |

### Steps per run

1. Fresh clone of the repo at the task's pinned commit, in a clean temp directory.
2. For ON only: run `compass init` and `compass index`, and record the index time separately.
3. Start the timer and run Claude Code headless (`claude -p`) with the task prompt and a JSON output format.
4. When the spec gate asks for approval, the harness answers open questions with "proceed with stated assumptions" and runs `/approve`. Wait time is excluded from wall-clock time.
5. Stop at completion, at the task's timeout, or at 40 turns.
6. Run the hidden acceptance test and record pass or fail.
7. Save the transcript, subagent transcripts, hook logs and `git diff` to `bench/results/<run-id>/`.

### The harness

`bench/run.py` carries out these steps, and `compass report bench/results/<batch>` writes the report below from what it saves. Some details the protocol leaves open:

- Active time comes from the transcript, not a stopwatch. It is the time from each prompt to the end of its turn, which leaves out the approval pause as step 4 requires. The harness also records the process time, and Claude Code's own cost estimate for the net cost-weighted metric.
- User settings and other MCP servers stay out in both conditions (`--setting-sources project,local`, `--strict-mcp-config`).
- The ablation conditions are `on-no-map` (query tools and context pack), `on-no-gates` (prompt and spec gates), `on-no-delegation` and `on-no-review`.
- Pilot telemetry uses the same row format as the harness, so one report reads both.

### Controls

- Pin the Claude Code version and the model for the whole benchmark; record both in the report.
- Randomise run order across tasks and conditions, so time-of-day API latency doesn't favour one side.
- Use the same machine class for all runs.
- Rerun the full suite after any change to Compass that could affect results. Never compare numbers across versions.

## Pilot field measurement

The benchmark shows what Compass can do; the pilot shows what it does in real work. The pilot also covers the effects the benchmark deliberately holds constant: prompt quality, review time and adoption.

| Weeks | Mode | What is collected |
| --- | --- | --- |
| 1–2 | Baseline: telemetry-only build, every other module off | Tokens, time, tool calls, correction turns per task |
| 3–4 | Compass on, modules rolled out as built | Same, plus bypass log and context-pack overhead |
| 5–7 | Compass fully on, rules tuned weekly | Same, plus review time on each accepted manifest |
| 8 | Evaluation | Survey, benchmark rerun, report |

### Task tagging

Developers tag each task with a category from the benchmark mix and a size (S, M or L) when they start it with `/task`. Comparisons are made within the same category and size, because a week of refactors cannot be compared with a week of bug fixes.

### Survey (week 8, 5 minutes)

1. How often did Compass stop you from starting with an unclear request? (never to always)
2. How much faster or slower did reviewing AI changes feel? (−2 to +2)
3. Which module would you keep, and which would you remove?
4. Did any gate block work it should not have? Give an example.
5. Would you want Compass on your next project? (yes, no, only some modules)

### Privacy

Telemetry rows hold counts, timings and task tags only; they contain no prompts, code or file contents. Developers export their own `telemetry.jsonl` to the pilot owner at the end, or set `telemetry.export` to a file in a folder the owner collects. `compass report` accepts several files at once.

Tasks are tagged in the brief: `/compass:task Goal: … Category: bug fix Size: M`.

## Analysis and report

Compare each task against itself: the headline number is the median of per-task changes, with a bootstrap confidence interval. Pooling all runs would let a few large tasks dominate the result.

For each task *t*, take the median of its 3 runs in each condition, then compute:

```latex
\Delta_t = \frac{\operatorname{median}(\text{ON}_t) - \operatorname{median}(\text{OFF}_t)}{\operatorname{median}(\text{OFF}_t)}
```

Report the median of Δ across the 20 tasks, with a 95% interval from 10,000 bootstrap resamples of the tasks.

### Rules

- Report tokens both over all runs and over passing runs only, so a cheap failure never counts as a saving.
- Pass rate is compared as counts, for example 52 of 60 against 50 of 60, alongside the token result.
- Break results down by task category. Compass may help a lot on locate-and-explain and very little on small features, and that tells us which modules to keep.
- Module attribution: on 6 tasks, run ablations with one module off at a time (code map, gates, delegation, review).

### Report template

```markdown
# Compass evaluation — <version>, <date>
Claude Code <version> · model <id> · 20 tasks × 2 conditions × 3 runs

## Result
Main-model tokens: <median Δ> (95% CI <low> to <high>)
Wall-clock: <median Δ> · Pass rate: <ON n/60> vs <OFF n/60>
Decision: go | narrow | stop

## By category
| Category | Tokens Δ | Time Δ | Pass ON / OFF |

## Module ablation
| Module off | Tokens Δ vs full ON |

## Pilot
Baseline vs Compass medians per category · survey summary · bypass rate

## Notable failures
<3–5 runs worth reading, with links to results folders>
```

## Threats to validity

The biggest threat is designing benchmark tasks that happen to suit Compass. Tasks should be written by someone who has not built Compass, from real tickets where possible.

| Threat | Effect | Mitigation |
| --- | --- | --- |
| Tasks chosen to favour Compass | Inflated savings | Tasks drawn from real closed tickets by a non-author; fixed before any ON run |
| Run-to-run model variance | Noisy or misleading deltas | 3 repeats, medians, bootstrap intervals; report the interval, not only the point |
| Claude Code or model update mid-study | Conditions not comparable | Pin versions; rerun both conditions after any upgrade |
| Index build time hidden | Understates Compass's cost | Report index time separately and amortise it per task in the cost figure |
| Auto-approval in the benchmark | Spec gate looks better than with real humans | Pilot measures real approval flow and wait time |
| Novelty and observer effect in the pilot | Better behaviour just from being measured | Baseline weeks also run telemetry; compare later pilot weeks, not only week 3 |
| Pilot team not representative | Results don't transfer | At least 2 stacks; state team size and experience in the report |
| Cache effects | Token counts depend on prompt caching behaviour | Report cache-read tokens separately alongside the total |
