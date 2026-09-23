# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**M1 (index core, Steps 0–3 of the Getting Started guide) is implemented; M2 (query tools and MCP server) is next.** The repo holds the Python core under `src/compass/`, its tests, and the five Markdown specs for Compass. `.docx` and `.pdf` exports of the specs live one directory up; the `.md` files here are the source of truth, and the exports predate M1.

What exists: file enumeration and the stack profile (IX-01, IX-10), the tree-sitter indexer with a universal-ctags fallback (IX-02 to IX-05), map shards and the `_index.md` folder tree (IX-06, IX-09), raw import targets (IX-11, not yet resolved to files), and incremental updates from git hooks and the `compass hook post-edit` / `session-start` handlers (IX-07, IX-08). The plugin folder (`plugin/`), MCP server, gates, manifests and telemetry do not exist yet.

The specs are internally cross-referenced, so a change to one usually needs matching edits in the others.

| Document | Role |
| --- | --- |
| `Compass — Proposal for Adoption.md` | Business case, 8-week pilot plan, go/no-go criteria |
| `Compass — Requirements Specification.md` | Numbered requirements (PG-01, IX-03, …) and NF targets — the contract v1 is accepted against |
| `Compass — Architecture & Technical Design.md` | Layers, tier routing, storage layout, config schema, ADRs 001–008 |
| `Compass — Getting Started Development Guide.md` | Milestones M1–M6, step-by-step build order with code sketches |
| `Compass — Evaluation & Metrics Plan.md` | Benchmark protocol, metric definitions, analysis rules |

Requirement IDs are the shared vocabulary across all five docs. When changing behaviour, find the requirement ID first; when adding behaviour, give it an ID in the Requirements Spec rather than describing it only in the Architecture or Getting Started doc.

## What Compass is

A layer between developers and Claude Code that routes each piece of work to the cheapest executor that can do it correctly, and makes the resulting changes reviewable. It ships as a Claude Code plugin plus a local Python CLI and MCP server. No server, no new infrastructure — everything runs on the developer's machine.

## Architecture

Three layers, from the Architecture doc:

1. **Plugin** (`plugin/`) — hooks, subagents, commands, skills, output style, `.mcp.json`. Holds **no logic**; every hook is a thin `compass hook <event>` shell-out.
2. **Core** (`src/compass/`) — Python. All behaviour lives here, so the same code serves Claude Code hooks, the MCP server, the developer CLI and CI. This is also what keeps Compass portable to other agents later: only the plugin layer is Claude Code specific.
3. **State** (`.compass/` in each target repo) — `config.yaml` and `standards/` are committed; `index.db`, `map/`, `changes/`, `state.json`, `telemetry.jsonl` and `logs/` are derived, gitignored and rebuildable with `compass index --full`.

### Tier routing — the idea everything else serves

| Tier | Executor | Handles |
| --- | --- | --- |
| 0 | Scripts (core) | Index, lookups, range reads, trees, manifests, gates |
| 1 | Local LLM | Undocumented-symbol summaries, bulk classification — background only, never awaited |
| 2 | Haiku subagent | Digesting logs, tests and large files; mechanical edits from a spec |
| 3 | Main model | Design, logic, judgment, anything ambiguous |

Most of the savings come from Tier 0, because work that never reaches a model costs nothing. The delegation thresholds (input over ~500 lines with short expected output → Tier 2; under ~50 lines or needs judgment → stays Tier 3) live in the CLAUDE.md fragment and subagent descriptions, **not** in core code, because the main model makes the delegation call itself.

### Invariants to preserve

These are decided, and code that violates them is wrong even if it works:

- **Fail open.** Any Compass error exits 0 and logs to `.compass/logs/`. The only non-zero exits are deliberate gate decisions (prompt gate in block mode, spec gate, Stop hook missing anchors). Compass must never make Claude Code worse than stock.
- **No network calls in hooks**, except the optional local-LLM health check.
- **SQLite is the source of truth; Markdown shards are the LLM view** (ADR 003). Two representations, kept in sync by the same update path.
- **Deterministic output** (NF-13). Identical input must produce byte-identical index and shards, so map diffs are meaningful — sort everything.
- **Public extension points only** (ADR 001). Every feature must map to a hook, subagent, skill, command, output style or MCP server. No wrapping or proxying Claude Code.
- **stdio-only MCP** (ADR 008). No open ports.
- **No Must requirement may depend on a local LLM.** Local features degrade silently when no endpoint is reachable.
- **GitHub and Azure DevOps are both first-class** (NF-16). Anything tied to a hosting service must support both: CI definitions (the stack profile has one detector per provider), links to hosted views, plugin and package distribution, and this repo's own CI. Version control itself goes through plain git, never a host API. Azure DevOps TFVC is not git and stays out of scope.
- **Adding a language or stack must not touch core code** — a language is a `src/compass/queries/<lang>/` directory (`language.yaml`, `tags.scm`, optional `imports.scm`; conventions in `queries/README.md`); a stack is a module in `src/compass/stacks/` with `detect(repo) -> dict | None`. Either needs a fixture repo and snapshot test.

### Latency budgets (NF-01 to NF-04)

Prompt gate ≤ 100 ms p95, context pack ≤ 300 ms p95, full index of 100k LOC ≤ 60 s, incremental single-file update ≤ 500 ms. These are felt on every prompt; a slow hook gets the whole plugin switched off. Measure from the first commit of any hook path.

## Commands

Python 3.11+ with [uv](https://docs.astral.sh/uv/). Every command takes `-C DIR` to run against another repository, like git.

```bash
uv sync                        # create .venv from uv.lock
uv run compass --help          # entry point
compass init                   # create .compass/, config, git hooks, first index
compass index [--full] [--json]  # refresh only changed files, or rebuild everything
compass update [paths]         # re-index specific files; --from-git is what git hooks call
compass files [--json]         # enumerated file list with language and content hash
compass stack [--json]         # detected stack profile
compass hook <event>           # Claude Code hook entry point, JSON on stdin; always exits 0 in M1
```

Planned for later milestones: `compass mcp` (M2, stdio MCP server), `compass manifest <id>` (M3), `compass enrich` (M5, background local-LLM summaries), `compass report` (M6), and the optional `compass watch` (IX-15). Every query tool will be both an MCP tool and `compass <cmd> --json` (QT-04). Hooks all route through `compass hook <session-start|prompt|pre-edit|post-edit|stop>`; M1 handles `session-start` and `post-edit`, and any other event name passes through with exit 0.

### Testing

```bash
uv run pytest                     # unit, snapshot, determinism, hook-contract tests (~10 s)
uv run pytest --perf              # also latency/footprint checks on a generated 100k LOC repo
uv run pytest --update-snapshots  # accept new output in tests/snapshots/ — review the diff first
COMPASS_TEST_CTAGS=/path/to/ctags uv run pytest tests/test_ctags.py   # real universal-ctags
```

Fixture repos live in `tests/fixtures/` (one per language family); `tests/snapshots/<fixture>/` holds the expected index rows, map shards, file list and stack profile. Tests isolate git from the developer's config and set `COMPASS_CTAGS=off`, so installed tools never change snapshot output. Latency checks use plain timers with p95 rather than `pytest-benchmark`. Still planned from Step 9: weekly end-to-end runs via headless `claude -p` against the latest Claude Code release, scheduled on both CI systems. CI is macOS, Ubuntu and Windows on Python 3.11 and 3.12 — Windows without WSL is a requirement (NF-08), not an afterthought. It is defined twice, identically: `.github/workflows/ci.yml` (GitHub Actions) and `azure-pipelines.yml` (Azure Pipelines). Change both together; `tests/test_ci_configs.py` fails when their matrices or commands drift apart, and it also validates both files against their published schemas, so the Azure pipeline gets checked on every GitHub run.

**CI constraints during development.** CI runs on a free personal GitHub account, with no organization, so:
- Use no organization-only features.
- Spend minutes carefully. Public repos are free; private repos get 2,000 minutes a month, and macOS costs about 10× Linux. The workflow cancels superseded runs, skips pushes that only touch root-level docs, and runs one macOS leg in private repos.
- Pin third-party actions to exact release tags or commit SHAs, and check the tag exists before using it. setup-uv publishes no moving major tags; `@v10` broke the first run. The tests enforce the pinning; actionlint does not check that tags exist.
- Azure DevOps has no organization yet. Its projects are always private: the hosted free tier (one job, 1,800 minutes a month) needs a linked Azure subscription, while one self-hosted agent is free.

### Implementation notes

- **tree-sitter is pinned** to `tree-sitter==0.25.2` and `tree-sitter-language-pack==0.13.0`. Language-pack 1.x downloads grammars at runtime, which would put network calls on hook paths and break offline machines; 0.13.0 is the last release that bundles them. The query API is only touched in `index/parser.py`.
- **argparse, not Typer**: Typer's import costs ~23 ms, a quarter of the prompt gate's budget, and every hook starts a `compass` process. Command modules import their heavy dependencies lazily.
- **Refresh is stat-based**: `compass index`, SessionStart and the git hooks compare size and mtime against the index, re-hash what moved, and re-parse what changed. That catches rebases, resets and stash pops as well as checkouts, so the git hooks do not diff HEADs. Files that are listed but not indexed (binaries, symlinks, oversized) sit in a `skipped` table so they are not re-read.
- **Rebuild triggers**: a change to any query file, the `index` config section or `INDEX_FORMAT` in `index/indexer.py` changes the index fingerprint, and the next run rebuilds from scratch. Bump `INDEX_FORMAT` whenever parser or shard output changes for the same input. ctags availability is deliberately *not* in the fingerprint, because PATH differs between a terminal and an IDE; after installing ctags, run `compass index --full`.
- **DB and shards stay in step**: shards are written inside the SQLite write transaction, so a failed shard write rolls the rows back and the next run retries. `compass index` (manual) also re-renders every shard as a repair pass.
- **`compass hook` bypasses argparse**: a usage error would exit 2, which Claude Code treats as "block". Hook stdin is read as UTF-8 bytes; Windows would otherwise decode it with the ANSI code page.
- **git hooks**: an existing hook is chained (renamed to `<hook>.compass-chained`) unless it dispatches on its own file name (symlinks, `basename "$0"`, husky 4). Those are left alone, as are all hooks when `core.hooksPath` is set; `init` then prints the line to add by hand.
- **Shard names**: `.compass/map/<dir>.md`, the repo root as `_root.md`, split parts as `<dir>~2.md`, `<dir>~3.md`. A directory named `_index` or `_root` gets an extra `_`, and `~` in directory names is doubled, so names never collide.
- **Determinism**: fresh builds are byte-identical (`index.db` and shards); a `--full` rebuild over an existing index matches except for three SQLite header counters.

## Conventions

- **Build order matters.** M1 index core → M2 query tools → M3 plugin + review manifest → M4 gates → M5 delegation → M6 telemetry. The deterministic core comes first because the code map and query tools cut tokens on their own and every later feature depends on them. The review manifest is deliberately built before the gates: it gives visible value on day one.
- **Dogfood from M2 onward.** Compass is used on its own repo.
- **Turn telemetry on early**, before M6 — baseline data from real sessions beats estimates.
- **Gate rules are tuned from the bypass log, not from guesses.** Defaults favour adoption: gates warn rather than block, `!quick` always bypasses, and every module can be switched off in `config.yaml`. The top project risk is developers disabling the plugin, not technical failure.
- **Anchor tags** `@ai:change`, `@ai:assume`, `@ai:review`, `@ai:todo` with a task id, written in the file's native comment syntax. The scanner is one regex with no per-language logic. A pre-commit hook blocks any commit still containing `@ai:`; `/accept <id>` strips them.
- **Never compare benchmark numbers across Compass versions or Claude Code versions.** Pin both, record them in the report, and rerun the full suite after any change that could affect results.

## Open questions

Recorded in the Requirements Spec and still undecided — don't quietly resolve one in code: the final product name; Python-only versus porting hot paths to Go or Rust; default prompt-gate strictness (warn or block); where the org-wide standards pack lives and who owns it; pilot repos, teams and local-LLM hardware; whether telemetry export is acceptable under company data policy. All eight ADRs are still **Proposed**, not accepted; M1 was built on them as written.
