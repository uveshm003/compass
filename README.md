# Compass

A Claude Code plugin plus a local CLI that routes work to the cheapest executor
that can do it correctly, and makes AI changes reviewable. The design lives in
the five `Compass — *.md` specs in this directory; `CLAUDE.md` summarises them.

**Status:** M1 to M5 are done: a tree-sitter code map in SQLite and Markdown
shards, kept current by git hooks and Claude Code hooks, served by a stdio MCP
server whose every tool also has a CLI twin; a Claude Code plugin that has
Claude tag each change for review, writes a change manifest every turn and
refuses commits that still carry the tags; the gates: vague requests get a
checklist, every prompt gets the code-map lines for the names it mentions, and
a large task changes no code until its spec is approved; and delegation: Haiku
subagents run tests, digest large inputs and make spelled-out edits, each held
to an output contract, while an optional local model summarises files and
undocumented symbols at no token cost. M6 measures it all: every turn's
tokens, time and tool calls from Claude Code's own transcripts, a report that
compares tasks with Compass on and off, and a benchmark harness for the
Evaluation Plan.

## Guides

- [Setup guide](docs/setup-guide.md): install Compass and set up a repository, in about ten minutes.
- [User guide](docs/user-guide.md): working with Compass day to day, every command and setting, and a
  ten-minute demo script.

## Use it

```bash
uv tool install .                                   # the compass CLI
claude plugin marketplace add ./                    # this repo's .claude-plugin/marketplace.json
claude plugin install compass@compass-marketplace   # the plugin
compass -C /path/to/repo init                       # per repository: config, git hooks, first index
```

The marketplace also works straight from GitHub (`owner/repo`) or Azure Repos
(`https://dev.azure.com/<org>/<project>/_git/<repo>`). `plugin/README.md` has
the details; `compass uninstall` removes the git hooks again.

## Develop

Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run compass --help
uv run pytest              # unit, snapshot and hook-contract tests
uv run pytest --perf       # also the latency checks on a generated 100k LOC repo
```

Try it on any git repository:

```bash
uv run compass -C /path/to/repo init     # .compass/, config, git hooks, first index
uv run compass -C /path/to/repo stack
cat /path/to/repo/.compass/map/_index.md
```

CI runs the same matrix (macOS, Ubuntu, Windows × Python 3.11 and 3.12) on
GitHub Actions (`.github/workflows/ci.yml`) and Azure Pipelines
(`azure-pipelines.yml`). Keep the two identical; `tests/test_ci_configs.py`
checks that they are. A weekly job on both (`e2e.yml`,
`azure-pipelines-e2e.yml`) runs the done-when checks against the latest
Claude Code, logged in with your Claude subscription through a
`CLAUDE_CODE_OAUTH_TOKEN` secret (`claude setup-token`); Compass never uses an
API key.

The benchmark harness runs tasks headless with Compass on and off; see
`bench/README.md`:

```bash
uv run python bench/run.py --model claude-opus-5-5 --repeats 3
uv run compass report bench/results/<batch>
```

## Commands

| Command | Does |
| --- | --- |
| `compass init` | Create `.compass/` with `config.yaml`, install git hooks, build the first index |
| `compass index [--full]` | Refresh the index (only changed files), or rebuild it |
| `compass update [paths]` | Re-index specific files; `--from-git` is what the git hooks call |
| `compass files [--json]` | The files Compass indexes, with language and content hash |
| `compass stack [--json]` | Stack profile from manifests and CI definitions (GitHub Actions, Azure Pipelines, GitLab CI): languages, frameworks, versions, commands |
| `compass mcp` | The query tools as a stdio MCP server (the plugin's `.mcp.json` runs it) |
| `compass find-symbol NAME` | Where a class, function or method is defined (twin of `find_symbol`) |
| `compass read-symbol NAME` | Just that symbol's source lines (`read_symbol`) |
| `compass file-outline PATH` | What a file defines (`file_outline`) |
| `compass map [DIR]` | The folder tree, or one directory's files and symbols (`map`) |
| `compass tests-for TARGET` | Tests for a file, directory or symbol (`tests_for`) |
| `compass importers-of TARGET` | Files importing a file, directory or module (`importers_of`) |
| `compass callers-of NAME` | Call sites of a function or method (`callers_of`) |
| `compass task [new]` | The active task (started if there is none), or a fresh one; `--brief -` is `/compass:task` |
| `compass approve [ID]` | Approve a large task's spec, recording who and when (`/compass:approve`) |
| `compass check-prompt TEXT` | What the prompt gate and context pack would do with a prompt; changes nothing |
| `compass manifest [ID]` | Write `.compass/changes/<id>.md`; `--hosted` prints it with GitHub or Azure DevOps links |
| `compass accept [ID]` | Strip a reviewed task's anchor tags and archive its manifest (`/compass:accept`) |
| `compass check-anchors [ID]` | List anchor tags; `--staged` is the git pre-commit check |
| `compass uninstall` | Remove Compass's git hooks, restoring any they chained |
| `compass report [PATHS]` | Tasks with Compass on against off, from telemetry; from `bench/results/<batch>`, the benchmark report |
| `compass enrich [--limit N]` | One-line local-model summaries for undocumented symbols, shown as `~` in the map; the git hooks run it in the background |
| `compass summarize-file PATH` | The gist of a file from the local model (`summarize_file`); `--focus` asks something specific |
| `compass classify-files PATHS… --labels a,b` | Sort files into labels with the local model (`classify_files`) |
| `compass hook <event>` | Entry point for Claude Code hooks (JSON on stdin; always fails open) |

Query commands print what the MCP tool returns; `--json` gives structured
output and `--cursor 0` pages the answer exactly as the MCP server does. Path
arguments are relative to the current directory, like any other command's.

## Layout

```
src/compass/
  cli.py            argparse entry point
  config.py         .compass/config.yaml defaults and validation
  files.py          git ls-files enumeration, excludes, hashing
  stack.py          stack profile; detectors in stacks/
  languages.py      language registry from queries/<lang>/language.yaml
  queries/<lang>/   tags.scm and imports.scm per language (see queries/README.md)
  index/            parser, doc attachment, ctags fallback, import resolution,
                    SQLite store, shards
  query.py          the query engine behind the MCP tools and CLI twins
  mcp_server.py     compass mcp
  anchors.py        anchor tags: scan, strip, staged-lines check
  state.py          .compass/state.json: tasks and turns
  manifest.py       change manifests, local and hosted links
  review.py         the review loop the hooks and CLI run
  gate/             prompt gate (rules/ has one module per field), context pack, hook logic
  spec.py           large-task specs and their approval
  delegation.py     the subagents' rules and output contracts
  llm.py            local-model client (OpenAI-compatible, loopback only)
  local_tools.py    summarize_file and classify_files
  enrich.py         background summaries for undocumented symbols
  telemetry.py      per-turn rows from Claude Code's transcripts
  report.py         compass report
  hooks.py          compass hook <event>
  githooks.py       post-commit/checkout/merge/rewrite and pre-commit hooks
plugin/             the Claude Code plugin (hooks, commands, agents, style, MCP)
.claude-plugin/     marketplace.json, so Claude Code can install ./plugin
bench/              the benchmark harness, its task format and example tasks
tests/
  fixtures/         small repos in Python, TypeScript/JavaScript, Go and Rust
  snapshots/        expected index rows and map shards per fixture
  schemas/          vendored SchemaStore schemas for the plugin files
  e2e/              headless Claude Code checks (spend usage; run by hand)
```

Adding a language: a directory under `src/compass/queries/`, a fixture repo
under `tests/fixtures/`, and its snapshot. Adding a stack: a module under
`src/compass/stacks/` with `detect(repo) -> dict | None`.
