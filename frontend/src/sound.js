// Sound cues: the chime (the floor's effects channel) and volume fades. No speech here; see floor.js.

let ctx = null;
function ac() {
  if (!ctx) { const C = window.AudioContext || window.webkitAudioContext; if (!C) return null; ctx = new C(); }
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx;
}

/** Soft scene-change chime (`alarm`: an alert, scaled by Settings → Alarms too): two sine partials (G5 + D6), 6 ms attack, ~250 ms decay. */
export function chime(alarm = false) {
  const a = ac(); if (!a) return;
  const t = a.currentTime + 0.01, out = a.createGain();
  const L = (typeof window !== "undefined" && window.__outpost && window.__outpost.levels) || { master: 1, alarms: 1 };   // Settings → Sound
  // [qa] Sound → Alarms scales only the alarm chimes (chime(true)); place and tour chimes follow Volume alone
  out.gain.value = 0.12 * L.master * (alarm ? L.alarms : 1); out.connect(a.destination);
  [[783.99, 1], [1174.66, 0.55]].forEach(([hz, amp]) => {
    const o = a.createOscillator(), g = a.createGain();
    o.type = "sine"; o.frequency.value = hz;
    g.gain.setValueAtTime(0, t);
    g.gain.linearRampToValueAtTime(amp, t + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.25);
    o.connect(g).connect(out); o.start(t); o.stop(t + 0.27);
  });
}

/** A soft haptic-like tick (gestures: grab = a low "tock", release = a higher "tick"). ~40 ms, quiet, Volume-scaled. */
export function tick(kind = "grab") {
  const a = ac(); if (!a) return;
  const L = (typeof window !== "undefined" && window.__outpost && window.__outpost.levels) || { master: 1 };
  if (!L.master) return;   // Mute
  const t = a.currentTime + 0.005, o = a.createOscillator(), g = a.createGain();
  const [f0, f1] = kind === "release" ? [1250, 900] : [520, 330];
  o.type = "triangle"; o.frequency.setValueAtTime(f0, t); o.frequency.exponentialRampToValueAtTime(f1, t + 0.04);
  g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.07 * L.master, t + 0.003); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.045);
  o.connect(g).connect(a.destination); o.start(t); o.stop(t + 0.05);
}
/** A short radio squelch + beep before CAPCOM relays Houston (Mute: levels().master is 0, so nothing plays). */
export function radioBeep() {
  const a = ac(); if (!a) return;
  const L = (typeof window !== "undefined" && window.__outpost && window.__outpost.levels) || { master: 1 };
  if (!L.master) return;
  const t = a.currentTime + 0.01, out = a.createGain(); out.gain.value = 0.08 * L.master; out.connect(a.destination);
  // 120 ms of band-passed noise (the squelch), then a 1.4 kHz beep
  const n = Math.floor(a.sampleRate * 0.12), buf = a.createBuffer(1, n, a.sampleRate), d = buf.getChannelData(0);
  for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n);
  const src = a.createBufferSource(), bp = a.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = 1800; bp.Q.value = 0.8;
  src.buffer = buf; src.connect(bp).connect(out); src.start(t);
  const o = a.createOscillator(), g = a.createGain(); o.type = "sine"; o.frequency.value = 1400;
  g.gain.setValueAtTime(0, t + 0.13); g.gain.linearRampToValueAtTime(0.6, t + 0.14); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.26);
  o.connect(g).connect(out); o.start(t + 0.13); o.stop(t + 0.28);
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

// The guide's voice moved to floor.js (server TTS as in-page audio, speechSynthesis fallback): speak, stopSpeaking,
// isSpeaking and STORY_VOICE are exported from there.
