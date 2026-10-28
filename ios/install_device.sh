#!/usr/bin/env bash
# Build + install + launch Echolyra on a connected iPhone.
# Requires: Xcode signed in with an Apple ID + Personal Team, and the iPhone trusted once
# (Settings > General > VPN & Device Management > Developer App > Trust).
set -euo pipefail
cd "$(dirname "$0")/Echolyra"

echo "== connected physical devices =="
DEVICE_ID="$(python3 - <<'PY'
import json, subprocess
try:
    out = subprocess.check_output(["xcrun","devicectl","list","devices","--json-output","-"], text=True)
    data = json.loads(out)
    devices = data.get("result", {}).get("devices", [])
    phys = [d for d in devices if d.get("hardwareProperties", {}).get("deviceType") == "iPhone"]
    if not phys:
        phys = [d for d in devices if d.get("reality") == "physical"]
    print(phys[0].get("hardwareProperties", {}).get("udid") or phys[0]["identifier"] if phys else "")
except Exception:
    print("")
PY
)"
if [ -z "$DEVICE_ID" ]; then
  echo "No physical iPhone found. Plug it in, tap Trust, enable Developer Mode." >&2
  exit 1
fi
echo "device: $DEVICE_ID"

# Prefer the team from Xcode's provisioning store (Personal Team works), then fall back
# to the codesigning identity's team.
TEAM="$(defaults read com.apple.dt.Xcode IDEProvisioningTeamByIdentifier 2>/dev/null | grep -oE 'teamID = [A-Z0-9]{10}' | head -1 | awk '{print $3}')"
if [ -z "$TEAM" ]; then
  TEAM="$(security find-identity -v -p codesigning 2>/dev/null | grep -oE 'Apple Development: .*\(([A-Z0-9]{10})\)' | grep -oE '[A-Z0-9]{10}\)' | tr -d ')' | head -1 || true)"
fi
if [ -z "$TEAM" ]; then
  echo
  echo "No Apple development team found." >&2
  echo "Open Xcode > Settings (Cmd-,) > Accounts > '+' > Apple ID, sign in," >&2
  echo "then Xcode > Project > Signing & Capabilities > Team = 'Personal Team'." >&2
  echo "Re-run this script afterwards." >&2
  exit 2
fi
echo "team:   $TEAM"
echo "building…"
xcodebuild -project Echolyra.xcodeproj -scheme Echolyra -configuration Debug \
  -destination "platform=iOS,id=$DEVICE_ID" -derivedDataPath build-device \
  -allowProvisioningUpdates DEVELOPMENT_TEAM="$TEAM" build

APP="build-device/Build/Products/Debug-iphoneos/Echolyra.app"
[ -d "$APP" ] || { echo "build product missing" >&2; exit 3; }
echo "installing…"
xcrun devicectl device install app --device "$DEVICE_ID" "$APP"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo 127.0.0.1)"
echo "launching with backend http://$LAN_IP:8080 …"
xcrun devicectl device process launch --device "$DEVICE_ID" \
  -e "{\"ECHOLYRA_BACKEND\":\"http://$LAN_IP:8080\"}" com.bnelabs.roomsense || true
echo "done. On the phone: Settings tab → backend URL → Test connection → Rooms → knock → Listen."
