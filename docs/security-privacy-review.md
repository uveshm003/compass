# Compass — Privacy audit (NF-10) and security review (NF-11)


Oct 15, 2026 · Compass 0.3.0 (branch `m7-installer-languages`) · Windows 11, Python 3.12, Claude Code 2.1.300

The Requirements Spec verifies two non-functional requirements by inspection rather than by measurement:

| ID | Requirement | Verified by |
| --- | --- | --- |
| NF-10 | No code leaves the machine except through Claude Code itself; local-LLM calls stay on localhost | Audit |
| NF-11 | The MCP server uses stdio only; hooks never execute code from the repo other than Compass's own scripts | Review |

This is the first audit and review. It found four problems: two that let a repository run its own code through Compass, one that let a local-model call leave the machine, and one that let a repository change what ctags indexes. All four are fixed in the same change, each with a test that fails without the fix. Five residual risks remain; each is low, and two need an owner decision. Rerun this review before v1 and after any change to how Compass starts programs or opens connections.

## Method

1. **Every network path in `src/`.** A search for `urllib`, `http`, `socket`, `requests`, `httpx`, `ssl` and `urlopen` finds one client, `llm.py`. Its loopback check, proxy bypass and redirect handling were read and tested.
2. **Every program Compass starts.** A search for `subprocess`, `os.system`, `exec`, `eval`, `importlib` and `shutil.which` finds them all. Each was traced: what it starts, how the program is found, and with what working directory.
3. **What the repository can influence.** These are `.compass/config.yaml` (committed, so a hostile repository controls it), files at the repository root, and option files that tools read from their working directory.
4. **Live reproduction.** Each suspected problem was reproduced on this machine before it was fixed, then checked again after the fix.

## NF-10: what leaves the machine

| Flow | Goes to | Carries | Control |
| --- | --- | --- | --- |
| MCP answers, SessionStart and prompt context, Stop and SubagentStop reasons | Claude Code, which sends them to Anthropic as part of the session | Map lines, signatures, symbol source, manifests | Allowed by NF-10 ("through Claude Code itself"); each module can be switched off |
| Local model: `summarize_file`, `classify_files`, `compass enrich` | Loopback only | Source of symbols and files | `is_loopback` (`localhost`, `127.0.0.0/8`, `::1`; not `0.0.0.0`), proxies bypassed, **redirects refused (F3)**; off by default |
| Telemetry | `.compass/telemetry.jsonl`, plus `telemetry.export` when set | Counts, timings, task tags, tool names (other MCP servers collapse to `mcp`); never prompts, code or paths | Export is opt-in (TM-02); see R1 |
| Logs | `.compass/logs/` (gitignored) | `gate.jsonl` keeps prompt excerpts for `ask` and `bypass` decisions; `errors.log` keeps tracebacks | Local only; see R4 |
| git | Local commands only: `rev-parse`, `ls-files`, `grep`, `diff`, `ls-tree`, `config`, `symbolic-ref`, `remote get-url` | Nothing leaves: no fetch, push or `ls-remote` | `remote get-url` reads the local config only |
| Installer, upgrade, npm wrapper | PyPI or the chosen feed, astral.sh (the uv installer, only with consent), Claude Code's marketplace | Package downloads | Run by the developer, never by a hook |
| Benchmark harness (`bench/`) | Clones its mirrors | Nothing of the developer's | Developer tooling, not shipped in the plugin |

The dependencies add no traffic of their own. `tree-sitter-language-pack` is pinned to 0.13.0, the last release that bundles its grammars (1.x downloads them at runtime). The `mcp` package brings `httpx`, `starlette` and `uvicorn` for its HTTP transports, but Compass only ever starts stdio (below).

**Verdict:** NF-10 holds, with F3 fixed.

## NF-11: transport and code execution

**stdio only.** `compass mcp` calls `build_server(...).run("stdio")`, and nothing else in `src/` opens a listening socket. The only socket code is `llm.py`'s client. ADR 008 holds.

**What the hooks run.** Every Claude Code hook is `compass hook <event>`. Compass's own code then runs from its package:

- Gate rules and stack detectors are modules in `compass.gate.rules` and `compass.stacks`, found with `importlib` inside the package.
- Tree-sitter queries are data files in `compass/queries/`.
- Config, `language.yaml` and stack manifests are parsed with `yaml.safe_load`.
- No config key names a program to run. `local_llm.base_url` is limited to loopback.
- The skills read `.compass/standards/` as Markdown, for Claude; nothing executes it.

The git hooks Compass writes call the interpreter that wrote them by absolute path. Before this review, though, three paths let the repository supply code, or change a tool's behaviour.

## Findings

| # | Requirement | Severity | Finding | Fix | Test |
| --- | --- | --- | --- | --- | --- |
| F1 | NF-11 | High (Windows) | Programs started by bare name (`git`, `ctags`, `nice`, and `uv`, `claude` and `compass` in the installer) were looked up in the working directory before PATH. On Windows, `CreateProcess` and `shutil.which` both do this, and an empty PATH entry (a stray `;;`, which this machine's PATH has) means the working directory too. Hooks and git hooks run in the repository root, so a committed `git.exe` would have run on every hook. Reproduced: `shutil.which("git")` returned `.\git.EXE`, and `subprocess.run(["git", …])` tried to start the planted file. | `compass.executables.which` resolves every program from absolute PATH entries only; `run_git`, the ctags lookup, `nice`, the installer and `doctor` use it. | `tests/test_executables.py` |
| F2 | NF-11 | High | `python -m compass` puts the working directory first on `sys.path`. The git hooks (on every commit, checkout, merge and rewrite), the background `compass enrich`, `doctor`'s MCP probe and the benchmark's PATH shim all ran it from the repository root. A `compass/` package there would replace Compass, and a `yaml.py` would replace PyYAML. Reproduced: `python -m compass --version` printed the planted package's output. | `-P` (Python 3.11+, which Compass requires) on every `-m compass` Compass starts. Existing repositories keep their old hooks until `compass init` rewrites them, so `compass doctor` now names hooks that differ from what this version writes. | `tests/test_executables.py` |
| F3 | NF-10 | Low | The local-model client used urllib's default redirect handling. A server on loopback could answer the health check (or a completion, as a GET without its body) with a redirect to another host, and the request would follow it off the machine. | Redirects are refused; the call counts as the model being unavailable. | `tests/test_llm.py::test_a_redirect_is_never_followed` |
| F4 | NF-11, NF-13 | Low | Universal Ctags reads option files from `./.ctags.d/` in its working directory (the repository root) and from the developer's home. A repository could switch languages off or change what ctags reports, and a developer's own option files made the index differ between machines. Reproduced: `--languages=-Ruby` in the repository's `.ctags.d/` removed every Ruby symbol. | `--options=NONE`, as the first argument, so no option file is read. `INDEX_FORMAT` is not bumped: output only changes where option files existed, and `compass index --full` rebuilds those indexes. | `tests/test_ctags.py::test_option_files_in_the_repository_are_ignored` (runs with a real Universal Ctags) |

## Residual risks

| # | Risk | Severity | Recommendation |
| --- | --- | --- | --- |
| R1 | `telemetry.export` accepts any path, and `config.yaml` is committed. A hostile repository could make Compass append telemetry rows to a file of its choosing. The rows are Compass's own JSON (counts and tags, no code), so this corrupts that file but does not run code. | Low | **Owner decision (TM-02):** accept only `.jsonl` targets, or take the export path from the developer's own settings rather than the repository. |
| R2 | When the interpreter a git hook names has been removed, the hook falls back to `compass` from PATH through `command -v`. In `sh`, an empty PATH entry means the current directory. | Low | `compass doctor` reports the hooks as written by another Python; `compass init` rewrites them. |
| R3 | Claude Code itself resolves `compass` for each hook and for the MCP entry. That lookup belongs to Claude Code, not Compass. | Outside Compass | On a pilot Windows machine, confirm that a `compass.cmd` committed to a repository root is not what Claude Code runs. |
| R4 | `.compass/logs/gate.jsonl` keeps prompt excerpts for `ask` and `bypass` decisions, so gate rules can be tuned from them. They stay local and gitignored. | Low | Cover it in the data-policy review (decision D5), alongside telemetry export. |
| R5 | A repository's committed `config.yaml` can switch modules on or off for everyone who opens it. That is how teams configure Compass, and no setting runs code. | By design | None. |

## Rerunning this review

- `uv run pytest tests/test_executables.py tests/test_llm.py tests/test_ctags.py` covers F1 to F4. Add `COMPASS_TEST_CTAGS=<path to ctags>` to include the real-ctags test.
- Search again for network modules and process starts in `src/`, and trace any new hit as in the method above.
- Run `compass doctor` in a repository indexed before this change: it should name the git hooks to rewrite until `compass init` runs.
