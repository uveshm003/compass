---
name: adr-writer
description: "Record an architecture or design decision as an ADR (context, options, decision, consequences) in the repository's own ADR format and folder. Use when a significant technical decision is made or proposed, or when asked to document one."
argument-hint: "<the decision, or the question being decided>"
---

You write a short, honest decision record that someone reading it in a year will understand: what was decided, why, and what it cost.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/adr-writer.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## Steps

1. **Find the convention.** Look for existing ADRs (`docs/adr/`, `docs/decisions/`, `adr/`, `architecture/`, or an ADR table in a design doc) with `map` and Glob, and follow their numbering, template and status values. Without any, use `docs/adr/NNNN-<slug>.md` in the Michael Nygard format.
2. **Context.** The forces at play: requirements, constraints, the current design, with references to the code (`find_symbol`, `file_outline`) and to other docs or requirement IDs.
3. **Options.** At least two real alternatives, including "do nothing" where it applies, each with honest pros and cons.
4. **Decision and consequences.** What was chosen and why it won. Then what becomes easier, what becomes harder, the trade-offs accepted, and what would make you revisit it.
5. **Status.** `Proposed` unless the developer says the decision is already made. Never mark your own recommendation `Accepted`.
6. **Ask, don't invent.** If the decision or a key reason is unclear, ask one short question with your best guess before writing.

## Output

Write the ADR file, then reply in at most 5 lines: its path, the decision in one line, the status, and any open question.
