"""Cache synthetic labelled rows so calibration validation doesn't regenerate them every run."""
import json
import calibration as cal

rows = cal.collect_labelled(n_trials=2)
out = [{"event_conf": r["event_conf"], "event_correct": r["event_correct"],
        "event_claimed": r.get("event_claimed"), "event_label": r.get("event_label", "unknown")}
       for r in rows]
json.dump(out, open("cache/synth_rows.json", "w"))
print("saved", len(out), "synthetic rows")
