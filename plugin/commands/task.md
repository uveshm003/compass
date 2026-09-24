---
description: Start a Compass task from a brief - Goal, Scope, Non-goals, Accept when, Constraints, and optionally a Category and Size for telemetry
argument-hint: "Goal: … Scope: … Non-goals: … Accept when: … Constraints: … Category: … Size: S|M|L"
allowed-tools: Bash(compass task new:*)
disable-model-invocation: true
---

```!
compass task new --brief - <<'COMPASS_BRIEF'
$ARGUMENTS
COMPASS_BRIEF
```

Above is Compass's answer. Follow it. For a large task, write the spec it names before touching any other file, then stop and ask the developer to review it. For a small task, start on the brief below, tagging each change as Compass describes.

Brief:
$ARGUMENTS
