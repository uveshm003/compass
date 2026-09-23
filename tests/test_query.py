"""The query tools (QT-01 to QT-05) over the fixture repos."""

from __future__ import annotations

import json
import os
import time

import pytest

from compass.index.indexer import Indexer
from compass.query import NotReady, Queries, page, split_qualified
from compass.repo import Repo
from conftest import bump_mtime, copy_fixture, run_compass, write


@pytest.fixture
def q(indexed_fixtures):
    return lambda name: Queries(indexed_fixtures[name])


# -- find_symbol ---------------------------------------------------------------


def test_find_symbol_ranks_names_before_docs_and_sources_before_tests(q):
    ts = q("ts_app").find_symbol("retry")
    assert ts.lines[1].startswith("src/transport/reconnect.ts:24-32  fn withRetry<T>(")
    assert "class ReconnectPolicy — Retry strategy" in ts.lines[2]  # found through its doc
    go = q("go_app").find_symbol("retry")
    assert [d["name"] for d in go.data] == ["Retry", "TestRetry"]
    assert go.lines[2].endswith("[test]")


def test_find_symbol_exact_name_ranks_first(q):
    result = q("python_app").find_symbol("Reading")
    assert result.data[0]["name"] == "Reading" and result.data[0]["kind"] == "class"


def test_find_symbol_filters(q):
    methods = q("python_app").find_symbol("a", kind="method", path="src/inventory/models.py")
    assert methods.data and all(d["kind"] == "method" and d["path"] == "src/inventory/models.py" for d in methods.data)
    fns = q("rust_app").find_symbol("new", kind="fn")
    assert {d["kind"] for d in fns.data} == {"method"} or all(d["kind"] == "function" for d in fns.data)


def test_find_symbol_qualified_names(q):
    result = q("ts_app").find_symbol("ReconnectPolicy.next")
    assert [(d["parent"], d["name"]) for d in result.data] == [("ReconnectPolicy", "next")]
    assert "method ReconnectPolicy.next(attempt: number): number" in result.lines[1]
    module_qualified = q("python_app").find_symbol("models.StockItem")  # a module, not a class
    assert module_qualified.data[0]["name"] == "StockItem"


def test_find_symbol_without_matches(q):
    result = q("go_app").find_symbol("zzz_nothing")
    assert result.data == [] and "No symbol named like" in result.lines[0]


def test_compact_import_lists():
    from compass.query import _compact

    assert _compact(["compass.query.NotReady", "compass.query.page"], ".") == "compass.query.{NotReady, page}"
    assert _compact([".models.Reading", ".models.StockItem"], ".") == ".models.{Reading, StockItem}"
    assert _compact(["crate::a::b", "crate::a::c::d"], "::") == "crate::a::{b, c::d}"
    assert _compact(["os", "os.path"], ".") == "os, os.path"  # os itself has nothing after the prefix
    assert _compact([".a", ".b"], ".") == ".a, .b"  # a bare `.` says nothing
    assert _compact(["typing.Any"], ".") == "typing.Any"


def test_split_qualified():
    assert split_qualified("Point::new") == ("new", "Point")
    assert split_qualified(" withRetry() ") == ("withRetry", None)
    assert split_qualified("a.b.c") == ("c", "a.b")


# -- read_symbol ---------------------------------------------------------------


def test_read_symbol_returns_the_range_with_its_doc(q):
    result = q("ts_app").read_symbol("withRetry", context=0)
    assert result.lines[0] == "src/transport/reconnect.ts:20-32  fn withRetry"
    assert result.lines[1] == "20\t/**"  # the whole doc comment, not just the context lines
    assert result.lines[-1] == "32\t}"
    assert len(result.lines) == 1 + 13


def test_read_symbol_context_lines(q):
    tight = q("go_app").read_symbol("Retry", context=0).data["blocks"][0]
    loose = q("go_app").read_symbol("Retry", context=2).data["blocks"][0]
    assert (tight["start"], tight["end"]) == (42, 51)  # the doc comment on 42, the function 43-51
    assert (loose["start"], loose["end"]) == (41, 53)  # two lines either side of the function


def test_read_symbol_ambiguous_names_list_candidates(q):
    result = q("ts_app").read_symbol("constructor")
    assert result.lines[0].startswith('"constructor" is defined in 2 files')
    assert {c["path"] for c in result.data["candidates"]} == {"src/transport/reconnect.ts", "src/legacy/util.js"}
    picked = q("ts_app").read_symbol("constructor", path="util.js")
    assert picked.data["path"] == "src/legacy/util.js"


def test_read_symbol_suggests_close_names(q):
    result = q("ts_app").read_symbol("withRetri")
    assert result.lines[0] == '[compass] No symbol named "withRetri".'
    assert any("withRetry" in line for line in result.lines)


def test_read_symbol_follows_edits_on_disk(tmp_path):
    repo = Repo(copy_fixture("go_app", tmp_path / "go"))
    Indexer(repo).build()
    path = repo.root / "internal/transport/retry.go"
    path.write_text(path.read_text().replace("package transport\n", "package transport\n\n// moved\n// down\n", 1))
    result = Queries(repo).read_symbol("Retry", context=0)
    assert result.lines[0] == "internal/transport/retry.go:45-54  fn Retry"  # was 42-51 before the edit
    assert result.lines[-1] == "54\t}"


# -- file_outline, map, stack_profile -------------------------------------------


def test_file_outline(q):
    result = q("ts_app").file_outline("src/transport/reconnect.ts")
    assert result.lines[0] == "src/transport/reconnect.ts  (typescript, 5 symbols)"
    assert "- L10    method next(attempt: number): number — Delay in ms, exponential with jitter" in result.lines
    assert result.lines[-2:] == ["imports:", "- src/transport/socket.ts  (./socket)"]


def test_file_outline_of_an_unknown_file(q):
    result = q("ts_app").file_outline("src/socket.ts")
    assert "not in the code map" in result.lines[0] and "src/transport/socket.ts" in result.lines[0]


def test_map(q):
    tree = q("ts_app").map()
    assert tree.lines[0].startswith("# Code map")
    one = q("ts_app").map("src/transport/")
    assert one.lines[0].startswith("# src/transport/  (4 files, 12 symbols) — Transport layer")
    parent = q("ts_app").map("src")
    assert "Subdirectories:" in parent.lines and any(line.startswith("- src/transport/") for line in parent.lines)
    missing = q("ts_app").map("transport")
    assert "Did you mean: src/transport/?" in missing.lines[0]


def test_stack_profile(q):
    result = q("go_app").stack_profile()
    assert result.lines[0] == "Languages: go (5)"
    assert "github_actions" in result.data["stacks"]


# -- relationships ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "source", "expected"),
    [
        ("python_app", "src/inventory/models.py", "tests/test_models.py  (name, imports) — test_alarm, test_restock"),
        ("ts_app", "src/transport/reconnect.ts", "src/transport/reconnect.test.ts  (name, imports)"),
        ("go_app", "internal/transport/retry.go", "internal/transport/retry_test.go  (name, package) — TestRetry"),
        ("rust_app", "src/transport/retry.rs", "src/transport/retry.rs  (inline tests) — delay_grows"),
    ],
)
def test_tests_for_files(q, fixture, source, expected):
    result = q(fixture).tests_for(source)
    assert result.lines == [f"Tests for {source}:", expected]


def test_tests_for_a_symbol_and_a_bare_file_name(q):
    result = q("python_app").tests_for("StockItem.restock")
    assert result.lines[:2] == ["Tests that call restock:", "tests/test_models.py:10  in test_restock"]
    by_name = q("python_app").tests_for("models.py")
    assert by_name.lines[0] == "Tests for src/inventory/models.py:"
    none = q("ts_app").tests_for("src/types.ts")
    assert none.lines[0].startswith("[compass] No tests found for src/types.ts")


def test_importers_of(q):
    python = q("python_app").importers_of("src/inventory/models.py")
    assert python.lines == [
        "3 files import src/inventory/models.py:",
        "src/inventory/__init__.py  (inventory.models.{Reading, StockItem})",
        "src/inventory/api.py  (.models.{Reading, StockItem})",
        "tests/test_models.py  (inventory.models.{Reading, StockItem})",
    ]
    go = q("go_app").importers_of("internal/transport/retry.go")  # Go imports name the package
    assert go.data == [{"path": "cmd/sensord/main.go", "targets": ["github.com/example/sensord/internal/transport"]}]
    external = q("ts_app").importers_of("react")
    assert external.data == [{"path": "src/components/Button.tsx", "targets": ["react"]}]


def test_importers_of_a_directory_leaves_out_its_own_files(q):
    python = q("python_app").importers_of("src/inventory")
    assert python.lines == [
        "1 file imports src/inventory/; imports from 2 files inside it are left out:",
        "tests/test_models.py  (uses models.py)",
    ]
    ts = q("ts_app").importers_of("src/transport/")
    assert ts.data == [{"path": "src/index.ts", "targets": ["./transport"], "uses": ["index.ts"]}]
    go = q("go_app").importers_of("internal")
    assert go.lines[1] == "cmd/sensord/main.go  (uses transport/)"
    assert q("rust_app").importers_of("src/transport/mod.rs").lines == ["[compass] Nothing imports src/transport/mod.rs."]


def test_importers_of_a_module_matches_its_submodules_only(make_repo):
    root = make_repo(files={
        "a.py": "import requests\n", "b.py": "import requests.adapters\n", "c.py": "from requests.auth import HTTPBasicAuth\n",
        "d.py": "import requests_toolbelt\n", "e.ts": 'import x from "requests/y";\n',
    })
    repo = Repo(root)
    Indexer(repo).build()
    result = Queries(repo).importers_of("requests")
    assert [d["path"] for d in result.data] == ["a.py", "b.py", "c.py", "e.ts"]


def test_callers_of(q):
    python = q("python_app").callers_of("is_alarm")
    assert python.lines == [
        "2 call sites of is_alarm:",
        'src/inventory/api.py:20  in post_reading — return {"alarm": reading.is_alarm()}',
        'tests/test_models.py:5  in test_alarm — assert Reading("s1", 50.0).is_alarm()  [test]',
    ]
    rust = q("rust_app").callers_of("next_delay")  # the calls sit inside assert!(...)
    assert rust.data[0]["caller"] == "tests.delay_grows"
    qualified = q("ts_app").callers_of("ReconnectPolicy.next")
    assert "matched by name 'next'" in qualified.lines[0]


# -- paging, readiness, CLI twins -------------------------------------------------


def test_pages_cover_every_line_once():
    lines = [f"line {i} " + "x" * (i % 40) for i in range(200)]
    seen, cursor = [], None
    while True:
        text = page(lines, cursor, 500)
        chunk = text.split("\n")
        if chunk[-1].startswith("[compass]") and "cursor=" in chunk[-1]:
            cursor = chunk[-1].split('cursor="')[1].rstrip('".')
            seen += chunk[:-1]
            assert len(text) <= 500 + 80
        else:
            seen += chunk
            break
    assert seen == lines
    assert page(lines, "999", 500) == "[compass] No more results."


def test_not_ready_answers(make_repo):
    plain = make_repo("python_app")
    with pytest.raises(NotReady, match="compass init"):
        Queries(Repo(plain)).find_symbol("x")
    repo = Repo(make_repo("python_app"))
    repo.ensure_state_dir()  # initialised, but the index is not built yet
    with pytest.raises(NotReady, match="being built"):
        Queries(repo).find_symbol("x")
    deadline = time.monotonic() + 30
    while not repo.db_path.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert repo.db_path.exists()  # the background build it started


def test_cli_twins(indexed_fixtures):
    root = str(indexed_fixtures["go_app"].root)
    found = json.loads(run_compass("-C", root, "find-symbol", "Retry", "--json").stdout)
    assert found[0] == {
        "name": "Retry", "kind": "function", "parent": None, "signature": "Retry(op func() error, b Backoff) error",
        "path": "internal/transport/retry.go", "start_line": 43, "end_line": 51, "visibility": "public",
        "doc": "Retry calls op until it succeeds or attempts run out", "is_test": False,
    }
    text = run_compass("-C", root, "callers-of", "Retry").stdout
    assert text.startswith("2 call sites of Retry:")
    paged = run_compass("-C", root, "map", "internal/transport", "--cursor", "0").stdout
    assert paged == Queries(indexed_fixtures["go_app"]).map("internal/transport").text + "\n"
    for command in (["tests-for", "retry.go"], ["importers-of", "internal/transport"], ["file-outline", "go.mod"],
                    ["read-symbol", "Exponential.Next"], ["stack-profile"]):
        proc = run_compass("-C", root, *command)
        assert proc.returncode == 0 and proc.stdout.strip(), command


def test_cli_twin_outside_an_initialised_repo(make_repo):
    proc = run_compass("-C", str(make_repo("go_app")), "find-symbol", "Retry")
    assert proc.returncode == 1 and "compass init" in proc.stderr


def test_the_index_refreshes_itself_between_queries(tmp_path, monkeypatch):
    repo = Repo(copy_fixture("python_app", tmp_path / "py"))
    Indexer(repo).build()
    queries = Queries(repo)
    assert queries.find_symbol("brand_new_function").data == []
    write(repo.root, "src/inventory/extra.py", "def brand_new_function():\n    pass\n")
    monkeypatch.setattr("compass.query.REFRESH_S", 0.0)
    assert queries.find_symbol("brand_new_function").data[0]["path"] == "src/inventory/extra.py"
    os.remove(repo.root / "src/inventory/extra.py")
    assert queries.find_symbol("brand_new_function").data == []


# -- regressions from the M2 review ------------------------------------------------


@pytest.fixture
def no_spawn(monkeypatch):
    """Record background builds instead of starting them."""
    spawned = []
    monkeypatch.setattr("compass.background.spawn", lambda args, cwd: spawned.append(args) or True)
    return spawned


def _repo(make_repo, files):
    repo = Repo(make_repo(files=files))
    Indexer(repo).build()
    return repo


@pytest.mark.parametrize("now", ["def other():\n    return 2\n", "".join(f"y{i} = {i}\n" for i in range(60))])
def test_read_symbol_after_the_symbol_was_deleted(make_repo, now):
    # The index still places `target` at line 41 when the question arrives.
    before = "".join(f"x{i} = {i}\n" for i in range(1, 40)) + "\ndef target():\n    return 1\n\ndef other():\n    return 2\n"
    repo = _repo(make_repo, {"a.py": before})
    queries = Queries(repo)
    assert queries.read_symbol("target", context=0).lines[1] == "41\tdef target():"
    write(repo.root, "a.py", now)  # shorter than line 41, or still longer
    bump_mtime(repo.root / "a.py")
    result = queries.read_symbol("target", context=0)
    assert result.lines[0] == '[compass] "target" is no longer defined in a.py; the file changed since it was indexed.'
    assert queries.read_symbol("target").lines[0] == '[compass] No symbol named "target".'  # the index caught up


def test_read_symbol_and_file_outline_while_another_process_holds_the_lock(make_repo, monkeypatch, no_spawn):
    from compass.lock import file_lock

    repo = _repo(make_repo, {"a.py": "def alpha():\n    return 1\n"})
    monkeypatch.setattr("compass.query.LOCK_WAIT_S", 0.05)
    with file_lock(repo.lock_path, 1.0):  # a background build, say
        write(repo.root, "a.py", "# moved\n# down\n\ndef alpha():\n    return 1\n")
        bump_mtime(repo.root / "a.py")
        queries = Queries(repo)
        assert queries.read_symbol("alpha", context=0).lines[:2] == ["a.py:4-5  fn alpha", "4\tdef alpha():"]
        assert "- L4  fn alpha()" in queries.file_outline("a.py").lines


def test_parallel_read_symbol_calls_after_an_edit(make_repo):
    import threading

    base = "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"
    repo = _repo(make_repo, {"a.py": base})
    queries = Queries(repo)  # one engine, many threads: how the MCP server runs tools
    wrong = []
    for trial in range(10):
        write(repo.root, "a.py", "# pad\n\n" * (12 if trial % 2 else 2) + base)
        bump_mtime(repo.root / "a.py")
        barrier = threading.Barrier(2)

        def run(name, barrier=barrier, trial=trial):
            barrier.wait()
            try:
                lines = queries.read_symbol(name, context=0).lines
                if f"def {name}():" not in lines[1]:
                    wrong.append((trial, name, lines))
            except Exception as exc:  # noqa: BLE001 - any error is a failure here
                wrong.append((trial, name, repr(exc)))

        threads = [threading.Thread(target=run, args=(n,)) for n in ("alpha", "beta")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert wrong == []


def test_queries_wait_for_the_first_build_to_commit(make_repo, no_spawn):
    from compass.index.store import Store

    repo = Repo(make_repo("python_app"))
    repo.ensure_state_dir()
    Store.open(repo.db_path, create=True).close()  # a first build has written the schema, no rows yet
    with pytest.raises(NotReady, match="being built"):
        Queries(repo).find_symbol("Reading")
    assert no_spawn  # and one is started in case the builder died


def test_read_symbol_prefers_the_path_as_given(make_repo):
    repo = _repo(make_repo, {
        "src/index.ts": "export function main() { return 1 }\n",
        "packages/app/src/index.ts": "export function main() { return 2 }\n",
    })
    queries = Queries(repo)
    for path in ("src/index.ts", "./src/index.ts", str(repo.root / "src/index.ts"), "src"):
        assert queries.read_symbol("main", path=path).data["path"] == "src/index.ts", path
    assert queries.read_symbol("main", path="app/src/index.ts").data["path"] == "packages/app/src/index.ts"


def test_the_repo_root_as_a_scope_means_everywhere(q, indexed_fixtures):
    root = str(indexed_fixtures["python_app"].root)
    for scope in (".", "./", root, ""):
        assert q("python_app").find_symbol("Reading", path=scope).data, scope
        assert q("python_app").read_symbol("restock", path=scope).data["path"] == "src/inventory/models.py", scope


def test_line_numbers_ignore_form_feeds_and_unicode_line_separators(make_repo):
    python = "import os\n\n\x0c\ndef first():\n    return helper()\n\n\x0c\ndef helper():\n    return 1\n"
    js = 'const s = "a b";\nexport function go() {\n  return run();\n}\nfunction run() { return 1; }\n'
    repo = _repo(make_repo, {"a.py": python, "b.js": js})
    queries = Queries(repo)
    assert queries.read_symbol("helper", context=0).lines[1:] == ["8\tdef helper():", "9\t    return 1"]
    assert queries.callers_of("helper").lines[1] == "a.py:5  in first — return helper()"
    assert queries.read_symbol("run", context=0).lines[1] == "5\tfunction run() { return 1; }"
    assert queries.callers_of("run").lines[1] == "b.js:3  in go — return run();"


def test_every_tool_notices_files_changed_outside_claude_code(make_repo, monkeypatch):
    repo = Repo(make_repo("python_app"))
    Indexer(repo).build()
    queries = Queries(repo)
    queries.find_symbol("x")  # uses up the rate-limited refresh
    monkeypatch.setattr("compass.query.REFRESH_S", 0.0)
    write(repo.root, "src/inventory/extra.py", "from .models import Reading\n\ndef brand_new():\n    return Reading\n")
    assert queries.read_symbol("brand_new").data["path"] == "src/inventory/extra.py"
    assert "src/inventory/extra.py  (.models.Reading)" in queries.importers_of("src/inventory/models.py").lines


def test_a_config_edit_does_not_leave_the_engine_stuck(make_repo):
    from compass.index.store import Store

    repo = Repo(make_repo("python_app"))
    Indexer(repo).build()
    queries = Queries(repo)  # long-lived, like the MCP server's
    queries.find_symbol("x")
    write(repo.root, ".compass/config.yaml", "index:\n  max_file_kb: 2048\n")
    Indexer(repo).build()  # rebuilt from the CLI with the new settings
    models = repo.root / "src/inventory/models.py"
    models.write_text("# x\n" * 5 + models.read_text(), encoding="utf-8")
    bump_mtime(models)
    queries.file_outline("src/inventory/models.py")
    with Store.open(repo.db_path) as store:  # the per-file refresh ran with the new fingerprint
        assert store.file_info("src/inventory/models.py")["mtime_ns"] == models.stat().st_mtime_ns


def test_python_member_imports_count_for_importers_and_tests(make_repo):
    repo = _repo(make_repo, {
        "src/pkg/__init__.py": "from .helpers import VERSION\n",
        "src/pkg/helpers.py": "VERSION = 1\n",
        "src/pkg/models.py": "class Model:\n    pass\n",
        "src/pkg/views.py": "from . import models\n\ndef view():\n    return models.Model()\n",
        "tests/test_things.py": "from pkg import models\n\ndef test_model():\n    assert models.Model()\n",
        "scripts/os.py": "def helper():\n    pass\n",
        "src/pkg/other.py": "import os.path\n",
    })
    queries = Queries(repo)
    assert [d["path"] for d in queries.importers_of("src/pkg/models.py").data] == ["src/pkg/views.py", "tests/test_things.py"]
    assert queries.tests_for("src/pkg/models.py").lines[1] == "tests/test_things.py  (imports) — test_model"
    assert queries.importers_of("scripts/os.py").lines == ["[compass] Nothing imports scripts/os.py."]


def test_typescript_path_aliases_resolve(make_repo):
    repo = _repo(make_repo, {
        "web/tsconfig.json": '{\n  // Next.js style\n  "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./*"]},},\n}\n',
        "web/lib/utils.ts": "export function cn() { return 1 }\n",
        "web/app/page.ts": "import { cn } from '@/lib/utils'\nexport function Page() { return cn() }\n",
    })
    queries = Queries(repo)
    assert queries.importers_of("web/lib/utils.ts").data == [{"path": "web/app/page.ts", "targets": ["@/lib/utils"]}]
    write(repo.root, "web/tsconfig.json", '{"compilerOptions": {"paths": {"@/*": ["./src/*"]}}}\n')
    bump_mtime(repo.root / "web/tsconfig.json")
    Indexer(repo).update(["web/tsconfig.json"])  # an alias file edit re-resolves every import
    assert queries.importers_of("web/lib/utils.ts").data == []


def test_tests_for_a_symbol_finds_test_calls_among_many_others(make_repo):
    body = "from core import compute\n\n" + "".join(f"def use{i}():\n    return compute()\n\n" for i in range(120))
    files = {f"src/users/u{k}.py": body for k in range(5)}
    files["src/core.py"] = "def compute():\n    return 1\n"
    files["tests/test_core.py"] = "from core import compute\n\ndef test_compute():\n    assert compute() == 1\n"
    repo = _repo(make_repo, files)
    result = Queries(repo).tests_for("compute")
    assert result.lines[:2] == ["Tests that call compute:", "tests/test_core.py:4  in test_compute"]


def test_file_outline_of_a_directory_points_to_map(make_repo, monkeypatch):
    repo = Repo(make_repo("python_app"))
    Indexer(repo).build()
    calls = []
    monkeypatch.setattr(Indexer, "update", lambda self, paths, **kw: calls.append(paths))
    result = Queries(repo).file_outline("src/inventory")
    assert result.lines == ['[compass] src/inventory/ is a directory; map("src/inventory") lists its files and symbols.']
    assert calls == []  # and nothing below it was re-hashed


def test_tests_for_ambiguous_names_directories_and_nearest_sources(q, make_repo):
    ambiguous = q("ts_app").tests_for("index.ts")
    assert ambiguous.lines == [
        "[compass] index.ts matches several files; pass the path of one:", "src/index.ts", "src/transport/index.ts",
    ]
    directory = q("ts_app").tests_for("src/transport")
    assert directory.lines[:2] == [
        "Tests for src/transport/ (3 source files):", "src/transport/reconnect.test.ts  (name, imports; for reconnect.ts)",
    ]
    repo = _repo(make_repo, {
        "a/utils.ts": "export function a() { return 1 }\n",
        "b/utils.ts": "export function b() { return 2 }\n",
        "b/utils.test.ts": "import { b } from './utils'\ntest('b', () => b())\n",
    })
    queries = Queries(repo)
    assert queries.tests_for("a/utils.ts").lines[0].startswith("[compass] No tests found for a/utils.ts")
    assert queries.tests_for("b/utils.ts").lines[1] == "b/utils.test.ts  (name, imports)"


def test_file_outline_lists_one_import_per_line(make_repo):
    source = "".join(f"import package_number_{i}.submodule\n" for i in range(200)) + "\ndef f():\n    pass\n"
    repo = _repo(make_repo, {"big.py": source})
    result = Queries(repo).file_outline("big.py")
    assert result.lines[2] == "imports:" and len(result.lines) == 3 + 200
    first = page(result.lines, None, 4000)
    assert len(first) <= 4000 and first.endswith('cursor="' + str(len(first.split("\n")) - 1) + '".')


def test_pages_stay_within_the_cap_and_reject_bad_cursors():
    lines = ["x" * 99] * 100
    for cap in (300, 1000, 4000):
        text = page(lines, None, cap)
        assert len(text) <= cap and text.endswith('".')
    assert page(["a" * 10_000], None, 500).endswith("…")
    assert page(lines, 3, 4000).startswith("x" * 99)  # a number works as well as "3"
    assert page(lines, "²", 4000).startswith("[compass] '²' is not a cursor")
    assert page(lines, "-1", 4000).startswith("[compass] '-1' is not a cursor")


def test_later_pages_skip_the_freshness_checks(make_repo, monkeypatch):
    repo = Repo(make_repo("python_app"))
    Indexer(repo).build()
    queries = Queries(repo)
    monkeypatch.setattr("compass.query.REFRESH_S", 0.0)
    ran = []
    monkeypatch.setattr("compass.hooks.refresh_or_hand_off", lambda repo, wait: ran.append(1) or False)
    with queries.continuing():
        queries.find_symbol("Reading")
    assert ran == []
    queries.find_symbol("Reading")
    assert ran == [1]


def test_cli_paths_are_relative_to_the_current_directory(indexed_fixtures):
    root = indexed_fixtures["python_app"].root
    inside = run_compass("file-outline", "models.py", cwd=root / "src/inventory")
    assert inside.returncode == 0 and inside.stdout.startswith("src/inventory/models.py  (python")
    from_root = run_compass("file-outline", "src/inventory/models.py", cwd=root / "src/inventory")
    assert from_root.stdout == inside.stdout  # a repo-relative path still works from anywhere


def test_editing_an_extended_tsconfig_re_resolves_imports(make_repo):
    repo = _repo(make_repo, {
        "tsconfig.json": '{"extends": "./tsconfig.base.json"}\n',
        "tsconfig.base.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}\n',
        "src/lib/log.ts": "export function log() {}\n",
        "src/app.ts": "import { log } from '@/lib/log'\n",
    })
    queries = Queries(repo)
    assert [d["path"] for d in queries.importers_of("src/lib/log.ts").data] == ["src/app.ts"]
    write(repo.root, "tsconfig.base.json", '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["lib/*"]}}}\n')
    bump_mtime(repo.root / "tsconfig.base.json")
    Indexer(repo).update(["tsconfig.base.json"])
    assert queries.importers_of("src/lib/log.ts").data == []
