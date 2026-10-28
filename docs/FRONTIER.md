# Frontier roadmap — from demo to a real acoustic-awareness system

**Goal (active until the hackathon ships, then product):** turn RoomSense from a threshold
prototype into a frontier acoustic-awareness system. Acceptance criteria:

1. Real pretrained acoustic understanding on-device (Apple SoundAnalysis, 303 classes) with
   Muse Spark 1.3 Contributor reasoning and calibrated abstention instead of "unknown". **(done, needs device verification)**
2. **Active room fingerprinting**: phone emits a quiet sweep, measures the true RIR, derives
   ISO-3382 EDT/T30 per octave — room identity becomes source-independent. **(backend done, iOS playback next)**
3. **Change detection**: re-probing detects door/furniture/environmental change (and, later,
   presence anomalies). **(done in backend, verified on synthetic rooms)**
4. Calibrated uncertainty (conformal / decision thresholds) so alerts are trustworthy. **(next)**
5. Multi-node localization using old phones/Mac as extra sensors. **(stretch)**
6. Real-room evaluation numbers in docs, not just synthetic. **(blocked on device permissions)**
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

## Increment 2 — plan

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
