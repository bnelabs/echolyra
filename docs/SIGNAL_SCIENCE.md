# Signal science — what RoomSense actually measures (and what it refuses to guess)

**Status:** implemented in `backend/awareness.py`; evaluated on synthetic rooms (see caveats).
This page answers: *does it analyse SNR / noise / reverberation — and where is the frontier?*

## 1. What the pipeline measures today

| Stage | What it computes | Why it matters |
|---|---|---|
| **Noise floor** | per-octave-band energy of the **pre-onset silence** (median of frames before the event) | the room's noise floor is the reference for every decision; no pre-roll → fallback to quietest 15% of frames |
| **Event SNR** | per-band SNR = `event_peak_band − noise_band` (clipped −10…60 dB), plus broadband **peak-to-noise** SNR | detects "is there actually a signal here?" |
| **SNR gate** | event label forced to `unknown` below **4 dB**; room attribution withheld below **25 dB** | refuses to hallucinate labels on noise |
| **Noise-normalised features** | event classification uses band **SNR** instead of raw band energy, plus crest factor, spectral centroid/flatness, tonality, 1.5–9 Hz modulation, active duration | makes event ID robust to gain and noise level |
| **Room fingerprint** | **early decay rate** fitted over **−5 → −25 dB** of the 300–6000 Hz envelope, spectral brightness, and **MFCC cosine** (13 cepstral coefficients) | late tail is where noise lives; early decay is a classical room-identity cue |
| **Room decision** | physical distance = 2·\|Δlog decay\| + 0.5·\|Δbrightness\|/6 + (1 − cos MFCC); softmax posterior; margin + SNR + sustained-sound guards | calibrated "which room" with an explicit *uncertain* state |
| **Certainty** | `event_conf × room_conf`, plus reasons (`low_snr`, `needs_room_sample`) | drives whether the app alerts or stays silent |

Known gaps: no dereverberation/noise suppression before feature extraction, no learned embeddings, no multi-microphone array processing, no calibration of the iPhone mic per device yet, and room attribution is event-type dependent.

## 2. Evaluation (synthetic transfer functions, 3 rooms × 4 event classes × 3 trials)

Rooms differ in early decay / wall low-pass / level. Added white noise targets a **peak-relative SNR**.
Raw data: [`eval_snr.json`](eval_snr.json).

| SNR condition | Event accuracy | Event "unknown" (gated) | Room accuracy (knocks) | Room "uncertain" (gated) |
|---|---|---|---|---|
| quiet (~60 dB) | **1.00** | 0% | **1.00** | 0% |
| 40 dB | **1.00** | 0% | **1.00** | 0% |
| 20 dB | 0.75 | 25% | 0.00 | **100%** (refuses) |
| 10 dB | 0.17 | 67% | 0.00 | **100%** (refuses) |
| 5 dB | 0.08 | 88% | 0.00 | 100% |
| 0 dB | 0.00 | 100% | 0.00 | 100% |

**Interpretation (honest):**
- **What happened** is robust down to ~20 dB SNR; below that the system gated most events (conservative, not wrong).
- **Which room** is robust down to ~40 dB SNR *with the early-decay + cepstral metric*; below that the noise buries the room tail and the system says *uncertain* rather than guessing.
- This asymmetry is physics: room identity lives in reverberation (the late, low-energy part); event identity lives in the excitation itself (higher energy).
- These are **simulated** transfer functions, not real rooms. Real-device validation is the next measurement (the app now runs on the iPhone).

## 2.5 Sound understanding stack (updated 2026-10-28)

**What hears the sound (on-device):** Apple `SoundAnalysis` / `SNClassifySoundRequest` —
a pretrained **303-class** sound classifier that ships with iOS/macOS. Verified vocabulary
includes `knock`, `glass_breaking`, `glass_clink`, `baby_crying`, `crying_sobbing`,
`door_slam`, `door_bell`, `alarm_clock`, `telephone_bell_ringing`, `water_tap_faucet`,
`thump_thud`, `speech`, `screaming`, `cough`. It runs fully on the phone; the top labels are
sent with the clip and mapped to RoomSense event families in `backend/awareness.py`
(`APPLE_LABEL_MAP`, `event_from_heard`).

**What reasons about it (Meta Model API):** `muse-spark-1.3-contributor` produces the
situation report (urgency, explanation, what to check). This is the default and is verified
live in every detection response (`_model: muse-spark-1.3-contributor`).

**Meta audio limitation (tested exhaustively, 2026-10-28):** Muse Spark 1.2 audio input
works only as a **speech transcriber** — transcribing TTS audio returned the exact sentence,
but every non-transcription prompt (identify/describe/classify) came back with
*"no audio provided"*, for both Spark 1.3/1.3-contributor and 1.2, across inline
`input_audio`, `audio_url`, `input_file` and Files-API `file_id` delivery. Conclusion: use
Apple's on-device classifier for acoustic event understanding, Meta Spark for reasoning —
this is also the better privacy story (audio never leaves the phone for classification).

**Capture bug found and fixed:** the app initially recorded digital silence (peak −39 dBFS,
RMS −66 dBFS, all zeros) because the microphone permission prompt had never been accepted
and `AVAudioRecorder` happily recorded silence. The recorder now **explicitly requests
microphone permission**, refuses to record without it, and the app shows a clear error
pointing to Settings. Sampling is WAV 16 kHz mono (Apple's analyzer silently returns nothing
for CAF files — a second capture bug that was masking the first).

## 3. Frontier science — ranked by impact for this product

1. **Active acoustic probing (highest impact).** Periodically emit a quiet/inaudible chirp and measure the true RIR with our existing sweep/deconvolution stack, instead of inferring the room from events. Gives ISO-3382 EDT/T30/DRR per room, **source-independent** fingerprints, and change detection (door/furniture/presence). This is the original acoustic-twin tech used as a sensor — a genuine differentiator.
2. **Learned audio embeddings / open vocabulary.** PANNs, BEATs, HTS-AT or CLAP as frozen embeddings; prototypical few-shot heads; **CLAP text prompts** for zero-shot classes ("glass breaking", "door knock", "infant cry") and OOD scores for "something new happened". Distill to Core ML for on-device inference.
3. **Joint source–room factorisation.** In the cepstral domain a recording ≈ source signature + room transfer offset. Estimate both jointly (EM / additive factor model) instead of classifying event and room independently — this decouples *what* from *where* and removes the event-type bias in room matching.
4. **Geometry-aware transfer models.** Use Apple RoomPlan geometry + image-source/ray-tracing simulation to predict the acoustic transfer between rooms, then solve room attribution as **Bayesian model comparison**; with wall-material priors it can work before any enrollment.
5. **Distributed sensing mesh.** Two or more old phones as nodes: TDOA + level-ratio fusion, particle filter over rooms; true "which room" and distance. (Product story: your drawer of old phones becomes the sensor network.)
6. **Uncertainty that is calibrated, not guessed.** Temperature scaling on labelled validation data; **conformal prediction** for alert thresholds; decision-theoretic alerting (cost of false alarm vs missed event).
7. **Robust front-end.** Noise PSD estimation + spectral subtraction / Wiener filtering before features; per-iPhone mic calibration (device EQ); AGC detection; dereverberation for classification (while keeping reverb for room ID).
8. **Sim2real data strategy.** Our RIR simulator generates arbitrary room/event/device/noise combinations for training and stress tests; add FSD50K/AudioSet pretraining (license-checked); domain-randomise device responses.
9. **Active sensing beyond audio.** Ultrasonic/FMCW presence and motion detection between events; IMU/UWB (iPhone 12 Pro has U1) for node placement; fuse with event detections.

## 3.5 Honest use cases (what this is for, and what it is not)

**Now (hackathon demo):** camera-free awareness for a single room: "something knocked in the
kitchen", "glass broke in the bedroom", "the baby is crying" + a spoken-word-style situation
report. The value is **privacy + immediate context**, not perfect taxonomy.

**Real product use cases, in order of strength:**
1. **Baby / child monitor without a camera** — parents will pay to avoid a camera in a
   nursery; event class + room + urgency is the job; "unclear sound" is acceptable there if
   the app says *where* and *how loud* — but only with reliable capture and alerts.
2. **Aging-in-place / caregiver awareness** — thuds, calls for help, glass breaking, door
   slams; alert escalation to family; no cameras in bedrooms/bathrooms.
3. **Apartment security without cameras** — glass break, door, footsteps; privacy-sensitive
   renters; multi-phone mesh later.
4. **"Which room was that?"** — for multi-node households (old phones as sensors); room
   fingerprinting is the differentiator and the hard part (see §2 fragility).
5. **Noise/privacy awareness** — "is my call being overheard", "which room is quietest".

**What makes it not a toy (and what is still toy-like):** the hearing model is now a real
pretrained AudioSet-scale classifier, not hand-written rules; the room fingerprint + Meta
reasoning are real. Still toy-like today: single-device audio only, no active room probing,
no learned embeddings, no multi-node localization, and the demo room is small. Those are
exactly the roadmap items in §3.

## 4. Next 48 hours (hackathon-relevant)

1. **Real-device 3-room measurement** with the app now installed: knock in living room / kitchen / bedroom, 3 repeats each; compute real room-ID accuracy (this replaces the synthetic number in the demo).
2. Surface **SNR + certainty + "uncertain" reasons** in the result card (in progress) — never show a confident label on a weak signal.
3. Optional: **active probe** at enrollment (0.5 s chirp) → RIR-based room fingerprints; the backend already has the deconvolution code from the earlier calibration build.
4. Demo narrative: show a clean detection at good SNR, then show the app **declining to guess** in a noisy/"can't hear it" condition — that is a trust feature, not a weakness.
