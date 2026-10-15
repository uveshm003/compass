"""``compass doctor`` (IN-09): what is installed, and is it wired correctly.

One line per check, marked ok, warn or FAIL; the exit code is 1 only when
something is broken. A CLI command, never run from a hook.
"""

from __future__ import annotations

import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

from compass import __version__
from compass.install import SCOPES
from compass.install import record as rec
from compass.install import source
from compass.install.installer import tool_version, wiring
from compass.install.targets import claude_code as cc

MIN_CLAUDE_CODE = "2.1.281"  # the version every done-when check passed on (NF-14)
# Claude Code gives an MCP server 30 s to connect, then works without it.
MCP_TIMEOUT_S = 30.0
MCP_SLOW_S = 10.0
OK, WARN, FAIL = "ok", "warn", "FAIL"

Out = Callable[[str], None]


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.split(".") if p.isdigit())


def run(out: Out = print, check_mcp: bool = True) -> int:
    from compass.repo import NotAGitRepo, find_repo

    results: list[tuple[str, str]] = []

    def say(level: str, text: str) -> None:
        results.append((level, text))
        out(f"  {level:<4}  {text}")

    out(f"Compass {__version__} doctor")
    on_path = tool_version("compass")
    where = shutil.which("compass")
    if where is None:
        say(FAIL, "compass is not on PATH, so Claude Code cannot run its hooks; run `uv tool update-shell` and restart")
    elif on_path != __version__:
        say(WARN, f"compass on PATH ({where}) is {on_path or 'unknown'}, this one is {__version__}")
    else:
        say(OK, f"compass {__version__} on PATH ({where})")
    bundled = source.plugin_version()
    if bundled and bundled != __version__:
        say(WARN, f"the bundled plugin files are {bundled}, the CLI {__version__}")

    claude = tool_version("claude")
    if claude is None:
        say(FAIL, "Claude Code (claude) is not on PATH")
    elif _version_tuple(claude) < _version_tuple(MIN_CLAUDE_CODE):
        say(WARN, f"Claude Code {claude} is older than {MIN_CLAUDE_CODE}, the oldest version Compass is tested with")
    else:
        say(OK, f"Claude Code {claude}")

    try:
        repo = find_repo()
    except NotAGitRepo:
        repo = None
    root = repo.root if repo else None

    wired = wiring(root)
    files_scopes = [s for s, info in wired.items() if info["hooks"]]
    plugin_scopes = [s for s, info in wired.items() if info["plugin"]]
    if files_scopes and plugin_scopes:
        say(FAIL, f"Compass is installed twice: as files ({', '.join(files_scopes)}) and as the plugin"
                  f" ({', '.join(plugin_scopes)}); every hook runs twice. Remove one (`compass uninstall --scope …`)")
    elif len(files_scopes) > 1:
        say(FAIL, f"Compass's hooks are in more than one settings file ({', '.join(files_scopes)}); every hook runs twice")
    elif files_scopes:
        info = wired[files_scopes[0]]
        expected = sorted(cc.hooks_for(source.plugin_root()))
        missing = [e for e in expected if e not in info["hooks"]]
        if missing:
            say(WARN, f"files install ({files_scopes[0]}) lacks hooks for {', '.join(missing)}; run `compass upgrade --skip-cli`")
        else:
            say(OK, f"installed as files ({files_scopes[0]} scope): hooks for {len(info['hooks'])} events")
    elif plugin_scopes:
        say(OK, f"installed as the plugin ({', '.join(plugin_scopes)} scope)")
    else:
        say(WARN, "no Compass plugin or hooks found in Claude Code's settings; run `compass install`")

    for scope in SCOPES:
        if scope != "user" and root is None:
            continue
        record = rec.load(Path.home() if scope == "user" else root, scope)
        if record and record.compass != __version__:
            say(WARN, f"the {scope} install is {record.compass}, the CLI {__version__}; run `compass upgrade --skip-cli`")

    if check_mcp:
        started = time.monotonic()
        tools = _mcp_tools(root)
        took = time.monotonic() - started
        if tools is None:
            say(FAIL, f"`compass mcp` did not start or list its tools within {MCP_TIMEOUT_S:.0f} s, so Claude Code"
                      " would work without it; run it in the repository to see the error")
        elif took > MCP_SLOW_S:
            say(WARN, f"`compass mcp` serves {len(tools)} tools but took {took:.0f} s to start; Claude Code gives up"
                      f" at {MCP_TIMEOUT_S:.0f} s. The first start after an install compiles Python files, so run"
                      " `compass doctor` again; if it stays slow, reinstall with `uv tool install --compile-bytecode`")
        else:
            say(OK, f"`compass mcp` serves {len(tools)} tools")

    if repo is None:
        say(WARN, "not in a git repository; repository checks skipped")
    elif not repo.compass_dir.is_dir():
        say(WARN, f"{repo.root} has no .compass/; run `compass init` (Compass stays idle here)")
    else:
        say(OK if (repo.compass_dir / "index.db").is_file() else WARN,
            "code map built" if (repo.compass_dir / "index.db").is_file() else "no code map yet; run `compass index`")
        from compass.githooks import HOOKS, _is_ours, hooks_dir

        directory, reason = hooks_dir(repo)
        if directory is None:
            say(WARN, f"git hooks: {reason}; add Compass's lines to your own hooks (see `compass init`)")
        else:
            ours = [h for h in HOOKS if _is_ours(directory / h)]
            say(OK if len(ours) == len(HOOKS) else WARN, f"git hooks: {len(ours)} of {len(HOOKS)} installed")
        from compass.config import load_config

        config = load_config(repo.root)
        if config.local_llm.enabled:
            from compass import llm

            up = llm.available(repo, config)
            say(OK if up else WARN, f"local model {config.local_llm.model} " + ("answers" if up else "is not answering"))

    broken = any(level == FAIL for level, _ in results)
    out("Something needs fixing (FAIL above)." if broken else "All good.")
    return 1 if broken else 0


def _mcp_tools(root: Path | None) -> list[str] | None:
    """The tools a fresh ``compass mcp`` lists, as Claude Code would start it; None on failure."""
    try:
        import anyio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        return None

    async def main() -> list[str]:
        params = StdioServerParameters(command=sys.executable, args=["-m", "compass", "mcp"],
                                       cwd=str(root or Path.cwd()))
        with anyio.fail_after(MCP_TIMEOUT_S):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    return [tool.name for tool in listed.tools]

    try:
        return anyio.run(main)
    except Exception:
        return None
