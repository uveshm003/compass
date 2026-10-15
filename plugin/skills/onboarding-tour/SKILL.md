---
name: onboarding-tour
description: "Give a structural tour of an unfamiliar repository or area: what it does, how it is laid out, the main flows, where to start reading, and how to build, test and run it. Use when someone is new to a codebase or asks how a project or module is organised."
argument-hint: "[directory or topic to focus on; default: the whole repository]"
---

You give a newcomer the mental model that would take a day of reading, using the code map instead of opening files.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/onboarding-tour.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## Steps

1. **Shape.** `map` with no argument gives the folder tree and each folder's purpose. `stack_profile` gives languages, frameworks, versions and the build, test and lint commands.
2. **Entry points.** Find main functions, server setup, CLI definitions, route tables and job schedulers with `find_symbol` and `file_outline`. Read the README's first section if there is one.
3. **Core flows.** Pick the two or three most important flows (for example, a request from route to database). Trace them with `callers_of`, `importers_of` and `read_symbol`, reading only signatures and key lines.
4. **Conventions.** Where tests live and how they're named (`tests_for` on a core file), configuration, error handling, and the layering rules that imports reveal.
5. **Focus.** If a directory or topic was given, go one level deeper there and stay brief everywhere else.

## Output

At most 45 lines:

1. What it is, in two lines.
2. Layout: the top folders, one line each.
3. Main flows, each as a chain of `file:line` steps.
4. Build, test and run commands.
5. Conventions to follow.
6. Where to start reading: five files or symbols, in order.
