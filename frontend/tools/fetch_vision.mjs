// Camera gestures: put the on-device vision runtime in frontend/public/vision/ so Vite serves it in dev and copies it
// into dist/ (and so into the desktop app). Nothing is ever loaded from a CDN at run time (docs/GESTURES.md §Offline).
//
//   node tools/fetch_vision.mjs            idempotent; runs before `npm run dev` / `npm run build`
//   node tools/fetch_vision.mjs --check    exit 1 if anything is missing or does not match its sha256
//
// - The WASM runtime comes from the pinned @mediapipe/tasks-vision npm package (node_modules, from `npm ci`): only the
//   ES-module SIMD build, which the module worker loads (Electron's Chromium always has WASM SIMD).
// - The two models are downloaded once from Google's public MediaPipe model bucket and pinned by sha256 (Apache-2.0).
//   A build machine needs the network the first time, like `npm ci`; the app never does.
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONT = path.resolve(HERE, "..");
const OUT = path.join(FRONT, "public", "vision");
const PKG = path.join(FRONT, "node_modules", "@mediapipe", "tasks-vision");

export const MODELS = [
  { file: "hand_landmarker.task", bytes: 7819105, sha256: "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1",
    url: "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task" },
  { file: "blaze_face_short_range.tflite", bytes: 229746, sha256: "b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f",
    url: "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite" },
];
export const WASM = ["vision_wasm_module_internal.js", "vision_wasm_module_internal.wasm"];
export const VERSION = "0.10.35";

const sha = f => crypto.createHash("sha256").update(fs.readFileSync(f)).digest("hex");
const check = process.argv.includes("--check");

function wasmOk() {
  return WASM.every(f => { const a = path.join(OUT, f), b = path.join(PKG, "wasm", f); return fs.existsSync(a) && (!fs.existsSync(b) || fs.statSync(a).size === fs.statSync(b).size); });
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  let bad = 0;
  // runtime
  const pkgVer = fs.existsSync(path.join(PKG, "package.json")) ? JSON.parse(fs.readFileSync(path.join(PKG, "package.json"), "utf8")).version : null;
  if (pkgVer && pkgVer !== VERSION) { console.error(`@mediapipe/tasks-vision is ${pkgVer}, expected ${VERSION} (package.json pins it)`); bad++; }
  if (!wasmOk()) {
    if (check) { console.error("vision: WASM runtime missing in public/vision"); bad++; }
    else if (!pkgVer) { console.error("vision: run `npm ci` first (node_modules/@mediapipe/tasks-vision missing)"); process.exit(1); }
    else WASM.forEach(f => fs.copyFileSync(path.join(PKG, "wasm", f), path.join(OUT, f)));
  }
  // models
  for (const m of MODELS) {
    const p = path.join(OUT, m.file);
    if (fs.existsSync(p) && fs.statSync(p).size === m.bytes && sha(p) === m.sha256) continue;
    if (check) { console.error(`vision: ${m.file} missing or wrong sha256`); bad++; continue; }
    process.stdout.write(`vision: downloading ${m.file} (${(m.bytes / 1e6).toFixed(1)} MB)… `);
    const r = await fetch(m.url);
    if (!r.ok) { console.error(`HTTP ${r.status}`); process.exit(1); }
    const buf = Buffer.from(await r.arrayBuffer());
    const got = crypto.createHash("sha256").update(buf).digest("hex");
    if (got !== m.sha256) { console.error(`sha256 mismatch: ${got}`); process.exit(1); }
    fs.writeFileSync(p + ".part", buf); fs.renameSync(p + ".part", p);
    console.log("ok");
  }
  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify({
    runtime: `@mediapipe/tasks-vision@${VERSION}`, license: "Apache-2.0",
    files: [...WASM, ...MODELS.map(m => m.file)].map(f => ({ file: f, bytes: fs.existsSync(path.join(OUT, f)) ? fs.statSync(path.join(OUT, f)).size : 0 })),
  }, null, 2) + "\n");
  if (bad) process.exit(1);
  const total = [...WASM, ...MODELS.map(m => m.file)].reduce((a, f) => a + fs.statSync(path.join(OUT, f)).size, 0);
  console.log(`vision: ${check ? "verified" : "ready"} in public/vision (${(total / 1e6).toFixed(1)} MB)`);
}
main();
