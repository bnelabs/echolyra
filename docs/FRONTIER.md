# Frontier roadmap — from demo to a real acoustic-awareness system

**Goal (active until the hackathon ships, then product):** turn RoomSense from a threshold
prototype into a frontier acoustic-awareness system. Acceptance criteria:

1. Real pretrained acoustic understanding on-device (Apple SoundAnalysis, 303 classes) with
   Muse Spark 1.3 Contributor reasoning and calibrated abstention instead of "unknown". **(done, needs device verification)**
2. **Active room fingerprinting**: phone emits a quiet sweep, measures the true RIR, derives
   ISO-3382 EDT/T30 per octave — room identity becomes source-independent. **(backend done, iOS playback next)**
3. **Change detection**: re-probing detects door/furniture/environmental change (and, later,
   presence anomalies). **(done in backend, verified on synthetic rooms)**
4. Calibrated uncertainty (conformal / decision thresholds) so alerts are trustworthy. **(done: ECE 0.039→0.016, operating point 0.25 @ 0.958 precision, zero wrong alerts; see CALIBRATION.md)**
5. Multi-node localization using old phones/Mac as extra sensors. **(fusion backend + browser sensor node done; real two-node demo pending device)**
6. Real-room evaluation numbers in docs, not just synthetic. **(partially done: real-world event evaluation in EVAL_REAL.md; real-room phone evaluation still blocked on device)**
7. Committed to the private repo with docs and demo script updated. **(continuous)**

## Increment 1 — active acoustic probing (2026-10-28, done)

**Signal chain:** `probe_sweep()` (250 Hz–16 kHz, 3 s, 48 kHz, phone-speaker-friendly) →
speaker → room → microphone → Farina deconvolution (auto-aligned on direct path) → RIR →
per-octave EDT/T30 (Schroeder) → room fingerprint (T30 vector + late-tail spectral shape) →
compare with stored baseline → change detection.

Endpoints: `POST /api/probe/enroll`, `POST /api/probe/check`, `GET /api/probe/status`.
The probe's `T30_mid` is attached to the room and **replaces the event-derived decay** in room
attribution (`Session.set_probe_baseline`), so "which room" no longer depends on what sound
happened to be tested.

**Measured on synthetic rooms** (simulated RIRs + noise, 48 kHz):

| scenario | true RT60 | recovered RT60 (mid-band) | verdict |
|---|---|---|---|
| treated room | 0.80 s | **0.80 s** | valid |
| medium room | 0.60 s | **0.60 s** | valid |
| heavily treated | 0.35 s | **0.36 s** | valid |

**Change detection** (baseline 0.80 s):

| scenario | ΔT30 (max band) | fingerprint distance | change detected |
|---|---|---|---|
| same room, new probe | 0.4% | 0.004 | no ✓ |
| door opened / less reverb | 38.9% | 0.55 | **yes** ✓ |
| furniture added | 60.2% | 0.97 | **yes** ✓ |

## Increment 2 — calibrated trust + multi-node (2026-10-28, done)

**Calibration/decision layer** (`backend/calibration.py`, `POST /api/calibrate`): histogram
reliability calibration + precision-targeted operating point + split-conformal threshold, and
an alert/explain/silent policy. Measured: ECE **0.0394 → 0.0162**; operating point 0.25 at
**0.958 precision**; zero wrong alerts across all SNR conditions; silent below 12 dB SNR.
Each `/api/detect` response now includes `decision {decision, calibrated_confidence, reason}`.

**Multi-node fusion** (`backend/fusion.py`, `POST/GET /api/fuse`): level + confidence +
agreement fusion across nodes. Verified: 3 synthetic node reports → `glass_impact` in
**Kitchen (0.79 posterior)**, confidence 0.66, agreement 0.67.
**Browser sensor node** (`static/node.html`): any laptop becomes a second sensor — records
3 s of audio in-browser, converts to WAV, posts to `/api/detect` with node id/room/level, and
the Fusion button combines it with the phone's recent detections. This makes the multi-node
story demo-able without a second iPhone.

## Increment 3 — real-world validation + temporal policy (2026-10-28, done)

- Real-world evaluation on 50 ESC-50 recordings: **92% event accuracy** with the on-device
  model vs **16%** with the earlier rule classifier; rules are now fallback only.
- Class-conditional operating points + two-tier temporal confirmation: immediate critical
  alerts at **precision 1.00**, ambiguous events deferred to confirmation (0.88 if confirmed),
  low-SNR recordings silent. See `EVAL_REAL.md` and `CALIBRATION.md`.
- Apple label mapping expanded to 36 identifiers (alarms, water, liquid, smoke detector, sirens).

## Increment 4 — judge-facing demo (round 3, 2026-10-28)

- **Browser demo** (`static/demo.html` + `POST /api/demo/setup`): three synthetic rooms with
  probe baselines, then recorded clips run through the calibrated pipeline. Verified live:
  glass clip → `glass_impact` 1.0, room Living, decision **alert 1.0**, Muse Spark situation.
- Device still `unavailable` (3rd round): criteria 1/2/5/6 on-device verification pending;
  all software-side work continues.
- Still queued: probe-informed fusion weighting, real-data calibration profile.

## Increment 5 — probe-informed fusion + real calibration profiles (round 4)

- **Probe-informed fusion**: node reports now carry the event's early decay, and `fusion.py`
  matches it against each room's active-probe RT60 (expected decay ≈ 60/RT60 dB/s), weighting
  by level, room confidence and decay consistency. Verified: ambiguous level-only case
  (Kitchen 0.50 vs Living 0.41) becomes **Kitchen 0.75 vs Living 0.22** with probe info.
- **Calibration profiles**: synthetic / real / hybrid profiles fitted and stored; hybrid
  cuts real-world calibration error from **0.205 → 0.049** ECE at 0.958 accepted precision
  (see CALIBRATION.md §3.6). Select via `CALIBRATION_PROFILE` or
  `GET /api/calibration?profile=hybrid`.
- Demo script finalized around active probing → change detection → live event → calibrated
  decision → Muse Spark; browser fallback documented.
- Device still unavailable (4th round): on-device verification of criteria 1/2/5/6 pending.

## Increment 6 — probe drift/transient monitor + held-out validation (round 5)

**Probe drift monitor** (`probe.py`): enrollment estimates each room's repeatability noise from
pairwise probe distances; checks report `stable / drift / changed` with a confidence, plus a
low-confidence `transient_change` flag when the room fluctuates and returns (door open/close,
someone moving things). Verified:

| scenario | ΔT30 (max band) | status | confidence |
|---|---|---|---|
| same room, new probe | 0.4% | stable | 0.96–0.97 |
| mild change | 11.8% | drift | 0.71 |
| moderate change | 22.3% | changed | 0.72 |
| real changes | 53–60% | changed | 0.94–0.99 |

**Held-out calibration validation**: 30/20 split of real recordings; hybrid profile reaches
**ECE 0.0166** on unseen real audio at 0.944 accepted precision (see CALIBRATION.md §3.6).

## Increment 4 — plan

1. **iOS probe flow** (Oct 29): play the sweep through the phone speaker while recording (co-located
   measurement), upload to `/api/probe/enroll`; show measured RT60 + "room learned"; add a
   "re-probe" button that calls `/api/probe/check` and surfaces *"your room changed"*.
2. **Calibrated abstention** (Oct 30): temperature-scale the Apple-classifier posteriors;
   conformal thresholds for "alert / explain / stay silent"; surface SNR + certainty in the UI
   (partially done).
3. **Real-room protocol** (Oct 31): 3 rooms × 3 probes + 3 event types per room, real device;
   publish RT60 error vs the probe and room-ID accuracy into `EVAL_REAL.md`.
4. **Multi-node stretch** (Nov 1): browser node (Mac) as a second sensor; level/spectral fusion
   for "which room" beyond single-device limits.
5. **Demo script** updated (Nov 2): show (a) active probe learning a room, (b) door-open change
   detected days later, (c) real event with on-device label + Muse Spark situation, (d) honest
   abstention on a weak signal.

## Why active probing is the frontier piece

Passive classification can only label an event; it cannot tell you whether the room itself
changed. Active probing measures the room's transfer function directly, which unlocks:
source-independent room fingerprints, change/presence detection, calibrated reverberation
metrics, and eventually geometry/material inference — all with the same phone speaker and mic
the user already owns, and all without cameras or cloud audio.
