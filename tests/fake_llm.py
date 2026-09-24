"""A fake OpenAI-compatible model server on 127.0.0.1 for the local-LLM tests
(DL-04 to DL-06): ``GET /v1/models`` and ``POST /v1/chat/completions``, with
answers from a function of the request body. It records every request, so a
test can tell whether the model was asked at all."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeLLM:
    def __init__(self, models: tuple[str, ...] = ("fake",), reply: Callable[[dict], str | None] | None = None):
        self.models = list(models)
        self.reply = reply or (lambda body: "Does one thing well.")
        self.hold: threading.Event | None = None  # completions wait until it is set
        self.requests: list[tuple[str, str, Any]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._server.block_on_close = False
        self._server.fake = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, args=(0.05,), daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    def config(self, model: str = "fake", **extra: Any) -> str:
        """``.compass/config.yaml`` text that points local_llm here."""
        lines = ["local_llm:", "  enabled: true", f"  base_url: {self.base_url}", f"  model: {model}"]
        lines += [f"  {key}: {value}" for key, value in extra.items()]
        return "\n".join(lines) + "\n"

    def completions(self) -> list[dict]:
        return [body for method, path, body in self.requests if method == "POST"]

    def start(self) -> FakeLLM:
        self._thread.start()
        return self

    def stop(self) -> None:
        if self.hold is not None:
            self.hold.set()
        self._server.shutdown()
        self._server.server_close()


def closed_port_url() -> str:
    """A loopback URL where nothing listens: connections are refused at once."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


class _Handler(BaseHTTPRequestHandler):
    server: Any

    def do_GET(self) -> None:  # noqa: N802 (http.server's naming)
        fake = self.server.fake
        fake.requests.append(("GET", self.path, None))
        if self.path.rstrip("/") == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in fake.models]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        fake = self.server.fake
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")
        fake.requests.append(("POST", self.path, body))
        if fake.hold is not None:
            fake.hold.wait(30)
        content = fake.reply(body) if self.path.rstrip("/") == "/v1/chat/completions" else None
        if content is None:
            self._send(500, {"error": "no answer"})
            return
        message = {"role": "assistant", "content": content}
        self._send(200, {"object": "chat.completion", "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]})

    def _send(self, status: int, data: dict) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass
