# Submission runbook — one page, copy-paste ready

Hard deadline: **Nov 4, 21:00 ET = Nov 5, 05:00 Istanbul**. Internal submit target: **Nov 3, 18:00 ET**.
Repo must be **public** at submission time. Video must be ≤3:00 and publicly viewable logged-out.

## T-4 → T-2 (Oct 31 – Nov 1): verify + record

```bash
# 1) device verification (only if the iPhone is available)
cd sprint/ios && ./install_device.sh
# follow docs/DEVICE_VERIFICATION.md, then fill the table in docs/EVAL_REAL.md

# 2) all gates
cd sprint
python3 tools/check_submission.py          # expect: PASS — repo is flip-ready
python3 tools/check_submission_fields.py   # expect: only video/demo-URL placeholders
cd backend && ../../prototype/.venv/bin/python ../tools/verify_claims.py
# expect: 11 × [PASS], "all runnable checks passed"
```

```bash
# 3) record the video
# script: docs/DEMO_VOICEOVER.md · storyboard: docs/DEMO_STORYBOARD.md
# assets: docs/media/card_*.png · screenshots: docs/screenshots/*_v2.png
# fallback: /static/demo.html needs no hardware
```

## T-1 (Nov 3): submit + flip public

```bash
# final gates (must all be green)
cd sprint
python3 tools/check_submission.py && python3 tools/check_submission_fields.py
cd backend && ../../prototype/.venv/bin/python ../tools/verify_claims.py
cd .. && git status --short        # expect: empty (clean tree)
```

```bash
# fill the placeholders in docs/SUBMISSION.md, then flip public
# (GitHub UI: Settings → General → Danger Zone → Change visibility → Public)
# or:
# gh repo edit bnelabs/roomsense --visibility public --accept-visibility-change-consequences
python3 tools/check_submission_fields.py   # expect: PASS once video/demo URLs are set
git add -A && git commit -m "submission: fill video and demo URLs" && git push
git tag -a v0.2.0-hackathon -m "Submission candidate" && git push origin v0.2.0-hackathon
```

```bash
# post-flip, logged out
curl -sI https://github.com/bnelabs/roomsense | head -1          # 200
# open README logged-out; click screenshots, docs links, demo link
# open the video URL in a private window; play through
```

## T-0 (Nov 4): submit

- [ ] Submission form: copy fields from `docs/SUBMISSION.md` § "Submission form — paste-ready fields"
- [ ] Repo URL public · video URL public · demo URL working
- [ ] Track = Indie Developer · Problem statement = Push the Frontier
- [ ] Screenshot the confirmation page/email
- [ ] Rotate the Meta API key after the event; confirm `backend/.env` never entered git (`git ls-files | grep -c '\.env$'` → 0)

## Expected outputs (current, verified)

| command | expected |
|---|---|
| `check_submission.py` | `PASS — repo is flip-ready` (warnings advisory) |
| `verify_claims.py` | 11 × `[PASS]`, `all runnable checks passed` |
| `check_links.py` | `11 relative links … all resolve` |
| `audit_numbers.py` | `every quoted number matches the cached measurements` |
| `check_submission_fields.py` | 3 placeholders until video/URLs filled, then PASS |
| fresh clone | verifier 11/11; server boots; demo works without key |

## Emergency fallbacks

- **Device dead / no time:** record the browser demo (`/static/demo.html`) for shots 2–6; story and numbers are identical.
- **No API key on demo machine:** `/api/detect` still returns event/room/decision; `situation._model` shows `fallback` — say so honestly.
- **Repo already public early:** nothing breaks; only re-run gates before submitting.
- **Video too long:** cut shot 6 (two-node) first; keep shots 2–5 (probe, change, alert, Spark).
- **Forgot to fix a number on screen:** stop; every number must match `docs/VERIFY.md` (re-run verifier).
