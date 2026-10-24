"""``compass status`` and ``/compass:status`` (UX-07): one screen with where
Compass stands in this repository and what the developer can reply next, so
nobody needs the docs to find their way."""

from __future__ import annotations

from compass import state
from compass.repo import Repo

MODULES = ("query", "prompt_gate", "context_pack", "spec_gate", "review", "delegation", "local_llm", "telemetry")
LABELS = {
    "query": "code map", "prompt_gate": "prompt check", "context_pack": "context", "spec_gate": "plans for big tasks",
    "review": "review notes", "delegation": "helpers", "local_llm": "local model", "telemetry": "telemetry",
}
NOT_SET_UP = (
    "Compass isn't set up in this repository.\n"
    "Say \"set up Compass\" to Claude (or run `compass init`) to switch it on."
)


def text(repo: Repo) -> str:
    from compass.anchors import scan_file
    from compass.config import load_config
    from compass.review import manifest_rel
    from compass.spec import spec_rel

    if not repo.initialized:
        return NOT_SET_UP
    config = load_config(repo.root)
    on = [m for m in MODULES if config.data.get(m, {}).get("enabled")]
    lines = [f"Compass is on in {repo.root.name}: " + (", ".join(LABELS[m] for m in on) or "telemetry only") + "."]
    current = state.read(repo)
    task = state.active_task(current)
    record = current["tasks"].get(task) if task else None
    waiting = state.needs_approval(current)
    tagged = 0
    touched = state.touched(current, task) if task else []
    if task and config.review.enabled:
        tagged = sum(len(scan_file(repo.root, rel, task)) for rel in touched)
    if not task or not (record and (record.get("brief") or touched)):
        lines.append("No task under way: just ask Claude for what you need.")
    else:
        brief = " ".join((record.get("brief") or "").split())
        lines.append(f"Task {task}" + (f": {brief[:90]}{'…' if len(brief) > 90 else ''}" if brief else ""))
        if waiting:
            lines.append(f"  Plan waiting for you: {spec_rel(task)}. Reply \"approve\" when it's right.")
        elif record.get("approved"):
            lines.append(f"  Plan approved by {record['approved'].get('by')}.")
        if touched:
            files = f"{len(touched)} file{'s' if len(touched) != 1 else ''} changed"
            if tagged:
                lines.append(f"  {files}, {tagged} review note{'s' if tagged != 1 else ''}: {manifest_rel(task)}")
                lines.append("  Read it, then reply \"accept\" (or \"accept and commit\").")
            else:
                lines.append(f"  {files}.")
    lines += [
        "",
        "Things you can say to Claude:",
        "  \"approve\"            a waiting plan is right; Claude goes ahead",
        "  \"accept\"             you've reviewed the changes; Compass removes its notes",
        "  \"accept and commit\"  both, then Claude commits",
        f"  \"{config.data['prompt_gate']['bypass_prefix']} …\"           skip Compass's checks for one message",
    ]
    return "\n".join(lines)
