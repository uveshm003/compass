---
description: Accept a reviewed change - strip its anchor tags and archive its manifest
argument-hint: "[task id, default: the active task]"
allowed-tools: Bash(compass accept:*)
disable-model-invocation: true
---

```!
compass accept $ARGUMENTS
```

Above is the output of `compass accept`. Report it to the developer in one or two lines. If some anchors were not removed, list them. Do not edit any files.
