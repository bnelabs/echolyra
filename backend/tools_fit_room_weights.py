"""Fit the room-attribution distance weights (decay / brightness / cepstrum) on synthetic data.

The hand-tuned weights (2.0, 0.083, 1.0) were guesses. This fits them on a training seed set
and reports held-out accuracy on unseen seeds. Weights are saved to cache/room_weights.json
and awareness.py loads them when present.
"""
import itertools
import json
from math import gcd

import numpy as np
from scipy.signal import fftconvolve, resample_poly

import awareness as aw

ROOMS = {"Living": (0.45, 7000, 0.0), "Kitchen": (0.22, 2500, -7.0), "Bedroom": (0.70, 4500, -3.0)}
KINDS = aw.GENERIC_EVENT_KINDS
FS = aw.FEATURE_SR


def transfer(rt, cutoff, gain):
    n = int(0.9 * FS); t = np.arange(n) / FS
    r = np.random.default_rng(hash((rt, cutoff, gain)) % 2**32)
    ir = r.normal(0, 1, n) * np.exp(-6.91 * t / rt)
    from scipy.signal import butter, sosfiltfilt
    ir = sosfiltfilt(butter(4, min(cutoff, FS / 2 * 0.95), "low", fs=FS, output="sos"), ir)
    ir[0] += 1.0
    return ir / np.max(np.abs(ir)) * (10 ** (gain / 20))


def room_stats(clips):
    vecs, feats = [], []
    for y in clips:
        f = aw.extract_features(y)
        vecs.append(aw.room_vector(f)); feats.append(f)
    v = np.mean(np.stack(vecs), axis=0)
    return {"rvec": v, "decay": float(v[13] * 60.0), "bright": float(v[14] * 10.0)}


def event_stats(y):
    f = aw.extract_features(y)
    vec = aw.room_vector(f)
    return {"decay": float(vec[13] * 60.0) if aw.extract_features else 0.0,
            "bright": float(vec[14] * 10.0), "mf": np.array(f["mfcc"], dtype=float),
            "decay_raw": f.get("early_decay_db_s") or f.get("decay_db_s") or 30.0}


def predict(ev, rooms, wd, wb, wm):
    scores = {}
    for name, r in rooms.items():
        log_ratio = abs(np.log(max(ev["decay_raw"] + 1.0, 1e-3) / max(r["decay"] + 1.0, 1e-3)))
        cos = float(np.dot(ev["mf"], r["rvec"][:13]) /
                    (np.linalg.norm(ev["mf"]) * np.linalg.norm(r["rvec"][:13]) + 1e-9))
        scores[name] = wd * log_ratio + wb * abs(ev["bright"] - r["bright"]) + wm * (1.0 - cos)
    ds = np.array(list(scores.values()))
    p = np.exp(-(ds - ds.min()) / 0.6)
    p = p / p.sum()
    order = np.argsort(-p)
    names = list(scores.keys())
    conf = float(p[order[0]]); margin = float(p[order[0]] - p[order[1]])
    uncertain = conf < 0.5 or margin < 0.15
    return names[order[0]], conf, uncertain


def make_rooms():
    rooms = {}
    for name, params in ROOMS.items():
        ir = transfer(*params)
        knocks = []
        for t in range(2):
            y = fftconvolve(aw.generic_kernel("knock", t, FS), ir)[: int(2.4 * FS)]
            knocks.append(y + np.random.default_rng(50 + t).normal(0, 1e-3, len(y)))
        rooms[name] = {**room_stats(knocks), "ir": ir}
    return rooms


def events(rooms, seeds):
    out = []
    for name, r in rooms.items():
        for kind in KINDS:
            for seed in seeds:
                y = fftconvolve(aw.generic_kernel(kind, 20 + seed, FS), r["ir"])[: int(2.4 * FS)]
                y = y + np.random.default_rng(300 + seed).normal(0, 1e-3, len(y))
                f = aw.extract_features(y)
                ev = {"decay_raw": f.get("early_decay_db_s") or f.get("decay_db_s") or 30.0,
                      "bright": float(aw.room_vector(f)[14] * 10.0),
                      "mf": np.array(f["mfcc"], dtype=float)}
                out.append((name, ev))
    return out


def score(rooms, evs, w):
    right = total = unc = 0
    for true_name, ev in evs:
        pred, conf, uncertain = predict(ev, rooms, *w)
        total += 1; right += int(pred == true_name); unc += int(uncertain)
    return right / total, unc / total


def main():
    rooms = make_rooms()
    train = events(rooms, seeds=[0, 1, 2])
    val = events(rooms, seeds=[10, 11, 12, 13])
    current = (2.0, 0.5 / 6.0, 1.0)
    base_train = score(rooms, train, current)
    base_val = score(rooms, val, current)
    grid = list(itertools.product(
        [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],            # decay log-ratio
        [0.0, 0.02, 0.05, 0.08, 0.12, 0.18, 0.25],  # brightness per dB
        [0.3, 0.6, 1.0, 1.4, 1.8, 2.4],             # cepstral cosine
    ))
    best = None
    for w in grid:
        tr, _ = score(rooms, train, w)
        if best is None or tr > best[0]:
            best = (tr, w)
    learned = best[1]
    val_learned = score(rooms, val, learned)
    out = {
        "current": {"weights": current, "train": base_train, "val": base_val},
        "learned": {"weights": learned, "train": best[0], "val": val_learned},
        "n_train": len(train), "n_val": len(val),
    }
    json.dump(out, open("cache/room_weights_search.json", "w"), indent=1)
    print(json.dumps(out, indent=1))
    # only ship learned weights if they genuinely generalise to unseen seeds
    if val_learned[0] > base_val[0]:
        json.dump({"weights": learned, "source": "tools_fit_room_weights.py",
                   "train_accuracy": best[0], "val_accuracy": val_learned[0]},
                  open("cache/room_weights.json", "w"), indent=1)
        print("shipping learned weights")
    else:
        print("learned weights do not generalise; keeping current")


if __name__ == "__main__":
    main()
