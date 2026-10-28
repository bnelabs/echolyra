# Frontier roadmap — from demo to a real acoustic-awareness system

**Goal (active until the hackathon ships, then product):** turn RoomSense from a threshold
prototype into a frontier acoustic-awareness system. Acceptance criteria:

1. Real pretrained acoustic understanding on-device (Apple SoundAnalysis, 303 classes) with
   Muse Spark 1.3 Contributor reasoning and calibrated abstention instead of "unknown". **(done, needs device verification)**
2. **Active room fingerprinting**: phone emits a quiet sweep, measures the true RIR, derives
   ISO-3382 EDT/T30 per octave — room identity becomes source-independent. **(backend done, iOS playback next)**
3. **Change detection**: re-probing detects door/furniture/environmental change (and, later,
   presence anomalies). **(done in backend, verified on synthetic rooms)**
4. Calibrated uncertainty (conformal / decision thresholds) so alerts are trustworthy. **(done: ECE 0.039→0.016, operating point 0.25 @ 0.958 precision, zero wrong alerts on the synthetic calibration set; see CALIBRATION.md)**
5. Multi-node localization using old phones/Mac as extra sensors. **(fusion backend + browser sensor node done; real two-node demo pending device)**
6. Real-room evaluation numbers in docs, not just synthetic. **(partially done: real-world event evaluation in EVAL_REAL.md; real-room phone evaluation still blocked on device)**
7. Committed to the private repo with docs and demo script updated. **(continuous)**

## Increment 1 — active acoustic probing (2026-10-28, done)

**Signal chain:** `probe_sweep()` (250 Hz–16 kHz, 3 s, 48 kHz, phone-speaker-friendly) →
speaker → room → microphone → Farina deconvolution (auto-aligned on direct path) → RIR →
per-octave EDT/T30 (Schroeder) → room fingerprint (T30 vector + late-tail spectral shape) →
compare with stored baseline → change detection.

Endpoints: `POST /api/probe/enroll`, `POST /api/probe/check`, `GET /api/probe/status`.
The probe's `T30_mid` is attached to the room and used for change detection and fusion. We
initially substituted it for the event-derived decay in passive room attribution; round 9
measurements showed that **hurts** accuracy (knocks enrollment: 0.500 → 0.389 on 54 events), so
the default is now `probe_decay_mode="ignore"` — probe truth is kept for probing/fusion, not
for re-scoring passive events.

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
**0.958 precision**; zero wrong alerts on the synthetic calibration set across all SNR conditions; silent below 12 dB SNR.
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

## Increment 7 — activity calibration, flip-readiness, storyboard (round 7)

- **Activity-score calibration** (`tools_calibrate_activity.py`): simulated stable vs
  door-open/close series → threshold **0.20**, simulated false-positive rate **0%**, detection
  rate **100%** (stable series score 0.0, activity series 1.0). `probe.check()` now reads the
  calibrated threshold; honest caveat: synthetic simulation, real-probe FAR to be measured on
  device.
- **Flip-readiness checker** (`tools/check_submission.py`): verifies required files, tracked
  secrets/credentials, forbidden paths, committed audio outside the synthetic demo set, commit
  dates, dirty tree. It found and we fixed: missing LICENSE, missing privacy section, wrong
  asset paths. Current status: **PASS**.
- **Demo storyboard** (`docs/DEMO_STORYBOARD.md`): shot-by-shot list with exact on-screen
  numbers and the browser fallback.
- Device still unavailable (7th round); on-device verification pending.

## Increment 8 — probe-seeded enrollment (round 8)

**Can one quiet probe replace knocking in every room?** `room_vector_from_rir()` convolves six
neutral event kernels with the measured RIR to synthesize a room signature, so a probe-only
enrollment is possible (`POST /api/probe/seed`, auto-seeded on first probe enroll).

Measured (3 synthetic rooms, 36 events through the true room transfers):

| enrollment | room accuracy | uncertain rate | mean room confidence |
|---|---|---|---|
| two knocks | 0.500 | 0.722 | 0.644 |
| **one active probe** | **0.444** | **0.472** | **0.779** |

One probe is roughly as accurate as two knocks (n=36; difference = 2 events) while being much
less uncertain and more confident — and it needs no human to stand in each room finding
something to knock. Synthetic evaluation; real-room numbers pending device.

Also: activity-score calibration (threshold 0.20, simulated FPR 0%, TPR 100%), flip-readiness
checker PASS, and `docs/DEMO_VOICEOVER.md` timed script.

## Increment 9 — tuning probe-seeded synthesis + honest correction (round 9)

Tried to improve RIR-seeded room templates (3 seeds/kernel, level normalisation, transient-
weighted kernels) on 54 events through the true room transfers: all variants were worse than
the simple 6-kernel synthesis (v0 accuracy 0.370; best variant 0.333; knocks 0.500). Kept v0.

**Correction found by measurement:** substituting the probe's RT60 for the event-derived decay
in passive attribution degrades accuracy — knocks enrollment 0.500 (ignore) vs 0.444 (blend)
vs 0.389 (replace); probe-seeded 0.370 vs 0.333 vs 0.296. The default is now `ignore`; the
probe RT60 stays in its honest role (change detection, fusion weighting, probe-only
enrollment). Documentation corrected here and in README.

## Increment 10 — room-weights study, iOS RT60 UX, demo cards (round 10)

- **Learned room-distance weights**: grid search over (decay, brightness, cepstrum) weights fit
  on 54 training events; train accuracy 0.537 → 0.593 but **held-out accuracy unchanged**
  (0.611 both), so the learned weights were *not* shipped (honest no-op). Current weights hold
  **0.611 on 72 unseen events** — better than the earlier 0.500 estimate.
- **iOS**: room rows now show the measured RT60 next to live drift/activity status;
  typecheck + device build succeeded.
- **Demo media pack**: five 1920×1080 number cards rendered in `docs/media/` (accuracy,
  calibration, probe recovery, change detection, fusion) for zero-title-work video editing.
- Device still unavailable (10th round).

## Increment 11 — screenshot + verified runsheet (round 11)

- Simulator UI screenshot captured (`docs/screenshots/rooms_v2.png`) showing the **active probe**
  action and learned rooms; verified headless via `simctl io screenshot`.
- Full end-to-end dry run through the live API (`/api/demo/setup`, five `/api/detect` clips,
  `/api/fuse`, `/api/probe/status`, `/api/calibration?profile=hybrid`), all static pages 200.
  Verified outputs recorded in `docs/DEMO_RUNSHEET.md` (glass→ALERT 1.00, baby→ALERT, knock→
  EXPLAIN, speech→SILENT, alarm→EXPLAIN; hybrid profile ECE 0.0162, op 0.23).
- Device still unavailable (11th round).

## Increment 12 — spectral room-ID experiment + two-node rehearsal (round 12)

- **Probe-template log-mel room ID** (proposed frontier alternative): templates synthesized from
  the measured RIR, matched in 40-band log-mel space. Held-out accuracy **0.458** — identical to
  the shipped metric (0.458 on the same split), and even *true-RIR* templates reached only 0.458.
  Conclusion: the ceiling is the template idea, not the metric; **not shipped** (documented no-op).
- **Two-node rehearsal fix**: fusion window was 3 s, shorter than a detect+situation round trip,
  so rehearsals saw one node. Window is now **10 s**; verified two nodes fuse correctly.
- Flip rehearsal: `tools/check_submission.py` **PASS** (71 tracked files, 20 commits, no `.env`
  tracked); only advisory warning is the dirty tree until this commit.
- Device still unavailable (12th round).

## Increment 13 — probe-seeded decay fit (no-op) + release freeze (round 13)

- Tried closing the probe-only enrollment gap by setting the synthesized room vector's decay
  slot to the measured probe RT60 (and separately a RIR spectral-centroid brightness):
  0.370 baseline → **0.296** / **0.333**; both worse (kept v0). Same lesson as round 9: passive
  attribution should not be forced toward physical room truth when the observed cue is
  source-dependent.
- Release freeze prepared: `docs/RELEASE_NOTES.md` maps every acceptance criterion to evidence
  and commits; annotated tag `v0.1-hackathon` cut.

## Increment 14 — judge verification script + submission finalization (round 14)

- **`tools/verify_claims.py`**: re-runs every headline number in one command; all 8 checks pass
  (probe recovery, change detection, activity, held-out calibration, decision policy, fusion,
  real-world accuracy, repo hygiene). Output archived in `docs/VERIFY.md`, linked from README.
- Device still unavailable (14th round).

## Increment 15 — result-card screenshot + freeze (round 15)

- Added `-sampleResult` debug launch mode so the Listen/result UI can be captured headlessly;
  screenshot `docs/screenshots/listen_v2.png` shows the full card (Glass Impact 96%, **ALERT**
  calibrated 96%, conformal_pass, SNR 34 dB, Kitchen 97%, on-device hearing chips, urgency,
  explanation, suggested action, false-alarm check) — now in the README.
- Device still unavailable (15th round); verification + submission checklists frozen.

## Increment 16 — external validation on unseen real clips (round 16)

Downloaded 60 **never-before-used** ESC-50 clips (10/class) and ran the untouched pipeline:

| metric | internal set | external set (n=60 unique; corrected round 17) |
|---|---|---|
| event accuracy | 0.92 | **0.900** |
| glass / knock / alarm | 0.9–1.0 | **1.00 each** |
| baby crying | 1.0 | 0.90 |
| water | 0.8 | 0.75 (mapping ambiguity) |
| calibration ECE | 0.0166 held-out | **0.0290** (no refit) |
| alert precision | 1.00 | **0.893** (3 wrong) |

The safety-critical classes generalize perfectly and calibration transfers to unseen recordings
without refitting. Also added `docs/VIDEO_EDIT_PACKAGE.md` and a phone-in-room placeholder table
to `EVAL_REAL.md`. Device still unavailable (16th round).

## Increment 17 — external validation bug fix + corrected numbers (round 17)

An earlier external run (round 16) had a filename-collision bug: every clip in a category wrote
to one path, so the benchmark effectively repeated 6 files. Fixed and re-run on **60 unique**
never-before-used ESC-50 clips:

| metric | corrected value |
|---|---|
| event accuracy | **0.900** |
| per class | glass 1.00, knock 1.00, alarm 1.00, baby 0.90, water 0.75 |
| calibration ECE (hybrid, no refit) | 0.1593 → **0.0290** |
| decisions | 28 alert / 32 silent |
| alert precision | **0.893** (3 wrong alerts) |

The corrected numbers are slightly better on accuracy but no longer claim "zero wrong alerts" —
docs and README updated honestly. Device still unavailable (17th round).

## Increment 18 — number audit + release refresh (round 18)

- Added `tools/audit_numbers.py`: cross-checks every quoted headline figure against the cached
  measurement JSONs, rejects retracted claims (the pre-correction round-16 figures), and
  requires the verifier evidence in `docs/VERIFY.md`. It caught stale figures in the round-16
  note; those are corrected. Verifier now includes the audit as a 10th check.
- Water-class behaviour documented precisely (Apple labels `tick`/`tick_tock` for drop-like
  transients; mapping them would mislabel clocks, so we keep abstaining — not benchmark tuning).
- Release notes gained the corrected external-validation section; tag `v0.1.1-hackathon` cut.
- Device still unavailable (18th round).

## Increment 19 — fresh-clone reproducibility (round 19)

- Committed derived measurement artifacts (`docs/measurements/`) and aggregate summaries
  (`docs/eval_real_summary.json`, `docs/eval_external.json`) with fresh-clone fallbacks in
  `calibration.load_params`, `probe._activity_threshold` and the verifier — every headline
  number now reproduces from a clean clone without dev caches or CC BY-NC audio.
- **Fresh-clone dry run passed**: verifier 10/10 from `/tmp/roomsense-fresh`; server boots,
  static pages 200, demo setup returns probe RT60s, glass detect returns `alert` (Muse Spark
  `fallback` without a key — correct). Evidence in `docs/FLIP_DRY_RUN.md`.
- Added `tools/check_submission_fields.py` (reports the three expected placeholders:
  video URL, demo hostname; zero once recorded).
- Device still unavailable (19th round).

## Increment 20 — doc link checker + judge-facing README (round 20)

- Added `tools/check_links.py`: strips code fences, resolves every relative Markdown
  link/image against the repo — **11 links across 17 docs, all resolve**.
- README rewritten for a 60-second judge scan: one-liner, 30-second browser demo, one-command
  verification, headline numbers, fixed screenshot grid (active-probe + result-card), and the
  real 4-beat demo story (measure → change → hear/decide → privacy/multi-node). No unverified
  features (the old "speak a rule" beat was removed).
- Device still unavailable (20th round).

## Increment 21 — submission runbook + final candidate tag (round 21)

- Consolidated `docs/SUBMISSION_RUNBOOK.md`: T-4→T-0 timeline, copy-paste gate commands with
  expected outputs, flip sequence, post-flip logged-out checks, submission-form fields, and
  emergency fallbacks.
- Current gates: checker **PASS**, verifier **11/11 PASS**, link check **PASS**, number audit
  **PASS**, submission-fields checker reports only the 3 expected video/URL placeholders.
- Tagged **`v0.2.0-hackathon`** as the submission candidate.
- Device still unavailable (21st round).

## Increment 22 — on-device verification + real probe protocol (round 22)

Device verification finally ran on the connected iPhone 12 Pro Max:

- **Criterion 2/3 verified on hardware**: 3-sweep active probe measured Living RT60 **0.239 s**;
  same-room re-probes 0.241/0.242 s → **stable** (ΔT30 7.7% / 1.6%, conf 0.69/0.93); opening a
  door/window produced **DRIFT** (fingerprint 0.258 = 23σ above noise, conf 0.51).
- **Criterion 1 verified on hardware**: real knocks → Apple labels `hammer` 80% / `knock` 72% /
  `door` 65% → event `knock` 0.72 → decision **EXPLAIN calibrated 0.94** → live Muse Spark
  situation, SNR 14.4 dB.
- **Protocol fixes discovered and shipped**: phone speaker cannot reproduce 250/500 Hz (6–10 s
  garbage RT60) and 1 kHz is unstable across launches (std 206 ms); room identity/change now
  uses **2–8 kHz** only. Single-sweep enrollment gave 9–13% spread; **3-sweep enrollment** with
  per-band repeatability stats + 30 ms tolerance floors makes same-room probes stable.
- iOS probe UI now records 3 sweeps (~15 s) like the CLI autoprobe; device build installed.
- **Glass path on device**: `glass_clink` 46% → `glass_impact` 0.46 → **EXPLAIN calibrated 0.64**
  (correctly below the critical immediate-alert bar) → live Muse Spark.
- **Browser sensor node verified for real**: Mac `node.html` (localhost) recorded a knock and
  posted `mac-node / Kitchen / knock 1.0 / level −25.3 dB / SNR 46.3`; fusion localized Kitchen
  1.0. Learned and fixed: browsers only expose the mic on a secure context, so the page must be
  opened via `localhost` (documented + friendly error). Fusion window widened to 20 s for demo
  timing, and node rooms are now first-class localization candidates.
- Numbers written to `docs/EVAL_REAL.md` (phone-in-room table). Device connected throughout.

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
