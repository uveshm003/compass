"""``compass mcp``: the query tools as a stdio MCP server (QT-01, QT-03; ADR 008).

The tools are thin wrappers over compass.query.Queries. Their descriptions say
when to prefer them over Read, Grep and Glob, and the server instructions add
the one rule from Step 4: look code up through Compass, read whole files only
to edit them. A bad request never takes the server down; problems come back
as a one-line answer and internal errors go to .compass/logs/.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from compass import __version__
from compass.log import log_error
from compass.query import NotReady, Queries, Result, page, parse_cursor
from compass.repo import NotAGitRepo, Repo, find_repo

INSTRUCTIONS = """\
Compass has indexed this repository: every class, function and method with \
its signature and doc, the folder tree, imports, call sites and tests. Answer \
questions about the code with these tools before reaching for Read, Grep or \
Glob: find_symbol to locate code, read_symbol to read one definition, \
file_outline for a file, map for folders, callers_of, importers_of and \
tests_for for relationships, and stack_profile for versions and commands. \
Read whole files only when you are about to edit them. Answers give \
path:line ranges; a long answer ends with a cursor to continue it."""

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

# Models send cursors both as strings and as numbers; accept either.
Cursor = int | str | None


class _Session:
    """Finds the repo once and keeps one Queries for the server's lifetime,
    so its freshness checks are rate-limited across calls."""

    def __init__(self, start: str | None) -> None:
        self.start = start
        self._queries: Queries | None = None

    def queries(self) -> Queries:
        if self._queries is None:
            where = self.start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
            try:
                repo = find_repo(where)
            except NotAGitRepo as exc:
                raise NotReady(f"[compass] {exc}; Compass needs a git repository.") from None
            self._queries = Queries(repo)
        return self._queries

    def repo(self) -> Repo | None:
        return self._queries.repo if self._queries else None


def build_server(start: str | None = None) -> MCPServer:
    session = _Session(start)
    server = MCPServer("compass", instructions=INSTRUCTIONS, version=__version__, log_level="WARNING")

    def answer(run: Callable[[Queries], Result], cursor: Cursor = None) -> str:
        try:
            queries = session.queries()
            if parse_cursor(cursor) is None:
                return page([], cursor, queries.settings.max_response_chars)  # says what a cursor is
            with queries.continuing(bool(parse_cursor(cursor))):
                result = run(queries)
            return page(result.lines, cursor, queries.settings.max_response_chars)
        except NotReady as exc:
            return str(exc)
        except Exception as exc:  # fail open: one bad call must not kill the server
            repo = session.repo()
            log_error(repo.root if repo else None, "mcp", exc)
            return f"[compass] Internal error ({type(exc).__name__}); details are in .compass/logs/errors.log."

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def find_symbol(name: str, kind: str | None = None, path: str | None = None, cursor: Cursor = None) -> str:
        """Find where a class, function, method, interface, type or constant is
        defined, by name. Matching is case-insensitive and partial (`retry` finds
        `withRetry`): exact names rank first, then names containing the text,
        then symbols whose doc mentions it. Accepts `Class.method`. Use this
        instead of Grep or Glob to locate code; each hit gives path:start-end,
        the signature and a one-line doc. Optional kind (class, function, method,
        interface, struct, enum, type, constant, ...) and path (a file or
        directory to search in). cursor continues a long answer."""
        return answer(lambda q: q.find_symbol(name, kind, path), cursor)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def read_symbol(name: str, path: str | None = None, context: int | None = None, cursor: Cursor = None) -> str:
        """Read the source of one symbol: its lines with its doc comment and a
        little context, numbered like Read's output. Use this instead of Read
        when you need a function or class rather than the whole file; read whole
        files only when you are about to edit them. Accepts `Class.method`. If
        the name is defined in several files the answer lists them; pass path=
        to choose. context= sets the extra lines around it (default 3)."""
        return answer(lambda q: q.read_symbol(name, path, context), cursor)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def file_outline(path: str, cursor: Cursor = None) -> str:
        """List what one file defines: classes, functions and methods with line
        numbers, signatures and one-line docs, plus its imports. Use this before
        Read to find the part of a file you need."""
        return answer(lambda q: q.file_outline(path), cursor)

    @server.tool(name="map", annotations=READ_ONLY, structured_output=False)
    def map_(dir: str = "", cursor: Cursor = None) -> str:  # noqa: A002 - the tool's parameter name
        """Browse the code map. With no dir: the folder tree with file and symbol
        counts and each folder's purpose. With a dir: every file in it and the
        symbols each defines, plus its subdirectories. Use this instead of
        listing or globbing directories."""
        return answer(lambda q: q.map(dir), cursor)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def stack_profile(cursor: Cursor = None) -> str:
        """The project's stack, read from manifests and lockfiles: languages,
        frameworks and tools with the versions actually installed, and the
        build, test and lint commands, including what CI runs. Check it before
        choosing APIs, adding dependencies or running tests."""
        return answer(lambda q: q.stack_profile(), cursor)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def tests_for(target: str, cursor: Cursor = None) -> str:
        """Find the tests for a source file or a symbol: test files that match
        its name, import it or share its package, with the test names inside
        them, and for a symbol the test lines that call it."""
        return answer(lambda q: q.tests_for(target), cursor)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def importers_of(target: str, cursor: Cursor = None) -> str:
        """List the files that import a file (for Go, its package), or that
        import an external module such as `react` or `requests`."""
        return answer(lambda q: q.importers_of(target), cursor)

    @server.tool(annotations=READ_ONLY, structured_output=False)
    def callers_of(name: str, cursor: Cursor = None) -> str:
        """List the call sites of a function or method: file:line, the enclosing
        function and the calling line. Matching is by name, so same-named
        methods of other types appear too. Use this to see what depends on code
        before changing it."""
        return answer(lambda q: q.callers_of(name), cursor)

    return server


def serve(start: str | Path | None = None) -> None:
    build_server(str(start) if start else None).run("stdio")
