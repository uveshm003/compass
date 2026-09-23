"""Python: pyproject.toml, setup.cfg/setup.py, requirements*.txt, Pipfile, and
uv / Poetry / PDM / Pipenv lockfiles for installed versions."""

from __future__ import annotations

import posixpath
import re

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir, pick_versions, run_in

FRAMEWORKS = {
    "aiohttp", "alembic", "celery", "click", "dash", "django", "djangorestframework", "fastapi",
    "flask", "httpx", "jax", "langchain", "numpy", "pandas", "polars", "pydantic", "pyside6",
    "requests", "scikit-learn", "scipy", "sqlalchemy", "starlette", "streamlit", "tensorflow",
    "torch", "transformers", "typer",
}
TOOLS = {
    "black", "coverage", "flake8", "hypothesis", "isort", "mypy", "nox", "pre-commit", "pylint",
    "pyright", "pytest", "ruff", "tox",
}
MANIFESTS = ("pyproject.toml", "setup.cfg", "setup.py", "Pipfile")
LOCKFILES = [("uv.lock", "uv"), ("poetry.lock", "poetry"), ("pdm.lock", "pdm"), ("Pipfile.lock", "pipenv")]
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(==\s*([^\s;,#]+))?")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def detect(repo: StackRepo) -> dict | None:
    dirs: dict[str, None] = {}
    for path in repo.find(*MANIFESTS) + [p for p in repo.files if _is_requirements(p)]:
        dirs.setdefault(posixpath.dirname(path), None)
    if not dirs:
        return None
    ordered = sorted(dirs, key=lambda d: (d.count("/") + (d != ""), d))
    packages = [p for p in (_package(repo, d) for d in ordered[:MAX_PACKAGES]) if p]
    if not packages:
        return None
    out: dict = {"packages": packages}
    if len(ordered) > MAX_PACKAGES:
        out["more_packages"] = len(ordered) - MAX_PACKAGES
    return out


def _is_requirements(path: str) -> bool:
    name = posixpath.basename(path)
    return name.startswith("requirements") and name.endswith((".txt", ".in"))


def _package(repo: StackRepo, base: str) -> dict | None:
    pyproject = repo.read_toml(in_dir(base, "pyproject.toml")) or {}
    project = pyproject.get("project") if isinstance(pyproject.get("project"), dict) else {}
    tool = pyproject.get("tool") if isinstance(pyproject.get("tool"), dict) else {}
    poetry = tool.get("poetry") if isinstance(tool.get("poetry"), dict) else {}

    declared: dict[str, str] = {}
    for spec in _strings(project.get("dependencies")):
        _add(declared, spec)
    for group in (project.get("optional-dependencies") or {}).values():
        for spec in _strings(group):
            _add(declared, spec)
    for group in (pyproject.get("dependency-groups") or {}).values():
        for spec in _strings(group):
            _add(declared, spec)
    for spec in _strings((tool.get("uv") or {}).get("dev-dependencies")):
        _add(declared, spec)
    for table in [poetry.get("dependencies"), poetry.get("dev-dependencies")] + [
        (g or {}).get("dependencies") for g in (poetry.get("group") or {}).values() if isinstance(g, dict)
    ]:
        if isinstance(table, dict):
            for name, value in table.items():
                if normalize(name) != "python":
                    declared.setdefault(normalize(name), _poetry_version(value))
    for path in [p for p in repo.files if posixpath.dirname(p) == base and _is_requirements(p)]:
        for line in (repo.read_text(path) or "").splitlines():
            if not line.strip().startswith(("#", "-")):
                _add(declared, line)

    runner, lockfile = None, None
    for directory in dict.fromkeys([base, ""]):
        for filename, name in LOCKFILES:
            if repo.exists(in_dir(directory, filename)):
                runner, lockfile = name, in_dir(directory, filename)
                break
        if lockfile:
            break
    if runner is None and poetry:
        runner = "poetry"
    resolved = _lock_versions(repo, lockfile) if lockfile else {}
    versions = {name: resolved.get(name, spec) for name, spec in declared.items()}

    tools = pick_versions(versions, TOOLS)
    for name, present in _configured_tools(repo, base, tool).items():
        if present:
            tools.setdefault(name, "")
    requires_python = project.get("requires-python") or (poetry.get("dependencies") or {}).get("python")
    if not (pyproject or declared or repo.exists(in_dir(base, "setup.py"))):
        return None
    path = next(
        (in_dir(base, m) for m in MANIFESTS if repo.exists(in_dir(base, m))),
        in_dir(base, "requirements.txt"),
    )
    return compact(
        {
            "path": path,
            "name": project.get("name") or poetry.get("name"),
            "requires_python": requires_python,
            "runner": runner,
            "lockfile": lockfile,
            "build_backend": (pyproject.get("build-system") or {}).get("build-backend"),
            "frameworks": pick_versions(versions, FRAMEWORKS),
            "tools": dict(sorted(tools.items())),
            "dependencies": len(declared),
            "commands": _commands(tools, runner, base, bool(pyproject.get("build-system"))),
        }
    )


def _poetry_version(value: object) -> str:
    """Poetry allows "^1.2", {version = "^1.2", ...}, or a list of such tables
    for per-platform constraints."""
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, (str, dict))), "")
    if isinstance(value, dict):
        value = value.get("version", "")
    return str(value) if isinstance(value, (str, int, float)) else ""


def _strings(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _add(declared: dict[str, str], spec: str) -> None:
    """Record a PEP 508 requirement: the pinned version, else its specifier."""
    spec = spec.split(";", 1)[0].split("#", 1)[0].strip()
    if not spec or "://" in spec:
        return
    m = _REQ_NAME.match(spec)
    if m:
        declared.setdefault(normalize(m.group(1)), m.group(4) or spec[m.end() :].strip())


def _configured_tools(repo: StackRepo, base: str, tool: dict) -> dict[str, bool]:
    def has(*names: str) -> bool:
        return any(repo.exists(in_dir(base, n)) for n in names)

    return {
        "pytest": "pytest" in tool or has("pytest.ini", "conftest.py", "tests/conftest.py"),
        "ruff": "ruff" in tool or has("ruff.toml", ".ruff.toml"),
        "black": "black" in tool,
        "mypy": "mypy" in tool or has("mypy.ini", ".mypy.ini"),
        "pyright": "pyright" in tool or has("pyrightconfig.json"),
        "flake8": has(".flake8"),
        "isort": "isort" in tool or has(".isort.cfg"),
        "tox": has("tox.ini"),
        "nox": has("noxfile.py"),
        "pre-commit": has(".pre-commit-config.yaml"),
    }


def _commands(tools: dict[str, str], runner: str | None, base: str, buildable: bool) -> dict[str, str]:
    prefix = f"{runner} run " if runner in ("uv", "poetry", "pdm", "pipenv") else ""
    out = {}
    if "pytest" in tools:
        out["test"] = f"{prefix}pytest"
    elif "tox" in tools:
        out["test"] = "tox"
    if "ruff" in tools:
        out["lint"] = f"{prefix}ruff check ."
        out["format"] = f"{prefix}ruff format ."
    elif "flake8" in tools:
        out["lint"] = f"{prefix}flake8"
    if "black" in tools and "format" not in out:
        out["format"] = f"{prefix}black ."
    if "mypy" in tools:
        out["typecheck"] = f"{prefix}mypy ."
    elif "pyright" in tools:
        out["typecheck"] = f"{prefix}pyright"
    if buildable:
        out["build"] = {"uv": "uv build", "poetry": "poetry build", "pdm": "pdm build"}.get(runner, "python -m build")
    return {role: run_in(base, cmd) for role, cmd in out.items()}


def _lock_versions(repo: StackRepo, lockfile: str) -> dict[str, str]:
    if lockfile.endswith("Pipfile.lock"):
        data = repo.read_json(lockfile) or {}
        out = {}
        for section in ("default", "develop"):
            for name, entry in (data.get(section) or {}).items():
                if isinstance(entry, dict) and isinstance(entry.get("version"), str):
                    out.setdefault(normalize(name), entry["version"].lstrip("="))
        return out
    data = repo.read_toml(lockfile) or {}
    out = {}
    for entry in data.get("package") or []:
        if isinstance(entry, dict) and "name" in entry and "version" in entry:
            out.setdefault(normalize(str(entry["name"])), str(entry["version"]))
    return out
