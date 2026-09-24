# Compass plugin for Claude Code

The plugin is plain files: hooks, three commands, three subagents, an optional
output style and the MCP registration. All behaviour lives in the `compass`
CLI, which every hook calls (`compass hook <event>`), so install both.

## Install

1. The CLI, from a clone or straight from the repository:

   ```bash
   uv tool install .                                   # in a clone
   uv tool install git+https://github.com/<owner>/<repo>
   uv tool install git+https://dev.azure.com/<org>/<project>/_git/<repo>
   ```

2. The plugin, from the marketplace file at the repository root
   (`.claude-plugin/marketplace.json`):

   ```bash
   claude plugin marketplace add ./                    # a local clone
   claude plugin marketplace add <owner>/<repo>        # GitHub
   claude plugin marketplace add https://dev.azure.com/<org>/<project>/_git/<repo>   # Azure Repos
   claude plugin install compass@compass-marketplace
   ```

   Inside Claude Code the same commands are `/plugin marketplace add …` and
   `/plugin install compass@compass-marketplace`. Private repositories
   authenticate through your git credential helper.

3. In each repository: `compass init` (config, git hooks, first index).

Restart Claude Code after installing or changing the plugin, then check
`/hooks`, `/agents` and `/mcp`. The first time Claude calls a Compass tool,
allow it for good ("don't ask again"): the tools only read the code map.

## What it does

| Piece | File | Does |
| --- | --- | --- |
| SessionStart hook | `hooks/hooks.json` | Refreshes the index; tells Claude to look code up through Compass, to tag its changes for the active task, and when to delegate |
| UserPromptSubmit hook | | Checks a new request for goal, scope and acceptance (warns by default, or blocks); adds the code map's lines for the names it mentions; starts the turn |
| PreToolUse hook (Write, Edit) | | While a large task's spec is unapproved, refuses edits to anything but the spec; keeps the `scaffold` subagent to the files it was given |
| PreToolUse hook (Agent) | | Notes which files a `scaffold` delegation names |
| PostToolUse hook (Write, Edit) | | Re-indexes the edited file; records it for the task's manifest |
| Stop hook | | Writes `.compass/changes/<task>.md`; asks Claude once to tag changed files it left untagged |
| SubagentStop hook | | Sends a Compass subagent's answer back once when it breaks its output contract (too long, no `file:line`, untagged changes) |
| MCP server | `.mcp.json` | `find_symbol`, `read_symbol`, `file_outline`, `map`, `stack_profile`, `tests_for`, `importers_of`, `callers_of`; with a local model, `summarize_file` and `classify_files` |
| `/compass:task <brief>` | `commands/task.md` | Starts a task from `Goal: … Scope: … Non-goals: … Accept when: … Constraints: …`; a large one gets a spec draft (developer only) |
| `/compass:approve [task]` | `commands/approve.md` | Approves a large task's spec, recording who and when (developer only) |
| `/compass:accept [task]` | `commands/accept.md` | Strips the task's anchor tags and archives its manifest (developer only) |
| `digest` subagent | `agents/digest.md` | Condenses large logs and files to 30 lines, citing `file:line` |
| `test-runner` subagent | `agents/test-runner.md` | Runs tests or a build and reports only the failures, in 20 lines at most |
| `scaffold` subagent | `agents/scaffold.md` | Makes mechanical edits to the files it is given, tagging each change |
| Output style (opt-in) | `output-styles/compass-review.md` | The same reply rules as a system-prompt style |

## Reviewing a change

Claude marks each change with a comment in the file's own syntax:
`@ai:review <task>` for a judgment call, `@ai:assume` for an unverified
assumption, `@ai:todo` for something left undone, and `@ai:change` for a
mechanical edit. At the end of each turn the manifest
`.compass/changes/<task>.md` lists them, grouped for reading, with links to
each line.

Read the Review and Assumption entries, then run `/compass:accept` to strip the
tags. The git pre-commit hook that `compass init` installs refuses any commit
that still adds a tag. `compass manifest <task> --hosted` prints an accepted
manifest with links into GitHub or Azure DevOps, ready for a pull request.

## Gates

A request that starts a task is checked for a goal, a scope and how to tell it
is done. By default Compass warns: Claude is told to ask before assuming, and
you see a one-line notice. With `prompt_gate.strictness: block` the prompt is
refused with a checklist instead. Questions, short replies and follow-ups are
never checked, and a prompt starting with `!quick` skips the check (and the
spec gate) for that turn.

A large task (a refactor or migration, or several files named) gets a spec at
`.compass/specs/<task>.md`. Claude fills it in with its open questions and
stops; until you run `/compass:approve`, it can change nothing else.

## Delegation

The subagents run on Haiku in their own context, so a 600-line test log or a
large file never reaches the main conversation: only the subagent's short
answer does. Claude decides when to delegate, from rules Compass adds at
session start: tests and builds go to `test-runner`, reading more than about
500 lines for a short answer to `digest`, spelled-out edits to `scaffold`.
Compass holds each answer to its contract and sends it back once when it
breaks it, and it refuses any edit `scaffold` makes outside the files named in
its instructions or the task's spec.

## A local model (optional)

With a model running on your machine (Ollama, llama.cpp, LM Studio) and

```yaml
local_llm:
  enabled: true
  base_url: http://localhost:11434/v1
  model: gemma3
```

in `.compass/config.yaml`, Claude also gets `summarize_file` and
`classify_files`, answered locally at no token cost, and after each commit
`compass enrich` writes one-line summaries of undocumented functions and
classes into the code map in the background. Only addresses on this machine
are accepted, so code never leaves it. When the model is not running, all of
this simply stays off.

Everything can be switched off in `.compass/config.yaml`: `prompt_gate`,
`context_pack`, `spec_gate`, `review` (`enabled`, `require_anchors`,
`reply_max_lines`, `anchor_exempt`), `delegation` (`enabled`,
`enforce_contracts`) and `local_llm`.
