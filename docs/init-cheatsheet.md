# Compass cheat sheet: switching it on


A quick reference for switching Compass on for one repository, one folder in it, or one Claude Code session. For the full walk-through, see the [setup guide](setup-guide.md); for day-to-day use, the [user guide](user-guide.md).

Compass has two parts, and each is switched on in its own way:

| Part | What it does | Where it is switched on |
| --- | --- | --- |
| The `compass` tool | The code map, gates, manifests, telemetry | Per **repository**, by `compass install` or `compass init` |
| The Claude Code integration | Hooks, subagents, skills, `/compass:*` commands, the MCP tools | Per **user**, **project** or **session**, as a plugin or as files in `.claude/` |

The hooks do nothing in a repository with no `.compass/` folder: they look for it next to `.git` and stay idle without it. So you can install the integration for your user and still choose which repositories use Compass, by setting up only those.

---

## 0. The quick way: one command

With [uv](https://docs.astral.sh/uv/) installed, run this inside the repository. It installs the tool, wires Compass into Claude Code and sets up the repository:

```powershell
uvx --python 3.12 --from git+https://github.com/<owner>/<repo> compass install   # or the Azure Repos URL
compass install                                                    # once the tool is installed
```

From a clone of Compass, `.\install.ps1` (Windows) or `./install.sh` (macOS, Linux) does the same, and installs uv first if it is missing. Add `-Repo <path>` / `--repo <path>` to set up another repository.

`compass install` asks three questions. Each is also a flag, and `--yes` takes the defaults for anything you leave out:

| Question | Flag | Choices |
| --- | --- | --- |
| Who is it for? | `--scope` | `user`: you, in every project · `project`: this repository, committed for the whole team · `local`: this repository, just you (plugin mode only) |
| How is it installed? | `--mode` | `plugin`: through Claude Code's plugin system · `files`: plain files in `.claude/` you can read, edit and commit |
| Which modules? | `--modules` | `full` (default) · `baseline`: telemetry only, to measure a baseline first · `custom`: choose each |

```powershell
compass install --yes --scope project --mode files   # the whole team, as files they can review
compass install --yes --scope user --mode plugin     # just you, everywhere
compass install --dry-run                            # list what it would write; change nothing
```

Restart Claude Code afterwards; plugins and hooks load when a session starts.

---

## 1. Another repository, once Compass is installed for your user

The user-scope integration is already there, so only the repository needs setting up:

```powershell
cd C:\path\to\your-repo
compass init
git add .compass/config.yaml .compass/.gitignore
git commit -m "Add Compass"
```

Useful variants:

```powershell
compass -C C:\path\to\your-repo init   # run it from anywhere, like git -C
compass init --no-git-hooks            # skip the git hooks (then run `compass index` yourself after pulls)
compass init --no-index                # set up now, build the map later with `compass index`
```

`compass init` is safe to run again: it keeps an existing `config.yaml` and rewrites only its own git hooks. Run it again after upgrading Compass, so the hooks match the new version (`compass doctor` says when they don't).

---

## 2. A specific folder

Compass always works on a whole **git repository**: `compass init` and `compass install` find the root with `git rev-parse --show-toplevel`.

| You are in… | What happens |
| --- | --- |
| The repository root | Compass is set up there. |
| A subfolder of a repository | Compass is set up at the **repository root**, not in the subfolder. |
| A folder that is not in git | `compass init` stops with "not inside a git working tree"; `compass install` wires Claude Code and skips the repository. |

**A folder that isn't a git repository yet:**

```powershell
cd C:\path\to\folder
git init
compass init
```

**Only one part of a large repository or monorepo:** set Compass up at the root, then leave the rest out of the map in `.compass/config.yaml`. The patterns are gitignore-style globs, relative to the repository root:

```yaml
index:
  exclude:
    - "services/legacy/**"
    - "frontend/**"
    - "vendor/**"
```

Then rebuild: `compass index --full`.

---

## 3. A single Claude Code session

To load the plugin for one session without installing it, point Claude Code at the `plugin/` folder of a Compass clone:

```powershell
cd C:\path\to\your-repo
claude --plugin-dir C:\path\to\compass\plugin
```

The repository still needs `compass init` (section 1) for the hooks to do anything. Close the session and Compass is gone again. This is also the quickest way to try changes to `plugin/`, because an installed plugin runs a cached copy.

---

## 4. Inside a session

| Want | Plugin mode | Files mode |
| --- | --- | --- |
| Skip the prompt check for one prompt | Start it with `!quick` | same |
| Start a fresh task | `/compass:task <what you want>` | same |
| Approve a large task's plan | `/compass:approve` | same |
| Accept reviewed changes (strip the tags) | `/compass:accept` | same |
| Check the install from inside Claude Code | `/compass:doctor` | same |
| Run a skill, e.g. a code review | `/compass:code-review <what>` | `/compass-code-review <what>` |

The eleven skills: `code-review`, `security-review`, `test-gaps`, `impact-analysis`, `debug`, `refactor-plan`, `pr-writeup`, `dependency-audit`, `perf-review`, `onboarding-tour`, `adr-writer`. Each reads your team's rules from `.compass/standards/all.md` and `.compass/standards/<skill>.md` when they exist.

From a terminal, `compass check-prompt "your prompt"` shows what the prompt check would say, without a session.

---

## 5. Check it worked

```powershell
compass doctor
```

It checks the tool on PATH, the Claude Code version, the hooks (wired exactly once, never in both modes), the MCP server's start-up time, the code map and the git hooks, and says how to fix anything that is wrong. In a session, also:

- `/mcp` shows `compass` as connected.
- `/agents` lists the three subagents: `compass:digest`, `compass:test-runner` and `compass:scaffold` (`compass-digest` and so on in files mode).
- `compass report` shows Compass tool calls above zero after a few sessions. If it says the query tools were unused, the MCP server did not connect.

---

## 6. Turning parts off, upgrading, removing

Every module can be switched off in `.compass/config.yaml`, for example:

```yaml
prompt_gate:
  strictness: off     # or: ask (default) | strict
review:
  enabled: false
delegation:
  enabled: false
```

```powershell
compass upgrade                    # newer tool, then refreshed plugin or files; your edits are kept as <file>.compass-new
compass uninstall                  # this repository: git hooks, and what `compass install` wrote; keeps .compass/
compass uninstall --scope user     # an install made for your user
Remove-Item -Recurse -Force .compass   # optional: drop the map, manifests and telemetry
uv tool uninstall compass          # the tool itself, once per machine
```

---

## Quick troubleshooting

| Symptom | Fix |
| --- | --- |
| `compass: command not found` in a hook | `uv tool update-shell`, then restart the terminal or IDE |
| `/mcp` says compass timed out | Run `compass doctor` once (the first start compiles Python files), then `/mcp` to reconnect |
| `not inside a git working tree` | `git init` first (section 2) |
| Hooks don't run | Restart Claude Code; check `.compass/` exists at the repository root; run `compass doctor` |
| Every hook seems to run twice | Compass is installed in two modes or scopes; `compass doctor` names them |
| Map looks stale | `compass index`, or `compass index --full` |
| Anything else | `.compass/logs/errors.log` |
