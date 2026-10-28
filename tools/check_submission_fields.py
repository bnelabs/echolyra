#!/usr/bin/env python3
"""Pre-submission completeness check for docs/SUBMISSION.md and the video/demo links.

Placeholders are expected until recording day; this script tells you exactly what is still
missing so the form can be submitted in one pass.
Run: python3 tools/check_submission_fields.py   (exits 1 while placeholders remain)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "SUBMISSION.md"

REQUIRED_SECTIONS = [
    "Identity", "100-word blurb", "Meta models in the live path",
    "What was built during the hackathon", "Numbers to put on screen",
    "Rubric mapping", "Submission form — paste-ready fields",
    "Submission checklist", "Honest limitations",
]
REQUIRED_FIELDS = ["Project name", "Tagline", "Track", "Repo", "Demo video", "Models used",
                   "New-work disclosure", "License", "Team"]
PLACEHOLDER_PATTERNS = [
    (re.compile(r"<fill[^>]*>", re.I), "unfilled video/link field"),
    (re.compile(r"<mac-ip>"), "demo URL still uses the LAN placeholder"),
    (re.compile(r"`<fill after recording>`"), "demo video URL not set"),
]


def main() -> int:
    text = DOC.read_text() if DOC.exists() else ""
    problems: list[str] = []
    if not text:
        return print("FAIL missing docs/SUBMISSION.md") or 1
    for section in REQUIRED_SECTIONS:
        if section.lower() not in text.lower():
            problems.append(f"missing section: {section}")
    for field in REQUIRED_FIELDS:
        if field.lower() not in text.lower():
            problems.append(f"missing form field: {field}")
    for pat, why in PLACEHOLDER_PATTERNS:
        for m in pat.finditer(text):
            problems.append(f"{why}: {m.group(0)[:40]}")
    open_checks = len(re.findall(r"- \[ \]", text))
    pending_checks = open_checks
    print(f"submission doc: {len(text)} chars | open checklist items: {open_checks}")
    for p in problems:
        print(f"PENDING  {p}")
    if problems:
        print(f"\n{len(problems)} placeholder(s) remaining — expected until recording/upload day"
              if problems else "")
        return 1
    print("\nPASS — submission docs complete (video URL and checklist may still need filling)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
