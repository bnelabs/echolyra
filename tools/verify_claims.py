#!/usr/bin/env python3
"""Re-run RoomSense's headline claims in one command.

Usage (from sprint/backend or anywhere):
    ../../prototype/.venv/bin/python tools/verify_claims.py

Synthetic checks run anywhere; real-world checks run when the ESC-50 evaluation dump from
docs/EVAL_REAL.md is present at $REAL_EVAL_JSON (default /tmp/realsounds/real_eval_final.json).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import acoustics as ac          # noqa: E402
import awareness as aw          # noqa: E402
import calibration as cal       # noqa: E402
import fusion                   # noqa: E402
import probe                    # noqa: E402

REAL_JSON = os.environ.get("REAL_EVAL_JSON", "/tmp/realsounds/real_eval_final.json")
results: list[tuple[str, bool | None, str]] = []


def check(name: str, ok: bool | None, detail: str):
    results.append((name, ok, detail))


def probe_rec(rt: float, seed: int) -> np.ndarray:
    room = ac.default_room()
    rir = ac.simulate_treated_rir(room, {"predicted_rt60_s": rt}, rt, fs=probe.FS)
    sweep = probe.probe_sweep()
    rec = np.convolve(rir, sweep)[: len(rir) + len(sweep)]
    rec = rec / max(np.max(np.abs(rec)), 1e-9) * 0.5
    return rec + np.random.default_rng(seed).normal(0, 2e-3, len(rec))


def check_probe_recovery():
    errs = []
    for target in (0.8, 0.6, 0.35):
        a = probe.analyze_probe(probe_rec(target, 0))
        measured = a["rt60_mid_s"]
        ok = a["valid"] and measured is not None and abs(measured - target) / target < 0.10
        errs.append(f"{target:.2f}→{measured:.2f}" if measured else f"{target:.2f}→invalid")
        if not ok:
            check("probe RT60 recovery", False, ", ".join(errs))
            return
    check("probe RT60 recovery", True, ", ".join(errs) + " (all within 10%)")


def check_change_detection():
    probe.STATE_PATH.unlink(missing_ok=True)
    probe.enroll("verify-room", "Verify room", [probe_rec(0.8, s) for s in (0, 1, 2)])
    same = probe.check("verify-room", probe_rec(0.8, 10))
    changed = probe.check("verify-room", probe_rec(0.45, 11))
    ok = same["status"] == "stable" and changed["status"] == "changed"
    check("change detection (stable vs changed)", ok,
          f"same ΔT30 {same['max_t30_change_pct']}% ({same['status']}) / "
          f"changed ΔT30 {changed['max_t30_change_pct']}% ({changed['status']})")


def check_activity():
    series = []
    for i, rt in enumerate([0.8, 0.55] * 5):
        r = probe.check("verify-room", probe_rec(rt, 100 + i))
        series.append(r)
    unusual = sum(1 for r in series if r["unusual_activity"])
    check("activity anomaly detection", unusual >= 2, f"{unusual}/10 alternating probes flagged unusual")


def check_calibration():
    path = BACKEND / "cache" / "calibration_holdout.json"
    if not path.exists():
        check("held-out calibration", None, "cache/calibration_holdout.json missing (run tools_validate_calibration.py)")
        return
    d = json.load(open(path))
    hybrid = d["profiles"].get("hybrid-fit")
    ok = bool(hybrid and hybrid["ece_after"] < 0.03 and hybrid["accepted_precision"] >= 0.90)
    check("held-out calibration (hybrid)", ok,
          f"ECE {hybrid['ece_before']}→{hybrid['ece_after']}, precision {hybrid['accepted_precision']} "
          f"(fit {d['n_fit']} / val {d['n_val']})" if hybrid else "missing")


def check_decision_policy():
    params = cal.load_params("hybrid")
    cases = [
        (cal.decide(0.95, 0.9, 35, params, "glass_impact"), "alert", "high conf + room"),
        (cal.decide(0.95, 0.2, 35, params, "glass_impact"), ("explain", "silent"), "uncertain room"),
        (cal.decide(0.95, 0.9, 5, params, "glass_impact"), "silent", "low SNR"),
    ]
    ok = all((d["decision"] == expected) if isinstance(expected, str)
             else (d["decision"] in expected) for d, expected, _ in cases)
    check("decision policy (alert/explain/silent)", ok,
          "; ".join(f"{label}: {d['decision']}" for d, _, label in cases))


def check_fusion():
    import time
    now = time.time()
    reports = [
        {"node_id": "phone", "room_name": "Living", "room_confidence": 0.6,
         "event_label": "glass_impact", "event_confidence": 0.9, "level_db": -20,
         "snr_db": 34, "event_decay": 130.0, "ts": now},
        {"node_id": "mac", "room_name": "Kitchen", "room_confidence": 0.7,
         "event_label": "glass_impact", "event_confidence": 0.85, "level_db": -31,
         "snr_db": 27, "event_decay": 128.0, "ts": now},
    ]
    out = fusion.fuse(reports, room_probe={"Living": 0.46, "Kitchen": 0.22})
    ok = out["room_name"] == "Living" and out["n_nodes"] == 2
    check("two-node fusion", ok,
          f"{out['event_label']} · {out['room_name']} {out['confidence']} "
          f"posteriors {out['room_posteriors']}")


def check_real_world():
    if not os.path.exists(REAL_JSON):
        check("real-world event accuracy", None, f"{REAL_JSON} not present (evaluation-only ESC-50 dump)")
        return
    rows = json.load(open(REAL_JSON))
    acc = sum(1 for r in rows if r.get("correct")) / max(1, len(rows))
    check("real-world event accuracy", acc >= 0.85, f"{acc:.3f} on {len(rows)} real recordings (expected 0.92)")


def check_external():
    path = Path(__file__).resolve().parents[1] / "docs" / "eval_external.json"
    if not path.exists():
        check("external validation (unseen real clips)", None, "docs/eval_external.json missing")
        return
    d = json.load(open(path))
    ok = d.get("accuracy", 0) >= 0.85 and d.get("ece_after", 1) < 0.05
    check("external validation (unseen real clips)", ok,
          f"accuracy {d.get('accuracy')} on {d.get('n')} unseen clips, "
          f"ECE {d.get('ece_before')}→{d.get('ece_after')}, alert precision {d.get('alert_precision')}")


def check_hygiene():
    import subprocess
    script = Path(__file__).resolve().parent / "check_submission.py"
    out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
    check("repo flip-readiness", out.returncode == 0,
          (out.stdout.strip().splitlines() or ["no output"])[-1])


def main():
    check_probe_recovery()
    check_change_detection()
    check_activity()
    check_calibration()
    check_decision_policy()
    check_fusion()
    check_real_world()
    check_external()
    check_hygiene()

    print("\nRoomSense claim verification\n" + "=" * 30)
    failed = 0
    for name, ok, detail in results:
        tag = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        failed += int(ok is False)
        print(f"[{tag}] {name}: {detail}")
    print("=" * 30)
    if failed:
        print(f"{failed} check(s) FAILED")
        return 1
    print("all runnable checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
