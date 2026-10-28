# Demo video — timed voiceover + recording checklist

Read at a natural pace; the numbers are the pitch. Target 3:00.

## Voiceover

**[0:00]** "Every room has a sound. Not the sounds in it — the room itself: how it answers a
clap, how it colours a voice, how long a glass clink rings. Cameras can see your home. We
wanted something that hears it and then forgets."

**[0:15]** "This is RoomSense. The phone plays a sweep you can barely hear and records the
room's answer — its true impulse response. In three seconds it measures the reverberation
time: 0.46 seconds in the living room, 0.22 in the kitchen, 0.71 in the bedroom. That's a
fingerprint no knock can fake, because the room, not the sound, defines it."

**[0:40]** "Weeks later, you open a door or move a rug. Re-probe, and it tells you the room
drifted eleven percent, or changed twenty-two percent — with a confidence. Not 'something
sounds different': a measurement."

**[1:00]** "Now a real event. Glass breaks in the kitchen. Apple's on-device classifier — three
hundred and three sound classes, running entirely on the phone — hears it in about a second.
It says glass impact, kitchen; the decision layer says ALERT, calibrated ninety-six percent."

**[1:25]** "A knock is ambiguous. First detection: EXPLAIN — needs confirmation. Second knock:
ALERT. Muse Spark one point three Contributor turns that into a situation: what happened,
how urgent, what to check. That's the Meta model doing the reasoning, not a fixed rule."

**[1:55]** "No camera. No audio ever uploaded — classification and probing stay on the phone,
only features leave. And every spare phone or laptop can join as a second sensor: fusion says
Kitchen, seventy-five percent, from the levels and the room fingerprints."

**[2:20]** "We measured it on real recordings, not just simulation: ninety-two percent event
accuracy, versus sixteen percent for hand-written rules. Calibration error on unseen audio:
zero point zero one seven, from zero point one three. One active probe is already as
informative as knocking in every room."

**[2:45]** "RoomSense. It hears your home, measures it, and knows when it doesn't know.
Built in six days with Meta's models. Repo and live demo on screen."

## Recording checklist

- [ ] 1080p/60, phone on a shelf in shot 1; screen recordings for shots 2–6 at 100% brightness
- [ ] Mic: record voice with a real mic (not the phone) if possible; room tone for 10 s
- [ ] Have the numbers on screen for ≥3 s each (shots 7 cards)
- [ ] Show the `_model` id once (muse-spark-1.3-contributor) during shot 5
- [ ] Show the ALERT/EXPLAIN chips clearly; zoom in post if needed
- [ ] Fallback: browser demo at `http://<mac-ip>:8080/static/demo.html` if a device fails
- [ ] Verify repo/video links logged-out before submitting; rotate the Meta API key after the event
