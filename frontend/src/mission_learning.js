// Mission-side learning beats (NASA Moon Learning & Media Plan v1), kept OUT of mission/ui.js (the mission-UI owner's
// file): main.js installs this next to the mission UI and it works through the DOM and the shell's navigation.
//   1. The Mission hub: a small "Watch the 1-min briefing" chip for NASA's real Moon Base video ([polish 4]: it used to
//      be a blocking Watch / Skip card before the first mission). Settings -> Help also plays it (a11y.js).
//   2. Debrief: "Learn more" (learn_more.js: one NASA video per outcome, or a fact card) and, when this mission unlocked
//      an explorer lesson (explorer.js), a one-tap offer to open it.
// Nothing here ever blocks the mission: every path ends in the mission's own action.
import { LEARN_MORE, EXPLORER, HUB, callSign } from "./story.js";
import { isAvailable as videoState, openVideo as playVideo, getVideo, watchLabel } from "./media/video.js";   // docs/MEDIA.md
import { pickLearnMore } from "./learn_more.js";
import { markMissionFlown, missionsFlown, newlyUnlocked } from "./explorer.js";
import { icon } from "./assets/icons.js";
import "./mission_learning.css";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/**
 * @param {object} o
 * @param {object} o.missionUI     mission/ui.js instance (screen(), context(), active)
 * @param {(t: string) => any} o.say    CAPCOM line
 * @param {() => void} o.stop      stop speech
 * @param {() => object[]} o.lessons     the course lessons (Flight School)
 * @param {(id: string) => void} o.openLesson   switch to Flight School and open a lesson
 * @param {(id: string) => Promise<object|null>} [o.fetchDebrief]
 */
export function installMissionLearning({ missionUI, say, stop = () => {}, lessons = () => [], openLesson = () => {},
  fetchDebrief = id => fetch(`/api/mission/${encodeURIComponent(id)}/debrief`).then(r => (r.ok ? r.json() : null)).catch(() => null) }) {
  // ---------- 1. the Moon Base video: a chip on the Mission hub ([polish 4]; never a blocking yes / no) ----------
  // Only a saved copy (moon_base_6mo is pinned: downloaded on the first online launch) shows the chip: it starts at
  // once, offline too, and a run without the cache (tests: VIDEO_PREFETCH=0) never sees it.
  const panel = document.getElementById("mPanel");
  async function chip() {
    if (!panel || !panel.classList.contains("mx-hub") || panel.querySelector("#mHubVideo")) return;
    let st; try { st = await videoState("moon_base_6mo"); } catch (e) { st = null; }
    if (st !== "cached" || !panel.classList.contains("mx-hub") || panel.querySelector("#mHubVideo")) return;
    const row = panel.querySelector(".mx-hubcard"); if (!row) return;
    const b = document.createElement("button");
    b.type = "button"; b.className = "mx-chip"; b.id = "mHubVideo";
    b.innerHTML = `${icon("play", { size: 14 })}<span>${esc(HUB.video)}</span>`;
    b.onclick = () => { stop(); playVideo("moon_base_6mo", { context: "mission_hub" }); };
    row.append(b);
  }
  addEventListener("outpost:mission-hub", () => { chip(); });

  /** Voice / gestures / keys (main.js shellNav calls this before missionUI.nav): nothing to answer any more. */
  function nav() { return false; }
  /** The router's screen frame: none of our own (the hub is mission/ui.js's). */
  const screen = () => null;
  const offer = null;

  // ---------- 2. the debrief: Learn more + a newly unlocked explorer lesson ----------
  let busy = false;
  async function decorate(host) {
    if (busy || !host || host.hidden || !host.querySelector("#mAgain") || host.querySelector("#mlLearn")) return;
    const ctx = missionUI.context && missionUI.context();
    if (!ctx || !ctx.id) return;
    busy = true;
    try {
      const d = await fetchDebrief(ctx.id);
      const outcome = d && d.outcome;
      if (!outcome || outcome === "in_progress" || host.querySelector("#mlLearn") || !host.querySelector("#mAgain")) return;
      const before = missionsFlown(callSign.get()), after = markMissionFlown(ctx.id, callSign.get());
      const unlockedNow = after > before ? newlyUnlocked(lessons(), after) : [];
      const pick = await pickLearnMore(outcome, videoState);
      if (host.querySelector("#mlLearn") || !host.querySelector("#mAgain")) return;
      const sec = document.createElement("section");
      sec.className = "ml-learn"; sec.id = "mlLearn"; sec.setAttribute("aria-label", LEARN_MORE.title);
      sec.innerHTML = (pick ? `<h3>${esc(LEARN_MORE.title)}</h3>` + (pick.kind === "video"
        ? `<button type="button" class="btn-quiet ml-go" id="mlLearnGo">${icon("play", { size: 16 })}<span>${esc(pick.line)}</span><small></small></button>`
        : `<p class="ml-fact">${icon("info", { size: 16 })}<span>${esc(pick.text)}</span></p>`) : "")
        + unlockedNow.map(l => `<p class="ml-unlock">${icon("star", { size: 16 })}<span><b>${esc(EXPLORER.unlockedTitle)}:</b> ${esc(l.title)}</span>
            <button type="button" class="btn-quiet" data-ml-open="${esc(l.id)}">${esc(EXPLORER.open)}</button></p>`).join("");
      if (!sec.innerHTML) return;
      const body = host.querySelector(".mx-db-body"), foot = host.querySelector(".mx-foot");   // [polish 4] in the scrolling body
      if (body) body.append(sec); else if (foot) foot.before(sec); else host.append(sec);
      const go = sec.querySelector("#mlLearnGo");
      if (go && pick) {
        go.onclick = () => { stop(); playVideo(pick.media, { context: "debrief:" + outcome }); };
        getVideo(pick.media).then(v => { if (v) go.querySelector("small").textContent = watchLabel(v).replace(/^Watch\s*/, ""); });
      }
      sec.querySelectorAll("[data-ml-open]").forEach(b => { b.onclick = () => openLesson(b.dataset.mlOpen); });
    } finally { busy = false; }
  }
  const host = document.getElementById("mDebrief");
  if (host && typeof MutationObserver !== "undefined") new MutationObserver(() => decorate(host)).observe(host, { childList: true });

  return { nav, screen, get offering() { return !!offer; }, _decorate: decorate };
}
