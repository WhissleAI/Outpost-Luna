// The NASA video pieces other screens use (docs/MEDIA.md):
//   - the lesson step {"type": "video", "media": id, "say": predict prompt, "reveal": one line} (course.json): CAPCOM
//     says `say` (the step prompt), one big "Watch (N min)" button + "Skip"; the video; then the server's reply says
//     `reveal` and the step is done. Skip, offline, or a video that can't play still move the lesson on.
//   - Settings → Videos: "X MB saved · Clear"
//   - About → Videos: every video the app can show, with its credit
import { icon } from "../assets/icons.js";
import { openVideo, isAvailable, getVideo, credits, videoCommand, watchLabel, needsNet, DOWNLOADING } from "./video.js";
import { holdButtonHtml, bindHold } from "../reset.js";   // Settings → Videos: Clear is a 3-second hold, like Reset

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };
O.stepRenderers = O.stepRenderers || {};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** What the renderer calls (tests swap these for fakes). */
export const deps = { openVideo, isAvailable, getVideo };

/** Words that start or skip the video on a video step (the rest of the step's turn goes to the server). */
export function stepWord(text) {
  const c = videoCommand(text);
  if (c === "play") return "watch";
  if (c === "skip" || c === "stop") return "skip";
  const q = String(text || "").toLowerCase().replace(/[^a-z ]+/g, " ").replace(/\s+/g, " ").trim();
  if (/^(?:(?:ok |okay |yes |yeah )?(?:watch(?: it| the video)?|show me|play(?: the video)?|yes|yeah|sure|option (?:one|1)|one|a))$/.test(q)) return "watch";
  if (/^(?:skip(?: it| the video)?|no(?: thanks)?|not now|option (?:two|2)|two|b)$/.test(q)) return "skip";
  return null;
}

/** Guess-chip words: "yes", "the second one", or a word of a chip's label ("shadow" for "Earth's shadow"). */
export function guessOf(text, options) {
  const q = String(text || "").toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
  if (!q || !options || !options.length) return null;
  const k = { one: 0, "1": 0, first: 0, two: 1, "2": 1, second: 1, three: 2, "3": 2, third: 2 }[q.replace(/^(the |option |number )/, "").replace(/ one$/, "")];
  if (k != null && options[k]) return options[k].id;
  const byId = options.find(o => o.id === q || q === `${o.id} please`); if (byId) return byId.id;
  if (/^(yeah|yep|yup|sure|i think so|i guess yes)$/.test(q)) { const y = options.find(o => o.id === "yes"); if (y) return y.id; }
  if (/^(nope|nah|no way|i don t think so|i dont think so)$/.test(q)) { const n = options.find(o => o.id === "no"); if (n) return n.id; }
  const words = o => String(o.label).toLowerCase().replace(/[^a-z0-9 ]+/g, " ").split(/\s+/).filter(w => w.length > 3 && !["like", "than", "with"].includes(w));
  const hits = options.filter(o => q === String(o.label).toLowerCase() || words(o).some(w => new RegExp(`\\b${w}\\b`).test(q)));
  return hits.length === 1 ? hits[0].id : null;
}
export const GUESS_ACK = "Got your guess. Now tap Watch to check.";

/** The video step's renderer (the Academy registry's factory form: ctx → {html, bind(el)}). A "Guess, then watch" step
 *  (acc.guess) shows its guess chips first (novice playtest 2026-11-16 #7: there was no way to guess, and "yes"
 *  opened the video); the reply checks the guess after the video, or after Skip, and the chips light up. */
O.stepRenderers.video = ctx => {
  const id = (ctx.acc && ctx.acc.media) || (ctx.step && ctx.step.media);
  const state = ctx.state || {};
  const opts = ((ctx.acc && ctx.acc.guess) || {}).options || [];
  const chips = opts.length ? `<div class="a-choices g-opts vs-guess" role="group" aria-label="Your guess">${opts.map((o, k) =>
    `<button type="button" class="a-choice" data-c="${esc(o.id)}" aria-pressed="${state.guess === o.id}"><span class="a-key" aria-hidden="true">${k + 1}</span><span>${esc(o.label)}</span></button>`).join("")}</div>` : "";
  return {
    html: `${chips}<div class="vs-row"${ctx.locked && opts.length ? " hidden" : ""}>
        <button type="button" class="btn-primary vs-watch" data-watch data-yes>${icon("play")}<span data-label>Watch</span></button>
        <button type="button" class="btn vs-skip" data-skip data-no>Skip</button></div>
      <p class="vs-note" data-note hidden></p>`,
    bind(el) {
      const watch = el.querySelector("[data-watch]"), skip = el.querySelector("[data-skip]"), note = el.querySelector("[data-note]");
      let busy = false;
      Promise.all([deps.getVideo(id), deps.isAvailable(id)]).then(([v, s]) => {
        if (!watch.isConnected) return;
        if (s === "offline" && !(v && v.fallback)) { watch.querySelector("[data-label]").textContent = needsNet(); watch.classList.add("is-offline"); }
        else if (s === "downloading") watch.querySelector("[data-label]").textContent = DOWNLOADING;   // [course switch] plays once saved
        else if (v) watch.querySelector("[data-label]").textContent = watchLabel(v);
        if (v && v.credit) { note.textContent = `Video: ${v.credit}`; note.hidden = false; }
      });
      const all = sel => (el.querySelectorAll ? [...el.querySelectorAll(sel)] : []);
      const withGuess = o => (state.guess ? { ...o, guess: state.guess } : o);
      const go = async () => {
        if (busy || ctx.locked) return; busy = true;
        const r = await deps.openVideo(id, { context: "lesson" });
        busy = false;
        ctx.answer({ video: withGuess({ watched: !!r.watched, seconds: r.seconds || 0, ...(r.offline ? { offline: true } : {}), ...(r.skipped ? { skipped: true } : {}) }) }, watch);
      };
      const no = () => { if (busy || ctx.locked) return; ctx.answer({ video: withGuess({ watched: false, seconds: 0, skipped: true }) }, skip); };
      const pick = (gid, quiet) => {
        if (ctx.locked || !opts.some(o => o.id === gid)) return false;
        state.guess = gid;
        all(".vs-guess .a-choice").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.c === gid)));
        watch.classList.add("is-cue");
        if (!quiet && ctx.say) ctx.say(GUESS_ACK);   // the app acknowledges the guess, then says what's next
        watch.focus({ preventScroll: true });
        return true;
      };
      all(".vs-guess .a-choice").forEach(b => (b.onclick = () => pick(b.dataset.c)));
      watch.onclick = go; skip.onclick = no;
      state.video = { watch: go, skip: no, needsGuess: () => !!opts.length && !state.guess && !ctx.locked,
        guess: gid => pick(gid), guessText: t => { const g = guessOf(t, opts); return g ? pick(g) : false; } };
      if (!ctx.locked) ((opts.length && !state.guess && el.querySelector(".vs-guess .a-choice")) || watch).focus({ preventScroll: true });
      if (state.guess) watch.classList.add("is-cue");
    },
  };
};

// ---------------------------------------------------------------- Settings → Videos ---------------------------------
const mb = b => (b / 1048576 < 10 ? (b / 1048576).toFixed(1) : Math.round(b / 1048576)) + " MB";
export const VIDEOS_COPY = {
  help: "NASA's lesson videos come in the app's video pack (14 videos, about 425 MB) and play offline.",
  hold: "Hold to clear saved videos",
  grownUp: "For a grown-up: hold for 3 seconds. The videos copy back from the pack when needed.",
  cleared: "Cleared",
};
export const settingsSection = {
  id: "videos", title: "Videos", after: "display", grownup: true,   // [0.4.1] drawn in Settings → For grown-ups
  html: () => `<p class="set-help" data-vid-stat>Videos: checking…</p>
    <p class="set-help">${esc(VIDEOS_COPY.help)}</p>
    ${holdButtonHtml(VIDEOS_COPY.hold, "data-vid-clear")}
    <small class="rs-note">${esc(VIDEOS_COPY.grownUp)}</small>`,
  bind(el, { fetchFn = (u, o) => fetch(u, o), holdMs } = {}) {
    const stat = el.querySelector("[data-vid-stat]"), clear = el.querySelector("[data-vid-clear]");
    let total = 0;   // the lesson videos this computer can have (the backend counts them; no fixed number here)
    const paint = s => { total = s.pinned_total ?? total; stat.textContent = `Videos: ${mb(s.bytes || 0)} saved · ${s.pinned_ready ?? 0} of ${s.pinned_total ?? 0} lesson videos ready`; };
    fetchFn("/api/video/cache").then(r => r.json()).then(paint).catch(() => { stat.textContent = "Videos: can't check right now."; });
    // a click does nothing: the clear runs only after a 3-second hold (bindHold, the grown-up gate's pattern)
    return bindHold(clear, { holdMs, onFire: async () => {
      const r = await fetchFn("/api/video/cache", { method: "DELETE" });
      paint({ ...(await r.json()), pinned_ready: 0, pinned_total: total });
      const label = clear.querySelector("span"); if (label) label.textContent = VIDEOS_COPY.cleared;
      fetchFn("/api/video/cache").then(r2 => r2.json()).then(paint).catch(() => {});
    } });
  },
};
if (typeof window !== "undefined") (O.settingsSections = O.settingsSections || []).push(settingsSection);

// ---------------------------------------------------------------- About → Videos (credits) ---------------------------
/** Fill the About dialog's video credits (index.html #aboutVideos). */
export async function fillCredits(doc = document) {
  const box = doc.getElementById("aboutVideos"); if (!box) return;
  const list = await credits(); if (!list.length) return;
  box.innerHTML = list.map(v => `<tr><td>${esc(v.title)}</td><td>${esc(creditLine(v))}</td></tr>`).join("");
}
/** One credit line: the catalog's credit, "· YouTube" for an embed, and "used with permission" for a third-party file
 *  the video pack carries (app/video.py validate() already makes that credit say so; this never drops it). */
export function creditLine(v) {
  let s = String(v.credit || "");
  if (v.source === "youtube") s += " · YouTube";
  if (v.source === "pack_file" && v.nasa === false && !/used with permission/i.test(s)) s += " · used with permission";
  return s;
}
export default O.stepRenderers;
