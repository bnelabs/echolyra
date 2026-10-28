"""Thin, cache-first clients for the Meta Model API.

VERIFIED AGAINST THE LIVE API ON 2026-10-28 (see HACKATHON.md §4):
  - Muse Spark 1.3 Contributor : POST {base}/chat/completions   model=muse-spark-1.3-contributor
        reasoning model: needs max_tokens >= ~3000 and reasoning_effort="low" to get content back
  - SAM 3.1                    : POST {base}/responses          model=sam-3.1
        input = [{"type":"message","role":"user","content":[input_text, input_image]}]
        output_text = special-token grammar: <0f>0<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|><|mask;...|>
  - Muse Image 1.0             : POST {base}/images/generations | /images/edits   model=muse-image-1.0
        returns b64_json (WebP, 1600x1600) — converted to JPEG here for iOS
  - Muse Voice Transcribe     : POST {base}/asr/transcribe      multipart `request` JSON + `audio`
        audio must be mono s16le WAV at 16 kHz or 24 kHz (we resample if needed)

Contributor mode is cheaper but Meta may train on inputs/outputs. Use it for the
hackathon demo; switch to `muse-spark-1.3` (Standard) before shipping to real users.
Every call: disk cache -> real HTTP -> deterministic fallback, so the demo never dies.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import re
import wave
from pathlib import Path

import httpx
import numpy as np
from scipy.signal import resample_poly

BASE = os.environ.get("META_BASE_URL", "https://api.meta.ai/v1")
KEY = os.environ.get("META_API_KEY", "")
MODEL_SPARK = os.environ.get("META_MODEL_SPARK", "muse-spark-1.3-contributor")
MODEL_SPARK_STANDARD = os.environ.get("META_MODEL_SPARK_STANDARD", "muse-spark-1.3")
MODEL_SAM = os.environ.get("META_MODEL_SAM", "sam-3.1")
MODEL_IMAGE = os.environ.get("META_MODEL_IMAGE", "muse-image-1.0")
MODEL_ASR = os.environ.get("META_MODEL_ASR", "muse-voice-transcribe-1.0")
REASONING_EFFORT = os.environ.get("META_REASONING_EFFORT", "low")
CACHE = Path(os.environ.get("CACHE_DIR", Path(__file__).parent / "cache"))
CACHE.mkdir(parents=True, exist_ok=True)
TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=120.0, pool=10.0)

CONTRIBUTOR_NOTE = ("Contributor mode: inputs/outputs may be used to train Meta models. "
                    "Fine for the hackathon demo; use Standard mode for real users' rooms.")


def configured() -> dict:
    return {"key": bool(KEY), "base_url": BASE, "spark": MODEL_SPARK,
            "spark_standard_fallback": MODEL_SPARK_STANDARD, "sam": MODEL_SAM,
            "image": MODEL_IMAGE, "asr": MODEL_ASR, "reasoning_effort": REASONING_EFFORT,
            "contributor_note": CONTRIBUTOR_NOTE}


def _hash(*parts: bytes | str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode())
    return h.hexdigest()[:32]


def _cache_get(name: str):
    p = CACHE / name
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def _cache_put(name: str, obj):
    try:
        (CACHE / name).write_text(json.dumps(obj))
    except Exception:
        pass
    return obj


def _headers(accept: str = "application/json") -> dict:
    return {"Authorization": f"Bearer {KEY}", "Accept": accept, "Content-Type": "application/json"}


# --------------------------------------------------------------- Muse Spark
SYSTEM = """You are RoomTwin, an acoustic consultant. You receive JSON measurements from a phone
measurement of a real room (RT60 per octave, C50, estimated surface absorption, a physics-based
treatment plan). Diagnose the room in plain language and prescribe a physical fix.
Rules: never claim lab certification; label numbers as estimates; prefer moving gear or adding
treatment over telling the user to buy new electronics; no medical or hearing claims.
Return ONLY valid JSON: {"score":0-100,"headline":"...","problems":[{"title":"...",
"surface":"...","why":"...","severity":"low|medium|high"}],"plan":[{"step":"...","why":"...",
"expected_effect":"..."}],"confidence":"low|medium|high"}"""


def muse_spark_plan(payload: dict) -> dict:
    key = _hash("spark", json.dumps(payload, sort_keys=True))
    cached = _cache_get(f"spark_{key}.json")
    if cached:
        return cached
    fallback = _fallback_plan(payload)
    if not KEY:
        return fallback
    for model in (MODEL_SPARK, MODEL_SPARK_STANDARD):
        body = {
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps(payload)}],
            "temperature": 0.2,
            "max_tokens": 4000,          # Muse Spark 1.3 is a reasoning model: content only after ~1-2k reasoning tokens
            "reasoning_effort": REASONING_EFFORT,
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(timeout=TIMEOUT) as c:
                r = c.post(f"{BASE}/chat/completions", headers=_headers(), json=body)
                r.raise_for_status()
                choice = r.json()["choices"][0]
                text = choice["message"].get("content") or ""
            plan = _parse_json(text)
            if plan and "problems" in plan:
                plan["_model"] = model
                return _cache_put(f"spark_{key}.json", plan)
            print(f"[muse-spark] {model}: empty/failed content (finish={choice.get('finish_reason')})")
        except Exception as e:  # noqa: BLE001
            print(f"[muse-spark] {model} fallback: {type(e).__name__}: {e}")
    return fallback


def _parse_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None


def _fallback_plan(payload: dict) -> dict:
    rt = payload.get("metrics", {}).get("rt60_mid_s") or 0.0
    problems = []
    if rt and rt > 0.6:
        problems.append({"title": f"Room holds sound for ~{rt:.1f}s (target ~0.4s)",
                         "surface": "front/back walls", "why": "strong specular reflections smear dialogue",
                         "severity": "high" if rt > 0.8 else "medium"})
    return {
        "score": payload.get("score", {}).get("total", 55),
        "headline": "Your room is echoey and slightly one-sided — both are fixable without new gear.",
        "problems": problems or [{"title": "No dominant problem found", "surface": "room",
                                  "why": "measurement looks reasonable", "severity": "low"}],
        "plan": [{"step": s["action"], "why": s["why"], "expected_effect": "lower RT60, clearer dialogue"}
                 for s in payload.get("plan", {}).get("steps", [])],
        "confidence": "medium", "_model": "fallback",
    }


# --------------------------------------------------------------- SAM 3.1
BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


def sam_segment(image_bytes: bytes, concept: str, mime: str = "image/jpeg") -> dict:
    """One short noun phrase per request. Returns boxes + area share (mask payload kept as a hash)."""
    key = _hash("sam", concept, image_bytes)
    cached = _cache_get(f"sam_{key}.json")
    if cached:
        return cached
    if not KEY:
        return {"model": MODEL_SAM, "concept": concept, "boxes": [], "mocked": True}
    b64 = base64.b64encode(image_bytes).decode()
    body = {"model": MODEL_SAM, "stream": False, "input": [{
        "type": "message", "role": "user", "content": [
            {"type": "input_text", "text": concept},
            {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"}]}]}
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{BASE}/responses", headers=_headers(), json=body)
            r.raise_for_status()
            data = r.json()
        text = ""
        for item in data.get("output", []):
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    text += part.get("text", "")
        boxes = [dict(zip(("x1", "y1", "x2", "y2", "w", "h"), map(int, m))) for m in BOX_RE.findall(text)]
        areas = [max(0, b["x2"] - b["x1"]) * max(0, b["y2"] - b["y1"]) for b in boxes]
        img_px = None
        if boxes:
            img_px = boxes[0]["w"] * boxes[0]["h"]
        out = {"model": MODEL_SAM, "concept": concept, "boxes": boxes[:8],
               "match_count": len(boxes),
               "area_share": round(sum(areas) / img_px, 3) if img_px else 0.0,
               "text_chars": len(text), "mocked": False}
        return _cache_put(f"sam_{key}.json", out)
    except Exception as e:  # noqa: BLE001
        print(f"[sam] fallback: {type(e).__name__}: {e}")
        return {"model": MODEL_SAM, "concept": concept, "boxes": [], "mocked": True}


def materials_from_segments(segments: list[dict]) -> dict:
    """Area share per concept (box-area proxy until the mask->area projection is wired)."""
    shares = {}
    for s in segments:
        if s.get("area_share"):
            shares[s["concept"]] = max(shares.get(s["concept"], 0.0), s["area_share"])
    total = sum(shares.values()) or 1.0
    return {k: round(v / total, 3) for k, v in shares.items()}


# --------------------------------------------------------------- Muse Image
def _webp_to_jpeg_b64(raw: bytes) -> str | None:
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # noqa: BLE001
        print(f"[muse-image] webp->jpeg failed: {e}")
        return None


def muse_image_edit(image_bytes: bytes, instruction: str, mime: str = "image/jpeg") -> dict:
    key = _hash("image", instruction, image_bytes)
    cached = _cache_get(f"image_{key}.json")
    if cached:
        return cached
    if not KEY:
        return {"mocked": True, "b64_jpeg": None, "revised_prompt": instruction}
    try:
        files = {"image": ("room.jpg", image_bytes, mime)}
        data = {"model": MODEL_IMAGE, "prompt": instruction, "n": "1", "size": "1024x1024"}
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{BASE}/images/edits", headers={"Authorization": f"Bearer {KEY}"},
                       files=files, data=data)
            r.raise_for_status()
            j = r.json()
        item = (j.get("data") or [{}])[0]
        b64 = item.get("b64_json") or ""
        raw = base64.b64decode(b64) if b64 else b""
        # Muse Image returns WebP; convert so UIImage/WebView display it everywhere
        jpeg_b64 = _webp_to_jpeg_b64(raw) if raw else None
        out = {"mocked": False, "b64_jpeg": jpeg_b64, "format_in": item.get("output_format", "webp"),
               "revised_prompt": item.get("revised_prompt", instruction)}
        return _cache_put(f"image_{key}.json", out)
    except Exception as e:  # noqa: BLE001
        print(f"[muse-image] fallback: {type(e).__name__}: {e}")
        return {"mocked": True, "b64_jpeg": None, "revised_prompt": instruction}


# --------------------------------------------------------------- Voice Transcribe
def _to_asr_wav(audio_bytes: bytes) -> bytes:
    """Meta wants mono s16le WAV at 16 or 24 kHz. Resample if the upload is WAV."""
    with wave.open(io.BytesIO(audio_bytes), "rb") as w:
        fs, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"expected s16le, got sample width {sw}")
    x = np.frombuffer(frames, dtype="<i2").astype(np.float64)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    target = 16000
    if fs != target:
        from math import gcd
        g = gcd(fs, target)
        x = resample_poly(x, target // g, fs // g)
    pcm = np.clip(x, -32768, 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(target)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe(audio_bytes: bytes, filename: str = "brief.wav", mime: str = "audio/wav") -> dict:
    key = _hash("asr", audio_bytes)
    cached = _cache_get(f"asr_{key}.json")
    if cached:
        return cached
    if not KEY:
        return {"text": "", "mocked": True}
    try:
        wav = _to_asr_wav(audio_bytes)
        request = json.dumps({"model": MODEL_ASR, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"})
        files = {"request": (None, request, "application/json"),
                 "audio": ("brief.wav", wav, "audio/wav")}
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{BASE}/asr/transcribe",
                       headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"},
                       files=files)
            r.raise_for_status()
            j = r.json()
        return _cache_put(f"asr_{key}.json", {"text": j.get("transcript", ""), "mocked": False,
                                              "model": MODEL_ASR})
    except Exception as e:  # noqa: BLE001
        print(f"[asr] fallback: {type(e).__name__}: {e}")
        return {"text": "", "mocked": True}


# --------------------------------------------------------------- situation report
SITUATION_SYSTEM = """You are RoomSense, a privacy-preserving home sound awareness system.
You receive JSON about one detected sound event: its acoustic class, confidence, the room it
was attributed to, the phone's measurements, and the local time. Write a calm, useful
situation report. Rules: never claim certainty beyond the confidence; no medical, security
or emergency guarantees; suggest checking only when reasonable; keep it to 1-2 short
sentences. Return ONLY valid JSON: {"urgency":"low|medium|high","headline":"...",
"explanation":"...","suggested_action":"...","false_alarm_check":"..."}"""

URGENCY_FALLBACK = {"baby_cry": "high", "glass_impact": "medium", "alarm_beep": "high",
                    "impact_thud": "low", "knock": "low", "speech": "low",
                    "water": "medium", "unknown": "low"}
EXPLAIN_FALLBACK = {"baby_cry": "infant cry detected", "glass_impact": "sharp breakable impact",
                    "alarm_beep": "steady alarm-like tone", "impact_thud": "heavy object impact",
                    "knock": "knock-like impact", "speech": "human speech", "water": "running water",
                    "unknown": "unclassified sound"}


def situation_report(payload: dict) -> dict:
    key = _hash("situation", json.dumps(payload, sort_keys=True))
    cached = _cache_get(f"situation_{key}.json")
    if cached:
        return cached
    label = payload.get("event", {}).get("label", "unknown")
    room = payload.get("room", {}).get("room_name") or "an unknown room"
    fallback = {
        "urgency": URGENCY_FALLBACK.get(label, "low"),
        "headline": f"{EXPLAIN_FALLBACK.get(label, 'sound')} — {room}",
        "explanation": f"A {EXPLAIN_FALLBACK.get(label, 'sound')} was detected in {room}.",
        "suggested_action": "No action needed." if label in ("knock", "speech") else "Glance at the room if you are nearby.",
        "false_alarm_check": "Sounds can travel through walls; the room attribution is an estimate.",
        "_model": "fallback",
    }
    if not KEY:
        return fallback
    body = {"model": MODEL_SPARK,
            "messages": [{"role": "system", "content": SITUATION_SYSTEM},
                         {"role": "user", "content": json.dumps(payload)}],
            "temperature": 0.2, "max_tokens": 3000, "reasoning_effort": REASONING_EFFORT,
            "response_format": {"type": "json_object"}}
    try:
        with httpx.Client(timeout=TIMEOUT) as c:
            r = c.post(f"{BASE}/chat/completions", headers=_headers(), json=body)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"].get("content") or ""
        out = _parse_json(text) or {}
        if out.get("headline"):
            out["_model"] = MODEL_SPARK
            return _cache_put(f"situation_{key}.json", out)
    except Exception as e:  # noqa: BLE001
        print(f"[situation] fallback: {type(e).__name__}: {e}")
    return fallback
