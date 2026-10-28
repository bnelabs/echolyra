"""Held-out validation of calibration profiles on real recordings.

Splits the real-world rows per class into fit (60%) and validation (40%), fits profiles on
fit data only, and scores them on the held-out rows -> honest numbers for docs.
"""
import json
import os

import calibration as cal

REAL_PATH = os.environ.get("REAL_EVAL_JSON", "/tmp/realsounds/real_eval_final.json")
SYNTH_PATH = os.path.join(os.path.dirname(__file__), "cache", "synth_rows.json")


def load_real():
    rows = json.load(open(REAL_PATH))
    converted = []
    for r in rows:
        converted.append({"true": r["true"], "event_conf": float(r.get("conf", 0.0)),
                          "event_correct": int(r.get("correct", 0)),
                          "event_claimed": int(r.get("label") not in (None, "unknown")),
                          "event_label": r.get("label", "unknown"),
                          "snr": float(r.get("snr", 30.0))})
    return converted


def split(rows):
    by_class = {}
    for r in rows:
        by_class.setdefault(r["true"], []).append(r)
    fit, val = [], []
    for cls, items in by_class.items():
        k = max(1, int(round(len(items) * 0.6)))
        fit += items[:k]
        val += items[k:]
    return fit, val


def rows_for_fit(rows):
    return [{"event_conf": r["event_conf"], "event_correct": r["event_correct"],
             "event_claimed": r["event_claimed"], "event_label": r["event_label"]} for r in rows]


def score_on(profile_params, val_rows):
    stats = cal.evaluate_profile(profile_params, rows_for_fit(val_rows))
    # decision-level behaviour on held-out rows (no temporal confirmation here)
    decisions = {"alert": 0, "explain": 0, "silent": 0}
    wrong_alerts = correct_alerts = 0
    for r in val_rows:
        d = cal.decide(r["event_conf"], 1.0, r["snr"], profile_params, event_label=r["event_label"])
        decisions[d["decision"]] += 1
        if d["decision"] == "alert":
            if r["event_correct"]:
                correct_alerts += 1
            else:
                wrong_alerts += 1
    stats["decisions"] = decisions
    stats["wrong_alerts"] = wrong_alerts
    stats["alert_precision"] = round(correct_alerts / max(1, correct_alerts + wrong_alerts), 3)
    return stats


def main():
    real = load_real()
    fit, val = split(real)
    synth = json.load(open(SYNTH_PATH)) if os.path.exists(SYNTH_PATH) else []
    profiles = {
        "synthetic": synth,
        "real-fit": rows_for_fit(fit),
        "hybrid-fit": synth + rows_for_fit(fit),
    }
    out = {"n_real": len(real), "n_fit": len(fit), "n_val": len(val), "profiles": {}}
    for name, rows in profiles.items():
        params = cal.fit_profile(rows, name=f"holdout_{name}")
        stats = score_on(params, val)
        out["profiles"][name] = {"fit_rows": len(rows), **stats,
                                 "operating_point": params.get("operating_point")}
    json.dump(out, open("cache/calibration_holdout.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
