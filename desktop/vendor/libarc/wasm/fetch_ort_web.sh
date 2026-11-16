#!/bin/sh
# onnxruntime-web for the libarc WebAssembly page: the npm package's tarball, sha512-checked against the registry's
# integrity, and only the three files the page loads (ort.wasm.min.mjs, ort-wasm-simd-threaded.mjs / .wasm, ~15 MB)
set -eu
V="${ORT_WEB_VERSION:-1.31.1}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
npm pack "onnxruntime-web@$V" --silent >/dev/null
WANT="$(npm view "onnxruntime-web@$V" dist.integrity)"
HAVE="sha512-$(openssl dgst -sha512 -binary "onnxruntime-web-$V.tgz" | openssl base64 -A)"
[ "$WANT" = "$HAVE" ] || { echo "onnxruntime-web $V: integrity mismatch" >&2; exit 1; }
tar xzf "onnxruntime-web-$V.tgz" package/dist/ort.wasm.min.mjs package/dist/ort-wasm-simd-threaded.mjs \
  package/dist/ort-wasm-simd-threaded.wasm
mkdir -p "$HERE/ort"
cp package/dist/ort.wasm.min.mjs package/dist/ort-wasm-simd-threaded.mjs package/dist/ort-wasm-simd-threaded.wasm "$HERE/ort/"
echo "onnxruntime-web $V -> $HERE/ort"
