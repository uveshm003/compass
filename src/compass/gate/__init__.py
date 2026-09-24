"""The prompt gate (C1, PG-01 to PG-04): deterministic checks on a prompt,
with no model call, so they fit NF-01's 100 ms on every prompt.

A prompt is parsed once (``parse``), sorted into a kind, and only a prompt
that starts a task is checked. Questions, short replies, slash commands and
follow-ups inside a task that is already under way are never nagged: the top
project risk is developers switching the plugin off, so the rules err towards
letting prompts through. They are tuned from ``.compass/logs/gate.jsonl``,
which records every decision, not from guesses.

Each checked field is a rule module in ``gate/rules/`` (``FIELD`` plus
``check(prompt, config) -> list[missing_field]``); ``prompt_gate.required_fields``
picks which ones run. Adding a rule means adding a module there.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from compass.config import Config

FIELD_TITLES = {
    "goal": "Goal", "scope": "Scope", "non_goals": "Non-goals", "acceptance": "Accept when", "constraints": "Constraints",
}
FIELD_HINTS = {
    "goal": "what should change, starting with a verb",
    "scope": "the files, modules or symbols involved",
    "non_goals": "what this task will not do",
    "acceptance": "how you will know it is done: behaviour, tests",
    "constraints": "limits to respect: APIs, dependencies, compatibility",
}
TASK_TEMPLATE = "/compass:task Goal: … Scope: … Non-goals: … Accept when: … Constraints: …"

# Label spellings, normalised to a field. `Accept when:` is the template's own.
_LABELS = re.compile(
    r"(?im)(?:^|(?<=[\s.;,(]))(goal|scope|non[- ]?goals?|accept(?:ance)?(?:\s+(?:when|criteria))?|done\s+when"
    r"|success\s+criteria|constraints?)\s*:"
)
_LABEL_FIELD = {"goal": "goal", "scope": "scope", "constraint": "constraints", "constraints": "constraints"}

# Openers that make a request out of a question ("can you add …").
_POLITE = re.compile(
    r"^(?:(?:please|pls|kindly|now|then|also|and|ok(?:ay)?|so|hey|hi|claude)[\s,]+)*"
    r"(?:(?:can|could|would|will)\s+(?:you|we)\s+(?:please\s+)?|let'?s\s+|lets\s+|i\s+(?:want|need|would\s+like|'d\s+like)"
    r"\s+(?:you\s+)?to\s+|we\s+(?:need|want|should)\s+to\s+|help\s+me\s+|go\s+ahead\s+and\s+)?",
    re.I,
)
QUESTION_WORDS = frozenset(
    "what where which who whom whose when why how is are was were do does did can could would should will shall may"
    " might has have had am explain describe show tell list summarize summarise find compare walk clarify review"
    " check understand".split()
)
# Verbs that open a request for a change; the first word of a task prompt.
TASK_VERBS = frozenset(
    "add fix implement refactor remove delete rename update change make create write migrate move extract replace"
    " optimize optimise improve support handle allow enable disable build convert split merge document test rewrite"
    " introduce upgrade bump clean drop port wire expose validate cache deprecate set configure integrate generate"
    " scaffold adjust tweak restore revert raise reduce increase limit cap return ensure prevent avoid stop start"
    " speed simplify parse log track store load save send fetch retry throttle paginate sort filter format lint"
    " annotate translate localize localise secure encrypt sanitize sanitise escape guard debug investigate resolve"
    " address finish complete apply use switch turn put append insert wrap inline reorder reorganize reorganise"
    " restructure standardize standardise normalize normalise unify dedupe deduplicate harden patch install"
    " uninstall rework redesign rebuild tidy expand shrink trim reject accept emit publish deploy release".split()
)
MIN_TASK_WORDS = 4  # below this, and not opening with a task verb, a prompt is a reply ("yes", "go ahead")

_PATH_EXTENSIONS = frozenset(
    ".py .pyi .ts .tsx .js .jsx .mjs .cjs .go .rs .java .kt .kts .swift .dart .cs .c .h .cc .cpp .hpp .rb .php"
    " .scala .lua .sh .bash .zsh .ps1 .sql .md .rst .txt .json .yaml .yml .toml .ini .cfg .xml .html .css .scss"
    " .vue .svelte .proto .graphql .tf .gradle .lock .env".split()
)
_BACKTICK = re.compile(r"`([^`\n]{1,200})`")
_TOKEN = re.compile(r"[\w./\\:-]+(?:\(\))?")
_CAMEL = re.compile(r"^(?:[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+|[a-z][a-z0-9]*[A-Z]\w*|[A-Z]{2,}[a-z]\w*)$")
_SNAKE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+$")
_DOTTED = re.compile(r"^[A-Za-z_]\w*(?:(?:\.|::|#)[A-Za-z_]\w*)+(?:\(\))?$")
_NOT_NAMES = frozenset({"e.g", "i.e", "etc", "vs"})
MAX_CANDIDATES = 20


@dataclass(frozen=True)
class Candidate:
    """A name the prompt mentions: ``path`` (a file or directory), or
    ``symbol`` (a class, function, ``Class.method``)."""

    text: str
    kind: str
    quoted: bool = False  # in backticks


@dataclass
class ParsedPrompt:
    text: str
    body: str  # without a bypass prefix or a polite opener
    words: list[str]
    labels: dict[str, str]
    candidates: list[Candidate]
    kind: str = "task"  # empty | command | bypass | question | reply | task
    resolved: dict[str, Any] = field(default_factory=dict)  # candidate text -> what the index knows
    stack: list[str] = field(default_factory=list)  # the project's frameworks and tools it names ("react 18.3.1")


def parse(text: str, bypass_prefix: str = "!quick") -> ParsedPrompt:
    raw = (text or "").strip()
    bypass = bool(bypass_prefix) and raw.startswith(bypass_prefix)
    after = raw[len(bypass_prefix):].strip() if bypass else raw
    body = _POLITE.sub("", after, count=1).strip()
    words = re.findall(r"[a-z][\w'-]*", body.lower())
    parsed = ParsedPrompt(raw, body, words, _labels(raw), _candidates(raw))
    parsed.kind = _kind(parsed, bypass)
    return parsed


def _kind(p: ParsedPrompt, bypass: bool) -> str:
    if not p.text:
        return "empty"
    if p.text.startswith("/"):
        return "command"
    if bypass:
        return "bypass"
    first = p.words[0] if p.words else ""
    if p.labels.get("goal"):
        return "task"
    if first in QUESTION_WORDS and first not in TASK_VERBS:
        return "question"
    if p.body.rstrip().endswith("?") and first not in TASK_VERBS:
        return "question"
    if len(p.words) < MIN_TASK_WORDS and first not in TASK_VERBS:
        return "reply"
    return "task"


def _labels(text: str) -> dict[str, str]:
    """``Goal: …`` style fields, each with the text up to the next label."""
    found: dict[str, str] = {}
    marks = list(_LABELS.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        value = text[m.end() : end].strip(" \t\n;,.")
        found.setdefault(_label_field(m.group(1)), value)
    return found


def _label_field(label: str) -> str:
    key = " ".join(label.lower().replace("-", " ").split())
    if key.startswith("non"):
        return "non_goals"
    if key.startswith(("accept", "done", "success")):
        return "acceptance"
    return _LABEL_FIELD.get(key, key)


def _candidates(text: str) -> list[Candidate]:
    """Names worth looking up: anything in backticks, path-like tokens, and
    identifiers written as code (CamelCase, snake_case, ``a.b``, ``f()``).
    Plain words are not names; they would drown the lookups in noise."""
    out: dict[str, Candidate] = {}

    def add(token: str, quoted: bool) -> None:
        token = token.strip().strip(".,;:!?'\"[]{}<>")
        called = token.endswith("()")  # reset() is code even in plain prose
        token = token.removesuffix("()").strip("()")
        if not token or token.lower() in _NOT_NAMES or len(token) < 2 or "://" in token:
            return
        kind = "symbol" if called and re.fullmatch(r"[A-Za-z_][\w.:#]*", token) else _classify_token(token, quoted)
        if kind and token not in out and len(out) < MAX_CANDIDATES:
            out[token] = Candidate(token, kind, quoted)

    for m in _BACKTICK.finditer(text):
        add(m.group(1), True)
    for m in _TOKEN.finditer(_BACKTICK.sub(" ", text)):
        add(m.group(0), False)
    return list(out.values())


def _classify_token(token: str, quoted: bool) -> str | None:
    tail = token.rsplit("/", 1)[-1]
    ext = ("." + tail.rsplit(".", 1)[-1].lower()) if "." in tail else ""
    if "/" in token or "\\" in token or ext in _PATH_EXTENSIONS:
        if re.fullmatch(r"[\d./]+", token):
            return None  # 1.2.3, 3/4
        return "path"
    if _DOTTED.match(token) or _CAMEL.match(token) or _SNAKE.match(token):
        return "symbol"
    if quoted and re.fullmatch(r"[A-Za-z_][\w.:#-]*", token):
        return "symbol"
    return None


# -- the rules ---------------------------------------------------------------------


def _rules() -> dict[str, Any]:
    from compass.gate import rules

    found = {}
    for info in sorted(pkgutil.iter_modules(rules.__path__), key=lambda i: i.name):
        module = importlib.import_module(f"{rules.__name__}.{info.name}")
        name = getattr(module, "FIELD", None)
        if isinstance(name, str) and callable(getattr(module, "check", None)):
            found[name] = module
    return found


def missing_fields(prompt: ParsedPrompt, config: Config) -> list[str]:
    """The required fields (``prompt_gate.required_fields``) the prompt lacks."""
    rules = _rules()
    missing: list[str] = []
    for name in config.data["prompt_gate"]["required_fields"]:
        rule = rules.get(name)
        if rule is not None:
            missing += [m for m in rule.check(prompt, config) if m not in missing]
    return missing


def checklist(missing: list[str]) -> str:
    """What block mode prints for the developer (PG-02)."""
    lines = [f"[compass] This prompt does not state its {_join(missing)}. Add them and send it again:"]
    lines += [f"  {FIELD_TITLES.get(m, m):<12} {FIELD_HINTS.get(m, '')}" for m in missing]
    lines.append(f"The task template has every field: {TASK_TEMPLATE}")
    lines.append("To send it as it is, start the prompt with !quick.")
    return "\n".join(lines)


def ask_first(missing: list[str]) -> str:
    """What warn mode tells Claude (PG-02)."""
    asks = "; ".join(f"{FIELD_TITLES.get(m, m).lower()} ({FIELD_HINTS.get(m, '')})" for m in missing)
    return (
        f"[compass] The developer's request does not state its {_join(missing)}. Unless the conversation already"
        f" answers it, ask one short question about each before changing any code: {asks}."
    )


def _join(missing: list[str]) -> str:
    names = [FIELD_TITLES.get(m, m).lower() for m in missing]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
