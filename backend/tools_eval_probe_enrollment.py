"""Can a single active probe enroll a room as well as knocking in it?

Compares room attribution accuracy with:
  A) probe-seeded enrollment: synthesize templates from the measured impulse response only
  B) knock-based enrollment: two knocks recorded in the room
Ground truth: events convolved with each room's true RIR (known synthetic rooms).
"""
import json
from math import gcd

import numpy as np
from scipy.signal import fftconvolve, resample_poly

import acoustics as ac
import awareness as aw
import probe

FS_EVENT = 16000
ROOMS = {"Living": (0.45, 7000, 0.0), "Kitchen": (0.22, 2500, -7.0), "Bedroom": (0.70, 4500, -3.0)}


def transfer(rt, cutoff, gain, fs):
    n = int(0.9 * fs)
    t = np.arange(n) / fs
    r = np.random.default_rng(hash((rt, cutoff, gain)) % 2**32)
    ir = r.normal(0, 1, n) * np.exp(-6.91 * t / rt)
    from scipy.signal import butter, sosfiltfilt
    ir = sosfiltfilt(butter(4, min(cutoff, fs / 2 * 0.95), "low", fs=fs, output="sos"), ir)
    ir[0] += 1.0
    return ir / np.max(np.abs(ir)) * (10 ** (gain / 20))


def to_fs(x, fs_in, fs_out):
    if fs_in == fs_out:
        return x
    g = gcd(int(fs_in), int(fs_out))
    return resample_poly(x, fs_out // g, fs_in // g)


def main():
    probe.STATE_PATH.unlink(missing_ok=True)
    for f in probe.RIR_DIR.glob("*.npy") if probe.RIR_DIR.exists() else []:
        f.unlink()

    rirs48 = {r: transfer(*p, probe.FS) for r, p in ROOMS.items()}
    # 1) active probe in each room, then seed a session from the measured RIRs
    for room, params in ROOMS.items():
        rir = rirs48[room]
        sweep = probe.probe_sweep()
        rec = np.convolve(rir, sweep)[: len(rir) + len(sweep)]
        rec = rec / np.max(np.abs(rec)) * 0.5
        rec = rec + np.random.default_rng(7).normal(0, 2e-3, len(rec))
        probe.enroll(room, room, [rec])

    probe_session = aw.Session()
    probe_session.reset()
    for room in ROOMS:
        rir = probe.load_rir(room)
        probe_session.enroll_from_probe(room, room, rir, probe.FS)

    # 2) knock-based enrollment in the same rooms
    knock_session = aw.Session()
    knock_session.reset()
    for room in ROOMS:
        rir16 = to_fs(rirs48[room], probe.FS, FS_EVENT)
        for t in range(2):
            y = fftconvolve(aw.generic_kernel("knock", t, FS_EVENT), rir16)[: int(2.4 * FS_EVENT)]
            y = y + np.random.default_rng(50 + t).normal(0, 1e-3, len(y))
            knock_session.enroll(room, room, [aw.wav_bytes(y)])

    # 3) evaluate events through the true room transfer
    results = {"probe": {"right": 0, "total": 0, "uncertain": 0, "conf": []},
               "knock": {"right": 0, "total": 0, "uncertain": 0, "conf": []}}
    rows = []
    for room in ROOMS:
        rir16 = to_fs(rirs48[room], probe.FS, FS_EVENT)
        for kind in aw.GENERIC_EVENT_KINDS:
            for t in range(2):
                y = fftconvolve(aw.generic_kernel(kind, 10 + t, FS_EVENT), rir16)[: int(2.4 * FS_EVENT)]
                y = y + np.random.default_rng(200 + t).normal(0, 1e-3, len(y))
                raw = aw.wav_bytes(y)
                for label, session in (("probe", probe_session), ("knock", knock_session)):
                    rec = session.detect(raw)
                    predicted = rec["room"].get("room_name")
                    uncertain = bool(rec["room"].get("uncertain", True))
                    st = results[label]
                    st["total"] += 1
                    st["right"] += int(predicted == room)
                    st["uncertain"] += int(uncertain)
                    st["conf"].append(float(rec["room"].get("confidence", 0.0)))
                    rows.append({"session": label, "event": kind, "true_room": room,
                                 "predicted_room": predicted, "uncertain": uncertain,
                                 "confidence": round(float(rec["room"].get("confidence", 0.0)), 3)})
    summary = {}
    for label, st in results.items():
        summary[label] = {
            "room_accuracy": round(st["right"] / max(1, st["total"]), 3),
            "uncertain_rate": round(st["uncertain"] / max(1, st["total"]), 3),
            "mean_confidence": round(float(np.mean(st["conf"])), 3) if st["conf"] else None,
            "n": st["total"],
        }
    out = {"summary": summary, "rows": rows}
    json.dump(out, open("../docs/eval_probe_enrollment.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
