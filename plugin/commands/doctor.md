---
description: Check that Compass is installed and wired correctly - the CLI on PATH, Claude Code's version, hooks wired once, the MCP server, the code map and git hooks
argument-hint: "[--no-mcp]"
allowed-tools: Bash(compass doctor:*)
---

```!
compass doctor --exit-zero $ARGUMENTS
```

Above is the output of `compass doctor`. If it ends with "All good.", say so in one line. Otherwise list each line marked as a failure or a warning, with the fix it names, and nothing else. Do not run the fixes or edit any files: they change the developer's install, which is theirs to do.
