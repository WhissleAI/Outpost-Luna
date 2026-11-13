// Live mic over WS /ws/listen: mic → AudioWorklet → 16 kHz PCM16 mono, 80 ms frames → server.
// Server → {t:"ready"|"words"|"turn"|"arc"|"emotion"|"error"}. Resolves start() false when the socket can't open,
// so the caller can fall back to Web Speech.

const WORKLET = `
class Pcm16 extends AudioWorkletProcessor {
  constructor(){ super(); this.ratio = sampleRate / 16000; this.pos = 0; this.buf = new Int16Array(1280); this.n = 0; }
  process(inputs){
    const ch = inputs[0] && inputs[0][0]; if (!ch) return true;
    // linear-interpolation resample to 16 kHz
    while (this.pos < ch.length - 1) {
      const i = Math.floor(this.pos), f = this.pos - i, s = ch[i] * (1 - f) + ch[i + 1] * f;
      const v = Math.max(-1, Math.min(1, s)); this.buf[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      if (this.n === this.buf.length) { this.port.postMessage(this.buf.buffer, [this.buf.buffer]); this.buf = new Int16Array(1280); this.n = 0; }
      this.pos += this.ratio;
    }
    this.pos -= ch.length; if (this.pos < 0) this.pos = 0;
    return true;
  }
}
registerProcessor("pcm16-80ms", Pcm16);`;

export function createListener(on) {
  let ws = null, ctx = null, stream = null, node = null, src = null, live = false;

  function wsUrl() { return (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/listen"; }

  async function start() {
    // 1) socket first: no mic prompt if the server side isn't there yet
    const ok = await new Promise(res => {
      let settled = false; const done = v => { if (!settled) { settled = true; clearTimeout(to); res(v); } };
      try { ws = new WebSocket(wsUrl()); } catch (e) { return res(false); }
      ws.binaryType = "arraybuffer";
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
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await ctx.audioWorklet.addModule(url); URL.revokeObjectURL(url);
      src = ctx.createMediaStreamSource(stream);
      node = new AudioWorkletNode(ctx, "pcm16-80ms");
      node.port.onmessage = e => { if (ws && ws.readyState === 1) ws.send(e.data); };
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

  return { start, stop, send, get live() { return live; } };
}
