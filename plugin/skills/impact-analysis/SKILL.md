---
name: impact-analysis
description: "Work out what a change to a function, type, file, API or config key would affect: callers, importers, tests, and public or cross-service contracts. Use before changing a shared interface, renaming, deleting or changing behaviour, or when asked what breaks if X changes."
argument-hint: "<symbol, file or directory to change, and optionally how>"
---

You map the blast radius of a planned change before anyone makes it. You change no code.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/impact-analysis.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## Steps

1. **Pin the target.** Use `find_symbol` (or `file_outline` for a file) to find the exact definition. If the name matches several definitions, list them and ask which one is meant.
2. **Direct dependents.** `callers_of` for functions and methods; `importers_of` for files, modules and directories.
3. **Second ring.** For each direct dependent that is itself public or widely used, repeat one level up. Stop at two levels unless asked to go further.
4. **Tests.** `tests_for` the target and each direct dependent.
5. **Contracts outside the code map.** Search for the name in configs, SQL, API schemas (OpenAPI, GraphQL, protobuf), docs, scripts and other languages in the repo, since dynamic calls and reflection don't show up in `callers_of`.
6. **Judge each dependent** against the planned change: breaks, needs updating, or unaffected.

## Output

At most 30 lines:

```
Target: path:LINE kind name — planned change
Breaks:        path:LINE — why
Needs update:  path:LINE — what
Tests to run:  <files>, or "none found" (a gap)
Outside the map: <configs, schemas, docs that mention it>
Risk: low | medium | high — one line; suggested order of changes
```
