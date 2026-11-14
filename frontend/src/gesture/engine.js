// Camera gestures: the engine. Owns the camera stream, paces frames into the vision worker (requestVideoFrameCallback,
// one frame in flight, adaptive 10–30 fps), runs the classifier on the landmarks that come back, and hands gesture
// events to bind.js. docs/GESTURES.md.
//
// Privacy: the stream never leaves this page. Each frame is downscaled into an ImageBitmap, transferred to the worker
// and closed there; only landmark numbers come back, and only intents leave this module. Nothing is stored or logged.
import { createGestureClassifier } from "./classifier.js";
import { cameraErrorText } from "./guide.js";

const FPS_STEPS = [30, 24, 15, 10];

export function createGestureEngine({ onEvents = () => {}, onLandmarks = () => {}, onStatus = () => {}, base = "/vision/", classifierOptions = {} } = {}) {
  const classifier = createGestureClassifier(classifierOptions);
  const video = document.createElement("video");
  video.muted = true; video.playsInline = true; video.setAttribute("aria-hidden", "true");
  let stream = null, worker = null, ready = false, busy = false, running = false, faceWanted = classifierOptions.headLook !== false;
  let fpsIdx = 1, lastSent = 0, rvfc = 0, raf = 0;
  const stats = { fps: 0, inferMs: 0, delegate: null, loadMs: 0, frames: 0, width: 0, height: 0, targetFps: FPS_STEPS[1], state: "off" };
  let fpsCount = 0, fpsT = performance.now(), msAvg = 0;

  function status(state, extra) { stats.state = state; onStatus({ state, ...extra, stats: { ...stats } }); }

  function adapt() {
    // frame budget: inference should take under ~60 % of the frame interval; step down when it doesn't, up when easy
    const budget = 1000 / FPS_STEPS[fpsIdx];
    if (msAvg > budget * 0.6 && fpsIdx < FPS_STEPS.length - 1) fpsIdx++;
    else if (fpsIdx > 0 && msAvg < (1000 / FPS_STEPS[fpsIdx - 1]) * 0.35) fpsIdx--;
    stats.targetFps = FPS_STEPS[fpsIdx];
  }

  function handleResult(m) {
    busy = false;
    msAvg = msAvg ? msAvg * 0.85 + m.ms * 0.15 : m.ms; stats.inferMs = Math.round(msAvg * 10) / 10;
    fpsCount++; stats.frames++;
    const now = performance.now();
    if (now - fpsT >= 1000) { stats.fps = Math.round(fpsCount * 1000 / (now - fpsT)); fpsCount = 0; fpsT = now; adapt(); }
    const frame = { t: m.ts, aspect: m.aspect, hands: m.hands, faces: m.faces };
    onLandmarks(frame);
    const ev = classifier.push(frame);
    if (ev.length) onEvents(ev, frame);
  }

  async function pump() {
    if (!running) return;
    schedule();
    if (!ready || busy || video.readyState < 2) return;
    const now = performance.now();
    if (now - lastSent < 1000 / FPS_STEPS[fpsIdx] - 2) return;
    lastSent = now; busy = true;
    try {
      const vw = video.videoWidth || 640, vh = video.videoHeight || 480, w = 320, h = Math.round(w * vh / vw);
      stats.width = vw; stats.height = vh;
      const bitmap = await createImageBitmap(video, { resizeWidth: w, resizeHeight: h, resizeQuality: "low" });
      if (!running) { bitmap.close(); busy = false; return; }
      worker.postMessage({ t: "frame", bitmap, ts: Math.round(now) }, [bitmap]);
    } catch (e) { busy = false; }
  }
  function schedule() {
    if (!running) return;
    if (video.requestVideoFrameCallback) rvfc = video.requestVideoFrameCallback(() => pump());
    else raf = requestAnimationFrame(() => pump());
  }

  function startWorker() {
    return new Promise((resolve, reject) => {
      worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module", name: "vision" });
      const to = setTimeout(() => reject(new Error("The gesture models took too long to load.")), 30000);
      worker.onmessage = e => {
        const m = e.data || {};
        if (m.t === "ready") { clearTimeout(to); ready = true; stats.delegate = m.delegate; stats.loadMs = m.loadMs; resolve(); }
        else if (m.t === "result") handleResult(m);
        else if (m.t === "error") { busy = false; if (!ready) { clearTimeout(to); reject(new Error(m.message)); } else console.warn("[gestures]", m.message); }
      };
      worker.onerror = e => { clearTimeout(to); reject(new Error(e.message || "vision worker failed")); };
      worker.postMessage({ t: "init", base: new URL(base, location.href).href, numHands: 2, face: true, delegate: "GPU" });
    });
  }

  async function start({ deviceId } = {}) {
    if (running) await stop();
    status("starting");
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { deviceId: deviceId ? { exact: deviceId } : undefined, width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30, max: 30 }, facingMode: deviceId ? undefined : "user" },
      });
    } catch (e) {
      status("denied", { error: cameraErrorText(e) });
      return false;
    }
    video.srcObject = stream;
    try { await video.play(); } catch (e) { /* autoplay of a muted stream is allowed; ignore */ }
    running = true; classifier.reset();
    try { if (!worker) await startWorker(); }
    catch (e) { await stop(); status("error", { error: "Gestures couldn't start: " + e.message }); return false; }
    worker.postMessage({ t: "config", face: faceWanted });
    status("on"); schedule();
    return true;
  }

  async function stop() {
    running = false; ready = ready && !!worker;
    if (rvfc && video.cancelVideoFrameCallback) video.cancelVideoFrameCallback(rvfc);
    cancelAnimationFrame(raf); rvfc = raf = 0;
    if (stream) stream.getTracks().forEach(t => t.stop());
    stream = null; video.srcObject = null; busy = false;
    // the worker (and its WASM heap) goes too: nothing stays loaded while the camera is off
    if (worker) { worker.terminate(); worker = null; ready = false; }
    stats.fps = 0; status("off");
  }

  async function listDevices() {
    try { return (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput").map((d, i) => ({ id: d.deviceId, label: d.label || `Camera ${i + 1}` })); }
    catch (e) { return []; }
  }

  return {
    start, stop, listDevices, video, classifier,
    get running() { return running; }, get stats() { return { ...stats }; },
    configure(o) {
      classifier.configure(o);
      if ("headLook" in o || "face" in o) { faceWanted = o.face ?? o.headLook; if (worker) worker.postMessage({ t: "config", face: faceWanted }); }
    },
    /** Tests and the calibration replay: push landmark frames straight into the classifier (no camera). */
    inject(frames) {
      const all = [];
      for (const f of [].concat(frames)) { onLandmarks(f); const ev = classifier.push(f); if (ev.length) { onEvents(ev, f); all.push(...ev); } }
      return all;
    },
  };
}
