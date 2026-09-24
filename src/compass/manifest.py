"""Change manifests (RO-03): ``.compass/changes/<id>.md``, the page a
reviewer opens instead of reading a whole diff.

A manifest groups a task's anchors into Review, Assumptions, TODO and
Mechanical, each entry a clickable ``path:line — note`` link, then lists the
files the task changed with ``git diff`` counts, calling out any changed file
that carries no anchor. It is generated, never edited: the Stop hook rewrites
it every turn that changes files, and ``compass accept`` archives it under
``changes/archive/`` with line numbers moved to where the code sits once the
anchors are gone.

Links are relative to the manifest, so they open from any editor or Markdown
preview. ``--hosted`` renders links into the repository's web view instead, for
a pull-request description: GitHub and Azure DevOps (NF-16), plus GitLab.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

from compass.anchors import KIND_TITLES, KINDS, Anchor, scan_file, scan_repo
from compass.globs import compile_globs
from compass.repo import Repo, run_git

Linker = Callable[[str, "int | None"], str]


@dataclass
class FileChange:
    path: str
    status: str  # modified | new | deleted
    added: int | None  # None for binary files
    deleted: int | None
    anchors: int = 0
    exempt: bool = False


@dataclass
class Manifest:
    task: str
    branch: str | None
    base: str | None
    anchors: list[Anchor] = field(default_factory=list)
    files: list[FileChange] = field(default_factory=list)
    accepted: bool = False

    @property
    def unanchored(self) -> list[FileChange]:
        return [f for f in self.files if f.anchors == 0 and f.status != "deleted"]

    def counts(self) -> dict[str, int]:
        return {kind: sum(1 for a in self.anchors if a.kind == kind) for kind in KINDS}

    def summary(self) -> str:
        """``2 to review, 1 assumption, 3 mechanical``: one line for chat."""
        c = self.counts()
        parts = [
            f"{c['review']} to review" if c["review"] else "",
            _plural(c["assume"], "assumption") if c["assume"] else "",
            _plural(c["todo"], "todo") if c["todo"] else "",
            f"{c['change']} mechanical" if c["change"] else "",
        ]
        unanchored = [f for f in self.unanchored if not f.exempt]
        if unanchored:
            parts.append(f"{_plural(len(unanchored), 'file')} without anchors")
        return ", ".join(p for p in parts if p) or "no anchors"

    def to_json(self) -> dict:
        return {
            "task": self.task, "branch": self.branch, "base": self.base, "accepted": self.accepted,
            "anchors": [asdict(a) for a in self.anchors], "files": [asdict(f) for f in self.files],
        }

    @classmethod
    def from_json(cls, data: dict) -> Manifest:
        return cls(
            task=data["task"], branch=data.get("branch"), base=data.get("base"), accepted=bool(data.get("accepted")),
            anchors=[Anchor(**a) for a in data.get("anchors", [])],
            files=[FileChange(**f) for f in data.get("files", [])],
        )


def build(repo: Repo, task: str, touched: list[str], exempt: tuple[str, ...] = ()) -> Manifest:
    """The manifest of ``task`` as the working tree stands: its anchors
    anywhere in the repo, plus every file it touched. In an ``exempt`` file
    (JSON and the like, which cannot hold comments) tag-shaped text is data,
    so it is never listed, and so never stripped by accept."""
    is_exempt = compile_globs(exempt)
    anchors = scan_repo(repo.root, task)
    # Files the task touched may be ignored by git, so git grep missed them.
    seen = {(a.path, a.line) for a in anchors}
    for rel in touched:
        for anchor in scan_file(repo.root, rel, task):
            if (anchor.path, anchor.line) not in seen:
                anchors.append(anchor)
    anchors = sorted(a for a in anchors if not is_exempt(a.path))
    paths = sorted(set(touched) | {a.path for a in anchors})
    per_file: dict[str, int] = {}
    for anchor in anchors:
        per_file[anchor.path] = per_file.get(anchor.path, 0) + 1
    files = [
        # A binary file cannot hold a comment either.
        FileChange(path, status, added, deleted, per_file.get(path, 0), bool(is_exempt(path)) or added is None)
        for path, (status, added, deleted) in _diff_stats(repo.root, paths).items()
    ]
    return Manifest(task, _branch(repo.root), _short_head(repo.root), anchors, files)


def manifest_path(repo: Repo, task: str, archived: bool = False) -> Path:
    return (repo.changes_dir / "archive" if archived else repo.changes_dir) / f"{task}.md"


def write(repo: Repo, manifest: Manifest, archived: bool = False) -> Path:
    """Write the Markdown and its JSON twin (what ``--hosted`` renders from)."""
    path = manifest_path(repo, manifest.task, archived)
    path.parent.mkdir(parents=True, exist_ok=True)
    depth = len(path.relative_to(repo.root).parts) - 1
    path.write_text(render(manifest, relative_linker("../" * depth)), encoding="utf-8", newline="\n")
    path.with_suffix(".json").write_text(
        json.dumps(manifest.to_json(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return path


def load(repo: Repo, task: str, archived: bool) -> Manifest | None:
    try:
        data = json.loads(manifest_path(repo, task, archived).with_suffix(".json").read_text(encoding="utf-8"))
        return Manifest.from_json(data)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def render(manifest: Manifest, link: Linker) -> str:
    m = manifest
    added = sum(f.added or 0 for f in m.files)
    deleted = sum(f.deleted or 0 for f in m.files)
    where = f"Branch `{m.branch}`" if m.branch else "Detached HEAD"
    where += f" at `{m.base}`" if m.base else " (no commits yet)"
    state = "accepted; anchors stripped" if m.accepted else f"{_plural(len(m.anchors), 'anchor')}"
    lines = [
        f"# Change {m.task}",
        "",
        f"{where} · {_plural(len(m.files), 'file')}, +{added} −{deleted} · {state}",
        "",
    ]
    if not m.accepted:
        lines += [
            "Read **Review** and **Assumptions** closely, decide on **TODO**, skim **Mechanical**.",
            f"When you are done, `/compass:accept {m.task}` strips the anchors and archives this page.",
            "",
        ]
    if not m.anchors and not m.files:
        lines += [f"No changes recorded for {m.task} yet.", ""]
    for kind in KINDS:
        entries = [a for a in m.anchors if a.kind == kind]
        if entries:
            lines += [f"## {KIND_TITLES[kind]} ({len(entries)})", ""]
            lines += [f"- [{a.path}:{a.line}]({link(a.path, a.line)})" + (f" — {a.note}" if a.note else "") for a in entries]
            lines.append("")
    unanchored = m.unanchored
    if unanchored and not m.accepted:
        lines += [f"## Changed without anchors ({len(unanchored)})", ""]
        for f in unanchored:
            why = " (exempt: cannot hold comments)" if f.exempt else ""
            lines.append(f"- [{f.path}]({link(f.path, None)}){why}")
        lines.append("")
    if m.files:
        lines += ["## Files", "", "| File | Change | + | − | Anchors |", "| --- | --- | --- | --- | --- |"]
        for f in m.files:
            plus = "binary" if f.added is None else str(f.added)
            minus = "" if f.deleted is None else str(f.deleted)
            lines.append(f"| [{_cell(f.path)}]({link(f.path, None)}) | {f.status} | {plus} | {minus} | {f.anchors} |")
        lines.append("")
    return "\n".join(lines)


def relative_linker(up: str) -> Linker:
    def link(path: str, line: int | None) -> str:
        return up + quote(path) + (f"#L{line}" if line else "")

    return link


# -- git ------------------------------------------------------------------------


def _diff_stats(root: Path, paths: list[str]) -> dict[str, tuple[str, int | None, int | None]]:
    """(status, added, deleted) per path, against HEAD; new files count every line."""
    if not paths:
        return {}
    stats: dict[str, tuple[str, int | None, int | None]] = {}
    has_head = run_git(root, "rev-parse", "--verify", "-q", "HEAD").returncode == 0
    tracked: set[str] = set()
    if has_head:
        proc = run_git(root, "diff", "HEAD", "--numstat", "-z", "--no-renames", "--no-color", "--", *paths)
        for record in proc.stdout.split(b"\0"):
            parts = record.decode("utf-8", "surrogateescape").split("\t", 2)
            if len(parts) != 3:
                continue
            added, deleted, path = parts
            stats[path] = (
                "deleted" if not (root / path).exists() else "modified",
                None if added == "-" else int(added),
                None if deleted == "-" else int(deleted),
            )
        listed = run_git(root, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", *paths)
        tracked = set(listed.stdout.decode("utf-8", "surrogateescape").split("\0")) - {""}
    for path in paths:
        if path in stats:
            continue
        full = root / path
        if not full.exists():
            continue  # touched, then deleted before it was ever committed
        if path in tracked:
            continue  # changed and changed back: nothing to review
        try:
            data = full.read_bytes()
        except OSError:
            continue
        lines = None if b"\0" in data[:8192] else data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)
        stats[path] = ("new", lines, 0 if lines is not None else None)
    return dict(sorted(stats.items()))


def net_changed(root: Path, paths: list[str]) -> list[str]:
    """The ``paths`` that differ from HEAD (or are new), in order."""
    if run_git(root, "rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        return list(paths)
    diff = run_git(root, "diff", "HEAD", "--name-only", "-z", "--no-renames", "--", *paths)
    untracked = run_git(root, "ls-files", "-z", "--others", "--exclude-standard", "--", *paths)
    changed = set((diff.stdout + b"\0" + untracked.stdout).decode("utf-8", "surrogateescape").split("\0")) - {""}
    return [p for p in paths if p in changed]


def _branch(root: Path) -> str | None:
    proc = run_git(root, "symbolic-ref", "--short", "-q", "HEAD")
    return proc.stdout.decode("utf-8", "replace").strip() or None if proc.returncode == 0 else None


def _short_head(root: Path) -> str | None:
    proc = run_git(root, "rev-parse", "--short", "--verify", "-q", "HEAD")
    return proc.stdout.decode("utf-8", "replace").strip() or None if proc.returncode == 0 else None


# -- hosted links (NF-16) ----------------------------------------------------------


@dataclass(frozen=True)
class Hosted:
    kind: str  # github | azure | gitlab
    web: str  # the repository's web URL, without credentials

    def file_url(self, ref: str, path: str, line: int | None, commit: bool = False) -> str:
        if self.kind == "azure":
            version = ("GC" if commit else "GB") + quote(ref, safe="")
            url = f"{self.web}?path=/{quote(path)}&version={version}"
            if line:
                url += f"&line={line}&lineEnd={line}&lineStartColumn=1&lineEndColumn=1&lineStyle=plain"
            return url + "&_a=contents"
        middle = "/-/blob/" if self.kind == "gitlab" else "/blob/"
        return f"{self.web}{middle}{quote(ref)}/{quote(path)}" + (f"#L{line}" if line else "")


def hosted(root: Path) -> Hosted | None:
    """The hosting service behind ``origin`` (or the only remote)."""
    proc = run_git(root, "remote", "get-url", "origin")
    if proc.returncode != 0:
        remotes = run_git(root, "remote").stdout.decode("utf-8", "replace").split()
        if len(remotes) != 1:
            return None
        proc = run_git(root, "remote", "get-url", remotes[0])
    return parse_remote(proc.stdout.decode("utf-8", "replace").strip())


def parse_remote(url: str) -> Hosted | None:
    """GitHub, Azure DevOps (dev.azure.com and legacy visualstudio.com) or
    GitLab, from any https, ssh or scp-style remote URL. Credentials in the
    URL are dropped."""
    if not url:
        return None
    scp = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):(?!//)(.+)", url)
    if scp and "://" not in url:
        host, path = scp.group(1), scp.group(2)
    else:
        parts = urlsplit(url)
        if not parts.hostname:
            return None
        host, path = parts.hostname, parts.path
    host = host.lower()
    path = path.strip("/").removesuffix(".git")
    segments = [s for s in path.split("/") if s]
    if host in ("ssh.dev.azure.com", "vs-ssh.visualstudio.com") and len(segments) == 4 and segments[0] == "v3":
        org, project, name = segments[1:]
        return Hosted("azure", f"https://dev.azure.com/{org}/{project}/_git/{name}")
    if host == "dev.azure.com" and len(segments) == 4 and segments[2] == "_git":
        org, project, _, name = segments
        return Hosted("azure", f"https://dev.azure.com/{org}/{project}/_git/{name}")
    if host.endswith(".visualstudio.com") and "_git" in segments:
        at = segments.index("_git")
        if at + 1 < len(segments) and at >= 1:
            org = host.split(".", 1)[0]
            project = segments[at - 1]
            return Hosted("azure", f"https://{org}.visualstudio.com/{project}/_git/{segments[at + 1]}")
    if len(segments) >= 2 and (host == "github.com" or host.startswith("github.")):
        return Hosted("github", f"https://{host}/{segments[0]}/{segments[1]}")
    if len(segments) >= 2 and (host == "gitlab.com" or host.startswith("gitlab.")):
        return Hosted("gitlab", f"https://{host}/{'/'.join(segments)}")
    return None


def hosted_linker(root: Path, ref: str | None) -> tuple[Linker, str] | None:
    """A linker into the web view at ``ref`` (default: the current branch, or
    the commit when HEAD is detached), and the ref it links to."""
    service = hosted(root)
    if service is None:
        return None
    commit = False
    if ref is None:
        ref = _branch(root)
        if ref is None:
            proc = run_git(root, "rev-parse", "--verify", "-q", "HEAD")
            ref = proc.stdout.decode("utf-8", "replace").strip()
            commit = True
        if not ref:
            return None

    def link(path: str, line: int | None) -> str:
        return service.file_url(ref, path, line, commit)

    return link, ref


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")
