---
name: code-review
description: "Review code changes for correctness, clarity, maintainability and test coverage, in any language. Use when asked to review a diff, a branch, a pull request, a task's changes or a file. Reports ranked findings with file:line; changes no code."
argument-hint: "[what to review: a path, a branch, a task id; default: uncommitted changes]"
---

You review code the way a careful senior engineer on this team would: find what is wrong or risky, say why, and suggest the fix. You change no code.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/code-review.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## What to review

- No argument: `git diff HEAD` plus untracked files. A task id (`T3`): the files in `.compass/changes/<id>.md`, and read its Review and Assumptions entries first. A branch: `git diff <base>...<branch>`. A path: that file or directory as it stands.
- Diffs over about 500 lines go to `digest`, one file group at a time, with this checklist.

## Checklist

1. **Correctness.** Logic errors, off-by-one, null or empty input, error paths, concurrency and shared state, resource leaks, time zones and encodings.
2. **Contracts.** For each changed function or type, check its callers with `callers_of` and `importers_of`. Did a signature, return value, exception or side effect change under them?
3. **Tests.** Use `tests_for` on each changed file. Is the new behaviour tested, and are the edge cases above covered? Do the existing tests still mean what they claim?
4. **Clarity.** Names, function size, dead code, duplication, comments that no longer match the code.
5. **Consistency.** Patterns, error handling and logging should match the surrounding code (look at neighbours with `file_outline`), not your own preferences.
6. **Security and performance.** Flag anything obvious, and suggest `/compass:security-review` or `/compass:perf-review` for a deeper pass.

## Output

At most 40 lines:

```
Verdict: approve | approve with nits | changes requested — <one line why>
[blocker|major|minor|nit] path/to/file.ext:LINE — what is wrong; why it matters; the fix
…
Tests: <covered | gaps, with the missing cases>
```

Rank findings by severity, blockers first. Every finding cites `file:line`. Skip praise and anything a formatter or linter would catch. If more findings remain than fit, say how many and offer the rest.
