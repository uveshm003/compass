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
`/hooks`, `/agents` and `/mcp`.

## What it does

| Piece | File | Does |
| --- | --- | --- |
| SessionStart hook | `hooks/hooks.json` | Refreshes the index; tells Claude to look code up through Compass and to tag its changes for the active task |
| UserPromptSubmit hook | | Starts the turn; announces a new task id |
| PostToolUse hook (Write, Edit) | | Re-indexes the edited file; records it for the task's manifest |
| Stop hook | | Writes `.compass/changes/<task>.md`; asks Claude once to tag changed files it left untagged |
| MCP server | `.mcp.json` | `find_symbol`, `read_symbol`, `file_outline`, `map`, `stack_profile`, `tests_for`, `importers_of`, `callers_of` |
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

Everything can be switched off in `.compass/config.yaml` (`review.enabled`,
`review.require_anchors`, `review.reply_max_lines`, `review.anchor_exempt`).
