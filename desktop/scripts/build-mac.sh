#!/usr/bin/env bash
# Outpost Luna desktop: one command from a fresh clone to desktop/dist/Outpost Luna-<version>-arm64.dmg (macOS arm64).
# Mirrors desktop/scripts/build-windows.ps1 step for step. docs/DESKTOP.md explains each step.
#
#   bash desktop/scripts/build-mac.sh            # everything
#   SKIP_MEDIA=1 bash desktop/scripts/build-mac.sh   # backend/data/media already in place
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
export CSC_IDENTITY_AUTO_DISCOVERY=false   # ad-hoc signature until a Developer ID exists (docs/DESKTOP.md)

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

step "2/8 NASA media (backend/data/media: 74 crew clips + Moon map, ~0.5 GB)"
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

step "7/8 Electron + electron-builder (dmg)"
cd desktop
npm ci --no-audit --no-fund
rm -rf dist/mac-arm64
npx electron-builder --mac dmg --arm64 --publish never
rm -rf dist/mac-arm64 dist/builder-debug.yml          # the unpacked app (1.9 GB) is inside the dmg

step "8/8 done"
ls -lh dist/*.dmg
echo "Installer: $ROOT/desktop/dist/$(cd dist && ls -t *.dmg | head -1)  ($(( $(date +%s) - T0 )) s)"
echo "Smoke test: open it, then: PYTHONPATH=desktop/resources/site/backend desktop/resources/python/bin/python3 desktop/scripts/smoke.py"
