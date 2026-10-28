# On-device verification — 10 steps (run when the iPhone reconnects)

Everything software-side is done; this is the only remaining acceptance path. Target: ~15 min.

## Steps

1. **Connect & confirm**
   `xcrun devicectl list devices` → iPhone shows `available` (unlock the phone, tap *Trust* if asked).
2. **Backend reachable on LAN**
   `cd sprint/backend && ./run_backend.sh` (prints `http://192.168.68.50:8080`); from phone Safari
   open `http://192.168.68.50:8080/api/health` → `{"ok":true,...}`.
3. **Install**
   `cd sprint/ios && ./install_device.sh` (auto-detects UDID + team, signs, installs, launches with
   the backend URL injected).
4. **Trust developer (one tap)**
   Tap RoomSense icon → *Untrusted Developer* → Settings → General → VPN & Device Management →
   **Baris Naci Erzeren** → Trust. Relaunch.
5. **Allow microphone (one tap)** when the app asks.
6. **Enroll rooms** — Rooms tab: enter `Living` → *Knock once and record*; repeat `Kitchen`,
   `Bedroom`. Expect "Learned rooms: 3".
7. **Active probe** — *Measure acoustics (active probe)* for each room. Expect
   `Room measured: RT60 0.4–0.8 s — acoustic fingerprint stored`; room row shows `RT60 x.xx s`.
8. **Change detection** — open a door, tap *Re-probe* on that room. Expect
   `Room drifting/changed — ΔT30 max …% (conf …%)`.
9. **Live event** — Listen tab: play a glass clink → `glass_impact`, room, `ALERT · calibrated`;
   knock once → `EXPLAIN · needs_confirmation`, knock again → `ALERT`.
10. **Two-node** — laptop `http://192.168.68.50:8080/static/node.html` → Listen; phone Listen;
    laptop Fuse within 10 s → event + room with posteriors.

## Record the numbers

After steps 7–9, copy the on-screen values into `docs/EVAL_REAL.md` → "Phone-in-room
verification" table: room, measured RT60, re-probe ΔT30/status, event label, decision,
calibrated confidence, SNR. Then commit.

## Troubleshooting

- App launches but requests fail → the injected backend URL is stale: relaunch via
  `install_device.sh` or set `ROOMSENSE_BACKEND` in Settings.
- "Microphone access is off" → Settings → RoomSense → Microphone → on; relaunch.
- Trust prompt not visible → uninstall/reinstall resets trust; repeat step 4.
- Re-probe says "no probe baseline" → run step 7 for that room first.
