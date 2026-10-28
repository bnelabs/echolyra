"""Active acoustic room fingerprinting.

Instead of inferring the room from whatever event happens to occur, the phone emits a
quiet logarithmic sweep, records it through its own microphone, deconvolves the measured
impulse response, and derives ISO-3382 room parameters. That makes room identity and room
change detection source-independent — the frontier capability over passive event matching.

Signal chain: probe_sweep() -> speaker -> room -> microphone -> deconvolve() -> RIR ->
analyze_rir() -> fingerprint -> compare with the stored baseline -> change detection.
"""
from __future__ import annotations

import io
import json
import math
import time
import wave
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve, resample_poly

FS = 48_000
BANDS = np.array([250, 500, 1000, 2000, 4000, 8000])
# Phone speakers cannot reproduce the low bands, and even 1 kHz is unstable across launches
# (measured CV 18% low bands, 1 kHz band std 206 ms on-device). Room identity/change uses
# 2-8 kHz, where repeatability is 4-7% of RT60.
USABLE_BANDS = np.array([2000, 4000, 8000])
USABLE_IDX = [int(np.where(BANDS == fc)[0][0]) for fc in USABLE_BANDS]
F1, F2, SWEEP_T = 250.0, 16_000.0, 3.0   # phone-speaker-friendly band
STATE_PATH = Path(__file__).parent / "cache" / "probe_state.json"
RIR_DIR = Path(__file__).parent / "cache" / "probe_rirs"


# --------------------------------------------------------------------- signals
def probe_sweep(T: float = SWEEP_T, f1: float = F1, f2: float = F2, fs: int = FS) -> np.ndarray:
    t = np.arange(int(T * fs)) / fs
    k = math.log(f2 / f1) / T
    return np.sin(2 * math.pi * f1 * (np.exp(k * t) - 1) / k)


def farina_inverse(sweep: np.ndarray, f1: float = F1, f2: float = F2, fs: int = FS) -> np.ndarray:
    T = len(sweep) / fs
    k = math.log(f2 / f1) / T
    t = np.arange(len(sweep)) / fs
    inv = sweep[::-1] * np.exp(-k * t) * (k / (1 - math.exp(-k * T)))
    return inv / np.sqrt(np.sum(inv ** 2))


def deconvolve(recording: np.ndarray, fs: int = FS, tail_s: float = 1.6) -> np.ndarray:
    h = fftconvolve(recording, farina_inverse(probe_sweep(fs=fs)))
    if len(h) == 0:
        return h
    peak = int(np.argmax(np.abs(h)))
    start = max(0, peak - int(0.005 * fs))
    out = h[start:start + int(tail_s * fs)]
    if len(out) == 0:
        return out
    out[0] = 0.0
    return out - np.mean(out[: min(200, len(out))])


# --------------------------------------------------------------------- acoustics
def _octave(x: np.ndarray, fc: float, fs: int = FS) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt
    lo, hi = fc / math.sqrt(2), min(fc * math.sqrt(2), 0.98 * fs / 2)
    if lo >= hi:
        return np.zeros_like(x)
    return sosfiltfilt(butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos"), x)


def _decay(rir: np.ndarray, fc: float, lo: float, hi: float, fs: int = FS) -> float:
    y = _octave(rir, fc, fs)
    e = np.cumsum(y[::-1] ** 2)[::-1]
    if e[0] <= 0:
        return float("nan")
    edc = 10 * np.log10(np.maximum(e / e[0], 1e-12))
    idx = np.where((edc <= lo) & (edc >= hi))[0]
    if len(idx) < 64:
        return float("nan")
    slope = np.polyfit(idx / fs, edc[idx], 1)[0]
    return float(-60.0 / slope) if slope < 0 else float("nan")


def _band_energy(rir: np.ndarray, fc: float, fs: int = FS) -> float:
    y = _octave(rir, fc, fs)
    return float(10 * math.log10(np.mean(y ** 2) + 1e-14))


def analyze_probe(recording: np.ndarray, fs: int = FS) -> dict:
    """Measure ISO-3382-ish parameters + a room fingerprint from one probe recording."""
    rir = deconvolve(recording, fs)
    if len(rir) < fs // 2:
        raise ValueError("recording too short to contain the probe")
    t30 = [_decay(rir, fc, -5, -35, fs) for fc in BANDS]
    edt = [_decay(rir, fc, 0, -10, fs) for fc in BANDS]
    energies = np.array([_band_energy(rir, fc, fs) for fc in BANDS])
    t30_arr = np.array(t30, dtype=float)
    usable_t30 = t30_arr[USABLE_IDX]
    usable_energies = energies[USABLE_IDX]
    valid_bands = int(np.sum(np.isfinite(usable_t30)))
    mid = np.nanmedian(t30_arr[USABLE_IDX[0]:USABLE_IDX[1] + 1])   # 2 kHz - 4 kHz
    snr = 20 * math.log10(
        (np.max(np.abs(recording)) + 1e-9) /
        (np.sqrt(np.mean(recording[: max(64, int(0.05 * fs))] ** 2)) + 1e-9))
    shape = (usable_energies - np.mean(usable_energies)) / 12.0
    # fingerprint: reverberation in phone-usable bands + late-tail spectral shape
    fingerprint = np.concatenate([
        np.nan_to_num(usable_t30, nan=0.0) / 1.2,
        shape,
        [math.log1p(max(mid, 0.01)) / 2.0],
    ]).tolist()
    return {
        "rir": rir,
        "t30_s": [None if not np.isfinite(v) else round(float(v), 3) for v in t30],
        "t30_usable_s": [None if not np.isfinite(v) else round(float(v), 3) for v in usable_t30],
        "usable_bands_hz": [int(v) for v in USABLE_BANDS],
        "edt_s": [None if not np.isfinite(v) else round(float(v), 3) for v in edt],
        "rt60_mid_s": None if not np.isfinite(mid) else round(float(mid), 3),
        "band_shape": [round(float(v), 2) for v in shape],
        "fingerprint": [round(float(v), 4) for v in fingerprint],
        "valid_bands": valid_bands,
        "snr_db": round(float(snr), 1),
        "valid": bool(valid_bands >= 3 and snr > 12),   # 3 usable bands (2-8 kHz)
        "measured_at": time.time(),
    }


# --------------------------------------------------------------------- store
def _activity_threshold() -> float:
    """Calibrated threshold for the activity score (committed measurement, else default)."""
    for path in (STATE_PATH.parent / "activity_calibration.json",
                 Path(__file__).parent.parent / "docs" / "measurements" / "activity_calibration.json"):
        try:
            return float(json.loads(path.read_text()).get("threshold", 0.45))
        except Exception:
            continue
    return 0.45


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            d = json.loads(STATE_PATH.read_text())
            if d.get("version") == 1:
                return d
        except Exception:
            pass
    return {"version": 1, "rooms": {}}


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


def enroll(room_id: str, room_name: str, recordings: list[np.ndarray]) -> dict:
    """Average fingerprints over 1-3 probes; store the baseline fingerprint for the room."""
    analyses = [analyze_probe(r) for r in recordings]
    if not analyses:
        raise ValueError("no probe recordings")
    fps = [np.array(a["fingerprint"]) for a in analyses]
    mean_fp = np.mean(np.stack(fps), axis=0)
    t30s = np.array([a["t30_usable_s"] for a in analyses], dtype=float)
    mid = np.nanmedian(t30s[:, :2]) if np.isfinite(t30s).any() else None
    usable_std = np.nanstd(t30s, axis=0) if len(analyses) > 1 else np.zeros(t30s.shape[1])
    # Repeatability estimate: pairwise distance between the enrollment probes tells us how
    # much this room's fingerprint naturally varies (noise floor for change detection).
    noise_mean, noise_std = 0.0, 0.02
    if len(fps) >= 2:
        dists = [float(np.linalg.norm(fps[i] - fps[j]))
                 for i in range(len(fps)) for j in range(i + 1, len(fps))]
        noise_mean = float(np.mean(dists))
        noise_std = max(float(np.std(dists)), 0.01)
    state = _load_state()
    room = {
        "id": room_id, "name": room_name,
        "fingerprint": mean_fp.tolist(),
        "noise_mean": round(noise_mean, 4), "noise_std": round(noise_std, 4),
        "history": [],
        "t30_mid_s": None if mid is None or not np.isfinite(mid) else round(float(mid), 3),
        "rt60_mid_s": analyses[0]["rt60_mid_s"],
        "t30_s": analyses[0]["t30_s"],
        "t30_usable_s": analyses[0]["t30_usable_s"],
        "t30_std": [None if not np.isfinite(v) else round(float(v), 3) for v in usable_std],
        "band_shape": analyses[0]["band_shape"],
        "valid": all(a["valid"] for a in analyses),
        "n_probes": len(analyses),
        "enrolled_at": time.time(),
    }
    # keep the measured impulse response so the room can be enrolled from the probe alone
    rirs = [a["rir"] for a in analyses]
    if rirs:
        n = min(len(r) for r in rirs)
        avg = np.mean(np.stack([r[:n] for r in rirs]), axis=0)
        avg = avg / (np.max(np.abs(avg)) + 1e-12)
        RIR_DIR.mkdir(parents=True, exist_ok=True)
        np.save(RIR_DIR / f"{room_id}.npy", avg.astype(np.float32))
    state["rooms"][room_id] = room
    _save_state(state)
    return {"room": room, "analyses": [{k: v for k, v in a.items() if k != "rir"} for a in analyses]}


def load_rir(room_id: str) -> np.ndarray | None:
    path = RIR_DIR / f"{room_id}.npy"
    return np.load(path) if path.exists() else None


def check(room_id: str, recording: np.ndarray) -> dict:
    """Compare a fresh probe with the stored baseline -> stable / drift / changed.

    The change statistic is a z-score of the fingerprint distance against the room's own
    repeatability noise (measured from the enrollment probes), so thresholds adapt to the
    room instead of being global guesses. Slowly accumulating history detects gradual drift;
    alternating probes in a short window flag an activity anomaly (possible movement).
    """
    state = _load_state()
    room = state["rooms"].get(room_id)
    if not room:
        raise KeyError(f"room {room_id} has no probe baseline")
    a = analyze_probe(recording)
    base = np.array(room["fingerprint"])
    cur = np.array(a["fingerprint"])
    if len(base) != len(cur):
        raise ValueError("probe baseline from an older protocol; re-enroll this room")
    dist = float(np.linalg.norm(cur - base))
    noise_mean = float(room.get("noise_mean", 0.0))
    noise_std = max(float(room.get("noise_std", 0.02)), 0.01)
    z = (dist - noise_mean) / noise_std

    base_t30 = np.array([v if v is not None else np.nan
                         for v in room.get("t30_usable_s", room.get("t30_s", []))], dtype=float)
    cur_t30 = np.array([v if v is not None else np.nan for v in a["t30_usable_s"]], dtype=float)
    if len(base_t30) != len(cur_t30):
        raise ValueError("probe baseline from an older protocol; re-enroll this room")
    rel = np.abs(cur_t30 - base_t30) / np.maximum(base_t30, 0.05)
    # RT-change decisions use the 2-4 kHz bands (8 kHz is fingerprint-only; it fluctuates more)
    mid_rel = rel[:2] if len(rel) >= 2 else rel
    max_rel = float(np.nanmax(mid_rel)) if np.isfinite(mid_rel).any() else 0.0
    # per-band z against the room's own repeated-probe variability (needs 3-probe enrollment)
    std = np.array([v if v is not None else np.nan for v in room.get("t30_std", [0.02] * 4)], dtype=float)
    std = np.where(np.isfinite(std) & (std > 0.01), std, 0.03)
    std = np.maximum(std, 0.03)   # 30 ms floor: cross-launch probe repeatability on a phone
    band_z = np.abs(cur_t30 - base_t30) / np.maximum(std, 0.01)
    max_band_z = float(np.nanmax(band_z)) if np.isfinite(band_z).any() else 0.0

    # Thresholds combine the physically meaningful per-band RT change with fingerprint
    # distance. (Pure z-scores explode when the enrollment repeatability is very tight.)
    # Change decision uses both the physical RT change and the room's measured repeatability:
    # a real door/furniture change must exceed what repeated probes already show.
    if max_rel > 0.25 or dist > 0.45 or max_band_z > 6.0:
        status = "changed"
        confidence = min(0.99, 0.70 + 0.29 * min(max(max_rel - 0.25, (max_band_z - 6.0) / 8.0), 1.0))
    elif max_rel > 0.10 or dist > 0.25 or max_band_z > 3.5:
        status = "drift"
        confidence = min(0.95, 0.55 + 0.40 * min(max(max_rel - 0.10, (max_band_z - 3.5) / 4.0) / 0.5, 1.0))
    else:
        status = "stable"
        confidence = min(0.99, 0.60 + 0.39 * (1.0 - min(max(max_rel / 0.10, max_band_z / 3.5), 1.0)))

    history = room.get("history", [])
    history.append({"ts": round(time.time(), 1), "distance": round(dist, 4), "z": round(z, 2),
                    "max_t30_change_pct": round(100 * max_rel, 1), "status": status,
                    "rt60_mid_s": a["rt60_mid_s"]})
    room["history"] = history[-100:]

    # transient change: the room fluctuated and returned (door opened/closed, someone moved
    # something) -> useful as a low-confidence "activity" signal, not a room redesign.
    recent = room["history"][-4:]
    dists_recent = [h["distance"] for h in recent]
    spread = (max(dists_recent) - min(dists_recent)) if dists_recent else 0.0
    transient = bool(len(recent) >= 3 and len({h["status"] for h in recent}) > 1
                     and spread > 0.10 and status != "changed")

    # activity score: how much more variable recent probes are than the room's own
    # repeatability noise. 0 = as steady as an empty room; 1 = highly variable (movement).
    window = room["history"][-6:]
    if len(window) >= 3:
        dvals = [h["distance"] for h in window]
        variation = float(np.std(dvals))
        activity_score = float(np.clip((variation / max(noise_std, 0.01) - 1.0) / 4.0, 0.0, 1.0))
    else:
        activity_score = 0.0
    unusual_activity = bool(activity_score >= _activity_threshold()
                            and len(window) >= 3 and status != "changed")
    room["last_status"] = status
    room["last_checked_at"] = time.time()
    _save_state(state)

    return {
        "room_id": room_id, "room_name": room["name"],
        "change_detected": status == "changed",
        "status": status, "confidence": round(confidence, 2), "z_score": round(z, 2),
        "repeatability_noise": {"mean": round(noise_mean, 4), "std": round(noise_std, 4)},
        "fingerprint_distance": round(dist, 3),
        "max_t30_change_pct": round(100 * max_rel, 1),
        "delta_t30_s": [None if not (np.isfinite(c) and np.isfinite(b)) else round(float(c - b), 3)
                        for b, c in zip(base_t30, cur_t30)],
        "transient_change": transient,
        "activity_score": round(activity_score, 2),
        "unusual_activity": unusual_activity,
        "current": {k: v for k, v in a.items() if k != "rir"},
        "baseline_rt60_mid_s": room.get("rt60_mid_s"),
        "history": room["history"][-8:],
    }


def status() -> dict:
    state = _load_state()
    return {"rooms": [{"id": r["id"], "name": r["name"], "rt60_mid_s": r.get("rt60_mid_s"),
                       "valid": r.get("valid"), "n_probes": r.get("n_probes"),
                       "last_status": r.get("last_status"),
                       "repeatability_std": r.get("noise_std"),
                       "history_len": len(r.get("history", []))}
                      for r in state["rooms"].values()]}
