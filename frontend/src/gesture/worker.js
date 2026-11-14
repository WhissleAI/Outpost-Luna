// Camera gestures: the vision worker. MediaPipe Tasks Vision (Apache-2.0) runs here, off the main thread, from files
// bundled in the app (/vision/: the WASM runtime and two models). It gets one downscaled ImageBitmap at a time, returns
// landmarks only, and closes the bitmap at once. Frames are never stored, logged or sent anywhere (docs/GESTURES.md).
//
// in:  {t: "init", base, numHands, face, delegate}   {t: "frame", bitmap, ts}   {t: "config", face}
// out: {t: "ready", delegate, loadMs}   {t: "result", ts, ms, hands, faces}   {t: "error", message}
import { FilesetResolver, HandLandmarker, FaceDetector } from "@mediapipe/tasks-vision";

let hands = null, face = null, faceOn = false, lastTs = -1;

let factory = null;   // the WASM module factory, imported once; MediaPipe clears self.ModuleFactory after each task
async function create(Kind, fileset, options, delegate) {
  if (!factory) factory = (await import(/* @vite-ignore */ fileset.wasmLoaderPath)).default;
  self.ModuleFactory = factory;
  try { return { task: await Kind.createFromOptions(fileset, { ...options, baseOptions: { ...options.baseOptions, delegate } }), delegate }; }
  catch (e) {
    if (delegate === "CPU") throw e;
    self.ModuleFactory = factory;
    return { task: await Kind.createFromOptions(fileset, { ...options, baseOptions: { ...options.baseOptions, delegate: "CPU" } }), delegate: "CPU" };
  }
}

async function init({ base = "/vision/", numHands = 2, face: wantFace = true, delegate = "GPU" }) {
  const t0 = performance.now();
  // Explicit fileset: our own bundled module build, never a CDN.
  const fileset = { wasmLoaderPath: base + "vision_wasm_module_internal.js", wasmBinaryPath: base + "vision_wasm_module_internal.wasm" };
  void FilesetResolver;   // (forVisionTasks() would probe; the paths above are fixed)
  const h = await create(HandLandmarker, fileset, {
    baseOptions: { modelAssetPath: base + "hand_landmarker.task" }, runningMode: "VIDEO", numHands,
    minHandDetectionConfidence: 0.6, minHandPresenceConfidence: 0.6, minTrackingConfidence: 0.5,
  }, delegate);
  hands = h.task;
  if (wantFace) {
    const f = await create(FaceDetector, fileset, {
      baseOptions: { modelAssetPath: base + "blaze_face_short_range.tflite" }, runningMode: "VIDEO", minDetectionConfidence: 0.6,
    }, h.delegate);
    face = f.task; faceOn = true;
  }
  postMessage({ t: "ready", delegate: h.delegate, loadMs: Math.round(performance.now() - t0) });
}

/** MediaPipe assumes a mirrored (selfie) image for handedness; our frames are not mirrored, so the label flips. */
const side = cat => (cat && cat.categoryName === "Left" ? "right" : "left");

function frame({ bitmap, ts }) {
  if (!hands) { bitmap.close(); return; }
  if (ts <= lastTs) ts = lastTs + 1; lastTs = ts;
  const t0 = performance.now(), W = bitmap.width, H = bitmap.height;
  let outHands = [], outFaces = [];
  try {
    const r = hands.detectForVideo(bitmap, ts);
    outHands = (r.landmarks || []).map((lm, i) => {
      const cat = ((r.handednesses || r.handedness || [])[i] || [])[0];
      return { lm: lm.map(p => [1 - p.x, p.y, p.z]), side: side(cat), score: cat ? cat.score : 1 };   // mirror x
    });
    if (face && faceOn) {
      const fr = face.detectForVideo(bitmap, ts);
      outFaces = (fr.detections || []).map(d => {
        const b = d.boundingBox || { originX: 0, originY: 0, width: 0, height: 0 };
        return {
          box: { x: 1 - (b.originX + b.width) / W, y: b.originY / H, w: b.width / W, h: b.height / H },
          kp: (d.keypoints || []).map(k => [1 - k.x, k.y]),
          score: (d.categories && d.categories[0] && d.categories[0].score) || 0,
        };
      });
    }
  } catch (e) { postMessage({ t: "error", message: String(e && e.message || e) }); }
  finally { bitmap.close(); }   // the pixels are gone now
  postMessage({ t: "result", ts, ms: Math.round((performance.now() - t0) * 10) / 10, aspect: W / H, hands: outHands, faces: outFaces });
}

onmessage = async e => {
  const m = e.data || {};
  try {
    if (m.t === "init") await init(m);
    else if (m.t === "frame") frame(m);
    else if (m.t === "config") faceOn = !!m.face && !!face;
  } catch (err) { if (m.bitmap) m.bitmap.close(); postMessage({ t: "error", message: String(err && err.message || err) }); }
};
