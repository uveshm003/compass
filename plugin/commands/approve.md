---
description: Approve a large task's spec so Claude may change code - records who approved and when
argument-hint: "[task id, default: the active task]"
allowed-tools: Bash(compass approve:*)
disable-model-invocation: true
---

```!
compass approve $ARGUMENTS
```

Above is the output of `compass approve`. Tell the developer the result in one line. If it worked, carry on with the task as the spec describes; if it listed unticked open questions, mention them first.
