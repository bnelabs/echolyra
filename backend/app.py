"""RoomTwin hackathon backend — FastAPI entrypoint.

Endpoints
  GET  /api/health          -> model configuration + cache state
  GET  /api/demo            -> full end-to-end analysis of a bundled demo room
  POST /api/analyze         -> multipart: audio(wav), room(json), use_case, photos[]
  POST /api/segment         -> multipart: image, concept  (SAM 3.1)
  POST /api/visualize       -> multipart: image, instruction (Muse Image)
  POST /api/transcribe      -> multipart: audio (Muse Voice Transcribe)
"""
from __future__ import annotations

import asyncio
import io
import json
import time
import uuid
import wave
import os
import pathlib
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, Form, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from scipy.signal import resample_poly

import acoustics as ac
import awareness as aw
import calibration
import fusion
import probe
import meta_models as mm
import geometry
import geometry_advisor
import geometry_stage
import geometry_upload

ROOT = Path(__file__).parent
OUT = ROOT / "static" / "out"
OUT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="RoomTwin", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
# Bound geometry uploads before the multipart parser buffers/spools an unbounded body.
app.add_middleware(geometry_upload.GeometryUploadLimit)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

DEMO_CACHE: dict[str, dict] = {}
SESSION = aw.Session()
NODE_REPORTS: list[dict] = []
RECENT_DECISIONS: dict[str, list[tuple[float, str, str]]] = {}
# Categories where a single high-confidence detection is already actionable (safety-relevant).
CRITICAL_LABELS = {"glass_impact", "alarm_beep", "baby_cry"}


def temporal_confirm(node: str, label: str, decision: dict) -> dict:
    """A single detection may explain; an alert needs a second agreeing detection soon.

    This is the temporal half of the decision policy: it halves false alarms from a single
    ambiguous transient without delaying the explanatory path.
    """
    now = time.time()
    history = [h for h in RECENT_DECISIONS.get(node, []) if now - h[0] <= 10.0]
    RECENT_DECISIONS[node] = history
    if decision.get("decision") == "alert":
        critical = (label in CRITICAL_LABELS
                    and float(decision.get("calibrated_confidence", 0.0)) >= 0.9)
        if not critical:
            confirmed = any(lbl == label and dec in ("alert", "explain") for _, lbl, dec in history)
            if not confirmed:
                decision = {**decision, "decision": "explain", "reason": "needs_confirmation"}
    history.append((now, label, decision.get("decision", "silent")))
    RECENT_DECISIONS[node] = history[-20:]
    return decision


# ------------------------------------------------------------------ helpers
def read_wav_mono(raw: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(raw), "rb") as w:
        fs, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        frames = w.readframes(n)
    if sw == 1:
        arr = (np.frombuffer(frames, dtype=np.uint8).astype(np.float64) - 128) / 128
    elif sw == 2:
        arr = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768
    elif sw == 4:
        arr = np.frombuffer(frames, dtype="<i4").astype(np.float64) / 2147483648
    else:
        raise ValueError(f"unsupported sample width {sw}")
    if ch > 1:
        arr = arr.reshape(-1, ch).mean(axis=1)
    return arr, fs


def resample(x: np.ndarray, fs: int, target: int = ac.FS) -> np.ndarray:
    if fs == target:
        return x
    from math import gcd
    g = gcd(int(fs), target)
    return resample_poly(x, target // g, fs // g)


def save_wav(name: str, data: bytes) -> str:
    (OUT / name).write_bytes(data)
    return f"/static/out/{name}"


def analysis_payload(room, measured_rir=None, use_case="movies") -> dict:
    result = ac.analyze(room, measured_rir=measured_rir, use_case=use_case)
    audio = result.pop("audio")
    tag = uuid.uuid4().hex[:10]
    result["audio"] = {"before_url": save_wav(f"before_{tag}.wav", audio["before"]),
                       "after_url": save_wav(f"after_{tag}.wav", audio["after"])}
    result["meta_models"] = mm.configured()
    result["ai_plan"] = mm.muse_spark_plan({
        "room": result["room"], "metrics": result["metrics"],
        "inversion": result["inversion"], "plan": result["plan"], "score": result["score"]})
    return result


# ------------------------------------------------------------------ routes
@app.get("/api/health")
def health():
    return {"ok": True, "models": mm.configured(), "demo_cached": "demo" in DEMO_CACHE}


@app.get("/api/demo")
def demo():
    if "demo" not in DEMO_CACHE:
        DEMO_CACHE["demo"] = analysis_payload(ac.default_room())
    return DEMO_CACHE["demo"]


@app.post("/api/analyze")
async def analyze(
    room: str = Form("{}"),
    use_case: str = Form("movies"),
    audio: list[UploadFile] | None = File(None),
    photos: list[UploadFile] | None = File(None),
):
    try:
        room_obj = ac.room_from_json(json.loads(room) if room else {})
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"bad room json: {e}"})
    # 1) vision first: SAM 3.1 area shares steer the material priors (vision -> physics)
    seg, vision = [], None
    if photos:
        jobs = []
        for ph in photos[:3]:
            img = await ph.read()
            for concept in ("wall", "curtain", "rug", "window"):
                jobs.append((img, concept, ph.content_type or "image/jpeg"))
        seg = list(await asyncio.gather(*[asyncio.to_thread(mm.sam_segment, *j) for j in jobs]))
        shares = mm.materials_from_segments(seg)
        vision = {"segments": seg, "material_shares": shares, **ac.apply_vision_prior(room_obj, shares)}
    # 2) measurement — 1..3 positions, median-fused in acoustics.analyze
    measured, audio_metas, qc = [], [], []
    if audio:
        for f in audio[:3]:
            raw = await f.read()
            try:
                x, fs = read_wav_mono(raw)
                x = resample(x, fs)
                # the app plays our known 4 s sweep; the upload is the recording
                rir = ac.deconvolve(x, ac.exp_sweep(), ac.FS)
                m = ac.analyze_rir(rir)
                measured.append(rir)
                qc.append(ac.quality_check(x, m))
                audio_metas.append({"bytes": len(raw), "sample_rate_in": fs,
                                    "duration_s": round(len(x) / ac.FS, 2)})
            except Exception as e:
                audio_metas.append({"error": f"could not read wav: {e}"})
    payload = analysis_payload(room_obj, measured if measured else None, use_case)
    payload["audio_meta"] = audio_metas
    payload["qc"] = qc
    if vision:
        payload["sam"] = vision
    return payload


@app.post("/api/segment")
async def segment(image: UploadFile = File(...), concept: str = Form("wall")):
    return mm.sam_segment(await image.read(), concept, image.content_type or "image/jpeg")


@app.post("/api/visualize")
async def visualize(image: UploadFile = File(...), instruction: str = Form("add acoustic panels")):
    return mm.muse_image_edit(await image.read(), instruction, image.content_type or "image/jpeg")


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    return mm.transcribe(await audio.read(), audio.filename or "brief.m4a",
                         audio.content_type or "audio/mp4")


# ------------------------------------------------------------------ RoomSense awareness
@app.get("/api/session")
def session_summary():
    return SESSION.summary()


@app.post("/api/reset")
def session_reset():
    SESSION.reset()
    return {"ok": True}


@app.post("/api/enroll")
async def enroll(room_id: str = Form(...), room_name: str = Form(...),
                 audio: list[UploadFile] | None = File(None)):
    raws = [await f.read() for f in (audio or [])]
    try:
        room = SESSION.enroll(room_id, room_name, raws)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": str(e)})
    return {"room": room, "session": SESSION.summary()}


@app.post("/api/teach")
async def teach(label: str = Form(...), audio: list[UploadFile] | None = File(None)):
    raws = [await f.read() for f in (audio or [])]
    try:
        out = SESSION.teach(label, raws)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": str(e)})
    return {**out, "session": SESSION.summary()}


@app.post("/api/detect")
async def detect(audio: UploadFile = File(...), node_room: str = Form(""),
                 sound_labels: str = Form("[]"), node_id: str = Form(""),
                 level_db: float | None = Form(None)):
    raw = await audio.read()
    if os.environ.get("DEBUG_CAPTURE", "0") == "1":
        try:
            Path("/tmp/last_device_clip.bin").write_bytes(raw)
        except Exception:
            pass
    try:
        import json as _json
        heard = _json.loads(sound_labels) if sound_labels else []
        if not isinstance(heard, list):
            heard = []
    except Exception:
        heard = []
    try:
        rec = SESSION.detect(raw, heard=heard)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": str(e)})
    payload = {**rec, "node_room": node_room,
               "sensor_room": None, "heard": rec.get("heard", [])}
    payload["situation"] = mm.situation_report(payload)
    decision = calibration.decide(
        float(rec["event"].get("confidence", 0.0)),
        float(rec["room"].get("confidence", 0.0)),
        float(rec["features"].get("snr_db", 30.0)),
        event_label=rec["event"].get("label", ""))
    payload["decision"] = temporal_confirm(node_id or node_room or "phone",
                                           rec["event"].get("label", ""), decision)
    NODE_REPORTS.append({
        "node_id": node_id or node_room or "phone",
        "node_room": node_room or None,
        "room_name": rec["room"].get("room_name"),
        "room_confidence": rec["room"].get("confidence", 0.0),
        "event_label": rec["event"].get("label"),
        "event_confidence": rec["event"].get("confidence", 0.0),
        "level_db": float(level_db) if level_db is not None else float(rec["features"].get("peak_db", -60.0)),
        "snr_db": float(rec["features"].get("snr_db", 0.0)),
        "event_decay": rec["features"].get("early_decay_db_s"),
        "ts": time.time(),
    })
    del NODE_REPORTS[:-40]
    payload["node_id"] = node_id or node_room or "phone"
    return payload


# ------------------------------------------------------------------ active acoustic probe
@app.post("/api/probe/enroll")
async def probe_enroll(room_id: str = Form(...), room_name: str = Form(...),
                       audio: list[UploadFile] | None = File(None)):
    recs = []
    debug_dir = None
    if os.environ.get("DEBUG_CAPTURE") == "1":
        debug_dir = pathlib.Path(__file__).parent / "cache" / "probe_clips" / room_id
        debug_dir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate((audio or [])[:3]):
        raw = await f.read()
        if debug_dir is not None:
            (debug_dir / f"{int(time.time())}_{i}.wav").write_bytes(raw)
        x, fs = read_wav_mono(raw)          # 16 kHz mono float
        if fs != probe.FS:
            x = resample(x, fs, probe.FS)
        recs.append(x)
    if not recs:
        return JSONResponse(status_code=400, content={"error": "no probe recordings"})
    try:
        out = probe.enroll(room_id, room_name, recs)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": str(e)})
    # Seed the room signature from the measured RIR *before* attaching the probe baseline
    # (set_probe_baseline creates the room record, so order matters here).
    seeded = None
    rir = probe.load_rir(room_id)
    existing = SESSION.state.get("rooms", {}).get(room_id, {})
    if rir is not None and "rvec" not in existing:
        try:
            seeded = SESSION.enroll_from_probe(room_id, room_name, rir, probe.FS)
        except Exception:
            seeded = None
    linked = SESSION.set_probe_baseline(room_id, out["room"].get("rt60_mid_s"), out["room"].get("rt60_mid_s"))
    return {"probe": out, "linked_session": linked, "seeded_room": seeded}


@app.post("/api/probe/check")
async def probe_check(room_id: str = Form(...), audio: UploadFile = File(...)):
    raw = await audio.read()
    if os.environ.get("DEBUG_CAPTURE") == "1":
        debug_dir = pathlib.Path(__file__).parent / "cache" / "probe_clips" / room_id
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"check_{int(time.time())}.wav").write_bytes(raw)
    x, fs = read_wav_mono(raw)
    if fs != probe.FS:
        x = resample(x, fs, probe.FS)
    try:
        out = probe.check(room_id, x)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": str(e)})
    if out.get("current", {}).get("rt60_mid_s") is not None:
        SESSION.set_probe_baseline(room_id, out["current"]["rt60_mid_s"], out["current"]["rt60_mid_s"])
    return out


@app.get("/api/probe/status")
def probe_status():
    return probe.status()


# -------------------------------------------------------- experimental acoustic geometry
# Geometry capture is deliberately independent of enrollment, debugging capture and
# household state. Uploaded audio is decoded transiently, never written by these routes.
GEOMETRY_MAX_FILE_BYTES = 2_000_000
GEOMETRY_MAX_REVIEW_BYTES = 64_000
GEOMETRY_WORKERS = asyncio.Semaphore(1)


def decode_geometry_recording(raw: bytes) -> np.ndarray:
    import soundfile as sf
    try:
        with sf.SoundFile(io.BytesIO(raw)) as recording:
            if recording.format not in {"WAV", "WAVEX"}:
                raise ValueError("Use a WAV recording of the RoomSense probe.")
            if not 32_000 <= recording.samplerate <= 96_000 or recording.channels not in (1, 2):
                raise ValueError("Use a mono or stereo WAV at 32–96 kHz.")
            duration = len(recording) / recording.samplerate
            if not 3.3 <= duration <= 7.0:
                raise ValueError("Each probe recording must be 3.3–7 seconds long.")
            fs = recording.samplerate
            samples = recording.read(dtype="float64", always_2d=True).mean(axis=1)
    except ValueError:
        raise
    except Exception:
        raise ValueError("Could not decode the probe WAV.") from None
    if not np.isfinite(samples).all():
        raise ValueError("The recording contains invalid samples.")
    return resample(samples, fs, probe.FS)


@app.post("/api/geometry/reconstruct")
async def geometry_reconstruct(audio: list[UploadFile] | None = File(None)):
    if not audio or not 1 <= len(audio) <= 3:
        return JSONResponse(status_code=400, content={"error": "Send one to three probe WAV recordings from the same stationary position."})
    recordings = []
    for upload in audio:
        raw = await upload.read(GEOMETRY_MAX_FILE_BYTES + 1)
        if len(raw) > GEOMETRY_MAX_FILE_BYTES:
            return JSONResponse(status_code=413, content={"error": "Each probe WAV must be smaller than 2 MB."})
        try:
            recordings.append(decode_geometry_recording(raw))
        except ValueError as error:
            return JSONResponse(status_code=400, content={"error": str(error)})
    async with GEOMETRY_WORKERS:
        return await asyncio.to_thread(geometry.reconstruct, recordings, probe.FS)


@app.get("/api/geometry/demo")
async def geometry_demo():
    async with GEOMETRY_WORKERS:
        if "geometry" not in DEMO_CACHE:
            DEMO_CACHE["geometry"] = await asyncio.to_thread(geometry.demo)
        return DEMO_CACHE["geometry"]


@app.post("/api/geometry/stage")
async def geometry_stage_route(request: Request):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > GEOMETRY_MAX_REVIEW_BYTES:
            return JSONResponse(status_code=413, content={"error": "Geometry staging request exceeds 64 KB."})
        chunks.append(chunk)
    try:
        result = json.loads(b"".join(chunks))
        if not isinstance(result, dict):
            raise ValueError
    except (ValueError, UnicodeError):
        return JSONResponse(status_code=400, content={"error": "Send a geometry result as JSON."})
    return await asyncio.to_thread(geometry_stage.stage, result)


@app.post("/api/geometry/review")
async def geometry_review(request: Request):
    # Review is a separate, user-triggered operation. No audio field is accepted.
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > GEOMETRY_MAX_REVIEW_BYTES:
            return JSONResponse(status_code=413, content={"error": "Geometry review exceeds 64 KB."})
        chunks.append(chunk)
    try:
        result = json.loads(b"".join(chunks))
        if not isinstance(result, dict):
            raise ValueError
    except (ValueError, UnicodeError):
        return JSONResponse(status_code=400, content={"error": "Send a geometry result as JSON."})
    return await asyncio.to_thread(geometry_advisor.review, result)


# ------------------------------------------------------------------ calibration + fusion
@app.get("/api/calibration")
def calibration_status(profile: str = "synthetic"):
    params = calibration.load_params(profile)
    if not params:
        return {"calibrated": False, "profile": profile,
                "available": ["synthetic", "real", "hybrid"]}
    return {**params, "active_profile": profile}


@app.post("/api/calibrate")
async def calibrate():
    params = await asyncio.to_thread(calibration.run_calibration, 2)
    return {"ok": True, "ece_before": params["ece_before"], "ece_after": params["ece_after"],
            "n_samples": params["n_samples"], "conformal": params["conformal"],
            "operating_point": params.get("operating_point"),
            "decisions_by_snr": params["decisions_by_snr"]}


@app.get("/api/debug/nodes")
def debug_nodes():
    return {"reports": NODE_REPORTS[-10:]}


@app.get("/api/fuse")
def fuse_recent():
    room_probe = {}
    try:
        for r in probe.status().get("rooms", []):
            if r.get("rt60_mid_s"):
                room_probe[r["name"]] = float(r["rt60_mid_s"])
    except Exception:
        pass
    return fusion.fuse(NODE_REPORTS, room_probe=room_probe)


@app.post("/api/fuse")
async def fuse_reports(reports: list[dict]):
    try:
        room_probe = {r["name"]: float(r["rt60_mid_s"]) for r in probe.status().get("rooms", [])
                      if r.get("rt60_mid_s")}
    except Exception:
        room_probe = None
    return fusion.fuse(reports, room_probe=room_probe)


# ------------------------------------------------------------------ judge-facing demo setup
@app.post("/api/demo/setup")
def demo_setup():
    """Enroll three synthetic rooms (events + active-probe baselines) so the browser demo
    has a realistic session without any hardware."""
    import wave as _wave
    SESSION.reset()
    probe.STATE_PATH.unlink(missing_ok=True)
    rng = np.random.default_rng(7)
    rooms = {"living": (0.45, 7000, 0.0), "kitchen": (0.22, 2500, -7.0), "bedroom": (0.70, 4500, -3.0)}
    def make_transfer(rt, cutoff, gain, seed):
        n = int(0.9 * 16000); t = np.arange(n) / 16000
        r = np.random.default_rng(seed)
        ir = r.normal(0, 1, n) * np.exp(-6.91 * t / rt)
        from scipy.signal import butter, sosfiltfilt
        ir = sosfiltfilt(butter(4, min(cutoff, 16000 / 2 * 0.95), "low", fs=16000, output="sos"), ir)
        ir[0] += 1.0
        return ir / np.max(np.abs(ir)) * (10 ** (gain / 20))
    def knock(seed):
        r = np.random.default_rng(seed)
        x = r.normal(0, 1e-4, int(1.6 * 16000)); k = np.zeros(int(0.28 * 16000)); i = int(0.03 * 16000)
        k[i:i+40] += np.hanning(40) * 0.8; t = np.arange(int(0.2 * 16000)) / 16000
        k[i:i+len(t)] += 0.35 * np.sin(2 * np.pi * 180 * t) * np.exp(-t / 0.02) * 0.8
        x[int(0.4 * 16000):int(0.4 * 16000)+len(k)] += k
        return x
    from math import gcd
    from scipy.signal import resample_poly
    for i, (room, (rt, cut, gain)) in enumerate(rooms.items()):
        tr = make_transfer(rt, cut, gain, i)
        for t in range(2):
            y = np.convolve(knock(t), tr)[: int(2.4 * 16000)]
            SESSION.enroll(room, room.capitalize(), [aw.wav_bytes(y)])
        sweep = probe.probe_sweep()
        rir = ac.simulate_treated_rir(ac.default_room(), {"predicted_rt60_s": rt}, rt, fs=probe.FS)
        rec = np.convolve(rir, sweep)[: len(rir) + len(sweep)]
        rec = rec / max(np.max(np.abs(rec)), 1e-9) * 0.5 + rng.normal(0, 2e-3, len(rec))
        probe.enroll(room, room.capitalize(), [rec])
        SESSION.set_probe_baseline(room, rt, rt)
    return {"ok": True, "session": SESSION.summary(), "probe": probe.status()}


@app.post("/api/probe/seed")
def probe_seed(room_id: str = Form(...), room_name: str = Form("")):
    """Enroll a room from its stored probe RIR alone (no knocks)."""
    rir = probe.load_rir(room_id)
    if rir is None:
        return JSONResponse(status_code=400, content={"error": "no stored RIR for this room"})
    room = SESSION.enroll_from_probe(room_id, room_name or room_id, rir, probe.FS)
    return {"ok": True, "room": {k: v for k, v in room.items() if k != "rvec"},
            "note": "room signature synthesized from the measured impulse response"}


@app.get("/", response_class=HTMLResponse)
def index():
    page = ROOT / "static" / "index.html"
    return HTMLResponse(page.read_text()) if page.exists() else HTMLResponse("<h1>RoomTwin API</h1>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
