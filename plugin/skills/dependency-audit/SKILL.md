---
name: dependency-audit
description: "Audit a project's dependencies against the versions actually locked: outdated, unmaintained, duplicated, unused or risky packages, and licence concerns. Use when asked about dependency health, before an upgrade, or for a periodic hygiene check."
argument-hint: "[ecosystem or manifest path; default: everything stack_profile finds]"
---

You assess dependencies from the manifests and lockfiles in the repo. Be explicit about what you know for certain and what needs checking online.

Request: $ARGUMENTS

## How to work

1. **Team standards first.** If `.compass/standards/all.md` or `.compass/standards/dependency-audit.md` exists, read it before anything else. Its rules add to this checklist and win where they disagree.
2. **Look things up, don't read everything.** Use the Compass tools: `map`, `find_symbol`, `read_symbol`, `file_outline`, `callers_of`, `importers_of`, `tests_for`, `stack_profile`. Open a whole file only when you need all of it. Without the tools (no code map yet), fall back to Grep and Read.
3. **Let the stack decide.** Take languages, framework versions and the test, build and lint commands from `stack_profile`. Never assume a technology the profile doesn't show, and judge code by the idioms of the language it is written in.
4. **Delegate bulk work.** Logs, generated files or more than about 500 lines of input go to the Compass `digest` subagent. Test and build runs go to `test-runner`. Both are named `compass:<name>` as a plugin and `compass-<name>` as files.

## Steps

1. **Inventory.** `stack_profile` lists every manifest and the versions installed from lockfiles. Read the manifests themselves for direct versus dev dependencies and version ranges.
2. **Usage.** For each direct dependency, check that the code uses it: `importers_of <package>` shows the importers. A dependency nothing imports may be unused, or used through config, plugins or the CLI only, so say which.
3. **Versions.** Flag ranges that are unpinned or overly loose, packages several major versions behind what you know to be current, and the same package at different versions across manifests.
4. **Risk.** Packages you know to be deprecated, unmaintained, or affected by serious advisories. Give the version a fix landed in when you are sure. Otherwise say "check against the advisory database" (`npm audit`, `pip-audit`, `cargo audit`, `govulncheck`, `dotnet list package --vulnerable`, OWASP Dependency-Check) and give the command for this stack.
5. **Licences.** Note copyleft or unusual licences you are confident about, when the project looks like it is distributed.

## Output

At most 35 lines, grouped as: Remove (unused), Upgrade (outdated or vulnerable: from → to, why), Pin (loose ranges), Check (needs an online lookup, with the command), and a one-line overall health.
