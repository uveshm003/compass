# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**M1 (index core), M2 (query tools, Step 4), M3 (plugin and review manifest, Steps 5–6), M4 (gates and context pack, Step 7) and M5 (delegation and the local-LLM adapter, Step 8) are implemented; M6 (telemetry and benchmark, Step 9) is next.** The repo holds the Python core under `src/compass/`, the Claude Code plugin under `plugin/`, its tests, and the five Markdown specs for Compass. `.docx` and `.pdf` exports of the specs live one directory up; the `.md` files here are the source of truth, and the exports predate M1.

What exists:
- **M1:** file enumeration and the stack profile (IX-01, IX-10), the tree-sitter indexer with a universal-ctags fallback (IX-02 to IX-05), map shards and the `_index.md` folder tree (IX-06, IX-09), and incremental updates from git hooks and the `compass hook post-edit` / `session-start` handlers (IX-07, IX-08).
- **M2:** call sites, imports resolved to files (IX-11) and test mapping (IX-12) in the index; the query engine (`query.py`) behind the stdio MCP server (`compass mcp`, QT-01 to QT-03, QT-05) and its CLI twins (QT-04).
- **M3:** the plugin (`plugin/`: hooks, the `/compass:accept` command, the `digest` subagent, an opt-in output style, the MCP registration) and a marketplace file at `.claude-plugin/marketplace.json` (CF-01); anchor tags, the task state, change manifests with local and hosted links, the Stop-hook anchor check, `compass accept` and the git pre-commit check (RO-01 to RO-05).
- **M4:** the prompt gate (`gate/`, PG-01 to PG-05, with `/compass:task`), the context pack (`gate/pack.py`, CP-01 to CP-03), the spec gate (`spec.py` plus the PreToolUse hook, SG-01 to SG-05, with `/compass:approve`), and the stack with installed versions at SessionStart (ST-02).
- **M5:** the `test-runner` and `scaffold` subagents next to `digest` (DL-01); their output contracts, enforced by the SubagentStop hook and, for scaffold's files, the PreToolUse hooks (`delegation.py`, DL-02); the delegation rules at SessionStart (DL-03); the loopback-only local-LLM client (`llm.py`) with the `summarize_file` and `classify_files` MCP tools (`local_tools.py`, DL-04) and background `compass enrich` (`enrich.py`, DL-05). Every local feature is simply absent when no model answers (DL-06).

Telemetry does not exist yet. The M2 to M5 done-when checks run real headless Claude Code sessions, so they are scripts rather than pytest tests (see Testing). All passed on 2026-09-24 with Claude Code 2.1.281 and claude-opus-5-5. M2: "where is retry handled and what calls it?" was answered with `find_symbol`, `read_symbol` and `callers_of` and zero Read, Grep or Glob calls. M3: on the Python, TypeScript and Go fixtures the change got anchors and a manifest, the reply stayed under 12 lines, the commit with tags was refused, and it went through after `compass accept`. M4: block mode refused "improve the error handling" before the model ran; warn mode had Claude ask which code to focus on and change nothing; a refactor got a spec draft with four open questions and no code edits, then was implemented, tagged, after `compass approve`. M5: asked to run a suite whose `python3 -m unittest -v` output is 623 lines, Claude handed the run to `compass:test-runner` and got back an 8-line answer naming both failures (3 of 3 runs, once the rule said that `tail` output counts too; 1 of 2 before); with gemma3 on Ollama a commit took 0.20 s with `local_llm` on or off, and the summaries reached the map afterwards.

This repo dogfoods Compass through its own plugin. `uv tool install --editable .` puts this checkout's `compass` on PATH, and the plugin is installed for this project only: `claude plugin marketplace add ./ --scope local`, then `claude plugin install compass@compass-marketplace --scope local`, which land in the untracked `.claude/settings.local.json`. Claude Code runs a cached copy of `plugin/` pinned to a commit, and `claude plugin update` only notices a new version number, so after changing `plugin/` reinstall (`claude plugin uninstall compass@compass-marketplace --scope local`, then install again) and restart, or iterate with `claude --plugin-dir ./plugin`; changes under `src/` apply at once. A release that changes `plugin/` should bump the version in `plugin.json` and `pyproject.toml` together (`tests/test_plugin.py` checks they match), so installed copies update. `compass init` installed the git hooks here, including the pre-commit anchor check. `.compass/config.yaml` excludes `tests/fixtures/**`, `tests/snapshots/**` and `tests/schemas/**` from the map.

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
3. **State** (`.compass/` in each target repo) — `config.yaml` and `standards/` are committed; `index.db`, `map/`, `changes/`, `state.json`, `telemetry.jsonl` and `logs/` are derived, gitignored and rebuildable with `compass index --full`. `summaries.db` (local-model summaries) is gitignored too, but only `compass enrich` can rebuild it, so `--full` keeps it.

### Tier routing — the idea everything else serves

| Tier | Executor | Handles |
| --- | --- | --- |
| 0 | Scripts (core) | Index, lookups, range reads, trees, manifests, gates |
| 1 | Local LLM | Undocumented-symbol summaries, bulk classification — background only, never awaited |
| 2 | Haiku subagent | Digesting logs, tests and large files; mechanical edits from a spec |
| 3 | Main model | Design, logic, judgment, anything ambiguous |

Most of the savings come from Tier 0, because work that never reaches a model costs nothing. The delegation thresholds (input over ~500 lines with short expected output → Tier 2; under ~50 lines or needs judgment → stays Tier 3) are rules for the main model, in the "CLAUDE.md fragment" SessionStart prints (`delegation.rules`) and the subagent descriptions, **not** routing logic in core code, because the main model makes the delegation call itself. Core code only holds each subagent to its output contract.

### Invariants to preserve

These are decided, and code that violates them is wrong even if it works:

- **Fail open.** Any Compass error exits 0 and logs to `.compass/logs/`. The only non-zero exits are deliberate gate decisions (prompt gate in block mode, spec gate, the scaffold subagent editing a file it was not given); the Stop and SubagentStop checks answer with a JSON block decision and exit 0. Compass must never make Claude Code worse than stock.
- **No network calls in hooks**, except the optional local-LLM health check, and that only to a loopback address (NF-10).
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
compass stack [--json]         # detected stack profile (twin of stack_profile)
compass mcp                    # the query tools as a stdio MCP server
compass find-symbol NAME       # twins of the MCP tools, same engine and text;
compass read-symbol NAME       #   add --json for structured output, or
compass file-outline PATH      #   --cursor 0 to page exactly as MCP does
compass map [DIR]
compass tests-for TARGET
compass importers-of TARGET
compass callers-of NAME
compass task [new]             # the active task (started if none), or a fresh one; --brief - is what /compass:task runs
compass approve [ID]           # approve a large task's spec (what /compass:approve runs); records who and when
compass check-prompt TEXT      # dry-run the prompt gate and context pack on a prompt; changes nothing
compass manifest [ID]          # write .compass/changes/<id>.md; --hosted prints GitHub/Azure DevOps links, --json the data
compass accept [ID]            # strip a reviewed task's anchors, archive its manifest (what /compass:accept runs)
compass check-anchors [ID]     # list anchor tags; --staged is the git pre-commit check (exit 1 if a commit adds any)
compass uninstall              # remove Compass's git hooks, restoring any they chained (CF-04); keeps .compass/
compass enrich [--limit N]     # local-model summaries for undocumented symbols (DL-05); the git hooks start it
compass summarize-file PATH    # twins of the local-model MCP tools (DL-04); --focus asks something specific
compass classify-files PATHS… --labels a,b
compass hook <event>           # Claude Code hook entry point, JSON on stdin; exits 0 except deliberate gate decisions
```

Planned for later milestones: `compass report` (M6) and the optional `compass watch` (IX-15). Hooks all route through `compass hook <session-start|prompt|pre-edit|post-edit|stop|delegate|subagent-stop>`, all handled; any other event name passes through with exit 0.

The plugin installs from this repo: `uv tool install .` for the CLI, then `claude plugin marketplace add ./` and `claude plugin install compass@compass-marketplace` (or `/plugin …` inside Claude Code). The same marketplace works from GitHub (`owner/repo`) and Azure Repos (the `https://dev.azure.com/…/_git/…` URL), NF-16. `claude plugin validate --strict plugin` checks the files locally without a model call.

### Testing

```bash
uv run pytest                     # unit, snapshot, determinism, hook-contract tests (~60 s, mostly subprocesses)
uv run pytest --perf              # also latency/footprint checks on a generated 100k LOC repo
uv run pytest --update-snapshots  # accept new output in tests/snapshots/ — review the diff first
COMPASS_TEST_CTAGS=/path/to/ctags uv run pytest tests/test_ctags.py   # real universal-ctags
```

`tests/test_query.py` covers every tool per language; `tests/test_mcp.py` drives the real server over stdio with the MCP client, as Claude Code does. The done-when checks run real headless Claude Code sessions, so pytest never runs them. `uv run python tests/e2e/check_query_tools.py` (M2) passes only if Claude answers through Compass with zero Read calls. `uv run python tests/e2e/check_review_loop.py [--fixture python_app|ts_app|go_app]` (M3) loads the plugin with `--plugin-dir` and has Claude make a small change, then checks the manifest, the tags, the reply length, the refused commit and the commit after accept. `uv run python tests/e2e/check_gates.py` (M4) runs block mode, warn mode and a large task through its spec, approval and implementation (a resumed session). `uv run python tests/e2e/check_delegation.py [--local-model gemma3]` (M5) asks Claude to run a 600-test suite with two failures and passes only if the run went to a Compass subagent, never to the main conversation's Bash, and came back short; with `--local-model` it also commits with `local_llm` on and off, compares the times and waits for the summaries (it needs a model already running, for example `ollama serve`; `--skip-session` runs only that part, with no Claude usage). Each costs roughly 1–7k output tokens. Neither can use `--bare`, which accepts only an API key and never a claude.ai login, so they keep other MCP servers out with `--strict-mcp-config` instead.

M5's tests are `tests/test_delegation.py` (the contracts, the SubagentStop, Agent and scaffold pre-edit hook contracts, binding parallel delegations, the SessionStart rules) and `tests/test_llm.py` (the client, the local tools, enrichment end to end and a real commit), both against `tests/fake_llm.py`, an OpenAI-compatible server on 127.0.0.1 that records every request; `tests/test_mcp.py` checks the local tools come and go with the model. M4's tests are `tests/test_gates.py`: prompt kinds, candidate names, labels, every rule, rule discovery, sizing, the pack against an indexed fixture, specs and approval, and the prompt and pre-edit hook contracts end to end. M3's tests: `tests/test_anchors.py` (scanner, stripper, staged-lines check), `tests/test_manifest.py` (grouping, links, hosted URLs for every GitHub and Azure DevOps remote form), `tests/test_review.py` (hook contracts for the whole review loop, `accept`, and real `git commit` runs against the pre-commit hook) and `tests/test_plugin.py` (plugin files against SchemaStore schemas vendored in `tests/schemas/`, hooks wired to handled events, versions in step, and `claude plugin validate --strict` when Claude Code is installed). Test files assemble tags at runtime (`AI = "@ai" + ":"`): a literal tag in Compass's own files would trip its own pre-commit check, and `test_compass_itself_carries_no_anchor_tags` enforces that.

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
- **Query tools** (M2): `query.py` holds all behaviour; `mcp_server.py` is thin wrappers whose descriptions say when to prefer each tool over Read, Grep and Glob. The server instructions carry Step 4's rule: read whole files only to edit them. Answers are compact text in the shard format rather than JSON, capped at `query.max_response_chars` with a `cursor` to continue; `--json` on the CLI twins returns structured data.
- **The query engine keeps the index fresh itself.** Bash and editor edits never reach the plugin's hooks, so every tool runs SessionStart's staleness check at most every 20 s, a tool about one file re-indexes it first if its stat changed, and `config.yaml` is re-read when it changes (the MCP server lives for a whole session). `read_symbol` and `file_outline` take line numbers from the file as it is on disk (one read, parsed with the same `parse_source`), so they stay right when another process holds the index lock; a symbol deleted since indexing is reported as such. Queries answer NotReady until the first build commits, rather than empty results. Later pages of an answer (a non-zero cursor) skip the freshness checks so pages come from one index state.
- **Concurrency**: the MCP SDK runs tool calls on worker threads, all sharing one `Queries`. Each call opens its own SQLite connection, tree-sitter parsing goes through a lock in `index/parser.py`, and the rate-limit and build-started state are locked.
- **Line numbers split on `\n` only** (`index.model.source_lines`), as tree-sitter and ctags count them; `str.splitlines()` also splits on form feeds, U+2028 and lone `\r` and shifts every later line.
- **MCP SDK v2** (`mcp>=2.2,<3`): `from mcp.server.mcpserver import MCPServer` (v2 renamed FastMCP); client types use snake_case (`input_schema`, `is_error`). The server imports in about 350 ms, paid once per Claude Code session, never on a hook path.
- **Index schema 2 / `INDEX_FORMAT` 2**: a `refs` table (call sites by callee name, found through `@reference.call` captures), `imports.resolved` (the repo file, or for Go the package directory) and `files.is_test`. `from pkg import models` is stored as target `pkg.models` (an `@import.member` capture), which resolves to `pkg/models.py` or, when `models` is not a module, to the package. Imports are re-resolved in full whenever a file is added or removed, or a `go.mod`, `tsconfig.json` or `jsconfig.json` (or a `tsconfig.*.json` it may extend) changes; otherwise only the edited files' imports. The resolver shares work across rows (one resolution per directory and target, one candidate search per module path), which keeps adding a file to an 80k LOC repo with 21k imports at about 200 ms in a fresh process. Resolver strategies (`path` with tsconfig `paths`/`baseUrl`, `module`, `package`) and test conventions live in each `language.yaml`; `queries/README.md` has the rules. Known gaps: Rust `use my_crate::Item` from integration tests (it needs the crate name from Cargo.toml) and JS/TS workspace packages imported by name.
- **Query answers**: `importers_of` gives one line per importing file, with the imported names compacted (`compass.query.{NotReady, Queries}`); for a directory it leaves out the directory's own files and says which of its files each importer uses; for a module name it matches submodules after the importer language's separator (`requests.adapters`, `react/jsx-runtime`, not `requests_toolbelt`). `tests_for` accepts a file, a bare file name, a directory (aggregated) or a symbol; name matching (`test_models.py` → `models.py`) picks the nearest same-named source by directory, so `b/utils.test.ts` is not also claimed for `a/utils.ts`. Pages fit `max_response_chars` including the cursor line, and cursors may be numbers or strings. CLI path arguments are relative to the current directory when they exist there, like `compass update`'s; MCP tools take repo-relative paths.

- **Plugin = thin shell-outs** (M3). `plugin/hooks/hooks.json` runs `compass hook <event>` from PATH with short timeouts (10–30 s), and `plugin/.mcp.json` runs `compass mcp`; nothing else in `plugin/` executes. A missing CLI shows up as a hook error notice, never a blocked session. `tests/test_plugin.py` fails if a hook names an event the core does not handle, or a handler is not wired.
- **Reply and anchor rules come from SessionStart context, not a forced output style.** The hook prints the query-tools rule, the four tag forms for the active task and the reply limit (`review.reply_max_lines`), so `review.enabled: false` turns them off (CF-03). `plugin/output-styles/compass-review.md` is the same rules as an opt-in style (`keep-coding-instructions: true`, never `force-for-plugin`, which would override the user's own style with no config switch).
- **Anchors** (`anchors.py`): one regex, `@ai:(change|assume|review|todo) <id> [—|-|:] note`, ids starting and ending alphanumeric. `@ai:` right after a backtick is a Markdown code span quoting a tag (the specs do this), and after a word character it is part of a word; neither counts. Stripping knows a short list of comment openers (`#`, `//`, `--`, `;`, `%`, `'`, `*`, `!` at line start; `#`, `//`, `--` after code, each with its whole run, so `///` and `##` go too) and block pairs (`/* */`, `<!-- -->`, `<%-- --%>`, `{# #}`, `{- -}`, `(* *)`, also opened as `/**`, `/*!`, `<!---`); a tag alone on its line deletes the line, a trailing tag removes just its comment, other bytes and line endings stay. In files matched by `review.anchor_exempt` (JSON and the like) tag-shaped text is data: the manifest, `accept` and the pre-commit check all skip it, so `accept` can never break a JSON file.
- **Tasks** (`state.py`, `.compass/state.json`, lock `state.lock`): an id `T<n>` is started by `/compass:task` or implicitly the first time Compass needs one, and stays active until `compass accept`. The first request of a task becomes its brief and sets its size; a large task also carries its spec approval. Each task records the files Claude edited (PostToolUse), each session its current turn's files and whether the last Stop blocked. Ids never repeat: `accepted` keeps closed ids, and when state is lost, ids still used by tags in files or archived manifests are skipped. Writes take the lock and replace the file atomically (retried on Windows); an unreadable file reads as empty.
- **Stop hook** (`review.on_stop`): only acts when the session's turn changed files. It rewrites `.compass/changes/<task>.md`, then blocks with `{"decision": "block", "reason": …}` (exit 0) when a changed file has no tag for the task — skipping files matched by `review.anchor_exempt`, binaries and edits undone again — unless `stop_hook_active` is set or Compass blocked the previous Stop itself. Otherwise it returns a one-line `systemMessage` summary. A new prompt starts a new turn.
- **Manifests** (`manifest.py`): Review, Assumptions, TODO, Mechanical, "Changed without anchors", then a files table from `git diff HEAD --numstat` (new files count every line). Links are relative (`../../path#L12`). `accept` archives to `changes/archive/<id>.md` plus a `.json` twin, with each line moved to where the tagged code sits once standalone tag lines are gone, so `compass manifest <id> --hosted` gives valid PR links after the commit. Hosted links parse `origin`: GitHub and GitHub Enterprise, Azure DevOps (`dev.azure.com`, `ssh.dev.azure.com:v3`, legacy `*.visualstudio.com`, `vs-ssh`), GitLab; credentials in the remote URL are dropped.
- **Pre-commit hook**: `compass init` installs it next to the post-* hooks (chained the same way; a failing chained hook fails the commit). It runs `compass check-anchors --staged`, which looks only at lines the commit adds (renames count as added, since rename detection is off), so a tag quoted in an already committed file never blocks later commits. It reads `git diff --cached`, so `git commit -a` and partial staging are judged on exactly what is being committed. Internal errors let the commit through; `git commit --no-verify` is the escape hatch; `review.enabled: false` disables it. `compass task`, `manifest` and `accept` refuse to run before `compass init`, so they never create `.compass/` in a repo where the hooks should stay idle.
- **Hook start-up cost**: the prompt hook runs on every prompt against NF-01's 100 ms, so its common case (a reply, a question or a follow-up that names no code, with nothing to announce) reads `state.json` and returns without loading config or opening the index; `argparse`, `subprocess` and the manifest code are imported only where used. The parsed config is cached in `.compass/config.cache.json`, keyed on `config.yaml`'s bytes and `config.py`'s source, so YAML is imported only when either changes. On a Mac the fast path takes about 30 ms, the gate on a new request about 50 ms, and gate plus pack for five names about 55 ms (p95 60–80 ms). The perf tests check both the absolute budgets and Compass's own share over a bare interpreter start, since Windows runners start processes several times slower.
- **The prompt gate checks only prompts that start a task** (`gate/`). Each prompt gets a kind: `command` (starts with `/`), `bypass` (the `!quick` prefix), `question` (opens with a question word, or ends with `?`, unless it opens with a task verb: "can you add…" is a request), `reply` (under four words, no task verb: "yes", "go ahead") or `task`. Only a `task` prompt while the active task is fresh (no brief, nothing edited) is checked; follow-ups inside a task are not, which keeps the gate quiet enough to stay installed. Rules are modules in `gate/rules/` (`FIELD`, `check(prompt, config) -> list[missing]`), run for `prompt_gate.required_fields`, and err towards passing: a path, backticks or a code name counts as scope; `should`/`when`/`if`, a number, a test or a behaviour ("raise", "return", "give up") counts as acceptance; renames and deletes carry their own. Warn mode (the default) answers with `additionalContext` telling Claude to ask, plus a `systemMessage` for the developer; block mode exits 2 with the checklist on stderr and leaves the task fresh. `strictness: off` works unquoted even though YAML reads it as false. Every decision goes to `.compass/logs/gate.jsonl` (prompt excerpts only for warn, block and bypass), the log rules are tuned from; `compass check-prompt` replays one prompt without changing anything.
- **Context pack** (`gate/pack.py`): candidates are backticked text, path-like tokens and code-shaped names (CamelCase, snake_case, `a.b`, `f()`); plain words never. Each resolves read-only against the index to a symbol (`path:line` signature and doc), a file outline, a directory listing or basename matches, then the tests that import or are named after those files, a version line for any framework or tool the prompt names (from `.compass/stack.json`, written at SessionStart), and "did you mean" for misspelt names. An unresolved name with no close match is not mentioned, so `ValueError` or `React` add nothing. Cut at `context_pack.token_budget`, highest-value lines first.
- **Spec gate** (`spec.py`, `gate/hook.py`): a task is large when its brief matches a `spec_gate.large_task_when` keyword (word prefixes: "refactor" finds "refactoring") or names `files_mentioned_gte` files: paths the code map knows, or new files written with an extension, but not a directory named as a filter ("under lib/") and never `.compass/`. A large task gets `.compass/specs/<id>.md` (front matter `status: draft`, the brief's fields, an Open questions checklist) and Claude is told to fill it and stop. PreToolUse on Write/Edit exits 2 for any other path in the repo until approved; files outside the repo pass. The approval that counts lives in `state.json`, written by `compass approve` (which also stamps the front matter with `approved_by` git user.name and `approved_at`), so Claude editing `status:` in the spec approves nothing, and `state.json` is among the files the gate protects. `!quick` lifts the gate for one turn. `/compass:task` passes its brief through a quoted heredoc (`<<'COMPASS_BRIEF'`), so the shell never expands it; the command's `!` block runs before UserPromptSubmit, which sees the raw `/compass:task …` and skips it as a command.

- **Delegation rules and contracts** (`delegation.py`). With `delegation.enabled`, SessionStart prints the rules (DL-03):
  - `compass:test-runner` for every test suite and build. The rule says that `tail` or `grep` output still lands in context, which was added after a session ran `unittest -v | tail -150` itself.
  - `compass:digest` for reading more than `delegation.digest_threshold_lines`.
  - `compass:scaffold` for edits that can be spelled out.
  - Small or judgment-heavy work stays inline.
  - The local tools are listed when a model answers.

  SubagentStop (`compass hook subagent-stop`) checks the `last_assistant_message` of `compass:*` agents against `CONTRACTS`. digest may use at most 30 lines, with code blocks of at most 5 lines, and must cite a `file:line` or log line when it runs past one line. test-runner may use at most 20 lines. An answer that breaks its contract is blocked once with the reason, and the retry (`stop_hook_active`) always passes. Subagents from other plugins are never checked. `delegation.enforce_contracts: false` switches the checks off.
- **Scaffold's files**:
  - PreToolUse on `Agent|Task` (`compass hook delegate`) records the paths a scaffold delegation's prompt names in `state.json`: `pending`, per session, for at most an hour, at most 10 entries.
  - Claude Code gives the Agent call no link to the agent it starts, so the agent is bound at its first edit: to the oldest pending delegation that names that file, else the oldest one. Parallel agents start editing in any order, and an agent that edits only its own files always finds its own delegation.
  - From then on, PreToolUse on Write/Edit exits 2 for any file outside those paths and the task spec's paths. A file name matches as a path suffix, and a directory covers everything below it. With no delegation recorded, nothing is refused (fail open).
  - PostToolUse records each subagent's edits under its `agent_id`. They also count for the task and its manifest.
  - At SubagentStop, with review on, every file scaffold changed must carry a tag for the task.
- **Local LLM** (`llm.py`): plain OpenAI-compatible HTTP through urllib, with no SDK to pin.
  - Only loopback `base_url`s count (`localhost`, `127.0.0.0/8`, `::1`; not `0.0.0.0`). Proxies are bypassed, so `HTTP_PROXY` cannot route code off the machine (NF-10).
  - The health check (`GET /models` within 1 s, with the configured model or `<model>:latest` listed) is cached in `.compass/llm.json` for 5 minutes, so SessionStart never waits on a missing model twice.
  - `compass mcp` probes once at start-up (2 s) and registers `summarize_file` and `classify_files` only when the model answers. They return the model's short answer, never the file.
- **Enrichment** (`enrich.py`):
  - When `local_llm.enabled`, `compass update --from-git` (the post-* git hooks) starts `compass enrich` detached, under `nice -n 10` (below-normal priority on Windows). No Claude Code hook ever starts it.
  - It summarises undocumented functions, methods, classes and types: the first 80 lines of each, at temperature 0, up to `local_llm.enrich_limit` per run.
  - Each summary is cached by a blake2b of the symbol's kind, name and source text in `.compass/summaries.db`, then written under the index lock into the index (`doc_source = 'generated'`) and the shards (`~`).
  - The indexer re-applies cached summaries whenever it parses a file. Rebuilds keep them, and a symbol whose code changed loses its summary until the next run. Symbols in files changed since indexing also wait for the next run.
  - Answers are cut to one line of at most 120 characters; refusals are dropped. Three failed calls end a run.
  - One run goes at a time (`enrich.lock`). A run that finds another going leaves `enrich.again`, and the running one makes another pass, so a rebase costs one extra pass rather than a process per commit.


## Conventions

- **Build order matters.** M1 index core → M2 query tools → M3 plugin + review manifest → M4 gates → M5 delegation → M6 telemetry. The deterministic core comes first because the code map and query tools cut tokens on their own and every later feature depends on them. The review manifest is deliberately built before the gates: it gives visible value on day one.
- **Dogfood from M2 onward.** Compass is used on its own repo.
- **Turn telemetry on early**, before M6 — baseline data from real sessions beats estimates.
- **Gate rules are tuned from the bypass log, not from guesses.** Defaults favour adoption: gates warn rather than block, `!quick` always bypasses, and every module can be switched off in `config.yaml`. The top project risk is developers disabling the plugin, not technical failure.
- **Anchor tags** `@ai:change`, `@ai:assume`, `@ai:review`, `@ai:todo` with a task id, written in the file's native comment syntax. The scanner is one regex with no per-language logic. A pre-commit hook blocks any commit that adds a tag; `/compass:accept <id>` strips them. When writing about tags in this repo, quote them in backticks or build them at runtime.
- **Never compare benchmark numbers across Compass versions or Claude Code versions.** Pin both, record them in the report, and rerun the full suite after any change that could affect results.

## Open questions

Recorded in the Requirements Spec and still undecided — don't quietly resolve one in code: the final product name; Python-only versus porting hot paths to Go or Rust; default prompt-gate strictness (warn or block); where the org-wide standards pack lives and who owns it; pilot repos, teams and local-LLM hardware; whether telemetry export is acceptable under company data policy. All eight ADRs are still **Proposed**, not accepted; M1 was built on them as written.
