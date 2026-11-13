// Moon Moment playback: one server moment (t0..t1 of a crew clip) with a karaoke caption, the globe following the
// places the crew names, PAUSE_EXPLAIN for hard words (at the next sentence end, max 1 per 30 s, none in the first
// 5 s), ducking while the kid talks, and a chime on every scene change.
import { chime, fadeTo, speak } from "./sound.js";
import { normMoment } from "./api.js";

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

  $("npStop").onclick = () => stop();

  function seek(t) {
    return new Promise(res => {
      const go = () => { audio.currentTime = t; res(); };
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
    whoEl.textContent = m.speaker && m.speaker !== "crew" ? m.speaker : "Artemis II crew";
    whereEl.textContent = ""; lineEl.textContent = "…"; lineEl.classList.remove("is-explain");
    bar.hidden = false;
    if (audio.src !== new URL(clip.file, location.href).href) audio.src = clip.file;
    const first = m.places.find(id => placeById(id));
    if (first) follow(first, false);
    chime();
    await seek(m.t0); if (my !== seq) return false;
    audio.volume = 1;
    try { await audio.play(); } catch (e) { lineEl.textContent = "Tap ▶ to listen"; }
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
    const t = audio.currentTime, W = P.clip.words;
    if (t >= P.t1) { stop(); return; }
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
    const line = `${w} means ${jg.explain.replace(/\.$/, "").split(/\s+/).slice(0, 12).join(" ")}.`;
    chime(); lineEl.textContent = line; lineEl.classList.add("is-explain"); my.li = -1;
    await speak(line, { rate: 0.9, pitch: 1.0 });
    if (P !== my) return;
    lineEl.classList.remove("is-explain"); my.explaining = false;
    if (isKidTalking()) return;      // the kid barged in: they get the floor
    chime(); audio.volume = 0; try { await audio.play(); } catch (e) { /* user can resume */ } fadeTo(audio, 1, 250);
  }

  /** End the moment (fade out). `quiet` skips the end callback (another moment or answer is taking over). */
  function stop(quiet) { seq++; halt(quiet); }
  function halt(quiet) {
    const was = P; P = null; bar.hidden = true;
    if (!audio.paused) fadeTo(audio, 0, 200).then(() => { audio.pause(); audio.volume = 1; });
    if (was && !quiet) onEnd();
  }

  audio.addEventListener("ended", () => { if (P) stop(); });

  return {
    play, stop,
    get active() { return !!P; },
    /** context.playing for /api/ask */
    get playing() { return P && !audio.paused ? { clip_id: P.m.clip_id, t: +audio.currentTime.toFixed(2) } : null; },
    duck() { if (P && !audio.paused) fadeTo(audio, 0.2, 150); },
    unduck() { if (P && !audio.paused && !P.explaining) fadeTo(audio, 1, 250); },
    dispose() { clearInterval(timer); },
  };
}
