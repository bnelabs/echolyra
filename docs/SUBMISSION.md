# RoomSense — submission pack

## Identity

- **Project:** RoomSense — camera-free home awareness
- **Track:** Indie Developer
- **Problem statement:** Push the Frontier
- **One-liner:** *A phone that measures a room's acoustic fingerprint, hears what happens in it,
  says which room it happened in, and knows when it doesn't know — without cameras or stored audio.*
- **Repo:** `github.com/bnelabs/roomsense` (private until submission; flip Nov 3, 18:00 ET)
- **Demo:** `/static/demo.html` (no hardware needed) · iOS app (`sprint/ios/RoomSense/`)

## 100-word blurb

RoomSense turns a phone into a privacy-preserving acoustic sensor. A quiet sweep measures each
room's true impulse response (ISO-3382 RT60/EDT), so rooms get source-independent fingerprints
and can be re-probed to detect change (door, furniture, movement). On-device Apple SoundAnalysis
(303 classes) recognizes what happened; a calibrated decision layer chooses alert / explain /
silent with temporal confirmation, so weak signals are never dressed up as certainty. Muse Spark
1.3 Contributor turns detections into situation reports. On real-world recordings event
recognition is 92% (vs 16% for hand-written rules) and calibrated alerts reach 1.00 precision
for critical events. No cameras. No cloud audio.

## Meta models in the live path (evidence)

| Model | Role | Evidence |
|---|---|---|
| `muse-spark-1.3-contributor` | Situation report: urgency, explanation, what to check | every `/api/detect` response shows `_model: muse-spark-1.3-contributor`; defaults in `.env` |
| `sam-3.1` | Room photos → surface/object context for the map | `backend/meta_models.py`, live-tested (boxes + masks) |
| `muse-voice-transcribe-1.0` | Voice rules ("only alert me for the baby or glass") | `backend/meta_models.py`, live-tested transcript |
| `muse-image-1.0` | Illustrative "what to check" render (optional, cut from demo) | live-tested edits |
| Muse Spark Open | Open-weights option (documented) | Baseten/Modal path in docs |

Meta audio limitation (tested exhaustively): Muse Spark audio input is transcription-only in
practice, so the "ears" are Apple's on-device 303-class classifier and Meta handles reasoning.

## What was built during the hackathon

| Day | Deliverable |
|---|---|
| Oct 28 | Awareness backend (enroll/teach/detect/session), Meta Model API clients live-verified |
| Oct 28 | On-device Apple SoundAnalysis classifier + label mapping (36 identifiers) |
| Oct 28 | Active acoustic probing: RIR deconvolution, ISO-3382 EDT/T30, fingerprint, change detection |
| Oct 28 | Calibrated trust: reliability binning, operating point, conformal threshold, two-tier temporal policy |
| Oct 28 | Multi-node fusion + browser sensor node; probe-informed weighting |
| Oct 28 | Real-world evaluation (ESC-50): 92% vs 16%; held-out calibration ECE 0.0166 |
| Oct 28 | Judge-facing browser demo (`/static/demo.html`) with synthetic demo rooms |
| Oct 29–Nov 3 | Device verification (pending iPhone reconnection), video, submission |

## On-device verified

iPhone 12 Pro Max (iOS 27.0.1), real room: probe **RT60 0.239 s**; re-probes stable
(0.241/0.242 s); door/window open → drift at **23σ**; knocks → Apple labels
`hammer 80% / knock 72% / door 65%` → **EXPLAIN calibrated 0.94** → live Muse Spark.

## Numbers to put on screen

- Event recognition: **92%** on 50 real recordings (rules: 16%)
- Calibrated trust: ECE **0.1285 → 0.0166** held-out; accepted precision **0.944**
- Critical alerts: **1.00 precision** (real data); ambiguous events deferred to confirmation
- Active probe: RT60 recovery **0.80→0.80, 0.60→0.60, 0.35→0.36 s**
- Change detection: same room 0.4% ΔT30 (stable) vs 39–60% (changed)
- Device/server loop: iPhone → `GET /api/session`, `POST /api/enroll`, `POST /api/detect` (200)

## Rubric mapping

| Criterion | Evidence |
|---|---|
| Uses Meta models in the live path | Spark 1.3 Contributor situation reports on every detection (verbatim model id in responses); SAM room context; Voice Transcribe rules |
| Technical ambition | Active RIR probing with ISO-3382, source-independent room fingerprints, calibrated abstention, probe-informed multi-node fusion |
| Creativity | "No cameras: it hears, then forgets" + physically grounded room fingerprints + honesty about uncertainty |
| Works | Browser demo + iOS app (device-compiled), verified end-to-end server loop, real-world benchmark |
| Production potential | Privacy-first architecture, on-device classification, installable calibration profiles, roadmapped mesh localization |

## Submission form — paste-ready fields

- **Project name:** RoomSense — camera-free home awareness
- **Tagline:** It hears your home, measures it, and knows when it doesn't know.
- **Track:** Indie Developer · **Problem statement:** Push the Frontier
- **Repo:** github.com/bnelabs/roomsense (public at flip)
- **Demo video:** `<fill after recording>` · **Live demo (no install):** `http://<mac-ip>:8080/static/demo.html`
- **Description (short):** RoomSense turns a phone into a privacy-preserving acoustic sensor.
  A quiet sweep measures each room's true impulse response (ISO-3382 RT60/EDT), giving
  source-independent room fingerprints and change detection. On-device Apple SoundAnalysis
  (303 classes) recognizes events; a calibrated decision layer alerts only when evidence is
  trustworthy; Muse Spark 1.3 Contributor writes the situation report. No cameras, no stored
  or uploaded audio.
- **Description (long):** see §100-word blurb and `HACKATHON.md` §1–2.
- **Models used:** muse-spark-1.3-contributor, sam-3.1, muse-voice-transcribe-1.0
  (muse-image-1.0 optional). On-device: Apple SoundAnalysis (iOS 27).
- **New-work disclosure:** all code written Oct 28–Nov 3, 2026 during the hackathon; commit
  history and `docs/RELEASE_NOTES.md` map every criterion to its evidence.
- **License:** MIT. **Team:** Baris Naci Erzeren (solo).

## Submission checklist (Nov 3 → Nov 4)

1. Reconnect iPhone → Trust developer → Allow microphone → run real-room verification (probe, event, two-node).
2. Record the 3-minute video (script: `HACKATHON.md` §6).
3. Flip repo public **Nov 3, 18:00 ET**; verify logged-out (README, license, commit dates Oct 28–Nov 3).
4. Video link public + tested logged-out.
5. Submit on the CV platform; screenshot confirmation. Hard deadline **Nov 4, 21:00 ET = Nov 5, 05:00 Istanbul**.
6. Rotate the Meta API key after the event (it was shared during development) and confirm `.env` never entered git.

## Honest limitations

- Room attribution across multiple rooms is hard from one device; the probe fingerprint and
  multi-node fusion are the paths forward, not shipped facts.
- Apple classifier categories are generic; mappings are versioned and imperfect (misses appear
  as abstentions, not wrong alerts).
- Real-world evaluation used ESC-50 (CC BY-NC, not redistributed) as a proxy; phone-in-room
  numbers still pending device reconnection.
- Not a security system: "awareness", with no emergency guarantees.
