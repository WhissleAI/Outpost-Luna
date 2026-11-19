#!/bin/bash
# Build and run the iPad app on a headless simulator (never opens Simulator.app). docs/IPAD.md.
#
#   bash ios/scripts/sim.sh build          xcodebuild for the simulator (DERIVED=<dir> to keep DerivedData elsewhere)
#   bash ios/scripts/sim.sh run            create/boot "Luna iPad", install, launch
#   bash ios/scripts/sim.sh shot <file>    screenshot of the running app
#   bash ios/scripts/sim.sh test [Test]    the touch walkthrough (XCUITest); screenshots into SHOTS=<dir>
#   bash ios/scripts/sim.sh stop           terminate the app and shut the simulator down
set -euo pipefail
IOS=$(cd "$(dirname "$0")/.." && pwd)
DERIVED=${DERIVED:-$IOS/build/DerivedData}
NAME=${SIM_NAME:-Luna iPad}
BUNDLE=ai.whissle.outpostluna
APP="$DERIVED/Build/Products/Debug-iphonesimulator/Outpost Luna.app"

udid() { xcrun simctl list devices -j | python3 -c "import json,sys;d=json.load(sys.stdin)['devices'];print(next((x['udid'] for v in d.values() for x in v if x['name']==sys.argv[1]),''))" "$NAME"; }

case "${1:-}" in
  build)
    [ -d "$IOS/build/Python.xcframework" ] || bash "$IOS/scripts/build_python.sh"
    nice -n 10 xcodebuild -project "$IOS/OutpostLuna.xcodeproj" -scheme OutpostLuna -configuration Debug \
      -destination "generic/platform=iOS Simulator" -derivedDataPath "$DERIVED" \
      CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM= build | grep -E "error:|BUILD (SUCCEEDED|FAILED)" || true
    [ -d "$APP" ] && du -sh "$APP"
    ;;
  run)
    U=$(udid)
    if [ -z "$U" ]; then
      U=$(xcrun simctl create "$NAME" com.apple.CoreSimulator.SimDeviceType.iPad-Pro-11-inch-M5-16GB \
          com.apple.CoreSimulator.SimRuntime.iOS-26-4)
    fi
    xcrun simctl boot "$U" 2>/dev/null || true
    xcrun simctl bootstatus "$U" >/dev/null
    xcrun simctl install "$U" "$APP"
    xcrun simctl terminate "$U" $BUNDLE 2>/dev/null || true
    xcrun simctl launch "$U" $BUNDLE
    ;;
  shot)
    xcrun simctl io "$(udid)" screenshot --type=png "${2:-$IOS/build/shot.png}"
    ;;
  test)
    U=$(udid); [ -n "$U" ] || { echo "run first: bash ios/scripts/sim.sh run"; exit 1; }
    mkdir -p "${SHOTS:=$IOS/build/shots}"
    nice -n 10 xcodebuild -project "$IOS/OutpostLuna.xcodeproj" -scheme OutpostLuna -configuration Debug \
      -destination "platform=iOS Simulator,id=$U" -derivedDataPath "$DERIVED" \
      CODE_SIGN_STYLE=Manual CODE_SIGN_IDENTITY=- DEVELOPMENT_TEAM= \
      -only-testing:"OutpostLunaUITests/Walkthrough${2:+/$2}" test \
      | grep -E "error:|Test Case|TEST (SUCCEEDED|FAILED)|XCTAssert|walkthrough:" || true
    # the runner writes into its own tmp (simulator apps get no host env): copy the newest luna-shots out
    src=$(ls -td "$HOME/Library/Developer/CoreSimulator/Devices/$U/data/Containers/Data/Application/"*/tmp/luna-shots 2>/dev/null | head -1)
    [ -n "$src" ] && cp "$src"/* "$SHOTS/" && rm -rf "$src" && echo "screenshots: $SHOTS"
    ;;
  stop)
    U=$(udid); xcrun simctl terminate "$U" $BUNDLE 2>/dev/null || true; xcrun simctl shutdown "$U" 2>/dev/null || true
    ;;
  *) sed -n 2,8p "$0"; exit 1 ;;
esac
