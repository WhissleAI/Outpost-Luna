// Speech learning steps (docs/SPEECH_LEARNING.md): read, vocab and summary. Like Field School steps they build up over
// turns: the server's reply carries `got` (academy/ui.js keeps it in ctx.state.got and sends it back). Every step works
// by voice, by typing (the small box on the card or the voice bar), by keys (real buttons, number keys) and by a
// controller (the same buttons through input/spatial.js focus). Grading is server-side (backend/app/academy/speech.py).
//
//   read     a short passage (Listen: the app's voice reads it; Read it aloud: the cadet reads, the ear counts words,
//            pace and skipped words), then 2-4 questions: choice, a short answer, find the sentence
//   vocab    one word at a time from its meaning (say it or pick it; sound-alike traps never pass), or use it in a
//            sentence; the order comes from this cadet's spaced repetition (speech_store.js)
//   summary  watch a video or read an article, then tell it back; spoken words collect until the cadet stops (or
//            taps Done), then the server names the key points told and one more (never a grade)
//
// Registered on window.__outpost.stepRenderers[type] as a factory (ctx) -> {html, bind(el)}.
import { icon } from "../assets/icons.js";
import * as store from "./speech_store.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };
O.stepRenderers = O.stepRenderers || {};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const gotOf = ctx => (ctx.state && Array.isArray(ctx.state.got) ? ctx.state.got : []);
const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
const q$ = sel => (typeof document !== "undefined" ? q$(sel) : null);

export const SPEECH_STEP_TYPES = ["read", "vocab", "summary"];

/** Card copy (docs/COPY.md: buttons are verbs, 1-3 words; lines 12 words or fewer). */
export const COPY = {
  listen: "Listen", aloud: "Read it aloud", done: "Done", again: "Start over", send: "Send", type: "Type your answer",
  typeSummary: "Or type it here", hear: "Hear it", watch: "Watch the video", source: "Source",
  aloudOn: "Read the passage out loud. Tap Done at the end.",
  aloudCount: n => `${n} words heard`,
  findHow: "Tap the sentence, or read it out loud.",
  sayHow: "Say it, or type it.",
  pickHow: "Say the word, or tap it.",
  sentenceHow: term => `Use “${term}” in a sentence. Or pick one that fits.`,
  tellHow: "Tell it back in your words. I'll listen until you stop.",
  tellCount: n => `${n} words so far`,
  of: (k, n) => `${k} of ${n}`,
};
export const DONE_WORDS = /\b(i m done|i am done|im done|that s it|thats it|the end|finished|all done)\s*$/;
export const AUTO_SEND_MS = 4500;   // a summary goes in after this much quiet (and >= MIN_WORDS words)
export const MIN_WORDS = 6;

/** Current question of a read step (the last once done). Pure. */
export const currentQuestion = (acc, got) => (acc.questions || [])[Math.min((got || []).length, (acc.questions || []).length - 1)] || null;
/** Words counted in a text. Pure. */
export const wordCount = t => (String(t || "").trim().match(/[A-Za-z0-9'’]+/g) || []).length;
/** The seconds to divide by for words a minute: the ear's speaking time when it has one, else the clock. Pure. */
export const readingSeconds = (earS, wallS) => (earS > 3 ? earS : wallS);

function dots(n, k, done) {
  return `<p class="f-round-n sp-n"><span class="g-dots" aria-hidden="true">${Array.from({ length: n }, (_, j) => `<i class="${j < done ? "is-done" : j === k ? "is-now" : ""}"></i>`).join("")}</span><span>${esc(COPY.of(Math.min(k + 1, n), n))}</span></p>`;
}
const typeBox = (label, id) => `<form class="sp-type" data-type="${id}"><input type="text" maxlength="300" aria-label="${esc(label)}" placeholder="${esc(label)}" autocomplete="off"><button type="submit" class="btn-quiet">${esc(COPY.send)}</button></form>`;
const srcLink = s => (s && s.url ? `<a class="chip-src" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.title)}">${esc(COPY.source)}</a>` : "");

function bindType(el, send) {
  el.querySelectorAll(".sp-type").forEach(f => (f.onsubmit = e => { e.preventDefault(); const v = f.querySelector("input").value.trim(); if (v) send(v, f.querySelector("button")); }));
}
function bindOptions(el, ctx) {
  el.querySelectorAll(".sp-opt").forEach(b => (b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)));
}

// ---------- read ----------
function passageHtml(p, { find = false, tools = true } = {}) {
  const ss = p.sentences || [p.text];
  return `<article class="sp-passage" aria-label="${esc(p.title || "Passage")}">
      <header class="sp-phead"><h3>${esc(p.title || "")}</h3>${tools ? `<span class="sp-tools">
        <button type="button" class="btn-quiet" data-listen>${icon("speaker", { size: 16 })}${esc(COPY.listen)}</button>
        <button type="button" class="btn-quiet" data-aloud>${icon("mic", { size: 16 })}${esc(COPY.aloud)}</button></span>` : ""}</header>
      <div class="sp-text${find ? " is-find" : ""}" role="${find ? "group" : "presentation"}"${find ? ` aria-label="Sentences"` : ""}>${ss.map((s, k) => find
        ? `<button type="button" class="a-choice sp-opt sp-sent" data-c="s${k + 1}"><span class="a-key" aria-hidden="true">${k + 1}</span><span>${esc(s)}</span></button>`
        : `<span class="sp-s">${esc(s)}</span>`).join(find ? "" : " ")}</div>
      <p class="sp-src">${srcLink(p.source)}</p>
    </article>
    <div class="sp-aloud" role="status" aria-live="polite" hidden></div>`;
}

/** Read it aloud: the cadet's words collect (ctx.state.onText) until Done; the server counts, nothing is kept. */
function startAloud(el, ctx) {
  const st = ctx.state, box = el.querySelector(".sp-aloud"); if (!box) return;
  const a = st.aloud = { t0: now(), last: now(), texts: [], ear: 0 };
  const paint = () => { const b = (q$("#aInput .sp-aloud")) || box;
    b.hidden = false; b.innerHTML = `<p>${esc(COPY.aloudOn)}</p><p class="sp-count">${esc(COPY.aloudCount(wordCount(a.texts.join(" "))))}</p>
      <p class="a-row"><button type="button" class="btn-primary" data-aloud-done>${icon("check", { size: 16 })}${esc(COPY.done)}</button></p>`;
    b.querySelector("[data-aloud-done]").onclick = () => finishAloud(ctx); };
  const onEar = e => { if (st.aloud === a && e.detail && +e.detail.speech_s > 0) a.ear += +e.detail.speech_s; };
  try { addEventListener("outpost:ear-final", onEar); } catch (e) { /* tests */ }
  a.off = () => { try { removeEventListener("outpost:ear-final", onEar); } catch (e) { /* */ } };
  st.onText = text => { if (st.aloud !== a) return false; a.texts.push(String(text)); a.last = now(); paint(); return true; };
  paint();
  const d = (q$("#aInput [data-aloud-done]")); if (d) d.focus({ preventScroll: true });
}
async function finishAloud(ctx) {
  const st = ctx.state, a = st.aloud; if (!a) return;
  st.aloud = null; st.onText = null; if (a.off) a.off();
  const text = a.texts.join(" "), secs = readingSeconds(a.ear, (a.last - a.t0) / 1000);
  let r = null;
  try {
    const res = await fetch("/api/academy/fluency", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lesson_id: ctx.lesson && ctx.lesson.id, step: ctx.stepIndex, text: text.slice(0, 6000), seconds: Math.round(secs * 10) / 10 }) });
    r = res.ok ? await res.json() : null;
  } catch (e) { r = null; }
  const b = q$("#aInput .sp-aloud");
  const lines = (r && r.lines) || ["I couldn't count that one. Try again."];
  if (b) { b.hidden = false; b.innerHTML = `<ul class="sp-lines">${lines.map(l => `<li>${esc(l)}</li>`).join("")}</ul>`; }
  if (r && r.correct) { const s = store.load(); const c = store.courseOf(ctx.lesson && ctx.lesson.id); store.addCount(s, c, "aloud"); store.addCount(s, c, "aloud_words", r.correct); store.save(s); }
  if (ctx.say) ctx.say(r && r.say ? r.say : lines[0]);
}

O.stepRenderers.read = ctx => {
  const acc = ctx.acc, got = gotOf(ctx), qs = acc.questions || [], q = currentQuestion(acc, got), k = Math.min(got.length, qs.length - 1);
  const find = !!(q && q.kind === "find" && !ctx.locked);
  const qHtml = !q ? "" : q.kind === "choice"
    ? `<div class="a-choices sp-opts" role="group" aria-label="Answers">${q.options.map((o, j) => `<button type="button" class="a-choice sp-opt" data-c="${esc(o.id)}"><span class="a-key" aria-hidden="true">${"ABCD"[j]}</span><span>${esc(o.label)}</span></button>`).join("")}</div>`
    : q.kind === "find" ? `<p class="a-how">${esc(COPY.findHow)}</p>` : `<p class="a-how">${esc(COPY.sayHow)}</p>${typeBox(COPY.type, "say")}`;
  return {
    html: `<div class="sp-read">${passageHtml(acc.passage, { find })}
        <section class="sp-q" aria-label="Question">${dots(qs.length, k, got.length)}<p class="sp-qp" aria-live="polite">${esc(q ? q.prompt : "")}</p>${qHtml}</section></div>`,
    bind: el => {
      if (!el || !el.querySelectorAll) return;
      bindOptions(el, ctx);
      bindType(el, (v, b) => ctx.answer({ text: v }, b));
      const l = el.querySelector("[data-listen]"); if (l && ctx.say) l.onclick = () => ctx.say(acc.passage.text);
      const a = el.querySelector("[data-aloud]"); if (a) { a.hidden = acc.fluency === false; a.onclick = () => startAloud(el, ctx); }
      if (ctx.state && ctx.state.aloud && !ctx.locked) { const keep = ctx.state.aloud; ctx.state.aloud = null; startAloud(el, ctx); ctx.state.aloud.t0 = keep.t0; ctx.state.aloud.texts = keep.texts; ctx.state.aloud.ear = keep.ear; }
    },
  };
};

// ---------- vocab ----------
/** The order this cadet sees the items in (due first), fixed for the step once chosen. */
export function stepPlan(ctx) {
  const st = ctx.state || {};
  if (Array.isArray(st.plan) && st.plan.length) return st.plan;
  const items = (ctx.acc.items || []).map(it => ({ id: it.id, term: (ctx.acc.terms || {})[it.id] || it.term || it.id }));
  const course = store.courseOf(ctx.lesson && ctx.lesson.id);
  const plan = store.planFor(items, store.load(), course).slice(0, ctx.acc.ask || items.length);
  st.plan = plan;
  return plan;
}
O.stepRenderers.vocab = ctx => {
  const acc = ctx.acc, got = gotOf(ctx), plan = stepPlan(ctx), byId = Object.fromEntries((acc.items || []).map(i => [i.id, i]));
  const k = Math.min(got.length, plan.length - 1), it = byId[plan[k]] || (acc.items || [])[0] || {};
  const term = (acc.terms || {})[it.id] || it.term || "";
  const body = it.kind === "sentence"
    ? `<p class="sp-def"><b>${esc(term)}</b>: ${esc(it.define)}</p><p class="a-how">${esc(COPY.sentenceHow(term))}</p>
       <div class="a-choices sp-opts sp-sentences" role="group" aria-label="Sentences">${(it.options || []).map((o, j) => `<button type="button" class="a-choice sp-opt" data-c="${esc(o.id)}"><span class="a-key" aria-hidden="true">${j + 1}</span><span>${esc(o.label)}</span></button>`).join("")}</div>
       ${typeBox(COPY.type, "sentence")}`
    : `<p class="sp-def" aria-live="polite">${esc(it.define)}</p><p class="a-how">${esc(COPY.pickHow)}</p>
       <div class="a-choices sp-opts sp-words" role="group" aria-label="Words">${(it.options || []).map((o, j) => `<button type="button" class="a-choice sp-opt" data-c="${esc(o.id)}"><span class="a-key" aria-hidden="true">${j + 1}</span><span>${esc(o.label)}</span></button>`).join("")}</div>`;
  return {
    html: `<div class="sp-vocab">${dots(plan.length, k, got.length)}
        <p class="sp-tools"><button type="button" class="btn-quiet" data-hear>${icon("speaker", { size: 16 })}${esc(COPY.hear)}</button></p>${body}</div>`,
    bind: el => {
      if (!el || !el.querySelectorAll) return;
      bindOptions(el, ctx);
      bindType(el, (v, b) => ctx.answer({ text: v }, b));
      const h = el.querySelector("[data-hear]"); if (h && ctx.say) h.onclick = () => ctx.say(it.kind === "sentence" ? `${term}. ${it.define}` : it.define);
    },
  };
};

// ---------- summary ----------
/** The words a summary collects: a "that's it" at the end ends it (and is not part of it). Pure. */
export function addSegment(texts, text) {
  const t = String(text || "").trim(), low = t.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const done = DONE_WORDS.test(low);
  const keep = done ? t.replace(/\b(i'?m done|i am done|that'?s it|the end|finished|all done)\W*$/i, "").trim() : t;
  return { texts: keep ? [...texts, keep] : texts, done };
}
function summarySend(ctx) {
  const st = ctx.state, r = st.rec; if (!r || !r.texts.length) return;
  clearTimeout(r.timer);
  const long = r.texts.join(" ").slice(0, 2400);
  r.texts = [];
  let rich = false; try { rich = !!(O.prefs && O.prefs.summaryHelper && O.prefs.summaryHelper()); } catch (e) { rich = false; }
  ctx.answer({ long_text: long, ...(rich ? { rich: true } : {}) });
}
function startRec(ctx) {
  const st = ctx.state;
  if (st.rec) return st.rec;
  const r = st.rec = { texts: [], timer: 0 };
  const paint = () => { const c = q$("#aInput .sp-count"); if (c) c.textContent = COPY.tellCount(wordCount(r.texts.join(" "))); };
  st.onText = text => {
    if (st.rec !== r) return false;
    const a = addSegment(r.texts, text);
    r.texts = a.texts; paint(); clearTimeout(r.timer);
    if (a.done) { summarySend(ctx); return true; }
    if (wordCount(r.texts.join(" ")) >= MIN_WORDS) r.timer = setTimeout(() => summarySend(ctx), AUTO_SEND_MS);
    return true;
  };
  return r;
}
O.stepRenderers.summary = ctx => {
  const acc = ctx.acc, src = acc.source || {}, got = gotOf(ctx), rec = ctx.locked ? null : startRec(ctx);
  const n = rec ? wordCount(rec.texts.join(" ")) : 0;
  const source = src.kind === "video"
    ? `<p class="sp-tools"><button type="button" class="btn" data-watch>${icon("play", { size: 16 })}${esc(COPY.watch)}</button></p>`
    : src.passage ? passageHtml(src.passage, { tools: true }) : "";
  return {
    html: `<div class="sp-summary">${source}
        <section class="sp-tell" aria-label="Tell it back">
          <p class="sp-tell-how">${icon("mic", { size: 16 })}<span>${esc(COPY.tellHow)}</span></p>
          ${acc.need ? `<p class="f-count sp-pts" aria-live="polite">${esc(COPY.of(Math.min(got.length, acc.need), acc.need))} key points</p>` : ""}
          <p class="sp-count" aria-live="polite">${esc(COPY.tellCount(n))}</p>
          <p class="a-row"><button type="button" class="btn-primary" data-tell-done>${icon("check", { size: 16 })}${esc(COPY.done)}</button>
            <button type="button" class="btn-quiet" data-tell-again>${icon("retry", { size: 16 })}${esc(COPY.again)}</button></p>
          ${typeBox(COPY.typeSummary, "summary")}
        </section></div>`,
    bind: el => {
      if (!el || !el.querySelectorAll) return;
      const w = el.querySelector("[data-watch]");
      if (w) w.onclick = () => import("../media/video.js").then(m => m.openVideo(src.media, { context: "lesson" })).catch(() => {});
      const l = el.querySelector("[data-listen]"); if (l && ctx.say && src.passage) l.onclick = () => ctx.say(src.passage.text);
      const a = el.querySelector("[data-aloud]"); if (a) a.hidden = true;   // a summary's article: Listen only
      const d = el.querySelector("[data-tell-done]"); if (d) d.onclick = () => summarySend(ctx);
      const g = el.querySelector("[data-tell-again]"); if (g) g.onclick = () => { if (ctx.state.rec) { ctx.state.rec.texts = []; clearTimeout(ctx.state.rec.timer); } const c = el.querySelector(".sp-count"); if (c) c.textContent = COPY.tellCount(0); };
      bindType(el, v => { const r = startRec(ctx); r.texts.push(v); summarySend(ctx); });
    },
  };
};

// ---------- counts (speech_store.js): every reply of these steps, from academy/ui.js ----------
try {
  addEventListener("outpost:lesson-result", e => {
    const d = e.detail || {};
    if (!SPEECH_STEP_TYPES.includes(d.step_type) || d.preview) return;
    const s = store.load(); store.applyReply(s, d); store.save(s);
  });
} catch (e) { /* no window (tests) */ }
