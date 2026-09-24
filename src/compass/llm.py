"""The local LLM adapter (DL-04, DL-06): plain OpenAI-compatible HTTP to a
model on this machine (Ollama, llama.cpp, LM Studio), with no SDK to pin.

Code must never leave the machine except through Claude Code (NF-10), so only
loopback endpoints are accepted (``localhost``, ``127.0.0.0/8``, ``::1``); any
other ``local_llm.base_url`` counts as unreachable. Nothing on a developer's
path waits for a local model, and no Must requirement depends on one: when it
is switched off or down, every local feature simply stays off. Health checks
are cached in ``.compass/llm.json`` for a few minutes, so a session start
never waits long for a model that is not there.
"""

from __future__ import annotations

import ipaddress
import json
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from compass.repo import Repo

HEALTH_TTL_S = 300
HEALTH_TIMEOUT_S = 1.0
CACHE_NAME = "llm.json"


class Unavailable(Exception):
    """The local model is switched off, not on loopback, or not answering."""


def is_loopback(base_url: str) -> bool:
    host = urlsplit(base_url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class LocalModel:
    def __init__(self, settings, repo: Repo | None = None) -> None:
        self.settings = settings
        self.repo = repo
        self.base = settings.base_url.rstrip("/")

    def healthy(self, timeout: float = HEALTH_TIMEOUT_S, use_cache: bool = True) -> bool:
        """Whether the endpoint answers and serves the configured model."""
        if not self.settings.enabled or not is_loopback(self.base):
            return False
        key = f"{self.base} {self.settings.model}"
        cached = self._read_cache() if use_cache else None
        if cached and cached.get("key") == key and time.time() - cached.get("t", 0) < HEALTH_TTL_S:
            return bool(cached.get("ok"))
        ok = self._probe(timeout)
        self._write_cache({"key": key, "ok": ok, "t": round(time.time(), 3)})
        return ok

    def _probe(self, timeout: float) -> bool:
        try:
            data = self._request("GET", "/models", None, timeout)
        except Unavailable:
            return False
        ids = {m.get("id") for m in data.get("data", []) if isinstance(m, dict)} if isinstance(data, dict) else set()
        model = self.settings.model
        # Ollama lists "gemma3:latest" for a model pulled as "gemma3".
        return not ids or model in ids or f"{model}:latest" in ids or model.removesuffix(":latest") in ids

    def complete(self, system: str, user: str, max_tokens: int = 400) -> str:
        """One chat completion, temperature 0; raises Unavailable on any failure."""
        if not self.settings.enabled or not is_loopback(self.base):
            raise Unavailable("local_llm is off, or its base_url is not on this machine")
        body = {
            "model": self.settings.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = self._request("POST", "/chat/completions", body, float(self.settings.timeout_s))
        try:
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise Unavailable(f"unexpected answer from {self.base}: {exc}") from exc

    def _request(self, method: str, path: str, body: dict[str, Any] | None, timeout: float) -> Any:
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method=method,
        )
        # No proxies: a loopback call must stay on loopback whatever HTTP_PROXY says.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace") or "null")
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            raise Unavailable(f"{self.base}{path}: {exc}") from exc

    def _read_cache(self) -> dict[str, Any] | None:
        if self.repo is None:
            return None
        try:
            return json.loads((self.repo.compass_dir / CACHE_NAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_cache(self, data: dict[str, Any]) -> None:
        if self.repo is None or not self.repo.compass_dir.is_dir():
            return
        try:
            (self.repo.compass_dir / CACHE_NAME).write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass


def available(repo: Repo, config) -> bool:
    """Whether local features should be on right now; never raises."""
    try:
        return LocalModel(config.local_llm, repo).healthy()
    except Exception:
        return False
