// Moon Moment playback: one server moment (t0..t1 of a crew clip) with a karaoke caption, the globe following the
// places the crew names, PAUSE_EXPLAIN for hard words (at the next sentence end, max 1 per 30 s, none in the first
// 5 s), ducking while the kid talks, and a chime on every scene change.
import { chime, fadeTo } from "./sound.js";
import { floor, speak } from "./floor.js";
import { normMoment } from "./api.js";
import { toClipTime, toFileTime } from "./cliptime.js";   // trimmed desktop audio: clip time <-> <audio> time

const MAX_LINE = 14;   // words per karaoke line when the transcript has no punctuation

/** Split moment words [a, b] into caption lines: utterance ends, sentence punctuation, long pauses, ≤ MAX_LINE. */
function lines(clip, a, b) {
  const W = clip.words, ends = new Set();
  (clip.utterances || []).forEach(([, e]) => ends.add(e - 1));
  for (let i = a; i <= b; i++) {
    if (/[.?!]$/.test(W[i][1])) ends.add(i);
    if (i < b && W[i + 1][0] - W[i][0] > 1.2) ends.add(i);
  }
  const out = []; let s = a;
  for (let i = a; i <= b; i++) {
    if (ends.has(i) || i === b || i - s + 1 >= MAX_LINE) { out.push([s, i]); s = i + 1; }
  }
  return out;
}
const wordEnd = (clip, i) => { const W = clip.words; return i + 1 < W.length ? Math.min(W[i][0] + 0.6, W[i + 1][0]) : W[i][0] + 0.6; };

export function createPlayer({ api, globe, placeById, isKidTalking, onPlace, onEnd }) {
  const $ = id => document.getElementById(id);
  const bar = $("nowPlaying"), whoEl = $("npWho"), lineEl = $("npLine"), whereEl = $("npWhere");
  const audio = new Audio(); audio.preload = "none";
  let P = null;          // {m, clip, a, b, lines, ends, li, wi, j, pending, lastPause, explaining, follow, spans}
  let seq = 0;
  const clipTime = (p = P) => toClipTime(p && p.clip.segs, audio.currentTime);

  // The floor owns this element as the crew channel: it reads the moment text (echo check), pauses the crew at a
  // sentence end so the guide can speak (§3.1), and resumes it after.
  const momentText = () => P ? P.clip.words.slice(P.a, P.b + 1).map(w => w[1]).join(" ") : "";
  function pauseAtSentenceEnd() {
    if (!P || audio.paused) return Promise.resolve();
    const my = P, t = clipTime(my), at = Math.min(P.ends.find(e => e >= t) ?? P.t1, t + 8);
    return new Promise(res => {
      const iv = setInterval(async () => {
        if (P !== my || audio.paused) { clearInterval(iv); res(); return; }
        if (clipTime(my) >= at - 0.08) { clearInterval(iv); my.held = true; await fadeTo(audio, 0, 120); audio.pause(); res(); }
      }, 40);
    });
  }
  function resume() {
    if (!P || !P.held || P.explaining) return;
    P.held = false; audio.volume = 0; audio.play().catch(() => {}); fadeTo(audio, 1, 250);
  }
  if (floor) floor.attachCrew(audio, { text: momentText, pauseAtSentenceEnd, resume });

  // Crew loudness (docs/VOICES.md): each clip's gain_db brings it to our voices' level, a limiter stops peaks, then the
  // Settings master volume. Built on the first play (an AudioContext needs a gesture); without Web Audio it plays as is.
  let graph = null;
  function crewGraph() {
    if (graph !== null) return graph;
    try {
      const C = window.AudioContext || window.webkitAudioContext; if (!C) return (graph = false);
      const ctx = new C(), src = ctx.createMediaElementSource(audio), gain = ctx.createGain(), lim = ctx.createDynamicsCompressor(), master = ctx.createGain();
      lim.threshold.value = -1; lim.knee.value = 0; lim.ratio.value = 20; lim.attack.value = 0.003; lim.release.value = 0.05;
      src.connect(gain).connect(lim).connect(master).connect(ctx.destination);
      graph = { ctx, gain, master };
      const setMaster = () => { const L = window.__outpost && window.__outpost.levels; master.gain.value = L && isFinite(L.master) ? L.master : 1; };
      setMaster(); addEventListener("outpost:prefs", setMaster);
    } catch (e) { graph = false; }
    return graph;
  }
  function clipGain(clip) {
    const g = crewGraph(); if (!g) return;
    if (g.ctx.state === "suspended") g.ctx.resume().catch(() => {});
    const db = +(clip && clip.gain_db); g.gain.gain.value = isFinite(db) ? Math.pow(10, db / 20) : 1;
  }

  $("npStop").onclick = () => stop();
  bar.addEventListener("click", e => {
    if (!P || e.target.closest("#npStop") || !audio.paused || P.explaining) return;
    bar.classList.remove("is-blocked"); audio.play().catch(() => bar.classList.add("is-blocked"));
  });

  function seek(t, segs) {
    return new Promise(res => {
      const go = () => { audio.currentTime = toFileTime(segs, t); res(); };
      if (audio.readyState >= 1) return go();
      audio.addEventListener("loadedmetadata", go, { once: true }); audio.preload = "auto"; audio.load(); setTimeout(res, 4000);
    });
  }

  async function play(raw) {
    const m = normMoment(raw), my = ++seq;
    halt(true);
    let clip;
    try { clip = await api.clip(m.clip_id); } catch (e) { return false; }
    if (my !== seq) return false;
    const W = clip.words, t1 = m.t1 ?? clip.dur;
    let a = W.findIndex(w => w[0] >= m.t0 - 0.3); if (a < 0) a = 0;
    let b = a; while (b + 1 < W.length && W[b + 1][0] < t1) b++;
    const L = lines(clip, a, b);
    P = { m, clip, a, b, t1, lines: L, ends: L.map(([, e]) => wordEnd(clip, e)), li: -1, wi: -1, j: 0, pending: null, lastPause: -1e9, explaining: false, follow: null, spans: [] };
    const sp = String(m.speaker || "crew");
    whoEl.textContent = sp === "crew" ? "Artemis II crew" : /^\d+$/.test(sp) ? "Astronaut " + (+sp + 1) : sp;
    whereEl.textContent = ""; lineEl.textContent = "…"; lineEl.classList.remove("is-explain");
    bar.hidden = false;
    if (audio.src !== new URL(clip.file, location.href).href) audio.src = clip.file;
    const first = m.places.find(id => placeById(id));
    if (first) follow(first, false);
    chime();
    await seek(m.t0, clip.segs); if (my !== seq) return false;
    audio.volume = 1; clipGain(clip);
    try { await audio.play(); } catch (e) { bar.classList.add("is-blocked"); }   // autoplay blocked: tap the bar
    if (floor && P && P.m === m) floor.crewPlayback("start", m.clip_id);
    return true;
  }

  function follow(id, ring = true) {
    if (!P || P.follow === id) return;
    P.follow = id; const f = placeById(id);
    if (ring) chime();
    globe.showFeature(f); onPlace(f.id);
    whereEl.textContent = "→ " + f.name;
  }

  function renderLine(li) {
    const [s, e] = P.lines[li]; lineEl.textContent = ""; P.spans = [];
    for (let i = s; i <= e; i++) { const sp = document.createElement("span"); sp.textContent = P.clip.words[i][1]; P.spans.push(sp); lineEl.append(sp, " "); }
  }

  function onTime() {
    if (!P || P.explaining) return;
    const t = clipTime(), W = P.clip.words;
    if (t >= P.t1) { stop(false, true); return; }
    // karaoke: current word i, current line li
    let i = P.a; while (i < P.b && W[i + 1][0] <= t) i++;
    if (W[i][0] > t + 0.05) i = -1;
    if (i >= 0 && i !== P.wi) {
      P.wi = i;
      const li = P.lines.findIndex(([s, e]) => i >= s && i <= e);
      if (li !== P.li) { P.li = li; renderLine(li); }
      const s0 = P.lines[li][0];
      P.spans.forEach((sp, k) => { sp.className = k + s0 < i ? "past" : k + s0 === i ? "now" : ""; });
      // follow the crew: latest FEATURE tag at or before this word, inside the moment
      let ft = null; for (const tg of P.clip.tags) { if (tg.i > i) break; if (tg.i >= P.a && tg.f && placeById(tg.f)) ft = tg; }
      if (ft) follow(ft.f);
    }
    // PAUSE_EXPLAIN
    const m = P.m;
    if (!P.pending) {
      while (P.j < m.jargon.length && m.jargon[P.j].t <= t) {
        const jg = m.jargon[P.j++], at = P.ends.find(e => e >= jg.t + 0.05);
        if (at != null && at < P.t1 - 0.3) { P.pending = { jg, at }; break; }
      }
    }
    if (P.pending && t >= P.pending.at - 0.08) {
      const { jg } = P.pending; P.pending = null;
      if (t - m.t0 >= 5 && performance.now() - P.lastPause >= 30000 && !isKidTalking()) explain(jg);
    }
  }
  const timer = setInterval(onTime, 60);

  async function explain(jg) {
    const my = P; my.explaining = true; my.lastPause = performance.now();
    await fadeTo(audio, 0, 200); audio.pause();
    const w = jg.word.charAt(0).toUpperCase() + jg.word.slice(1);
    const ex = jg.explain.charAt(0).toLowerCase() + jg.explain.slice(1);
    const line = `${w} means ${ex.replace(/\.$/, "").split(/\s+/).slice(0, 12).join(" ")}.`;
    chime(); lineEl.textContent = line; lineEl.classList.add("is-explain"); my.li = -1;
    await speak(line, { rate: 0.9, pitch: 1.0 });
    if (P !== my) return;
    lineEl.classList.remove("is-explain"); my.explaining = false;
    if (isKidTalking()) return;      // the kid barged in: they get the floor
    chime(); audio.volume = 0; try { await audio.play(); } catch (e) { /* user can resume */ } fadeTo(audio, 1, 250);
  }

  /** End the moment (fade out). `quiet` skips the end callback (another moment or answer is taking over). */
  function stop(quiet, natural) { seq++; halt(quiet, natural); }
  function halt(quiet, natural) {
    const was = P; P = null; bar.hidden = true; bar.classList.remove("is-blocked");
    if (was && floor) floor.crewPlayback(natural ? "end" : "interrupted", was.m.clip_id);
    if (!audio.paused) fadeTo(audio, 0, 200).then(() => { audio.pause(); audio.volume = 1; });
    if (was && !quiet) onEnd();
  }

  audio.addEventListener("ended", () => { if (P) stop(false, true); });

  return {
    play, stop,
    get active() { return !!P; },
    /** context.playing for /api/ask */
    get playing() { return P && !audio.paused ? { clip_id: P.m.clip_id, t: +clipTime().toFixed(2) } : null; },
    /** Barge-in: crew to 15% (the floor tracks it, so unduck after a no-request turn restores it). */
    duck() { if (floor) floor.duck(0.15); else if (P && !audio.paused) fadeTo(audio, 0.15, 150); },
    unduck() { if (P && P.explaining) return; if (floor) floor.unduck(); else if (P && !audio.paused) fadeTo(audio, 1, 250); },
    dispose() { clearInterval(timer); },
  };
}
