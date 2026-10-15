"""``compass install``, ``compass upgrade`` and the Claude Code half of
``compass uninstall`` (IN-01 to IN-08, IN-15).

An install runs in phases: the CLI on PATH, the Claude Code integration,
``compass init`` in the repository, then the install record. File writes go
through a journal, so a failed integration phase is rolled back; running the
installer again picks up where it stopped (every phase is idempotent).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from compass import __version__
from compass.install import FILES, PLUGIN, SCOPES
from compass.install import record as rec
from compass.install import settings as js
from compass.install import source
from compass.install.targets import claude_code as cc

MODULES = ("query", "prompt_gate", "context_pack", "spec_gate", "review", "delegation", "local_llm")
PRESETS = ("full", "baseline", "custom")
MCP_FILE = ".mcp.json"
USER_MCP = "claude mcp (user)"

Out = Callable[[str], None]


class InstallError(Exception):
    pass


@dataclass
class Options:
    scope: str | None = None
    mode: str | None = None
    modules: str | None = None
    custom: dict[str, bool] = field(default_factory=dict)
    git_hooks: bool | None = None
    init: bool = True
    yes: bool = False
    dry_run: bool = False
    reconfigure: bool = False
    marketplace: str | None = None
    skip_cli: bool = False
    source: str | None = None


# -- running things -----------------------------------------------------------------------


class Journal:
    """File writes that a failed phase can undo; with ``dry_run`` it only says what it would do."""

    def __init__(self, out: Out, dry_run: bool) -> None:
        self.out, self.dry_run = out, dry_run
        self.undo: list[tuple[Path, bytes | None]] = []

    def write(self, path: Path, content: bytes) -> None:
        if self.dry_run:
            self.out(f"  would write {path}")
            return
        self.undo.append((path, path.read_bytes() if path.is_file() else None))
        js.atomic_write(path, content)

    def remove(self, path: Path) -> None:
        if self.dry_run:
            self.out(f"  would remove {path}")
            return
        if path.is_file():
            self.undo.append((path, path.read_bytes()))
            path.unlink()

    def run(self, command: list[str], check: bool = True) -> subprocess.CompletedProcess[str] | None:
        shown = " ".join(command)
        if self.dry_run:
            self.out(f"  would run {shown}")
            return None
        exe = shutil.which(command[0])
        if exe is None:
            raise InstallError(f"`{command[0]}` is not on PATH (needed for: {shown})")
        proc = subprocess.run([exe, *command[1:]], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if check and proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            raise InstallError(f"`{shown}` failed: {detail[-1] if detail else f'exit {proc.returncode}'}")
        return proc

    def rollback(self) -> None:
        for path, previous in reversed(self.undo):
            try:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    js.atomic_write(path, previous)
            except OSError:
                pass
        self.undo.clear()

    def commit(self) -> None:
        self.undo.clear()


def choose(question: str, options: list[tuple[str, str]], default: str, interactive: bool,
           out: Out, ask: Callable[[str], str]) -> str:
    """One numbered question; the default when not interactive or on Enter."""
    if not interactive:
        return default
    labels = "  ".join(f"({i}) {label}" for i, (_, label) in enumerate(options, 1))
    number = next(i for i, (value, _) in enumerate(options, 1) if value == default)
    while True:
        answer = ask(f"? {question}  {labels}  [{number}] ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        for value, _ in options:
            if answer.lower() == value:
                return value
        out(f"  answer 1 to {len(options)}")


def confirm(question: str, default: bool, interactive: bool, ask: Callable[[str], str]) -> bool:
    if not interactive:
        return default
    answer = ask(f"? {question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    return default if not answer else answer.startswith("y")


# -- the CLI on PATH (IN-01) ----------------------------------------------------------------


def find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    exe = "uv.exe" if os.name == "nt" else "uv"
    for candidate in (Path.home() / ".local" / "bin" / exe, Path.home() / ".cargo" / "bin" / exe):
        if candidate.is_file():
            return str(candidate)
    return None


def tool_version(command: str) -> str | None:
    exe = shutil.which(command)
    if exe is None:
        return None
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"\d+\.\d+\.\d+", proc.stdout or "")
    return match.group(0) if match else None


def ephemeral() -> bool:
    """True when this process runs from a throwaway ``uvx`` environment, which
    hooks could not call once it is gone."""
    return any(part.startswith(("archive-v", "builds-v")) for part in Path(sys.prefix).parts)


def ensure_cli(opts: Options, journal: Journal, out: Out) -> None:
    on_path = tool_version("compass")
    if on_path == __version__ and not ephemeral():
        out(f"  compass     {__version__} on PATH ({shutil.which('compass')})")
        return
    uv = find_uv()
    if uv is None:
        raise InstallError(
            "uv is needed to install the compass CLI. Install it (macOS/Linux:"
            " `curl -LsSf https://astral.sh/uv/install.sh | sh`; Windows:"
            " `powershell -ExecutionPolicy ByPass -c \"irm https://astral.sh/uv/install.ps1 | iex\"`), then run this again."
        )
    spec = opts.source or source.package_source() or f"compass=={__version__}"
    out(f"  compass     installing {spec} with uv tool …")
    journal.run([uv, "tool", "install", "--force", "--compile-bytecode", spec])
    if not opts.dry_run and shutil.which("compass") is None:
        journal.run([uv, "tool", "update-shell"], check=False)
        out("  PATH        added uv's tool folder; open a new terminal (and restart your IDE) before starting Claude Code")


# -- config presets (IN-15) -----------------------------------------------------------------


def config_text(preset: str, custom: dict[str, bool]) -> str:
    from compass.config import DEFAULT_CONFIG_TEXT

    if preset == "baseline":
        choices = {m: False for m in MODULES}
    elif preset == "custom":
        choices = dict(custom)
    else:
        choices = {}
    text = DEFAULT_CONFIG_TEXT
    for module, on in choices.items():
        text, count = re.subn(rf"(?m)^({re.escape(module)}:\n  enabled: )(true|false)",
                              rf"\g<1>{'true' if on else 'false'}", text, count=1)
        if count != 1:
            raise InstallError(f"no `{module}.enabled` in the default config")
    return text


# -- what is installed where ----------------------------------------------------------------


def base_for(scope: str, repo_root: Path | None) -> Path:
    if scope == "user":
        return Path.home()
    if repo_root is None:
        raise InstallError(f"--scope {scope} needs a git repository; run it inside one, or use --scope user")
    return repo_root


def wiring(repo_root: Path | None) -> dict[str, dict[str, Any]]:
    """Per settings file: the compass plugin it enables and the events it wires
    to ``compass hook``. Unreadable files count as empty."""
    found = {}
    for scope, path in cc.settings_paths(repo_root).items():
        try:
            data = js.load(path)
        except js.SettingsError:
            data = None
        found[scope] = {"path": path, "plugin": js.enabled_plugin(data), "hooks": js.compass_hook_events(data)}
    return found


def check_conflict(mode: str, target: str, repo_root: Path | None) -> None:
    """Refuse a second install mode, or files mode in a second scope: either
    would run every hook twice."""
    for scope, info in wiring(repo_root).items():
        if mode == FILES and info["hooks"] and scope != target:
            raise InstallError(
                f"Compass is already installed as files for the {scope} scope ({info['path']}); a second copy would run"
                f" every hook twice. Run `compass uninstall --scope {scope}` first, or install with --scope {scope}."
            )
        if mode == FILES and info["plugin"]:
            raise InstallError(
                f"the Compass plugin is already enabled ({scope} settings, {info['path']}); with files mode too every"
                f" hook would run twice. Remove it first (`claude plugin uninstall {info['plugin']} --scope {scope}`),"
                " or install with --mode plugin."
            )
        if mode == PLUGIN and info["hooks"]:
            raise InstallError(
                f"Compass is already installed as files ({scope} settings, {info['path']}); with the plugin too every"
                f" hook would run twice. Run `compass uninstall --scope {scope}` first, or install with --mode files."
            )


# -- compass install --------------------------------------------------------------------------


def install(opts: Options, out: Out = print, ask: Callable[[str], str] = input) -> int:
    from compass.repo import NotAGitRepo, find_repo

    try:
        repo = find_repo()
    except NotAGitRepo:
        repo = None
    root = repo.root if repo else None
    interactive = not opts.yes and not opts.dry_run and sys.stdin.isatty()

    out(f"Compass {__version__} installer" + (" (dry run: nothing is changed)" if opts.dry_run else ""))
    scope = opts.scope or choose(
        "Install for:", [("user", "just me, every project"), ("project", "this repository, for the whole team")],
        "project" if repo else "user", interactive, out, ask,
    )
    if scope not in SCOPES:
        raise InstallError(f"unknown scope {scope!r} (user, project or local)")
    base = base_for(scope, root)
    mode = opts.mode or choose(
        "Install as:", [(PLUGIN, "Claude Code plugin"), (FILES, "files in .claude/")], PLUGIN, interactive, out, ask,
    )
    if mode == FILES and scope == "local":
        raise InstallError("files mode has no local scope (Claude Code has no untracked commands folder); use --scope project or user")
    preset = opts.modules or (choose(
        "Modules:", [("full", "full"), ("baseline", "baseline: telemetry only"), ("custom", "choose each")],
        "full", interactive, out, ask,
    ) if repo and opts.init else "full")
    if preset not in PRESETS:
        raise InstallError(f"unknown module preset {preset!r} (full, baseline or custom)")
    custom = dict(opts.custom)
    if preset == "custom":
        for module in MODULES:
            if module in custom:
                continue
            if module == "local_llm" and not _local_model_answers(root):
                custom[module] = False
                out("  local model  none answering on localhost (switch it on later in .compass/config.yaml)")
                continue
            custom[module] = confirm(f"Switch on {module}?", module != "local_llm", interactive, ask)
    git_hooks = opts.git_hooks if opts.git_hooks is not None else (
        confirm("Install git hooks (keep the map fresh, refuse commits that still carry review tags)?", True,
                interactive, ask) if repo and opts.init else True
    )

    journal = Journal(out, opts.dry_run)
    if not opts.skip_cli:
        ensure_cli(opts, journal, out)
    check_conflict(mode, scope, root)
    previous = rec.load(base, scope)
    record = rec.Record(compass=__version__, mode=mode, scope=scope, installed_at=rec.now())
    try:
        if mode == FILES:
            install_files(base, scope, previous, record, journal, out)
        else:
            install_plugin(scope, opts.marketplace, base, previous, record, journal, out)
    except Exception:
        journal.rollback()
        raise
    journal.commit()

    if repo is not None and opts.init:
        record.init = {"modules": preset, "git_hooks": git_hooks}
        if preset == "custom":
            record.init["custom"] = {m: custom[m] for m in MODULES}
        init_repo(repo, config_text(preset, custom), opts.reconfigure, git_hooks, opts.dry_run, out)
    elif opts.init:
        out("  init        skipped: not in a git repository (run `compass init` in each repository)")

    record_path = rec.path_for(base, scope)
    journal.write(record_path, record.to_json().encode("utf-8"))
    journal.commit()
    out(f"  record      {record_path}")
    out("")
    out("Done. Restart Claude Code, then run `compass doctor`." if not opts.dry_run else "Dry run finished; nothing was changed.")
    if scope == "project" and not opts.dry_run:
        out("Commit .claude/ and .compass/config.yaml (and .mcp.json in files mode) so the team gets Compass too.")
    return 0


def _local_model_answers(root: Path | None) -> bool:
    try:
        from compass import llm
        from compass.config import load_config

        config = load_config(root or Path.cwd())
        return llm.LocalModel(config.local_llm, None).healthy(use_cache=False)
    except Exception:
        return False


def install_files(base: Path, scope: str, previous: rec.Record | None, record: rec.Record,
                  journal: Journal, out: Out) -> None:
    plugin = source.plugin_root()
    wanted = cc.files_for(plugin)
    settings_rel = cc.settings_rel(scope)
    js.load(base / settings_rel)  # refuse an unreadable file before writing anything
    if scope == "project":
        js.load(base / MCP_FILE)
    kept = []
    for action in rec.plan_files(base, wanted, previous):
        path = base / action.rel
        if action.action in ("write", "add"):
            journal.write(path, action.content or b"")
            record.files[action.rel] = rec.digest(action.content or b"")
        elif action.action == "same":
            record.files[action.rel] = rec.digest(action.content or b"")
        elif action.action in ("keep-edited", "keep-existing"):
            journal.write(path.with_name(path.name + rec.NEW_SUFFIX), action.content or b"")
            kept.append(action.rel)
            if action.action == "keep-edited" and previous:
                record.files[action.rel] = previous.files[action.rel]
        elif action.action == "keep-deleted" and previous:
            record.files[action.rel] = previous.files[action.rel]
        elif action.action == "remove":
            journal.remove(path)
    out(f"  files       {len(record.files)} files under {base / '.claude'}")
    for rel in kept:
        out(f"  kept        {rel} (edited); the new version is beside it as {Path(rel).name}{rec.NEW_SUFFIX}")

    created = merge_json(base / settings_rel, lambda d: js.merge_hooks(d, cc.hooks_for(plugin)), journal,
                         (previous.settings.get(settings_rel) if previous else None))
    record.settings[settings_rel] = {"created": created}
    out(f"  hooks       {settings_rel}: compass hook for {', '.join(sorted(cc.hooks_for(plugin)))}")

    server = cc.server_for(plugin)
    if scope == "project":
        created = merge_json(base / MCP_FILE, lambda d: js.merge_server(d, cc.SERVER, server), journal,
                             (previous.mcp.get(MCP_FILE) if previous else None))
        record.mcp[MCP_FILE] = {"created": created}
        out(f"  mcp         {MCP_FILE}: compass")
    else:
        proc = journal.run(cc.user_mcp_add(), check=False)
        if proc is not None and proc.returncode != 0 and "already exists" not in (proc.stdout + proc.stderr):
            raise InstallError(f"`{' '.join(cc.user_mcp_add())}` failed: {(proc.stderr or proc.stdout).strip()}")
        record.mcp[USER_MCP] = {"scope": "user"}
        out("  mcp         compass registered for your user (claude mcp add --scope user)")


def merge_json(path: Path, change: Callable[[dict[str, Any]], dict[str, Any]], journal: Journal,
               earlier: dict[str, Any] | None) -> bool:
    """Apply ``change`` to a JSON file, keeping a backup before the first
    write; returns whether Compass created the file (as first recorded)."""
    data = js.load(path)
    created = bool(earlier.get("created")) if earlier else data is None
    new = change(data or {})
    if data is not None and new == data:
        return created
    backup = js.backup_path(path)
    if path.is_file() and not backup.exists() and not created:
        journal.write(backup, path.read_bytes())
    journal.write(path, js.dumps(new))
    return created


def install_plugin(scope: str, marketplace: str | None, base: Path, previous: rec.Record | None,
                   record: rec.Record, journal: Journal, out: Out) -> None:
    market = marketplace or str(lasting_bundle())
    local_path = marketplace is None or Path(market).exists()
    if scope == "project" and local_path:
        out("  note        the marketplace is a folder on this machine, which teammates won't have;"
            " pass --marketplace <owner>/<repo> (or the Azure Repos URL) for a team-wide install")
    settings_rel = cc.settings_rel(scope)
    settings = base / settings_rel
    js.load(settings)  # refuse an unreadable file before Claude Code edits it
    earlier = previous.plugin if previous and previous.mode == PLUGIN else {}
    created = bool(earlier["settings"].get("created")) if isinstance(earlier.get("settings"), dict) else not settings.is_file()
    if settings.is_file() and not created and not js.backup_path(settings).exists():
        journal.write(js.backup_path(settings), settings.read_bytes())
    added = bool(earlier.get("marketplace_added"))
    for command in cc.plugin_commands(market, scope, source.PLUGIN_ID):
        proc = journal.run(command, check=False)
        said = (proc.stdout + proc.stderr).lower() if proc is not None else ""
        if proc is not None and proc.returncode != 0 and "already" not in said:
            detail = (proc.stderr or proc.stdout).strip().splitlines()
            raise InstallError(f"`{' '.join(command)}` failed: {detail[-1] if detail else proc.returncode}")
        if command[2] == "marketplace" and proc is not None and "already" not in said:
            added = True  # Compass added it, so uninstall removes it; a marketplace the developer had stays
    record.plugin = {"id": source.PLUGIN_ID, "marketplace": market, "marketplace_added": added,
                     "settings": {"path": settings_rel, "created": created}}
    out(f"  plugin      {source.PLUGIN_ID} installed (scope: {scope})")


def lasting_bundle() -> Path:
    """The bundle Claude Code's marketplace should point at: for a uvx run,
    the copy in the uv tool environment ``ensure_cli`` installed, which
    ``compass upgrade`` refreshes in place; otherwise this install's own."""
    here = source.bundle_root()
    uv = find_uv() if ephemeral() else None
    if uv is None:
        return here
    try:
        tools = subprocess.run([uv, "tool", "dir"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return here
    env = Path(tools) / "compass"
    for pattern in ("Lib/site-packages/compass/_bundle", "lib/python*/site-packages/compass/_bundle"):
        for candidate in sorted(env.glob(pattern)):
            if (candidate / "plugin" / ".claude-plugin" / "plugin.json").is_file():
                return candidate
    return here


def init_repo(repo, text: str, reconfigure: bool, git_hooks: bool, dry_run: bool, out: Out) -> None:
    config = repo.config_path
    if dry_run:
        out(f"  would write {config}" if reconfigure or not config.exists() else f"  config      {config} kept")
        out("  would run compass init" + ("" if git_hooks else " --no-git-hooks"))
        return
    if reconfigure or not config.exists():
        repo.ensure_state_dir()
        config.write_text(text, encoding="utf-8", newline="\n")
    args = ["-C", str(repo.root), "init", *([] if git_hooks else ["--no-git-hooks"])]
    if ephemeral() and shutil.which("compass"):
        # The git hooks name the interpreter that installs them, so let the
        # persistent compass write them, not this throwaway environment.
        subprocess.run([shutil.which("compass") or "compass", *args], check=False)
    else:
        from compass.cli import main

        cwd = os.getcwd()
        try:
            main(args)
        finally:
            os.chdir(cwd)


# -- compass uninstall (IN-07) --------------------------------------------------------------


def uninstall(base: Path, scope: str, out: Out = print, dry_run: bool = False) -> bool:
    """Remove what the scope's install record lists; False when there is none."""
    record = rec.load(base, scope)
    if record is None:
        return False
    journal = Journal(out, dry_run)
    for rel, recorded in sorted(record.files.items()):
        path = base / rel
        sibling = path.with_name(path.name + rec.NEW_SUFFIX)
        if sibling.is_file():
            journal.remove(sibling)
        if not path.is_file():
            continue
        if rec.digest(path.read_bytes()) == recorded:
            journal.remove(path)
        else:
            out(f"  kept        {rel} (edited since it was installed)")
    for rel, meta in sorted(record.settings.items()):
        unmerge_json(base / rel, js.remove_hooks, bool(meta.get("created")), journal)
    for rel, meta in sorted(record.mcp.items()):
        if rel == USER_MCP:
            journal.run(cc.user_mcp_remove(), check=False)
        else:
            unmerge_json(base / rel, lambda d: js.remove_server(d, cc.SERVER), bool(meta.get("created")), journal)
    if record.plugin:
        plugin_id = record.plugin.get("id") or source.PLUGIN_ID
        ours = plugin_id.partition("@")[2] if record.plugin.get("marketplace_added") else None
        for command in cc.plugin_uninstall_commands(scope, plugin_id, ours):
            journal.run(command, check=False)
        meta = record.plugin.get("settings")
        if isinstance(meta, dict) and meta.get("path"):
            unmerge_json(base / meta["path"], lambda d: js.remove_plugin(d, plugin_id, ours),
                         bool(meta.get("created")), journal)
    journal.remove(rec.path_for(base, scope))
    if not dry_run:  # folders the removed files leave empty go too, up to (not including) .claude/
        stop = base / ".claude"
        folders = {(base / rel).parent for rel in record.files} | {rec.path_for(base, scope).parent}
        for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
            while folder != stop and stop in folder.parents:
                try:
                    folder.rmdir()  # only when empty
                except OSError:
                    break
                folder = folder.parent
    journal.commit()
    out(f"  claude      removed Compass's {record.mode} install ({scope} scope)")
    return True


def unmerge_json(path: Path, change: Callable[[dict[str, Any]], dict[str, Any]], created: bool,
                 journal: Journal) -> None:
    try:
        data = js.load(path)
    except js.SettingsError as exc:
        journal.out(f"  skipped     {exc}")
        return
    if data is None:
        return
    content = js.restore_or_write(path, change(data), created)
    if content is None:
        journal.remove(path)
    elif content != path.read_bytes():
        journal.write(path, content)
    backup = js.backup_path(path)
    if backup.is_file():
        journal.remove(backup)


# -- compass upgrade (IN-06) ----------------------------------------------------------------


def upgrade(opts: Options, out: Out = print) -> int:
    """A newer CLI first (only when asked: never from a hook), then the
    installed files refreshed by the new CLI itself."""
    from compass.repo import NotAGitRepo, find_repo

    journal = Journal(out, opts.dry_run)
    if not opts.skip_cli:
        uv = find_uv()
        if uv is None:
            raise InstallError("uv is not on PATH; upgrade the compass CLI with it, then run `compass upgrade --skip-cli`")
        spec = opts.source or source.package_source()
        out(f"  compass     upgrading {spec or 'compass'} with uv tool …")
        journal.run([uv, "tool", "install", "--force", "--compile-bytecode", spec] if spec
                    else [uv, "tool", "upgrade", "--compile-bytecode", "compass"])
        if opts.dry_run:
            return 0
        new = shutil.which("compass")
        if new is None:
            raise InstallError("compass is not on PATH after the upgrade; open a new terminal and run `compass upgrade --skip-cli`")
        return subprocess.run([new, "upgrade", "--skip-cli", *(["--yes"] if opts.yes else [])], check=False).returncode

    try:
        root: Path | None = find_repo().root
    except NotAGitRepo:
        root = None
    done = 0
    for scope in SCOPES:
        if scope != "user" and root is None:
            continue
        base = base_for(scope, root)
        previous = rec.load(base, scope)
        if previous is None:
            continue
        record = rec.Record(compass=__version__, mode=previous.mode, scope=scope, installed_at=rec.now(),
                            init=previous.init)
        out(f"Upgrading the {scope} install ({previous.mode} mode, {previous.compass} -> {__version__})")
        try:
            if previous.mode == FILES:
                install_files(base, scope, previous, record, journal, out)
            else:
                record.plugin = previous.plugin
                for command in cc.plugin_update_commands(source.MARKETPLACE, scope,
                                                          previous.plugin.get("id") or source.PLUGIN_ID):
                    journal.run(command, check=False)
                out(f"  plugin      {source.PLUGIN_ID} updated (scope: {scope}); restart Claude Code")
        except Exception:
            journal.rollback()
            raise
        journal.write(rec.path_for(base, scope), record.to_json().encode("utf-8"))
        journal.commit()
        done += 1
    if not done:
        out("Nothing to upgrade: no install record for this repository or your user. Run `compass install`.")
    return 0
