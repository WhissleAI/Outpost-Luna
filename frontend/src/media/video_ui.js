// The NASA video pieces other screens use (docs/MEDIA.md):
//   - the lesson step {"type": "video", "media": id, "say": predict prompt, "reveal": one line} (course.json): CAPCOM
//     says `say` (the step prompt), one big "Watch (N min)" button + "Skip"; the video; then the server's reply says
//     `reveal` and the step is done. Skip, offline, or a video that can't play still move the lesson on.
//   - Settings → Videos: "X MB saved · Clear"
//   - About → Videos: every video the app can show, with its credit
import { icon } from "../assets/icons.js";
import { openVideo, isAvailable, getVideo, credits, videoCommand, watchLabel, NEEDS_NET } from "./video.js";

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

/** The video step's renderer (the Academy registry's factory form: ctx → {html, bind(el)}). */
O.stepRenderers.video = ctx => {
  const id = (ctx.acc && ctx.acc.media) || (ctx.step && ctx.step.media);
  const state = ctx.state || {};
  return {
    html: `<div class="vs-row">
        <button type="button" class="btn-primary vs-watch" data-watch data-yes>${icon("play")}<span data-label>Watch</span></button>
        <button type="button" class="btn vs-skip" data-skip data-no>Skip</button></div>
      <p class="vs-note" data-note hidden></p>`,
    bind(el) {
      const watch = el.querySelector("[data-watch]"), skip = el.querySelector("[data-skip]"), note = el.querySelector("[data-note]");
      let busy = false;
      Promise.all([deps.getVideo(id), deps.isAvailable(id)]).then(([v, s]) => {
        if (!watch.isConnected) return;
        if (s === "offline" && !(v && v.fallback)) { watch.querySelector("[data-label]").textContent = NEEDS_NET; watch.classList.add("is-offline"); }
        else if (v) watch.querySelector("[data-label]").textContent = watchLabel(v);
        if (v && v.credit) { note.textContent = `Video: ${v.credit}`; note.hidden = false; }
      });
      const go = async () => {
        if (busy || ctx.locked) return; busy = true;
        const r = await deps.openVideo(id, { context: "lesson" });
        busy = false;
        ctx.answer({ video: { watched: !!r.watched, seconds: r.seconds || 0, ...(r.offline ? { offline: true } : {}), ...(r.skipped ? { skipped: true } : {}) } }, watch);
      };
      const no = () => { if (busy || ctx.locked) return; ctx.answer({ video: { watched: false, seconds: 0, skipped: true } }, skip); };
      watch.onclick = go; skip.onclick = no;
      state.video = { watch: go, skip: no };
      if (!ctx.locked) watch.focus({ preventScroll: true });
    },
  };
};

// ---------------------------------------------------------------- Settings → Videos ---------------------------------
const mb = b => (b / 1048576 < 10 ? (b / 1048576).toFixed(1) : Math.round(b / 1048576)) + " MB";
const settingsSection = {
  id: "videos", title: "Videos", after: "display",
  html: () => `<p class="set-help" data-vid-stat>Videos: checking…</p>
    <button type="button" class="btn" data-vid-clear>Clear saved videos</button>
    <p class="set-help">NASA videos are saved here after the first time online, so lessons can show them offline.</p>`,
  bind(el) {
    const stat = el.querySelector("[data-vid-stat]"), clear = el.querySelector("[data-vid-clear]");
    const paint = s => { stat.textContent = `Videos: ${mb(s.bytes || 0)} saved · ${s.pinned_ready ?? 0} of ${s.pinned_total ?? 0} lesson videos ready`; };
    fetch("/api/video/cache").then(r => r.json()).then(paint).catch(() => { stat.textContent = "Videos: can't check right now."; });
    clear.onclick = async () => {
      clear.disabled = true;
      try { const r = await fetch("/api/video/cache", { method: "DELETE" }); paint({ ...(await r.json()), pinned_ready: 0, pinned_total: 8 }); clear.textContent = "Cleared"; }
      catch (e) { clear.disabled = false; }
      fetch("/api/video/cache").then(r => r.json()).then(paint).catch(() => {});
    };
  },
};
if (typeof window !== "undefined") (O.settingsSections = O.settingsSections || []).push(settingsSection);

// ---------------------------------------------------------------- About → Videos (credits) ---------------------------
/** Fill the About dialog's video credits (index.html #aboutVideos). */
export async function fillCredits(doc = document) {
  const box = doc.getElementById("aboutVideos"); if (!box) return;
  const list = await credits(); if (!list.length) return;
  box.innerHTML = list.map(v => `<tr><td>${esc(v.title)}</td><td>${esc(v.credit)}${v.source === "youtube" ? " · YouTube" : ""}</td></tr>`).join("");
}
export default O.stepRenderers;
