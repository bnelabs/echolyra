# Demo runsheet — one page, everything verified

Use this on recording day. Every expected output below was captured from a live dry run.

## 0. Pre-flight (2 min)

```bash
cd sprint/backend
set -a; . ./.env; set +a
../../prototype/.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

- `GET /api/health` → `{"ok": true, ... "spark": "muse-spark-1.3-contributor" ...}`
- Browser demo: `http://<mac-ip>:8080/static/demo.html`
- Sensor node: `http://<mac-ip>:8080/static/node.html`
- Number cards: `docs/media/card_*.png` · app screenshot: `docs/screenshots/rooms_v2.png`

## 1. Browser demo (no hardware path)

1. Open `/static/demo.html` → **Set up 3 demo rooms** → rooms + probe baselines appear:
   `Living 0.46 s · Kitchen 0.219 s · Bedroom 0.709 s`
2. Then press each **Analyze** button. Expected (verified dry run):

| clip | event | room | decision | calibrated |
|---|---|---|---|---|
| Glass | `glass_impact` | Living | **ALERT** | 1.00 |
| Baby cry | `baby_cry` | Living | **ALERT** | 1.00 |
| Knock | `impact_thud` | Kitchen | EXPLAIN | 1.00 |
| Speech | `speech` | Living (uncertain) | SILENT | 1.00 |
| Alarm | `alarm_beep` | Living (uncertain) | EXPLAIN | 1.00 |

3. Press **Fuse recent node detections** (after one detect): shows `event · room · confidence`.
4. Points to say: "ALERT only when event and room are both trustworthy; otherwise it explains
   or stays silent — that's the calibration."

## 2. iOS device path (preferred footage)

1. Reconnect iPhone, unlock. If reinstalled: tap app → **Trust** the developer, then **Allow**
   microphone (one time).
2. Rooms tab → type room name → **Measure acoustics (active probe)** for Living, Kitchen,
   Bedroom. Expect `Room measured: RT60 0.46 s — acoustic fingerprint stored`.
3. Tap **Re-probe** on a room after opening a door → expect `Room drifting — ΔT30 max 11.8%`
   (or `Room changed` for bigger changes).
4. Listen tab → play a glass clink → expect `glass_impact` + room + **ALERT · calibrated** chip.
5. Knock once → `EXPLAIN · needs_confirmation`; knock again within 10 s → `ALERT`.
6. Show Muse Spark situation card (its `_model` is `muse-spark-1.3-contributor`).

## 3. Two-node shot

Fusion window is 10 s, so detect on both nodes then press Fuse within that window.
Dry-run verification (phone node level −20 dB in Living, Mac node −31 dB in Kitchen, same glass
clip): fused `glass_impact · Living`, posteriors **Living 1.00**, 2 nodes.



- Laptop `/static/node.html` (node id `mac-node`, room Kitchen) → **Listen** while the phone
  hears a Living-room event → phone **Listen** → laptop **Fuse** → expected ~
  `glass_impact · Living` (dry-run verification: **Living 0.80 / Kitchen 0.20**).

## 4. Numbers to show (cards in docs/media)

- **92%** real-world events vs **16%** rules (`card_accuracy.png`)
- held-out calibration **0.1285 → 0.0166** (`card_calibration.png`)
- probe RT60 **0.80 → 0.80 s** (`card_probe.png`)
- change detection **0.4% vs 39–60%** (`card_change.png`)
- fusion **Living 0.80** (`card_fusion.png`)

## 5. Fallbacks

- Device dead → record the browser demo path; identical story and numbers.
- Backend restarted → always **Set up 3 demo rooms** first (sessions are in memory).
- If a clip produces `unknown`/silent on stage → say the honest line: "it abstains when the
  evidence is weak — that's the trust feature."
- Never show `.env` or the API key; rotate the key after the event.

## 6. Liveness check (verified)

```
/static/demo.html 200 · /static/node.html 200 · /static/demo/labels.json 200
/static/demo/glass.wav 200 · /api/demo/setup 200 · /api/detect 200 · /api/fuse 200
GET /api/calibration?profile=hybrid → ECE 0.0162, operating point 0.23
```
