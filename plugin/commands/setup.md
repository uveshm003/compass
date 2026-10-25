---
description: Switch Compass on in this repository - builds its code map so Claude finds code faster and spends fewer tokens. Use when the developer asks to set up, enable or switch on Compass here
allowed-tools: Bash(compass init:*)
---


```!
compass init --modules essentials
```

Above is the output of `compass init`. Tell the developer in two lines that Compass is now on in this repository and what it does for them: Claude finds code through its map instead of searching, and hands long test runs and logs to cheaper helpers. Mention that `.compass/config.yaml` can be committed so the team shares the setup. Do not edit any files.
