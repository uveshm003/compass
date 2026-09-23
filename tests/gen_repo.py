"""Generate a deterministic multi-language repo of a given size, for the
latency checks (NF-01 to NF-04 are all stated against 100k LOC).

    python tests/gen_repo.py /tmp/big-repo 100000
"""

from __future__ import annotations

import sys
from pathlib import Path

LINES_PER_FILE = 125
LANGS = ("python", "typescript", "go", "rust")


def _python(i: int, blocks: int) -> list[str]:
    out = [f'"""Generated module {i} for latency tests."""', "", "import os", "", f"LIMIT_{i} = {i}", "", ""]
    out += [f"class Service{i}:", f'    """Service number {i}."""', ""]
    for j in range(blocks):
        out += [
            f"    def method_{j}(self, value: int) -> int:",
            f'        """Compute step {j}."""',
            "        total = value",
            "        for k in range(10):",
            f"            total += k * {j}",
            "        return total",
            "",
        ]
    return out


def _typescript(i: int, blocks: int) -> list[str]:
    out = [f"// Generated module {i} for latency tests.", "", f"export const LIMIT_{i} = {i};", ""]
    out += [f"/** Service number {i}. */", f"export class Service{i} {{"]
    for j in range(blocks):
        out += [
            f"  /** Compute step {j}. */",
            f"  method{j}(value: number): number {{",
            "    let total = value;",
            f"    for (let k = 0; k < 10; k++) total += k * {j};",
            "    return total;",
            "  }",
            "",
        ]
    return out + ["}"]


def _go(i: int, blocks: int) -> list[str]:
    out = [f"package pkg{i % 50}", "", f"// Limit{i} caps work.", f"const Limit{i} = {i}", ""]
    out += [f"// Service{i} is service number {i}.", f"type Service{i} struct {{", "\tName string", "}", ""]
    for j in range(blocks):
        out += [
            f"// Method{j} computes step {j}.",
            f"func (s *Service{i}) Method{j}(value int) int {{",
            "\ttotal := value",
            f"\tfor k := 0; k < 10; k++ {{ total += k * {j} }}",
            "\treturn total",
            "}",
            "",
        ]
    return out


def _rust(i: int, blocks: int) -> list[str]:
    out = [f"//! Generated module {i} for latency tests.", "", f"pub const LIMIT_{i}: u32 = {i};", ""]
    out += [f"/// Service number {i}.", f"pub struct Service{i} {{", "    pub name: String,", "}", "", f"impl Service{i} {{"]
    for j in range(blocks):
        out += [
            f"    /// Compute step {j}.",
            f"    pub fn method_{j}(&self, value: u64) -> u64 {{",
            "        let mut total = value;",
            f"        for k in 0..10 {{ total += k * {j}; }}",
            "        total",
            "    }",
            "",
        ]
    return out + ["}"]


RENDER = {"python": (_python, "py"), "typescript": (_typescript, "ts"), "go": (_go, "go"), "rust": (_rust, "rs")}


def generate(root: Path, target_loc: int = 100_000) -> int:
    """Write the repo and return its line count."""
    total = 0
    i = 0
    while total < target_loc:
        lang = LANGS[i % len(LANGS)]
        render, ext = RENDER[lang]
        lines = render(i, blocks=(LINES_PER_FILE - 12) // 7)
        path = root / lang / f"area{i % 12}" / f"mod{i // 12}" / f"module_{i}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        total += len(lines)
        i += 1
    return total


if __name__ == "__main__":
    dest = Path(sys.argv[1])
    loc = generate(dest, int(sys.argv[2]) if len(sys.argv) > 2 else 100_000)
    print(f"wrote {loc} lines under {dest}")
