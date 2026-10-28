"""Experimental multi-position acoustic reflection mapping.

The phone is carried along an approximate L-path (assumed spacing, reported to the user).
Each probe echo is a distance measurement: the reflector lies on a circle around that pose.
Voting those circles on a 2D floor grid localizes reflectors without matching echoes across
captures. Persistent reflections (furniture/walls) get support from every pose; moving things
(people, pets) rarely line up and surface as unstable/low-support candidates.

This is explicitly a reflector-candidate map, not object identification: no size, material,
identity or true height is recovered; spacing is approximate; height is assumed. No audio is
sent anywhere except the user's own backend. Public functions are unit-tested.
"""
from __future__ import annotations

import math

import numpy as np

import geometry
import probe

SOUND_SPEED = geometry.SOUND_SPEED
ASSUMED_SPACING_M = 0.6
MAX_POSES = 8
MIN_POSES = 4
GRID_STEP_M = 0.08
RING_TOLERANCE_M = 0.07
MAX_RANGE_M = 5.0
MIN_POSE_SEPARATION_M = 0.15
MAX_REFLECTORS = 6
ASSUMPTIONS = [
    "Phone moved along an approximate L-path with 0.6 m hand spacing (user instruction; not measured).",
    "Reflectors are localized on a 2D horizontal plane; true height and identity are unknown.",
    "Echoes may come from furniture, walls, people or multipath; a reflector is not an object label.",
    "A moving reflector will usually have weak or inconsistent support across poses.",
    "This is experimental: no dimensional accuracy or object-classification claim is made.",
]


def sanitize_poses(raw) -> list[dict] | None:
    """Allowlisted pose list: relative x/y in metres and optional yaw in radians."""
    if not isinstance(raw, list) or not MIN_POSES <= len(raw) <= MAX_POSES:
        return None
    poses = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        xv, yv = item.get("x"), item.get("y")
        if isinstance(xv, bool) or isinstance(yv, bool) or not isinstance(xv, (int, float)) \
                or not isinstance(yv, (int, float)):
            return None
        xv, yv = float(xv), float(yv)
        if not (math.isfinite(xv) and math.isfinite(yv)) or not -2.0 <= xv <= 6.0 or not -2.0 <= yv <= 6.0:
            return None
        yaw = item.get("yaw", 0.0)
        if isinstance(yaw, bool) or not isinstance(yaw, (int, float)) or not math.isfinite(float(yaw)):
            return None
        poses.append({"x": round(xv, 3), "y": round(yv, 3), "yaw": round(float(yaw), 3)})
    for i in range(len(poses)):
        for j in range(i + 1, len(poses)):
            if math.hypot(poses[i]["x"] - poses[j]["x"], poses[i]["y"] - poses[j]["y"]) < MIN_POSE_SEPARATION_M:
                return None
    return poses


def echo_radii(recording: np.ndarray, fs: int = probe.FS, max_echoes: int = 14) -> tuple[list[dict], dict]:
    peaks, diag = geometry.extract_echoes(recording, fs)
    if diag.get("reason"):
        return [], diag
    short = [p for p in peaks if 1.5 <= p["delay_ms"] <= 2 * MAX_RANGE_M / SOUND_SPEED * 1000]
    short = sorted(short, key=lambda p: -p["strength"])[:max_echoes]
    return [{"delay_ms": p["delay_ms"], "strength": p["strength"],
             "radius_m": p["delay_ms"] / 1000.0 * SOUND_SPEED / 2.0} for p in short], diag


def _grid(poses: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    xs = [p["x"] for p in poses]
    ys = [p["y"] for p in poses]
    x0, x1 = min(xs) - MAX_RANGE_M, max(xs) + MAX_RANGE_M
    y0, y1 = min(ys) - MAX_RANGE_M, max(ys) + MAX_RANGE_M
    gx = np.arange(x0, x1, GRID_STEP_M)
    gy = np.arange(y0, y1, GRID_STEP_M)
    return gx, gy, *np.meshgrid(gx, gy)


def scan(recordings: list[np.ndarray], poses: list[dict], fs: int = probe.FS) -> dict:
    """Vote echo-distance circles over a 2D grid and return reflector candidates."""
    if not MIN_POSES <= len(poses) <= MAX_POSES:
        raise ValueError(f"Walk scan needs {MIN_POSES} to {MAX_POSES} positions.")
    if len(recordings) != len(poses):
        raise ValueError("Provide one probe recording per walk-scan position.")
    echo_sets, capture_diags = [], []
    for recording in recordings:
        echoes, diag = echo_radii(recording, fs)
        echo_sets.append(echoes)
        capture_diags.append(diag)
    out = scan_echoes(echo_sets, poses)
    out["diagnostics"]["capture_checks"] = capture_diags
    return out


def scan_echoes(echo_sets: list[list[dict]], poses: list[dict]) -> dict:
    """Pure localization step (public for tests): echo radii per pose -> reflectors."""
    if not MIN_POSES <= len(poses) <= MAX_POSES:
        raise ValueError(f"Walk scan needs {MIN_POSES} to {MAX_POSES} positions.")
    if len(echo_sets) != len(poses):
        raise ValueError("One echo set per pose is required.")
    gx, gy, X, Y = _grid(poses)
    support = np.zeros(X.shape, dtype=np.int16)
    weight = np.zeros(X.shape, dtype=float)
    usable_poses = 0
    for pose, radii in zip(poses, echo_sets):
        if not radii:
            continue
        usable_poses += 1
        dist = np.hypot(X - pose["x"], Y - pose["y"])
        ring_mask = np.zeros(X.shape, dtype=bool)
        for echo in radii:
            ring_mask |= np.abs(dist - echo["radius_m"]) <= RING_TOLERANCE_M
            weight += np.exp(-((dist - echo["radius_m"]) / RING_TOLERANCE_M) ** 2) * echo["strength"]
        support += ring_mask.astype(np.int16)
    need = max(3, math.ceil(usable_poses * 2 / 3)) if usable_poses else 0
    reflectors = []
    if need:
        candidates = np.argwhere(support >= need)
        ranked = sorted(((float(weight[y, x]), int(y), int(x)) for y, x in candidates), reverse=True)
        for score, y, x in ranked:
            rx, ry = float(gx[x]), float(gy[y])
            if any(math.hypot(rx - r["x"], ry - r["y"]) < 0.55 for r in reflectors):
                continue
            if any(math.hypot(rx - p["x"], ry - p["y"]) < 0.25 for p in poses):
                continue
            reflector = {
                "id": f"reflector-{len(reflectors) + 1}",
                "x": round(rx, 2), "y": round(ry, 2),
                "distance_from_start_m": round(math.hypot(rx - poses[0]["x"], ry - poses[0]["y"]), 2),
                "support": int(support[y, x]), "poses": int(usable_poses),
                "score": round(score, 3),
                "type": "persistent" if int(support[y, x]) >= usable_poses else "unstable",
                "note": "Acoustic reflection candidate on the scan plane; not an identified object.",
            }
            reflectors.append(reflector)
            if len(reflectors) >= MAX_REFLECTORS:
                break
    reflectors.sort(key=lambda r: (r["type"] != "persistent", -r["score"]))
    status = "reflectors" if reflectors else "insufficient_evidence"
    message = ("Reflection candidates localized. These are surfaces that reflected the probe, not "
               "identified furniture; moving things can appear as unstable candidates." if reflectors else
               "Not enough consistent reflections across the walk positions. Move more slowly and stay away "
               "from soft furnishings, or repeat in a quieter room.")
    return {"status": status, "message": message, "assumptions": ASSUMPTIONS.copy(),
            "poses": poses, "reflectors": reflectors,
            "diagnostics": {"recordings": len(echo_sets), "usable_poses": usable_poses,
                            "support_needed": need, "grid_step_m": GRID_STEP_M,
                            "assumed_spacing_m": ASSUMED_SPACING_M}}
