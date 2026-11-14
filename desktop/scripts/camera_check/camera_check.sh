#!/usr/bin/env bash
# Camera gestures in real Electron, without the 1 GB bundle (docs/GESTURES.md §"Electron check").
# Packages a tiny .app with the SAME electron version, Info.plist camera/mic strings, entitlements and session lockdown
# (desktop/main/permissions.js) as Outpost Luna, then runs it against a backend that serves frontend/dist.
#
#   (cd desktop && npm ci)                       # electron 44 + electron-builder (if Electron's binary is missing: node node_modules/electron/install.js)
#   (cd frontend && npm run build)  + a backend serving it, e.g. on :8390
#   bash desktop/scripts/camera_check/camera_check.sh [origin]          # real camera: macOS asks once
#   FAKE_CAMERA=1 bash desktop/scripts/camera_check/camera_check.sh     # Chromium's fake camera, no prompt
# Writes the result JSON (fps, ms, delegate, indicator, CPU, prompt result) to $OUT (default /tmp/outpost-camera-check.json).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; DESK="$(cd "$HERE/../.." && pwd)"
ORIGIN="${1:-http://127.0.0.1:8390}"
OUT="${OUT:-/tmp/outpost-camera-check.json}"
BUILD="${BUILD:-$DESK/build/camera_check}"
cp "$DESK/main/permissions.js" "$HERE/permissions.js"
rm -rf "$BUILD"
CSC_IDENTITY_AUTO_DISCOVERY=false "$DESK/node_modules/.bin/electron-builder" --projectDir "$HERE" --mac dir --arm64 --publish never \
  -c.appId=ai.whissle.outpostluna.cameracheck -c.electronVersion="$(node -p "require('$DESK/node_modules/electron/package.json').version")" \
  -c.electronDist="$DESK/node_modules/electron/dist" -c.directories.output="$BUILD" -c.mac.identity=- \
  -c.mac.entitlements="$DESK/build-resources/entitlements.mac.plist" -c.mac.entitlementsInherit="$DESK/build-resources/entitlements.mac.plist" \
  -c.mac.extendInfo.NSCameraUsageDescription="$(node -e "const y=require('fs').readFileSync('$DESK/electron-builder.yml','utf8');process.stdout.write(y.match(/NSCameraUsageDescription: \"([^\"]+)\"/)[1])")" \
  -c.mac.extendInfo.NSMicrophoneUsageDescription="Outpost Luna camera check." >/dev/null
rm -f "$HERE/permissions.js"
APP="$(ls -d "$BUILD"/mac-arm64/*.app)"
/usr/libexec/PlistBuddy -c "Print :NSCameraUsageDescription" "$APP/Contents/Info.plist"
# Launched from a terminal, macOS attributes camera consent to the terminal (its "responsible process"), so the app's own
# prompt never shows. OPEN=1 launches through LaunchServices like a double-click: the app asks for itself.
if [ "${OPEN:-0}" = 1 ]; then
  open -n -W --env OUTPOST_ORIGIN="$ORIGIN" --env OUT="$OUT" --env FAKE_CAMERA="${FAKE_CAMERA:-0}" --env SECONDS_ON="${SECONDS_ON:-15}" "$APP" || true
else
  OUTPOST_ORIGIN="$ORIGIN" OUT="$OUT" FAKE_CAMERA="${FAKE_CAMERA:-0}" "$APP/Contents/MacOS/$(basename "$APP" .app)" || true
fi
cat "$OUT"
[ "${KEEP:-0}" = 1 ] || rm -rf "$BUILD"
