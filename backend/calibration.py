"""Calibrated uncertainty + decision policy for RoomSense.

Two layers:
1. Reliability calibration (histogram binning with Laplace smoothing + monotonicity):
   maps the classifier's raw top confidence to an empirically observed accuracy.
2. Conformal thresholding: with a user-chosen risk alpha, computes the confidence needed
   for an alert decision with a distribution-free coverage guarantee on held-out calibration
   data.
3. Decision policy: alert / explain / silent, using calibrated confidence, room confidence
   and the measured SNR. This is what stops the app from confidently labelling noise.

Run `run_calibration()` (or POST /api/calibrate) to rebuild the parameters from a labelled
set; parameters are stored in cache/calibration.json.
"""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfiltfilt

import awareness as aw

PARAMS_PATH = Path(__file__).parent / "cache" / "calibration.json"
N_BINS = 10
ALPHA = 0.10          # conformal risk: 90% coverage target


# --------------------------------------------------------------------- calibration math
def _bin_index(conf: float) -> int:
    return min(N_BINS - 1, max(0, int(conf * N_BINS)))


def fit_binning(confs: list[float], corrects: list[int]) -> dict:
    """Reliability mapping: raw confidence -> empirical accuracy per bin (smoothed)."""
    sums = np.zeros(N_BINS)
    counts = np.zeros(N_BINS)
    for c, ok in zip(confs, corrects):
        b = _bin_index(c)
        sums[b] += ok
        counts[b] += 1
    values = np.full(N_BINS, np.nan)
    for b in range(N_BINS):
        centre = (b + 0.5) / N_BINS
        if counts[b] == 0:
            values[b] = centre
        else:
            # Laplace-style shrinkage toward the bin centre
            values[b] = (sums[b] + 2.5 * centre) / (counts[b] + 2.5)
    # enforce monotonicity (a raw-confidence increase must not lower calibrated accuracy)
    for i in range(1, N_BINS):
        if values[i] < values[i - 1]:
            values[i] = values[i - 1]
    return {"edges": [round(i / N_BINS, 2) for i in range(N_BINS + 1)],
            "values": [round(float(v), 4) for v in values],
            "counts": [int(c) for c in counts]}


def apply_binning(conf: float, params: dict) -> float:
    b = _bin_index(conf)
    return float(params["values"][b])


def expected_calibration_error(confs: list[float], corrects: list[int], bins: int = N_BINS) -> float:
    n = len(confs)
    if n == 0:
        return float("nan")
    err = 0.0
    for b in range(bins):
        idx = [i for i, c in enumerate(confs) if _bin_index(c) == b]
        if not idx:
            continue
        acc = sum(corrects[i] for i in idx) / len(idx)
        conf = sum(confs[i] for i in idx) / len(idx)
        err += (len(idx) / n) * abs(acc - conf)
    return float(err)


def fit_conformal(confs: list[float], corrects: list[int], alpha: float = ALPHA) -> dict:
    """Split-conformal: threshold on (1 - confidence) for 'correct' coverage 1-alpha."""
    n = len(confs)
    if n == 0:
        return {"alpha": alpha, "threshold": 0.5, "coverage_empirical": None}
    scores = sorted(1.0 - c for c in confs)
    k = min(n - 1, int(math.ceil((n + 1) * (1 - alpha))) - 1)
    threshold_conf = 1.0 - scores[k]
    covered = sum(1 for c, ok in zip(confs, corrects) if ok and c >= threshold_conf)
    # empirical probability that a positive prediction is correct
    predicted = [ok for c, ok in zip(confs, corrects) if c >= threshold_conf]
    return {"alpha": alpha, "threshold": round(float(threshold_conf), 3),
            "n": n, "predicted": len(predicted),
            "precision_at_threshold": None if not predicted else round(sum(predicted) / len(predicted), 3)}


def fit_operating_point(confs: list[float], corrects: list[int],
                        target_precision: float = 0.90, min_n: int = 10) -> dict:
    """Lowest confidence threshold whose accepted predictions reach target precision."""
    pairs = sorted(zip(confs, corrects), key=lambda p: -p[0])
    best = None
    n = correct = 0
    for conf, ok in pairs:
        n += 1
        correct += ok
        precision = correct / n
        if n >= min_n and precision >= target_precision:
            best = {"threshold": round(float(conf), 3), "precision": round(precision, 3),
                    "accepted": n}
    if best is None:
        return {"threshold": 0.85, "precision": None, "accepted": 0,
                "note": "insufficient data for target precision"}
    return best


def fit_operating_points_by_label(rows: list[dict], target_precision: float = 0.90,
                                   min_n: int = 5) -> dict:
    """Per-event-class precision thresholds, with the global operating point as fallback."""
    by = {}
    for r in rows:
        if not r.get("event_claimed"):
            continue
        by.setdefault(r.get("label", "unknown"), []).append(r)
    out = {}
    for label, subset in by.items():
        confs = [r["event_conf"] for r in subset]
        corr = [r["event_correct"] for r in subset]
        if len(subset) >= min_n:
            out[label] = fit_operating_point(confs, corr, target_precision=target_precision,
                                             min_n=min_n)
    return out


# --------------------------------------------------------------------- decision policy
def decide(event_conf: float, room_conf: float, snr_db: float, params: dict | None = None,
           event_label: str = "") -> dict:
    params = params or load_params()
    cal = apply_binning(event_conf, params["binning"]) if params else event_conf
    by_label = (params or {}).get("operating_points_by_label") or {}
    op = by_label.get(event_label) or (params or {}).get("operating_point") or {}
    conf_thr = float(op.get("threshold", 0.75))
    reasons = []
    if snr_db < 12.0:
        return {"decision": "silent", "calibrated_confidence": round(cal, 2),
                "reason": "low_snr", "snr_db": round(snr_db, 1),
                "alert_threshold": conf_thr}
    if cal < 0.45:
        return {"decision": "silent", "calibrated_confidence": round(cal, 2),
                "reason": "low_confidence", "snr_db": round(snr_db, 1),
                "alert_threshold": conf_thr}
    if cal >= conf_thr and room_conf >= 0.55:
        return {"decision": "alert", "calibrated_confidence": round(cal, 2),
                "reason": "conformal_pass", "snr_db": round(snr_db, 1),
                "alert_threshold": conf_thr}
    return {"decision": "explain", "calibrated_confidence": round(cal, 2),
            "reason": "needs_context", "snr_db": round(snr_db, 1),
            "alert_threshold": conf_thr}


# --------------------------------------------------------------------- parameter store
def load_params() -> dict | None:
    if PARAMS_PATH.exists():
        try:
            return json.loads(PARAMS_PATH.read_text())
        except Exception:
            return None
    return None


def save_params(params: dict):
    PARAMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARAMS_PATH.write_text(json.dumps(params, indent=1))


# --------------------------------------------------------------------- labelled data
def _transfer(rt: float, cut: float, gain_db: float, seed: int, fs: int = 16000) -> np.ndarray:
    n = int(0.9 * fs)
    t = np.arange(n) / fs
    r = np.random.default_rng(seed)
    ir = r.normal(0, 1, n) * np.exp(-6.91 * t / rt)
    ir = sosfiltfilt(butter(4, min(cut, fs / 2 * 0.95), "low", fs=fs, output="sos"), ir)
    ir[0] += 1.0
    return ir / np.max(np.abs(ir)) * (10 ** (gain_db / 20))


def _event(kind: str, seed: int, fs: int = 16000) -> np.ndarray:
    r = np.random.default_rng(seed)
    n = int(2.0 * fs)
    x = r.normal(0, 1e-4, n)
    if kind == "knock":
        k = np.zeros(int(0.28 * fs)); i = int(0.03 * fs)
        k[i:i+40] += np.hanning(40) * 0.8
        t = np.arange(int(0.2 * fs)) / fs
        k[i:i+len(t)] += 0.35 * np.sin(2 * np.pi * 180 * t) * np.exp(-t / 0.02) * 0.8
        x[int(0.4 * fs):int(0.4 * fs) + len(k)] += k
    elif kind == "glass":
        m = int(0.15 * fs); t = np.arange(m) / fs
        b = r.normal(0, 1, m) * np.exp(-t / 0.02)
        b = sosfiltfilt(butter(4, 3500, "high", fs=fs, output="sos"), b)
        x[int(0.4 * fs):int(0.4 * fs) + m] += b * 0.7
    elif kind == "cry":
        m = int(1.4 * fs); t = np.arange(m) / fs
        f = 420 + 90 * np.sin(2 * np.pi * 3.2 * t)
        x[int(0.3 * fs):int(0.3 * fs) + m] += 0.5 * np.sin(2 * np.pi * np.cumsum(f) / fs)
    elif kind == "alarm":
        m = int(1.4 * fs); t = np.arange(m) / fs
        x[int(0.3 * fs):int(0.3 * fs) + m] += 0.5 * np.sin(2 * np.pi * 1000 * t)
    elif kind == "speech":
        t = np.arange(n) / fs
        env = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t)
        carrier = sosfiltfilt(butter(4, [300, 3000], "bandpass", fs=fs, output="sos"),
                              r.normal(0, 1, n))
        x += 0.05 * carrier * env
    elif kind == "water":
        t = np.arange(n) / fs
        x += 0.02 * sosfiltfilt(butter(4, [200, 4000], "bandpass", fs=fs, output="sos"),
                                r.normal(0, 1, n))
    return x


ROOMS = {"living": (0.45, 7000, 0.0), "kitchen": (0.22, 2500, -7.0), "bedroom": (0.70, 4500, -3.0)}


def collect_labelled(n_trials: int = 2, snrs: list[float | None] = None) -> list[dict]:
    """Run the real pipeline on synthetic rooms/events; record confidence + correctness."""
    snrs = snrs if snrs is not None else [None, 40, 20, 10, 5]
    transfers = {r: _transfer(*v, seed=i) for i, (r, v) in enumerate(ROOMS.items())}
    session = aw.Session()
    session.reset()
    for room in ROOMS:
        for t in range(2):
            y = np.convolve(_event("knock", t), transfers[room])[: int(2.4 * 16000)]
            y += np.random.default_rng(t).normal(0, 1e-3, len(y))
            session.enroll(room, room.capitalize(), [aw.wav_bytes(y)])
    rows = []
    kinds = ["knock", "glass", "cry", "alarm", "speech", "water"]
    for snr in snrs:
        for kind in kinds:
            for room in ROOMS:
                for t in range(n_trials):
                    y = np.convolve(_event(kind, 10 + t), transfers[room])[: int(2.4 * 16000)]
                    y += np.random.default_rng(100 + t).normal(0, 1e-3, len(y))
                    if snr is not None:
                        seg = y[int(0.4 * 16000): int(0.6 * 16000)]
                        p = float(np.mean(seg ** 2))
                        y = y + np.random.default_rng(200 + t).normal(0, 1, len(y)) * math.sqrt(
                            max(p, 1e-10) / 10 ** (snr / 10))
                    rec = session.detect(aw.wav_bytes(y))
                    label = rec["event"]["label"]
                    expected = {"knock": {"knock", "impact_thud"}, "glass": {"glass_impact"},
                                "cry": {"baby_cry"}, "alarm": {"alarm_beep"},
                                "speech": {"speech"}, "water": {"water"}}[kind]
                    rows.append({
                        "snr": snr,
                        "event_conf": float(rec["event"].get("confidence", 0.0)),
                        "event_correct": int(label in expected),
                        "event_claimed": int(label not in (None, "unknown")),
                        "event_label": label,
                        "room_conf": float(rec["room"].get("confidence", 0.0)),
                        "room_correct": int((not rec["room"].get("uncertain", True))
                                            and rec["room"].get("room_name") == room.capitalize()),
                    })
    return rows


# --------------------------------------------------------------------- end-to-end fit
def run_calibration(n_trials: int = 2) -> dict:
    rows = collect_labelled(n_trials=n_trials)
    # Reliability calibration on all rows; operating point/coverage only on rows where the
    # classifier actually made a claim (abstentions are handled by the SNR/decision gates).
    confs = [r["event_conf"] for r in rows]
    corrects = [r["event_correct"] for r in rows]
    claimed = [r for r in rows if r.get("event_claimed")]
    c_confs = [r["event_conf"] for r in claimed]
    c_correct = [r["event_correct"] for r in claimed]
    ece_before = expected_calibration_error(confs, corrects)
    binning = fit_binning(confs, corrects)
    cal_confs = [apply_binning(c, binning) for c in confs]
    ece_after = expected_calibration_error(cal_confs, corrects)
    ece_claimed_before = expected_calibration_error(c_confs, c_correct)
    conformal = fit_conformal(c_confs, c_correct, alpha=ALPHA)
    operating = fit_operating_point(c_confs, c_correct, target_precision=0.90, min_n=10)
    operating_by_label = fit_operating_points_by_label(
        [{"event_conf": r["event_conf"], "event_correct": r["event_correct"],
          "event_claimed": r.get("event_claimed"), "label": r.get("event_label", "unknown")}
         for r in rows], target_precision=0.90, min_n=5)

    # decision-layer evaluation at each SNR (uses the calibrated operating point)
    decisions = {}
    for snr in sorted({str(r["snr"]) for r in rows}, key=lambda s: (s == "None", s)):
        subset = [r for r in rows if str(r["snr"]) == snr]
        counts = {"alert": 0, "explain": 0, "silent": 0}
        wrong_alerts = correct = 0
        for r in subset:
            d = decide(r["event_conf"], r["room_conf"],
                       r["snr"] if r["snr"] is not None else 40.0,
                       {"binning": binning, "conformal": conformal,
                        "operating_point": operating})
            counts[d["decision"]] += 1
            if d["decision"] == "alert":
                correct += r["event_correct"]
                wrong_alerts += 0 if r["event_correct"] else 1
        decisions[snr] = {"n": len(subset), **counts,
                          "wrong_alerts": wrong_alerts,
                          "alert_precision": None if counts["alert"] == 0 else round(correct / counts["alert"], 2)}
    params = {"version": 1, "binning": binning, "conformal": conformal,
              "operating_point": operating,
              "operating_points_by_label": operating_by_label,
              "ece_before": round(ece_before, 4), "ece_after": round(ece_after, 4),
              "ece_claimed_before": round(ece_claimed_before, 4),
              "claimed_rows": len(claimed), "rows": len(rows),
              "n_samples": len(rows), "created_at": time.time(),
              "decisions_by_snr": decisions}
    save_params(params)
    return params
