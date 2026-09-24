# Compass setup guide

Compass makes Claude Code cheaper to run and its changes easier to review. It adds four things:
- a code map that Claude looks things up in instead of reading whole files
- checks on requests before work starts
- Haiku subagents for heavy reading
- a review manifest for every change

Everything runs on your own machine, on top of Claude Code and your own Claude login. There is no server, and no API key is involved.

Setup takes about ten minutes. Once per machine, you install the `compass` command-line tool and the Claude Code plugin. Then you run `compass init` once in each repository.

## What you need

| | Version | Why |
| --- | --- | --- |
| Claude Code | 2.1.281 or later, signed in with your Claude account | Compass is a Claude Code plugin |
| git | any recent version | Compass works in git repositories, on GitHub or Azure Repos |
| uv | any recent version | installs the `compass` tool and the Python it needs (3.11 or later) |
| universal-ctags | optional | indexes languages that have no built-in parser |
| Ollama or LM Studio | optional | a local model for summaries at no token cost |

Compass runs natively on macOS, Linux and Windows 10 or later. Windows needs no WSL.

## 1. Install uv

macOS and Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 2. Install the compass tool

Install it from wherever your team hosts the Compass repository:

```bash
uv tool install git+https://github.com/<owner>/<repo>                    # GitHub
uv tool install git+https://dev.azure.com/<org>/<project>/_git/<repo>    # Azure Repos
uv tool install .                                                         # or from a clone, inside it
```

Next, put uv's tool folder on your PATH (you only need to do this once), and open a new terminal:

```bash
uv tool update-shell
compass --version        # compass 0.1.0
```

Claude Code runs Compass's hooks by calling `compass` from the PATH, so the terminal or IDE that starts Claude Code must see it too. If you use Claude Code inside an IDE, restart the IDE after `update-shell`.

## 3. Install the Claude Code plugin

Add the repository as a plugin marketplace, then install the plugin from it:

```bash
claude plugin marketplace add <owner>/<repo>                                        # GitHub
claude plugin marketplace add https://dev.azure.com/<org>/<project>/_git/<repo>     # Azure Repos
claude plugin marketplace add /path/to/compass                                      # a local clone

claude plugin install compass@compass-marketplace
```

Inside Claude Code, the same commands are `/plugin marketplace add …` and `/plugin install compass@compass-marketplace`. For private repositories, your git credential helper handles sign-in.

By default the plugin is installed for you alone, in every project. To switch it on for everyone who opens one repository, install it from inside that repository with `--scope project`; the choice is saved in `.claude/settings.json`. Each developer still needs the `compass` tool from step 2.

## 4. Set up a repository

Run this once in each repository:

```bash
cd your-repo
compass init
```

```text
Compass in /home/you/your-repo
  config      wrote .compass/config.yaml (commit it)
  gitignore   .compass/.gitignore keeps derived files out of git
  git hook    post-commit: installed
  git hook    post-checkout: installed
  git hook    post-merge: installed
  git hook    post-rewrite: installed
  git hook    pre-commit: installed
  index       Indexed 9 files, 21 symbols in 0.19 s (full build).
  map         .compass/map/_index.md
```

Then commit the two files the team shares:

```bash
git add .compass/config.yaml .compass/.gitignore
git commit -m "Add Compass"
```

Everything else in `.compass/` is derived, stays out of git, and can be rebuilt with `compass index --full`:

| Path | What it is | In git? |
| --- | --- | --- |
| `config.yaml` | Settings; every module can be switched off here | Yes |
| `.gitignore` | Keeps the derived files out of git | Yes |
| `specs/` | Specs for large tasks, which you approve | Your choice (recommended) |
| `index.db`, `map/` | The code map: an SQLite index, and Markdown pages Claude reads | No |
| `changes/` | A review manifest per task | No |
| `state.json` | The active task, and who approved which spec | No |
| `telemetry.jsonl` | What each turn cost: counts and timings only | No |
| `logs/` | Errors, and every prompt-gate decision | No |

The git hooks keep the map current after commits, checkouts, merges and rebases. The pre-commit hook refuses a commit that still carries review tags. If your repository sets `core.hooksPath` (husky, for example), `compass init` leaves your hooks alone and prints the two lines to add to them.

## 5. Check it works

Restart Claude Code in the repository. Plugins load when a session starts, so a session that was already open won't see Compass. Then check three things:

- `/hooks` lists Compass's hooks for SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, SubagentStop and Stop.
- `/agents` lists `compass:digest`, `compass:test-runner` and `compass:scaffold`.
- `/mcp` shows `compass` as connected.

Now ask Claude something about the code, for example *"Where is a reading judged to be an alarm, and what calls it?"*. The first time Claude calls a Compass tool, allow it permanently ("don't ask again"): the tools only read the code map.

You can also query the map yourself:

```bash
compass map
compass find-symbol alarm
```

```text
2 symbols matching "alarm":
src/inventory/models.py:28-30  method Reading.is_alarm(self, threshold: float = DEFAULT_THRESHOLD) -> bool — True when the reading crosses the alarm threshold
tests/test_models.py:4-5  fn test_alarm()  [test]
```

## Optional extras

**universal-ctags.** Compass has tree-sitter parsers for its main languages and uses ctags for everything else. Install it (`brew install universal-ctags`, `sudo apt install universal-ctags`, or a build from the universal-ctags project for Windows), then run `compass index --full` once.

**A local model.** With Ollama or LM Studio running, Claude also gets `summarize_file` and `classify_files`, and after each commit Compass writes one-line summaries of undocumented code into the map. Both run at no token cost. Turn it on in `.compass/config.yaml`:

```yaml
local_llm:
  enabled: true
  base_url: http://localhost:11434/v1   # Ollama; only addresses on this machine are accepted
  model: gemma3
```

When the model isn't running, these features simply stay off.

## Updating

```bash
uv tool upgrade compass                                   # the tool
claude plugin marketplace update compass-marketplace       # the plugin's source
claude plugin update compass@compass-marketplace           # the plugin itself
```

Restart Claude Code afterwards. A plugin update applies only when the plugin's version number changes. After changes that keep the same version, uninstall the plugin and install it again.

## Removing Compass

```bash
compass uninstall                                 # in each repository: removes Compass's git hooks, restores any it chained
claude plugin uninstall compass@compass-marketplace
uv tool uninstall compass
```

`compass uninstall` keeps `.compass/`; delete the folder if you no longer want it. With the plugin removed, Claude Code behaves exactly as stock again.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| A hook error saying `compass: command not found` | The tool isn't on the PATH Claude Code sees. Run `uv tool update-shell`, then restart the terminal or IDE. |
| `/mcp` shows compass as failed | The same PATH problem. Or run `compass mcp` in the repository to see the error. |
| Compass hooks don't run | Plugins load when a session starts. Restart Claude Code in the repository. |
| "The code map is being built in the background" | The first index of a big repository is still running. Give it a few seconds. |
| Answers look out of date | Run `compass index`, or `compass index --full` to rebuild everything. |
| Plugin changes don't show up | Uninstall the plugin, install it again, and restart. |
| A commit is refused because of AI anchor tags | Review `.compass/changes/<task>.md`, then run `/compass:accept` and commit again. |
| Anything else | See `.compass/logs/errors.log`. Compass never stops Claude Code because of its own errors. |

Next: the [user guide](user-guide.md) shows how to work with Compass day to day, and includes a ten-minute demo.
