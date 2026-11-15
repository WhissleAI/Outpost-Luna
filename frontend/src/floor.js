// Floor manager: the one owner of every sound the app makes (docs/SESSION_CONTRACT.md §3 rules 1, 3, 5 and §4).
//
// Channels
//   guide    server speech, GET /api/tts?text=…&voice=guide|capcom|story|houston&style=…, one sentence at a time with
//            the next one prefetched. `style` is the Director's say.style (Steer TTS steering, docs/VOICE_STEERING.md);
//            each sentence also sends i/n/next so Steer's performance director plans it in context. The URL (and so the
//            browser and server caches) includes the style.
//            prefetched, played as an in-page <audio> so the browser's echo canceller removes it from the mic.
//            Fallback (no key / offline / 5xx): speechSynthesis, sentence by sentence, never cancel() right before
//            speak() (≥ 60 ms gap), with a keep-alive so Chrome doesn't cut long utterances at ~15 s.
//   crew     the crew-audio <audio> element owned by player.js (attachCrew).
//   effects  the chime (sound.js). Not a floor holder.
//
// Event bus
//   floor.on(event, fn) → off()            floor.off(event, fn)
//   "floor"     {holder: "kid"|"guide"|"crew"|"none"}                                   on every change
//   "playback"  {kind: "guide"|"crew", state: "start"|"end"|"interrupted", id, t}       t = Date.now() (ms)
//   "sentence"  {id, index, text, voice}                                                each guide sentence as it starts
// The session Director forwards "playback" (and "floor") on WS /ws/session as {t:"playback", …}.
//
// Control
//   say(text, {voice, priority, id, style}) → Promise<boolean>   true when spoken to the end
//       priority (0 highest, §3.6): ≤ 2 waits for the current guide sentence to end, then takes over;
//       3 replaces the current guide speech now; ≥ 4 (proactive) waits until the floor is "none" (§3.5).
//       Every say waits while the kid holds the floor (§3.3); with crew audio playing it waits for the crew's
//       sentence end, pauses the crew, speaks, and resumes the crew (§3.1).
//   stopGuide()          stop the guide now (barge-in, < 200 ms): the current sentence and anything queued
//   duck(level) / unduck()   crew volume (barge-in ducks to 0.15)
//   setKid(on)           the kid takes / releases the floor (voice.js)
//   attachCrew(el, {text, pauseAtSentenceEnd, resume})   player.js registers its element and hooks
//   crewPlayback(state, id)   player.js reports crew start / end / interrupted
//   holder, guideBusy, guideText, guideSentence, crewText   (the echo check reads the last three)
import { fadeTo } from "./sound.js";

// ---------- pure helpers (unit-tested in tests/floor.test.js) ----------

/** Split text into speakable sentences of at most `max` chars (long ones break at commas, then spaces). */
export function splitSentences(text, max = 280) {
  const t = String(text || "").replace(/\s+/g, " ").trim();
  if (!t) return [];
  const raw = t.split(/(?<=[.!?…]["'”’)\]]?)\s+(?=["'“‘(\[]?[A-Z0-9])/);
  const out = [];
  for (const s of raw) {
    if (s.length <= max) { out.push(s); continue; }
    let rest = s;
    while (rest.length > max) {
      let cut = rest.lastIndexOf(", ", max); if (cut < max * 0.4) cut = rest.lastIndexOf(" ", max);
      if (cut <= 0) cut = max;
      out.push(rest.slice(0, cut + (rest[cut] === "," ? 1 : 0)).trim()); rest = rest.slice(cut + 1).trim();
    }
    if (rest) out.push(rest);
  }
  // fold tiny fragments ("Wow!") into the next sentence: fewer round trips, same sound
  const merged = [];
  for (const s of out) {
    const prev = merged[merged.length - 1];
    if (prev && prev.length < 20 && prev.length + 1 + s.length <= max) merged[merged.length - 1] = prev + " " + s;
    else merged.push(s);
  }
  return merged;
}

/** A say's sentences: one text, or a list of lines spoken as one (each line split on its own). */
export function sayLines(text) {
  return (Array.isArray(text) ? text : [text]).flatMap(t => splitSentences(t));
}

/** Lowercase words without punctuation ("Shields, to 40!" → ["shields","to","40"]). */
export function normWords(text) {
  return String(text || "").toLowerCase().replace(/[’']/g, "").replace(/[^\p{L}\p{N}]+/gu, " ").trim().split(" ").filter(Boolean);
}

/** The heard words are an echo of what we're playing when ≥ 60% of them appear in any of the reference texts. */
export function isEcho(heard, refs, threshold = 0.6) {
  const w = normWords(heard);
  if (!w.length) return true;
  const ref = new Set(); (refs || []).forEach(r => normWords(r).forEach(x => ref.add(x)));
  if (!ref.size) return false;
  const hits = w.filter(x => ref.has(x)).length;
  return hits / w.length >= threshold;
}

// Mirrors backend/app/turn_router.py nav_intent + answers_offer: the words that take a pending spoken offer (the screen
// frame's `offer`). "next" / "start" / "yes" take any offer; the rest only their own.
const OFFER_YES = /^(?:yes|yeah|yep|yup|sure|ok|okay|alright|all right|lets do it|lets go|do it|go|go for it|yes please|ready|im ready|affirmative|roger|copy)$/;
const OFFER_NEXT = /^(?:next|next one|next please|next lesson|next step|go on|keep going|move on|whats next|okay next|ok next|carry on)$/;
const OFFER_START = /^(?:start|begin|lets start|start (?:the )?lesson|start learning|lets begin|start (?:flight school|the academy)|continue|resume)$/;
const OFFER_OWN = {
  mission: /^(?:(?:go to |open |start |begin )?(?:the )?(?:mission|missions|outpost|outpost luna)(?: mode)?|lets (?:go to|do) the mission|go on (?:a|the) mission|(?:ill |i will |let me )?(?:take command|take the command|start the shift|start (?:my |the )?(?:first )?shift|launch|start the mission|begin the mission|im ready to command))$/,
  take_command: /^(?:ill |i will |let me )?(?:take command|take the command|start the shift|start (?:my |the )?(?:first )?shift|launch|start the mission|begin the mission|im ready to command)$/,
  fly_again: /^(?:(?:fly|play|go) again|(?:fly|play) (?:it )?one more time|(?:restart|replay) (?:the )?mission|another (?:mission|shift|go)|new mission)$/,
};
/** The turn takes the pending offer ("Ready for the next lesson?" → "next", "yes"; "Fly again?" → "fly again"). */
export function takesOffer(text, offer) {
  if (!offer) return false;
  const q = normWords(text).join(" ").replace(/^(?:okay|ok|um|uh|so|hey|capcom|please) /, "").replace(/ (?:please|now|capcom)$/, "");
  if (!q) return false;
  return OFFER_YES.test(q) || OFFER_NEXT.test(q) || OFFER_START.test(q) || !!(OFFER_OWN[offer] && OFFER_OWN[offer].test(q));
}

/** A lesson or check-ride step is waiting for its answer (the screen frame). */
export const stepOpen = f => !!(f && (f.screen === "lesson" || f.screen === "ride") && f.step_type);

/**
 * The client's echo decision for a finished open-mic turn (mirrors turn_router.echo()). The reply the screen is
 * waiting for, a word that takes the pending offer or the answer to an open lesson / ride step, is an echo only when
 * one of our lines was on air at the turn start (`onAir`: playing, or started during the turn; no tail). Anything
 * else: an echo of the fresh lines (`refs`: on air + the last 3 s) or a near-verbatim repeat of an older one.
 * @param {{text:string, frame?:object, onAir:boolean, refs:string[], oldRefs?:string[]}} o
 */
export function turnIsEcho({ text, frame, onAir, refs, oldRefs = [] }) {
  const f = frame || {};
  if (!onAir && takesOffer(text, f.offer)) return false;
  if (stepOpen(f)) {
    // a step answer often repeats the prompt's words ("I heard you"); older lines are never used here
    const readback = f.step_type === "keywords" || f.step_type === "vocab_say";
    return onAir && isEcho(text, refs, readback ? 0.85 : 0.6);
  }
  return isEcho(text, refs) || (normWords(text).length >= 3 && isEcho(text, oldRefs, 0.85));
}

/**
 * Open-mic barge-in while audio plays (§3 rule 2): Flux StartOfTurn, ≥ 2 words, not an echo of the guide/crew
 * text, and Arc device_directed ≥ 0.5 when Arc sent one.
 */
/** Settings → Listening → "Ignore other voices" (mirrors the server's filter levels): [ignore below, needed during speech]. */
export const BARGE = { relaxed: [0.35, 0.55], normal: [0.5, 0.7], strict: [0.65, 0.85] };
function bargeThresholds() {
  const f = typeof window !== "undefined" && window.__outpost && window.__outpost.prefs && window.__outpost.prefs.filter;
  return BARGE[f] || BARGE.normal;
}
/** The kid's voice prefs on a line the client speaks itself (Academy replies, the badge, a11y): the chosen Steer voice
 *  (for the guide, or every voice when "use for everyone" is on), the speed and the liveliness. */
export function prefStyle(style, voice, speed) {
  const P = typeof window !== "undefined" && window.__outpost && window.__outpost.prefs;
  if (!P) return style;
  const out = { ...(style && typeof style === "object" ? style : {}) };
  if (P.voice && (P.voice_all || voice === "guide")) out.steer_voice = P.voice;   // CAPCOM, Houston and the story keep their own voices unless voice_all
  if (speed && Math.abs(speed - 1) > 1e-3) out.speed = speed;
  if (P.expressiveness != null && Math.abs(P.expressiveness - 0.5) > 1e-3) out.expr = P.expressiveness;
  if (P.volume != null && Math.abs(P.volume - 1) > 1e-3) out.volume = P.volume;
  return Object.keys(out).length ? out : style;
}
export function shouldBargeIn({ started, text, refs, dd }) {
  if (!started) return false;
  const w = normWords(text);
  if (w.length < 2 || isFiller(text)) return false;
  if (isEcho(text, refs)) return false;
  const [lo, hi] = bargeThresholds();
  if (dd != null && dd < lo) return false;
  if (w.length === 2 && !CONTROL.test(w.join(" ")) && !(dd != null && dd >= hi)) return false;   // 2 words: a control word or clearly to us
  return true;
}

// Mirrors backend/app/turn_router.py FILLER / NONLEX: a turn made only of these is never for us ("Oh.", "Mm-mm.").
const FILLER = new Set(("oh ohh ooh oo o ah ahh aah a uh uhh um umm hm hmm hmmm mm mmm mhm mmhm mmhmm er erm eh huh ha haha hah " +
  "heh hehe wow whoa oops ugh aw aww yay la na shh psst tsk pfft boo ow ouch hey hi hello so well like and but the i you it").split(" "));
const NONLEX = /^(?:[aeiou]*h+[aeiou]*h*|u+[mh]+|h+m+|m+[mh]*|a+[hw]+|o+[ho]*|e+[rh]+m*|h+u+h+|h+a+(?:h+a+)*|[mn]+|s+h+|p+s+t+|z+)$/;
const CONTROL = /^(stop|wait|stop please|wait please|hold on|go back|say again|next please|stop talking|be quiet)$/;
/** Only non-lexical sounds and fillers. */
export function isFiller(text) {
  const w = normWords(text);
  return !w.length || w.every(x => FILLER.has(x) || NONLEX.test(x));
}

/**
 * What a Space press does for the focused element: "ignore" (typing: text inputs, textarea, contenteditable),
 * "blur" (a button-like control has focus: blur it, then push-to-talk; preventDefault so it doesn't click) or "ptt".
 */
export function spaceAction(target) {
  if (!target || typeof target.closest !== "function") return "ptt";
  if (target.isContentEditable || target.closest("textarea, [contenteditable]:not([contenteditable='false'])")) return "ignore";
  const inp = target.closest("input");
  if (inp) {
    const ty = String(inp.type || "text").toLowerCase();
    return ["button", "submit", "reset", "checkbox", "radio", "range", "color", "file", "image"].includes(ty) ? "blur" : "ignore";
  }
  if (target.closest("button, select, summary, a[href], [role='button'], [tabindex]")) return "blur";
  return "ptt";
}

/** A friendly line for a getUserMedia / Web Speech failure. */
export function micErrorText(e) {
  // short enough for the voice bar's field (one line at 1280); the state slot already says "Mic blocked"
  const n = e && (e.name || e.error || "");
  if (/NotAllowed|Security|not-allowed|service-not-allowed/i.test(n)) return "Mic is blocked. Type instead.";
  if (/NotFound|Overconstrained|audio-capture/i.test(n)) return "No microphone found. Type instead.";
  if (/NotReadable|Abort/i.test(n)) return "Another app is using the mic. Type instead.";
  return "The mic didn't start. Type instead, or tap the mic.";
}

// ---------- the floor manager ----------

const VOICE_PARAMS = {          // speechSynthesis fallback only
  guide: { rate: 0.98, pitch: 1.08 },
  capcom: { rate: 1.04, pitch: 0.92 },
  story: { rate: 0.92, pitch: 1.4 },
  houston: { rate: 0.98, pitch: 0.85 },
};

/** The /api/tts URL for one sentence: voice, the Director's style, and its place in the text (for Steer's director). */
export function ttsUrlFor(base, text, voice, style, i, n, next, speed) {
  const q = new URLSearchParams({ voice, text });
  if (speed && Math.abs(speed - 1) > 1e-3) q.set("speed", String(speed));   // [a11y] the kid's TTS speed (a11y.js)
  if (style && typeof style === "object" && Object.keys(style).length) q.set("style", JSON.stringify(style));
  if (n > 1) { q.set("i", String(i)); q.set("n", String(n)); if (next) q.set("next", next); }
  return `${base}?${q.toString()}`;
}
const sleep = ms => new Promise(r => setTimeout(r, ms));
const DUP_MS = 3000;   // a line asked for again within 3 s of the same line (queued, playing or just said) is dropped
const DEV = (() => { try { return !!(import.meta.env && import.meta.env.DEV); } catch (e) { return false; } })();
const callerOf = e => String((e && e.stack) || "").split("\n").slice(2, 4).map(s => s.trim()).join(" < ");
/** Two lines are the same utterance: identical words, or >= 85% of the words shared both ways (>= 3 words). */
export function nearSame(a, b) {
  if (!a.length || !b.length) return false;
  if (a.join(" ") === b.join(" ")) return true;
  if (Math.min(a.length, b.length) < 3) return false;
  const A = new Set(a), B = new Set(b);
  const ab = [...A].filter(w => B.has(w)).length;
  return ab / A.size >= 0.85 && ab / B.size >= 0.85;
}

const levels = () => (typeof window !== "undefined" && window.__outpost && window.__outpost.levels) || { master: 1, alarms: 1 };
export function createFloor({ ttsUrl = "/api/tts" } = {}) {
  const subs = {};
  const emit = (ev, data) => (subs[ev] || []).slice().forEach(fn => { try { fn(data); } catch (e) { console.error(e); } });
  const on = (ev, fn) => { (subs[ev] = subs[ev] || []).push(fn); return () => off(ev, fn); };
  const off = (ev, fn) => { subs[ev] = (subs[ev] || []).filter(f => f !== fn); };

  let guideEl = null;                       // created on first use (needs a document)
  let server = true;                        // false after a 503: this backend has no TTS, use the browser voice
  const synth = typeof window !== "undefined" ? window.speechSynthesis || null : null;
  let lastCancel = 0;
  let speed = 1;                            // [a11y] TTS speed (0.75–1.5): Steer rate+pace on the server, rate here

  let kid = false, holder = "none";
  let cur = null;                           // the say() that owns the guide channel: {id, text, sentence, stop, yield, done}
  let crew = { el: null, text: () => "", pauseAtSentenceEnd: null, resume: null }, ducked = false;
  let nextId = 1;
  const waiters = new Set();                // re-check functions for say()s waiting on the floor

  function crewPlaying() { const el = crew.el; return !!(el && !el.paused && !el.ended); }
  function recompute() {
    const h = kid ? "kid" : cur && cur.speaking ? "guide" : crewPlaying() ? "crew" : "none";
    if (h !== holder) { holder = h; emit("floor", { holder }); }
    waiters.forEach(fn => fn());
  }
  /** Resolve when pred() is true (re-checked on every floor change, and every 250 ms as a net) or tok is cancelled. */
  function waitFor(pred, tok) {
    if (pred() || tok.cancelled) return Promise.resolve();
    return new Promise(res => {
      const check = () => { if (pred() || tok.cancelled) { waiters.delete(check); clearInterval(iv); res(); } };
      const iv = setInterval(check, 250); waiters.add(check);
    });
  }
  // `text`: what we are saying (the session's echo check covers every app voice: guide, CAPCOM, story, Houston, crew)
  // `more`: another say is queued right behind this one (the session's hard mute holds through the gap, Spoken.end)
  const playback = (kind, state, id, text, extra) => emit("playback", { kind, state, id, t: Date.now(), ...(text ? { text } : {}), ...(extra || {}) });

  // ----- guide: server audio -----
  function el() {
    if (!guideEl) { guideEl = new Audio(); guideEl.preload = "auto"; guideEl.setAttribute("data-floor", "guide"); }
    return guideEl;
  }
  /** Fetch one sentence's audio → blob URL, or null (fall back for this sentence). A 503 turns server TTS off. */
  // A stalled TTS request (a busy model server) must never leave a readback silent with the floor held: after
  // TTS_TIMEOUT_MS the sentence goes to the browser voice instead (owner's rc/2 play: silent orders).
  const TTS_TIMEOUT_MS = 8000;
  async function fetchTTS(text, voice, style, i = 0, n = 1, next = "") {
    if (!server) return null;
    const ac = typeof AbortController === "function" ? new AbortController() : null;
    const t = ac ? setTimeout(() => ac.abort(), TTS_TIMEOUT_MS) : 0;
    try {
      const r = await fetch(ttsUrlFor(ttsUrl, text, voice, prefStyle(style, voice, speed), i, n, next, speed), ac ? { signal: ac.signal } : undefined);
      if (r.status === 503) { server = false; return null; }
      if (!r.ok) return null;
      // [a11y] word timings (X-TTS-Words, "startMs-endMs,…" per display word) for the caption bar (caption.js)
      return { url: URL.createObjectURL(await r.blob()), words: r.headers.get("X-TTS-Words") || "", engine: r.headers.get("X-TTS-Engine") || "" };
    } catch (e) { return null; } finally { if (t) clearTimeout(t); }
  }
  function playUrl(url, tok) {
    const a = el();
    return new Promise(res => {
      let done = false;
      let watch = 0;
      const fin = v => { if (done) return; done = true; clearTimeout(watch); a.onended = a.onerror = a.onplaying = null; tok.stop = null; res(v); };
      // An error AFTER the sentence was heard (a late decode error, a play() promise rejected by the next load) is its
      // end, not a reason to say it again in the browser voice: that spoke one line twice, in two different voices.
      let heard = false;
      // watchdog: a clip that never starts (8 s) or never reports its end (its length + 2 s) releases the floor
      watch = setTimeout(() => failed(), 8000);
      a.onplaying = () => { heard = true; clearTimeout(watch);
        const len = isFinite(a.duration) && a.duration > 0 ? a.duration : 15;
        watch = setTimeout(() => fin("end"), (len / (a.playbackRate || 1) + 2) * 1000); };
      const failed = () => fin(heard || (a.currentTime || 0) > 0.25 ? "end" : "error");
      a.onended = () => fin("end"); a.onerror = failed;
      tok.stop = () => { a.pause(); fin("stop"); };
      a.volume = 1; a.muted = !!levels().muted; a.src = url;   // the top bar's Mute (mute.js): the text still shows
      a.play().catch(failed);      // autoplay blocked / decode error before any sound → browser voice for this sentence
    });
  }

  // ----- guide: speechSynthesis fallback -----
  function pickVoice() {
    const v = synth ? synth.getVoices() : [];
    return v.find(x => /Samantha|Google US English|Karen|Moira/.test(x.name)) || v.find(x => x.lang && x.lang.startsWith("en"));
  }
  async function speakSynth(text, voice, tok) {
    if (!synth) return "error";
    const gap = 60 - (performance.now() - lastCancel); if (gap > 0) await sleep(gap);   // Chrome drops speak() right after cancel()
    if (tok.cancelled) return "stop";
    return new Promise(res => {
      const u = new SpeechSynthesisUtterance(text), v = pickVoice(), p = VOICE_PARAMS[voice] || VOICE_PARAMS.guide;
      if (v) u.voice = v; u.rate = p.rate * speed; u.pitch = p.pitch; u.volume = Math.min(1, levels().master);   // [qa] Volume applies to the browser voice too
      u.onboundary = e => { if (e.name === "word" || e.name == null) emit("boundary", { id: tok.id, charIndex: e.charIndex, text }); };   // [a11y]
      let done = false;
      const fin = r => { if (done) return; done = true; clearTimeout(cap); clearInterval(keep); tok.stop = null; res(r); };
      u.onend = () => fin("end"); u.onerror = e => fin(e && (e.error === "interrupted" || e.error === "canceled") ? "stop" : "error");
      // Keep-alive: Chrome stops an utterance after ~15 s unless it's nudged.
      const keep = setInterval(() => { if (synth.speaking && !synth.paused) { synth.pause(); synth.resume(); } }, 10000);
      const cap = setTimeout(() => fin("end"), 2500 + text.split(/\s+/).length * 500);   // onend sometimes never fires
      tok.stop = () => { synth.cancel(); lastCancel = performance.now(); fin("stop"); };
      synth.speak(u);
    });
  }

  // ----- say -----
  // `text` may be a list of lines (CAPCOM's hello → brief → question): they play as ONE say, one on-air span with
  // one playback start / end, the floor held by the guide between lines (no gap where the ear slips in).
  async function say(text, opts = {}) {
    // One utterance per user action: the same (or nearly the same) line asked for again while it is queued, playing
    // or within DUP_MS of either, in ANY voice, is dropped (a tap once spoke its line twice, in two voices). Explicit
    // repeats ("Hear it again", "say that again") pass {repeat: true}.
    const words = normWords(sayLines(text).join(" "));
    const now = performance.now();
    const dup = !opts.repeat && words.length && said_.find(s => (s.end === Infinity || now - s.end < DUP_MS || now - s.at < DUP_MS) && nearSame(s.words, words));
    if (dup) {
      if (DEV) console.info("[floor] dropped a duplicate say", { text: words.join(" ").slice(0, 80), voice: opts.voice || "guide", first: dup.voice, source: opts.source || callerOf(new Error()) });
      return false;
    }
    const rec = { words, voice: opts.voice || "guide", at: now, end: Infinity };
    said_.push(rec); if (said_.length > 12) said_.shift();
    const tok0 = { cancelled: false };
    queued.add(tok0);
    try { return await say_(text, opts, tok0); } finally { queued.delete(tok0); rec.end = performance.now(); }
  }
  const said_ = [];
  async function say_(text, { voice = "guide", priority = 3, id, style } = {}, tok0) {
    const sentences = sayLines(text);
    if (!sentences.length) return false;
    if (!VOICE_PARAMS[voice]) voice = "guide";
    const tok = { id: id || "g" + nextId++, text: sentences.join(" "), sentence: "", speaking: false, cancelled: false, stop: null, yield: false, priority };
    tok0.tok = tok;
    const prev = cur;
    if (prev && !prev.cancelled) {
      if (priority <= 2) { prev.yield = true; await waitFor(() => cur !== prev || prev.cancelled || prev.finished, tok); }
      else if (priority === 3) cancel(prev);
    }
    if (priority >= 4) await waitFor(() => holder === "none" && (!cur || cur.finished || cur.cancelled), tok);
    if (tok.cancelled) return false;
    if (cur && cur !== tok && !cur.finished && !cur.cancelled && priority <= 3) cancel(cur);
    cur = tok; pending.add(tok);
    try {
      await waitFor(() => !kid, tok);                                   // §3.3: never talk over the kid
      if (tok.cancelled) return false;
      let pausedCrew = false;
      if (crewPlaying() && crew.pauseAtSentenceEnd) {                  // §3.1: the guide speaks at crew sentence ends
        if (priority >= 4) await waitFor(() => !crewPlaying(), tok);
        else { await crew.pauseAtSentenceEnd(); pausedCrew = true; }
      }
      if (tok.cancelled) return false;
      const ok = await speakAll(tok, sentences, voice, style);
      if (pausedCrew && !kid && crew.resume && cur === tok) crew.resume();
      return ok;
    } finally { tok.finished = true; pending.delete(tok); if (cur === tok) { tok.speaking = false; recompute(); } }
  }
  const pending = new Set();
  const queued = new Set();      // every say() from its call to its return (also while it waits for the floor)
  /** Another say is queued behind `tok` (it will play next): the line's end is not the end of what we're saying. */
  const moreAfter = tok => [...queued].some(q => q.tok !== tok && !(q.tok && (q.tok.cancelled || q.tok.finished)));

  async function speakAll(tok, sentences, voice, style) {
    const n = sentences.length, get = i => fetchTTS(sentences[i], voice, style, i, n, sentences[i + 1] || "");
    let next = get(0), started = false;
    for (let i = 0; i < n; i++) {
      const got = await next, url = got && got.url;   // [a11y] fetchTTS → {url, words, engine}
      next = i + 1 < n ? get(i + 1) : null;   // prefetch while this one plays
      if (tok.cancelled) { if (url) URL.revokeObjectURL(url); break; }
      tok.sentence = sentences[i]; tok.speaking = true;
      if (!started) { started = true; playback("guide", "start", tok.id, tok.text); }
      recompute();
      emit("sentence", { id: tok.id, index: i, text: sentences[i], voice, words: got ? got.words : "", engine: got ? got.engine : "browser", audio: url ? el() : null, speed });
      let r = url ? await playUrl(url, tok) : "error";
      if (url) {
        // stopped / failed mid-load: detach the element first, or it keeps fetching a revoked blob (a console error)
        if (r !== "end" && guideEl && guideEl.src === url) { try { guideEl.removeAttribute("src"); guideEl.load(); } catch (e) { /* */ } }
        URL.revokeObjectURL(url);
      }
      if (r === "error" && !tok.cancelled) r = await speakSynth(sentences[i], voice, tok);
      if (r === "stop" || tok.cancelled) break;
      if (tok.yield) { tok.cancelled = true; break; }                   // a critical alert takes the floor after this sentence
    }
    if (next) next.then(u => u && u.url && URL.revokeObjectURL(u.url));
    tok.speaking = false;
    const full = !tok.cancelled;
    if (started) playback("guide", full ? "end" : "interrupted", tok.id, "", full && moreAfter(tok) ? { more: true } : null);
    recompute();
    return full;
  }

  function cancel(tok) {
    if (!tok || tok.cancelled) return;
    tok.cancelled = true;
    if (tok.stop) tok.stop();
    recompute();
  }
  /** Stop the guide now: the current sentence and every say() waiting for the floor. */
  function stopGuide() {
    pending.forEach(cancel);
    if (synth && (synth.speaking || synth.pending)) { synth.cancel(); lastCancel = performance.now(); }
    if (guideEl && !guideEl.paused) guideEl.pause();
    recompute();
  }

  // ----- crew -----
  function attachCrew(audioEl, hooks = {}) {
    crew = { el: audioEl, text: hooks.text || (() => ""), pauseAtSentenceEnd: hooks.pauseAtSentenceEnd || null, resume: hooks.resume || null };
    ["play", "playing", "pause", "ended", "emptied"].forEach(ev => audioEl.addEventListener(ev, recompute));
  }
  function crewPlayback(state, id) { if (state !== "start") ducked = false; let tx = ""; try { tx = state === "start" ? crew.text() || "" : ""; } catch (e) { /* */ } playback("crew", state, id, tx); recompute(); }
  function duck(level = 0.15) { ducked = true; if (crewPlaying()) fadeTo(crew.el, level, 150); }
  function unduck() { if (!ducked) return; ducked = false; if (crewPlaying()) fadeTo(crew.el, 1, 250); }

  return {
    on, off, say, stopGuide, duck, unduck, attachCrew, crewPlayback,
    setKid(v) { v = !!v; if (v !== kid) { kid = v; recompute(); } },
    get holder() { return holder; },
    get guideBusy() { return [...pending].some(t => !t.cancelled && !t.finished); },
    /** On air for the ear's hard mute: a voice is playing, or a say is still running or queued (between the lines of
     *  a sequence, while the next line's audio is fetched, the floor is "none" but we have not finished talking). */
    get onAir() { return holder === "guide" || holder === "crew" || [...pending].some(t => !t.cancelled && !t.finished) || moreAfter(null); },
    get guideText() { return cur && !cur.cancelled && !cur.finished ? cur.text : ""; },
    get guideSentence() { return cur && cur.speaking ? cur.sentence : ""; },
    get crewText() { try { return crewPlaying() ? crew.text() || "" : ""; } catch (e) { return ""; } },
    get ducked() { return ducked; },
    get serverTTS() { return server; },
    // ---- [a11y] speed + elements for captions (a11y.js, caption.js) ----
    setSpeed(v) { const x = +v; speed = x >= 0.5 && x <= 2 ? x : 1; },
    get speed() { return speed; },
    get guideAudio() { return guideEl; },
    get crewEl() { return crew.el; },
    emit,
  };
}

/** The app's one floor (browser only). */
export const floor = typeof window !== "undefined" ? createFloor() : null;

// ---------- the old sound.js speech API, now on the floor ----------
/** The voice a piece of hardware tells its own story in. */
export const STORY_VOICE = { voice: "story" };
export const CAPCOM_VOICE = { voice: "capcom" };
/** Speak on the guide channel; resolves true when spoken to the end. Old {rate, pitch} options mean the guide voice. */
export function speak(text, opts = {}) { return floor ? floor.say(text, { voice: opts.voice || "guide", priority: opts.priority ?? 3, style: opts.style, repeat: opts.repeat, source: opts.source }) : Promise.resolve(false); }
/** The style of the first `say` decision in a Director / Academy response (Steer steering), if any. */
export const sayStyle = r => ((r && r.decisions) || []).find(d => d.t === "say" && d.style)?.style;
export function stopSpeaking() { if (floor) floor.stopGuide(); }
export function isSpeaking() { return !!(floor && floor.guideBusy); }
