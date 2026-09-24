"""Prompt-gate rules, one module per field (the Architecture's extension point).

A rule module defines ``FIELD`` (the name ``prompt_gate.required_fields``
uses) and ``check(prompt, config) -> list[str]``: the fields it finds missing,
usually ``[]`` or ``[FIELD]``. ``prompt`` is a ``compass.gate.ParsedPrompt``,
already parsed and, when the index is available, with its names resolved.
Rules are pure functions over that: no file access, no network, no model.
"""
