"""Calibrate the probe activity score: how often does an empty-but-noisy room look active?

Simulates a stable series (same room, new noise realisations) and an activity series
(door open/closed alternation) and derives an activity threshold with a stated false-positive
rate. Writes cache/activity_calibration.json, which probe.check() reads.
"""
import json
import os

import numpy as np

import acoustics as ac
import probe

OUT = os.path.join(os.path.dirname(__file__), "cache", "activity_calibration.json")
sweep = probe.probe_sweep()
room = ac.default_room()


def rec_for(rt, seed):
    rir = ac.simulate_treated_rir(room, {"predicted_rt60_s": rt}, rt, fs=probe.FS)
    rec = np.convolve(rir, sweep)[: len(rir) + len(sweep)]
    rec = rec / max(np.max(np.abs(rec)), 1e-9) * 0.5
    return rec + np.random.default_rng(seed).normal(0, 2e-3, len(rec))


def series(room_id, rt_sequence, seed0):
    scores = []
    for i, rt in enumerate(rt_sequence):
        r = probe.check(room_id, rec_for(rt, seed0 + i))
        scores.append((r["activity_score"], r["status"], r["unusual_activity"]))
    return scores


def main():
    probe.STATE_PATH.unlink(missing_ok=True)
    probe.enroll("calib", "Calibration room", [rec_for(0.8, s) for s in (0, 1, 2)])

    stable = series("calib", [0.8] * 14, seed0=100)
    active = series("calib", [0.8, 0.55] * 7, seed0=300)

    warm_stable = [s for s, _, _ in stable[3:]]
    warm_active = [s for s, _, _ in active[3:]]
    p95 = float(np.percentile(warm_stable, 95))
    threshold = max(round(p95 + 0.02, 2), 0.20)
    far = float(np.mean([s >= threshold for s in warm_stable]))
    tpr = float(np.mean([s >= threshold for s in warm_active]))
    result = {
        "threshold": threshold,
        "false_positive_rate": round(far, 3),
        "true_positive_rate": round(tpr, 3),
        "stable_scores": [round(s, 2) for s, _, _ in stable],
        "activity_scores": [round(s, 2) for s, _, _ in active],
        "n_stable": len(warm_stable),
        "n_active": len(warm_active),
    }
    json.dump(result, open(OUT, "w"), indent=1)
    print(json.dumps({k: result[k] for k in ("threshold", "false_positive_rate",
                                             "true_positive_rate", "n_stable", "n_active")}, indent=1))
    print("stable scores :", result["stable_scores"])
    print("activity scores:", result["activity_scores"])


if __name__ == "__main__":
    main()
