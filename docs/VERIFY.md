# Verify the claims (one command)

```bash
cd sprint/backend
../../prototype/.venv/bin/python ../tools/verify_claims.py
```

Synthetic checks run anywhere. Real-world checks run when the ESC-50 evaluation dump exists at
`$REAL_EVAL_JSON` (default `/tmp/realsounds/real_eval_final.json`; the audio itself is
CC BY-NC and is not redistributed). Repo hygiene calls `tools/check_submission.py`.

## Last verified output

```
RoomSense claim verification
==============================
[PASS] probe RT60 recovery: 0.80→0.80, 0.60→0.60, 0.35→0.36 (all within 10%)
[PASS] change detection (stable vs changed): same ΔT30 0.4% (stable) / changed ΔT30 53.2% (changed)
[PASS] activity anomaly detection: 5/10 alternating probes flagged unusual
[PASS] held-out calibration (hybrid): ECE 0.1285→0.0166, precision 0.944 (fit 30 / val 20)
[PASS] decision policy (alert/explain/silent): high conf + room: alert; uncertain room: explain; low SNR: silent
[PASS] two-node fusion: glass_impact · Living 0.81 posteriors {'Living': 0.81, 'Kitchen': 0.19}
[PASS] real-world event accuracy: 0.920 on 50 real recordings (expected 0.92)
[PASS] external validation (unseen real clips): accuracy 0.9 on 60 unseen clips, ECE 0.1593→0.029, alert precision 0.893
[PASS] documented numbers match measurements: PASS — every quoted number matches the cached measurements
[PASS] repo flip-readiness: PASS — repo is flip-ready (warnings above are advisory)
==============================
all runnable checks passed
```

## What it covers

| claim | check |
|---|---|
| active probe recovers RT60 | simulated rooms 0.80/0.60/0.35 s, within 10% |
| change detection | same-room probe → stable (0.4% ΔT30); altered room → changed |
| activity anomalies | alternating probes flagged unusual |
| calibrated trust | held-out hybrid ECE 0.0166, precision 0.944 |
| decision policy | alert / explain / silent on high-conf, uncertain-room, low-SNR cases |
| multi-node fusion | two-node reports → `glass_impact · Living`, posteriors |
| real-world accuracy | 0.92 on 50 real recordings (ESC-50 dump) |
| repo flip-readiness | LICENSE/docs/secrets/paths audit |
