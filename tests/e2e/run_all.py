"""Every done-when check, one after another, against whatever Claude Code is
installed and logged in: the weekly compatibility job runs this with the
latest release (NF-14) on GitHub Actions and Azure Pipelines alike. On your
machine the checks use your normal Claude Code login; in CI, the subscription
token from ``claude setup-token``. No API key is ever needed.

    uv run python tests/e2e/run_all.py [--model sonnet]

``E2E_MODEL`` in the environment stands in for ``--model``. Each check runs a
few short headless sessions, which count against the subscription's usage;
it exits 1 when any check fails and prints which.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKS = ("check_query_tools.py", "check_review_loop.py", "check_gates.py", "check_delegation.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    model = os.environ.get("E2E_MODEL", "").strip()
    model = "" if model.startswith("$(") else model  # Azure passes an undefined variable as its own name
    parser.add_argument("--model", default=model or None, help="Claude model for every check")
    parser.add_argument("--only", help="comma-separated check names, e.g. check_gates")
    args = parser.parse_args()
    if shutil.which("claude") is None:
        print("claude (Claude Code) is not on PATH", file=sys.stderr)
        return 2
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    print(f"Claude Code {version}, model {args.model or '(default)'}", flush=True)
    wanted = {name.removesuffix(".py") for name in args.only.split(",")} if args.only else None
    outcomes = []
    for check in CHECKS:
        if wanted and check.removesuffix(".py") not in wanted:
            continue
        print(f"\n=== {check}", flush=True)
        started = time.monotonic()
        command = [sys.executable, str(HERE / check), *(["--model", args.model] if args.model else [])]
        code = subprocess.run(command).returncode
        outcomes.append((check, code, time.monotonic() - started))
    print("\n=== Summary")
    for check, code, seconds in outcomes:
        print(f"{'ok  ' if code == 0 else 'FAIL'}  {check} ({seconds:.0f} s)")
    return 0 if outcomes and all(code == 0 for _, code, _ in outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
