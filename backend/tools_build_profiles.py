"""Build calibration profiles: synthetic, real-world (ESC-50 eval), and hybrid."""
import json
import os
import sys

import calibration as cal

REAL_PATH = os.environ.get("REAL_EVAL_JSON", "/tmp/realsounds/real_eval_final.json")


def main():
    synth = cal.collect_labelled(n_trials=2)
    synth_rows = [{"event_conf": r["event_conf"], "event_correct": r["event_correct"],
                   "event_claimed": r.get("event_claimed"), "event_label": r.get("event_label", "unknown")}
                  for r in synth]
    real_rows = []
    if os.path.exists(REAL_PATH):
        for r in json.load(open(REAL_PATH)):
            real_rows.append({"event_conf": float(r.get("conf", 0.0)),
                              "event_correct": int(r.get("correct", 0)),
                              "event_claimed": int(r.get("label") not in (None, "unknown")),
                              "event_label": r.get("label", "unknown")})

    profiles = {"synthetic": synth_rows}
    if real_rows:
        profiles["real"] = real_rows
        profiles["hybrid"] = synth_rows + real_rows

    results = {}
    for name, rows in profiles.items():
        params = cal.fit_profile(rows, name=name)
        cal.save_params(params, profile=name)
        results[name] = params
        print(f"[fit] {name}: n={len(rows)} claimed={params['claimed_rows']} "
              f"ECE {params['ece_before']}->{params['ece_after']} op={params['operating_point']}")
        if real_rows and name != "real":
            print(f"       external on real n={len(real_rows)}: {cal.evaluate_profile(params, real_rows)}")
    if real_rows:
        print(f"[in-sample] real profile: {cal.evaluate_profile(results['real'], real_rows)}")
    json.dump({k: {kk: vv for kk, vv in v.items() if kk != 'binning'} for k, v in results.items()},
              open("cache/profile_summary.json", "w"), indent=1)


if __name__ == "__main__":
    main()
