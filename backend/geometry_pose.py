"""Pose-graph adjustment for the walk scan.

The phone records stepped distance (pedometer) and facing heading (device attitude) per segment,
plus a loop-closure constraint when the user returns to the start. Raw dead-reckoning drifts;
a small least-squares pose graph distributes the loop residual over the path so the echo circles
are voted with a self-consistent trajectory. This is deliberately simple and testable, not a full
visual-inertial SLAM.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import least_squares

MIN_SEGMENTS = 3
MAX_SEGMENTS = 8
MIN_DISTANCE_M = 0.05
MAX_DISTANCE_M = 3.0
ASSUMPTIONS = [
    "Distances come from the phone's step sensor; heading from device attitude while walking.",
    "Pedometer distance and hand-held heading are approximate; loop closure reduces but does not remove drift.",
    "Pose tracks are 2D on the floor plane; phone height and tilt are not used.",
]


def sanitize_trajectory(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    segments = raw.get("segments")
    if not isinstance(segments, list) or not MIN_SEGMENTS <= len(segments) <= MAX_SEGMENTS:
        return None
    loop = raw.get("loop", True)
    if not isinstance(loop, bool):
        return None
    clean = []
    for item in segments:
        if not isinstance(item, dict):
            return None
        distance, heading = item.get("distance_m"), item.get("heading_rad")
        if isinstance(distance, bool) or isinstance(heading, bool):
            return None
        if not isinstance(distance, (int, float)) or not isinstance(heading, (int, float)):
            return None
        distance, heading = float(distance), float(heading)
        if not math.isfinite(distance) or not math.isfinite(heading):
            return None
        if not MIN_DISTANCE_M <= distance <= MAX_DISTANCE_M:
            return None
        clean.append({"distance_m": round(distance, 3), "heading_rad": round(heading, 4)})
    return {"segments": clean, "loop": loop}


def adjust(trajectory: dict) -> dict:
    segments = trajectory["segments"]
    loop = trajectory.get("loop", True)
    vectors = [s["distance_m"] * np.array([math.cos(s["heading_rad"]), math.sin(s["heading_rad"])])
               for s in segments]
    raw = [np.zeros(2)]
    for vector in vectors:
        raw.append(raw[-1] + vector)
    raw = np.asarray(raw)
    n = len(segments)
    if n < 3:
        raise ValueError("At least three segments are required.")
    weights = np.array([max(0.05, min(0.4, 0.06 + 0.12 * s["distance_m"])) for s in segments])

    def unpack(x: np.ndarray) -> np.ndarray:
        return np.vstack([[0.0, 0.0], x.reshape(n, 2)])

    def residuals(x: np.ndarray) -> np.ndarray:
        poses = unpack(x)
        residual = []
        for index, vector in enumerate(vectors):
            residual.extend((poses[index + 1] - poses[index] - vector) / weights[index])
        if loop:
            residual.extend((poses[n] - poses[0]) * 2.2 / float(np.mean(weights)))
        return np.asarray(residual)

    x0 = raw[1:].reshape(-1)
    solved = least_squares(residuals, x0, loss="soft_l1", f_scale=1.0,
                           max_nfev=300)
    adjusted = unpack(solved.x)
    raw_loop = float(np.linalg.norm(raw[-1] - raw[0])) if loop else None
    adj_loop = float(np.linalg.norm(adjusted[-1] - adjusted[0])) if loop else None
    # Rotate so the first segment points along +x (orientation is arbitrary anyway).
    angle = -float(segments[0]["heading_rad"]) if segments else 0.0
    rotation = np.array([[math.cos(angle), -math.sin(angle)],
                         [math.sin(angle), math.cos(angle)]])
    poses = [{"x": round(float((rotation @ point)[0]), 3),
              "y": round(float((rotation @ point)[1]), 3),
              "yaw": 0.0} for point in adjusted]
    return {
        "poses": poses,
        "assumptions": ASSUMPTIONS.copy(),
        "diagnostics": {
            "segments": n, "loop": loop,
            "raw_loop_error_m": None if raw_loop is None else round(raw_loop, 3),
            "adjusted_loop_error_m": None if adj_loop is None else round(adj_loop, 3),
            "mean_step_m": round(float(np.mean([s["distance_m"] for s in segments])), 3),
            "raw_poses": [{"x": round(float(p[0]), 3), "y": round(float(p[1]), 3)} for p in raw],
            "adjusted_poses": [{"x": p["x"], "y": p["y"]} for p in poses],
        },
    }
