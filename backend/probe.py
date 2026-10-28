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
F1, F2, SWEEP_T = 250.0, 16_000.0, 3.0   # phone-speaker-friendly band
STATE_PATH = Path(__file__).parent / "cache" / "probe_state.json"


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
    valid_bands = int(np.sum(np.isfinite(t30)))
    t30_arr = np.array(t30, dtype=float)
    mid = np.nanmedian(t30_arr[1:4])           # 500 Hz - 2 kHz
    snr = 20 * math.log10(
        (np.max(np.abs(recording)) + 1e-9) /
        (np.sqrt(np.mean(recording[: max(64, int(0.05 * fs))] ** 2)) + 1e-9))
    shape = (energies - np.mean(energies)) / 12.0
    # fingerprint: reverberation in the most phone-usable bands + late-tail spectral shape
    fingerprint = np.concatenate([
        np.nan_to_num(t30_arr, nan=0.0) / 1.2,
        shape,
        [math.log1p(max(mid, 0.01)) / 2.0],
    ]).tolist()
    return {
        "rir": rir,
        "t30_s": [None if not np.isfinite(v) else round(float(v), 3) for v in t30],
        "edt_s": [None if not np.isfinite(v) else round(float(v), 3) for v in edt],
        "rt60_mid_s": None if not np.isfinite(mid) else round(float(mid), 3),
        "band_shape": [round(float(v), 2) for v in shape],
        "fingerprint": [round(float(v), 4) for v in fingerprint],
        "valid_bands": valid_bands,
        "snr_db": round(float(snr), 1),
        "valid": bool(valid_bands >= 4 and snr > 12),
        "measured_at": time.time(),
    }


# --------------------------------------------------------------------- store
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
    t30s = np.array([a["t30_s"] for a in analyses], dtype=float)
    mid = np.nanmedian(t30s[:, 1:4]) if np.isfinite(t30s).any() else None
    state = _load_state()
    room = {
        "id": room_id, "name": room_name,
        "fingerprint": mean_fp.tolist(),
        "t30_mid_s": None if mid is None or not np.isfinite(mid) else round(float(mid), 3),
        "rt60_mid_s": analyses[0]["rt60_mid_s"],
        "t30_s": analyses[0]["t30_s"],
        "band_shape": analyses[0]["band_shape"],
        "valid": all(a["valid"] for a in analyses),
        "n_probes": len(analyses),
        "enrolled_at": time.time(),
    }
    state["rooms"][room_id] = room
    _save_state(state)
    return {"room": room, "analyses": [{k: v for k, v in a.items() if k != "rir"} for a in analyses]}


def check(room_id: str, recording: np.ndarray) -> dict:
    """Compare a fresh probe against the stored baseline -> change detection."""
    state = _load_state()
    room = state["rooms"].get(room_id)
    if not room:
        raise KeyError(f"room {room_id} has no probe baseline")
    a = analyze_probe(recording)
    base = np.array(room["fingerprint"])
    cur = np.array(a["fingerprint"])
    dist = float(np.linalg.norm(cur - base))
    # per-band T30 relative change (the physically meaningful cue)
    base_t30 = np.array([v if v is not None else np.nan for v in room.get("t30_s", [])], dtype=float)
    cur_t30 = np.array([v if v is not None else np.nan for v in a["t30_s"]], dtype=float)
    rel = np.abs(cur_t30 - base_t30) / np.maximum(base_t30, 0.05)
    max_rel = float(np.nanmax(rel)) if np.isfinite(rel).any() else 0.0
    changed = bool(max_rel > 0.20 or dist > 0.35)
    return {
        "room_id": room_id, "room_name": room["name"],
        "change_detected": changed,
        "fingerprint_distance": round(dist, 3),
        "max_t30_change_pct": round(100 * max_rel, 1),
        "delta_t30_s": [None if not (np.isfinite(c) and np.isfinite(b)) else round(float(c - b), 3)
                        for b, c in zip(base_t30, cur_t30)],
        "current": {k: v for k, v in a.items() if k != "rir"},
        "baseline_rt60_mid_s": room.get("rt60_mid_s"),
    }


def status() -> dict:
    state = _load_state()
    return {"rooms": [{"id": r["id"], "name": r["name"], "rt60_mid_s": r.get("rt60_mid_s"),
                       "valid": r.get("valid"), "n_probes": r.get("n_probes")}
                      for r in state["rooms"].values()]}
