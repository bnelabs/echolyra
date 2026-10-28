#!/usr/bin/env python3
"""Cross-check the headline numbers quoted in docs against the cached measurements.

Motivated by round 17, where a filename-collision bug inflated an external benchmark.
Run: python3 tools/audit_numbers.py  (from sprint/)
Exits non-zero on any mismatch.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text())


def dig(data: dict, path: str):
    cur = data
    for part in path.split("."):
        cur = cur[part]
    return cur


# (json file, json path, expected value, doc file, exact string that must appear in doc)
CHECKS = [
    ("docs/eval_external.json", "accuracy", 0.90, "docs/EVAL_REAL.md", "0.900"),
    ("docs/eval_external.json", "ece_after", 0.029, "docs/EVAL_REAL.md", "0.0290"),
    ("docs/eval_external.json", "alert_precision", 0.893, "docs/EVAL_REAL.md", "0.893"),
    ("docs/eval_external.json", "n", 60, "docs/EVAL_REAL.md", "n=60 unique"),
    ("docs/measurements/calibration_holdout.json", "profiles.hybrid-fit.ece_after", 0.0166,
     "docs/CALIBRATION.md", "0.0166"),
    ("docs/measurements/activity_calibration.json", "threshold", 0.2, "docs/FRONTIER.md", "0.20"),
    ("docs/eval_external.json", "accuracy", 0.90, "README.md", "90%"),
]

# phrases/figures that must not appear in current-facing docs (stale or retracted claims)
STALE = [
    ("docs/FRONTIER.md", "0.833", "round-16 pre-correction external accuracy"),
    ("docs/FRONTIER.md", "0.0345", "round-16 pre-correction external ECE"),
    ("docs/FRONTIER.md", "zero wrong alerts) |", "retracted external zero-wrong-alert claim"),
    ("docs/EVAL_REAL.md", "0.833", "pre-correction external accuracy"),
]

# whole-file sanity
REQUIRED_PASSES = [
    ("docs/VERIFY.md", "external validation (unseen real clips)"),
    ("docs/VERIFY.md", "all runnable checks passed"),
    ("docs/VERIFY.md", "repo flip-readiness"),
]


def main() -> int:
    failures = []
    for json_file, path, expected, doc, needle in CHECKS:
        try:
            actual = dig(load(json_file), path)
        except Exception as exc:
            failures.append(f"{json_file}:{path} unreadable ({exc})")
            continue
        if isinstance(expected, float):
            ok_value = abs(float(actual) - expected) <= max(0.0006, abs(expected) * 0.01)
        else:
            ok_value = actual == expected
        text = (ROOT / doc).read_text()
        if not ok_value:
            failures.append(f"{json_file}:{path} = {actual}, expected {expected}")
        if needle not in text:
            failures.append(f"{doc} missing current figure {needle!r}")
    for doc, phrase, why in STALE:
        if phrase in (ROOT / doc).read_text():
            failures.append(f"{doc} still contains stale figure {phrase!r} ({why})")
    for doc, phrase in REQUIRED_PASSES:
        text = (ROOT / doc).read_text() if (ROOT / doc).exists() else ""
        if phrase not in text:
            failures.append(f"{doc} missing verification evidence: {phrase!r}")
    passes = sum(1 for _ in re.finditer(r"\[PASS\]", (ROOT / "docs/VERIFY.md").read_text()))
    if passes < 8:
        failures.append(f"docs/VERIFY.md reports only {passes} PASS checks (expected >= 8)")

    print(f"audited {len(CHECKS)} canonical figures + {len(STALE)} stale patterns + {len(REQUIRED_PASSES)} verifier markers")
    for f in failures:
        print(f"FAIL  {f}")
    if failures:
        print(f"\n{len(failures)} number/doc mismatch(es)")
        return 1
    print("\nPASS — every quoted number matches the cached measurements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
