# Release notes — `v0.1.1-hackathon` (2026-10-28)

Correction release: external-validation numbers fixed (60 unique clips: 0.900 accuracy,
0.0290 calibrated ECE, 0.893 alert precision); documented numbers are now audited against the
cached measurements by `tools/audit_numbers.py`.

RoomSense: camera-free home awareness that measures rooms, understands sounds on-device, and
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
- **iOS app:** `ios/RoomSense/` — `sprint/ios/install_device.sh` builds/installs; device run
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
