# Release notes — Echolyra (`v0.6.0`)

Project renamed **Echolyra** (formerly RoomSense) — echo + lyre, pronounced *ek-oh-LY-rah*.
The iOS bundle identifier remains `com.bnelabs.roomsense` because the free provisioning
profile cannot auto-provision a new identifier; display name, product, backend, repo and docs
are Echolyra.

## v0.2.0-hackathon (2026-10-28)

Submission candidate: judge-facing README, 11/11 claim verifier, doc-link + number audits, fresh-clone reproducibility proof, one-page submission runbook.

## v0.1.1-hackathon

Correction release: external-validation numbers fixed (60 unique clips: 0.900 accuracy,
0.0290 calibrated ECE, 0.893 alert precision); documented numbers are now audited against the
cached measurements by `tools/audit_numbers.py`.

Echolyra: camera-free home awareness that measures rooms, understands sounds on-device, and
knows when it doesn't know.

## What is in this release

| # | Acceptance criterion | Evidence | Commits |
|---|---|---|---|
| 1 | Pretrained on-device understanding (Apple SoundAnalysis, 303 classes) + Muse Spark 1.3 Contributor reasoning + calibrated abstention | 92% on 50 real recordings vs 16% rules (`docs/EVAL_REAL.md`) | `de67a7a`, `3233eed`, `a3e9a31` |
| 2 | Active room fingerprinting (quiet sweep → RIR → ISO-3382 EDT/T30 → fingerprint), probe-only enrollment | RT60 recovery 0.80→0.80, 0.60→0.60, 0.35→0.36 s (`docs/FRONTIER.md`); probe-only enrollment 0.444 vs 0.500 knocks | `e480045`, `e57d90d`, `1a61149`, `b30059e` |
| 3 | Change detection + presence/activity anomalies | stable 0.4% ΔT30 (conf 0.96) vs changed 22–60% (conf 0.72–0.99); calibrated activity threshold 0.20 | `e480045`, `6ba3ff7`, `ee74c66` |
| 4 | Calibrated uncertainty (reliability + operating point + conformal + temporal) | held-out ECE 0.1285→0.0166 at 0.944 precision; zero wrong critical alerts | `a3e9a31`, `bcd7ff6`, `6ba3ff7`, `3233eed` |
| 5 | Multi-node localization | two-node dry run: `glass_impact · Living`, posteriors Living 1.00; probe-aware weighting | `a3e9a31`, `bcd7ff6`, `558858c` |
| 6 | Real-room evaluation numbers | real-world event evaluation + held-out calibration validation (`docs/EVAL_REAL.md`); phone-in-room pending device | `3233eed`, `6ba3ff7` |
| 7 | Repo/docs/demo script | browser demo, node sensor page, runsheet, storyboard, voiceover, number cards; flip checker PASS | `e32f4e6`, `ee74c66`, `080fd27`, `1f08c3f` |

## Judge-facing entry points

- **Browser demo (no hardware):** `/static/demo.html` — 3 demo rooms with probe baselines, five
  clips through the full calibrated pipeline, live Muse Spark situation reports.
- **Sensor-node page:** `/static/node.html` — any laptop joins as a second microphone.
- **iOS app:** `ios/Echolyra/` — `sprint/ios/install_device.sh` builds/installs; device run
  pending iPhone reconnection.
- **Verification:** `tools/verify_claims.py` (all 8 checks pass, output in `docs/VERIFY.md`)
  and `tools/check_submission.py` (flip-readiness PASS).
- **On-device path:** `docs/DEVICE_VERIFICATION.md` (10-step checklist + expected outputs).
- **Docs:** `HACKATHON.md` (runbook, demo script), `docs/SUBMISSION.md` (submission pack),
  `docs/DEMO_RUNSHEET.md`, `docs/DEMO_VOICEOVER.md`, `docs/FRONTIER.md`, `docs/CALIBRATION.md`,
  `docs/EVAL_REAL.md`.

## Verified numbers

```
real-world event accuracy   92% (n=50)      vs 16% hand-written rules
held-out calibration ECE    0.1285 → 0.0166  (fit 30 / val 20)
accepted-detection precision 0.944 held-out
critical immediate alerts   precision 1.00
probe RT60 recovery         0.80→0.80, 0.60→0.60, 0.35→0.36 s
change detection            0.4% ΔT30 stable vs 39–60% changed
probe-only enrollment       0.444 accuracy vs 0.500 knocks (uncertain 0.47 vs 0.72)
two-node fusion             glass_impact · Living, posteriors Living 1.00
```

## Experimental: walk-scan reflection map

New **Walk scan** captures probes at four hand positions along an approximate L-path and
localizes reflective surfaces by voting echo-distance circles on a floor grid. Persistent
reflections (all poses) are separated from unstable ones (some poses → possible movement), and
the app renders a 3D candidate map with the phone path. It is not object identification:
spacing is instructed not measured, the plane is 2D, and height/identity are unknown. Backend
only; no audio to Meta. 53 geometry tests pass.

## Experimental: sound-only 3D room (low-confidence tier)

Real-room recordings that fail the strict shoebox fit now return a **clearly-labelled
low-confidence estimate** (or several) instead of only "couldn't map this room yet". A clutter
guard keeps dense random echoes and noise rejected; the UI shows an orange "verify the
dimensions" warning, and estimates remain unverified (e.g. saved iPhone living-room captures:
3 low-confidence layouts, ≈4.99–6.49 m × 2.16–4.99 m × 1.87–2.16 m, 57 % echo coverage).

## Experimental: sound-only 3D room (rich presentation)

Richer 3D scene: measured shell + **distance-only acoustic object candidates** (cyan rings) +
clearly-labelled **illustrative staging** (Meta-composed numeric spec or procedural fallback)
with stylized furniture meshes, measured/illustrative badges and banner. Staged objects are not
measurements; a single-position recording cannot resolve object direction/identity. Backend does
noise-to-signal filtering (matched filter, ≥24 dB probe match, cross-capture repeatability,
2–8 kHz envelope, bounded upserts); optional staging sends numeric diagnostics only and cannot
change the acoustic fit. Verified with 46 tests, live staging fallback, and simulator/device
builds.

## Experimental: sound-only 3D room (baseline)

New **3D Room** tab estimates a rectangular shell from repeated probe echoes — no camera,
LiDAR, supplied dimensions, or model-generated geometry. Backend `/api/geometry/*` routes never
persist captures or change enrollment; optional Meta review sends allowlisted numeric
diagnostics only. Verified: synthetic demo recovers 5.699 × 4.298 × 2.898 m from 21 echoes
(fit 0.037 ms); real iPhone living-room sweeps correctly return **insufficient_evidence** instead
of inventing dimensions. 37 unit tests pass; total geometry upload body cap wired and tested.
Real-room dimensional accuracy is **not** established.

## On-device verification (iPhone 12 Pro Max, iOS 27.0.1)

- **Active probe**: 3-sweep enrollment measured Living **RT60 0.239 s** (2–8 kHz usable bands);
  same-room re-probes **0.241 / 0.242 s → stable** (ΔT30 7.7% / 1.6%, conf 0.69 / 0.93);
  opening a door/window produced **drift** (fingerprint distance 0.258 = **23σ**, conf 0.51).
- **On-device hearing**: real knocks → Apple labels `hammer` 80% / `knock` 72% / `door` 65% →
  event `knock` 0.72 → decision **EXPLAIN calibrated 0.94** (temporal: needs confirmation) →
  live Muse Spark situation, SNR 14.4 dB.
- **Glass path**: `glass_clink` 46% → `glass_impact` → **EXPLAIN calibrated 0.64** → live Muse
  Spark (below the critical immediate-alert bar; correct behaviour).
- **Browser sensor node (Mac)**: real knock posted as `mac-node / Kitchen / knock 1.0 /
  SNR 46.3 dB`; fusion localized Kitchen 1.0. The page now explains the secure-context mic rule
  (use `http://localhost:8080/static/node.html`).
- **Protocol findings fixed**: 250/500 Hz and even 1 kHz are unusable on a phone speaker;
  analysis now uses **2–8 kHz** only, with 3-sweep enrollment and measured-noise thresholds.

## External validation (60 unseen real clips, corrected round 17)

- event accuracy **0.900** (glass/knock/alarm 1.00, baby 0.90, water 0.75)
- calibration ECE **0.1593 → 0.0290** with no refit; 28 alerts at **0.893 precision**
  (3 wrong); aggregate in `docs/eval_external.json`, checked by `tools/verify_claims.py`.

## Known limitations (kept honest)

- Phone-in-room verification of probe RT60 / two-node footage still pending device reconnection.
- Room attribution from a single device is fundamentally hard; active probes and multi-node
  fusion are the paths, not shipped facts.
- Apple categories are generic; mapping gaps appear as abstentions, never as false critical alerts.
- ESC-50 (CC BY-NC) used for evaluation only — its audio is not redistributed.
- Contributor-mode inputs may train Meta models (fine for the hackathon; Standard mode for real users).

## Negative results (documented, not shipped)

Learned room-distance weights (overfit, held-out unchanged), probe-RT60 decay substitution
(degraded 0.500→0.389), probe-template log-mel room ID (0.458, same ceiling as true RIRs),
multi-seed/weighted RIR template synthesis (worse than simple). See `docs/FRONTIER.md`.

## Next (post-hackathon)

Device verification + real-room numbers, larger real calibration corpus with fit/validation
split, two-phone mesh, iOS TestFlight polish, and a privacy/security review before any
consumer release.
