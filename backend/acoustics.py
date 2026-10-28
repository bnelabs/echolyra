"""Echolyra hackathon backend — acoustic measurement, inversion, plan, auralization.

Deliberately dependency-light: numpy + scipy (+ pyroomacoustics only for the demo
simulation of an untreated room, which can be replaced by a cached RIR).
"""
from __future__ import annotations

import io
import math
import wave
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, fftconvolve, sosfiltfilt

FS = 48000
BANDS = [125, 250, 500, 1000, 2000, 4000]
BAND_LABELS = ["125", "250", "500", "1k", "2k", "4k"]

# absorption priors per material class and octave band (125..4k) — ISO 354 / vendor data
MATERIAL_PRIORS: dict[str, list[float]] = {
    "drywall":   [0.10, 0.10, 0.06, 0.04, 0.04, 0.05],
    "plaster":   [0.02, 0.02, 0.02, 0.03, 0.04, 0.05],
    "wood":      [0.15, 0.11, 0.10, 0.07, 0.06, 0.07],
    "carpet":    [0.08, 0.24, 0.57, 0.69, 0.71, 0.73],
    "rug":       [0.05, 0.15, 0.35, 0.45, 0.50, 0.50],
    "curtain":   [0.05, 0.06, 0.39, 0.63, 0.70, 0.73],
    "glass":     [0.35, 0.25, 0.18, 0.12, 0.07, 0.04],
    "sofa":      [0.20, 0.30, 0.40, 0.45, 0.45, 0.45],
    "bookshelf": [0.15, 0.25, 0.35, 0.40, 0.45, 0.45],
    "panel_2in": [0.10, 0.25, 0.60, 0.80, 0.85, 0.85],
    "bass_trap": [0.35, 0.55, 0.65, 0.60, 0.50, 0.45],
}

# a small treatment catalog (hackathon stub — expand with real SKUs post-hackathon)
CATALOG = [
    {"id": "panel_2in_2x4", "name": "2\" acoustic panel, 2'x4'", "area_m2": 0.557,
     "alpha": [0.10, 0.25, 0.60, 0.80, 0.85, 0.85], "price_usd": 45},
    {"id": "bass_trap_corner", "name": "corner bass trap", "area_m2": 0.30,
     "alpha": [0.35, 0.55, 0.65, 0.60, 0.50, 0.45], "price_usd": 90},
    {"id": "rug_2x3", "name": "wool rug, 2x3 m", "area_m2": 6.0,
     "alpha": [0.05, 0.15, 0.35, 0.45, 0.50, 0.50], "price_usd": 180},
    {"id": "curtain_heavy", "name": "heavy curtain (per m²)", "area_m2": 1.0,
     "alpha": [0.05, 0.06, 0.39, 0.63, 0.70, 0.73], "price_usd": 35},
]


# --------------------------------------------------------------------- signals
def exp_sweep(T: float = 4.0, f1: float = 40.0, f2: float = 20000.0, fs: int = FS) -> np.ndarray:
    t = np.arange(int(T * fs)) / fs
    K = math.log(f2 / f1) / T
    return np.sin(2 * math.pi * f1 * (np.exp(K * t) - 1) / K)


def farina_inverse(sweep: np.ndarray, f1: float = 40.0, f2: float = 20000.0, fs: int = FS) -> np.ndarray:
    T = len(sweep) / fs
    K = math.log(f2 / f1) / T
    t = np.arange(len(sweep)) / fs
    inv = sweep[::-1] * np.exp(-K * t) * (K / (1 - math.exp(-K * T)))
    return inv / np.sqrt(np.sum(inv ** 2))


def deconvolve(recording: np.ndarray, sweep: np.ndarray, fs: int = FS,
               tail_s: float = 1.5, pre_ms: float = 5.0) -> np.ndarray:
    """ESS deconvolution, auto-aligned on the direct-path peak.

    Phones cannot start recording and playback at the same sample, so the upload has an
    arbitrary pre-roll. The deconvolved signal has a sharp direct-path peak; we align on it
    instead of assuming a fixed offset (which would silently truncate the RIR head).
    """
    h = fftconvolve(recording, farina_inverse(sweep, fs=fs))
    if len(h) == 0:
        return h
    peak = int(np.argmax(np.abs(h)))
    start = max(0, peak - int(pre_ms * 1e-3 * fs))
    out = h[start: start + int(tail_s * fs)]
    if len(out) == 0:
        return out
    return out - np.mean(out[: min(300, len(out))])


def _octave(x: np.ndarray, fc: float, fs: int = FS) -> np.ndarray:
    lo, hi = fc / math.sqrt(2), min(fc * math.sqrt(2), 0.98 * fs / 2)
    return sosfiltfilt(butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos"), x)


def schroeder_curve(rir: np.ndarray, fc: float, fs: int = FS) -> np.ndarray:
    y = _octave(rir, fc, fs)
    e = np.cumsum(y[::-1] ** 2)[::-1]
    if e[0] <= 0:
        return np.array([])
    return 10 * np.log10(np.maximum(e / e[0], 1e-12))


def decay_time(rir: np.ndarray, fc: float, lo_db: float, hi_db: float, fs: int = FS) -> float:
    edc = schroeder_curve(rir, fc, fs)
    if len(edc) == 0:
        return float("nan")
    # lo_db is the start of the fit range (e.g. -5), hi_db the end (e.g. -35)
    idx = np.where((edc <= lo_db) & (edc >= hi_db))[0]
    if len(idx) < 64:
        return float("nan")
    slope = np.polyfit(idx / fs, edc[idx], 1)[0]
    return float(-60.0 / slope) if slope < 0 else float("nan")


def clarity(rir: np.ndarray, fc: float, fs: int = FS) -> float:
    y = _octave(rir, fc, fs)
    n = int(0.05 * fs)
    e = np.cumsum(y ** 2)
    early = e[min(n, len(e) - 1)]
    late = max(e[-1] - early, 1e-14)
    return float(10 * math.log10(max(early, 1e-14) / late))


def analyze_rir(rir: np.ndarray, fs: int = FS) -> dict:
    """Per-octave EDT/T30, C50 and DRR from one measured RIR."""
    out = {"bands": BAND_LABELS, "edt_s": [], "t30_s": [], "c50_db": []}
    for fc in BANDS:
        out["edt_s"].append(decay_time(rir, fc, 0, -10, fs))
        out["t30_s"].append(decay_time(rir, fc, -5, -35, fs))
        out["c50_db"].append(clarity(rir, fc, fs))
    t30 = np.array(out["t30_s"], dtype=float)
    out["rt60_mid_s"] = float(np.nanmedian(t30[2:4])) if np.isfinite(t30[2:4]).any() else float("nan")
    return out


# --------------------------------------------------------------------- geometry
@dataclass
class Surface:
    id: str
    area_m2: float
    material: str


@dataclass
class Room:
    name: str
    length: float
    width: float
    height: float
    surfaces: list[Surface] = field(default_factory=list)

    @property
    def volume(self) -> float:
        return self.length * self.width * self.height

    @property
    def total_area(self) -> float:
        return sum(s.area_m2 for s in self.surfaces)


def default_room(name: str = "demo living room", L: float = 5.2, W: float = 4.0, H: float = 2.6) -> Room:
    """A furnished room where the user has a hard back wall and a curtained side wall."""
    return Room(name, L, W, H, [
        Surface("floor", L * W, "wood"),
        Surface("ceiling", L * W, "plaster"),
        Surface("left", W * H, "curtain"),
        Surface("right", W * H, "drywall"),
        Surface("front", L * H, "drywall"),
        Surface("back", L * H, "drywall"),
    ])


def room_from_json(d: dict) -> Room:
    surfaces = [Surface(s["id"], float(s.get("area_m2", s.get("area", 0))), s.get("material", "drywall"))
                for s in d.get("surfaces", [])]
    room = Room(d.get("name", "room"), float(d["length"]), float(d["width"]), float(d["height"]), surfaces)
    if not room.surfaces:  # derive standard 6-surface room from dimensions
        room = default_room(room.name, room.length, room.width, room.height)
        for s in room.surfaces:  # keep any material overrides
            for given in d.get("surfaces", []):
                if given.get("id") == s.id:
                    s.material = given.get("material", s.material)
    return room


def room_to_json(room: Room) -> dict:
    return {"name": room.name, "length": room.length, "width": room.width, "height": room.height,
            "volume_m3": round(room.volume, 2),
            "surfaces": [{"id": s.id, "area_m2": round(s.area_m2, 2), "material": s.material}
                         for s in room.surfaces]}


# --------------------------------------------------------- vision -> materials
CONCEPT_TO_MATERIAL = {"window": "glass", "curtain": "curtain", "rug": "rug",
                       "sofa": "sofa", "wall": "drywall", "wood floor": "wood"}


def apply_vision_prior(room: Room, material_shares: dict, min_share: float = 0.05) -> dict:
    """Use SAM 3.1 area shares to set plausible surface materials before inversion.

    Hackathon mapping: a detected curtain/window/rug upgrades one compatible surface so the
    material priors (and therefore the inversion) change based on what the vision model saw.
    """
    applied = []
    walls = [s for s in room.surfaces if s.id not in ("floor", "ceiling")]
    for concept, share in sorted(material_shares.items(), key=lambda kv: -kv[1]):
        mat = CONCEPT_TO_MATERIAL.get(concept)
        if not mat or share < min_share:
            continue
        if mat == "rug" and any(s.id == "floor" for s in room.surfaces):
            floor = next(s for s in room.surfaces if s.id == "floor")
            if floor.material != "rug":
                floor.material = "rug"
                applied.append({"concept": concept, "surface": "floor", "material": "rug", "share": share})
        elif mat in ("curtain", "glass") and walls:
            target = max(walls, key=lambda s: s.area_m2)
            if target.material == "drywall":
                target.material = mat
                applied.append({"concept": concept, "surface": target.id, "material": mat, "share": share})
    return {"applied": applied, "material_shares": material_shares}


# --------------------------------------------------------------------- inversion
def _prior(material: str, band: int) -> float:
    return float(MATERIAL_PRIORS.get(material, MATERIAL_PRIORS["drywall"])[band])


def _eyring_alpha(rt60: float, volume: float, total_area: float) -> float:
    """Solve Eyring: RT = 0.161 V / (-S ln(1-alpha))  ->  alpha_bar."""
    if not np.isfinite(rt60) or rt60 <= 0:
        return float("nan")
    x = 0.161 * volume / (rt60 * max(total_area, 1e-6))
    return float(1 - math.exp(-x))


def invert_surfaces(metrics: dict, room: Room) -> dict:
    """Per-band per-surface absorption estimate.

    Hackathon version: measured RT60 -> total required absorption per band (Eyring),
    then distribute over surfaces by scaling the material priors multiplicatively.
    Returns alpha per surface + a heuristic confidence based on decay-curve quality.
    """
    rt = np.array(metrics.get("t30_s", [float("nan")] * len(BANDS)), dtype=float)
    out = {"bands": BAND_LABELS, "alpha": {s.id: [] for s in room.surfaces},
           "confidence": [], "total_absorption_m2": []}
    S = room.total_area
    for bi, fc in enumerate(BANDS):
        a_bar = _eyring_alpha(rt[bi], room.volume, S) if np.isfinite(rt[bi]) else float("nan")
        prior = np.array([_prior(s.material, bi) for s in room.surfaces], dtype=float)
        area = np.array([s.area_m2 for s in room.surfaces], dtype=float)
        f_prior = -np.log(np.maximum(1 - prior, 1e-3))
        need = -math.log(max(1 - a_bar, 1e-3)) if np.isfinite(a_bar) else float("nan")
        if np.isfinite(need) and np.sum(area * f_prior) > 0:
            k = (S * need) / float(np.sum(area * f_prior))
            alpha = 1 - np.power(np.maximum(1 - prior, 1e-3), k)
        else:
            alpha = prior
        alpha = np.clip(alpha, 0.01, 0.95)
        for s, a in zip(room.surfaces, alpha):
            out["alpha"][s.id].append(round(float(a), 3))
        out["total_absorption_m2"].append(round(float(np.sum(area * alpha)), 2))
        # confidence: decent when mid-band RT is measurable and decays are long enough
        ok = np.isfinite(rt[bi])
        out["confidence"].append("high" if ok and rt[bi] > 0.25 else ("medium" if ok else "low"))
    return out


# --------------------------------------------------------------------- planning
TARGET_RT = {"movies": 0.40, "music": 0.45, "voice": 0.32, "mixed": 0.42}


def _reflection_points(room: Room, source_xy: tuple[float, float], listener_xy: tuple[float, float]) -> dict:
    """First-order specular reflection point on each wall (2D floor plan, walls at x/y=0/L/W)."""
    sx, sy = source_xy
    lx, ly = listener_xy
    pts = {}
    pts["left"] = (0.0, (sy + ly) / 2)          # y=0 wall
    pts["right"] = (room.width, (sy + ly) / 2)  # y=W wall
    pts["front"] = (0.0, (sx + lx) / 2)         # x=0 wall
    pts["back"] = (room.length, (sx + lx) / 2)  # x=L wall
    return pts


def treatment_plan(room: Room, metrics: dict, inversion: dict, use_case: str = "movies") -> dict:
    target = TARGET_RT.get(use_case, 0.42)
    rt_now = metrics.get("rt60_mid_s", float("nan"))
    S = room.total_area
    A_now = 0.161 * room.volume / rt_now if np.isfinite(rt_now) and rt_now > 0 else None
    A_target = 0.161 * room.volume / target
    steps, cost, added = [], 0, 0.0
    if A_now is not None and A_now < A_target:
        idx = 2  # 500 Hz as the design band
        needed = A_target - A_now
        panel = CATALOG[0]
        # added absorption of a panel over a drywall wall at 500 Hz
        per_panel = panel["area_m2"] * (panel["alpha"][idx] - MATERIAL_PRIORS["drywall"][idx])
        n = max(1, math.ceil(needed / max(per_panel, 1e-6)))
        n = min(n, 12)
        cost += n * panel["price_usd"]
        added += n * per_panel
        steps.append({"action": f"Mount {n} acoustic panels (2'x4') at the first-reflection points",
                      "where": "front and back walls, ear height, verified with the in-app markers",
                      "why": "kills the strong early reflections that smear dialogue and stereo image",
                      "count": n, "cost_usd": n * panel["price_usd"]})
        steps.append({"action": "Add a thick rug between speakers and listening position",
                      "where": "floor, centre", "why": "reduces the floor-ceiling flutter and mid-band tail",
                      "count": 1, "cost_usd": 180})
        cost += 180
        added += 6.0 * (MATERIAL_PRIORS["rug"][idx] - MATERIAL_PRIORS["wood"][idx])
        steps.append({"action": "Move the left speaker 30–40 cm away from the side wall",
                      "where": "left speaker", "why": "reduces the side-wall reflection notch (SBIR)",
                      "count": 1, "cost_usd": 0})
    rt_after = 0.161 * room.volume / (A_now + added) if A_now is not None and (A_now + added) > 0 else float("nan")
    return {
        "use_case": use_case,
        "target_rt60_s": target,
        "current_rt60_s": None if not np.isfinite(rt_now) else round(float(rt_now), 2),
        "predicted_rt60_s": None if not np.isfinite(rt_after) else round(float(rt_after), 2),
        "steps": steps,
        "cost_usd": cost,
        "reflection_points": _reflection_points(room, (room.length * 0.25, room.width * 0.5),
                                                (room.length * 0.7, room.width * 0.5)),
        "disclaimer": "Estimates only — measured with a phone, not a certified lab.",
    }


# --------------------------------------------------------------------- auralization
def _decay_tail(n_samples: int, rt60: float, fs: int = FS, rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng(0)
    t = np.arange(n_samples) / fs
    noise = rng.normal(0, 1, n_samples)
    return noise * np.exp(-6.91 * t / max(rt60, 0.05))


def simulate_treated_rir(room: Room, treatment: dict, rt_before: float, fs: int = FS) -> np.ndarray:
    """Cheap demonstration simulator: direct + a few early reflections + statistical tail
    matched to the predicted RT60. The production plan uses the full room simulation."""
    rng = np.random.default_rng(7)
    n = int(1.2 * fs)
    rir = np.zeros(n)
    rir[0] = 1.0
    for delay_ms, gain in [(7, 0.45), (11, -0.35), (17, 0.28), (23, -0.22), (31, 0.18), (43, -0.12)]:
        i = int(delay_ms * 1e-3 * fs)
        if i < n:
            rir[i] += gain
    rt_after = treatment["predicted_rt60_s"] or rt_before
    tail_start = int(0.02 * fs)
    rir[tail_start:] += 0.25 * _decay_tail(n - tail_start, float(rt_after), fs, rng)
    return rir / np.max(np.abs(rir))


def _write_wav(samples: np.ndarray, fs: int = FS) -> bytes:
    samples = np.clip(samples, -1, 1)
    pcm = (samples * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1 if pcm.ndim == 1 else pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def demo_clip(seconds: float = 8.0, fs: int = FS) -> np.ndarray:
    """A music-ish test signal (royalty free, generated) for the A/B player."""
    rng = np.random.default_rng(3)
    t = np.arange(int(seconds * fs)) / fs
    sig = np.zeros_like(t)
    for f0, t0, dur in [(220, 0.2, 1.6), (330, 2.0, 1.6), (440, 3.8, 2.4), (277, 6.4, 1.4)]:
        env = np.exp(-(t - t0) / 0.25) * ((t >= t0) & (t < t0 + dur))
        for h in range(1, 7):
            sig += env * (0.5 ** h) * np.sin(2 * math.pi * f0 * h * t + rng.uniform(0, 6.28))
    for t0 in np.arange(0.1, seconds - 0.2, 0.9):
        n = int(0.008 * fs)
        i = int(t0 * fs)
        sig[i:i + n] += rng.normal(0, 0.6, n) * np.exp(-np.arange(n) / (0.2 * n))
    return sig / np.max(np.abs(sig)) * 0.7


def auralize(before_rir: np.ndarray, after_rir: np.ndarray, clip: np.ndarray | None = None) -> dict:
    clip = demo_clip() if clip is None else clip
    b = fftconvolve(clip, before_rir)[: len(clip)]
    a = fftconvolve(clip, after_rir)[: len(clip)]
    b = b / max(np.max(np.abs(b)), 1e-9) * 0.85
    a = a / max(np.max(np.abs(a)), 1e-9) * 0.85
    return {"before": _write_wav(b), "after": _write_wav(a)}


# --------------------------------------------------------- QC + position fusion
def quality_check(recording: np.ndarray, metrics: dict) -> dict:
    """Cheap, honest capture QC so the app can ask the user to redo a bad measurement."""
    if len(recording) == 0:
        return {"peak": 0.0, "rms_db": -120.0, "clipped": False, "silent": True,
                "bands_ok": 0, "warnings": ["Empty recording."]}
    peak = float(np.max(np.abs(recording)))
    rms = float(np.sqrt(np.mean(recording ** 2)))
    clipped = peak >= 0.99
    silent = rms < 1e-4
    bands_ok = int(np.sum(np.isfinite(np.array(metrics.get("t30_s", []), dtype=float))))
    warnings = []
    if clipped:
        warnings.append("Recording clipped — lower the playback volume and retry.")
    if silent:
        warnings.append("Recording is silent — check microphone permission/route.")
    if bands_ok < 4:
        warnings.append("Decay was measurable in <4 bands — use a quieter room or add a longer tail.")
    return {"peak": round(peak, 3),
            "rms_db": round(20 * math.log10(rms + 1e-12), 1),
            "clipped": clipped, "silent": silent, "bands_ok": bands_ok,
            "warnings": warnings}


def combine_metrics(all_metrics: list[dict]) -> dict:
    """Robust multi-position fusion: per-band median across measurements."""
    if not all_metrics:
        return {"bands": BAND_LABELS, "edt_s": [], "t30_s": [], "c50_db": [], "rt60_mid_s": float("nan")}
    out = {"bands": BAND_LABELS, "edt_s": [], "t30_s": [], "c50_db": []}
    for key in ("edt_s", "t30_s", "c50_db"):
        arr = np.array([m.get(key, [np.nan] * len(BANDS)) for m in all_metrics], dtype=float)
        out[key] = [float(np.nanmedian(arr[:, i])) if np.isfinite(arr[:, i]).any() else float("nan")
                    for i in range(arr.shape[1])]
    t30 = np.array(out["t30_s"])
    out["rt60_mid_s"] = float(np.nanmedian(t30[2:4])) if np.isfinite(t30[2:4]).any() else float("nan")
    out["n_positions"] = len(all_metrics)
    return out


# --------------------------------------------------------------------- end-to-end
def analyze(room: Room, measured_rir: np.ndarray | list[np.ndarray] | None = None,
            use_case: str = "movies", fs: int = FS) -> dict:
    """Full pipeline. If no measured RIR is given, builds a realistic demo RIR.
    `measured_rir` may be a list of RIRs from several listening positions (median-fused)."""
    rirs = measured_rir if isinstance(measured_rir, list) else ([measured_rir] if measured_rir is not None else [])
    if not rirs:
        # untreated demo room: RT ~0.95 s
        untreated = simulate_treated_rir(room, {"predicted_rt60_s": 0.95}, 0.95, fs)
        rec = fftconvolve(untreated, exp_sweep(fs=fs))[: int(5.2 * fs)]
        rirs = [deconvolve(rec, exp_sweep(fs=fs), fs)]
    per_position = [analyze_rir(r, fs) for r in rirs]
    metrics = combine_metrics(per_position)
    measured_rir = rirs[0]
    inversion = invert_surfaces(metrics, room)
    plan = treatment_plan(room, metrics, inversion, use_case)
    rt_before = metrics.get("rt60_mid_s") or 0.8
    after_rir = simulate_treated_rir(room, plan, float(rt_before), fs)
    audio = auralize(measured_rir, after_rir)
    return {
        "room": room_to_json(room),
        "metrics": metrics,
        "positions": per_position,
        "inversion": inversion,
        "plan": plan,
        "score": _score(metrics, plan),
        "audio": audio,
    }


def _score(metrics: dict, plan: dict) -> dict:
    rt = metrics.get("rt60_mid_s")
    target = plan["target_rt60_s"]
    if not rt or not math.isfinite(rt):
        return {"total": None, "label": "Measurement too noisy — try again"}
    ratio = rt / target
    echo_penalty = max(0.0, min(40.0, 40.0 * (ratio - 1.0) / 2.0))
    c50 = np.nanmedian([c for c in metrics.get("c50_db", []) if c is not None and math.isfinite(c)] or [0])
    clarity_bonus = max(0.0, min(25.0, (c50 + 2) * 2.5))
    total = int(max(5, min(95, 60 - echo_penalty + (clarity_bonus - 25) * 0.5 + 25)))
    return {"total": total, "label": "Echoey — fixable" if rt > target * 1.3 else "Reasonably controlled",
            "rt60_vs_target": round(ratio, 2)}
