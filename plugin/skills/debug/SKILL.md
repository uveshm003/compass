---
name: debug
description: "Find the root cause of a bug, failing test, crash or wrong output, systematically: reproduce, form hypotheses, narrow down, confirm, then fix. Use when something fails or behaves unexpectedly and the cause is not obvious."
argument-hint: "<symptom: error message, failing test, wrong behaviour>"
---

You find the cause before you change anything. A fix without a confirmed cause is a guess.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/debug.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## Steps

1. **Reproduce.** Find the smallest command that shows the failure (from `stack_profile`'s test command, or the developer's report). Run test suites through `test-runner`. Run a single test inline only when you need its full output. Long logs go to `digest`.
2. **Locate.** From the stack trace or error, use `find_symbol` and `read_symbol` to read just the frames involved. Use `callers_of` to see how the failing code is reached.
3. **Hypothesise.** Write down two or three possible causes, ranked by likelihood, each with the observation that would confirm or rule it out.
4. **Narrow down.** Test the hypotheses cheapest first: a targeted assertion or log line, a smaller input, `git log -L` or `git bisect` when it used to work. Change one thing at a time.
5. **Confirm.** State the root cause and the evidence for it. If it's still unconfirmed after the hypotheses are spent, stop and report what was ruled out.
6. **Fix.** Make the smallest change that addresses the cause, not the symptom. Add or adjust a test that fails without the fix, then rerun through `test-runner`. Remove any temporary logging.

## Output

At most 15 lines: the symptom, the root cause with `file:line` and evidence, the fix, the test that now guards it, and anything ruled out along the way.
