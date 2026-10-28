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

## Limitations (be honest in the demo)

- This evaluates **event understanding only**; room attribution is not measurable on clips
  whose rooms we don't know. The active-probe room numbers remain synthetic until real-phone
  measurement (see `SIGNAL_SCIENCE.md`).
- ESC-50 clips are often noisy/low-SNR (22 of 50 below 12 dB in our features); 10 crying-baby
  clips were correctly recognized but suppressed by the SNR gate. A phone close to a nursery
  should be much higher SNR — that is what the real-device test will establish.
- Apple categories are generic (e.g. `baby_laughter`, `smoke_detector`); mapping gaps are
  visible as misses, which is why the mapping table in `backend/awareness.py` is versioned.
