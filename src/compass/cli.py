"""The ``compass`` command.

argparse rather than Typer: every Claude Code hook runs ``compass hook ...``,
and Typer's import alone costs about a quarter of the prompt gate's 100 ms
budget (NF-01). Heavier modules are imported inside the commands that use them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from compass import __version__

EXIT_OK = 0
EXIT_ERROR = 1


def app() -> None:
    sys.exit(main())


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _utf8_stdio()
    event = _hook_event(argv)
    if event is not None:
        from compass import hooks

        return hooks.run(event)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.directory:
        try:
            os.chdir(args.directory)
        except OSError as exc:
            return _fail(f"cannot change to {args.directory}: {exc.strerror}")
    if args.command is None:
        parser.print_help()
        return EXIT_OK

    from compass.files import GitError
    from compass.lock import LockTimeout
    from compass.repo import NotAGitRepo

    try:
        return COMMANDS[args.command](args)
    except NotAGitRepo as exc:
        return _fail(f"{exc} (Compass works on git repositories)")
    except (GitError, LockTimeout) as exc:
        return _fail(str(exc))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # Background runs have no terminal, so the log is the only record.
        from compass.log import log_error
        from compass.repo import find_initialized_repo

        repo = find_initialized_repo(os.getcwd())
        if repo is None:
            raise
        log_error(repo.root, f"compass {args.command}", exc)
        return _fail(f"internal error: {exc!r} (details in .compass/logs/errors.log)")


def _hook_event(argv: list[str]) -> str | None:
    """The event for ``compass [-C DIR] hook <event> ...``, or None for other commands.

    Hooks bypass argparse: its usage errors exit 2, which Claude Code reads as
    "block". Extra arguments from a newer hook config are ignored.
    """
    i = 0
    directory = None
    while i < len(argv) and argv[i] == "-C":
        directory = argv[i + 1] if i + 1 < len(argv) else None
        i += 2
    if i >= len(argv) or argv[i] != "hook":
        return None
    if directory:
        try:
            os.chdir(directory)
        except OSError:
            pass
    return argv[i + 1] if i + 1 < len(argv) else ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compass",
        description="Code map, prompt gates and review manifests for Claude Code.",
    )
    parser.add_argument("--version", action="version", version=f"compass {__version__}")
    parser.add_argument("-C", dest="directory", metavar="DIR", help="run as if compass was started in DIR")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("init", help="create .compass/, config and git hooks, then build the first index")
    p.add_argument("--no-git-hooks", action="store_true", help="do not install git hooks")
    p.add_argument("--no-index", action="store_true", help="do not build the index yet")

    p = sub.add_parser("index", help="build or refresh the SQLite index and map shards")
    p.add_argument("--full", action="store_true", help="re-parse every file, not only changed ones")
    p.add_argument("--json", action="store_true", help="print the result as JSON")

    p = sub.add_parser("update", help="re-index the given files, or everything that changed")
    p.add_argument("paths", nargs="*", help="files or directories (default: every changed file)")
    p.add_argument(
        "--from-git",
        action="store_true",
        help="refresh after a git operation (used by git hooks; never fails)",
    )
    p.add_argument("--json", action="store_true", help="print the result as JSON")

    p = sub.add_parser("files", help="list the files Compass indexes, with language and hash")
    p.add_argument("--json", action="store_true", help="print as JSON")

    p = sub.add_parser("stack", help="show the stack profile read from manifests")
    p.add_argument("--json", action="store_true", help="print as JSON")

    # Only for --help: main() dispatches `hook` before argparse (see _hook_event).
    p = sub.add_parser("hook", help="entry point for Claude Code hooks; reads the hook JSON on stdin")
    p.add_argument("event", metavar="event", help="session-start | prompt | pre-edit | post-edit | stop")
    return parser


# -- commands ---------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    from compass.config import DEFAULT_CONFIG_TEXT
    from compass.repo import find_repo

    repo = find_repo()
    repo.ensure_state_dir()
    lines = [f"Compass in {repo.root}"]
    if repo.config_path.exists():
        lines.append("  config      .compass/config.yaml exists; kept as is")
    else:
        repo.config_path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8", newline="\n")
        lines.append("  config      wrote .compass/config.yaml (commit it)")
    lines.append("  gitignore   .compass/.gitignore keeps derived files out of git")
    if not args.no_git_hooks:
        from compass.githooks import install

        for message in install(repo):
            lines.append(f"  git hook    {message}")
    config = _config(repo)
    print("\n".join(lines))
    if not args.no_index:
        from compass.index.indexer import Indexer

        result = Indexer(repo, config).build()
        print(f"  index       {_describe(result)}")
        print("  map         .compass/map/_index.md")
    return EXIT_OK


def cmd_index(args: argparse.Namespace) -> int:
    from compass.index.indexer import Indexer
    from compass.repo import find_repo

    repo = find_repo()
    # The manual command also rewrites every shard, so it doubles as a repair.
    result = Indexer(repo, _config(repo)).build(full=args.full, repair=True)
    if args.json:
        print(json.dumps(result.as_dict()))
    else:
        print(_describe(result))
    return EXIT_OK


def cmd_update(args: argparse.Namespace) -> int:
    if args.from_git:
        return _update_from_git()
    from compass.index.indexer import Indexer
    from compass.repo import find_repo

    repo = find_repo()
    indexer = Indexer(repo, _config(repo))
    rels = []
    everything = not args.paths
    for raw in args.paths:
        rel = repo.relpath(raw)
        if rel is None:
            print(f"compass: skipping {raw}: outside {repo.root}", file=sys.stderr)
        elif rel == "":
            everything = True  # the repo root itself
        else:
            rels.append(rel)
    if not (rels or everything):
        return EXIT_ERROR
    result = indexer.build() if everything else indexer.update(rels)
    print(json.dumps(result.as_dict()) if args.json else _describe(result))
    return EXIT_OK


def _update_from_git() -> int:
    """Called by git hooks: refresh inline when the change is small, hand big
    ones to a background process, and never fail the git command."""
    from compass.log import log_error
    from compass.repo import find_repo

    repo = None
    try:
        from compass.hooks import refresh_or_hand_off

        repo = find_repo()
        if repo.initialized:
            refresh_or_hand_off(repo, lock_wait=2.0)
    except Exception as exc:
        log_error(repo.root if repo else None, "update --from-git", exc)
    return EXIT_OK


def cmd_files(args: argparse.Namespace) -> int:
    from compass.files import enumerate_files
    from compass.globs import compile_globs
    from compass.languages import load_registry
    from compass.repo import find_repo

    repo = find_repo()
    settings = _config(repo).index
    infos = enumerate_files(repo.root, compile_globs(settings.exclude), load_registry(), settings.max_file_bytes)
    if args.json:
        rows = [{"path": i.path, "lang": i.lang, "size": i.size, "hash": i.hash} for i in infos]
        print(json.dumps(rows, indent=1))
    else:
        width = max((len(i.lang or "-") for i in infos), default=1)
        for info in infos:
            print(f"{info.lang or '-':<{width}}  {info.path}")
    return EXIT_OK


def cmd_stack(args: argparse.Namespace) -> int:
    from compass.repo import find_repo
    from compass.stack import build_profile, render_text

    repo = find_repo()
    profile = build_profile(repo.root, _config(repo))
    print(json.dumps(profile, indent=2) if args.json else render_text(profile))
    return EXIT_OK


COMMANDS = {
    "init": cmd_init,
    "index": cmd_index,
    "update": cmd_update,
    "files": cmd_files,
    "stack": cmd_stack,
}


# -- helpers ----------------------------------------------------------------


def _config(repo):
    from compass.config import load_config

    config = load_config(repo.root)
    for warning in config.warnings:
        print(f"compass: warning: {warning}", file=sys.stderr)
    return config


def _describe(result) -> str:
    what = f"{result.files} files, {result.symbols} symbols"
    if result.mode == "full":
        return f"Indexed {what} in {result.seconds:.2f} s (full build)."
    changes = f"{result.parsed} re-parsed, {result.removed} removed"
    return f"Index up to date: {what} ({changes}, {result.seconds:.2f} s)."


def _fail(message: str) -> int:
    print(f"compass: {message}", file=sys.stderr)
    return EXIT_ERROR


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
