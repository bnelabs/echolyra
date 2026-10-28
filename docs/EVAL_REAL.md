# Real-world evaluation — how good is the understanding, really?

All numbers below are measured on **real recordings**, not simulation. This is the honest
answer to "does it actually recognize sounds, or is it a toy?"

## Dataset

- **50 real-world clips** from **ESC-50** (Piczak, 2015): 10 clips each for
  `glass_breaking`, `door_wood_knock`, `crying_baby`, `clock_alarm`, `water` (pouring/drops).
- ESC-50 is **CC BY-NC 3.0**: used for evaluation only, not redistributed with the app.
- Recordings come from unknown rooms/microphones — so they evaluate **event recognition**
  (what happened), not room attribution (where). Room evaluation needs our own phone data.

## Heads-up: the rule classifier is the toy

| recognizer | real-world accuracy (n=50) |
|---|---|
| hand-written rules + template matching (earlier prototype) | **0.16** |
| **Apple SoundAnalysis 303-class model, on-device** | **0.92** |

That is a **5.8× improvement** on the same real audio and the single most important fix in
this project: the on-device pretrained model is now authoritative, rules are only a fallback
when Apple's model returns nothing mappable.

Per class (on-device model): knock **1.00**, baby crying **1.00**, glass breaking **0.90**,
alarm **0.90**, water **0.80**.

## Decision policy on real data (calibrated + temporal)

Calibration parameters are fitted on the synthetic labelled set; the decision layer has a
two-tier temporal policy:

- **Immediate alerts**: only safety-critical, high-confidence detections —
  `glass_impact`, `alarm_beep`, `baby_cry` with calibrated confidence ≥ 0.9.
- **Confirmation required**: ambiguous classes (`knock`, `impact_thud`, `water`, …) are shown
  as *explain* on the first detection and escalate to *alert* when a second agreeing detection
  arrives within 10 s.
- **Silent**: SNRs below 12 dB or calibrated confidence below the operating point.

| behaviour | count (n=50) | precision |
|---|---|---|
| immediate alerts (critical, cal ≥ 0.9) | 10 | **1.00** |
| deferred to confirmation (ambiguous) | 17 | 0.88 if confirmed |
| silent (mostly low-SNR recordings) | 23 | — |

Raw (pre-temporal) alerts: 27 at **0.926 precision**. So: no false critical alerts, and the
system is conservative about the ambiguous classes.

## Held-out calibration (round 5)

Splitting the real recordings 30 fit / 20 validation and fitting only on the 30:

| profile | ECE before → after (held-out) | accepted precision |
|---|---|---|
| synthetic | 0.1285 → 0.0423 | 0.944 |
| real-fit | 0.1285 → 0.0251 | 0.944 |
| **hybrid** | 0.1285 → **0.0166** | 0.944 |

Held-out decisions: 9 alerts at **0.889 precision** (one wrong), 11 silent. So the calibrated
trust layer generalizes to recordings it never saw.

## External validation — 60 clips never seen during development (round 16)

Downloaded 10 additional ESC-50 clips per class that were **not** used for any earlier tuning or
calibration fit, and ran the full pipeline unchanged (60 unique recordings; an earlier run of this
check had a filename-collision bug that repeated 6 files — corrected in round 17):

| metric | value |
|---|---|
| event accuracy (n=60 unique) | **0.900** |
| per class | glass **1.00**, knock **1.00**, alarm **1.00**, baby crying **0.90**, water **0.75** |
| calibration ECE (hybrid profile, no refit) | 0.1593 → **0.0290** |
| decisions | 28 alert / 32 silent |
| alert precision | **0.893** (3 wrong alerts among 28) |

The water class is the weak spot, and the reason is concrete: ESC-50 `water_drops` clips are
often labelled by Apple as **`tick` / `tick_tock` / `clock`** (drop-like transients), and
`tick_tock` is also a legitimate clock sound. Mapping those to `water` would mislabel clocks, so
we keep them as **abstentions** instead — water stays our weakest class by design, not by tuning
to the benchmark. `pouring_water` clips mostly map correctly via `liquid_*` / `water`. Glass, knock and alarm were perfect on unseen data; baby crying was 0.90. Calibration
transferred (0.0290 ECE) without refitting, and no silent failure was observed.
Aggregate numbers: `docs/eval_external.json`.

## Phone-in-room verification (measured on iPhone 12 Pro Max, iOS 27.0.1)

Protocol after real-device tuning: **3 probe sweeps** per enrollment, analysis restricted to the
**2–8 kHz** bands the phone speaker/mic can actually reproduce, tolerance floors from measured
re-проbе noise (30 ms per band). All numbers below are from the device, not simulation.

| room | measured RT60 (2–8 kHz) | re-probe ΔT30 / status | event | decision | calibrated | SNR |
|---|---|---|---|---|---|---|
| Living | **0.239 s** (2k 0.233 / 4k 0.245 / 8k 0.244) | same config: 7.7% stable (0.69), 1.6% stable (0.93) | 6–8 knocks | `knock` 0.72 → **EXPLAIN** | **0.94** | 14.4 dB |
| Living, door/window open | 0.238 s | **ΔT30 5.6%, fingerprint distance 0.258 (23σ) → DRIFT** (0.51), transient flagged | — | — | — | — |

Apple on-device labels for the knock clip: **`hammer` 80%, `knock` 72%, `door` 65%** (mapped to
`knock`); Muse Spark returned a live situation ("Possible knock heard"). The EXPLAIN (not ALERT)
is the temporal policy: one knock needs confirmation; a second agreeing detection escalates.

### Real-device protocol findings (shipped fixes)

- 250 Hz and 500 Hz deconvolution is unusable on a phone speaker (RT60 estimates 6–10 s);
  1 kHz is unstable across launches (per-band std 206 ms). **2–8 kHz is the usable range**
  (band CV 4–7%).
- Single-sweep enrollment gave 9–13% RT60 spread between identical probes. **3-sweep
  enrollment** + per-band repeatability keeps same-room re-probes at ΔT30 1.6–7.7% (stable).
- Change detection uses the measured noise: a door/window change produced a 23σ fingerprint
  shift even though mid-band RT60 moved only 5.6% — detection is not just RT60.

### Still pending (honest)

- Multiple rooms + glass event on device (only Living + knocks recorded so far).
- Real two-phone/browser-node fusion on-device (fusion verified with stored reports + browser
  node dry runs).

## Limitations (be honest in the demo)

- This evaluates **event understanding only**; room attribution is not measurable on clips
  whose rooms we don't know. The active-probe room numbers remain synthetic until real-phone
  measurement (see `SIGNAL_SCIENCE.md`).
- ESC-50 clips are often noisy/low-SNR (22 of 50 below 12 dB in our features); 10 crying-baby
  clips were correctly recognized but suppressed by the SNR gate. A phone close to a nursery
  should be much higher SNR — that is what the real-device test will establish.
- Apple categories are generic (e.g. `baby_laughter`, `smoke_detector`); mapping gaps are
  visible as misses, which is why the mapping table in `backend/awareness.py` is versioned.
