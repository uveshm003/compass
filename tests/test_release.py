"""scripts/check_release.py, the gate both release pipelines run before
publishing (IN-10, IN-13)."""


from __future__ import annotations

import importlib.util
import io
import json
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("check_release", ROOT / "scripts/check_release.py")
check_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_release)

VERSION = check_release.versions(ROOT)["pyproject.toml"]


@pytest.fixture
def tree(tmp_path):
    """The four files that carry the version, copied from this checkout."""
    for rel in ("pyproject.toml", "plugin/.claude-plugin/plugin.json", "src/compass/__init__.py", "npm/package.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    return tmp_path


def dist(tmp_path: Path, version: str = VERSION, plugin_version: str | None = None, npm_version: str | None = None) -> Path:
    out = tmp_path / "dist"
    out.mkdir()
    with zipfile.ZipFile(out / f"compass-{version}-py3-none-any.whl", "w") as zf:
        zf.writestr(check_release.BUNDLED_PLUGIN, json.dumps({"version": plugin_version or version}))
        zf.writestr(check_release.BUNDLED_MARKETPLACE, "{}")
    (out / f"compass-{version}.tar.gz").write_bytes(b"")
    with tarfile.open(out / f"compass-cc-{version}.tgz", "w:gz") as tf:
        for name, data in (("package/package.json", json.dumps({"version": npm_version or version}).encode()),
                           ("package/bin/compass-cc.js", b"")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return out


def test_this_checkout_is_consistent():
    assert check_release.check(ROOT, "", None) == []
    assert len(set(check_release.versions(ROOT).values())) == 1


def test_a_tag_must_name_the_version_but_branch_builds_need_none():
    assert check_release.check(ROOT, f"v{VERSION}", None) == []
    assert check_release.check(ROOT, "main", None) == []
    assert check_release.check(ROOT, "v9.9.9", None) == [f"tag v9.9.9 does not match version {VERSION}"]


def test_a_version_out_of_step_is_reported(tree):
    path = tree / "npm/package.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = "0.0.1"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert check_release.check(tree, "", None) == [f"npm/package.json says 0.0.1, pyproject.toml says {VERSION}"]


def test_artifacts_are_checked(tmp_path):
    assert check_release.check_dist(ROOT, dist(tmp_path), VERSION) == []


def test_a_wheel_with_a_stale_plugin_or_a_wrong_npm_tarball_is_refused(tmp_path):
    problems = check_release.check_dist(ROOT, dist(tmp_path, plugin_version="0.0.1", npm_version="0.0.2"), VERSION)
    assert any("bundles plugin 0.0.1" in p for p in problems)
    assert any("holds version 0.0.2" in p for p in problems)


def test_missing_artifacts_are_refused(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    problems = check_release.check_dist(ROOT, empty, VERSION)
    assert len(problems) == 3  # wheel, sdist, npm tarball
