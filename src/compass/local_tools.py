"""The local-model query tools (DL-04): ``summarize_file`` and
``classify_files``. Tier 1: a model on this machine does bulk, low-judgment
reading at no token cost, and only its short answer reaches Claude.

The MCP server offers these tools only when ``local_llm`` is enabled and the
model answers at start-up (DL-06); the CLI twins say plainly when it is not.
"""

from __future__ import annotations

from compass.llm import LocalModel, Unavailable
from compass.query import Queries, Result

MAX_FILE_LINES = 1500
MAX_CLASSIFY_FILES = 50
CLASSIFY_LINES = 120
SUMMARY_SYSTEM = (
    "You summarise source files for a coding agent that has not read them. Be factual and brief; never guess."
)


def summarize_file(queries: Queries, model: LocalModel, path: str, focus: str | None = None) -> Result:
    rel = queries._rel(path)
    full = queries._full_path(rel) if rel else None
    if full is None or not full.is_file():
        return Result([f"[compass] {path} is not a file in this repository."], None)
    lines = full.read_text(encoding="utf-8", errors="replace").split("\n")
    shown = lines[:MAX_FILE_LINES]
    numbered = "\n".join(f"L{n}: {text}" for n, text in enumerate(shown, 1))
    cut = f"\n(Only the first {MAX_FILE_LINES} of {len(lines)} lines are shown.)" if len(lines) > MAX_FILE_LINES else ""
    ask = focus or "What does this file do, and what are its main parts?"
    prompt = f"File: {rel}\nQuestion: {ask}\nAnswer in at most 12 lines, citing line numbers as L<n>.{cut}\n\n{numbered}"
    try:
        answer = model.complete(SUMMARY_SYSTEM, prompt, max_tokens=500)
    except Unavailable as exc:
        return Result([f"[compass] The local model did not answer ({exc}); use file_outline or read_symbol."], None)
    lines_out = [f"[local model {model.settings.model}] {rel}:", *answer.strip().splitlines()]
    return Result(lines_out, {"path": rel, "model": model.settings.model, "summary": answer.strip()})


def classify_files(queries: Queries, model: LocalModel, paths: list[str], labels: list[str]) -> Result:
    labels = [label.strip() for label in labels if label.strip()]
    if not labels:
        return Result(["[compass] classify_files needs at least one label."], None)
    rows: list[tuple[str, str]] = []
    for path in paths[:MAX_CLASSIFY_FILES]:
        rel = queries._rel(path)
        full = queries._full_path(rel) if rel else None
        if full is None or not full.is_file():
            rows.append((path, "not a file"))
            continue
        head = "\n".join(full.read_text(encoding="utf-8", errors="replace").split("\n")[:CLASSIFY_LINES])
        prompt = f"Labels: {', '.join(labels)}\nFile: {rel}\n\n{head}\n\nReply with exactly one of the labels."
        try:
            answer = model.complete("You sort files into categories. Reply with one label only.", prompt, max_tokens=20)
        except Unavailable as exc:
            return Result([f"[compass] The local model did not answer ({exc})."], None)
        rows.append((rel, _match_label(answer, labels)))
    files = "1 file" if len(rows) == 1 else f"{len(rows)} files"
    lines = [f"[local model {model.settings.model}] {files}:"] + [f"{p}: {label}" for p, label in rows]
    if len(paths) > MAX_CLASSIFY_FILES:
        lines.append(f"[compass] Only the first {MAX_CLASSIFY_FILES} of {len(paths)} files were classified.")
    return Result(lines, [{"path": p, "label": label} for p, label in rows])


def _match_label(answer: str, labels: list[str]) -> str:
    text = (answer or "").strip().strip("`\"'.* ").lower()
    for label in labels:
        if text == label.lower():
            return label
    for label in labels:  # "Label: tests", "tests." and friends
        if label.lower() in text:
            return label
    return "unclear"
