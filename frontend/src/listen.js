// Live mic over WS /ws/listen: mic → AudioWorklet → 16 kHz PCM16 mono, 80 ms frames → server.
// The worklet runs at the AudioContext's real rate (`sampleRate`, often 48 kHz or 44.1 kHz) and resamples by linear
// interpolation, carrying the last sample across 128-frame blocks so non-integer ratios (44.1k) don't drift.
// echoCancellation / noiseSuppression / autoGainControl stay on: the guide now plays as in-page audio (floor.js),
// which the echo canceller can subtract. on.level(rms 0..1) reports the mic level per 80 ms frame (the meter).
// Server → {t:"ready"|"words"|"turn"|"arc"|"emotion"|"error"}. Resolves start() false when the socket can't open,
// so the caller can fall back to Web Speech.

export const WORKLET = `
class Pcm16 extends AudioWorkletProcessor {
  constructor(){ super(); this.ratio = sampleRate / 16000; this.pos = 0; this.last = 0; this.buf = new Int16Array(1280); this.n = 0; }
  process(inputs){
    const ch = inputs[0] && inputs[0][0]; if (!ch) return true;
    // linear-interpolation resample to 16 kHz; index -1 is the previous block's last sample
    const L = ch.length;
    while (this.pos < L - 1) {
      const i = Math.floor(this.pos), f = this.pos - i, a = i < 0 ? this.last : ch[i], s = a * (1 - f) + ch[i + 1] * f;
      const v = Math.max(-1, Math.min(1, s)); this.buf[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.buffer, [this.buf.buffer]); this.buf = new Int16Array(1280); this.n = 0; }
      this.pos += this.ratio;
    }
    this.pos -= L; this.last = ch[L - 1];
    return true;
  }
}
registerProcessor("pcm16-80ms", Pcm16);`;

/** The worklet's same-origin URL: the desktop CSP (script-src 'self') blocks blob: worklets, which made a working mic
 *  fail with "Another app is using the mic" (AbortError from addModule). */
export const WORKLET_PATH = "/pcm16_worklet.js";   // frontend/public/: copied as-is (Vite would inline a small src/ file as a data: URL, which the CSP also blocks)
const workletUrl = () => (typeof location !== "undefined" ? new URL(WORKLET_PATH, location.href).href : WORKLET_PATH);
/** Load the PCM16 worklet: the same-origin file first, a blob of the same code as a fallback (a page without a CSP). */
export async function loadPcmWorklet(ctx) {
  try { await ctx.audioWorklet.addModule(workletUrl()); return "file"; }
  catch (e) {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    try { await ctx.audioWorklet.addModule(url); return "blob"; }
    catch (e2) { const err = new Error("The mic's audio worklet failed to load"); err.name = "WorkletError"; throw err; }
    finally { URL.revokeObjectURL(url); }
  }
}

export function createListener(on) {
  let ws = null, ctx = null, stream = null, node = null, src = null, live = false;
  let sent = 0;            // 16 kHz samples sent on this socket: the mic stream's clock (echoref.js stamps playback with it)

  function wsUrl() { return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/listen"; }

  async function start() {
    // 1) socket first: no mic prompt if the server side isn't there yet
    const ok = await new Promise(res => {
      let settled = false; const done = v => { if (!settled) { settled = true; clearTimeout(to); res(v); } };
      try { ws = new WebSocket(wsUrl()); } catch (e) { return res(false); }
      ws.binaryType = "arraybuffer"; sent = 0;
      const to = setTimeout(() => done(false), 2500);
      ws.onopen = () => done(true);
      ws.onerror = () => done(false);
      ws.onclose = () => { done(false); if (live) { live = false; cleanup(); on.close && on.close(); } };
      ws.onmessage = e => { if (typeof e.data !== "string") return; let m; try { m = JSON.parse(e.data); } catch (_) { return; } on.message && on.message(m); };
    });
    if (!ok) { try { ws && ws.close(); } catch (e) {} ws = null; return false; }
    // 2) mic + worklet
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === "suspended") ctx.resume().catch(() => {});
      await loadPcmWorklet(ctx);
      src = ctx.createMediaStreamSource(stream);
      node = new AudioWorkletNode(ctx, "pcm16-80ms");
      node.port.onmessage = e => {
        if (ws && ws.readyState === 1) { ws.send(e.data); sent += e.data.byteLength / 2; }
        if (on.level) { const a = new Int16Array(e.data); let sum = 0; for (let k = 0; k < a.length; k += 4) sum += a[k] * a[k]; on.level(Math.sqrt(sum / (a.length / 4)) / 32768); }
      };
      const mute = ctx.createGain(); mute.gain.value = 0;
      src.connect(node).connect(mute).connect(ctx.destination);
      live = true; return true;
    } catch (e) {
      try { ws.close(); } catch (_) {} ws = null; cleanup();
      on.micError && on.micError(e); return "mic";
    }
  }

  function cleanup() {
    try { src && src.disconnect(); node && node.disconnect(); } catch (e) {}
    if (stream) stream.getTracks().forEach(t => t.stop());
    if (ctx) ctx.close().catch(() => {});
    src = node = stream = ctx = null;
  }

  function stop() {
    live = false;
    if (ws && ws.readyState === 1) { try { ws.send(JSON.stringify({ t: "stop" })); } catch (e) {} }
    const w = ws; ws = null; setTimeout(() => { try { w && w.close(); } catch (e) {} }, 400);
    cleanup();
  }

  /** Send a JSON control frame (e.g. {t:"context",…}) when the socket is open. Returns whether it was sent. */
  function send(obj) { if (!ws || ws.readyState !== 1) return false; try { ws.send(JSON.stringify(obj)); return true; } catch (e) { return false; } }

  /** Seconds of mic audio sent on this socket (the ear's own clock for this stream). */
  const clock = () => sent / 16000;

  return { start, stop, send, clock, get live() { return live; }, get sampleRate() { return ctx ? ctx.sampleRate : 0; } };
}
