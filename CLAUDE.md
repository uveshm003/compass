# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

**M1 (index core), M2 (query tools, Step 4) and M3 (plugin and review manifest, Steps 5–6) are implemented; M4 (gates and context pack) is next.** The repo holds the Python core under `src/compass/`, the Claude Code plugin under `plugin/`, its tests, and the five Markdown specs for Compass. `.docx` and `.pdf` exports of the specs live one directory up; the `.md` files here are the source of truth, and the exports predate M1.

What exists:
- **M1:** file enumeration and the stack profile (IX-01, IX-10), the tree-sitter indexer with a universal-ctags fallback (IX-02 to IX-05), map shards and the `_index.md` folder tree (IX-06, IX-09), and incremental updates from git hooks and the `compass hook post-edit` / `session-start` handlers (IX-07, IX-08).
- **M2:** call sites, imports resolved to files (IX-11) and test mapping (IX-12) in the index; the query engine (`query.py`) behind the stdio MCP server (`compass mcp`, QT-01 to QT-03, QT-05) and its CLI twins (QT-04).
- **M3:** the plugin (`plugin/`: hooks, the `/compass:accept` command, the `digest` subagent, an opt-in output style, the MCP registration) and a marketplace file at `.claude-plugin/marketplace.json` (CF-01); anchor tags, the task state, change manifests with local and hosted links, the Stop-hook anchor check, `compass accept` and the git pre-commit check (RO-01 to RO-05).

Gates, the context pack, delegation rules and telemetry do not exist yet. Two done-when checks need a real Claude Code session and so a manual run (see Testing): M2's "answered through Compass with zero Read calls" and M3's "a real task produces a manifest" (the scripted half, a commit with leftover tags being rejected, is covered by `tests/test_review.py`).

This repo dogfoods Compass through its own plugin. `uv tool install --editable .` puts this checkout's `compass` on PATH, and the plugin is installed for this project only: `claude plugin marketplace add ./ --scope local`, then `claude plugin install compass@compass-marketplace --scope local`, which land in the untracked `.claude/settings.local.json`. Claude Code runs a cached copy of `plugin/` pinned to a commit, so after changing it run `claude plugin update compass@compass-marketplace` and restart, or iterate with `claude --plugin-dir ./plugin`; changes under `src/` apply at once. `compass init` installed the git hooks here, including the pre-commit anchor check. `.compass/config.yaml` excludes `tests/fixtures/**`, `tests/snapshots/**` and `tests/schemas/**` from the map.

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
compass stack [--json]         # detected stack profile (twin of stack_profile)
compass mcp                    # the query tools as a stdio MCP server
compass find-symbol NAME       # twins of the MCP tools, same engine and text;
compass read-symbol NAME       #   add --json for structured output, or
compass file-outline PATH      #   --cursor 0 to page exactly as MCP does
compass map [DIR]
compass tests-for TARGET
compass importers-of TARGET
compass callers-of NAME
compass task [new]             # the active task (started if none), or a fresh one
compass manifest [ID]          # write .compass/changes/<id>.md; --hosted prints GitHub/Azure DevOps links, --json the data
compass accept [ID]            # strip a reviewed task's anchors, archive its manifest (what /compass:accept runs)
compass check-anchors [ID]     # list anchor tags; --staged is the git pre-commit check (exit 1 if a commit adds any)
compass uninstall              # remove Compass's git hooks, restoring any they chained (CF-04); keeps .compass/
compass hook <event>           # Claude Code hook entry point, JSON on stdin; always exits 0
```

Planned for later milestones: `compass enrich` (M5, background local-LLM summaries), `compass report` (M6), and the optional `compass watch` (IX-15). Hooks all route through `compass hook <session-start|prompt|pre-edit|post-edit|stop>`; all but `pre-edit` (M4's spec gate) are handled, and any other event name passes through with exit 0.

The plugin installs from this repo: `uv tool install .` for the CLI, then `claude plugin marketplace add ./` and `claude plugin install compass@compass-marketplace` (or `/plugin …` inside Claude Code). The same marketplace works from GitHub (`owner/repo`) and Azure Repos (the `https://dev.azure.com/…/_git/…` URL), NF-16. `claude plugin validate --strict plugin` checks the files locally without a model call.

### Testing

```bash
uv run pytest                     # unit, snapshot, determinism, hook-contract tests (~40 s, mostly subprocesses)
uv run pytest --perf              # also latency/footprint checks on a generated 100k LOC repo
uv run pytest --update-snapshots  # accept new output in tests/snapshots/ — review the diff first
COMPASS_TEST_CTAGS=/path/to/ctags uv run pytest tests/test_ctags.py   # real universal-ctags
```

`tests/test_query.py` covers every tool per language; `tests/test_mcp.py` drives the real server over stdio with the MCP client, as Claude Code does. The M2 done-when check runs a real headless Claude Code session and passes only if it answers through Compass with zero Read calls: `uv run python tests/e2e/check_query_tools.py`. It spends Claude usage, so pytest never runs it; ask before running it.

M3's tests: `tests/test_anchors.py` (scanner, stripper, staged-lines check), `tests/test_manifest.py` (grouping, links, hosted URLs for every GitHub and Azure DevOps remote form), `tests/test_review.py` (hook contracts for the whole review loop, `accept`, and real `git commit` runs against the pre-commit hook) and `tests/test_plugin.py` (plugin files against SchemaStore schemas vendored in `tests/schemas/`, hooks wired to handled events, versions in step, and `claude plugin validate --strict` when Claude Code is installed). Test files assemble tags at runtime (`AI = "@ai" + ":"`): a literal tag in Compass's own files would trip its own pre-commit check, and `test_compass_itself_carries_no_anchor_tags` enforces that.

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
- **The query engine keeps the index fresh itself.** No plugin hooks exist yet, and Bash or editor edits never reach them anyway. Every tool runs SessionStart's staleness check at most every 20 s, a tool about one file re-indexes it first if its stat changed, and `config.yaml` is re-read when it changes (the MCP server lives for a whole session). `read_symbol` and `file_outline` take line numbers from the file as it is on disk (one read, parsed with the same `parse_source`), so they stay right when another process holds the index lock; a symbol deleted since indexing is reported as such. Queries answer NotReady until the first build commits, rather than empty results. Later pages of an answer (a non-zero cursor) skip the freshness checks so pages come from one index state.
- **Concurrency**: the MCP SDK runs tool calls on worker threads, all sharing one `Queries`. Each call opens its own SQLite connection, tree-sitter parsing goes through a lock in `index/parser.py`, and the rate-limit and build-started state are locked.
- **Line numbers split on `\n` only** (`index.model.source_lines`), as tree-sitter and ctags count them; `str.splitlines()` also splits on form feeds, U+2028 and lone `\r` and shifts every later line.
- **MCP SDK v2** (`mcp>=2.2,<3`): `from mcp.server.mcpserver import MCPServer` (v2 renamed FastMCP); client types use snake_case (`input_schema`, `is_error`). The server imports in about 350 ms, paid once per Claude Code session, never on a hook path.
- **Index schema 2 / `INDEX_FORMAT` 2**: a `refs` table (call sites by callee name, found through `@reference.call` captures), `imports.resolved` (the repo file, or for Go the package directory) and `files.is_test`. `from pkg import models` is stored as target `pkg.models` (an `@import.member` capture), which resolves to `pkg/models.py` or, when `models` is not a module, to the package. Imports are re-resolved in full whenever a file is added or removed, or a `go.mod`, `tsconfig.json` or `jsconfig.json` (or a `tsconfig.*.json` it may extend) changes; otherwise only the edited files' imports. The resolver shares work across rows (one resolution per directory and target, one candidate search per module path), which keeps adding a file to an 80k LOC repo with 21k imports at about 200 ms in a fresh process. Resolver strategies (`path` with tsconfig `paths`/`baseUrl`, `module`, `package`) and test conventions live in each `language.yaml`; `queries/README.md` has the rules. Known gaps: Rust `use my_crate::Item` from integration tests (it needs the crate name from Cargo.toml) and JS/TS workspace packages imported by name.
- **Query answers**: `importers_of` gives one line per importing file, with the imported names compacted (`compass.query.{NotReady, Queries}`); for a directory it leaves out the directory's own files and says which of its files each importer uses; for a module name it matches submodules after the importer language's separator (`requests.adapters`, `react/jsx-runtime`, not `requests_toolbelt`). `tests_for` accepts a file, a bare file name, a directory (aggregated) or a symbol; name matching (`test_models.py` → `models.py`) picks the nearest same-named source by directory, so `b/utils.test.ts` is not also claimed for `a/utils.ts`. Pages fit `max_response_chars` including the cursor line, and cursors may be numbers or strings. CLI path arguments are relative to the current directory when they exist there, like `compass update`'s; MCP tools take repo-relative paths.

- **Plugin = thin shell-outs** (M3). `plugin/hooks/hooks.json` runs `compass hook <event>` from PATH with short timeouts (10–30 s), and `plugin/.mcp.json` runs `compass mcp`; nothing else in `plugin/` executes. A missing CLI shows up as a hook error notice, never a blocked session. `tests/test_plugin.py` fails if a hook names an event the core does not handle, or a handler is not wired.
- **Reply and anchor rules come from SessionStart context, not a forced output style.** The hook prints the query-tools rule, the four tag forms for the active task and the reply limit (`review.reply_max_lines`), so `review.enabled: false` turns them off (CF-03). `plugin/output-styles/compass-review.md` is the same rules as an opt-in style (`keep-coding-instructions: true`, never `force-for-plugin`, which would override the user's own style with no config switch).
- **Anchors** (`anchors.py`): one regex, `@ai:(change|assume|review|todo) <id> [—|-|:] note`, ids starting and ending alphanumeric. `@ai:` right after a backtick is a Markdown code span quoting a tag (the specs do this), and after a word character it is part of a word; neither counts. Stripping knows a short list of comment openers (`#`, `//`, `--`, `;`, `%`, `'`, `*`, `!` at line start; `#`, `//`, `--` after code, each with its whole run, so `///` and `##` go too) and block pairs (`/* */`, `<!-- -->`, `<%-- --%>`, `{# #}`, `{- -}`, `(* *)`, also opened as `/**`, `/*!`, `<!---`); a tag alone on its line deletes the line, a trailing tag removes just its comment, other bytes and line endings stay. In files matched by `review.anchor_exempt` (JSON and the like) tag-shaped text is data: the manifest, `accept` and the pre-commit check all skip it, so `accept` can never break a JSON file.
- **Tasks** (`state.py`, `.compass/state.json`, lock `state.lock`): an id `T<n>` is started implicitly the first time Compass needs one and stays active until `compass accept`; M4's `/task` will start tasks explicitly. Each task records the files Claude edited (PostToolUse), each session its current turn's files and whether the last Stop blocked. Ids never repeat: `accepted` keeps closed ids, and when state is lost, ids still used by tags in files or archived manifests are skipped. Writes take the lock and replace the file atomically (retried on Windows); an unreadable file reads as empty.
- **Stop hook** (`review.on_stop`): only acts when the session's turn changed files. It rewrites `.compass/changes/<task>.md`, then blocks with `{"decision": "block", "reason": …}` (exit 0) when a changed file has no tag for the task — skipping files matched by `review.anchor_exempt`, binaries and edits undone again — unless `stop_hook_active` is set or Compass blocked the previous Stop itself. Otherwise it returns a one-line `systemMessage` summary. A new prompt starts a new turn.
- **Manifests** (`manifest.py`): Review, Assumptions, TODO, Mechanical, "Changed without anchors", then a files table from `git diff HEAD --numstat` (new files count every line). Links are relative (`../../path#L12`). `accept` archives to `changes/archive/<id>.md` plus a `.json` twin, with each line moved to where the tagged code sits once standalone tag lines are gone, so `compass manifest <id> --hosted` gives valid PR links after the commit. Hosted links parse `origin`: GitHub and GitHub Enterprise, Azure DevOps (`dev.azure.com`, `ssh.dev.azure.com:v3`, legacy `*.visualstudio.com`, `vs-ssh`), GitLab; credentials in the remote URL are dropped.
- **Pre-commit hook**: `compass init` installs it next to the post-* hooks (chained the same way; a failing chained hook fails the commit). It runs `compass check-anchors --staged`, which looks only at lines the commit adds (renames count as added, since rename detection is off), so a tag quoted in an already committed file never blocks later commits. It reads `git diff --cached`, so `git commit -a` and partial staging are judged on exactly what is being committed. Internal errors let the commit through; `git commit --no-verify` is the escape hatch; `review.enabled: false` disables it. `compass task`, `manifest` and `accept` refuse to run before `compass init`, so they never create `.compass/` in a repo where the hooks should stay idle.
- **Hook start-up cost**: the prompt hook runs on every prompt against NF-01's 100 ms, so its common case (task already announced, nothing to reset) reads `state.json` and returns without loading config or YAML; `argparse` and `subprocess` are imported only where used. It takes about 30 ms on a Mac, some 10 ms above a bare interpreter start. The perf test checks both the absolute budget and Compass's own share, since Windows runners start processes several times slower.

## Conventions

- **Build order matters.** M1 index core → M2 query tools → M3 plugin + review manifest → M4 gates → M5 delegation → M6 telemetry. The deterministic core comes first because the code map and query tools cut tokens on their own and every later feature depends on them. The review manifest is deliberately built before the gates: it gives visible value on day one.
- **Dogfood from M2 onward.** Compass is used on its own repo.
- **Turn telemetry on early**, before M6 — baseline data from real sessions beats estimates.
- **Gate rules are tuned from the bypass log, not from guesses.** Defaults favour adoption: gates warn rather than block, `!quick` always bypasses, and every module can be switched off in `config.yaml`. The top project risk is developers disabling the plugin, not technical failure.
- **Anchor tags** `@ai:change`, `@ai:assume`, `@ai:review`, `@ai:todo` with a task id, written in the file's native comment syntax. The scanner is one regex with no per-language logic. A pre-commit hook blocks any commit that adds a tag; `/compass:accept <id>` strips them. When writing about tags in this repo, quote them in backticks or build them at runtime.
- **Never compare benchmark numbers across Compass versions or Claude Code versions.** Pin both, record them in the report, and rerun the full suite after any change that could affect results.

## Open questions

Recorded in the Requirements Spec and still undecided — don't quietly resolve one in code: the final product name; Python-only versus porting hot paths to Go or Rust; default prompt-gate strictness (warn or block); where the org-wide standards pack lives and who owns it; pilot repos, teams and local-LLM hardware; whether telemetry export is acceptable under company data policy. All eight ADRs are still **Proposed**, not accepted; M1 was built on them as written.
