# Demo video — shot-by-shot storyboard

Target: **3:00**, screen-first, one phone, no cuts longer than 4 s. Record at 1080p (simulator
for exact numbers is acceptable; real device preferred). Fallback at any point: open
`/static/demo.html` in a browser and run the same pipeline live.

## Assets needed

- iPhone with RoomSense installed, 3 rooms enrolled (living, kitchen, bedroom)
- Laptop with `http://<mac-ip>:8080/static/node.html` open (second sensor)
- 2 takes of a glass clink, 1 knock, 1 closing door
- The screenshots in `docs/screenshots/` as caption material if a live shot fails

## Shots

| # | Time | Visual (what is on screen) | On-screen text / caption |
|---|---|---|---|
| 1 | 0:00–0:15 | Quiet living room, phone on a shelf. Slow push-in. | **No cameras. It hears.** |
| 2 | 0:15–0:40 | Rooms tab → tap **"Measure acoustics (active probe)"**. Phone is silent to the ear; screen shows "Measuring the room…" then **"Room measured: RT60 0.46 s — acoustic fingerprint stored."** Repeat for kitchen (**0.22 s**) and bedroom (**0.71 s**). | **It doesn't just listen — it measures the room.** |
| 3 | 0:40–1:00 | Open a door / move a rug, then **Re-probe**. Room row shows **"Room drifting — ΔT30 max 11.8% (conf 71%)"**; then a bigger change: **"Room changed — ΔT30 max 22.3% (conf 72%)"**. | **Days later, it tells you the room itself changed.** |
| 4 | 1:00–1:25 | Tap Listen, play glass clink: result card → **glass_impact**, room **Kitchen**, chip **ALERT · calibrated 96%**, SNR 34 dB. | **On-device 303-class understanding + calibrated decision.** |
| 5 | 1:25–1:55 | Knock once: **EXPLAIN · needs_confirmation**; knock a second time within 10 s: **ALERT**. Muse Spark card appears: "Possible glass impact in Kitchen…" | **Ambiguous events wait for confirmation; Muse Spark explains the situation.** |
| 6 | 1:55–2:20 | Privacy card + laptop `node.html` listening; press **Fuse**: **glass_impact — Kitchen**, posteriors **Kitchen 0.75 / Living 0.22 / Bedroom 0.03**. | **No cloud audio. Every spare device can be a sensor.** |
| 7 | 2:20–2:45 | Number cards, large type: **92%** real-world events (vs **16%** rules), **0.1285 → 0.0166** held-out calibration error, **0.80→0.80 s** RT60 recovery, **0.4% vs 39–60%** change detection. | **Measured on real audio, not simulation.** |
| 8 | 2:45–3:00 | Repo URL + browser demo URL; small Meta model ids: muse-spark-1.3-contributor, sam-3.1, muse-voice-transcribe-1.0. | **Built during the hackathon. It knows when it doesn't know.** |

## Exact numbers to use (verified in this repo)

| Claim | Value | Source |
|---|---|---|
| Real-world event accuracy | 92% (n=50) | `docs/EVAL_REAL.md` |
| Hand-written rules accuracy | 16% (n=50) | `docs/EVAL_REAL.md` |
| Held-out calibration ECE | 0.1285 → 0.0166 | `docs/CALIBRATION.md` §3.6 |
| Accepted-detection precision | 0.944 held-out; 1.00 for immediate critical alerts | `docs/CALIBRATION.md`, `docs/EVAL_REAL.md` |
| RT60 recovery | 0.80→0.80, 0.60→0.60, 0.35→0.36 s | `docs/FRONTIER.md` |
| Change detection | 0.4% ΔT30 stable vs 39–60% changed | `docs/FRONTIER.md` |
| Probe drift classes | stable 0.96 conf, drift 0.71, changed 0.94–0.99 | `docs/FRONTIER.md` |
| Activity score | threshold 0.20, simulated FPR 0%, TPR 100% | `cache/activity_calibration.json` |

## Recording notes

- If the phone is unavailable, record shots 2–5 from the browser demo with the same numbers;
  keep the device footage for shots 1 and 6 if possible.
- Say the honest limitation out loud once: "single phone room attribution is hard — that's why
  we added active probes and multi-node fusion." Judges reward that.
- Keep the Muse Spark response visible on screen for at least 3 s (it is the Meta-model proof).
