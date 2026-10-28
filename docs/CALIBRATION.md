# Calibrated uncertainty and decision policy

**The problem:** a confidence like "0.9" from a rule/template classifier is not a probability.
The app must not alert on weak evidence, and "unknown" is not good enough — it must know
*when* it doesn't know. This is the trust layer that makes the difference between a toy and a
system you'd leave running at home.

Implemented in `backend/calibration.py`; parameters rebuild via `POST /api/calibrate` and are
stored in `cache/calibration.json`. Every detection response now carries a `decision` object.

## 1. Reliability calibration (histogram binning)

Maps raw top confidence → empirically observed accuracy, with Laplace shrinkage and a
monotonicity constraint. Evaluated on a labelled set (180 detections: 6 event classes ×
3 synthetic rooms × 5 SNR conditions × 2 trials).

| metric | before | after |
|---|---|---|
| Expected Calibration Error (ECE) | **0.0394** | **0.0162** |

So after calibration a "70% confidence" is much closer to a 70% hit rate.

## 2. Operating point (precision target)

Chosen only over detections where the classifier actually made a claim (abstentions are the
decision layer's job):

| parameter | value |
|---|---|
| accepted rows | 71 / 180 (the rest are abstentions) |
| confidence threshold | **0.25** |
| precision at threshold | **0.958** |
| conformal threshold (α = 0.10) | **0.28** (precision 1.0 on 66 predictions) |

## 3. Decision policy

`decision ∈ {alert, explain, silent}` from calibrated confidence + room confidence + SNR:

- **silent** — SNR < 12 dB, calibrated confidence < 0.45, or no room confidence
- **explain** — evidence is usable but not strong enough for an alert (needs context)
- **alert** — calibrated confidence ≥ operating threshold **and** room confidence ≥ 0.55

Measured decision behaviour on the labelled set (zero wrong alerts in every condition):

| condition | alerts | explain | silent | wrong alerts | alert precision |
|---|---|---|---|---|---|
| quiet (~60 dB) | 8 | 16 | 12 | **0** | **1.00** |
| 40 dB | 8 | 16 | 12 | **0** | **1.00** |
| 20 dB | 0 | 18 | 18 | 0 | — (room uncertain) |
| 10 dB | 0 | 0 | 36 | 0 | — |
| 5 dB | 0 | 0 | 36 | 0 | — |

This is the desired safety profile: it alerts only when both the event *and* the room are
trustworthy, explains when only the event is, and goes silent under noise.

## 3.5 Temporal confirmation (two-tier)

A single alert is easy to fake with an ambiguous transient, but a safety-critical event must not
be delayed. Policy in `backend/app.py`:

- critical + high confidence (`glass_impact`, `alarm_beep`, `baby_cry`, cal ≥ 0.9) → **alert immediately**
- everything else → **explain** on the first detection, **alert** after a second agreeing
  detection within 10 s (`needs_confirmation`)
- low SNR / low confidence → **silent**

Real-world check (ESC-50, see `EVAL_REAL.md`): immediate critical alerts precision **1.00**;
deferred ambiguous detections precision **0.88** if confirmed.

## 3.6 Real-data calibration profiles (round 4)

We fitted calibration profiles from real-world recordings (50 ESC-50 clips; see
`EVAL_REAL.md`) and from the pooled synthetic+real set. Scored **on the real clips**:

| profile (fit data) | rows | ECE before → after (real) | operating point | accepted precision |
|---|---|---|---|---|
| synthetic only (default) | 180 synthetic | 0.205 → 0.099 | 0.25 | 0.958 |
| real only | 50 real | 0.205 → 0.053 | 0.23 | 0.958 |
| **hybrid (synthetic + real)** | 230 | **0.205 → 0.049** | 0.23 | 0.958 |

The hybrid profile is the best calibrated on real audio. Caveat: the real rows are also used
in the hybrid fit (small n=50), so this is not a fully held-out estimate — the next real phone
corpus will be split into fit/validation. Profiles are stored as
`cache/calibration{synthetic,real,hybrid}.json`; select one with the `CALIBRATION_PROFILE`
env var or read it via `GET /api/calibration?profile=hybrid`. Default remains `synthetic`
until a larger real corpus exists.

## 4. Limitations / next

- The calibration set is **synthetic**. Rebuild it on real device data as soon as the iPhone
  is available: collect ~100 labelled detections, then `POST /api/calibrate` (or add a
  `real` flag and extend `collect_labelled`). Parameters are only as good as that set.
- Alert thresholds are currently conservative (room confidence gate dominates). Once active
  probes are available on-device, room confidence will be source-independent and the alert
  rate should rise without losing precision.
- Future: class-conditional conformal sets, temporal decision smoothing (two detections
  within N seconds), and cost-sensitive thresholds (missed glass break ≠ missed knock).
