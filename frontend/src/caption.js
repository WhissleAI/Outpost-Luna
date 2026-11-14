// Caption bar: every spoken line (guide, CAPCOM, story, Houston, and the crew audio) as text, with the word being
// spoken highlighted in sync with playback (docs/ACCESSIBILITY.md).
//
// Timing sources, best first:
//   1. Steer TTS word timings: /api/tts returns X-TTS-Words ("startMs-endMs,…" per display word), taken from Steer's
//      own duration predictor (model_server/app/tts_steer.py). floor.js passes them on its "sentence" event.
//   2. The browser voice: speechSynthesis "boundary" events (floor.js re-emits them as "boundary").
//   3. Deepgram / no timings: an estimate from the audio's duration, weighted by each word's syllables.
//   Crew audio: player.js already renders a karaoke line from the clip index's word timings (#npLine); we mirror it.
// Every caption also goes to a transcript (window.__outpost.transcript), which the a11y panel shows.

// ---------- pure helpers (tests/a11y.test.js) ----------

/** "0-320,320-610" → [[0, 0.32], [0.32, 0.61]] (seconds). Bad input → []. */
export function parseWords(header) {
  const h = String(header || "").trim();
  if (!/^\d+-\d+(,\d+-\d+)*$/.test(h)) return [];
  return h.split(",").map(p => p.split("-").map(x => +x / 1000));
}

/** Rough English syllable count (≥ 1): vowel groups, minus a silent final e; digits count per digit. */
export function syllables(word) {
  const w = String(word || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  if (!w) return 1;
  if (/^\d+$/.test(w)) return Math.max(1, w.length * 1.5);
  const groups = w.replace(/e$/, "").match(/[aeiouy]+/g);
  return Math.max(1, groups ? groups.length : 1);
}

/** Estimated [start, end] per word over `dur` seconds, by syllables, with a small pause after , . ! ? */
export function estimateWords(words, dur, lead = 0.05) {
  const w = (words || []).map(x => syllables(x) + (/[,;:]$/.test(x) ? 0.6 : /[.!?]$/.test(x) ? 1 : 0));
  const tot = w.reduce((a, b) => a + b, 0) || 1, span = Math.max(0, dur - lead * 2);
  let t = lead; return w.map(x => { const a = t; t += span * x / tot; return [a, t]; });
}

/** Index of the word being spoken at time t (the last word that has started), or -1 before the first. */
export function wordAt(times, t) {
  let k = -1;
  for (let i = 0; i < times.length; i++) { if (times[i][0] <= t + 0.02) k = i; else break; }
  return k;
}

/** Break words into lines of at most `max` characters (the reading-support line-length limit). */
export function wrapLines(words, max = 42) {
  const out = []; let cur = [], len = 0;
  (words || []).forEach((w, i) => {
    if (cur.length && len + 1 + w.length > max) { out.push(cur); cur = []; len = 0; }
    cur.push(i); len += (len ? 1 : 0) + w.length;
  });
  if (cur.length) out.push(cur);
  return out;
}

/** Character offset → word index (for speechSynthesis boundary events). */
export function wordAtChar(words, charIndex) {
  let pos = 0;
  for (let i = 0; i < words.length; i++) { if (charIndex < pos + words[i].length + 1) return i; pos += words[i].length + 1; }
  return words.length - 1;
}

const WHO = { guide: "Guide", capcom: "CAPCOM", story: "Hardware", houston: "Houston", crew: "Artemis II crew" };

// ---------- DOM ----------

export function initCaptions({ floor, settings = () => ({}) } = {}) {
  if (typeof document === "undefined" || !floor) return null;
  const O = (window.__outpost = window.__outpost || { stepRenderers: {} });
  O.transcript = O.transcript || [];
  let bar = document.getElementById("captionBar");
  if (!bar) {                       // the layout agent adds #captionBar; until then, our own (fixed, above the dock)
    bar = document.createElement("div"); bar.id = "captionBar"; bar.className = "caption-bar is-own";
    const dock = document.getElementById("askbar");
    if (dock) dock.prepend(bar); else document.body.append(bar);
  }
  bar.classList.add("caption-bar");
  bar.setAttribute("role", "region"); bar.setAttribute("aria-label", "Captions");
  bar.innerHTML = `<span class="cap-who" aria-hidden="true"></span><p class="cap-line"></p><span class="cap-speed" aria-hidden="true"></span>`;
  const whoEl = bar.querySelector(".cap-who"), lineEl = bar.querySelector(".cap-line"), spEl = bar.querySelector(".cap-speed");
  bar.hidden = true;

  let cur = null;   // {id, words, times, spans, audio, mode: "timed"|"estimate"|"boundary", k}
  let raf = 0, hideT = 0;

  function log(who, text) {
    const e = { who, text, t: Date.now() };
    O.transcript.push(e); if (O.transcript.length > 200) O.transcript.shift();
    window.dispatchEvent(new CustomEvent("outpost:transcript", { detail: e }));
  }

  function render(words, who) {
    clearTimeout(hideT);
    const max = settings().captionChars || 42;
    lineEl.textContent = ""; const spans = [];
    wrapLines(words, max).slice(0, 4).forEach(line => {
      const row = document.createElement("span"); row.className = "cap-row";
      line.forEach(i => { const s = document.createElement("span"); s.className = "cap-w"; s.textContent = words[i]; spans[i] = s; row.append(s, " "); });
      lineEl.append(row);
    });
    whoEl.textContent = WHO[who] || who || "";
    bar.dataset.who = who || "";
    bar.hidden = false;
    if (O.highlight && O.highlight.markCaption) O.highlight.markCaption(spans, words);
    return spans;
  }
  function paint(k) {
    if (!cur || k === cur.k) return;
    cur.k = k;
    cur.spans.forEach((s, i) => { if (s) s.className = s.className.replace(/\b(now|past)\b/g, "").trim() + (i < k ? " past" : i === k ? " now" : ""); });
  }
  function tick() {
    raf = 0;
    if (!cur || !cur.audio) return;
    const a = cur.audio;
    if (cur.mode === "estimate" && !cur.times.length && isFinite(a.duration) && a.duration > 0) cur.times = estimateWords(cur.words, a.duration);
    if (cur.times.length) paint(wordAt(cur.times, a.currentTime));
    // keep going while it plays, or while it is still loading (paused at 0); stop when stopped or ended
    if (!a.ended && (!a.paused || a.currentTime === 0)) raf = requestAnimationFrame(tick);
  }

  floor.on("sentence", e => {
    const words = String(e.text || "").split(/\s+/).filter(Boolean);
    const times = parseWords(e.words);
    cur = { id: e.id, words, times: times.length === words.length ? times : [], audio: e.audio, k: -2,
      mode: e.audio ? (times.length === words.length ? "timed" : "estimate") : "boundary" };
    cur.spans = render(words, e.voice);
    bar.dataset.timing = cur.mode;           // "timed" = Steer's own word timings
    spEl.textContent = e.speed && e.speed !== 1 ? e.speed + "×" : "";
    log(e.voice, e.text);
    cancelAnimationFrame(raf); raf = 0;
    if (e.audio) {
      const start = () => { if (!raf) raf = requestAnimationFrame(tick); };
      e.audio.addEventListener("playing", start, { once: true }); start();
    } else paint(0);
  });
  floor.on("boundary", e => { if (cur && cur.mode === "boundary") paint(wordAtChar(cur.words, e.charIndex)); });
  floor.on("playback", e => {
    if (e.state !== "start") { hideT = setTimeout(() => { if (!floor.guideBusy && !crewOn) bar.hidden = true; }, 2500); if (e.kind === "guide") { if (cur) paint(cur.words.length); } }
  });

  // ---- crew audio: mirror player.js's karaoke line (#npLine) ----
  let crewOn = false, lastCrew = "";
  const np = document.getElementById("npLine");
  if (np && typeof MutationObserver !== "undefined") {
    const mirror = () => {
      const sp = [...np.querySelectorAll("span")];
      if (!sp.length) return;
      const words = sp.map(s => s.textContent), text = words.join(" ");
      crewOn = true; clearTimeout(hideT);
      if (text !== lastCrew) {
        lastCrew = text; cur = { id: "crew", words, times: [], audio: null, mode: "crew", k: -2 };
        cur.spans = render(words, "crew"); bar.dataset.timing = "crew"; log("crew", text);
      }
      const k = sp.findIndex(s => s.classList.contains("now"));
      if (cur && cur.id === "crew") { cur.k = -2; paint(k); }
    };
    new MutationObserver(mirror).observe(np, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
    floor.on("playback", e => { if (e.kind === "crew" && e.state !== "start") { crewOn = false; lastCrew = ""; } });
  }

  // Keyboard: Escape hides the bar until the next line.
  bar.addEventListener("keydown", e => { if (e.key === "Escape") bar.hidden = true; });
  O.captions = { bar, log, get current() { return cur; } };
  return O.captions;
}
