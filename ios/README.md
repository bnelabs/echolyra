# RoomSense iOS app — ready to build (typechecked against iOS 27.1 SDK)

**Status:** 9 Swift files, 615 lines, written and **typechecked with Swift 6 against the
iPhoneOS 27.1 SDK on this Mac — zero errors**. It has not been run on a device yet
(no iPhone detected by the toolchain at the time of writing).

**Definition of done for today:** phone connected → build → backend reachable → learn 3 rooms
by knocking → "Listen" correctly says *what* and *which room*.

---

## 1. Create the Xcode project (2 minutes)

1. Xcode → File → New → Project → **iOS App**, SwiftUI, Swift.
2. Product name **RoomSense**, minimum iOS **17.0**, Interface SwiftUI, Language Swift.
3. Delete the generated `ContentView.swift` and `RoomSenseApp.swift`.
4. Drag the **9 files from `RoomSense/`** into the project (Copy items if needed, add to target).
5. Signing & Capabilities → select your personal team (free Apple ID works for on-device builds).

## 2. Info.plist keys

```xml
<key>NSMicrophoneUsageDescription</key>
<string>RoomSense listens for knocks and household sounds to learn each room's acoustic signature.</string>
<key>NSLocalNetworkUsageDescription</key>
<string>RoomSense sends acoustic features to your own backend on the local network.</string>
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsLocalNetworking</key><true/>
</dict>
```
If plain-HTTP LAN requests are still blocked: add `NSAllowsArbitraryLoads = true` **for this
hackathon build only**.

## 3. Run the backend and connect

```bash
cd sprint
PYTHON=../prototype/.venv/bin/python ./run_backend.sh     # prints your LAN IP
```
- **Simulator:** backend URL `http://127.0.0.1:8080` works (Mac-local).
- **iPhone:** use the Mac's LAN IP (default in the app: `http://192.168.68.50:8080`) and make
  sure the phone is on the same Wi-Fi. Check in Safari first: `http://<mac-ip>:8080/api/health`.

## 4. First run checklist

1. Open **Settings** tab → confirm the backend URL → **Test connection**.
2. **Rooms** tab → type a room name → **Knock once and record** (2.8 s; knock while it listens).
   Repeat for 2–3 rooms (living room, kitchen, bedroom).
3. **Listen** tab → **Listen for 3 seconds** → knock from one of the rooms → expect:
   event label + confidence, room name + confidence, and a Muse Spark situation card.
4. Wrong room? Record another sample in that room (adds to the room signature).
5. Wrong event label? Use **Teach this sound** and pick the right label.

## 5. Installing on a physical iPhone (one-time)

Team detected on this Mac: **QGPX7JPUL4 — "Baris Naci Erzeren (Personal Team)"**
(iPhone 12 Pro Max, iOS 27.0.1, Developer Mode enabled, profile valid until Nov 4).

```bash
./sprint/ios/install_device.sh     # builds with provisioning, installs, launches
```

iOS requires a one-time **Trust** for the developer certificate before a dev-signed app
can launch. On the iPhone: tap the RoomSense icon → *Untrusted Developer* → **Settings →
General → VPN & Device Management → Developer App → "Baris Naci Erzeren" → Trust**, then
allow the microphone prompt. After that, `install_device.sh` launches the app directly.

## 6. What each file does

| File | Role |
|---|---|
| `RoomSenseApp.swift` | app entry |
| `ContentView.swift` | 3 tabs: Rooms / Listen / Settings |
| `RoomsView.swift` | learn a room (record a knock → `POST /api/enroll`) |
| `DetectView.swift` | record a sound → `POST /api/detect`; result card + teach menu |
| `SettingsView.swift` | backend URL, connection test, reset session |
| `AppModel.swift` | app state + API calls |
| `APIClient.swift` | multipart upload of CAF clips; decodes session/detect responses |
| `Recorder.swift` | 16 kHz mono CAF recording via `AVAudioRecorder` (no sweep, no playback) |
| `Models.swift` | Codable models + event labels |

## 6. Notes

- Audio is recorded as **CAF**, which the backend reads via libsndfile (`soundfile`); no conversion
  needed on the phone.
- The old calibration app (`ios/RoomTwin/`) is legacy and not used by RoomSense.
- Reproduce the type check:
  ```bash
  xcrun --sdk iphoneos swiftc -typecheck -target arm64-apple-ios17.0 \
    -sdk "$(xcrun --sdk iphoneos --show-sdk-path)" -swift-version 6 *.swift
  ```
- No physical device was connected to this Mac during development: plug in the iPhone, trust the
  Mac, and enable Developer Mode (Settings → Privacy & Security → Developer Mode).
