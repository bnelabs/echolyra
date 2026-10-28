# Echolyra backend — hackathon starter (Day 1)

FastAPI service that turns a phone sweep recording + RoomPlan geometry (+ photos) into an
acoustic analysis, a physical treatment plan, and **before/after audio** — wired for four
Meta models. It runs **with zero API keys** (deterministic fallbacks + disk cache), so the
demo can never die on stage; add `META_API_KEY` to switch every call to the real API.

## Quickstart

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add META_API_KEY
set -a && . ./.env && set +a
uvicorn app:app --host 0.0.0.0 --reload --port 8080   # --host 0.0.0.0 so the iPhone can reach it
# open http://localhost:8080  → "Load demo room"
```

Optional real Meta models:

```bash
export META_API_KEY=...            # from dev.meta.ai (claim the $150 hackathon credits)
export META_BASE_URL=https://api.meta.ai/v1
export META_MODEL_SPARK=muse-spark-1.3
export META_MODEL_SAM=sam-3.1
export META_MODEL_IMAGE=muse-image-1.0
export META_MODEL_ASR=muse-voice-transcribe-1.0
```

`GET /api/health` shows whether the key is loaded. Every Meta response is cached under
`cache/` keyed by input hash — warm the cache before recording the demo.


## Live-verified with the real Meta API (2026-10-28)

The four model calls below were executed against `https://api.meta.ai/v1` from this backend
and all returned real results (no mocks). Default model: **`muse-spark-1.3-contributor`**
(cheap; inputs/outputs may be used to train Meta models — fine for the demo, use Standard
mode for real users).

| Call | Working request | Verified result | Latency |
|---|---|---|---|
| Muse Spark 1.3 Contributor | `POST /chat/completions`, `max_tokens=4000`, `reasoning_effort="low"`, `response_format={"type":"json_object"}` | real JSON plan (`_model: muse-spark-1.3-contributor`) | **3.3 s** |
| SAM 3.1 | `POST /responses` with `input=[{"type":"message","role":"user","content":[input_text, input_image(data URL)]}]` | boxes + masks; e.g. `curtain` → 2 matches, area share 0.132 | **3.1 s / call** |
| Muse Image 1.0 | `POST /images/edits` (multipart `image` + `prompt`) | edited room render (WebP) → converted to JPEG for iOS | **12.5 s** |
| Muse Voice Transcribe | `POST /asr/transcribe`, multipart `request` JSON + `audio` | exact transcript of a test clip | ~2 s |

**Gotchas that cost time (now handled in `meta_models.py`):**
- Muse Spark 1.3 is a **reasoning model**: with `max_tokens=80` it returns `content: null` and
  spends all tokens on reasoning. Use `max_tokens >= 3000` (4000 here) and
  `reasoning_effort="low"`; typical reasoning is ~600–1,300 tokens before the JSON.
- SAM requires the `{"type":"message", ...}` wrapper (a bare `{role, content}` is rejected with
  *"input[0].content did not match any supported type"*). Data URLs work; one noun phrase per call.
- ASR accepts only **mono s16le WAV at 16 or 24 kHz**; the backend resamples WAV uploads.
  Have the iOS app record the voice brief as 16 kHz mono WAV (m4a needs ffmpeg).
- Muse Image returns **WebP** `b64_json`; `meta_models.py` converts to JPEG so `UIImage` displays it.
- SAM/Image/Spark calls are cached on disk by input hash → **rehearse the demo once to warm the cache**,
  then the demo runs instantly and survives rate limits.

**Cost of a full demo run** (contributor pricing): Spark ~$0.001, 4× SAM ~$0.01,
1× Muse Image ~$0.01, ASR <$0.001 → **well under $0.05 per run**, so $150 of credits is ample.

**Key hygiene:** the key lives only in `.env` (gitignored). Never commit it to the public
hackathon repo; the key you pasted in chat should be rotated after the event.

## API contract (what the iOS app calls)

### `POST /api/analyze` — multipart form
| field | type | notes |
|---|---|---|
| `audio` | WAV file, **may repeat 1–3×** | one recording per listening position of the app's 4 s log sweep (mono, any rate; backend resamples to 48 kHz, then median-fuses RT/C50 across positions) |
| `room` | JSON string | RoomPlan geometry, see schema below |
| `use_case` | string | `movies` \| `music` \| `voice` \| `mixed` |
| `photos` | files[] | 2–4 room photos → SAM 3.1 surface prompts (`wall`,`curtain`,`rug`,`window`) |

Response: `room`, `metrics` (EDT/T30/C50 per octave, `rt60_mid_s`, `n_positions`), `positions`
(per-position metrics), `qc` (per-recording peak/RMS/clipped/silent/bands_ok/warnings),
`inversion` (α per surface per band), `plan` (target RT, predicted RT, steps, cost,
reflection points), `score`, `ai_plan` (Muse Spark JSON), `audio` (`before_url`, `after_url`), `sam`.

```bash
curl -F audio=@sweep_recording.wav \
     -F room="$(cat room.json)" \
     -F use_case=movies \
     -F photos=@room1.jpg -F photos=@room2.jpg \
     http://localhost:8080/api/analyze
```

### Room JSON (produced by the iOS RoomPlan screen)
```json
{
  "name": "living room",
  "length": 5.2, "width": 4.0, "height": 2.6,
  "surfaces": [
    {"id": "floor",   "area_m2": 20.8, "material": "wood"},
    {"id": "ceiling", "area_m2": 20.8, "material": "plaster"},
    {"id": "left",    "area_m2": 10.4, "material": "curtain"},
    {"id": "right",   "area_m2": 10.4, "material": "drywall"},
    {"id": "front",   "area_m2": 13.5, "material": "drywall"},
    {"id": "back",    "area_m2": 13.5, "material": "drywall"}
  ]
}
```
If `surfaces` is omitted, the backend derives a 6-surface room from the dimensions.

### Other endpoints
- `POST /api/segment` (image, concept) → SAM 3.1 boxes (mask-parser TODO; boxes are enough for area shares)
- `POST /api/visualize` (image, instruction) → Muse Image edited render
- `POST /api/transcribe` (audio) → Muse Voice Transcribe text
- `GET /api/demo` → full analysis of the bundled room (used by the browser demo)
- `GET /api/health` → model configuration

## What is real vs. hackathon-simplified

| Piece | Status |
|---|---|
| ESS deconvolution, octave bands, EDT/T30/C50 | real DSP, tested against a synthetic room |
| Eyring inversion of total absorption per band | real closed form; per-surface split uses material priors |
| Per-surface *learned* inversion with confidence | hackathon simplification — roadmap is in `PLAN.md` §5.3 |
| Treatment planner + first-reflection points | real arithmetic + stub catalog (20 SKUs) |
| Before/after RIR simulation | simplified early-reflections + statistical tail; production uses full room simulation |
| SAM 3.1 / Muse Spark / Muse Image / Voice Transcribe | **live-verified on 2026-10-28** (see section above); adapters cache + fall back |
| SAM → material priors → inversion | wired: detected `curtain`/`rug`/`window` areas rewrite the room's surface materials before the Eyring inversion, so vision changes the physics (verified: front wall → curtain, floor → rug) |
| Mask → area projection | TODO: port the special-token parser (`@meta-sam/parser` is JS) or use boxes as proxy |

## Files
- `acoustics.py` — DSP, metrics, inversion, plan, auralization (no external services)
- `meta_models.py` — Meta Model API clients, caching, deterministic fallbacks
- `app.py` — FastAPI routes
- `static/index.html` — judge-facing browser demo

## iOS capture app
See [`../ios/README.md`](../ios/README.md) — a ready-to-paste SwiftUI reference (RoomPlan scan → 2 photos → 3 sweep measurements → analyze → before/after player).

## Test
```bash
python - <<'PY'
import acoustics as ac
r = ac.analyze(ac.default_room())
print(r["metrics"]["rt60_mid_s"], r["plan"]["predicted_rt60_s"], r["score"])
PY
```

## Day-1 checklist (from HACKATHON.md)
1. `GET /api/health` with your key → `"key": true`.
2. Run the demo, listen to before/after.
3. Wire the iOS capture upload (multipart, fields above).
4. Add 2–3 real room photos and confirm SAM returns boxes; cache them.
5. Deploy to a public HTTPS URL (Fly/Render/Railway) and test from the iPhone over cellular.
