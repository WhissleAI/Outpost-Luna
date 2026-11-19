#!/bin/bash
# Cross-compile pydantic-core's Rust extension for iOS (simulator + device) against BeeWare's Python.xcframework.
# Nobody publishes iOS wheels for pydantic-core (PyPI and the BeeWare index have none), so the app builds its own.
# Needs: rustup with `rustup target add aarch64-apple-ios aarch64-apple-ios-sim`, Xcode. ~3 min per target.
#   bash ios/scripts/build_pydantic_core.sh <build dir with Python.xcframework> <out dir>
set -euo pipefail
B=$1; OUT=$2
X=$B/Python.xcframework
VER=2.50.4                                        # = backend/uv.lock (pydantic 2.14.3 needs exactly this)
URL=https://files.pythonhosted.org/packages/9c/0f/34f9ce4ba701dd0b815033ef94d99b56f66200e578ee6052aa3ac26f064e/pydantic_core-$VER.tar.gz
export PATH=$HOME/.cargo/bin:$PATH
command -v cargo >/dev/null || { echo "needs Rust: https://rustup.rs, then rustup target add aarch64-apple-ios aarch64-apple-ios-sim"; exit 1; }
SRC=$B/pydantic_core-$VER
if [ ! -d "$SRC" ]; then
  curl -fsSL "$URL" -o "$B/dl/pydantic_core-$VER.tar.gz"
  tar -xzf "$B/dl/pydantic_core-$VER.tar.gz" -C "$B"
fi
export CARGO_TARGET_DIR=$B/pydantic_core-target
cd "$SRC"
for spec in "aarch64-apple-ios-sim:ios-arm64_x86_64-simulator:iphonesimulator:iphonesimulator" \
            "aarch64-apple-ios:ios-arm64:iphoneos:iphoneos"; do
  IFS=: read -r T SLICE SUF SDK <<<"$spec"
  dst=$OUT/$SDK/_pydantic_core.cpython-313-$SUF.so
  [ -f "$dst" ] && continue
  export PYO3_CROSS_LIB_DIR=$X/$SLICE/lib-arm64/python3.13
  export PYO3_CROSS_PYTHON_VERSION=3.13
  export IPHONEOS_DEPLOYMENT_TARGET=17.0
  SDKROOT=$(xcrun --sdk "$SDK" --show-sdk-path); export SDKROOT
  RUSTFLAGS="-L $X/$SLICE/lib -C link-arg=-F$X/$SLICE -C link-arg=-framework -C link-arg=Python" \
    cargo rustc --release --lib --target "$T" --crate-type cdylib
  mkdir -p "$OUT/$SDK"
  cp "$CARGO_TARGET_DIR/$T/release/lib_pydantic_core.dylib" "$dst"
  install_name_tool -id "@rpath/_pydantic_core.framework/_pydantic_core" "$dst" 2>/dev/null || true
done
ls -la "$OUT"/*
