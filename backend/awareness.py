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
from scipy.signal import butter, resample_poly, sosfiltfilt, fftconvolve

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


# --------------------------------------------------------------------- mfcc / noise
N_MELS, N_MFCC, N_FFT = 26, 13, 512


def _mel_filterbank() -> np.ndarray:
    def hz2mel(h): return 2595.0 * math.log10(1.0 + h / 700.0)
    def mel2hz(m): return 700.0 * (10 ** (m / 2595.0) - 1.0)
    lo, hi = hz2mel(80.0), hz2mel(min(7600.0, FEATURE_SR / 2 - 100))
    pts = mel2hz(np.linspace(lo, hi, N_MELS + 2))
    bins = np.floor((N_FFT + 1) * pts / FEATURE_SR).astype(int)
    fb = np.zeros((N_MELS, N_FFT // 2 + 1))
    for m in range(1, N_MELS + 1):
        l, c, r = bins[m - 1], bins[m], bins[m + 1]
        for k in range(l, c):
            fb[m - 1, k] = (k - l) / max(1, c - l)
        for k in range(c, r):
            fb[m - 1, k] = (r - k) / max(1, r - c)
    return fb


MEL_FB = _mel_filterbank()


def mfcc(x: np.ndarray, fs: int = FEATURE_SR, n_frames: int = 40) -> np.ndarray:
    """Mean MFCC vector (13) — cepstral coloration is a classic room fingerprint."""
    win, hop = int(0.025 * fs), int(0.010 * fs)
    if len(x) < win:
        x = np.pad(x, (0, win - len(x)))
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    if len(frames) > n_frames:
        frames = frames[:n_frames]
    spec = np.abs(np.fft.rfft(frames * np.hanning(win), n=N_FFT)) ** 2
    mel = np.log(spec @ MEL_FB.T + 1e-10)
    from scipy.fft import dct
    ceps = dct(mel, type=2, axis=1)[:, 1:N_MFCC + 1]
    return ceps.mean(axis=0)


def _frame_band_energies(x: np.ndarray, fs: int = FEATURE_SR):
    """Per-frame octave-band dB energies (for noise-floor and SNR estimation)."""
    win, hop = int(0.030 * fs), int(0.010 * fs)
    if len(x) < win:
        x = np.pad(x, (0, win - len(x)))
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    spec = np.abs(np.fft.rfft(frames * np.hanning(win), n=1024)) ** 2
    freqs = np.fft.rfftfreq(1024, 1 / fs)
    out = []
    for fc in BANDS:
        m = (freqs >= fc / math.sqrt(2)) & (freqs < fc * math.sqrt(2))
        out.append(10 * np.log10(spec[:, m].sum(axis=1) + 1e-12) if m.any() else np.full(len(frames), -120.0))
    return np.stack(out, axis=1), win / fs  # [frames, bands]


def noise_and_snr(x: np.ndarray, onset: int, fs: int = FEATURE_SR) -> dict:
    """Estimate the room's noise floor and the event's per-band SNR.

    Noise floor = per-band energy of the pre-onset segment (silence before the sound).
    Event energy = peak per-band frame energy in the active window. Using pre-onset
    silence avoids the bias that a 15th-percentile over the whole clip has when the
    event dominates the recording.
    """
    frames, frame_dur = _frame_band_energies(x, fs)
    onset_frame = int(onset / fs / frame_dur)
    pre = frames[: max(1, min(onset_frame, len(frames)))]
    if len(pre) >= 2:
        noise = np.percentile(pre, 50, axis=0)
    else:  # no pre-roll: fall back to the quietest frames
        noise = np.percentile(frames, 15, axis=0)
    t0, t1 = onset_frame, min(len(frames), onset_frame + max(1, int(0.5 / frame_dur)))
    event = frames[t0:t1].max(axis=0) if t1 > t0 else frames.max(axis=0)
    snr_band = np.clip(event - noise, -10, 60)

    # broadband SNR from time-domain RMS: pre-event silence vs active segment
    pre_n = int(0.35 * fs)
    pre_sig = x[max(0, onset - pre_n):onset]
    seg = x[onset: onset + int(0.5 * fs)]
    if len(pre_sig) > 64 and len(seg) > 64:
        noise_rms = float(np.sqrt(np.mean(pre_sig ** 2))) + 1e-9
        snr_db = 10 * math.log10(float(np.mean(seg ** 2)) / (noise_rms ** 2) + 1e-12)
    else:
        snr_db = float(np.median(snr_band))
    return {
        "noise_floor_db": [round(float(v), 1) for v in noise],
        "snr_band_db": [round(float(v), 1) for v in snr_band],
        "snr_db": round(float(np.clip(snr_db, -20, 100)), 1),
    }


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


def early_decay(x: np.ndarray, fs: int = FEATURE_SR) -> float | None:
    """Decay rate (dB/s) fitted only over -5..-25 dB of the 300-6000 Hz envelope.

    Room identity lives in reverberation, but the *late* tail is exactly where noise
    lives. Restricting the fit to the first 25 dB keeps the fingerprint usable at
    moderate SNR (classical EDT/T20-style practice).
    """
    y = _band(x, 300, 6000, fs)
    env, win = _envelope(np.abs(y), fs, 5.0)
    if len(env) < 12:
        return None
    db = 20 * np.log10(env + 1e-12)
    db = db - db.max()
    idx = np.where((db <= -5) & (db >= -25))[0]
    if len(idx) < 8:
        return None
    slope = np.polyfit(idx * (win / fs), db[idx], 1)[0]
    return float(-slope) if slope < 0 else None


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
    snr_info = noise_and_snr(x, onset, fs)
    mfcc_mean = mfcc(seg[: int(0.5 * fs)], fs)

    return {
        "onset_sample": int(onset),
        "duration_ms": round(len(seg) / fs * 1000, 1),
        "active_ms": round(active_ms, 1),
        "peak_db": round(20 * math.log10(peak + 1e-12), 1),
        "rms_db": round(20 * math.log10(rms + 1e-12), 1),
        "crest": round(crest, 2),
        "decay_db_s": None if not math.isfinite(decay_db_s) else round(decay_db_s, 1),
        "early_decay_db_s": None if early_decay(seg, fs) is None else round(early_decay(seg, fs), 1),
        "decay_20_ms": None if not math.isfinite(decay_20_ms) else round(decay_20_ms, 1),
        "bands_db": [round(float(b), 1) for b in bands_db],
        "brightness_db": round(float(hf), 1),
        "centroid_hz": round(centroid, 0),
        "flatness": round(flatness, 4),
        "tonality": round(tonal, 4),
        "modulation": round(mod, 3),
        "mfcc": [round(float(v), 2) for v in mfcc_mean],
        **snr_info,
    }


def source_vector(f: dict) -> np.ndarray:
    """Features for WHAT happened — noise-normalised, so low-SNR events stay separable."""
    snr = np.clip(np.array(f["snr_band_db"], dtype=float), -5, 45) / 20.0
    bright = (np.mean(snr[-3:]) - np.mean(snr[:2]))
    return np.concatenate([
        snr,
        [bright,
         (f["crest"] - 5.0) / 15.0,
         f["modulation"],
         f["flatness"] * 5.0,
         f["tonality"] * 3.0,
         min(f["active_ms"], 3000.0) / 1000.0],
    ])


def room_vector(f: dict) -> np.ndarray:
    """Features for WHERE it happened — cepstral coloration + reverberant decay."""
    mf = np.array(f["mfcc"], dtype=float) / 8.0
    decay = (f.get("early_decay_db_s") or f["decay_db_s"] or 30.0) / 60.0
    bright = f["brightness_db"] / 10.0
    dur = math.log1p(max(f["active_ms"], 1.0)) / 3.0
    return np.concatenate([mf, [decay, bright, dur]])



# --------------------------------------------------------------------- Apple sound labels
# Apple's SoundAnalysis classifier (303 classes) runs on-device; the app sends its top labels.
APPLE_LABEL_MAP = {
    # glass / breakage
    "glass_breaking": "glass_impact", "glass_clink": "glass_impact",
    # knocks / doors / impacts
    "knock": "knock", "door": "knock",
    "thump_thud": "impact_thud", "door_slam": "impact_thud",
    "drawer_open_or_close": "impact_thud", "cupboard_open_or_close": "impact_thud",
    # voices
    "baby_crying": "baby_cry", "crying_sobbing": "baby_cry",
    "speech": "speech", "conversation": "speech", "whispering": "speech",
    # alarms / alerts
    "alarm_clock": "alarm_beep", "telephone_bell_ringing": "alarm_beep",
    "reverse_beeps": "alarm_beep", "beep": "alarm_beep",
    "siren": "alarm_beep", "police_siren": "alarm_beep",
    "ambulance_siren": "alarm_beep", "fire_engine_siren": "alarm_beep",
    "civil_defense_siren": "alarm_beep", "smoke_detector": "alarm_beep",
    "door_bell": "alarm_beep", "buzzer": "alarm_beep",
    # water
    "water": "water", "waterfall": "water", "water_tap_faucet": "water",
    "liquid_dripping": "water", "liquid_pouring": "water",
    "liquid_trickle_dribble": "water", "liquid_splashing": "water",
    "liquid_sloshing": "water", "liquid_filling_container": "water",
    "liquid_spraying": "water", "liquid_squishing": "water",
}


def event_from_heard(heard: list[dict]) -> dict | None:
    """Map on-device Apple classifier labels to our event label (best confidence wins)."""
    best = None
    for item in heard:
        label = str(item.get("label", "")).strip().lower()
        conf = float(item.get("confidence", 0.0))
        mapped = APPLE_LABEL_MAP.get(label)
        if mapped and conf >= 0.15 and (best is None or conf > best[1]):
            best = (mapped, conf, label)
    if best is None:
        return None
    return {"label": best[0], "confidence": round(best[1], 2), "heard_as": best[2],
            "source": "apple_sound_analysis"}

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
        v = source_vector(f)
        for label, examples in templates.items():
            if not examples:
                continue
            d = min(float(np.linalg.norm(v - np.array(e))) for e in examples)
            scores[label] = scores.get(label, 0.0) + max(0.0, 1.5 - d)
    total = sum(max(0.0, s) for s in scores.values()) or 1.0
    ranked = sorted(((k, max(0.0, v)) for k, v in scores.items()), key=lambda kv: -kv[1])
    top_label, top_score = ranked[0]
    confidence = round(top_score / total, 2)
    # Signal-quality gate: do not confidently label sounds that are near the noise floor.
    snr = float(f.get("snr_db", 30.0))
    if snr < 4.0:
        return {"label": "unknown", "confidence": 0.0, "reason": "low_snr",
                "snr_db": snr,
                "ranking": [{"label": k, "score": round(v, 2)} for k, v in ranked[:4]]}
    confidence = round(min(1.0, confidence * max(0.25, min(1.0, (snr - 2) / 18.0))), 2)
    return {"label": top_label if top_score > 0.4 else "unknown",
            "confidence": confidence, "snr_db": snr,
            "ranking": [{"label": k, "score": round(v, 2)} for k, v in ranked[:4]]}


# --------------------------------------------------------------------- session
def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text())
            if state.get("version") != 2:
                return {"version": 2, "rooms": {}, "templates": {}, "events": []}
            return state
        except Exception:
            pass
    return {"version": 2, "rooms": {}, "templates": {}, "events": []}


def _save_state(state: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1))


# ---------------------------------------------------------------- probe-seeded enrollment
GENERIC_EVENT_KINDS = ("knock", "glass", "cry", "alarm", "speech", "water")


def generic_kernel(kind: str, seed: int = 0, fs: int = FEATURE_SR) -> np.ndarray:
    """A neutral, room-independent event waveform used to synthesize room templates."""
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
        x += 0.05 * sosfiltfilt(butter(4, [300, 3000], "bandpass", fs=fs, output="sos"),
                                r.normal(0, 1, n)) * env
    elif kind == "water":
        x += 0.02 * sosfiltfilt(butter(4, [200, 4000], "bandpass", fs=fs, output="sos"),
                                r.normal(0, 1, n))
    return x


def room_vector_from_rir(rir: np.ndarray, fs: int) -> dict:
    """Synthesize room templates by convolving neutral event kernels with a measured RIR.

    This is what makes a single active probe enough to enroll a room: the phone measures the
    true impulse response once, and we can predict how any event would colour in that room.
    """
    from math import gcd
    from scipy.signal import resample_poly
    if fs != FEATURE_SR:
        g = gcd(int(fs), FEATURE_SR)
        rir = resample_poly(rir, FEATURE_SR // g, fs // g)
    rir = np.asarray(rir, dtype=float)
    peak = np.max(np.abs(rir))
    if not np.isfinite(peak) or peak <= 0:
        raise ValueError("unusable RIR")
    rir = rir / peak
    vecs, feats = [], []
    for i, kind in enumerate(GENERIC_EVENT_KINDS):
        y = fftconvolve(generic_kernel(kind, seed=i), rir)[: int(2.4 * FEATURE_SR)]
        y = y + np.random.default_rng(100 + i).normal(0, 1e-3, len(y))
        f = extract_features(y)
        vecs.append(room_vector(f))
        feats.append(f)
    v = np.mean(np.stack(vecs), axis=0)
    return {
        "rvec": v.tolist(),
        "decay_db_s": round(float(np.mean([f.get("decay_db_s") or 30 for f in feats])), 1),
        "snr_db": 30.0,
        "level_db": round(float(np.mean([f["peak_db"] for f in feats])), 1),
        "n_events": len(vecs),
    }


class Session:
    def __init__(self):
        self.state = _load_state()

    def reset(self):
        self.state = {"version": 2, "rooms": {}, "templates": {}, "events": []}
        _save_state(self.state)

    def enroll(self, room_id: str, room_name: str, clips: list[bytes]) -> dict:
        vectors, feats = [], []
        for raw in clips:
            x, _ = read_wav_mono(raw)
            f = extract_features(x)
            vectors.append(room_vector(f))
            feats.append(f)
        if not vectors:
            raise ValueError("no usable clips")
        v = np.mean(np.stack(vectors), axis=0)
        room = self.state["rooms"].get(room_id, {"id": room_id, "name": room_name, "n": 0})
        room["name"] = room_name
        room["n"] += len(vectors)
        room["rvec"] = v.tolist()
        room["snr_db"] = round(float(np.mean([f.get("snr_db", 30) for f in feats])), 1)
        room["level_db"] = round(float(np.mean([f["peak_db"] for f in feats])), 1)
        room["decay_db_s"] = round(float(np.mean([f["decay_db_s"] or 30 for f in feats])), 1)
        self.state["rooms"][room_id] = room
        _save_state(self.state)
        return room

    def set_probe_baseline(self, room_id: str, t30_mid_s: float | None,
                           rt60_mid_s: float | None) -> dict:
        """Attach the active-probe measurement to a room (source-independent decay truth)."""
        room = self.state["rooms"].get(room_id)
        if room is None:
            room = {"id": room_id, "name": room_id, "n": 0}
        if t30_mid_s is not None:
            room["probe_t30"] = float(t30_mid_s)
        if rt60_mid_s is not None:
            room["probe_rt60"] = float(rt60_mid_s)
        self.state["rooms"][room_id] = room
        _save_state(self.state)
        return {"room_id": room_id, "probe_t30": room.get("probe_t30"),
                "probe_rt60": room.get("probe_rt60")}

    def enroll_from_probe(self, room_id: str, room_name: str,
                          rir: np.ndarray, rir_fs: int) -> dict:
        """Enroll a room from its measured impulse response alone (no knocks needed)."""
        seeded = room_vector_from_rir(rir, rir_fs)
        room = self.state["rooms"].get(room_id, {"id": room_id, "name": room_name, "n": 0})
        room.update({"name": room_name, "rvec": seeded["rvec"],
                     "decay_db_s": seeded["decay_db_s"],
                     "snr_db": seeded["snr_db"], "level_db": seeded["level_db"],
                     "probe_seeded": True})
        self.state["rooms"][room_id] = room
        _save_state(self.state)
        return room

    def teach(self, label: str, clips: list[bytes]) -> dict:
        self.state["templates"].setdefault(label, [])
        for raw in clips:
            x, _ = read_wav_mono(raw)
            self.state["templates"][label].append(source_vector(extract_features(x)).tolist())
        _save_state(self.state)
        return {"label": label, "examples": len(self.state["templates"][label])}

    def attribute_room(self, f: dict, event_label: str = "") -> dict:
        rooms = self.state["rooms"]
        if not rooms:
            return {"room_id": None, "room_name": None, "confidence": 0.0,
                    "uncertain": True, "ranking": [], "reason": "no_rooms"}
        vectors, ids, names = [], [], []
        for rid, r in rooms.items():
            if "rvec" not in r:            # legacy record
                continue
            vectors.append(r["rvec"]); ids.append(rid); names.append(r["name"])
        if not vectors:
            return {"room_id": None, "room_name": None, "confidence": 0.0,
                    "uncertain": True, "ranking": [], "reason": "no_rooms"}
        R = np.array(vectors)
        if len(R) == 1:
            return {"room_id": ids[0], "room_name": names[0], "confidence": 1.0,
                    "uncertain": False, "distance": 0.0, "reason": "single_room",
                    "ranking": [{"room": names[0], "distance": 0.0, "p": 1.0}]}
        # Physical, noise-robust metric: early decay (room tail before noise dominates),
        # spectral brightness (wall low-pass), and cepstral cosine (coloration).
        ev_dec = f.get("early_decay_db_s")
        if ev_dec is None or not math.isfinite(float(ev_dec)) or float(ev_dec) <= 0:
            ev_dec = f.get("decay_db_s")
        if ev_dec is None or not math.isfinite(float(ev_dec)) or float(ev_dec) <= 0:
            ev_dec = 30.0
        ev_dec = float(ev_dec)
        ev_br = float(f["brightness_db"])
        ev_mf = np.array(f["mfcc"], dtype=float)
        d = []
        for idx, rv in enumerate(R):
            rid = ids[idx]
            probe_t30 = self.state["rooms"].get(rid, {}).get("probe_t30")
            enrolled_dec = float(rv[13] * 60.0)
            mode = getattr(self, "probe_decay_mode", "ignore")
            if probe_t30 and mode == "replace":
                r_dec = float(probe_t30)
            elif probe_t30 and mode == "blend":
                r_dec = 0.5 * (enrolled_dec + float(probe_t30))
            else:
                r_dec = enrolled_dec
            r_br = float(rv[14] * 10.0)
            r_mf = rv[:13]
            cos = float(np.dot(ev_mf, r_mf) /
                        (np.linalg.norm(ev_mf) * np.linalg.norm(r_mf) + 1e-9))
            log_ratio = abs(math.log(max(ev_dec + 1.0, 1e-3) / max(r_dec + 1.0, 1e-3)))
            d.append(2.0 * log_ratio
                     + 0.5 * abs(ev_br - r_br) / 6.0
                     + 1.0 * (1.0 - cos))
        d = np.array(d)
        p = np.exp(-(d - d.min()) / 0.6)
        p = p / p.sum()
        order = np.argsort(-p)
        conf = float(p[order[0]])
        margin = float(p[order[0]] - p[order[1]])
        snr_ev = float(f.get("snr_db", 30.0))
        # Below ~25 dB the reverberant tail is buried in noise: say "uncertain" instead of guessing.
        sustained = event_label in {"baby_cry", "speech", "water", "alarm_beep"}
        low_snr = snr_ev < 25.0
        uncertain = bool(conf < 0.50 or margin < 0.15 or low_snr or (sustained and len(R) < 3))
        reason = None
        if low_snr: reason = "low_snr"
        elif sustained: reason = "needs_room_sample"
        return {"room_id": ids[order[0]], "room_name": names[order[0]],
                "confidence": round(conf, 2), "uncertain": uncertain,
                "distance": round(float(d[order[0]]), 2), "reason": reason,
                "snr_db": round(snr_ev, 1),
                "ranking": [{"room": names[i], "distance": round(float(d[i]), 2),
                             "p": round(float(p[i]), 2)} for i in order[:4]]}

    def detect(self, raw: bytes, heard: list[dict] | None = None) -> dict:
        x, _ = read_wav_mono(raw)
        f = extract_features(x)
        event = classify_event(f, self.state.get("templates"))
        heard_event = event_from_heard(heard or [])
        if heard_event:
            heard_event["snr_db"] = event.get("snr_db")
            heard_event["ranking"] = event.get("ranking", [])
            event = heard_event
        where = self.attribute_room(f, event_label=event["label"])
        if where.get("uncertain"):
            where["room_name"] = where.get("room_name")
        rec = {"event": event, "room": where, "heard": heard or [],
               "certainty": round(event["confidence"] * where["confidence"], 2),
               "features": f}
        self.state["events"] = (self.state["events"] + [rec])[-50:]
        _save_state(self.state)
        return rec

    def summary(self) -> dict:
        return {"rooms": [{"id": r["id"], "name": r["name"], "examples": r["n"]}
                          for r in self.state["rooms"].values()],
                "templates": {k: len(v) for k, v in self.state["templates"].items()},
                "events": [{"label": e["event"]["label"], "room": e["room"]["room_name"],
                            "confidence": e["event"]["confidence"],
                            "snr_db": e["features"].get("snr_db"),
                            "heard_as": e["event"].get("heard_as")}
                           for e in self.state["events"][-8:]]}


# --------------------------------------------------------------- test helpers
def wav_bytes(x: np.ndarray, fs: int = FEATURE_SR) -> bytes:
    """Serialise float samples to mono 16-bit WAV (used by tests/evaluation)."""
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(fs)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()
