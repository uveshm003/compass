"""Dockerfiles: the runtime images a service actually ships on."""

from __future__ import annotations

import posixpath
import re

from compass.stack import StackRepo, compact

_FROM = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", re.IGNORECASE | re.MULTILINE)


def _is_dockerfile(path: str) -> bool:
    name = posixpath.basename(path)
    return name == "Dockerfile" or name.startswith("Dockerfile.") or name.endswith(".Dockerfile")


def detect(repo: StackRepo) -> dict | None:
    files = sorted((p for p in repo.files if _is_dockerfile(p)), key=lambda p: (p.count("/"), p))
    if not files:
        return None
    images: set[str] = set()
    for path in files[:10]:
        stages = set()
        for image, stage in _FROM.findall(repo.read_text(path) or ""):
            if image.lower() != "scratch" and image not in stages and "$" not in image:
                images.add(image)
            if stage:
                stages.add(stage)
    compose = [p for p in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml") if repo.exists(p)]
    return compact({"files": files[:10], "images": sorted(images), "compose": compose})
