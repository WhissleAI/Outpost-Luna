// Moon Moments: 8–25 s slices of crew audio about one place (REVAMP §3.3).
// Prefer GET /api/moments; until that ships, derive simple moments from /api/clips utterances.

const GLOSSARY = {
  albedo: "how bright or dark a surface is",
  ejecta: "rock thrown out when a crater was made",
  limb: "the edge of the Moon we can see",
  relief: "how high and low the ground is",
  mare: "a dark, flat plain made of old lava",
  maria: "dark, flat plains made of old lava",
  terminator: "the line between day and night",
  rays: "bright streaks splashed out from a crater",
  plateau: "a big high, flat area",
  basin: "a giant, very old crater",
  pyroclastic: "made by volcanoes spraying hot ash",
  regolith: "the Moon's dusty, rocky soil",
  rille: "a long, skinny valley",
  highlands: "the bright, bumpy, older parts of the Moon",
  pillowing: "soft-looking bumps, like pillows",
};
export const explainWord = w => GLOSSARY[(w || "").toLowerCase().replace(/[^a-z]/g, "")] || null;

const endsSentence = w => /[.?!]$/.test(w);

/** Sentence/utterance boundaries in a clip: list of end times (s), sorted. */
export function sentenceEnds(clip) {
  const W = clip.words, ends = new Set();
  (clip.utterances || []).forEach(([, e]) => { if (e > 0) ends.add(e - 1); });
  W.forEach(([, w], i) => { if (endsSentence(w)) ends.add(i); });
  W.forEach(([t], i) => { if (i + 1 < W.length && W[i + 1][0] - t > 1.2) ends.add(i); });
  ends.add(W.length - 1);
  return [...ends].sort((a, b) => a - b).map(i => wordEnd(clip, i));
}
export const wordEnd = (clip, i) => {
  const W = clip.words; return i + 1 < W.length ? Math.min(W[i][0] + 0.6, W[i + 1][0]) : Math.min(W[i][0] + 0.6, clip.dur);
};

/** Derive moments from a clip: the window around each place mention, snapped to sentence ends. */
export function deriveMoments(clip, placeName) {
  const W = clip.words; if (!W || !W.length) return [];
  const ends = new Set(); (clip.utterances || []).forEach(([, e]) => ends.add(e - 1));
  W.forEach(([, w], i) => { if (endsSentence(w)) ends.add(i); });
  const isEnd = i => ends.has(i) || i === W.length - 1;
  const out = [], used = new Set();
  clip.tags.filter(t => t.f).forEach(tg => {
    if (used.has(tg.f + ":" + Math.floor(W[tg.i][0] / 30))) return;
    used.add(tg.f + ":" + Math.floor(W[tg.i][0] / 30));
    // start: after the sentence end before the mention, at most ~8 s back
    let s = tg.i; while (s > 0 && !isEnd(s - 1) && W[tg.i][0] - W[s - 1][0] < 8) s--;
    // end: first sentence end ≥ 8 s after start, capped near 25 s
    let e = tg.i; const t0 = W[s][0];
    while (e < W.length - 1 && (!isEnd(e) || W[e][0] - t0 < 8) && W[e + 1][0] - t0 < 25) e++;
    const t1 = wordEnd(clip, e);
    const words = W.slice(s, e + 1);
    const jargon = [];
    clip.tags.forEach(j => {
      if (j.i < s || j.i > e) return;
      const word = W[j.i][1], ex = explainWord(j.label || word) || explainWord(word);
      if (ex && !jargon.some(x => x.word.toLowerCase() === word.toLowerCase().replace(/[^a-z]/gi, ""))) jargon.push({ t: W[j.i][0], word: word.replace(/[^a-z]/gi, ""), explain: ex });
    });
    words.forEach(([t, w]) => { const ex = explainWord(w); const k = w.replace(/[^a-z]/gi, "");
      if (ex && !jargon.some(x => x.word.toLowerCase() === k.toLowerCase())) jargon.push({ t, word: k, explain: ex }); });
    jargon.sort((a, b) => a.t - b.t);
    out.push({
      id: `d-${clip.id}-${tg.f}-${s}`, clip_id: clip.id, t0: Math.max(0, t0 - 0.2), t1,
      speaker: "crew", places: [tg.f], text: words.map(w => w[1]).join(" "),
      jargon, awe: clip.tags.some(a => a.type === "AWE" && a.i >= s && a.i <= e) ? 0.7 : 0.3,
      title: placeName ? placeName(tg.f) : tg.f, derived: true,
    });
  });
  return out;
}

const cache = {};
/** Moments for a place (or all when place is null). Server first, client-derived fallback. */
export async function getMoments(place, clips, placeName) {
  const key = place || "*"; if (cache[key]) return cache[key];
  let ms = null;
  try {
    const r = await fetch("/api/moments" + (place ? "?place=" + encodeURIComponent(place) : ""));
    if (r.ok) { const j = await r.json(); if (Array.isArray(j.moments)) ms = j.moments; }
  } catch (e) { /* fall through */ }
  if (!ms || (!ms.length && !place)) {
    ms = clips.flatMap(c => deriveMoments(c, placeName));
    if (place) ms = ms.filter(m => (m.places || []).some(p => (p.id || p) === place));
    ms.sort((a, b) => b.awe - a.awe);
  }
  return (cache[key] = ms.map(m => normMoment(m)));
}

/** Accept both the new moment shape and the REVAMP §3.3 draft (`clip` instead of `clip_id`, places as {id,conf}). */
export function normMoment(m) {
  if (!m) return null;
  return {
    ...m,
    clip_id: m.clip_id || m.clip,
    places: (m.places || []).map(p => (typeof p === "string" ? p : p.id)),
    jargon: (m.jargon || []).filter(j => j && j.explain).sort((a, b) => a.t - b.t),
    t0: +m.t0 || 0, t1: m.t1 != null ? +m.t1 : null,
  };
}
