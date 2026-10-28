# Video edit package — assets, timings, overlays

Everything below is committed and verified. Export: 1920×1080 / 30 fps, H.264, ≤3:00.

## Asset inventory

| asset | path | use |
|---|---|---|
| Rooms tab (active probe UI) | `docs/screenshots/rooms_v2.png` | shot 2 |
| Result card (ALERT, Spark situation) | `docs/screenshots/listen_v2.png` | shots 4–5 |
| Number cards | `docs/media/card_accuracy.png`, `card_calibration.png`, `card_probe.png`, `card_change.png`, `card_fusion.png` | shot 7 |
| Browser demo | `http://<mac-ip>:8080/static/demo.html` | fallback + shot 6 |
| Sensor node | `http://<mac-ip>:8080/static/node.html` | shot 6 |
| Voiceover | `docs/DEMO_VOICEOVER.md` | audio track |
| Storyboard | `docs/DEMO_STORYBOARD.md` | sequence |

## Edit timeline

| time | clip | on-screen text |
|---|---|---|
| 0:00–0:15 | room tone + phone on shelf | **No cameras. It hears.** |
| 0:15–0:40 | screen: rooms_v2.png + probe success toasts | **It measures the room** · RT60 0.46 / 0.22 / 0.71 s |
| 0:40–1:00 | re-probe status: drifting → changed | **The room changed: ΔT30 11.8% → 22.3%** |
| 1:00–1:25 | listen_v2.png full card zoom | **ALERT · calibrated 96%** |
| 1:25–1:55 | second knock: EXPLAIN → ALERT; Spark text | **Muse Spark 1.3 Contributor — situation, not just a label** |
| 1:55–2:20 | node.html Fuse result | **Two sensors → Kitchen 0.75 / Living 0.22** |
| 2:20–2:45 | cards crossfade | **92% (vs 16%) · ECE 0.1285→0.0166 · 0.80→0.80 s · 0.4% vs 39–60%** |
| 2:45–3:00 | repo + demo URL | **Built with Meta models · it knows when it doesn't know** |

## Audio notes

- Voiceover recorded separately, normalized to −16 LUFS; lower bed music to −28 dB under voice.
- Keep the phone's recorded probe sweep audible at 0:15 (it is quiet by design — say so: "you can
  barely hear it").
- Silence the Muse Spark card for 1 s so the text is readable.

## Final checks before export

- [ ] Every number matches `docs/VERIFY.md` (re-run the verifier if any code changed)
- [ ] No `.env`/API key visible in any screen recording
- [ ] Repo URL and demo URL legible for ≥3 s
- [ ] Video ≤3:00 and playable logged-out
