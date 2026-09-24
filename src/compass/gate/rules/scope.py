"""Scope: a ``Scope:`` label, a path, anything in backticks, a code name
(``StockItem``, ``parse_config``, ``Retry()``), or one of the project's own
frameworks or tools by name ("upgrade react"). A resolved name is best, but an
unresolved one still says where to look, so it counts too."""

from __future__ import annotations

FIELD = "scope"


def check(prompt, config) -> list[str]:
    if prompt.labels.get("scope") or prompt.candidates or prompt.stack:
        return []
    return [FIELD]
