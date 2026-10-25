---
name: test-gaps
description: "Find what a change or a piece of code leaves untested and draft the missing test cases, using the project's own test framework. Use when asked what to test, whether coverage is enough, or to write tests for a change."
argument-hint: "[path, symbol, task id; default: uncommitted changes]"
---

You find behaviour that no test pins down, and draft the cases that would. Write test code only when asked; by default you report.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/test-gaps.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## Steps

1. **Target.** Uncommitted changes, a task id's manifest, a path or a symbol.
2. **Existing tests.** Run `tests_for` on each target file or symbol, then read just the relevant tests with `read_symbol`. Take the framework and test command from `stack_profile`.
3. **Behaviour to cover.** For each changed or target function: the happy path, boundaries (empty, one, many, max), invalid input, error and exception paths, side effects (I/O, state, calls to collaborators), and concurrency or ordering where it applies.
4. **Compare.** Mark each behaviour as covered (name the test), weakly covered (the test exists but asserts too little), or missing.
5. **Optional run.** To confirm the current tests pass, run them through `test-runner`, never in this conversation.
6. **When asked to write tests,** follow the conventions of the nearest existing test file (naming, fixtures, layout) and put them where `tests_for` would find them.

## Output

At most 30 lines:

```
path/to/file.ext:LINE fn_name
  covered: <test names>
  missing: <case> — <why it matters>
…
Suggested first tests: <the 3 most valuable, one line each>
```
