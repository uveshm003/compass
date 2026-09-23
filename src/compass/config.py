"""``.compass/config.yaml``: defaults, loading and validation.

The template below is both what ``compass init`` writes and the source of the
defaults, so the two cannot drift. User values are merged over it: mappings
merge key by key, everything else (lists included) replaces the default.
An invalid file never stops Compass; bad values fall back to their defaults and
come back as warnings.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from compass.globs import invalid_globs

CONFIG_VERSION = 1

DEFAULT_CONFIG_TEXT = """\
# Compass settings for this repository. Every module can be switched off.
# Derived data (index, map shards, logs) lives next to this file and is
# gitignored; rebuild it at any time with `compass index --full`.
version: 1

prompt_gate:
  enabled: true
  strictness: warn          # off | warn | block
  bypass_prefix: "!quick"
  required_fields: [goal, scope, acceptance]

context_pack:
  enabled: true
  token_budget: 1500

spec_gate:
  enabled: true
  large_task_when:
    files_mentioned_gte: 3
    keywords: [refactor, migrate, redesign, "new module"]

index:
  # gitignore-style globs, matched against repo-relative paths. A pattern
  # without a slash matches a file or directory name at any depth.
  exclude:
    - "**/generated/**"
    - "**/*.min.js"
    - "**/*.min.css"
    - "**/*.js.map"
    - "vendor/**"
    # Lockfiles: the stack profile reads them directly; the code map skips them.
    - "**/*.lock"
    - "**/package-lock.json"
    - "**/pnpm-lock.yaml"
    - "**/bun.lockb"
    - "**/go.sum"
    - "**/Package.resolved"
  max_file_kb: 1024
  shard_token_limit: 2000

query:
  max_response_chars: 4000  # longer MCP answers end with a cursor to continue
  context_lines: 3          # lines shown around a symbol by read_symbol

review:
  enabled: true
  require_anchors: true     # the Stop hook sends Claude back to tag changed files
  reply_max_lines: 10
  # Files that cannot hold a comment; changes to them need no anchor.
  anchor_exempt:
    - "**/*.json"
    - "**/*.jsonl"
    - "**/*.ipynb"
    - "**/*.lock"
    - "**/*.csv"
    - "**/*.tsv"
    - "**/*.svg"
    - "**/*.snap"
    - "**/*.min.*"
    - "**/*.map"
    - "**/go.sum"

delegation:
  digest_threshold_lines: 500

local_llm:
  enabled: false
  base_url: http://localhost:11434/v1
  model: qwen2.5-coder:7b

telemetry:
  enabled: true
  export: false
"""

DEFAULTS: dict[str, Any] = yaml.safe_load(DEFAULT_CONFIG_TEXT)

# Integer settings that must be positive (or at least zero) to make sense.
_POSITIVE = {
    "index.max_file_kb", "index.shard_token_limit", "context_pack.token_budget", "query.max_response_chars",
    "review.reply_max_lines",
}
_NON_NEGATIVE = {"query.context_lines"}


@dataclass(frozen=True)
class IndexSettings:
    exclude: tuple[str, ...]
    max_file_kb: int
    shard_token_limit: int

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_kb * 1024


@dataclass(frozen=True)
class QuerySettings:
    max_response_chars: int
    context_lines: int


@dataclass(frozen=True)
class ReviewSettings:
    enabled: bool
    require_anchors: bool
    reply_max_lines: int
    anchor_exempt: tuple[str, ...]


@dataclass
class Config:
    data: dict[str, Any]
    warnings: list[str] = field(default_factory=list)

    @property
    def review(self) -> ReviewSettings:
        section = self.data["review"]
        return ReviewSettings(
            enabled=section["enabled"],
            require_anchors=section["require_anchors"],
            reply_max_lines=section["reply_max_lines"],
            anchor_exempt=tuple(section["anchor_exempt"]),
        )

    @property
    def query(self) -> QuerySettings:
        section = self.data["query"]
        return QuerySettings(section["max_response_chars"], section["context_lines"])

    @property
    def index(self) -> IndexSettings:
        section = self.data["index"]
        return IndexSettings(
            exclude=tuple(section["exclude"]),
            max_file_kb=section["max_file_kb"],
            shard_token_limit=section["shard_token_limit"],
        )


def default_config() -> Config:
    return Config(copy.deepcopy(DEFAULTS))


def load_config(repo_root: Path) -> Config:
    """Read ``.compass/config.yaml`` over the defaults; never raises."""
    path = repo_root / ".compass" / "config.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default_config()
    except OSError as exc:
        return Config(copy.deepcopy(DEFAULTS), [f"cannot read {path.name}: {exc}; using defaults"])
    return parse_config(text)


def parse_config(text: str) -> Config:
    try:
        user = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        where = getattr(exc, "problem_mark", None)
        line = f" (line {where.line + 1})" if where is not None else ""
        return Config(copy.deepcopy(DEFAULTS), [f"config.yaml is not valid YAML{line}; using defaults"])
    if user is None:
        return default_config()
    warnings: list[str] = []
    if not isinstance(user, dict):
        return Config(copy.deepcopy(DEFAULTS), ["config.yaml must be a mapping; using defaults"])
    version = user.get("version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        warnings.append(f"config.yaml version {version!r} is not {CONFIG_VERSION}; reading it anyway")
    merged = _merge(DEFAULTS, user, "", warnings)
    for key in ("index.exclude", "review.anchor_exempt"):
        section, name = key.split(".")
        for pattern in invalid_globs(merged[section][name]):
            warnings.append(f"{key} pattern {pattern!r} is not a valid glob; ignoring it")
    return Config(merged, warnings)


def _merge(default: Any, user: Any, path: str, warnings: list[str]) -> Any:
    if isinstance(default, dict):
        if not isinstance(user, dict):
            warnings.append(f"{path} should be a mapping; using the default")
            return copy.deepcopy(default)
        out: dict[str, Any] = {}
        for key, value in default.items():
            sub = f"{path}.{key}" if path else key
            out[key] = _merge(value, user[key], sub, warnings) if key in user else copy.deepcopy(value)
        for key in sorted(set(user) - set(default), key=str):
            sub = f"{path}.{key}" if path else str(key)
            warnings.append(f"unknown setting {sub} (ignored)")
        return out
    if not _same_type(default, user):
        warnings.append(f"{path} should be {_type_name(default)}; using the default {default!r}")
        return copy.deepcopy(default)
    if isinstance(default, list) and default:
        kind = type(default[0])
        if not all(isinstance(item, kind) for item in user):
            warnings.append(f"{path} should be a list of {_type_name(default[0])}; using the default")
            return copy.deepcopy(default)
    if path in _POSITIVE and user <= 0:
        warnings.append(f"{path} must be positive; using the default {default!r}")
        return default
    if path in _NON_NEGATIVE and user < 0:
        warnings.append(f"{path} cannot be negative; using the default {default!r}")
        return default
    return copy.deepcopy(user)


def _same_type(default: Any, user: Any) -> bool:
    if isinstance(default, bool):
        return isinstance(user, bool)
    if isinstance(default, int):
        return isinstance(user, int) and not isinstance(user, bool)
    if isinstance(default, float):
        return isinstance(user, (int, float)) and not isinstance(user, bool)
    return isinstance(user, type(default))


def _type_name(value: Any) -> str:
    return {bool: "true/false", int: "a number", float: "a number", str: "text", list: "a list"}.get(
        type(value), type(value).__name__
    )
