"""The MCP server over real stdio, as Claude Code talks to it (QT-01, QT-03, QT-05)."""

from __future__ import annotations

import os
import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from compass.index.indexer import Indexer
from compass.repo import Repo
from conftest import copy_fixture, write
from fake_llm import FakeLLM

TOOLS = {
    "find_symbol", "read_symbol", "file_outline", "map", "stack_profile", "tests_for", "importers_of", "callers_of",
}


def session_run(cwd, body, args=("mcp",), env=None):
    """Start `compass mcp` in ``cwd`` and run ``body(session)`` against it."""

    async def main():
        params = StdioServerParameters(command=sys.executable, args=["-m", "compass", *args], cwd=str(cwd), env=env)
        async with stdio_client(params) as (read, write_stream):
            async with ClientSession(read, write_stream) as session:
                init = await session.initialize()
                return await body(session, init)

    return anyio.run(main)


async def call(session, tool, /, **arguments):
    result = await session.call_tool(tool, arguments)
    return result.is_error, "\n".join(block.text for block in result.content)


@pytest.fixture(scope="module")
def go_repo(tmp_path_factory):
    repo = Repo(copy_fixture("go_app", tmp_path_factory.mktemp("mcp") / "go"))
    Indexer(repo).build()
    return repo


def test_tools_and_instructions(go_repo):
    async def body(session, init):
        tools = (await session.list_tools()).tools
        return init, {t.name: t for t in tools}

    init, tools = session_run(go_repo.root, body)
    assert set(tools) == TOOLS  # QT-01 plus the QT-03 pair
    assert "before reaching for Read, Grep or Glob" in init.instructions
    assert all(t.annotations.read_only_hint and not t.annotations.open_world_hint for t in tools.values())
    assert "instead of Grep or Glob" in tools["find_symbol"].description
    assert "instead of Read" in tools["read_symbol"].description
    assert "cursor" in tools["find_symbol"].input_schema["properties"]


def test_every_tool_answers(go_repo):
    async def body(session, _init):
        return {
            "find": await call(session, "find_symbol", name="retry"),
            "read": await call(session, "read_symbol", name="Exponential.Next", context=0),
            "outline": await call(session, "file_outline", path="internal/transport/retry.go"),
            "map": await call(session, "map"),
            "map_dir": await call(session, "map", dir="internal/transport"),
            "stack": await call(session, "stack_profile"),
            "tests": await call(session, "tests_for", target="internal/transport/retry.go"),
            "importers": await call(session, "importers_of", target="internal/transport"),
            "callers": await call(session, "callers_of", name="Retry"),
        }

    answers = session_run(go_repo.root, body)
    assert all(not is_error for is_error, _text in answers.values())
    assert answers["find"][1].startswith('2 symbols matching "retry":')
    assert answers["read"][1].splitlines()[2] == "32\tfunc (e *Exponential) Next(n int) time.Duration {"
    assert "method Exponential.Next(n int) time.Duration" in answers["outline"][1]
    assert answers["map"][1].startswith("# Code map")
    assert answers["stack"][1].startswith("Languages: go")
    assert "retry_test.go  (name, package)" in answers["tests"][1]
    assert "cmd/sensord/main.go" in answers["importers"][1]
    assert answers["callers"][1].startswith("2 call sites of Retry:")


def test_bad_arguments_do_not_stop_the_server(go_repo):
    async def body(session, _init):
        bad = await session.call_tool("find_symbol", {})
        good = await call(session, "find_symbol", name="Retry")
        return bad, good

    bad, good = session_run(go_repo.root, body)
    assert bad.is_error
    assert good == (False, good[1]) and "Retry" in good[1]


def test_long_answers_page_with_a_cursor(tmp_path):
    repo = Repo(copy_fixture("python_app", tmp_path / "py"))
    write(repo.root, ".compass/config.yaml", "query:\n  max_response_chars: 300\n")
    Indexer(repo).build()

    async def body(session, _init):
        first = await call(session, "map", dir="src/inventory")
        cursor = first[1].rsplit('cursor="', 1)[1].split('"')[0]
        second = await call(session, "map", dir="src/inventory", cursor=cursor)
        return first[1], second[1]

    first, second = session_run(repo.root, body)
    assert len(first) <= 300 and first.splitlines()[-1].startswith("[compass]")
    assert first.splitlines()[0].startswith("# src/inventory/")
    assert second.splitlines()[0] != first.splitlines()[0]


def test_cursors_may_be_numbers(tmp_path):
    repo = Repo(copy_fixture("python_app", tmp_path / "py"))
    write(repo.root, ".compass/config.yaml", "query:\n  max_response_chars: 300\n")
    Indexer(repo).build()

    async def body(session, _init):
        as_text = await call(session, "map", dir="src/inventory", cursor="3")
        as_number = await call(session, "map", dir="src/inventory", cursor=3)
        bogus = await call(session, "map", dir="src/inventory", cursor="²")
        return as_text, as_number, bogus

    as_text, as_number, bogus = session_run(repo.root, body)
    assert as_number == as_text and not as_text[0]
    assert bogus == (False, "[compass] '²' is not a cursor; pass the cursor=\"N\" an earlier answer ended with.")


def test_dash_c_names_the_repo_to_serve(tmp_path):
    served = Repo(copy_fixture("go_app", tmp_path / "go"))
    other = Repo(copy_fixture("python_app", tmp_path / "py"))
    for repo in (served, other):
        Indexer(repo).build()

    async def body(session, _init):
        return await call(session, "stack_profile")

    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(other.root)}
    _is_error, text = session_run(tmp_path, body, args=("-C", str(served.root), "mcp"), env=env)
    assert text.startswith("Languages: go")


def test_outside_a_repo_the_tools_explain(tmp_path):
    async def body(session, _init):
        return await call(session, "find_symbol", name="x")

    is_error, text = session_run(tmp_path, body)
    assert not is_error and "needs a git repository" in text

    plain = copy_fixture("go_app", tmp_path / "plain")  # a git repo, never initialised
    is_error, text = session_run(plain, body)
    assert not is_error and "compass init" in text


def test_the_local_model_tools_are_offered_only_while_a_model_answers(tmp_path):
    repo = Repo(copy_fixture("go_app", tmp_path / "go"))
    Indexer(repo).build()

    def reply(body):
        return "code" if "sort files" in body["messages"][0]["content"] else "Retries with backoff (L12)."

    async def body(session, _init):
        tools = {t.name: t for t in (await session.list_tools()).tools}
        if "summarize_file" not in tools:
            return set(tools), None, None
        summary = await call(session, "summarize_file", path="internal/transport/retry.go")
        labels = await call(session, "classify_files", paths=["internal/transport/retry.go"], labels=["code", "test"])
        assert all(t.annotations.read_only_hint for t in tools.values())
        return set(tools), summary, labels

    fake = FakeLLM(reply=reply).start()
    try:
        write(repo.root, ".compass/config.yaml", fake.config())
        tools, summary, labels = session_run(repo.root, body)
    finally:
        fake.stop()
    assert tools == TOOLS | {"summarize_file", "classify_files"}  # DL-04
    assert summary == (False, "[local model fake] internal/transport/retry.go:\nRetries with backoff (L12).")
    assert labels == (False, "[local model fake] 1 file:\ninternal/transport/retry.go: code")
    assert session_run(repo.root, body)[0] == TOOLS  # the model is gone: so are its tools (DL-06)
