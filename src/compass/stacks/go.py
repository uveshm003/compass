"""Go: go.mod (versions are exact there) and go.work."""

from __future__ import annotations

import posixpath
import re

from compass.stack import MAX_PACKAGES, StackRepo, compact, in_dir, run_in

FRAMEWORKS = {
    "entgo.io/ent", "github.com/gin-gonic/gin", "github.com/go-chi/chi", "github.com/gofiber/fiber",
    "github.com/gorilla/mux", "github.com/jackc/pgx", "github.com/labstack/echo",
    "github.com/sirupsen/logrus", "github.com/spf13/cobra", "github.com/stretchr/testify",
    "go.uber.org/zap", "google.golang.org/grpc", "gorm.io/gorm", "k8s.io/client-go",
}
GOLANGCI = (".golangci.yml", ".golangci.yaml", ".golangci.toml", ".golangci.json")
_REQUIRE = re.compile(r"^\s*([^\s()]+)\s+(v[^\s]+)(\s*//\s*indirect)?")


def detect(repo: StackRepo) -> dict | None:
    mods = repo.find("go.mod")
    if not mods:
        return None
    modules = [_module(repo, path) for path in mods[:MAX_PACKAGES]]
    out: dict = {"modules": [m for m in modules if m]}
    work = repo.read_text("go.work")
    if work:
        out["workspace"] = sorted(set(re.findall(r"^\s*(?:use\s+)?(\./[^\s)]*|\.)\s*$", work, re.MULTILINE)))
    if len(mods) > MAX_PACKAGES:
        out["more_modules"] = len(mods) - MAX_PACKAGES
    return compact(out) or None


def _module(repo: StackRepo, path: str) -> dict | None:
    text = repo.read_text(path)
    if text is None:
        return None
    base = posixpath.dirname(path)
    module = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
    go = re.search(r"^go\s+(\S+)", text, re.MULTILINE)
    toolchain = re.search(r"^toolchain\s+(\S+)", text, re.MULTILINE)
    requires: dict[str, str] = {}
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("require ("):
            in_block = True
            continue
        if in_block and stripped == ")":
            in_block = False
            continue
        target = stripped[len("require ") :] if stripped.startswith("require ") else stripped if in_block else None
        if target is None:
            continue
        m = _REQUIRE.match(target)
        if m and not m.group(3):
            requires[m.group(1)] = m.group(2)
    frameworks = {name: version for name, version in sorted(requires.items()) if _base_path(name) in FRAMEWORKS}
    lint = "golangci-lint run" if any(repo.exists(in_dir(base, f)) or repo.exists(f) for f in GOLANGCI) else "go vet ./..."
    return compact(
        {
            "path": path,
            "name": module.group(1) if module else None,
            "go": go.group(1) if go else None,
            "toolchain": toolchain.group(1) if toolchain else None,
            "frameworks": frameworks,
            "dependencies": len(requires),
            "commands": {
                "build": run_in(base, "go build ./..."),
                "test": run_in(base, "go test ./..."),
                "lint": run_in(base, lint),
            },
        }
    )


def _base_path(module: str) -> str:
    """github.com/labstack/echo/v4 -> github.com/labstack/echo"""
    return re.sub(r"/v\d+$", "", module)
