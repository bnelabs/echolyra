"""Optional model review of a numerical acoustic-room fit.

Call only after a user explicitly requests cloud review. No recordings, free text,
room identifiers, geometry meshes, or device/location coordinates are transmitted.
This module never alters a fit or substitutes model prose for recorded measurements.
"""
from __future__ import annotations

import json
import math
import re
from urllib.parse import urlsplit

import httpx

import meta_models as mm

TIMEOUT = httpx.Timeout(connect=3.0, read=20.0, write=5.0, pool=3.0)
SYSTEM = """You help a person understand an experimental room estimate from sound.
The input contains echo measurements and estimated rectangular layouts, not known room dimensions.
The solver assumes approximately co-located speaker and microphone, rectangular
walls, specular early reflections, and an unknown axis orientation. A plausible
box or a small timing residual does not establish that the real room was found.
Separate what the phone recorded from what the estimated layout suggests.
Do not certify, approve, validate, or raise confidence in any layout. Do not
invent observations, furniture, materials, wall directions, or missing echoes.
Suggest ONE practical additional acoustic measurement that may distinguish the
remaining layouts. Do not require cameras or LiDAR. Do not supply new geometry
or execute tools. Use everyday language and a helpful, direct tone. Say
"measurements" and "estimated layout"; never use "evidence", "hypothesis", or
"insufficient evidence" in the reply. If the measurements are unclear, explain
what recording to try next. Return ONLY JSON with two short strings:
{"assessment":"what the measurements can tell us", "next_measurement":"one next recording to try"}.
"""


def _meta_endpoint(base: object) -> str | None:
    """Keep the recipient identical to the one named in the app's Meta consent."""
    if not isinstance(base, str):
        return None
    try:
        url = urlsplit(base)
        valid = (url.scheme == "https" and url.hostname == "api.meta.ai"
                 and url.port in (None, 443) and url.username is None and url.password is None
                 and url.path.rstrip("/") == "/v1" and not url.query and not url.fragment)
    except ValueError:
        return None
    return "https://api.meta.ai/v1/chat/completions" if valid else None


def _number(value: object, lo: float, hi: float) -> float | None:
    # bool is a subclass of int, but is never an acoustic measurement.
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return round(value, 4) if math.isfinite(value) and lo <= value <= hi else None


def _count(value: object, hi: int = 10000) -> int | None:
    value = _number(value, 0, hi)
    return int(value) if value is not None and value.is_integer() else None


def sanitize(result: dict) -> dict:
    """Construct a new allowlisted payload; never forward arbitrary result fields."""
    status = result.get("status")
    payload: dict = {
        "status": status if status in ("candidate", "ambiguous", "insufficient_evidence") else "unknown",
        "synthetic": result.get("source") == "synthetic_demo",
        "candidates": [], "echoes": [], "diagnostics": {},
    }
    candidates = result.get("candidates")
    for candidate in candidates[:3] if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict):
            continue
        dimensions = candidate.get("dimensions_m")
        if not isinstance(dimensions, list) or len(dimensions) != 3:
            continue
        dimensions = [_number(v, 0.1, 50.0) for v in dimensions]
        if any(v is None for v in dimensions):
            continue
        clean = {"dimensions_m": dimensions}
        fit_error = _number(candidate.get("fit_error_ms"), 0, 1000)
        support = _number(candidate.get("support_fraction"), 0, 1)
        if fit_error is not None:
            clean["fit_error_ms"] = fit_error
        if support is not None:
            clean["support_fraction"] = support
        for field in ("matched_echoes", "total_predicted_echoes"):
            count = _count(candidate.get(field))
            if count is not None:
                clean[field] = count
        payload["candidates"].append(clean)
    echoes = result.get("echoes")
    for echo in echoes[:64] if isinstance(echoes, list) else []:
        if not isinstance(echo, dict):
            continue
        delay = _number(echo.get("delay_ms"), 0, 200)
        strength = _number(echo.get("strength"), 0, 1)
        if delay is not None and strength is not None:
            payload["echoes"].append({"delay_ms": delay, "strength": strength})
    diagnostics = result.get("diagnostics")
    if isinstance(diagnostics, dict):
        for field in ("recordings", "repeatable_echoes"):
            count = _count(diagnostics.get(field))
            if count is not None:
                payload["diagnostics"][field] = count
    return payload


def review(result: dict) -> dict:
    """Request a bounded advisory opinion; return no provider exception details."""
    model = mm.MODEL_SPARK
    training = isinstance(model, str) and model.endswith("-contributor")
    base = {"available": False, "model": model, "training_use": training}
    if not mm.KEY:
        return {**base, "text": "Meta review is not set up. You can still explore the room estimate."}
    if not isinstance(model, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", model) is None:
        return {**base, "model": None, "text": "The configured review model is invalid."}
    endpoint = _meta_endpoint(mm.BASE)
    if endpoint is None:
        return {**base, "text": "Meta review needs the official Meta API address in your backend settings. You can still explore the room estimate."}
    payload = sanitize(result)
    if not payload["echoes"] and not payload["candidates"]:
        return {**base, "text": "Record the room first, then ask Meta about the measurements."}
    request = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": json.dumps(payload, allow_nan=False)}],
        "temperature": 0.1,
        "max_tokens": 3000,
        "reasoning_effort": "low",
        "response_format": {"type": "json_object"},
    }
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
            response = client.post(endpoint,
                                   headers={"Authorization": f"Bearer {mm.KEY}"}, json=request)
            response.raise_for_status()
            # Bound a provider response before parsing, including JSON-mode failures.
            if len(response.content) > 100_000:
                raise ValueError("oversized response")
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or len(content) > 12_000:
                raise ValueError("invalid content")
            suggestion = json.loads(content)
            if not isinstance(suggestion, dict):
                raise ValueError("invalid advice object")
            assessment = suggestion.get("assessment")
            measurement = suggestion.get("next_measurement")
            if not isinstance(assessment, str) or not isinstance(measurement, str):
                raise ValueError("invalid advice schema")
            if not assessment.strip() or not measurement.strip():
                raise ValueError("empty advice")
            text = ("Meta’s interpretation of the measurements. It does not confirm the room’s actual dimensions.\n\n"
                    + assessment.strip()[:1500] + "\n\nNext measurement: " + measurement.strip()[:1500])
            return {**base, "available": True, "text": text}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
        # Provider errors can include auth headers, echoed inputs or diagnostic URLs.
        # No exception text is exposed to the app or logs and no alternate mode is tried.
        return {**base, "text": "Meta could not respond right now. Your room estimate is still available."}
