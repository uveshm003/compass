# Compass plugin for Claude Code

The plugin is plain files: hooks, one command, one subagent, an optional output
style and the MCP registration. All behaviour lives in the `compass` CLI, which
every hook calls (`compass hook <event>`), so install both.

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
| SessionStart hook | `hooks/hooks.json` | Refreshes the index; tells Claude to look code up through Compass and to tag its changes for the active task |
| UserPromptSubmit hook | | Checks a new request for goal, scope and acceptance (warns by default, or blocks); adds the code map's lines for the names it mentions; starts the turn |
| PreToolUse hook (Write, Edit) | | While a large task's spec is unapproved, refuses edits to anything but the spec |
| PostToolUse hook (Write, Edit) | | Re-indexes the edited file; records it for the task's manifest |
| Stop hook | | Writes `.compass/changes/<task>.md`; asks Claude once to tag changed files it left untagged |
| MCP server | `.mcp.json` | `find_symbol`, `read_symbol`, `file_outline`, `map`, `stack_profile`, `tests_for`, `importers_of`, `callers_of` |
| `/compass:task <brief>` | `commands/task.md` | Starts a task from `Goal: … Scope: … Non-goals: … Accept when: … Constraints: …`; a large one gets a spec draft (developer only) |
| `/compass:approve [task]` | `commands/approve.md` | Approves a large task's spec, recording who and when (developer only) |
| `/compass:accept [task]` | `commands/accept.md` | Strips the task's anchor tags and archives its manifest (developer only) |
| `digest` subagent | `agents/digest.md` | Condenses large logs and files to 30 lines |
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

Everything can be switched off in `.compass/config.yaml`: `prompt_gate`,
`context_pack`, `spec_gate`, and `review` (`enabled`, `require_anchors`,
`reply_max_lines`, `anchor_exempt`).
