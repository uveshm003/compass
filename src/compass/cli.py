"""The ``compass`` command.

argparse rather than Typer: every Claude Code hook runs ``compass hook ...``,
and Typer's import alone costs about a quarter of the prompt gate's 100 ms
budget (NF-01). Heavier modules are imported inside the commands that use them.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING

from compass import __version__

if TYPE_CHECKING:  # argparse is imported only past the hook fast path
    import argparse

EXIT_OK = 0
EXIT_ERROR = 1
NOT_INITIALIZED = "this repository has no .compass/ yet; run `compass init` first"


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
    import argparse

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

    sub.add_parser("uninstall", help="remove Compass's git hooks (restoring any they chained); keeps .compass/")

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

    p = sub.add_parser("stack", aliases=["stack-profile"], help="show the stack profile read from manifests")
    p.add_argument("--json", action="store_true", help="print as JSON")

    # The query tools: each is the CLI twin of the MCP tool of the same name (QT-04).
    p = sub.add_parser("find-symbol", help="find definitions by name (MCP: find_symbol)")
    p.add_argument("name", help="a name or part of one; Class.method works too")
    p.add_argument("--kind", help="only this kind: class, function, method, interface, ...")
    p.add_argument("--path", help="only in this file or directory")
    _query_output(p)

    p = sub.add_parser("read-symbol", help="print one symbol's source lines (MCP: read_symbol)")
    p.add_argument("name")
    p.add_argument("--path", help="pick the definition in this file when the name is ambiguous")
    p.add_argument("--context", type=int, help="extra lines around the symbol (default: query.context_lines)")
    _query_output(p)

    p = sub.add_parser("file-outline", help="list what a file defines (MCP: file_outline)")
    p.add_argument("path")
    _query_output(p)

    p = sub.add_parser("map", help="the folder tree, or one directory's files and symbols (MCP: map)")
    p.add_argument("dir", nargs="?", default="", help="a directory (default: the whole tree)")
    _query_output(p)

    p = sub.add_parser("tests-for", help="tests for a file or symbol (MCP: tests_for)")
    p.add_argument("target", help="a file path or a symbol name")
    _query_output(p)

    p = sub.add_parser("importers-of", help="files importing a file or module (MCP: importers_of)")
    p.add_argument("target", help="a file path, a directory, or a module name such as react")
    _query_output(p)

    p = sub.add_parser("callers-of", help="call sites of a function or method (MCP: callers_of)")
    p.add_argument("name")
    _query_output(p)

    sub.add_parser("mcp", help="serve the query tools over MCP on stdin/stdout")

    # Review output (RO-02 to RO-05).
    p = sub.add_parser("task", help="show the active task, or start a new one")
    p.add_argument("action", nargs="?", choices=["show", "new"], default="show")
    p.add_argument("--brief", help="with new: the task's brief, or - to read it from stdin (what /compass:task runs)")
    p.add_argument("--json", action="store_true", help="print as JSON")

    p = sub.add_parser("approve", help="approve a large task's spec so Claude may change code (/compass:approve)")
    p.add_argument("task", nargs="?", help="task id (default: the active task)")

    p = sub.add_parser("check-prompt", help="dry-run the prompt gate and context pack on a prompt")
    p.add_argument("prompt", help="the prompt text, or - to read it from stdin")

    p = sub.add_parser("report", help="compare tasks run with Compass on and off (telemetry or benchmark results)")
    p.add_argument("paths", nargs="*", help="telemetry files or bench/results folders (default: this repo's telemetry)")
    p.add_argument("--since", metavar="YYYY-MM-DD", help="only tasks from this date on")
    p.add_argument("--json", action="store_true", help="print the numbers as JSON")

    # The local model (DL-04, DL-05): off unless local_llm.enabled.
    p = sub.add_parser("enrich", help="summarise undocumented symbols with the local model (background job)")
    p.add_argument("--limit", type=int, help="most symbols to summarise this run (default: local_llm.enrich_limit)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")

    p = sub.add_parser("summarize-file", help="the gist of a file from the local model (MCP: summarize_file)")
    p.add_argument("path")
    p.add_argument("--focus", help="a specific question about the file")
    _query_output(p)

    p = sub.add_parser("classify-files", help="sort files into labels with the local model (MCP: classify_files)")
    p.add_argument("paths", nargs="+")
    p.add_argument("--labels", required=True, help="comma-separated labels, e.g. test,config,logic")
    _query_output(p)

    p = sub.add_parser("manifest", help="write the change manifest of a task (default: the active one)")
    p.add_argument("task", nargs="?", help="task id, e.g. T3")
    p.add_argument("--hosted", action="store_true", help="print it with links into GitHub or Azure DevOps")
    p.add_argument("--ref", help="branch or commit the hosted links point at (default: the current branch)")
    p.add_argument("--json", action="store_true", help="print the manifest data as JSON")

    p = sub.add_parser("accept", help="strip a reviewed task's anchors and archive its manifest")
    p.add_argument("task", nargs="?", help="task id (default: the active task)")

    p = sub.add_parser("check-anchors", help="list anchor tags; --staged is the pre-commit check")
    p.add_argument("task", nargs="?", help="only this task's anchors")
    p.add_argument("--staged", action="store_true", help="check the lines a commit would add; exit 1 if any")

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


def cmd_uninstall(args: argparse.Namespace) -> int:
    from compass.githooks import uninstall
    from compass.repo import find_repo

    repo = find_repo()
    for message in uninstall(repo):
        print(message)
    print(
        "Left in place: .compass/ (delete it to drop the index and manifests; config.yaml is yours)."
        " Remove the Claude Code plugin with `claude plugin uninstall compass`."
    )
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
            if _config(repo, quiet=True).local_llm.enabled:
                # Summaries for new code, detached and at low priority: the commit never waits (DL-05).
                from compass import background

                background.spawn(["-C", str(repo.root), "enrich"], repo.root, low_priority=True)
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


def cmd_mcp(args: argparse.Namespace) -> int:
    from compass.mcp_server import serve

    # -C names the repo explicitly; otherwise Claude Code's project dir, then the cwd.
    serve(os.getcwd() if args.directory else None)
    return EXIT_OK


def cmd_task(args: argparse.Namespace) -> int:
    from compass import review, state
    from compass.repo import find_repo

    repo = find_repo()
    if not repo.initialized:
        return _fail(NOT_INITIALIZED)
    if args.action == "new" and args.brief is not None:
        from compass.gate.hook import start_task

        print(start_task(repo, sys.stdin.read() if args.brief == "-" else args.brief))
        return EXIT_OK
    with state.transaction(repo) as st:
        previous = state.active_task(st)
        if args.action == "new" and previous is not None:
            # The old task stays acceptable by id; one with nothing recorded is dropped.
            if not state.touched(st, previous):
                st["tasks"].pop(previous, None)
            st["task"] = None
        task = state.ensure_task(st, None if state.active_task(st) else review.taken_ids(repo))
        touched = state.touched(st, task)
        record = dict(st["tasks"].get(task) or {})
    size = record.get("size") or "not sized yet"
    if args.json:
        print(json.dumps({
            "task": task, "touched": touched, "manifest": review.manifest_rel(task), "size": record.get("size"),
            "reason": record.get("reason"), "approved": record.get("approved"), "brief": record.get("brief"),
        }))
    else:
        approval = ""
        if record.get("size") == "large":
            approval = f"; spec approved by {record['approved']['by']}" if record.get("approved") else "; spec not approved"
        print(f"{task}  ({size}{approval}; {len(touched)} files changed; manifest {review.manifest_rel(task)})")
    return EXIT_OK


def cmd_approve(args: argparse.Namespace) -> int:
    from compass.gate.hook import approve_task
    from compass.repo import find_repo

    repo = find_repo()
    if not repo.initialized:
        return _fail(NOT_INITIALIZED)
    code, message = approve_task(repo, args.task)
    if code:
        return _fail(message)
    print(message)
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    from pathlib import Path

    from compass import report
    from compass.repo import find_repo

    gate = None
    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        repo = find_repo()
        if not repo.initialized:
            return _fail(NOT_INITIALIZED)
        paths = [repo.compass_dir / "telemetry.jsonl"]
        gate = report.gate_summary(repo.logs_dir / "gate.jsonl", args.since)
    missing = [str(p) for p in paths if not p.exists()]
    if missing and len(missing) == len(paths) and args.paths:
        return _fail(f"no such file or folder: {', '.join(missing)}")
    tasks = report.tasks_from_rows(report.load(paths), args.since)
    if args.json:
        print(json.dumps(report.as_json(tasks, gate), indent=2, sort_keys=True))
    elif any(t.bench for t in tasks):
        print(report.bench_text(tasks))
    else:
        print(report.pilot_text(tasks, [str(p) for p in paths if p.exists()], gate))
    return EXIT_OK


def cmd_enrich(args: argparse.Namespace) -> int:
    from compass import enrich
    from compass.repo import find_repo

    repo = find_repo()
    if not repo.initialized:
        return _fail(NOT_INITIALIZED)
    result = enrich.run(repo, _config(repo, quiet=True), args.limit)
    if args.json:
        print(json.dumps(result))
    elif "skipped" in result:
        print(f"compass enrich: nothing done: {result['skipped']}.")
    else:
        print(
            f"Summarised {result['summarised']} symbols ({result['cached']} already cached, {result['left']} left"
            f" for the next run); {result['applied']} applied to the code map."
        )
    return EXIT_OK


def _local_query(args: argparse.Namespace, run) -> int:
    """The local-model twins: like the query commands, when a model answers."""
    from compass.llm import LocalModel
    from compass.repo import find_repo

    repo = find_repo()
    model = LocalModel(_config(repo, quiet=True).local_llm, repo)
    if not model.healthy(use_cache=False):
        return _fail("no local model answering; set local_llm in .compass/config.yaml and start it (Ollama, LM Studio)")
    return _run_query(args, lambda q: run(q, model))


def cmd_summarize_file(args: argparse.Namespace) -> int:
    from compass.local_tools import summarize_file

    return _local_query(args, lambda q, model: summarize_file(q, model, args.path, args.focus))


def cmd_classify_files(args: argparse.Namespace) -> int:
    from compass.local_tools import classify_files

    return _local_query(args, lambda q, model: classify_files(q, model, args.paths, args.labels.split(",")))


def cmd_check_prompt(args: argparse.Namespace) -> int:
    from compass.gate.hook import dry_run
    from compass.repo import find_repo

    repo = find_repo()
    print(dry_run(repo, sys.stdin.read() if args.prompt == "-" else args.prompt))
    return EXIT_OK


def cmd_manifest(args: argparse.Namespace) -> int:
    from compass import manifest, state
    from compass.repo import find_repo

    repo = find_repo()
    if not repo.initialized:
        return _fail(NOT_INITIALIZED)
    current = state.read(repo)
    task = args.task or state.active_task(current)
    if not task:
        return _fail("no active task; pass a task id")
    archived = task in current["accepted"] and manifest.load(repo, task, archived=True)
    if archived:
        built = archived
    else:
        built = manifest.build(repo, task, state.touched(current, task), _config(repo).review.anchor_exempt)
    if args.json:
        print(json.dumps(built.to_json(), indent=1, ensure_ascii=False))
        return EXIT_OK
    if args.hosted:
        linker = manifest.hosted_linker(repo.root, args.ref)
        if linker is None:
            return _fail("no GitHub, Azure DevOps or GitLab remote found (git remote get-url origin)")
        print(manifest.render(built, linker[0]))
        return EXIT_OK
    path = manifest.write(repo, built, archived=bool(archived))
    print(f"{path.relative_to(repo.root).as_posix()}: {built.summary()}")
    return EXIT_OK


def cmd_accept(args: argparse.Namespace) -> int:
    from compass import review
    from compass.repo import find_repo

    repo = find_repo()
    if not repo.initialized:
        return _fail(NOT_INITIALIZED)
    try:
        done = review.accept(repo, _config(repo), args.task)
    except review.NothingToAccept as exc:
        return _fail(str(exc))
    archived = done.archived.relative_to(repo.root).as_posix()
    print(
        f"Accepted {done.task}: removed {done.removed} anchor{'s' if done.removed != 1 else ''}"
        f" from {len(done.files)} file{'s' if len(done.files) != 1 else ''}; manifest archived at {archived}."
    )
    for anchor in done.leftover:
        print(f"  not removed: {anchor.path}:{anchor.line} ({anchor.kind} {anchor.task})")
    return EXIT_ERROR if done.leftover else EXIT_OK


def cmd_check_anchors(args: argparse.Namespace) -> int:
    from compass.anchors import scan_repo
    from compass.repo import find_repo

    if args.staged:
        return _pre_commit_check()
    repo = find_repo()
    for anchor in scan_repo(repo.root, args.task):
        print(f"{anchor.path}:{anchor.line}  {anchor.kind} {anchor.task}" + (f" — {anchor.note}" if anchor.note else ""))
    return EXIT_OK


def _pre_commit_check() -> int:
    """The git pre-commit hook (RO-05): refuse a commit that adds anchor tags.
    Any internal problem lets the commit through (fail open) and is logged."""
    from compass.anchors import staged_anchors
    from compass.log import log_error
    from compass.repo import find_repo

    repo = None
    try:
        from compass.globs import compile_globs

        repo = find_repo()
        settings = _config(repo, quiet=True).review
        if not settings.enabled:
            return EXIT_OK
        exempt = compile_globs(settings.anchor_exempt)  # tag-shaped text in JSON is data
        found = [a for a in staged_anchors(repo.root) if not exempt(a.path)]
    except Exception as exc:
        log_error(repo.root if repo else None, "check-anchors --staged", exc)
        return EXIT_OK
    if not found:
        return EXIT_OK
    tasks = sorted({a.task for a in found})
    lines = [f"compass: commit refused: the staged changes still add {len(found)} AI anchor tag{'s' if len(found) != 1 else ''}:"]
    lines += [f"  {a.path}:{a.line}  {a.kind} {a.task}" + (f" — {a.note}" if a.note else "") for a in found[:20]]
    if len(found) > 20:
        lines.append(f"  … and {len(found) - 20} more")
    lines.append(
        f"Review them (.compass/changes/{tasks[0]}.md), strip them with /compass:accept in Claude Code or"
        f" `compass accept {tasks[0]}`, stage the result and commit again. To commit anyway: git commit --no-verify."
    )
    print("\n".join(lines), file=sys.stderr)
    return EXIT_ERROR


def _query_output(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="print structured results as JSON")
    p.add_argument("--cursor", help="page the answer as the MCP tool does, starting here (e.g. 0)")


def _run_query(args: argparse.Namespace, run) -> int:
    from compass.query import NotReady, Queries, page
    from compass.repo import find_repo

    repo = find_repo()
    for name in _PATH_ARGS:
        if getattr(args, name, None):
            setattr(args, name, _cli_path(repo, getattr(args, name)))
    queries = Queries(repo, _config(repo))
    try:
        result = run(queries)
    except NotReady as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        print(json.dumps(result.data, indent=1, ensure_ascii=False))
    elif args.cursor is not None:
        print(page(result.lines, args.cursor, queries.settings.max_response_chars))
    else:
        print(result.text)
    return EXIT_OK


# Arguments that name files or directories. On the command line they are
# relative to the current directory, like `compass update`'s; the MCP tools
# take repo-relative paths.
_PATH_ARGS = ("path", "dir", "target")


def _cli_path(repo, arg: str) -> str:
    """``arg`` as a repo-relative path when it names something that exists
    from the current directory; otherwise unchanged (a repo-relative path, a
    module name or a symbol)."""
    if not os.path.exists(arg):
        return arg
    rel = repo.relpath(arg)
    if rel is None:
        return arg
    return rel or "."


COMMANDS = {
    "init": cmd_init,
    "uninstall": cmd_uninstall,
    "index": cmd_index,
    "update": cmd_update,
    "files": cmd_files,
    "stack": cmd_stack,
    "stack-profile": cmd_stack,
    "mcp": cmd_mcp,
    "task": cmd_task,
    "approve": cmd_approve,
    "check-prompt": cmd_check_prompt,
    "report": cmd_report,
    "enrich": cmd_enrich,
    "summarize-file": cmd_summarize_file,
    "classify-files": cmd_classify_files,
    "manifest": cmd_manifest,
    "accept": cmd_accept,
    "check-anchors": cmd_check_anchors,
    "find-symbol": lambda a: _run_query(a, lambda q: q.find_symbol(a.name, a.kind, a.path)),
    "read-symbol": lambda a: _run_query(a, lambda q: q.read_symbol(a.name, a.path, a.context)),
    "file-outline": lambda a: _run_query(a, lambda q: q.file_outline(a.path)),
    "map": lambda a: _run_query(a, lambda q: q.map(a.dir)),
    "tests-for": lambda a: _run_query(a, lambda q: q.tests_for(a.target)),
    "importers-of": lambda a: _run_query(a, lambda q: q.importers_of(a.target)),
    "callers-of": lambda a: _run_query(a, lambda q: q.callers_of(a.name)),
}


# -- helpers ----------------------------------------------------------------


def _config(repo, quiet: bool = False):
    from compass.config import load_config

    config = load_config(repo.root)
    for warning in [] if quiet else config.warnings:
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
