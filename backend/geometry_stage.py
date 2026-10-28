"""Optional illustrative staging for the estimated room shell.

This module produces *visualisation*, never measurement. It receives only numeric room
dimensions and distance-only acoustic candidates; it never sees audio, room names, files,
meshes or device coordinates. The result is always labelled illustrative and cannot change,
validate or extend the acoustic fit. If the model is unavailable or returns something
malformed, a deterministic procedural staging is returned so the demo never dies.
"""
from __future__ import annotations

import json
import math
import os
import re

import httpx

import geometry_advisor
import meta_models as mm

TIMEOUT = httpx.Timeout(connect=3.0, read=25.0, write=5.0, pool=3.0)
MAX_OBJECTS = 8
KINDS = {"sofa", "armchair", "chair", "table", "desk", "rug", "plant", "lamp", "shelf", "bed"}
PALETTE = ["#d8c3a5", "#8d7b68", "#a4907c", "#c8b6a6", "#6b705c", "#b7b7a4"]
SYSTEM = """You stage an ILLUSTRATIVE visualisation of an estimated rectangular room.
The numbers are approximate acoustic estimates, not a survey; object candidates are
distance-only echo clusters with unknown direction, identity and size.
Return ONLY JSON: {"style": short phrase, "palette": ["#rrggbb", ... up to 5],
"objects": [{"kind": one of sofa, armchair, chair, table, desk, rug, plant, lamp, shelf, bed,
"x": m, "z": m, "w": m, "d": m, "h": m, "color": "#rrggbb"}]}.
x/z are object-centre positions on the floor inside the room; w/d/h are object sizes.
Use at most 8 objects, keep everything inside the room with a small margin, and choose a
tasteful, realistic arrangement. Do not claim these objects were measured or detected."""


def _num(value: object, lo: float, hi: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) and lo <= value <= hi else None


def _hex(value: object, fallback: str) -> str:
    return value.lower() if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


def sanitize(result: dict) -> dict | None:
    """Allowlisted numeric payload for staging; arbitrary result text is never forwarded."""
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    candidate = candidates[0] if isinstance(candidates[0], dict) else {}
    dimensions = candidate.get("dimensions_m")
    if not isinstance(dimensions, list) or len(dimensions) != 3:
        return None
    dims = [_num(v, 1.5, 12.0) for v in dimensions]
    if any(v is None for v in dims):
        return None
    distances = []
    for item in (result.get("objects") or [])[:8]:
        if isinstance(item, dict):
            distance = _num(item.get("distance_m"), 0.2, 12.0)
            strength = _num(item.get("strength"), 0.0, 1.0)
            if distance is not None:
                distances.append({"distance_m": round(distance, 2),
                                  "strength": round(strength, 2) if strength is not None else None})
    return {"dimensions_m": [round(v, 2) for v in dims], "acoustic_candidates": distances,
            "synthetic": result.get("source") == "synthetic_demo"}


def _fit(kind: str, x: float, z: float, w: float, d: float, h: float,
         room: list[float], color: str) -> dict:
    length, depth, height = room
    w = min(max(w, 0.2), length * 0.85)
    d = min(max(d, 0.2), depth * 0.85)
    h = min(max(h, 0.05), height * 0.85)
    x = min(max(x, w / 2 + 0.05), length - w / 2 - 0.05)
    z = min(max(z, d / 2 + 0.05), depth - d / 2 - 0.05)
    return {"kind": kind, "x": round(x, 2), "z": round(z, 2), "w": round(w, 2),
            "d": round(d, 2), "h": round(h, 2), "color": color}


def procedural(payload: dict, note: str = "Illustrative procedural staging; these objects are not measured.") -> dict:
    """Deterministic fallback staging that fits any estimated shell."""
    length, depth, height = payload["dimensions_m"]
    layout = [
        ("rug", length * 0.5, depth * 0.5, length * 0.45, depth * 0.32, 0.02, PALETTE[0]),
        ("sofa", length * 0.32, depth * 0.20, length * 0.34, min(0.85, depth * 0.18), 0.72, PALETTE[4]),
        ("table", length * 0.52, depth * 0.52, length * 0.20, depth * 0.20, 0.42, PALETTE[1]),
        ("lamp", length * 0.88, depth * 0.85, 0.22, 0.22, 1.55, PALETTE[2]),
        ("plant", length * 0.12, depth * 0.82, 0.35, 0.35, 0.95, PALETTE[3]),
        ("shelf", length * 0.82, depth * 0.16, min(1.2, length * 0.22), 0.32, 1.35, PALETTE[5]),
    ]
    objects = [_fit(kind, x, z, w, d, h, payload["dimensions_m"], color)
               for kind, x, z, w, d, h, color in layout]
    return {"available": True, "source": "procedural", "model": None, "training_use": False,
            "style": "Warm minimal (illustrative)", "palette": PALETTE[:4],
            "objects": objects, "note": note}


def _validate_model_spec(content: str, payload: dict) -> dict | None:
    if not isinstance(content, str) or len(content) > 20_000:
        return None
    try:
        spec = json.loads(content)
    except (ValueError, TypeError):
        return None
    if not isinstance(spec, dict):
        return None
    palette = spec.get("palette")
    palette = [_hex(v, PALETTE[i % len(PALETTE)]) for i, v in enumerate(palette[:5])] \
        if isinstance(palette, list) else PALETTE[:4]
    if not palette:
        palette = PALETTE[:4]
    objects_in = spec.get("objects")
    if not isinstance(objects_in, list) or not objects_in:
        return None
    objects = []
    for i, item in enumerate(objects_in[:MAX_OBJECTS]):
        if not isinstance(item, dict) or item.get("kind") not in KINDS:
            continue
        # Reject only non-finite/nonsense numbers; _fit clamps everything into the shell.
        w = _num(item.get("w"), 0.01, 1000.0); d = _num(item.get("d"), 0.01, 1000.0)
        h = _num(item.get("h"), 0.01, 1000.0); x = _num(item.get("x"), -1000.0, 1000.0)
        z = _num(item.get("z"), -1000.0, 1000.0)
        if any(v is None for v in (w, d, h, x, z)):
            continue
        objects.append(_fit(item["kind"], x, z, w, d, h, payload["dimensions_m"],
                            _hex(item.get("color"), palette[i % len(palette)])))
    if not objects:
        return None
    style = spec.get("style")
    style = style.strip()[:80] if isinstance(style, str) and style.strip() else "Illustrative staging"
    return {"style": style, "palette": palette, "objects": objects}


def stage(result: dict) -> dict:
    payload = sanitize(result)
    if payload is None:
        return {"available": False, "source": "none", "model": None, "training_use": False,
                "style": "", "palette": [], "objects": [],
                "note": "No room estimate to stage yet."}
    if os.environ.get("GEOMETRY_STAGE_MODE") == "procedural":
        return procedural(payload)
    model = mm.MODEL_SPARK
    training = isinstance(model, str) and model.endswith("-contributor")
    base = {"available": False, "model": model if isinstance(model, str) else None,
            "training_use": training, "palette": PALETTE[:4], "objects": []}
    endpoint = geometry_advisor._meta_endpoint(mm.BASE)
    if not mm.KEY or endpoint is None or not isinstance(model, str) or \
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", model) is None:
        return procedural(payload, "Meta staging unavailable; showing illustrative procedural staging. "
                                   "These objects are not measured.")
    request = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": json.dumps(payload, allow_nan=False)}],
        "temperature": 0.4, "max_tokens": 2200, "reasoning_effort": "low",
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            response = client.post(endpoint,
                                   headers={"Authorization": f"Bearer {mm.KEY}"}, json=request)
            response.raise_for_status()
            if len(response.content) > 100_000:
                raise ValueError("oversized staging response")
            content = response.json()["choices"][0]["message"]["content"]
            validated = _validate_model_spec(content, payload)
            if validated is None:
                raise ValueError("invalid staging")
            return {"available": True, "source": "meta", "model": model,
                    "training_use": training, **validated,
                    "note": "Illustrative staging generated from approximate acoustic estimates. "
                            "These objects were not measured and are not detected furniture."}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        return procedural(payload, "Meta staging could not respond; showing illustrative procedural "
                                   "staging. These objects are not measured.")
