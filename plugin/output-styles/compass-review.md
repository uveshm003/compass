---
name: Compass review
description: Short replies that point to the change manifest, with every change tagged for review
keep-coding-instructions: true
---

# Compass review style

This repository uses Compass. Your changes are reviewed through a change manifest, not through the chat.

## Tag every change

Mark each change with an anchor comment in the file's own comment syntax, on the changed line or the line above it: `@ai:<kind> <task> — <note>`. The kind is `review` for a judgment call, `assume` for an assumption you did not verify, `todo` for something deliberately left undone, and `change` for a mechanical edit. The task id comes from Compass's session context. Files that cannot hold comments, such as JSON, need no tag.

## Keep the reply short

End each turn with at most 10 lines: what changed, the manifest path (`.compass/changes/<task>.md`), and any risks or open questions. Do not paste code into the chat; the manifest links every change.

## Look code up through Compass

Use the compass MCP tools (`find_symbol`, `read_symbol`, `file_outline`, `map`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`) before Read, Grep or Glob. Read a whole file only when you are about to edit it.
