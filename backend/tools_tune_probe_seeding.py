"""Try variants of RIR-based room-template synthesis and measure room attribution."""
import json
from math import gcd

import numpy as np
from scipy.signal import fftconvolve, resample_poly

import acoustics as ac
import awareness as aw
import probe

ROOMS = {"Living": (0.45, 7000, 0.0), "Kitchen": (0.22, 2500, -7.0), "Bedroom": (0.70, 4500, -3.0)}
KINDS = aw.GENERIC_EVENT_KINDS


def transfer(rt, cutoff, gain, fs):
    n = int(0.9 * fs); t = np.arange(n) / fs
    r = np.random.default_rng(hash((rt, cutoff, gain)) % 2**32)
    ir = r.normal(0, 1, n) * np.exp(-6.91 * t / rt)
    from scipy.signal import butter, sosfiltfilt
    ir = sosfiltfilt(butter(4, min(cutoff, fs / 2 * 0.95), "low", fs=fs, output="sos"), ir)
    ir[0] += 1.0
    return ir / np.max(np.abs(ir)) * (10 ** (gain / 20))


def to_fs(x, fs_in, fs_out):
    if fs_in == fs_out: return x
    g = gcd(int(fs_in), int(fs_out))
    return resample_poly(x, fs_out // g, fs_in // g)


def synth_rvec(rir48, spec, normalize_peak=None):
    rir = to_fs(rir48, probe.FS, aw.FEATURE_SR)
    rir = rir / (np.max(np.abs(rir)) + 1e-12)
    vecs = []
    for kind, reps, seeds in spec:
        for rep in range(reps):
            for seed in seeds:
                y = fftconvolve(aw.generic_kernel(kind, seed, aw.FEATURE_SR), rir)[: int(2.4 * aw.FEATURE_SR)]
                y = y + np.random.default_rng(seed + 3).normal(0, 1e-3, len(y))
                if normalize_peak:
                    y = y / (np.max(np.abs(y)) + 1e-12) * normalize_peak
                vecs.append(aw.room_vector(aw.extract_features(y)))
    return np.mean(np.stack(vecs), axis=0).tolist()


def run(spec, normalize_peak, events_per_kind=3):
    session = aw.Session(); session.reset()
    for room, params in ROOMS.items():
        rir48 = transfer(*params, probe.FS)
        session.state["rooms"][room] = {"id": room, "name": room, "n": 0,
                                        "rvec": synth_rvec(rir48, spec, normalize_peak)}
    right = total = uncertain = 0; conf = []
    for room, params in ROOMS.items():
        rir16 = to_fs(transfer(*params, probe.FS), probe.FS, aw.FEATURE_SR)
        for kind in KINDS:
            for seed in range(events_per_kind):
                y = fftconvolve(aw.generic_kernel(kind, 20 + seed, aw.FEATURE_SR), rir16)[: int(2.4 * aw.FEATURE_SR)]
                y = y + np.random.default_rng(300 + seed).normal(0, 1e-3, len(y))
                rec = session.detect(aw.wav_bytes(y))
                total += 1
                right += int(rec["room"].get("room_name") == room)
                uncertain += int(bool(rec["room"].get("uncertain", True)))
                conf.append(float(rec["room"].get("confidence", 0.0)))
    return {"accuracy": round(right / total, 3), "uncertain": round(uncertain / total, 3),
            "confidence": round(float(np.mean(conf)), 3), "n": total}


def main():
    probe.STATE_PATH.unlink(missing_ok=True)
    for f in probe.RIR_DIR.glob("*.npy") if probe.RIR_DIR.exists() else []:
        f.unlink()
    rir48 = {}
    for room, params in ROOMS.items():
        rir48[room] = transfer(*params, probe.FS)
        sweep = probe.probe_sweep()
        rec = np.convolve(rir48[room], sweep)[: len(rir48[room]) + len(sweep)]
        rec = rec / np.max(np.abs(rec)) * 0.5
        rec = rec + np.random.default_rng(7).normal(0, 2e-3, len(rec))
        probe.enroll(room, room, [rec])
    measured = {room: np.load(probe.RIR_DIR / f"{room}.npy") for room in ROOMS}

    base = [(k, 1, [0]) for k in KINDS]
    variants = {
        "v0_current": (base, None),
        "v1_3seeds": ([(k, 1, [0, 1, 2]) for k in KINDS], None),
        "v2_3seeds_level": ([(k, 1, [0, 1, 2]) for k in KINDS], 0.25),
        "v3_weighted": ([(k, reps, [0, 1, 2]) for k, reps in
                         (("knock", 2), ("glass", 2), ("water", 2),
                          ("cry", 1), ("alarm", 1), ("speech", 1))], 0.25),
    }
    results = {}
    # baseline: knocks
    ksession = aw.Session(); ksession.reset()
    for room in ROOMS:
        rir16 = to_fs(rir48[room], probe.FS, aw.FEATURE_SR)
        for t in range(2):
            y = fftconvolve(aw.generic_kernel("knock", t, aw.FEATURE_SR), rir16)[: int(2.4 * aw.FEATURE_SR)]
            y = y + np.random.default_rng(50 + t).normal(0, 1e-3, len(y))
            ksession.enroll(room, room, [aw.wav_bytes(y)])
    right = total = uncertain = 0; conf = []
    for room in ROOMS:
        rir16 = to_fs(rir48[room], probe.FS, aw.FEATURE_SR)
        for kind in KINDS:
            for seed in range(3):
                y = fftconvolve(aw.generic_kernel(kind, 20 + seed, aw.FEATURE_SR), rir16)[: int(2.4 * aw.FEATURE_SR)]
                y = y + np.random.default_rng(300 + seed).normal(0, 1e-3, len(y))
                rec = ksession.detect(aw.wav_bytes(y))
                total += 1
                right += int(rec["room"].get("room_name") == room)
                uncertain += int(bool(rec["room"].get("uncertain", True)))
                conf.append(float(rec["room"].get("confidence", 0.0)))
    results["knocks"] = {"accuracy": round(right / total, 3), "uncertain": round(uncertain / total, 3),
                         "confidence": round(float(np.mean(conf)), 3), "n": total}
    for name, (spec, norm) in variants.items():
        # patch synth function to use measured RIRs from probe
        def patched(rir, spec=spec, norm=norm):
            return synth_rvec(rir, spec, norm)
        session = aw.Session(); session.reset()
        for room in ROOMS:
            session.state["rooms"][room] = {"id": room, "name": room, "n": 0,
                                            "rvec": patched(measured[room])}
        r = run_events(session)
        results[name] = r
        print(name, r)
    print("knocks", results["knocks"])
    json.dump(results, open("cache/probe_seeding_tuning.json", "w"), indent=1)


def run_events(session):
    right = total = uncertain = 0; conf = []
    for room, params in ROOMS.items():
        rir16 = to_fs(transfer(*params, probe.FS), probe.FS, aw.FEATURE_SR)
        for kind in KINDS:
            for seed in range(3):
                y = fftconvolve(aw.generic_kernel(kind, 20 + seed, aw.FEATURE_SR), rir16)[: int(2.4 * aw.FEATURE_SR)]
                y = y + np.random.default_rng(300 + seed).normal(0, 1e-3, len(y))
                rec = session.detect(aw.wav_bytes(y))
                total += 1
                right += int(rec["room"].get("room_name") == room)
                uncertain += int(bool(rec["room"].get("uncertain", True)))
                conf.append(float(rec["room"].get("confidence", 0.0)))
    return {"accuracy": round(right / total, 3), "uncertain": round(uncertain / total, 3),
            "confidence": round(float(np.mean(conf)), 3), "n": total}


if __name__ == "__main__":
    main()
