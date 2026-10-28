# Public-flip dry run (verified 2026-10-28)

Simulates what a judge sees after the repo goes public: a **fresh clone**, no dev cache, no
`.env`, no ESC-50 audio.

## Fresh-clone verification — 10/10 PASS

```bash
git clone https://github.com/bnelabs/echolyra /tmp/echolyra-fresh
cd /tmp/echolyra-fresh/backend
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
python ../tools/verify_claims.py
```

Verified output (this machine, no network needed beyond pip):

```
[PASS] probe RT60 recovery: 0.80→0.80, 0.60→0.60, 0.35→0.36
[PASS] change detection: same 0.4% (stable) / changed 53.2% (changed)
[PASS] activity anomaly detection: 5/10 alternating probes flagged unusual
[PASS] held-out calibration (hybrid): ECE 0.1285→0.0166, precision 0.944
[PASS] decision policy: alert / explain / silent
[PASS] two-node fusion: glass_impact · Living 0.81
[PASS] real-world event accuracy: 0.920 (aggregate committed; CC BY-NC audio not redistributed)
[PASS] external validation: 0.900 (n=60), ECE 0.1593→0.029, precision 0.893
[PASS] documented numbers match measurements
[PASS] repo flip-readiness
all runnable checks passed
```

The committed `docs/measurements/` + `docs/eval_*_summary.json` make every headline number
reproducible **without** redistributing evaluation-only audio or committing dev caches.

## Fresh-clone server — boots and runs

```bash
cd /tmp/echolyra-fresh/backend
uvicorn app:app --host 127.0.0.1 --port 8081
```

Verified:

| request | result |
|---|---|
| `GET /api/health` | 200, `ok: true`, Spark model id present, `key: false` (no `.env` committed — expected) |
| static pages | `/static/demo.html`, `/static/node.html`, labels, clips → 200 |
| `POST /api/demo/setup` | 3 rooms + probe baselines `0.46 / 0.219 / 0.709 s` |
| `POST /api/detect` (glass clip) | `glass_impact`, decision **alert**, `situation._model: fallback` (no key in fresh clone; with `.env`, `muse-spark-1.3-contributor`) |

This is the intended judge experience: the browser demo works with zero setup; live Muse Spark
reports need only a Meta key in `backend/.env` (never committed).

## Flip checklist (Nov 3)

1. `python3 tools/check_submission.py` → PASS
2. `python3 tools/verify_claims.py` → all checks pass
3. `python3 tools/check_submission_fields.py` → only video/demo-URL placeholders (fill on record day)
4. `git status --short` → clean
5. Change visibility to public (GitHub UI or `gh repo edit --visibility public`)
6. Verify logged-out: repo, README, demo pages, video link
