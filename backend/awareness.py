"""RoomSense — home sound awareness.

Core loop:
  1. ENROLL: a docked phone hears a sound made in each room (a knock is enough).
     The received sound carries that room's transfer path to the phone (direct + wall
     attenuation + base-room response), so we store a per-room "transfer signature".
  2. TEACH (optional): a few labelled example events per class (knock, glass, cry...).
  3. DETECT: a new event is detected, classified (what), attributed to an enrolled room
     (where) by comparing transfer signatures, then Muse Spark writes the situation.

Privacy: only feature vectors are kept — no audio is persisted after feature extraction.
"""
from __future__ import annotations

import io
import json
import math
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, resample_poly, sosfiltfilt

FEATURE_SR = 16000
BANDS = np.array([125, 250, 500, 1000, 2000, 4000, 8000])
STATE_PATH = Path(__file__).parent / "cache" / "awareness_state.json"

# trained-ish rule priors for event classes (no big dataset needed for the demo)
EVENT_LABELS = ["knock", "glass_impact", "impact_thud", "baby_cry", "speech",
                "alarm_beep", "water", "unknown"]


# --------------------------------------------------------------------- audio io
def read_wav_mono(raw: bytes, target_sr: int = FEATURE_SR) -> tuple[np.ndarray, int]:
    """Read WAV (stdlib) or any libsndfile format (CAF from iOS, m4a, ...) as mono."""
    try:
        with wave.open(io.BytesIO(raw), "rb") as w:
            fs, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            frames = w.readframes(w.getnframes())
        dtype = {1: np.uint8, 2: "<i2", 4: "<i4"}.get(sw)
        if dtype is None:
            raise ValueError(f"unsupported sample width {sw}")
        x = np.frombuffer(frames, dtype=dtype).astype(np.float64)
        if sw == 1:
            x = (x - 128) / 128
        else:
            x = x / (2 ** (8 * sw - 1))
        if ch > 1:
            x = x.reshape(-1, ch).mean(axis=1)
    except Exception:
        import soundfile as sf  # handles CAF/m4a/flac via libsndfile
        x, fs = sf.read(io.BytesIO(raw), dtype="float64", always_2d=True)
        x = x.mean(axis=1)
    if fs != target_sr:
        from math import gcd
        g = gcd(int(fs), target_sr)
        x = resample_poly(x, target_sr // g, fs // g)
    return x, target_sr


def _band(x: np.ndarray, lo: float, hi: float, fs: int = FEATURE_SR) -> np.ndarray:
    hi = min(hi, fs / 2 * 0.98)
    if lo >= hi:
        return np.zeros_like(x)
    return sosfiltfilt(butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos"), x)


def _rms_db(x: np.ndarray) -> float:
    return float(20 * math.log10(math.sqrt(float(np.mean(x ** 2))) + 1e-12))


def _envelope(x: np.ndarray, fs: int = FEATURE_SR, win_ms: float = 10.0):
    win = max(1, int(fs * win_ms / 1000))
    n = len(x) // win
    if n == 0:
        return np.zeros(1), win
    frames = x[: n * win].reshape(n, win)
    return np.sqrt(np.mean(frames ** 2, axis=1)), win


def find_onset(x: np.ndarray, fs: int = FEATURE_SR) -> int:
    """First frame whose energy rises well above the noise floor (fallback: peak energy)."""
    env, win = _envelope(x, fs)
    if len(env) < 3:
        return 0
    floor = float(np.percentile(env[: max(3, len(env) // 10)], 30)) + 1e-9
    thresh = max(floor * 6.0, float(np.max(env)) * 0.25)
    for i in range(1, len(env)):
        if env[i] > thresh and env[i] > env[i - 1] * 1.8:
            return max(0, (i - 1) * win - int(0.005 * fs))
    return max(0, int(int(np.argmax(env)) * win - int(0.005 * fs)))


# --------------------------------------------------------------------- features
def _log_band_energies(x: np.ndarray) -> np.ndarray:
    if len(x) < 32:
        x = np.pad(x, (0, 32 - len(x)))
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)), n=2048)) + 1e-12
    freqs = np.fft.rfftfreq(2048, 1 / FEATURE_SR)
    out = []
    for i, fc in enumerate(BANDS):
        lo = fc / math.sqrt(2) if i else 40.0
        hi = fc * math.sqrt(2)
        m = (freqs >= lo) & (freqs < hi)
        out.append(10 * math.log10(float(np.mean(spec[m] ** 2)) + 1e-12) if m.any() else -120.0)
    return np.array(out)


def extract_features(x: np.ndarray, fs: int = FEATURE_SR) -> dict:
    """Source-aware + room-aware features from one event recording."""
    onset = find_onset(x, fs)
    seg = x[onset: onset + int(1.2 * fs)]
    if len(seg) < int(0.05 * fs):
        seg = x[: max(1, len(x))]
    peak = float(np.max(np.abs(seg))) if len(seg) else 0.0
    rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    env, win = _envelope(seg, fs)
    peak_i = int(np.argmax(env)) if len(env) else 0

    # decay after the peak (dB/s), only if there is room for it
    decay_db_s = float("nan")
    decay_20_ms = float("nan")
    if len(env) > peak_i + 5:
        tail = 20 * np.log10(env[peak_i:] + 1e-9)
        t = np.arange(len(tail)) * (win / fs)
        k = min(len(tail), int(0.4 * fs / win))
        if k > 4:
            slope = np.polyfit(t[:k], tail[:k], 1)[0]
            decay_db_s = float(-slope)
            reach = tail - tail[0]
            idx = np.where(reach <= -20)[0]
            if len(idx):
                decay_20_ms = float(idx[0] * win / fs * 1000)

    bands_db = _log_band_energies(seg[: min(len(seg), int(0.25 * fs))])
    bands_db = bands_db - np.mean(bands_db)            # shape only, level-independent
    hf = np.mean(bands_db[-3:]) - np.mean(bands_db[:2])  # brightness / through-wall cue

    spec = np.abs(np.fft.rfft(seg[: min(len(seg), 4096)] * np.hanning(min(len(seg), 4096)))) + 1e-12
    freqs = np.fft.rfftfreq(min(len(seg), 4096), 1 / fs)
    p = spec ** 2
    centroid = float(np.sum(freqs * p) / np.sum(p))
    flatness = float(np.exp(np.mean(np.log(p + 1e-12))) / (np.mean(p) + 1e-12))
    tonal = float(np.max(p) / (np.sum(p) + 1e-12))

    # modulation 2-8 Hz (speech/cry) from the 300-3000 Hz envelope
    mod = 0.0
    y = _band(seg, 300, 3000, fs)
    m_env, m_win = _envelope(np.abs(y), fs, 5.0)   # 5 ms frames
    if len(m_env) > 20:
        mf = np.abs(np.fft.rfft(m_env - m_env.mean()))
        mfreq = np.fft.rfftfreq(len(m_env), m_win / fs)
        band_m = (mfreq >= 1.5) & (mfreq <= 9)
        if band_m.any():
            mod = float(np.sum(mf[band_m]) / (np.sum(mf) + 1e-12))

    above = env > max(1e-6, 0.15 * float(np.max(env))) if len(env) else np.array([False])
    active_ms = float(np.sum(above) * win / fs * 1000)
    crest = float(peak / (rms + 1e-9))

    return {
        "onset_sample": int(onset),
        "duration_ms": round(len(seg) / fs * 1000, 1),
        "active_ms": round(active_ms, 1),
        "peak_db": round(20 * math.log10(peak + 1e-12), 1),
        "rms_db": round(20 * math.log10(rms + 1e-12), 1),
        "crest": round(crest, 2),
        "decay_db_s": None if not math.isfinite(decay_db_s) else round(decay_db_s, 1),
        "decay_20_ms": None if not math.isfinite(decay_20_ms) else round(decay_20_ms, 1),
        "bands_db": [round(float(b), 1) for b in bands_db],
        "brightness_db": round(float(hf), 1),
        "centroid_hz": round(centroid, 0),
        "flatness": round(flatness, 4),
        "tonality": round(tonal, 4),
        "modulation": round(mod, 3),
    }


def feature_vector(f: dict) -> np.ndarray:
    """Room-transfer signature: source-independent-ish shape cues."""
    bands = np.array(f["bands_db"], dtype=float)
    v = np.concatenate([
        bands / 12.0,
        [f["brightness_db"] / 12.0,
         (f["decay_db_s"] or 30.0) / 120.0,
         (f["crest"] - 5.0) / 15.0,
         f["modulation"],
         f["flatness"] * 5.0],
    ])
    return v


# --------------------------------------------------------------------- classifier
def _rule_scores(f: dict) -> dict:
    s = {k: 0.0 for k in EVENT_LABELS}
    cent = f["centroid_hz"]
    dur = f["active_ms"]
    crest = f["crest"]
    flat = f["flatness"]
    mod = f["modulation"]
    dec = f["decay_db_s"] or 30.0
    tonal = f["tonality"]

    # sharp transient classes
    if dur < 450 and crest > 3.5:
        if cent > 2400:
            s["glass_impact"] += 1.6
        elif 250 <= cent <= 2400:
            s["knock"] += 1.4
            if dec > 60:
                s["knock"] += 0.4
        elif cent < 250:
            s["impact_thud"] += 1.5
    # sustained periodic: cry vs speech vs alarm
    if dur > 450:
        if tonal > 0.40 and dur > 600:                  # steady pure tone -> alarm
            s["alarm_beep"] += 2.2
        elif 250 <= cent <= 1300 and mod > 0.06:
            s["baby_cry"] += 1.3 + 2.0 * mod
        elif 300 <= cent <= 4200 and mod > 0.06 and tonal < 0.35:
            s["speech"] += 0.9 + mod
        if flat > 0.10 and crest < 3.0:                 # broadband, steady -> water
            s["water"] += 1.1
    return s


def classify_event(f: dict, templates: dict[str, list[list[float]]] | None = None) -> dict:
    scores = _rule_scores(f)
    if templates:
        v = feature_vector(f)
        for label, examples in templates.items():
            if not examples:
                continue
            d = min(float(np.linalg.norm(v - np.array(e))) for e in examples)
            scores[label] = scores.get(label, 0.0) + max(0.0, 1.5 - d)
    total = sum(max(0.0, s) for s in scores.values()) or 1.0
    ranked = sorted(((k, max(0.0, v)) for k, v in scores.items()), key=lambda kv: -kv[1])
    top_label, top_score = ranked[0]
    confidence = round(top_score / total, 2)
    return {"label": top_label if top_score > 0.4 else "unknown",
            "confidence": confidence,
            "ranking": [{"label": k, "score": round(v, 2)} for k, v in ranked[:4]]}


# --------------------------------------------------------------------- session
def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"rooms": {}, "templates": {}, "events": []}


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


class Session:
    def __init__(self):
        self.state = _load_state()

    def reset(self):
        self.state = {"rooms": {}, "templates": {}, "events": []}
        _save_state(self.state)

    def enroll(self, room_id: str, room_name: str, clips: list[bytes]) -> dict:
        vectors, feats = [], []
        for raw in clips:
            x, _ = read_wav_mono(raw)
            f = extract_features(x)
            vectors.append(feature_vector(f))
            feats.append(f)
        if not vectors:
            raise ValueError("no usable clips")
        v = np.mean(np.stack(vectors), axis=0)
        room = self.state["rooms"].get(room_id, {"id": room_id, "name": room_name, "n": 0})
        room["name"] = room_name
        room["n"] += len(vectors)
        room["vector"] = v.tolist()
        room["level_db"] = round(float(np.mean([f["peak_db"] for f in feats])), 1)
        room["decay_db_s"] = round(float(np.mean([f["decay_db_s"] or 30 for f in feats])), 1)
        self.state["rooms"][room_id] = room
        _save_state(self.state)
        return room

    def teach(self, label: str, clips: list[bytes]) -> dict:
        self.state["templates"].setdefault(label, [])
        for raw in clips:
            x, _ = read_wav_mono(raw)
            self.state["templates"][label].append(feature_vector(extract_features(x)).tolist())
        _save_state(self.state)
        return {"label": label, "examples": len(self.state["templates"][label])}

    def attribute_room(self, f: dict) -> dict:
        rooms = self.state["rooms"]
        if not rooms:
            return {"room_id": None, "room_name": None, "confidence": 0.0, "ranking": []}
        v = feature_vector(f)
        scored = []
        for rid, r in rooms.items():
            rv = np.array(r["vector"])
            dist = float(np.linalg.norm(v - rv))
            scored.append((dist, rid, r["name"]))
        scored.sort()
        best_d, best_id, best_name = scored[0]
        conf = 1.0 / (1.0 + best_d)
        if len(scored) > 1:
            margin = scored[1][0] - best_d
            conf = min(1.0, conf * (0.6 + min(1.0, margin)))
        return {"room_id": best_id, "room_name": best_name,
                "confidence": round(conf, 2),
                "ranking": [{"room": n, "distance": round(d, 3)} for d, _, n in scored[:4]]}

    def detect(self, raw: bytes) -> dict:
        x, _ = read_wav_mono(raw)
        f = extract_features(x)
        event = classify_event(f, self.state.get("templates"))
        where = self.attribute_room(f)
        rec = {"event": event, "room": where, "features": f}
        self.state["events"] = (self.state["events"] + [rec])[-50:]
        _save_state(self.state)
        return rec

    def summary(self) -> dict:
        return {"rooms": [{"id": r["id"], "name": r["name"], "examples": r["n"]}
                          for r in self.state["rooms"].values()],
                "templates": {k: len(v) for k, v in self.state["templates"].items()},
                "events": [{"label": e["event"]["label"], "room": e["room"]["room_name"],
                            "confidence": e["event"]["confidence"]}
                           for e in self.state["events"][-8:]]}
