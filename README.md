# Compass

A Claude Code plugin plus a local CLI that routes work to the cheapest executor
that can do it correctly, and makes AI changes reviewable. The design lives in
the five `Compass — *.md` specs in this directory; `CLAUDE.md` summarises them.

**Status:** M1 (index core) — file enumeration, stack profile, tree-sitter code
map in SQLite, Markdown map shards, and incremental updates from git hooks and
Claude Code hooks. Query tools (M2) and the plugin itself (M3) come next.

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
checks that they are.

## Commands (M1)

| Command | Does |
| --- | --- |
| `compass init` | Create `.compass/` with `config.yaml`, install git hooks, build the first index |
| `compass index [--full]` | Refresh the index (only changed files), or rebuild it |
| `compass update [paths]` | Re-index specific files; `--from-git` is what the git hooks call |
| `compass files [--json]` | The files Compass indexes, with language and content hash |
| `compass stack [--json]` | Stack profile from manifests and CI definitions (GitHub Actions, Azure Pipelines, GitLab CI): languages, frameworks, versions, commands |
| `compass hook <event>` | Entry point for Claude Code hooks (JSON on stdin; always fails open) |

## Layout

```
src/compass/
  cli.py            argparse entry point
  config.py         .compass/config.yaml defaults and validation
  files.py          git ls-files enumeration, excludes, hashing
  stack.py          stack profile; detectors in stacks/
  languages.py      language registry from queries/<lang>/language.yaml
  queries/<lang>/   tags.scm and imports.scm per language (see queries/README.md)
  index/            parser, doc attachment, ctags fallback, SQLite store, shards
  hooks.py          compass hook <event>
  githooks.py       post-commit/checkout/merge/rewrite hooks
tests/
  fixtures/         small repos in Python, TypeScript/JavaScript, Go and Rust
  snapshots/        expected index rows and map shards per fixture
```

Adding a language: a directory under `src/compass/queries/`, a fixture repo
under `tests/fixtures/`, and its snapshot. Adding a stack: a module under
`src/compass/stacks/` with `detect(repo) -> dict | None`.
