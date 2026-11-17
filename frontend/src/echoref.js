// Echo reference: what the app plays, sent to the ear so it can tell our own voice from the kid's (libarc ABI 2,
// arc_nft2_stream_feed_ref; model_server/app/arc_ear.py feed_ref; docs/ARC_ABI2.md "Echo reference").
//
// The ear needs the played audio as 16 kHz mono PCM, stamped with the MICROPHONE stream's clock: seconds of audio the
// mic socket has sent (listen.js counts its 80 ms frames). The canceller learns an echo path up to 512 ms long, so the
// stamp only has to be no later than the echo: we stamp "now" on the mic clock when a sound starts (the mic frames
// already counted lag the real mic by up to one frame, and the speaker adds its own output latency, so the echo always
// arrives after the stamp).
//
// Sources:
//   - the guide channel (OS voice, the Nora voice pack, Steer): floor.js holds each sentence's WAV blob; fromBlob()
//     decodes it at 16 kHz (OfflineAudioContext, no device) when it starts playing;
//   - crew clips: player.js routes them through Web Audio; tapNode() adds a capture worklet at the end of that graph
//     and streams what really goes to the speaker, 80 ms at a time.
// Not covered: NASA videos (a <video> element with no Web Audio graph), YouTube (an iframe), the browser-voice
// fallback (speechSynthesis) and UI beeps. Muted playback sends nothing (nothing reaches the mic).

import { WORKLET } from "./listen.js";

const SR = 16000;
const MAX_S = 10;              // one message: at most 10 s (the relay takes up to 12)
let sink = null;               // {send(obj) -> bool, clock() -> seconds of mic audio sent}

/** voice.js binds the live mic listener here (null when the mic is off: nothing to align to). */
export function bind(listener) { sink = listener && typeof listener.send === "function" ? listener : null; }
export const bound = () => !!(sink && sink.live !== false && typeof sink.clock === "function");

function b64(int16) {
  const u8 = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return typeof btoa === "function" ? btoa(s) : Buffer.from(s, "binary").toString("base64");
}

export function toPcm16(f32) {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) { const v = Math.max(-1, Math.min(1, f32[i])); out[i] = v < 0 ? v * 0x8000 : v * 0x7fff; }
  return out;
}

/** Send float samples (16 kHz mono) that start playing at mic time `at` (seconds; null: right after the last one). */
export function sendSamples(f32, at = null) {
  if (!bound() || !f32 || !f32.length) return 0;
  let sent = 0;
  for (let i = 0; i < f32.length; i += SR * MAX_S) {
    const part = f32.subarray(i, Math.min(f32.length, i + SR * MAX_S));
    const ok = sink.send({ t: "ref", at: i === 0 && at != null ? +at.toFixed(3) : null, pcm: b64(toPcm16(part)) });
    if (!ok) break;
    sent += part.length;
  }
  return sent;
}

/** A sentence's audio blob that has just started playing, `playedS` seconds in (its currentTime). */
export async function fromBlob(blob, playedS = 0, muted = false) {
  if (muted || !bound() || !blob || typeof blob.arrayBuffer !== "function") return 0;
  const at = sink.clock() - Math.max(0, playedS || 0);
  const OAC = typeof OfflineAudioContext !== "undefined" ? OfflineAudioContext : null;
  if (!OAC) return 0;
  try {
    const buf = await new OAC(1, SR, SR).decodeAudioData(await blob.arrayBuffer());
    return sendSamples(buf.getChannelData(0), at);
  } catch (e) { return 0; }
}

/** Tap a Web Audio node (the crew graph's output): what it plays goes to the ear as it plays. Returns an off(). */
export async function tapNode(ctx, node) {
  try {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await ctx.audioWorklet.addModule(url); URL.revokeObjectURL(url);
    const cap = new AudioWorkletNode(ctx, "pcm16-80ms");
    const silent = ctx.createGain(); silent.gain.value = 0;
    let quiet = 0;
    cap.port.onmessage = e => {
      if (!bound()) return;
      const a = new Int16Array(e.data);
      let peak = 0; for (let k = 0; k < a.length; k += 8) peak = Math.max(peak, Math.abs(a[k]));
      if (peak < 8) { quiet++; if (quiet > 2) return; } else quiet = 0;   // paused / silent: send nothing
      const f = new Float32Array(a.length); for (let k = 0; k < a.length; k++) f[k] = a[k] / 32768;
      sendSamples(f, sink.clock() - a.length / SR);   // these 80 ms just left the graph
    };
    node.connect(cap).connect(silent).connect(ctx.destination);
    return () => { try { node.disconnect(cap); cap.disconnect(); } catch (e) {} };
  } catch (e) { return () => {}; }
}
