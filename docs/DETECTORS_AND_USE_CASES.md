# Detectors, Meta assistance, and honest real-life use cases

What sensors/detectors an iPhone app can actually use, what Meta models can genuinely add, and
which use cases are real versus marketing. Sources are linked; ratings are our judgment.

## 1. What Meta can and cannot do (verified)

| Model | Real capability | Honest limits |
|---|---|---|
| **SAM 3.1** ([docs](https://dev.meta.ai/docs/media-segmentation), [segmenting](https://dev.meta.ai/docs/sam/segmenting)) | Text noun-phrase, box, or point prompts over **images/video** → boxes/masks; object picking/tracking | Returns geometry/masks, not depth, identity, or 3D position; cloud upload; no safety guarantee |
| **Muse Wonder** ([models](https://dev.meta.ai/docs/models), [image](https://dev.meta.ai/docs/image-understanding), [video/audio](https://dev.meta.ai/docs/video-understanding)) | Text + image + video + PDF input → text: scene description, object lists, OCR-ish reasoning, video summaries, **audio is transcribed only** | Can hallucinate; not calibrated; not a measurement device; non-speech audio returns `NO_AUDIO_ACCESS` (tested); cloud latency/cost |
| **Muse Spark** | Text reasoning, situation reports, planning | Not a detector; can be wrong; use for explanation, not alerting logic |
| **Muse Image** ([docs](https://dev.meta.ai/docs/image-generation)) | Generate/edit images from prompts | Illustration only, never evidence/measurement |
| **Muse Voice Transcribe** ([docs](https://dev.meta.ai/docs/speech-to-text)) | Speech → text, turns, speakers | Speech only; **no sound-event detection** |

**Hard rule we verified:** Meta cannot classify knocks, glass, alarms, or room acoustics. Audio sent
to Meta is usable only for speech transcription. Any safety alert must be decided on-device.

## 2. Detector inventory on iPhone 12 Pro

| Detector | What it actually gives you | API / limits |
|---|---|---|
| **Microphone + Apple SoundAnalysis** | 303 built-in sound classes (alarms, glass, doorbell, water, pets, speech, vehicles…) on-device ([WWDC21](https://developer.apple.com/videos/play/wwdc2021/10036/)) | Not all custom sounds; confidence calibrated per class; mic uncalibrated for dB SPL |
| **Speaker + mic acoustic probe** | Room impulse response, RT60/EDT, room fingerprint, echo distances | Research-grade geometry; needs movement/known poses; directivity limits |
| **Camera + Vision** | Object/image classification, OCR, barcodes, human body/hand pose, saliency ([Vision](https://developer.apple.com/documentation/vision)) | 2D only; privacy; battery |
| **Camera + ARKit** | Device pose (VIO), plane detection, scene geometry | Requires camera; privacy; not depth-accurate without LiDAR |
| **LiDAR + RoomPlan** | Walls, doors, windows, openings, **furniture objects with category + dimensions/transform**, USDZ export ([RoomPlan](https://developer.apple.com/documentation/roomplan), [attributes](https://developer.apple.com/documentation/roomplan/captured-object-attributes)) | LiDAR iPhones only; categories coarse; no identity/condition; camera permission |
| **CoreMotion + pedometer** | Activity (walk/run/cycle/automotive/stationary), steps/distance, orientation, rotation | Drift; not a people detector; fall detection is Apple Watch, not iPhone |
| **Barometer (CMAltimeter)** | Relative altitude, floor changes | Weather drift; needs calibration |
| **Bluetooth / NFC / UWB** | Presence of known devices/tags; precise UWB range to U1/U2 accessories ([NearbyInteraction](https://developer.apple.com/documentation/nearbyinteraction)) | MAC randomization, background limits; UWB needs an accessory; no passive people sensing |
| **Wi-Fi / local network** | Device/service discovery (mDNS/SSDP), router integrations | RSSI/room inference is unreliable; permissions/entitlements |
| **Apple Watch / HealthKit** | Heart rate, activity rings, fall detection, workout data | User must wear Watch; medical claims off-limits |
| **HomeKit / Matter sensors** | Contact, motion, leak, temperature, air quality | Best-in-class for safety; requires accessories |
| **Ultrasound (speaker/mic)** | Potential presence/gesture research (18–22 kHz) | Phone rolloff/directivity; no shipping API; research only |

## 3. Real-life use cases — honest ratings

### Strong (sound + on-device detector + Meta explanation)
1. **Safety sound alerts with room context** — smoke alarm, glass break, doorbell/knock, running
   water, dog bark, baby cry. Detect on-device, attribute the room via acoustic fingerprint, let
   Muse Spark write the explanation/next step. Caveat: **not a certified safety device; never
   promise emergency response**; false alarms possible.
2. **Home awareness timeline** — “something happened in the kitchen while you were out” with
   sound class + room + confidence and silence under noise. This already exists in the app.
3. **Accessibility sound companion** — phone alerts for alarms/doorbell/knock, with visual/haptic
   cues; on-device by default. Strong social value; no cloud needed.

### Strong (LiDAR/vision, opt-in)
4. **Room + furniture inventory** — LiDAR/RoomPlan captures walls/doors/windows/furniture
   categories/dimensions in one walk-around; export USDZ; optional Meta SAM/Wonder photo pass for
   extra objects (boxes/masks). Caveat: categories approximate; no valuation/insurance-grade claim.
5. **Move-out / renovation baseline** — “before” room model + photos; Muse Wonder compares and
   describes changes (text), Muse Image renders concept illustrations. Text/illustration are not
   measurements.
6. **Opt-in “Scene check”** — user takes a photo/video; app asks *“what objects/hazards are
   visible?”* → SAM boxes + Muse Wonder description. Useful for package identification,
   accessibility narration, trip/clutter checks. Caveat: cloud upload explicit; can miss objects;
   no medical/security guarantee.

### Medium (works, but not alone)
7. **Elderly / independent-living check-in** — Watch activity/fall signals + on-device unusual
   sound + opt-in visual check; family summary written by Spark. **Not a medical device, no
   diagnosis, no guaranteed fall detection on iPhone alone.**
8. **Baby / pet monitoring** — cry/bark classes + room context + optional LiDAR/camera occupancy;
   no breathing/sleep-apnea claims; camera-free by default.
9. **Doorbell / package detection** — knock/doorbell sound triggers an opt-in photo check
   (SAM/Wonder: “is a package visible?”); works, but no delivery guarantee and privacy tradeoff.
10. **Smart-home presence** — BLE/UWB/HomeKit presence + room-acoustic context; automation.
    Acoustic presence alone is not reliable; UWB needs tags.
11. **Noise & comfort report** — RT60/reverb and relative noise levels; honest about uncalibrated
    dB(A); useful for calls/recording/quiet-hours, not legal sound measurement.

### Weak / don’t claim
12. **Water-leak detection by sound alone** — running water is detectable, but dripping/leaks are
    not reliable; recommend HomeKit leak sensors instead.
13. **Object-level acoustic mapping** — echoes localize surfaces/reflectors, not identities;
    LiDAR/camera needed for objects.
14. **Medical monitoring** (breathing, falls, sleep apnea) — not supportable with these sensors.
15. **Security monitoring / intruder guarantee** — sounds + camera checks are aids, not a
    monitored alarm; false alarms and liability risk.
16. **Sending audio to Meta** — verified impossible for non-speech analysis (`NO_AUDIO_ACCESS`);
    do not build an audio-upload feature expecting acoustic understanding.
17. **Calibrated legal sound-level meter** — iPhone mic is not a certified SPL meter without
    calibration.

## 4. Where Meta genuinely helps (and where it must not)

**Genuine:** scene description/object lists from opt-in photos/video (Muse Wonder), object
boxing/masking (SAM 3.1), reasoning over detector summaries (Muse Spark), speech transcription
(Muse Voice Transcribe), concept illustrations (Muse Image), numeric geometry review (Muse Wonder).

**Must stay on-device:** safety alert decisions, sound classification, fall/activity detection,
LiDAR geometry, any always-on sensing. Never send raw audio to Meta for acoustic understanding;
never let a cloud model be the only path for an alarm.

## 5. Recommended product packages

1. **Echolyra Awareness (sound-only, privacy-first)** — on-device sound alerts + room identity +
   calibrated uncertainty + Spark explanations. Already shipped.
2. **Echolyra Precision (LiDAR, opt-in)** — one-walk room/furniture model, USDZ export, local
   ground truth. Already shipped (hybrid build).
3. **Scene Check (Meta vision, opt-in)** — photo/video → SAM object boxes + Wonder description;
   best for accessibility, package checks, clutter/hazard review. Backend primitives exist
   (`/api/segment`, `/api/visualize`); not yet wired into the iOS UI.
4. **Home Inventory / Move-out** — Precision + Scene Check + Wonder descriptions; human-reviewed,
   not insurance-grade.
5. **Independent-living check-in** — Watch/activity + sound anomalies + opt-in visual check;
   explicit non-medical framing.

## 6. Sources

- Meta models overview: https://dev.meta.ai/docs/models
- Meta image understanding: https://dev.meta.ai/docs/image-understanding
- Meta video/audio understanding: https://dev.meta.ai/docs/video-understanding
- Meta SAM/media segmentation: https://dev.meta.ai/docs/media-segmentation and https://dev.meta.ai/docs/sam/segmenting
- Meta speech-to-text: https://dev.meta.ai/docs/speech-to-text
- Apple SoundAnalysis: https://developer.apple.com/documentation/soundanalysis
- Apple RoomPlan: https://developer.apple.com/documentation/roomplan
- Apple Vision: https://developer.apple.com/documentation/vision
- Apple NearbyInteraction: https://developer.apple.com/documentation/nearbyinteraction
- SoundAnalysis 303 classes (WWDC21): https://developer.apple.com/videos/play/wwdc2021/10036/
