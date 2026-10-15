"""Checks a release before anything is published (IN-10, IN-13).

    python scripts/check_release.py [DIST]

Every copy of the version must agree: pyproject.toml, plugin.json,
compass/__init__.py and npm/package.json. On a version tag (RELEASE_TAG, set
by both release pipelines) the tag must name that version. With DIST, the
built artifacts are checked too: one wheel and one sdist of that version, the
wheel carrying the plugin and its marketplace file, and the npm tarball.

Package names are read from the files, never written here, so renaming the
packages (an open question) changes no pipeline code. Exit 1 on any problem.
"""


from __future__ import annotations

import json
import os
import re
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_PLUGIN = "compass/_bundle/plugin/.claude-plugin/plugin.json"
BUNDLED_MARKETPLACE = "compass/_bundle/.claude-plugin/marketplace.json"


def versions(root: Path) -> dict[str, str]:
    init = (root / "src/compass/__init__.py").read_text(encoding="utf-8")
    found = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", init, re.MULTILINE)
    return {
        "pyproject.toml": tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
        "plugin/.claude-plugin/plugin.json": json.loads(
            (root / "plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8")
        )["version"],
        "src/compass/__init__.py": found.group(1) if found else "(missing)",
        "npm/package.json": json.loads((root / "npm/package.json").read_text(encoding="utf-8"))["version"],
    }


def check(root: Path, tag: str, dist: Path | None) -> list[str]:
    problems: list[str] = []
    found = versions(root)
    version = found["pyproject.toml"]
    for where, value in found.items():
        if value != version:
            problems.append(f"{where} says {value}, pyproject.toml says {version}")
    # Branch builds (a manual run) have no version tag; only a v* tag must match.
    if re.fullmatch(r"v\d.*", tag) and tag != f"v{version}":
        problems.append(f"tag {tag} does not match version {version}")
    if dist is not None:
        problems += check_dist(root, dist, version)
    return problems


def check_dist(root: Path, dist: Path, version: str) -> list[str]:
    problems: list[str] = []
    python_name = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    stem = re.sub(r"[-_.]+", "_", python_name).lower()  # wheel and sdist file names normalise the project name
    wheels = sorted(dist.glob(f"{stem}-{version}-*.whl"))
    sdists = sorted(dist.glob(f"{stem}-{version}.tar.gz"))
    if len(wheels) != 1:
        problems.append(f"expected one {stem}-{version} wheel in {dist}, found {len(wheels)}")
    if len(sdists) != 1:
        problems.append(f"expected one {stem}-{version} sdist in {dist}, found {len(sdists)}")
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as zf:
            names = set(zf.namelist())
            for required in (BUNDLED_PLUGIN, BUNDLED_MARKETPLACE):
                if required not in names:
                    problems.append(f"{wheel.name} lacks {required}")
            if BUNDLED_PLUGIN in names:
                bundled = json.loads(zf.read(BUNDLED_PLUGIN))["version"]
                if bundled != version:
                    problems.append(f"{wheel.name} bundles plugin {bundled}, expected {version}")
    npm = json.loads((root / "npm/package.json").read_text(encoding="utf-8"))
    tarball = dist / f"{npm['name'].lstrip('@').replace('/', '-')}-{version}.tgz"
    if not tarball.is_file():
        problems.append(f"missing npm tarball {tarball.name} in {dist}")
    else:
        with tarfile.open(tarball) as tf:
            member = tf.extractfile("package/package.json")
            packed = json.loads(member.read()) if member else {}
            if packed.get("version") != version:
                problems.append(f"{tarball.name} holds version {packed.get('version')}, expected {version}")
            names = set(tf.getnames())
            for script in (npm.get("bin") or {}).values():
                if f"package/{script.removeprefix('./')}" not in names:
                    problems.append(f"{tarball.name} lacks {script}")
    return problems


def main(argv: list[str]) -> int:
    dist = Path(argv[0]) if argv else None
    tag = os.environ.get("RELEASE_TAG", "")
    problems = check(ROOT, tag, dist)
    for problem in problems:
        print(f"release check: {problem}", file=sys.stderr)
    if not problems:
        version = versions(ROOT)["pyproject.toml"]
        print(f"release check: {version} consistent" + (f", tag {tag}" if tag.startswith("v") else "")
              + (f", artifacts in {dist}" if dist else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
