# Compass — Architecture & Technical Design

Sep 23, 2026 · @Uvesh

## Architecture overview

Compass has three layers: a thin plugin that Claude Code loads, a local Python core that does all the work, and on-disk state under `.compass/`. The plugin holds no logic; every hook and tool calls into the core.

```mermaid
flowchart TD
  subgraph Plugin[Claude Code plugin]
    H[Hooks]
    A[Subagents]
    K[Commands + skills]
    O[Output style]
  end
  subgraph Core[compass core - Python]
    G[Gates + context pack]
    I[Indexer]
    Q[Query engine]
    M[Manifest + telemetry]
    L[Local LLM adapter]
  end
  subgraph State[.compass/ on disk]
    DB[(index.db)]
    SH[map shards]
    SP[specs + changes]
  end
  H --> G
  H --> I
  H --> M
  MCP[MCP server] --> Q
  Q --> DB
  I --> DB
  I --> SH
  G --> Q
  M --> SP
  L -.optional.-> Q
```

Keeping logic in the core means the same code serves Claude Code hooks, the MCP server, the developer's CLI and CI. It also keeps Compass portable to other agents later, since only the thin plugin layer is Claude Code specific.

The plugin layer reaches Claude Code in one of two install modes, both built from the same `plugin/` folder: as a marketplace plugin, or as plain files in `.claude/` that a team can commit (see [Installation and distribution](#installation-and-distribution), M7).

## Request lifecycle

A large task passes through five Compass touchpoints between the developer's prompt and an accepted change. Small tasks skip the spec steps.

```mermaid
sequenceDiagram
  participant D as Developer
  participant C as Claude Code
  participant X as Compass core
  participant S as Haiku subagent
  D->>C: /task prompt
  C->>X: UserPromptSubmit
  X-->>C: context pack, and what to ask about
  C->>X: find_symbol / read_symbol (MCP)
  C->>C: writes spec, open questions
  D->>C: answers, /approve
  C->>X: PreToolUse Write/Edit
  X-->>C: allowed
  C->>S: digest test output
  S-->>C: 20-line summary
  C->>X: Stop
  X-->>D: manifest link + telemetry row
  D->>C: /accept
```

The main model never sees raw test logs or whole files it only needed to locate things in.

## Execution tiers and routing

Every piece of work goes to the lowest tier that can do it correctly. Most savings come from Tier 0, because work that never reaches a model costs nothing.

| Tier | Executor | Latency | Handles | On the critical path? |
| --- | --- | --- | --- | --- |
| 0 | Scripts (core) | ms | Index, lookups, range reads, trees, manifests, gates | Yes |
| 1 | Local LLM | seconds | Summaries for undocumented symbols, bulk classification | No, background only |
| 2 | Haiku subagent | seconds | Digesting logs, tests and large files; mechanical edits from a spec | Yes, when input is large |
| 3 | Main model | normal | Design, logic, judgment, anything ambiguous | Yes |

### Routing rules

1. A question about where or what something is goes to Tier 0 query tools first.
2. Input over about 500 lines with a short expected output goes to Tier 2.
3. Work that needs judgment, or is under about 50 lines of input, stays in Tier 3; a subagent's fresh context would cost more than it saves.
4. Tier 1 is never awaited by a developer-facing step.

Rules 2 and 3 live in the CLAUDE.md fragment, which SessionStart prints, and in the subagent descriptions, since the main model makes the delegation call. Compass enforces what comes back: the SubagentStop hook sends an answer that breaks its subagent's output contract back once, and PreToolUse keeps the `scaffold` agent to the files it was given (DL-02).

## Data and storage layout

All state lives in one `.compass/` folder per repo. Team-owned inputs are committed; derived data is gitignored and can be rebuilt at any time with `compass index --full`.

| Path | Contents | Committed? |
| --- | --- | --- |
| `config.yaml` | Module toggles, gate rules, budgets, local-LLM settings | Yes |
| `standards/` | Team standards skills per stack | Yes (or linked from an org repo) |
| `specs/<id>.md` | Task specs with status and open questions | Team choice; recommended yes |
| `index.db` | SQLite: files (with a test-file flag), symbols, imports resolved to files, call sites | No |
| `map/` | Markdown shards per directory + `_index.md` | No |
| `changes/<id>.md` | Change manifests, each with a `.json` twin | No; moved to `changes/archive/` on `/compass:accept` |
| `state.json` | Active task id and size, each task's brief, touched files and spec approval, per-session turn state, the scaffold subagent's delegated files and edits | No |
| `stack.json`, `config.cache.json`, `llm.json` | Caches for the hooks: the stack summary from SessionStart, the parsed config, the local model's last health check | No |
| `summaries.db` | Local-model summaries of undocumented symbols, keyed by content hash (`compass enrich`) | No; kept by `compass index --full`, since only the local model can rebuild it |
| `telemetry.jsonl` | One row per turn and per subagent, tagged with its task: tokens per model, tool calls, prompts, active time, context Compass injected; never prompts or code. `compass report` rolls them up into tasks | No; the measurement record, which nothing can rebuild |
| `telemetry-offsets.json` | How far the hooks have read each session's and subagent's transcript | No |
| `logs/` | Hook errors (`errors.log`) and every prompt-gate decision, bypasses included (`gate.jsonl`) | No |

Shards are derived and fast to regenerate, so there is no reason to commit them and create merge conflicts.

The installer (M7) writes outside `.compass/`, into Claude Code's own folders, and records what it wrote:

| Path | Contents | Committed? |
| --- | --- | --- |
| `.claude/compass/install.json` (project) or `~/.claude/compass/install.json` (user) | Install record: version, mode, scope, each installed file with its hash, the settings and MCP entries added (IN-05) | Project scope: yes, with the rest of `.claude/` |
| `.claude/commands/compass/`, `.claude/agents/compass-*.md`, `.claude/output-styles/compass-review.md` | `files` mode only: the plugin's commands, agents and style | Project scope: yes |
| `.claude/settings.json` `hooks`, `.mcp.json` `mcpServers.compass` | `files` mode only: the `compass hook` entries and the MCP registration, merged into existing files (IN-08) | Project scope: yes |

## Configuration

One YAML file controls everything. Defaults favour adoption: the prompt gate never rejects a prompt, it has Claude ask about what is missing, and every module can be switched off.

```yaml
# .compass/config.yaml
version: 1

prompt_gate:
  enabled: true
  strictness: ask           # ask | strict (edits also wait for the answer) | off
  bypass_prefix: "!quick"
  required_fields: [goal, scope, acceptance]

context_pack:
  enabled: true
  token_budget: 1500

spec_gate:
  enabled: true
  large_task_when:
    files_mentioned_gte: 3
    keywords: [refactor, migrate, redesign, "new module"]
    except_one_function: true   # a keyword alone doesn't count for one function the map knows

index:
  exclude: ["**/generated/**", "**/*.min.js", "**/*.min.css", "**/*.js.map", "vendor/**",
            "**/*.lock", "**/package-lock.json", "**/pnpm-lock.yaml", "**/bun.lockb",
            "**/go.sum", "**/Package.resolved"]   # lockfiles: the stack profile reads them directly
  max_file_kb: 1024
  shard_token_limit: 2000

query:
  enabled: true             # the MCP query tools and the SessionStart rule to use them
  max_response_chars: 4000  # longer MCP answers end with a cursor (QT-05)
  context_lines: 3          # lines around a symbol in read_symbol (QT-02)

review:
  enabled: true
  require_anchors: true     # the Stop hook sends Claude back once to tag untagged changes
  reply_max_lines: 10
  anchor_exempt: ["**/*.json", "**/*.lock", "**/*.svg"]   # files that cannot hold comments (shortened)

delegation:
  enabled: true
  digest_threshold_lines: 500  # hand reading this much to a subagent when the answer is short
  enforce_contracts: true      # a subagent whose answer breaks its contract is sent back once

local_llm:
  enabled: false
  base_url: http://localhost:11434/v1  # loopback only: code never leaves the machine (NF-10)
  model: qwen2.5-coder:7b
  timeout_s: 30
  enrich_limit: 200            # symbols `compass enrich` summarises per run

telemetry:
  enabled: true      # per-turn tokens, time and tool counts in .compass/telemetry.jsonl; never prompts or code
  export: false      # or a file path: also append every row there, e.g. a folder the pilot owner collects
```

The model name above is only an example; pick whatever runs well on the team's hardware.

For the pilot's telemetry-only baseline, set `enabled: false` on `query`, `prompt_gate`, `context_pack`, `spec_gate`, `review` and `delegation`. Claude Code then runs as stock, while the Stop hook still records every turn, marked `compass: false`.

## Installation and distribution

M7, built in 0.3.0 (requirements IN-01 to IN-15, ADR 009; the work breakdown is in `docs/installer-plan.md`). The code is `src/compass/install/` and the npm wrapper `npm/`. The installer is a CLI command, never a hook, so it may use the network and exit non-zero. Nothing it installs changes what runs during a session.

```mermaid
flowchart LR
  N["npx compass-cc install"] -->|finds or installs uv| T["uv tool install compass==version"]
  U["uvx … compass install"] --> T
  T --> C["compass install"]
  C -->|plugin mode| P["claude plugin marketplace add, claude plugin install --scope"]
  C -->|files mode| F[".claude/ files, settings.json hooks, .mcp.json"]
  C --> I["compass init with a module preset"]
  C --> R["install record"]
```

- **One installer, two entry points.** `compass install` in `src/compass/install/` does the work. The npm package only finds or installs uv, installs the CLI at its own version and passes its arguments on (IN-12), so behaviour stays in the core. `uvx` alone is ephemeral and hooks need `compass` on PATH, so the installer always ends with a persistent `uv tool install`.
- **Two modes from one source.** `plugin` mode uses the public `claude plugin` CLI. `files` mode copies `plugin/commands/` to `.claude/commands/compass/` (so the command names stay `/compass:*`), `plugin/agents/<n>.md` to `.claude/agents/compass-<n>.md`, `plugin/skills/<n>/` to `.claude/skills/compass-<n>/` (so `/compass-<n>`), and the style. It also merges `hooks.json` into `settings.json`, and the MCP server into `.mcp.json` (project scope) or through `claude mcp add --scope user`. The wheel carries `plugin/` as package data. Installing both modes at once would run every hook twice, so the installer refuses and `compass doctor` reports it.
- **Agent names differ by mode.** Plugin agents are `compass:<n>`, file agents `compass-<n>`. The core accepts both for contracts, telemetry and the report, and SessionStart names them as the active mode does (IN-11). Telemetry rows record the mode (IN-14).
- **Upgrade and uninstall go by the install record.** A file whose hash still matches is replaced. An edited file is kept, with the new version written beside it as `.compass-new` when the release changed that file (not when it ships the version already recorded), and a deleted file stays deleted. Settings entries are found by their `compass hook ` prefix, every other key is left alone, and a backup is taken before the first write. Uninstall extends CF-04, so the touched files end up as they were.
- **No update check in hooks.** GSD checks for updates at session start. Compass doesn't, because that would be a network call on a hook path (NF-10). `compass upgrade` runs only when someone types it.
- **Hosts.** Python packages go to PyPI or an Azure Artifacts feed, the npm wrapper to npmjs, GitHub Packages or an Azure Artifacts npm feed, and git URLs work for both hosts (NF-16). Release jobs are defined identically in both CI systems.

## Extension points

Stack-agnosticism depends on these extension points being small and data-driven, so adding support never touches core code.

| To add | You provide | Where |
| --- | --- | --- |
| A language | A `language.yaml` (grammar, file matching, docstring, visibility, test and import-resolution rules), a `tags.scm` query (definitions and call sites) and an optional import query | `src/compass/queries/<lang>/` |
| A stack detector | A module with a `detect(repo) -> dict \| None` function reading one manifest type | `src/compass/stacks/` |
| A prompt-gate rule | A function `(prompt, config) -> list[missing_field]` | `src/compass/gate/rules/` |
| A test-mapping convention | Test-file globs and name affixes, e.g. `x.test.ts` tests `x.ts` | The language's `language.yaml` (`tests:` section) |
| A subagent | A Markdown file with frontmatter and an output contract | `plugin/agents/` |
| A skill (ST-04) | A `SKILL.md` folder in the shared shape (standards first, query tools, `stack_profile`, delegation, a bounded answer); `tests/test_plugin.py` checks the shape | `plugin/skills/<name>/` |
| A team standard | Markdown rules for all skills or one skill (ST-06) | `.compass/standards/all.md`, `.compass/standards/<skill>.md`, or the org repo |
| An install target (M7) | A module that maps `plugin/` onto one runtime's folders and settings; Claude Code is the only target in v1 (other agents are deferred for review, MT-01) | `src/compass/install/targets/` |

Every new language must come with a fixture repo and snapshot test before it counts as supported.

Hosting services follow the same pattern. GitHub Actions, Azure Pipelines and GitLab CI each have their own stack detector, and anything else tied to a hosting service, such as links to hosted views or distribution, must support both GitHub and Azure DevOps (NF-16). Everything that touches version control goes through plain git, so git hooks and file enumeration already behave the same on Azure Repos as on GitHub.

## Failure modes

Compass must never make Claude Code worse than stock. Any failure other than a deliberate gate decision exits 0 and logs to `.compass/logs/`.

| Failure | Behaviour | User sees |
| --- | --- | --- |
| Hook raises an exception | Exit 0, error logged | Nothing; session continues |
| Index missing or corrupt | SessionStart triggers a rebuild in the background; query tools answer "index not ready" | One-line notice |
| Hook exceeds its time budget | Context pack returns what it has so far | Smaller context pack |
| Local LLM unreachable | Local features disabled for the session; `compass enrich` does nothing | Nothing |
| Subagent answer breaks its contract | SubagentStop sends it back once with the reason; the retry always passes | A slightly longer delegation |
| `scaffold` edits a file it was not given | PreToolUse refuses the edit and names the allowed files; the agent reports back | The subagent's report names the file |
| Stop hook would block twice in a row | Second block skipped (`stop_hook_active` check, plus Compass's own record of its last block) | Normal stop |
| `compass` CLI not installed but the plugin is | Each hook command fails to start; Claude Code treats that as a non-blocking error | A hook error notice; session continues |
| Pre-commit check fails internally | Commit allowed, error logged | Nothing |
| Spec gate blocks a genuinely small edit | Developer runs `!quick` or `/approve` | Clear message naming the fix |
| Config file invalid | Defaults used; warning printed once per session | One-line warning |
| Installer phase fails (M7) | The files that phase wrote are rolled back; exit non-zero (the installer is not a hook) | What is in place; running the installer again finishes the job |
| `settings.json` does not parse | The installer refuses to touch it | The path and the parse error |
| Plugin and `files` mode both installed | `install` refuses to add the second; `doctor` reports it | How to switch modes |
| An upgrade meets an edited Compass file | The edit is kept; if the release changed the file, the new version is written beside it as `.compass-new` | The list of kept files |

## Architecture decision records

The first eight decisions were proposed for review before M1 started; ADR 009 was added with the M7 plan. New decisions get the next ADR number and one row here; a superseded ADR stays listed with its replacement noted.

| ADR | Decision | Why | Trade-off accepted | Status |
| --- | --- | --- | --- | --- |
| 001 | Build as a Claude Code plugin, not a wrapper CLI | Uses supported extension points; survives Claude Code updates | Limited to what hooks, subagents and MCP expose | Proposed |
| 002 | tree-sitter for parsing, universal-ctags as fallback | One parser framework covers 100+ languages; incremental and robust to syntax errors | Tags queries must be maintained per language | Proposed |
| 003 | SQLite as source of truth, Markdown shards as the LLM view | Fast structured queries plus token-cheap reading | Two representations to keep in sync | Proposed |
| 004 | Python for v1 | Fastest to build; mature tree-sitter and MCP bindings | Start-up time and packaging; revisit Go or Rust for hot paths after the pilot | Proposed |
| 005 | Local LLMs via MCP tools, not by remapping a model tier through a gateway | Small local models are unreliable at agentic tool calling; tools only need plain completions | No local model for interactive agent turns | Proposed |
| 006 | Deterministic rules for the prompt gate | Must run under 100 ms on every prompt with no token cost | Rules are cruder than an LLM judge; tuned from logs | Proposed |
| 007 | Anchor tags in code, stripped before commit | Reviewers see marks in context in any editor; no editor plugin needed | Extra comment noise until `/accept` | Proposed |
| 008 | stdio-only MCP server | No open ports; nothing reachable from the network | One server process per Claude Code session | Proposed |
| 009 | One installer in the Python CLI (`compass install`), with a logic-free npm wrapper, installing either as a plugin or as files in `.claude/` from the same `plugin/` source | One-command setup like GSD and BMAD, without splitting behaviour across two languages; `files` mode lets a team commit Compass with its repo; both stay on public extension points (ADR 001) | Two install modes to test; agent names differ by mode; npm and Python packages to publish in step | Proposed |
