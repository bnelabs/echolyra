#!/usr/bin/env python3
"""Check that every relative link / image path in the tracked Markdown docs resolves.

Run: python3 tools/check_links.py   (exits 1 on any broken path)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
FENCE_RE = re.compile(r"```.*?```", re.S)
EXTERNAL = ("http://", "https://", "mailto:", "#")


def main() -> int:
    files = [Path(p) for p in subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        if p.strip()]
    broken: list[str] = []
    checked = 0
    for rel in files:
        path = ROOT / rel
        text = FENCE_RE.sub("", path.read_text())
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip().strip("<>")
            if target.startswith(EXTERNAL) or not target:
                continue
            target_path = target.split("#")[0]
            if not target_path:
                continue
            resolved = (path.parent / target_path).resolve()
            checked += 1
            if not resolved.exists():
                broken.append(f"{rel}: {target} -> missing {resolved.relative_to(ROOT) if str(resolved).startswith(str(ROOT)) else resolved}")
    print(f"checked {checked} relative links/images across {len(files)} Markdown files")
    for b in broken:
        print(f"BROKEN  {b}")
    if broken:
        print(f"\n{len(broken)} broken link(s)")
        return 1
    print("\nPASS — all relative doc links and image paths resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
