// Field School steps (0.5, docs/LEARNING_DESIGN.md §12): describe, sequence and rounds. Like the route, each one
// builds up over several turns: the server's reply carries `got` (academy/ui.js keeps it in ctx.state.got and sends
// it back with the next answer), so "big and round" then "with long shadows" add up to one report.
//
// Registered on window.__outpost.stepRenderers[type] as a factory ({step, acc, answer, esc, state, locked}) ->
// {html, bind(el)}. Every step works by voice alone (the Academy sends the kid's words) and by tap or keyboard alone
// (the chips and option buttons). Grading is server-side (backend/app/academy/grade.py FIELD_TYPES).
//
//   describe   a cue card, like the Artemis II crew's: five kinds of words (size, shape, bright or dark, texture,
//              shadows), each with two chips; a kind lights up when the kid has said (or tapped) a word of it
//   sequence   the station routine as chips in a jumbled order; tap or say them in order; the order fills in above
//   rounds     one question, several times: a round's prompt, its clue, the real Apollo rock in 3D when the
//              nasa_views pack is installed (the clue alone when it is not), and the answer buttons
import { icon } from "../assets/icons.js";
import { getViews } from "../media/nasa_views.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };
O.stepRenderers = O.stepRenderers || {};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const gotOf = ctx => (ctx.state && Array.isArray(ctx.state.got) ? ctx.state.got : []);

export const FIELD_STEP_TYPES = ["describe", "sequence", "rounds"];

/** The cue card's rows: [{id, label, chips, done}] for the descriptor kinds, in order. Pure (tested). */
export function cueRows(acc, got) {
  const have = new Set(got || []);
  return (acc.cats || []).map(c => ({ ...c, done: have.has(c.id) }));
}

O.stepRenderers.describe = ctx => {
  const got = gotOf(ctx), rows = cueRows(ctx.acc, got), need = ctx.acc.need || 3;
  const n = rows.filter(r => r.done).length;
  return {
    html: `<div class="f-cue" role="group" aria-label="Cue card">
        <p class="f-cue-head"><b>Cue card</b><span class="f-count" aria-live="polite">${Math.min(n, need)} of ${need}</span></p>
        <ul class="f-cue-rows">${rows.map(r => `<li class="f-cue-row${r.done ? " is-done" : ""}">
          <span class="f-cue-kind">${r.done ? icon("check", { size: 16 }) : `<i aria-hidden="true"></i>`}${esc(r.label)}${r.done ? `<span class="sr-only"> (said)</span>` : ""}</span>
          <span class="f-chips">${r.chips.map(w => `<button type="button" class="a-choice f-chip" data-say="${esc(w.toLowerCase())}">${esc(w)}</button>`).join("")}</span></li>`).join("")}</ul>
      </div>`,
    bind: el => {
      if (!el || !el.querySelectorAll) return;
      el.querySelectorAll(".f-chip").forEach(b => (b.onclick = () => ctx.answer({ text: b.dataset.say }, b)));
    },
  };
};

O.stepRenderers.sequence = ctx => {
  const got = gotOf(ctx), items = ctx.acc.items || [], byId = Object.fromEntries(items.map(o => [o.id, o]));
  const n = items.length;
  return {
    html: `<ol class="f-seq" aria-label="Your order so far">${Array.from({ length: n }, (_, k) => {
        const it = byId[got[k]];
        return `<li class="${it ? "is-done" : k === got.length ? "is-now" : ""}"><span class="f-seq-n" aria-hidden="true">${k + 1}</span>${it ? esc(it.label) : `<span class="sr-only">empty</span>`}</li>`;
      }).join("")}</ol>
      <div class="a-choices f-seq-chips" role="group" aria-label="Station steps">${items.map(o =>
        `<button type="button" class="a-choice f-chip" data-c="${esc(o.id)}"${got.includes(o.id) ? " disabled" : ""}>${esc(o.label)}</button>`).join("")}</div>`,
    bind: el => {
      if (!el || !el.querySelectorAll) return;
      el.querySelectorAll(".f-chip").forEach(b => (b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)));
    },
  };
};

/** The rock a round shows: the pack's sample, or null (no pack: the clue alone). Pure apart from getViews. */
export function roundRock(round, views = getViews()) {
  if (!round || !round.rock || !views) return null;
  return (views.rocks || []).find(r => r.id === round.rock) || null;
}

/** The round the kid is on (the last one once the step is done). */
export const currentRound = (acc, got) => (acc.rounds || [])[Math.min((got || []).length, (acc.rounds || []).length - 1)] || null;

let turntable = null;   // one turntable at a time (media/turntable.js, loaded only when a rock is shown)
O.stepRenderers.rounds = ctx => {
  const got = gotOf(ctx), rs = ctx.acc.rounds || [], r = currentRound(ctx.acc, got), rock = roundRock(r);
  const k = Math.min(got.length, rs.length - 1);
  return {
    html: `<div class="f-rounds">
        <p class="f-round-n"><span class="g-dots" aria-hidden="true">${rs.map((_, j) => `<i class="${j < got.length ? "is-done" : j === k ? "is-now" : ""}"></i>`).join("")}</span>
          <span>${esc(`${k + 1} of ${rs.length}`)}</span></p>
        ${rock ? `<figure class="f-rock"><div class="f-rock-view"><canvas aria-hidden="true"></canvas><p class="f-rock-wait">Loading the rock…</p></div>
          <figcaption>${esc(r.clue || "")} <a class="chip-src" href="${esc(rock.source || "https://ares.jsc.nasa.gov/astromaterials3d/")}" target="_blank" rel="noopener">${esc(rock.credit || "NASA/Astromaterials 3D")}</a></figcaption></figure>`
          : r && r.clue ? `<p class="f-clue">${icon("info", { size: 16 })}${esc(r.clue)}</p>` : ""}
        <p class="f-round-q" aria-live="polite">${esc(r ? r.prompt : "")}</p>
        <div class="a-choices g-opts f-opts" role="group" aria-label="Answers">${(ctx.acc.options || []).map((o, j) =>
          `<button type="button" class="a-choice" data-c="${esc(o.id)}"><span class="a-key" aria-hidden="true">${j + 1}</span><span>${esc(o.label)}</span></button>`).join("")}</div>
      </div>`,
    bind: el => {
      if (!el || !el.querySelectorAll) return;
      el.querySelectorAll(".f-opts .a-choice").forEach(b => (b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)));
      const cv = el.querySelector(".f-rock canvas");
      if (!cv || !rock) return;
      import("../media/turntable.js").then(({ createTurntable }) => {
        if (!cv.isConnected) return;
        if (turntable) turntable.dispose();
        turntable = createTurntable(cv);
        turntable.start();
        return turntable.show(rock.url).then(ok => { const w = el.querySelector(".f-rock-wait"); if (w && ok) w.hidden = true; });
      }).catch(() => { const w = el.querySelector(".f-rock-wait"); if (w) w.textContent = r.clue || ""; });
    },
  };
};
