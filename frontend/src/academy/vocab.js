// Space words: renderers for the four vocab step types (docs/VOCABULARY.md). Grading is server-side
// (backend/app/academy/vocab.py); these only draw the step and send {choice} or {text}.
//
// Registered on window.__outpost.stepRenderers[type]; the Academy UI calls
//   renderer({step, acc, answer, say, playCrew, esc, captions}) → {html, bind(stepEl)}
// and inserts `html` in the step body. Every option is a real <button> (keyboard + voice: "option 2", "press crater").

import { icon } from "../ui-icons.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };
O.stepRenderers = O.stepRenderers || {};

const escD = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** "regolith" → "reg·o·lith" (a reading aid: vowel-group syllables). */
export function syllabify(word) {
  return String(word || "").split(" ").map(w => {
    const parts = w.match(/[^aeiouy]*[aeiouy]+(?:[^aeiouy](?=[^aeiouy]))?|[^aeiouy]+$/gi);
    if (!parts || parts.length < 2) return w;
    const out = [...parts]; const last = out[out.length - 1];
    if (/^[^aeiouy]+$/i.test(last) || /^[^aeiouy]*e$/i.test(last)) { out.pop(); out[out.length - 1] += last; }
    return out.join("·");
  }).join(" ");
}

function sourceHtml(acc) {
  const s = acc.source || {};
  if (!s.url) return "";
  return `<p class="v-src">Heard in: <a class="chip-src" href="${escD(s.url)}" target="_blank" rel="noopener">${escD(s.title)}</a>
    ${s.clip_id ? `<button type="button" class="btn-quiet v-crew" data-crew>${icon("play", { size: 16 })}Hear the crew say it</button>` : ""}</p>`;
}
function optionsHtml(acc, cls = "") {
  return `<div class="a-choices v-opts ${cls}" role="group" aria-label="Answers">${(acc.options || []).map((o, k) =>
    `<button type="button" class="a-choice v-opt" data-c="${escD(o.id)}"><span class="v-n" aria-hidden="true">${k + 1}</span>${escD(o.label)}</button>`).join("")}</div>`;
}
function bindCommon(root, ctx) {
  root.querySelectorAll(".v-opt").forEach(b => b.onclick = () => ctx.answer({ choice: b.dataset.c }, b));
  const crew = root.querySelector("[data-crew]"), s = ctx.acc.source || {};
  if (crew && ctx.playCrew) crew.onclick = () => ctx.playCrew({ clip_id: s.clip_id, t0: Math.max(0, s.t - 2), t1: s.t + 4, speaker: "crew", places: [], jargon: [] });
  root.querySelectorAll("[data-hear]").forEach(b => b.onclick = () => ctx.say(b.dataset.hear, { situation: "vocab", vocab: ctx.acc.term ? [ctx.acc.term] : [] }));
}
const vocabStyle = acc => ({ situation: "vocab", vocab: acc.term ? [acc.term] : [] });

O.stepRenderers.vocab_match = ctx => {
  const { acc } = ctx;
  return {
    html: `<div class="v-word"><span class="v-label">Space word</span><b lang="en">${escD(acc.term)}</b>
        <button type="button" class="btn-quiet" data-hear="${escD(acc.term)}" aria-label="Hear the word ${escD(acc.term)}">${icon("volume", { size: 16 })}Hear it</button></div>
      <p class="a-how">Tap the meaning, or say it</p>${optionsHtml(acc, "is-meanings")}${sourceHtml(acc)}`,
    bind: root => bindCommon(root, ctx),
  };
};

O.stepRenderers.vocab_listen = ctx => {
  const { acc } = ctx, showText = ctx.captions !== false;
  return {
    html: `<div class="v-listen"><button type="button" class="btn" data-hear="${escD(acc.explain || "")}">${icon("volume", { size: 16 })}Hear the meaning</button>
        <details class="v-reveal" ${showText ? "open" : ""}><summary>Show the words</summary><p>${escD(acc.explain || "")}</p></details></div>
      <p class="a-how">Which word is it? Tap it, or say it</p>${optionsHtml(acc)}${sourceHtml(acc)}`,
    bind: root => bindCommon(root, ctx),
  };
};

O.stepRenderers.vocab_fill = ctx => {
  const { acc } = ctx;
  const sent = escD(acc.sentence || "").replace("____", `<span class="v-blank" aria-label="blank">______</span>`);
  return {
    html: `<p class="v-sentence">${sent}</p><button type="button" class="btn-quiet v-read" data-hear="${escD((acc.sentence || "").replace("____", "blank"))}">${icon("volume", { size: 16 })}Read it to me</button>
      <p class="a-how">Tap the missing word, or say it</p>${optionsHtml(acc)}${sourceHtml(acc)}`,
    bind: root => bindCommon(root, ctx),
  };
};

O.stepRenderers.vocab_say = ctx => {
  const { acc } = ctx;
  return {
    html: `<div class="v-word is-say"><span class="v-label">Say it back</span><b lang="en">${escD(acc.term)}</b>
        <span class="v-syl" aria-hidden="true">${escD(syllabify(acc.term))}</span>
        <button type="button" class="btn" data-hear="${escD(acc.term)}. ${escD(acc.term)}." aria-label="Hear ${escD(acc.term)} slowly">${icon("volume", { size: 16 })}Hear it slowly</button></div>
      <p class="v-mean">${escD(acc.explain || "")}</p>
      <p class="a-how">Say the word, or type it</p>${sourceHtml(acc)}`,
    bind: root => bindCommon(root, ctx),
  };
};

export const VOCAB_STYLE = vocabStyle;
export default O.stepRenderers;
