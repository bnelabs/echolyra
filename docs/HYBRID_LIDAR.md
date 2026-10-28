# Hybrid mode: sound-only default + optional on-device LiDAR precision scan

Echolyra's privacy-first path stays **sound-only**. For a real room + furniture geometry, the
3D Room tab now offers an explicit **Precision scan · LiDAR** that uses Apple **RoomPlan** on
LiDAR-equipped iPhones (iPhone 12 Pro or later).

## What it does

- One continuous walk-around: press **Scan room with LiDAR**, grant camera permission (one time),
  tap **Start**, walk around the room, tap **Finish**.
- RoomPlan returns a **CapturedRoom**: walls, doors, windows, openings and objects with categories
  and dimensions/transforms. Echolyra exports it to a local **USDZ** model and renders it in an
  interactive SceneKit view (orbit/zoom).
- UI shows wall/door/window/object counts and object categories, and offers **Export 3D model
  (USDZ)** via the system share sheet.

## Privacy

- Camera + depth frames are processed **on-device** by Apple RoomPlan.
- The USDZ model is written **only** to the app's temporary directory; nothing is uploaded to the
  backend or Meta.
- The permission text (`NSCameraUsageDescription`) states this explicitly.
- The sound-only features remain the default; no LiDAR/camera access happens unless the user taps
  the precision scan and grants permission.
- Trial on an iPhone 12 Pro: real room and furniture geometry (RoomPlan), locally only.

## Why hybrid

Sound-only mapping in furnished rooms is research-grade: mono echo geometry recovers walls at best
and distance-only reflection candidates, and free-movement no-stop acoustic scanning is a SLAM
research problem. LiDAR/RoomPlan is the technology that delivers the natural "walk around once and
get the room" UX reliably, with true object geometry. Keeping both gives:

1. **Sound-only awareness** — always-on, privacy-preserving events/change monitoring.
2. **Optional precision scan** — real 3D room/furniture model when the user asks, for setup,
   visualization, or as **ground truth** to validate the acoustic map.
3. **No silent uploads** — the LiDAR model never leaves the device.

## Limits / honest notes

- LiDAR scans require a LiDAR device (iPhone 12 Pro+ / iPad Pro). Simulator and non-LiDAR phones
  show an unsupported message.
- RoomPlan object categories are coarse; the model is geometric, not semantic recognition.
- The LiDAR model and acoustic map are not yet automatically co-registered; alignment/validation
  is roadmap work.
- Camera permission is required for RoomPlan; without it the precision scan cannot run (sound-only
  features still work).
