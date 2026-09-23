"""`compass init`, the git hooks it installs, and the CLI surface."""

from __future__ import annotations

import json
import os
import sys

from compass.githooks import CHAIN_SUFFIX, HOOKS, MARKER
from compass.index.store import Store
from compass.repo import Repo
from conftest import git, needs_permissions, posix_only, run_compass, write


def symbols(root) -> set[str]:
    with Store.open(Repo(root).db_path) as store:
        return {s["name"] for s in store.dump()["symbols"]}


def test_help_and_version():
    proc = run_compass("--help")
    assert proc.returncode == 0
    for command in ("init", "index", "update", "files", "stack", "hook"):
        assert command in proc.stdout
    assert run_compass("--version").stdout.startswith("compass 0.1.0")


def test_outside_git_is_a_clear_error(tmp_path):
    proc = run_compass("-C", str(tmp_path), "index")
    assert proc.returncode == 1
    assert "not inside a git working tree" in proc.stderr


def test_init_writes_config_gitignore_hooks_and_index(make_repo):
    root = make_repo("python_app")
    proc = run_compass("-C", str(root), "init")
    assert proc.returncode == 0, proc.stderr
    assert (root / ".compass/config.yaml").read_text(encoding="utf-8").startswith("# Compass settings")
    assert "map/" in (root / ".compass/.gitignore").read_text(encoding="utf-8")
    for hook in HOOKS:
        assert MARKER in (root / ".git/hooks" / hook).read_text(encoding="utf-8")
    assert (root / ".compass/map/_index.md").exists()
    # Derived files are ignored; the config is not.
    status = git(root, "status", "--porcelain", "--untracked-files=all", ".compass")
    assert ".compass/config.yaml" in status and ".compass/.gitignore" in status
    assert "index.db" not in status and "map/" not in status

    again = run_compass("-C", str(root), "init")
    assert again.returncode == 0 and "exists; kept as is" in again.stdout
    assert not list((root / ".git/hooks").glob(f"*{CHAIN_SUFFIX}"))


@posix_only
def test_existing_hooks_are_chained_not_replaced(make_repo):
    root = make_repo("go_app")
    hook = root / ".git/hooks/post-commit"
    hook.write_text("#!/bin/sh\necho ran > \"$(git rev-parse --show-toplevel)/chained-ran\"\nexit 3\n")
    hook.chmod(0o755)
    assert run_compass("-C", str(root), "init").returncode == 0
    assert (root / ".git/hooks/post-commit.compass-chained").exists()

    write(root, "pkg/api/extra.go", "package api\n\nfunc Extra() {}\n")
    git(root, "add", "-A")
    proc = run_git_commit(root)
    assert proc.returncode == 0  # post-commit exit codes never fail a commit
    assert (root / "chained-ran").exists()
    assert "Extra" in symbols(root)


@posix_only
def test_hooks_that_dispatch_on_their_own_name_are_left_alone(make_repo):
    root = make_repo("go_app")
    hooks = root / ".git/hooks"
    by_name = '#!/bin/sh\nhook=$(basename "$0")\nexec run-hook "$hook" "$@"\n'
    (hooks / "post-merge").write_text(by_name)
    (hooks / "post-merge").chmod(0o755)
    (hooks / "post-rewrite").write_text('#!/bin/sh\n. "$(dirname "$0")/husky.sh"\n')
    (hooks / "post-rewrite").chmod(0o755)
    os.symlink("overcommit-hook", hooks / "post-checkout")
    proc = run_compass("-C", str(root), "init", "--no-index")
    assert proc.returncode == 0
    for hook in ("post-merge", "post-rewrite", "post-checkout"):
        assert f"{hook}: left alone (it dispatches on its own name)" in proc.stdout
        assert not os.path.lexists(hooks / f"{hook}{CHAIN_SUFFIX}")
    assert (hooks / "post-merge").read_text() == by_name
    assert (hooks / "post-checkout").is_symlink()
    assert MARKER in (hooks / "post-commit").read_text()  # the free one is still installed


def run_git_commit(root):
    import subprocess

    return subprocess.run(["git", "commit", "-qm", "msg"], cwd=root, capture_output=True, text=True)


@posix_only
def test_git_hooks_keep_the_index_current_across_checkouts(make_repo):
    root = make_repo("rust_app")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    assert run_compass("-C", str(root), "init").returncode == 0
    git(root, "checkout", "-qb", "feature")
    write(root, "src/extra.rs", "/// Extra.\npub fn extra() {}\n")
    (root / "src/transport/retry.rs").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-qm", "feature")  # post-commit hook
    assert "extra" in symbols(root) and "next_delay" not in symbols(root)
    git(root, "checkout", "-q", "main")  # post-checkout hook
    assert "extra" not in symbols(root) and "next_delay" in symbols(root)
    shard = (root / ".compass/map/src/transport.md").read_text(encoding="utf-8")
    assert "next_delay" in shard


def test_core_hooks_path_is_respected(make_repo):
    root = make_repo("python_app")
    git(root, "config", "core.hooksPath", ".husky")
    proc = run_compass("-C", str(root), "init", "--no-index")
    assert proc.returncode == 0
    assert "core.hooksPath is set" in proc.stdout and "compass update --from-git" in proc.stdout
    assert not (root / ".husky").exists()
    assert not any((root / ".git/hooks" / h).exists() for h in HOOKS)


def test_update_from_git_never_fails(make_repo, tmp_path):
    proc = run_compass("-C", str(tmp_path), "update", "--from-git")
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")
    root = make_repo("python_app")
    proc = run_compass("-C", str(root), "update", "--from-git")  # not initialised: no-op
    assert proc.returncode == 0 and not (root / ".compass").exists()


def test_files_and_stack_json(make_repo):
    root = make_repo("ts_app")
    files = json.loads(run_compass("-C", str(root), "files", "--json").stdout)
    paths = {f["path"] for f in files}
    assert "src/components/Button.tsx" in paths
    assert "public/lib.min.js" not in paths and "dist/bundle.js" not in paths and "pnpm-lock.yaml" not in paths
    stack = json.loads(run_compass("-C", str(root), "stack", "--json").stdout)
    package = stack["stacks"]["node"]["packages"][0]
    assert package["package_manager"] == "pnpm"
    assert package["frameworks"]["react"] == "18.3.1"
    assert package["commands"]["test"] == "pnpm test"


def test_binaries_symlinks_and_big_files_are_skipped(make_repo):
    root = make_repo("python_app")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    write(root, "big.py", "x = 1\n" * 200_000)  # over 1024 KB
    if os.name != "nt":
        os.symlink("src/inventory/models.py", root / "alias.py")
    paths = {f["path"] for f in json.loads(run_compass("-C", str(root), "files", "--json").stdout)}
    assert not paths & {"logo.png", "big.py", "alias.py"}
    assert "src/inventory/models.py" in paths


def test_index_and_update_commands(make_repo):
    root = make_repo("python_app")
    proc = run_compass("-C", str(root), "index", "--json")
    assert proc.returncode == 0 and json.loads(proc.stdout)["mode"] == "full"
    write(root, "src/inventory/api.py", "def only():\n    pass\n")
    proc = run_compass("-C", str(root / "src"), "update", "inventory/api.py")
    assert proc.returncode == 0 and "1 re-parsed" in proc.stdout
    assert "only" in symbols(root)
    proc = run_compass("-C", str(root), "update", str(root.parent))
    assert proc.returncode == 1 and "outside" in proc.stderr
    proc = run_compass("-C", str(root), "update", ".")  # the repo root means everything
    assert proc.returncode == 0 and proc.stdout.startswith("Index up to date")


@needs_permissions
def test_unexpected_errors_are_logged_for_background_runs(make_repo):
    root = make_repo("python_app")
    assert run_compass("-C", str(root), "index").returncode == 0
    write(root, "src/inventory/api.py", "def changed():\n    pass\n")
    (root / ".compass/map/src").chmod(0o555)
    try:
        proc = run_compass("-C", str(root), "index")
    finally:
        (root / ".compass/map/src").chmod(0o755)
    assert proc.returncode == 1
    assert "internal error" in proc.stderr and "errors.log" in proc.stderr
    log = (root / ".compass/logs/errors.log").read_text(encoding="utf-8")
    assert "[compass index]" in log and "PermissionError" in log


def test_stack_text_output_includes_ci_commands(make_repo):
    proc = run_compass("-C", str(make_repo("go_app")), "stack")
    assert proc.returncode == 0, proc.stderr
    assert "github_actions:" in proc.stdout and "run: go test -race ./..." in proc.stdout


def test_invalid_config_warns_but_works(make_repo):
    root = make_repo("python_app")
    write(root, ".compass/config.yaml", "index: [broken\n")
    proc = run_compass("-C", str(root), "index")
    assert proc.returncode == 0
    assert "warning: config.yaml is not valid YAML" in proc.stderr


def test_python_module_entry_point():
    import subprocess

    proc = subprocess.run([sys.executable, "-m", "compass", "--version"], capture_output=True, text=True)
    assert proc.returncode == 0
