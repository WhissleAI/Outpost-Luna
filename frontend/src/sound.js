// Sound cues and the guide's voice. The guide and the crew take turns; nothing here mixes speech under crew audio.

let ctx = null;
function ac() {
  if (!ctx) { const C = window.AudioContext || window.webkitAudioContext; if (!C) return null; ctx = new C(); }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

/** Soft scene-change chime: two sine partials (G5 + D6), 6 ms attack, ~250 ms decay. */
export function chime() {
  const a = ac(); if (!a) return;
  const t = a.currentTime + 0.01, out = a.createGain();
  out.gain.value = 0.12; out.connect(a.destination);
  [[783.99, 1], [1174.66, 0.55]].forEach(([hz, amp]) => {
    const o = a.createOscillator(), g = a.createGain();
    o.type = "sine"; o.frequency.value = hz;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(amp, t + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    o.connect(g).connect(out); o.start(t); o.stop(t + 0.27);
  });
}

/** Smoothly move an <audio> element's volume to `to` over `ms`. */
export function fadeTo(el, to, ms = 180) {
  return new Promise(res => {
    const from = el.volume, t0 = performance.now();
    if (el._fade) cancelAnimationFrame(el._fade);
    const step = now => {
      const k = Math.min(1, (now - t0) / ms);
      el.volume = Math.max(0, Math.min(1, from + (to - from) * k));
      if (k < 1) el._fade = requestAnimationFrame(step); else { el._fade = null; res(); }
    };
    el._fade = requestAnimationFrame(step);
  });
}

const synth = window.speechSynthesis || null;
export const ttsAvailable = !!synth;
export const tts = { on: true };
let seq = 0;

function pickVoice() {
  const v = synth ? synth.getVoices() : [];
  return v.find(x => /Samantha|Google US English|Karen|Moira/.test(x.name)) || v.find(x => x.lang && x.lang.startsWith("en"));
}

/** The voice a piece of hardware tells its own story in: a little slower and higher than the guide. */
export const STORY_VOICE = { rate: 0.92, pitch: 1.4 };

/** Speak and resolve when done (or cancelled). Resolves immediately when read-aloud is off. */
export function speak(text, { rate = 0.98, pitch = 1.08 } = {}) {
  const my = ++seq;
  if (!synth || !tts.on || !text) return Promise.resolve(false);
  synth.cancel();
  return new Promise(res => {
    const u = new SpeechSynthesisUtterance(text); const v = pickVoice(); if (v) u.voice = v;
    u.rate = rate; u.pitch = pitch;
    let done = false; const fin = ok => { if (!done) { done = true; clearTimeout(cap); res(ok && my === seq); } };
    u.onend = () => fin(true); u.onerror = () => fin(false);
    // Safety net: Chrome sometimes never fires onend.
    const cap = setTimeout(() => fin(true), 1500 + text.split(/\s+/).length * 450);
    synth.speak(u);
  });
}
export function stopSpeaking() { seq++; if (synth) synth.cancel(); }
export function isSpeaking() { return !!(synth && (synth.speaking || synth.pending)); }
