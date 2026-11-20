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

/** When each chapter star lands (ms after the card opens): the same beat as cabin.css (.cb-ch-stars, --i). */
export const STAR_MS = [450, 900, 1350];
/** Notes of the chapter cue: one rising bell note per star earned, on the beat the star lands, then a soft chord when
 *  all three are in. Plain sine partials like chime(), Volume-scaled; Mute (levels().master 0) plays nothing. -> notes */
export function starCueNotes(n) {
  const k = Math.max(0, Math.min(3, n | 0)), hz = [659.25, 783.99, 987.77];
  const notes = Array.from({ length: k }, (_, i) => ({ at: STAR_MS[i] / 1000, hz: hz[i], amp: 1, len: 0.45 }));
  if (k === 3) notes.push({ at: STAR_MS[2] / 1000 + 0.32, hz: 1318.5, amp: 0.5, len: 0.9 }, { at: STAR_MS[2] / 1000 + 0.32, hz: 987.77, amp: 0.4, len: 0.9 });
  if (!k) notes.push({ at: 0.45, hz: 523.25, amp: 0.6, len: 0.4 });   // no star: one soft note, the moment still lands
  return notes;
}
export function starCue(n) {
  const L = (typeof window !== "undefined" && window.__outpost && window.__outpost.levels) || { master: 1 };
  if (!L.master) return [];
  const a = ac(); if (!a) return [];
  const t0 = a.currentTime + 0.01, out = a.createGain(); out.gain.value = 0.1 * L.master; out.connect(a.destination);
  const notes = starCueNotes(n);
  notes.forEach(({ at, hz, amp, len }) => {
    const o = a.createOscillator(), g = a.createGain(), t = t0 + at;
    o.type = "sine"; o.frequency.value = hz;
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(amp, t + 0.008); g.gain.exponentialRampToValueAtTime(0.0001, t + len);
    o.connect(g).connect(out); o.start(t); o.stop(t + len + 0.02);
  });
  return notes;
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
