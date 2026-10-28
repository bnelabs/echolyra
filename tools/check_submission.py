#!/usr/bin/env python3
"""Pre-flip / pre-submission hygiene check for the RoomSense repo.

Run from the repo root (the directory containing backend/, ios/, docs/):
    python3 tools/check_submission.py
Exits non-zero if a blocking issue is found.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md", "LICENSE", ".gitignore", "backend/requirements.txt", "run_backend.sh",
    "backend/app.py", "backend/awareness.py", "backend/probe.py", "backend/calibration.py",
    "backend/fusion.py", "backend/meta_models.py", "backend/.env.example",
    "ios/RoomSense/RoomSense.xcodeproj/project.pbxproj",
    "docs/SUBMISSION.md", "docs/EVAL_REAL.md", "docs/CALIBRATION.md", "docs/FRONTIER.md",
    "backend/static/demo.html", "backend/static/node.html",
    "backend/static/demo/labels.json", "tools/check_submission.py",
]
REQUIRED_README = ["Run", "API", "privacy", "Real-world", "calibrat"]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?:api[_-]?key|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{24,}['\"]", re.I),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{24,}"),
]
FORBIDDEN_TRACKED = [re.compile(p) for p in (
    r"(^|/)\.env$", r"(^|/)cache/", r"(^|/)build", r"\.xcresult", r"\.xcuserstate$",
)]
WINDOW = (datetime(2026, 10, 27, tzinfo=timezone.utc), datetime(2026, 11, 5, tzinfo=timezone.utc))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []
    tracked = [p for p in git("ls-files").splitlines() if p.strip()]
    if not tracked:
        return print("not a git repo / no tracked files") or 1

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            failures.append(f"missing required file: {rel}")

    readme = (ROOT / "README.md").read_text() if (ROOT / "README.md").exists() else ""
    for needle in REQUIRED_README:
        if needle.lower() not in readme.lower():
            warnings.append(f"README missing section/keyword: {needle!r}")

    for rel in tracked:
        if any(p.search(rel) for p in FORBIDDEN_TRACKED):
            failures.append(f"forbidden tracked path: {rel}")
        if rel.endswith((".wav", ".mp3", ".m4a")) and "static/demo/" not in rel:
            failures.append(f"audio file committed outside the synthetic demo set: {rel}")
        if rel.endswith((".key", ".pem", ".p12", ".mobileprovision")):
            failures.append(f"credential file tracked: {rel}")

    for rel in tracked:
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        for pat in SECRET_PATTERNS:
            for m in pat.finditer(text):
                if ".env.example" in rel:
                    continue
                failures.append(f"possible secret in {rel}: {m.group(0)[:12]}…")

    dates = []
    for line in git("log", "--format=%ad", "--date=iso-strict").splitlines():
        try:
            dates.append(datetime.fromisoformat(line.strip()))
        except ValueError:
            pass
    if dates:
        if min(dates) < WINDOW[0]:
            warnings.append(f"oldest commit {min(dates).date()} is before the hackathon window")
        if max(dates) > WINDOW[1]:
            warnings.append(f"newest commit {max(dates).date()} is outside the window")

    status = git("status", "--porcelain").strip()
    if status:
        warnings.append("working tree not clean (commit before flipping public)")

    print(f"tracked files: {len(tracked)} | commits: {len(dates)}")
    for w in warnings:
        print(f"WARN  {w}")
    for f in failures:
        print(f"FAIL  {f}")
    if failures:
        print(f"\n{len(failures)} blocking issue(s)")
        return 1
    print("\nPASS — repo is flip-ready (warnings above are advisory)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
