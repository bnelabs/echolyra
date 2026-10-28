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

## 3.6 Real-data calibration profiles (held-out validation, round 5)

Real-world rows: 50 ESC-50 clips, split per class into **fit 30 / validation 20**. Profiles are
fitted only on fit data; scored only on held-out recordings:

| profile (fit data) | fit rows | ECE before | **ECE after (held-out)** | accepted/20 | precision |
|---|---|---|---|---|---|
| synthetic only | 180 | 0.1285 | **0.0423** | 18 | 0.944 |
| real-fit only | 30 | 0.1285 | **0.0251** | 18 | 0.944 |
| **hybrid (synthetic + real-fit)** | 210 | 0.1285 | **0.0166** | 18 | 0.944 |

Decision behaviour on the held-out rows: 9 alerts (**precision 0.889**, one wrong alert),
11 silent, 0 explain (single-shot, no temporal confirmation). The hybrid profile is the best
calibrated and is what a real deployment should use; the synthetic profile stays the default
for the synthetic-room demo. Profiles live in `cache/calibration{synthetic,real,hybrid}.json`
and are selectable with `CALIBRATION_PROFILE` or `GET /api/calibration?profile=hybrid`.
Reproduce with `backend/tools_validate_calibration.py`.

## 4. Limitations / next

- The calibration set is **synthetic**. Rebuild it on real device data as soon as the iPhone
  is available: collect ~100 labelled detections, then `POST /api/calibrate` (or add a
  `real` flag and extend `collect_labelled`). Parameters are only as good as that set.
- Alert thresholds are currently conservative (room confidence gate dominates). Once active
  probes are available on-device, room confidence will be source-independent and the alert
  rate should rise without losing precision.
- Future: class-conditional conformal sets, temporal decision smoothing (two detections
  within N seconds), and cost-sensitive thresholds (missed glass break ≠ missed knock).
