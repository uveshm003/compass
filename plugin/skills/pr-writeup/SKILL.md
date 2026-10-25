---
name: pr-writeup
description: "Write a pull request description and commit message for the current change from its diff and Compass's change manifest, ready for GitHub or Azure DevOps. Use when asked for a PR description, a commit message or a change summary."
argument-hint: "[task id; default: the active task or uncommitted changes]"
---

You write what a reviewer needs to read the change fast: why, what, how it was tested, and where to look first.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/pr-writeup.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## Steps

1. **Collect.** If a Compass task exists, read `.compass/changes/<task>.md` (or `compass manifest <task> --hosted` once the task is accepted, which gives links into GitHub or Azure DevOps). Also read the task's brief (`compass task`) and its spec, if it has one. Otherwise use `git diff HEAD --stat` and the diff itself, and send diffs over about 500 lines to `digest`.
2. **Why.** The problem or goal in the brief, or as the changes show it. Never invent a ticket number or motivation; leave a placeholder for the author to fill.
3. **What.** Group the changes by intent, not file by file. Call out the judgment calls and assumptions from the manifest's Review and Assumptions sections.
4. **Testing.** The tests added or changed (from the diff) and the commands to run them (from `stack_profile`).
5. **Commit message.** A subject in the imperative mood, at most 72 characters, a blank line, then a short body with the why. Follow the repository's own style if `git log --oneline -20` shows one, for example Conventional Commits.

## Output

Two fenced blocks, nothing else:

1. The PR description in Markdown: Summary, Changes, Review focus (with `file:line` links from the manifest), Testing, Risks or follow-ups.
2. The commit message.
