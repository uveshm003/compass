---
name: refactor-plan
description: "Turn a refactoring request (clean up, restructure, extract, rename across modules, migrate an API) into a staged, low-risk plan with the impact and checks for each step. Use before any refactor that touches more than one function or file."
argument-hint: "<what to refactor and why>"
---

You plan the refactor; you don't start it. Each step must leave the code building and the tests passing.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/refactor-plan.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## Steps

1. **Goal and boundary.** Restate what should improve (readability, coupling, a deprecated API, duplication) and what must not change (behaviour, public API, performance). Ask if either is unclear.
2. **Survey.** Use `map` and `file_outline` on the area, `callers_of` and `importers_of` on everything that moves or changes signature, and `tests_for` on all of it. Note untested code: it needs a characterisation test before it changes.
3. **Stage it.** Split the work into steps that each build and pass the tests on their own: add the new thing, migrate callers in batches, then remove the old thing. Mark purely mechanical steps (renames, moves, call-site updates). Those can go to the Compass `scaffold` subagent, naming every file it may touch.
4. **Risk per step.** What could break, and which tests prove it didn't.
5. **If Compass's spec gate drafted `.compass/specs/<task>.md` for this task,** write the plan there under its sections and list your open questions. Then stop for approval.

## Output

At most 40 lines: the goal and invariants; numbered steps, each with its files, whether it is mechanical (scaffold) or needs judgment, its risk, and its checks; tests to add first; open questions.
