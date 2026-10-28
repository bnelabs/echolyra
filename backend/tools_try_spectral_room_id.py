"""Frontier experiment: identify the room in log-mel spectral space using templates
synthesized from the measured probe RIR, vs the current decay/brightness/cepstrum metric."""
import json

import numpy as np
from scipy.signal import fftconvolve, get_window

import awareness as aw
import probe

ROOMS = {"Living": (0.45, 7000, 0.0), "Kitchen": (0.22, 2500, -7.0), "Bedroom": (0.70, 4500, -3.0)}
KINDS = aw.GENERIC_EVENT_KINDS
FS = 16000
N_MELS = 40
FMIN, FMAX = 100.0, 7800.0


def transfer(rt, cutoff, gain, fs=FS):
    n = int(0.9 * fs); t = np.arange(n) / fs
    r = np.random.default_rng(hash((rt, cutoff, gain)) % 2**32)
    ir = r.normal(0, 1, n) * np.exp(-6.91 * t / rt)
    from scipy.signal import butter, sosfiltfilt
    ir = sosfiltfilt(butter(4, min(cutoff, fs / 2 * 0.95), "low", fs=fs, output="sos"), ir)
    ir[0] += 1.0
    return ir / np.max(np.abs(ir)) * (10 ** (gain / 20))


def _mel_fb(fs=FS, n_fft=512):
    def hz2mel(f): return 2595 * np.log10(1 + f / 700)
    def mel2hz(m): return 700 * (10 ** (m / 2595) - 1)
    mels = np.linspace(hz2mel(FMIN), hz2mel(FMAX), N_MELS + 2)
    hz = mel2hz(mels)
    bins = np.floor((n_fft + 1) * hz / fs).astype(int)
    fb = np.zeros((N_MELS, n_fft // 2 + 1))
    for i in range(N_MELS):
        lo, mid, hi = bins[i], bins[i + 1], bins[i + 2]
        for k in range(lo, mid):
            if mid > lo: fb[i, k] = (k - lo) / (mid - lo)
        for k in range(mid, hi):
            if hi > mid: fb[i, k] = (hi - k) / (hi - mid)
    return fb


FB = _mel_fb()


def logmel(x, fs=FS):
    win = int(0.025 * fs); hop = int(0.010 * fs)
    w = get_window("hann", win)
    frames = [x[i:i + win] * w for i in range(0, len(x) - win, hop)]
    if not frames:
        frames = [np.zeros(win)]
    spec = np.abs(np.fft.rfft(np.stack(frames), n=512)) ** 2
    mel = np.log(spec @ FB.T + 1e-10)
    energies = spec.mean(axis=1)
    keep = energies > max(energies.max() * 1e-3, 1e-9)
    v = mel[keep].mean(axis=0) if keep.any() else mel.mean(axis=0)
    v = v - v.mean()
    return v / (np.linalg.norm(v) + 1e-9)


def make_rooms():
    rooms = {}
    for name, params in ROOMS.items():
        ir = transfer(*params)
        rooms[name] = {"ir": ir, "knocks": []}
        for t in range(2):
            y = fftconvolve(aw.generic_kernel("knock", t, FS), ir)[: int(2.4 * FS)]
            rooms[name]["knocks"].append(y + np.random.default_rng(50 + t).normal(0, 1e-3, len(y)))
    return rooms


def measured_rirs(rooms):
    probe.STATE_PATH.unlink(missing_ok=True)
    for f in (probe.RIR_DIR.glob("*.npy") if probe.RIR_DIR.exists() else []):
        f.unlink()
    out = {}
    for name, r in rooms.items():
        sweep = probe.probe_sweep()
        rec = np.convolve(r["ir"], sweep)[: len(r["ir"]) + len(sweep)]
        rec = rec / np.max(np.abs(rec)) * 0.5
        rec = rec + np.random.default_rng(7).normal(0, 2e-3, len(rec))
        probe.enroll(name, name, [rec])
        out[name] = np.load(probe.RIR_DIR / f"{name}.npy")
    return out


def event_set(rooms, seeds):
    out = []
    for name, r in rooms.items():
        for kind in KINDS:
            for seed in seeds:
                y = fftconvolve(aw.generic_kernel(kind, 20 + seed, FS), r["ir"])[: int(2.4 * FS)]
                y = y + np.random.default_rng(300 + seed).normal(0, 1e-3, len(y))
                out.append((name, y))
    return out


def spectral_predict(templates, y):
    v = logmel(y)
    scores = {}
    for room, t in templates.items():
        scores[room] = float(np.dot(v, t))  # cosine similarity
    names = list(scores); sims = np.array([scores[n] for n in names])
    p = np.exp((sims - sims.max()) / 0.05); p = p / p.sum()
    order = np.argsort(-p)
    uncertain = p[order[0]] < 0.5 or (p[order[0]] - p[order[1]]) < 0.15
    return names[order[0]], uncertain


def spectral_templates(rirs):
    templates = {}
    for room, rir in rirs.items():
        vecs = []
        for i, kind in enumerate(KINDS):
            y = fftconvolve(aw.generic_kernel(kind, i, FS), rir)[: int(2.4 * FS)]
            y = y + np.random.default_rng(100 + i).normal(0, 1e-3, len(y))
            vecs.append(logmel(y))
        templates[room] = np.mean(np.stack(vecs), axis=0)
    return templates


def current_predict(events, rooms):
    """Reproduce the shipped metric (decay/brightness/cepstrum) for a fair baseline."""
    session = aw.Session(); session.reset()
    for name, r in rooms.items():
        session.enroll(name, name, [aw.wav_bytes(y) for y in r["knocks"]])
    right = unc = 0
    for true_room, y in events:
        rec = session.detect(aw.wav_bytes(y))
        right += int(rec["room"].get("room_name") == true_room)
        unc += int(bool(rec["room"].get("uncertain", True)))
    return right / len(events), unc / len(events)


def main():
    rooms = make_rooms()
    train_events = event_set(rooms, [0, 1, 2])
    val_events = event_set(rooms, [10, 11, 12, 13])
    rirs = measured_rirs(rooms)

    results = {}
    for template_name, rirs_used in (("probe_rir_templates", rirs),):
        templates = spectral_templates(rirs_used)
        for split, evs in (("train", train_events), ("val", val_events)):
            right = unc = 0
            for true_room, y in evs:
                pred, uncertain = spectral_predict(templates, y)
                right += int(pred == true_room); unc += int(uncertain)
            results[f"{template_name}_{split}"] = {"acc": round(right / len(evs), 3),
                                                   "uncertain": round(unc / len(evs), 3)}
        # also template from the *true* RIR as an upper bound
        true_templates = spectral_templates({k: v["ir"] for k, v in rooms.items()})
        right = unc = 0
        for true_room, y in val_events:
            pred, uncertain = spectral_predict(true_templates, y)
            right += int(pred == true_room); unc += int(uncertain)
        results["true_rir_templates_val"] = {"acc": round(right / len(val_events), 3),
                                             "uncertain": round(unc / len(val_events), 3)}

    acc, unc = current_predict(val_events, rooms)
    results["current_metric_val"] = {"acc": round(acc, 3), "uncertain": round(unc, 3)}
    json.dump(results, open("cache/spectral_room_id.json", "w"), indent=1)
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
