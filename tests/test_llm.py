"""M5's local model (DL-04 to DL-06): the loopback-only client, the local
query tools and background enrichment, against a fake OpenAI-compatible
server on 127.0.0.1. Every local feature degrades to off when no model answers."""

from __future__ import annotations

import json
import subprocess
import threading
import time

import pytest

from compass import enrich
from compass.config import LocalLLMSettings, load_config
from compass.index.indexer import Indexer
from compass.index.store import Store
from compass.llm import HEALTH_TIMEOUT_S, LocalModel, Unavailable, is_loopback
from compass.lock import file_lock
from compass.repo import Repo
from conftest import bump_mtime, git, posix_only, run_compass, write
from fake_llm import FakeLLM, closed_port_url

SHAPES = '''"""Shapes and their measurements."""


class Circle:
    def __init__(self, r):
        self.r = r

    def area(self):
        return 3.14159 * self.r * self.r


def documented(x):
    """Doubles x."""
    return 2 * x


def perimeter(shape):
    return 2 * 3.14159 * shape.r
'''


def summary_of(body: dict) -> str:
    """The fake model's summary: names what it was shown ("function perimeter in src/shapes.py:")."""
    head = body["messages"][1]["content"].split(" in ", 1)[0]
    return f"Handles {head.split(' ', 1)[1]}."


@pytest.fixture
def fake():
    server = FakeLLM(reply=summary_of).start()
    yield server
    server.stop()


def settings(base_url: str, model: str = "fake", enabled: bool = True) -> LocalLLMSettings:
    return LocalLLMSettings(enabled=enabled, base_url=base_url, model=model, timeout_s=5, enrich_limit=200)


def docs(repo: Repo) -> dict[str, tuple[str | None, str | None]]:
    with Store.open(repo.db_path) as store:
        return {s["name"]: (s["doc"], s["doc_source"]) for s in store.dump()["symbols"]}


@pytest.fixture
def shapes(make_repo, fake):
    root = make_repo(files={"src/shapes.py": SHAPES, ".compass/config.yaml": fake.config()})
    repo = Repo(root)
    Indexer(repo).build()
    return repo


# -- the client -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "loopback"),
    [
        ("http://localhost:11434/v1", True),
        ("http://127.0.0.1:8080/v1", True),
        ("http://127.8.9.10/v1", True),
        ("http://[::1]:11434/v1", True),
        ("http://10.0.0.5:11434/v1", False),
        ("http://0.0.0.0:11434/v1", False),
        ("https://api.example.com/v1", False),
        ("http://localhost.example.com/v1", False),
        ("not a url", False),
    ],
)
def test_only_loopback_endpoints_count(url, loopback):
    assert is_loopback(url) is loopback


def test_code_never_leaves_the_machine(monkeypatch):
    model = LocalModel(settings("https://api.example.com/v1"))
    monkeypatch.setattr(model, "_request", lambda *a: pytest.fail("a request left the machine"))
    assert not model.healthy()
    with pytest.raises(Unavailable, match="not on this machine"):
        model.complete("system", "user")


def test_health_is_probed_once_then_cached(fake, make_repo):
    repo = Repo(make_repo(files={".compass/config.yaml": ""}))
    model = LocalModel(settings(fake.base_url), repo)
    assert model.healthy() and model.healthy()
    assert [r[:2] for r in fake.requests] == [("GET", "/v1/models")]
    assert json.loads((repo.compass_dir / "llm.json").read_text(encoding="utf-8"))["ok"] is True
    assert model.healthy(use_cache=False) and len(fake.requests) == 2
    assert not LocalModel(settings(fake.base_url, model="other"), repo).healthy()  # a new key probes again
    assert len(fake.requests) == 3


@pytest.mark.parametrize(
    ("listed", "model", "healthy"),
    [(("fake",), "fake", True), (("gemma3:latest",), "gemma3", True), (("gemma3",), "gemma3:latest", True),
     (("gemma3:latest",), "qwen2.5-coder:7b", False), ((), "anything", True)],
)
def test_health_needs_the_configured_model(listed, model, healthy):
    server = FakeLLM(models=listed).start()
    try:
        assert LocalModel(settings(server.base_url, model)).healthy() is healthy
    finally:
        server.stop()


def test_a_completion_is_deterministic_and_trimmed(fake):
    fake.reply = lambda body: "  One line.\n"
    assert LocalModel(settings(fake.base_url)).complete("Be brief.", "Summarise this.", max_tokens=12) == "One line."
    (body,) = fake.completions()
    assert body == {
        "model": "fake",
        "messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Summarise this."}],
        "temperature": 0, "max_tokens": 12, "stream": False,
    }


def test_a_model_that_is_down_or_failing_is_unavailable(fake):
    down = LocalModel(settings(closed_port_url()))
    started = time.monotonic()
    assert not down.healthy()
    # Bounded by the probe's timeout (a refused connect takes about 2 s on Windows, so it times out).
    assert time.monotonic() - started < HEALTH_TIMEOUT_S + 1.5
    with pytest.raises(Unavailable):
        down.complete("system", "user")
    fake.reply = lambda body: None  # a server error
    with pytest.raises(Unavailable):
        LocalModel(settings(fake.base_url)).complete("system", "user")
    assert not LocalModel(settings(fake.base_url, enabled=False)).healthy()
    assert fake.requests[-1][0] == "POST"  # switched off: not even probed


def test_proxy_settings_never_route_loopback_calls(fake, monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, closed_port_url())
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    assert LocalModel(settings(fake.base_url)).healthy(use_cache=False)


# -- the local query tools (DL-04) ------------------------------------------------------------


def test_summarize_file_numbers_the_lines_it_shows(shapes, fake):
    fake.reply = lambda body: "Defines Circle (L4) and perimeter (L17)."
    proc = run_compass("-C", str(shapes.root), "summarize-file", "src/shapes.py", "--focus", "What is measured?")
    assert (proc.returncode, proc.stderr) == (0, "")
    assert proc.stdout == "[local model fake] src/shapes.py:\nDefines Circle (L4) and perimeter (L17).\n"
    prompt = fake.completions()[-1]["messages"][1]["content"]
    assert "Question: What is measured?" in prompt and "\nL17: def perimeter(shape):\n" in prompt


def test_classify_files_maps_answers_onto_the_labels(shapes, fake):
    write(shapes.root, "tests/test_shapes.py", "def test_area():\n    assert True\n")
    fake.reply = lambda body: "Test." if "def test_" in body["messages"][1]["content"] else "**code**"
    proc = run_compass(
        "-C", str(shapes.root), "classify-files", "src/shapes.py", "tests/test_shapes.py", "gone.py", "--labels", "code,test"
    )
    assert (proc.returncode, proc.stderr) == (0, "")
    assert proc.stdout.splitlines() == [
        "[local model fake] 3 files:", "src/shapes.py: code", "tests/test_shapes.py: test", "gone.py: not a file",
    ]
    fake.reply = lambda body: "no idea"
    proc = run_compass("-C", str(shapes.root), "classify-files", "src/shapes.py", "--labels", "code,test", "--json")
    assert json.loads(proc.stdout) == [{"path": "src/shapes.py", "label": "unclear"}]


def test_the_local_tools_say_when_no_model_answers(shapes):
    write(shapes.root, ".compass/config.yaml", f"local_llm:\n  enabled: true\n  base_url: {closed_port_url()}\n")
    proc = run_compass("-C", str(shapes.root), "summarize-file", "src/shapes.py")
    assert proc.returncode == 1 and "no local model answering" in proc.stderr and proc.stdout == ""


# -- enrichment (DL-05) --------------------------------------------------------------------------


def test_enrich_summarises_undocumented_symbols_into_the_map(shapes, fake):
    result = enrich.run(shapes, load_config(shapes.root))
    assert result == {"summarised": 4, "cached": 0, "applied": 4, "left": 0, "failed": 0}
    assert {b["messages"][1]["content"].split(" in ")[0] for b in fake.completions()} == {
        "class Circle", "method Circle.__init__", "method Circle.area", "function perimeter",
    }  # never the documented one
    assert docs(shapes)["perimeter"] == ("Handles perimeter.", "generated")
    assert docs(shapes)["documented"] == ("Doubles x.", "author")
    shard = (shapes.compass_dir / "map/src.md").read_text(encoding="utf-8")
    assert "- L17  fn perimeter(shape) ~ Handles perimeter" in shard
    assert "- L12  fn documented(x) — Doubles x" in shard


def test_summaries_are_cached_by_content_and_survive_rebuilds(shapes, fake):
    enrich.run(shapes, load_config(shapes.root))
    asked = len(fake.completions())
    shard = (shapes.compass_dir / "map/src.md").read_text(encoding="utf-8")

    nothing = {"summarised": 0, "cached": 0, "applied": 0, "left": 0, "failed": 0}
    assert enrich.run(shapes, load_config(shapes.root)) == nothing  # every symbol has its summary
    Indexer(shapes).build(full=True)  # a full rebuild takes them from the cache
    assert (shapes.compass_dir / "map/src.md").read_text(encoding="utf-8") == shard
    assert len(fake.completions()) == asked

    # A changed body loses its summary until the next run; the rest keep theirs.
    path = write(shapes.root, "src/shapes.py", SHAPES.replace("2 * 3.14159 * shape.r", "3.14159 * shape.d"))
    bump_mtime(path)
    Indexer(shapes).update(["src/shapes.py"])
    assert docs(shapes)["perimeter"] == (None, None) and docs(shapes)["area"][1] == "generated"
    assert enrich.run(shapes, load_config(shapes.root))["summarised"] == 1
    assert len(fake.completions()) == asked + 1


def test_enrich_keeps_to_its_limit_and_skips_files_that_moved(shapes, fake):
    assert enrich.run(shapes, load_config(shapes.root), limit=1)["left"] == 3
    write(shapes.root, "src/other.py", "def helper():\n    return 1\n")
    Indexer(shapes).build()
    bump_mtime(write(shapes.root, "src/other.py", "\n\ndef helper():\n    return 1\n"))  # lines moved since
    result = enrich.run(shapes, load_config(shapes.root))
    assert result["summarised"] == 3 and "helper" not in json.dumps(fake.completions())


def test_enrich_drops_refusals_and_stops_when_the_model_fails(shapes, fake):
    fake.reply = lambda body: "I cannot help with that."
    assert enrich.run(shapes, load_config(shapes.root))["summarised"] == 0
    assert all(source is None for _doc, source in docs(shapes).values() if source != "author")
    fake.reply = lambda body: None
    before = len(fake.completions())
    assert enrich.run(shapes, load_config(shapes.root))["failed"] == 3  # then it gives up until next time
    assert len(fake.completions()) == before + 3


@pytest.mark.parametrize(
    ("answer", "summary"),
    [
        ("Parses the config file.", "Parses the config file."),
        ('"Summary: Parses the config file."\nMore detail here.', "Parses the config file."),
        ("`Loads settings`", "Loads settings"),
        ("I'm unable to summarise this.", None),
        ("Sorry, no.", None),
        ("   ", None),
        ("x" * 200, "x" * 119 + "…"),
    ],
)
def test_clean_summary(answer, summary):
    assert enrich.clean_summary(answer) == summary


def test_enrich_does_nothing_without_a_model(shapes, fake):
    write(shapes.root, ".compass/config.yaml", "")
    assert enrich.run(shapes, load_config(shapes.root)) == {"skipped": "local_llm is off in .compass/config.yaml"}
    write(shapes.root, ".compass/config.yaml", f"local_llm:\n  enabled: true\n  base_url: {closed_port_url()}\n")
    assert "no local model answering" in enrich.run(shapes, load_config(shapes.root))["skipped"]
    assert not (shapes.compass_dir / enrich.CACHE_NAME).exists() and fake.completions() == []
    proc = run_compass("-C", str(shapes.root), "enrich")
    assert proc.returncode == 0 and proc.stdout.startswith("compass enrich: nothing done: no local model answering")


def test_one_enrich_at_a_time_and_none_is_lost(shapes, fake):
    config = load_config(shapes.root)
    with file_lock(shapes.compass_dir / "enrich.lock", 1.0):
        assert "another compass enrich is running; it picks this change up" in enrich.run(shapes, config)["skipped"]
    assert (shapes.compass_dir / enrich.AGAIN_NAME).exists()

    # A commit lands while a run is summarising: that run makes one more pass for it.
    def reply(body):
        if not fake.completions()[:-1]:  # the first question
            write(shapes.root, "src/late.py", "def late():\n    return 1\n")
            Indexer(shapes).build()
            assert "skipped" in enrich.run(shapes, config)
        return summary_of(body)

    fake.reply = reply
    result = enrich.run(shapes, config)
    assert (result["summarised"], result["applied"]) == (5, 5)
    assert docs(shapes)["late"] == ("Handles late.", "generated")
    assert not (shapes.compass_dir / enrich.AGAIN_NAME).exists()


@posix_only
def test_a_commit_never_waits_for_enrichment(make_repo, fake):
    fake.hold = threading.Event()  # the model answers only when the test says so
    root = make_repo(files={"src/base.py": 'def base():\n    """Returns one."""\n    return 1\n'})
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    assert run_compass("-C", str(root), "init").returncode == 0
    write(root, ".compass/config.yaml", fake.config(timeout_s=20))
    write(root, "src/extra.py", "def extra():\n    return 1\n")
    git(root, "add", "-A")
    # post-commit refreshes the index inline and starts enrich in the background;
    # were the commit waiting on the model, it would still be waiting.
    proc = subprocess.run(["git", "commit", "-qm", "extra"], cwd=root, capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stderr
    repo = Repo(root)
    assert docs(repo)["extra"] == (None, None)
    fake.hold.set()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and docs(repo)["extra"][1] != "generated":
        time.sleep(0.1)
    assert docs(repo)["extra"] == ("Handles extra.", "generated")
    assert [b["messages"][1]["content"].split(":")[0] for b in fake.completions()] == ["function extra in src/extra.py"]
