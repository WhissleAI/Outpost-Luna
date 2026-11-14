#!/usr/bin/env bash
# Outpost Luna desktop: one command from a fresh clone to desktop/dist/Outpost Luna-<version>-arm64.dmg (macOS arm64).
# Mirrors desktop/scripts/build-windows.ps1 step for step. docs/DESKTOP.md explains each step.
#
#   bash desktop/scripts/build-mac.sh            # everything
#   SKIP_MEDIA=1 bash desktop/scripts/build-mac.sh   # backend/data/media already in place
#   SKIP_PREP=1 ...                                  # steps 2-6 already done (desktop/resources/ is complete)
#
# Signing (docs/DESKTOP.md "Signing and notarization"): ad-hoc by default. For a release:
#   MAC_SIGN_IDENTITY="Developer ID Application: Whissle LLC (XXK95K57U5)"   # in the login keychain
#   NOTARY_PROFILE=outpost-notary        # once: xcrun notarytool store-credentials outpost-notary ...
#
# Needs: Xcode command line tools (clang), Node 22+, uv, CMake, Git. About 6 GB free disk. No accounts, keys or tokens:
# the models come from the public, sha256-pinned model package; the NASA media from nasa.gov.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
T0=$(date +%s)
step() { printf '\n==> [%s] %s\n' "$(( $(date +%s) - T0 ))s" "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# Caches stay inside the clone.
export UV_CACHE_DIR="$ROOT/desktop/build/uv-cache"
export ELECTRON_CACHE="$ROOT/desktop/build/cache/electron"
export ELECTRON_BUILDER_CACHE="$ROOT/desktop/build/cache/electron-builder"
export npm_config_cache="$ROOT/desktop/build/cache/npm"
export CSC_IDENTITY_AUTO_DISCOVERY=false   # never pick a keychain identity implicitly: MAC_SIGN_IDENTITY or ad-hoc
MAC_SIGN_IDENTITY="${MAC_SIGN_IDENTITY:-}"
NOTARY_PROFILE="${NOTARY_PROFILE:-}"
export MAC_SIGN_IDENTITY                   # read by desktop/scripts/sign-resources.js (afterPack)

step "1/8 prerequisites"
[ "$(uname -s)" = Darwin ] || die "build-mac.sh is for macOS; on Windows run desktop/scripts/build-windows.ps1"
[ "$(uname -m)" = arm64 ] || echo "warning: this Mac is $(uname -m); the dmg is arm64 only"
command -v git >/dev/null   || die "git missing: xcode-select --install"
command -v clang >/dev/null || die "clang missing: xcode-select --install"
command -v node >/dev/null  || die "Node missing: brew install node@22"
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
[ "$NODE_MAJOR" -ge 22 ] || die "Node $NODE_MAJOR found, need 22+: brew install node@22"
command -v uv >/dev/null    || die "uv missing: curl -LsSf https://astral.sh/uv/install.sh | sh"
command -v cmake >/dev/null || die "CMake missing: brew install cmake"
FREE_GB=$(df -g "$ROOT" | awk 'NR==2{print $4}')
[ "$FREE_GB" -ge 6 ] || die "only ${FREE_GB} GB free; the build needs about 6 GB"
echo "node $(node -v), $(uv --version), $(cmake --version | head -1), ${FREE_GB} GB free"
if [ -n "$MAC_SIGN_IDENTITY" ]; then
  security find-identity -v -p codesigning | grep -qF "\"$MAC_SIGN_IDENTITY\"" \
    || die "signing identity not in the keychain: $MAC_SIGN_IDENTITY (security find-identity -v -p codesigning)"
  echo "signing: $MAC_SIGN_IDENTITY (hardened runtime)"
  if [ -n "$NOTARY_PROFILE" ]; then
    xcrun notarytool history --keychain-profile "$NOTARY_PROFILE" >/dev/null 2>&1 \
      || die "notary profile '$NOTARY_PROFILE' missing or invalid: xcrun notarytool store-credentials $NOTARY_PROFILE --apple-id <id> --team-id <team>"
    echo "notarizing with keychain profile: $NOTARY_PROFILE"
  else echo "warning: MAC_SIGN_IDENTITY without NOTARY_PROFILE -> signed but NOT notarized (Gatekeeper still warns)"; fi
else
  [ -z "$NOTARY_PROFILE" ] || die "NOTARY_PROFILE needs MAC_SIGN_IDENTITY (an ad-hoc app cannot be notarized)"
  echo "signing: ad-hoc (set MAC_SIGN_IDENTITY for a Developer ID build)"
fi

if [ "${SKIP_PREP:-0}" = 1 ]; then
  step "2-6/8 skipped (SKIP_PREP=1)"
  for f in desktop/resources/python/bin/python3 desktop/resources/native/libarctag.dylib desktop/resources/models/arctag; do
    [ -e "$f" ] || die "SKIP_PREP=1 but $f is missing; run without it"; done
else
step "2/8 NASA media (backend/data/media: 74 crew clips + Moon map, ~0.5 GB; trimmed copy for the app, ~175 MB)"
if [ "${SKIP_MEDIA:-0}" = 1 ]; then echo "skipped (SKIP_MEDIA=1)"
else uv run --no-project --with pillow==11.3.0 python backend/pipeline/fetch_media.py; fi
[ -s backend/data/media/img/moon4k.jpg ] || die "backend/data/media is incomplete (re-run; fetch_media.py resumes)"

step "3/8 frontend dependencies"
(cd frontend && npm ci --no-audit --no-fund && node tools/fetch_vision.mjs)   # + camera-gesture runtime/models (sha256-pinned)

step "4/8 embedded Python + backend/model-server deps + app code (frontend build included)"
uv run --no-project python desktop/scripts/build_python.py

step "5/8 models (local HF cache if complete, else the public package; sha256 + models.lock.json)"
uv run --no-project python desktop/scripts/gather_models.py

step "6/8 Arc Tagger native library (libarctag.dylib)"
cmake -S desktop/vendor/arctag -B desktop/build/arctag -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 >/dev/null
cmake --build desktop/build/arctag --config Release
mkdir -p desktop/resources/native
cp desktop/build/arctag/libarctag.dylib desktop/resources/native/

fi

# Always (also with SKIP_MEDIA / SKIP_PREP; incremental, seconds when current). The installer ships only the playable stretches of each clip, mono 48 kbps (~175 MB, not ~550): ffmpeg from a pinned wheel
(cd backend && uv run --with imageio-ffmpeg==0.6.0 python -m pipeline.trim_media)

step "7/8 Electron + electron-builder (dmg)"
cd desktop
npm ci --no-audit --no-fund
rm -rf dist/mac-arm64
APP="dist/mac-arm64/Outpost Luna.app"
if [ -z "$MAC_SIGN_IDENTITY" ]; then
  npx electron-builder --mac dmg --arm64 --publish never
else
  # 7a: signed .app (osx-sign seals the Electron parts; sign-resources.js the Python/torch/arctag Mach-O files)
  npx electron-builder --mac dir --arm64 --publish never \
    -c.mac.identity="${MAC_SIGN_IDENTITY#Developer ID Application: }" -c.mac.hardenedRuntime=true
  codesign --verify --deep --strict "$APP"
  notarize() {  # $1 = file to submit (zip or dmg)
    echo "notarytool: uploading $(du -h "$1" | cut -f1) ..."
    OUT=$(xcrun notarytool submit "$1" --keychain-profile "$NOTARY_PROFILE" --wait --timeout 2h 2>&1) || true
    echo "$OUT"
    ID=$(echo "$OUT" | awk '/^  id:/{print $2; exit}')
    if ! echo "$OUT" | grep -q "status: Accepted"; then
      [ -n "$ID" ] && xcrun notarytool log "$ID" --keychain-profile "$NOTARY_PROFILE" | tee dist/notary-log.json
      die "notarization of $1 failed (log: desktop/dist/notary-log.json)"
    fi
  }
  if [ -n "$NOTARY_PROFILE" ]; then
    # 7b: notarize + staple the .app itself, so a copy dragged to /Applications opens offline too
    ditto -c -k --sequesterRsrc --keepParent "$APP" dist/notarize-app.zip
    notarize dist/notarize-app.zip && rm -f dist/notarize-app.zip
    xcrun stapler staple "$APP"
  fi
  # 7c: dmg around the (stapled) app, signed; then the dmg is notarized + stapled as well
  npx electron-builder --mac dmg --arm64 --publish never --prepackaged "$APP" \
    -c.mac.identity="${MAC_SIGN_IDENTITY#Developer ID Application: }" -c.mac.hardenedRuntime=true
  DMG="dist/$(cd dist && ls -t *.dmg | head -1)"
  codesign --force --sign "$MAC_SIGN_IDENTITY" --timestamp "$DMG"
  if [ -n "$NOTARY_PROFILE" ]; then
    notarize "$DMG"
    xcrun stapler staple "$DMG"
    spctl -a -vvv -t install "$DMG"
    spctl -a -vvv -t exec "$APP"
  fi
fi
rm -rf dist/mac-arm64 dist/builder-debug.yml          # the unpacked app (1.9 GB) is inside the dmg

step "8/8 done"
ls -lh dist/*.dmg
echo "Installer: $ROOT/desktop/dist/$(cd dist && ls -t *.dmg | head -1)  ($(( $(date +%s) - T0 )) s)"
echo "Smoke test: open it, then: PYTHONPATH=desktop/resources/site/backend desktop/resources/python/bin/python3 desktop/scripts/smoke.py"
