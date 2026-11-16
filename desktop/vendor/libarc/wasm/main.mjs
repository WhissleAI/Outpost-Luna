// libarc (C, WebAssembly) + onnxruntime-web: load the ear, transcribe one clip, show the JSON (window.arcResult).
// ?clip=c11_0 (a desktop/tests/golden clip), ?names=Shackleton:lunar_feature;Tycho:lunar_feature, ?threads=4
import * as ort from "./ort/ort.wasm.min.mjs";
import createArc from "./build/arc.mjs";

const q = new URLSearchParams(location.search);
const clip = q.get("clip") || "c11_0";
const names = q.get("names");
const status = (s) => { document.getElementById("status").textContent = s; console.log(s); };
const MODEL = "model/";   // the nft2/ folder, served by serve.py
// everything libarc's C reads; encoder.weights (282 MB) goes to onnxruntime-web only
const FILES = ["config.json", "tags.json", "adapters.safetensors", "model.q4.safetensors",
  "decoder/config.json", "decoder/generation_config.json", "decoder/processor_config.json",
  "decoder/tokenizer_config.json", "decoder/tokenizer.json", "decoder/model.safetensors",
  "encoder_onnx/config.json", "encoder_onnx/tokens.txt", "encoder_onnx/tokenizer.model", "encoder_onnx/frontend.npz",
  "encoder_onnx/encoder.onnx", "encoder_onnx/encoder_first.onnx", "encoder_onnx/decoder.onnx",
  "encoder_onnx/joint_enc.onnx", "encoder_onnx/joint_net.onnx"];

async function bytes(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}

async function run() {
  const t0 = performance.now();
  ort.env.wasm.wasmPaths = new URL("./ort/", location.href).href;
  ort.env.wasm.numThreads = self.crossOriginIsolated ? Number(q.get("threads") || 4) : 1;
  let out = "";
  let done;
  const finished = new Promise((res) => (done = res));
  const Module = await createArc({
    print: (line) => {
      out += line + "\n";
      try { done(JSON.parse(out)); } catch { /* not complete yet */ }
    },
    printErr: (line) => console.warn(line),
  });
  Module.ort = ort;
  status("fetching the model…");
  Module.FS.mkdirTree("/nft2/decoder");
  Module.FS.mkdirTree("/nft2/encoder_onnx");
  let mb = 0;
  for (const f of FILES) {
    const b = await bytes(MODEL + f);
    mb += b.length / 1e6;
    Module.FS.writeFile("/nft2/" + f, b);
  }
  Module.encoderWeights = await bytes(MODEL + "encoder_onnx/encoder.weights");
  mb += Module.encoderWeights.length / 1e6;
  Module.FS.writeFile("/clip.wav", await bytes(`clip/${clip}.wav`));
  const tFetch = performance.now();
  status(`fetched ${mb.toFixed(0)} MB in ${((tFetch - t0) / 1000).toFixed(1)} s; loading + transcribing…`);
  const args = ["/nft2", "(linked)", "/clip.wav", "--threads", "1"];
  if (names) args.push("--names", names);
  Module.callMain(args);
  const r = await finished;
  r.page = { clip, fetch_s: +((tFetch - t0) / 1000).toFixed(2), total_s: +((performance.now() - t0) / 1000).toFixed(2),
             cross_origin_isolated: self.crossOriginIsolated, ort_threads: ort.env.wasm.numThreads,
             ort_web: ort.env.versions && ort.env.versions.web,
             js_heap_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null,
             arc_heap_mb: Math.round(Module.HEAPU8 ? Module.HEAPU8.length / 1e6 : -1) };
  window.arcResult = r;
  status(r.error ? `error: ${r.error}: ${r.reason}` : `"${(r.utts || []).map((u) => u.text).join(" / ")}"`);
  document.getElementById("out").textContent = JSON.stringify(r, null, 1);
}

run().catch((e) => {
  window.arcResult = { error: "page", reason: String(e && e.stack || e) };
  status("error: " + e);
});
