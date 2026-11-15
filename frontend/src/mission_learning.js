// Mission-side learning beats (NASA Moon Learning & Media Plan v1), kept OUT of mission/ui.js (the mission-UI owner's
// file): main.js installs this next to the mission UI and it works through the DOM and the shell's navigation.
//   1. First mission only: before "Take command" flies, NASA's real Moon Base video ("NASA plans a real base near here.
//      Ours is pretend. Let's run it."). Shown once; Settings -> Help replays it (a11y.js). Watch or Skip; when the video
//      can't play (offline, no player) the mission simply starts.
//   2. Debrief: "Learn more" (learn_more.js: one NASA video per outcome, or a fact card) and, when this mission unlocked
//      an explorer lesson (explorer.js), a one-tap offer to open it.
// Nothing here ever blocks the mission: every path ends in the mission's own action.
import { MOON_BASE, LEARN_MORE, EXPLORER, callSign } from "./story.js";
import { isAvailable as videoState, openVideo as playVideo, getVideo, watchLabel } from "./media/video.js";   // docs/MEDIA.md
import { pickLearnMore } from "./learn_more.js";
import { markMissionFlown, missionsFlown, newlyUnlocked } from "./explorer.js";
import { icon } from "./assets/icons.js";
import "./mission_learning.css";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const get = k => { try { return localStorage.getItem(k); } catch (e) { return "1"; } };
const set = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } };

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
  // ---------- 1. the first-mission Moon Base offer ----------
  const cs = () => callSign.get() || "cadet";
  const seenKey = () => "outpost-moonbase-seen:" + cs();
  const firstMission = () => get("outpost-first-mission:" + cs()) !== "1" && missionsFlown(callSign.get()) === 0;
  const onPicker = () => { const f = missionUI.active && missionUI.screen && missionUI.screen(); return !!(f && f.screen === "brief" && f.offer === "take_command"); };
  const shouldOffer = () => !offer && get(seenKey()) !== "1" && firstMission() && onPicker();
  let offer = null;     // {el, done(watch)} while the card is up
  let bypass = false;

  async function offerThen(proceed) {
    const st = await videoState("moon_base_6mo");
    // only a saved copy (moon_base_6mo is pinned: downloaded on the first online launch): it starts at once, offline
    // too, and a run without the cache (tests: VIDEO_PREFETCH=0) never meets the card. Otherwise straight on.
    if (st !== "cached" || !onPicker()) { proceed(); return; }
    set(seenKey(), "1");
    const el = document.createElement("div");
    el.className = "ml-offer"; el.setAttribute("role", "dialog"); el.setAttribute("aria-labelledby", "mlOfferTitle");
    el.innerHTML = `<div class="ml-card"><p class="eyebrow">Briefing</p><h2 id="mlOfferTitle">${esc(MOON_BASE.title)}</h2>
      <p class="ml-line">${esc(MOON_BASE.line)}</p>
      <div class="ml-actions"><button type="button" class="btn-quiet" data-intent="no" id="mlSkip">${esc(MOON_BASE.skip)}</button>
      <button type="button" class="btn-primary" data-intent="yes" id="mlWatch">${icon("play", { size: 18 })}${esc(MOON_BASE.watch)}</button></div></div>`;
    document.body.append(el);
    offer = {
      el,
      async done(watch) {
        if (!offer) return;
        offer = null; el.remove();
        if (watch) { stop(); await playVideo("moon_base_6mo", { context: "first_mission" }); }
        proceed();
      },
    };
    el.querySelector("#mlWatch").onclick = () => offer && offer.done(true);
    el.querySelector("#mlSkip").onclick = () => offer && offer.done(false);
    el.querySelector("#mlWatch").focus({ preventScroll: true });
    Promise.resolve(say(MOON_BASE.line)).catch(() => {});
  }
  // a tap on Take command (the mission UI's own onclick runs after, through `bypass`)
  document.addEventListener("click", e => {
    const b = e.target && e.target.closest && e.target.closest("#mStart");
    if (!b || bypass || !shouldOffer()) return;
    e.preventDefault(); e.stopImmediatePropagation();
    offerThen(() => { bypass = true; try { b.click(); } finally { bypass = false; } });
  }, true);

  /** Voice / gestures / keys (main.js shellNav calls this before missionUI.nav). True when it took the intent. */
  function nav(intent, arg) {
    if (offer) {
      if (["accept_offer", "yes", "next"].includes(intent)) { offer.done(true); return true; }
      if (["decline_offer", "no", "take_command", "start", "skip_tour", "back"].includes(intent)) { offer.done(false); return true; }
      return false;
    }
    if (["take_command", "start", "next", "accept_offer"].includes(intent) && shouldOffer()) {
      offerThen(() => missionUI.nav(intent, arg));
      return true;
    }
    return false;
  }
  /** The router's screen frame while the card is up ("yes" watches, "no" skips). */
  const screen = () => (offer ? { screen: "brief", offer: "moon_base" } : null);

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
      const foot = host.querySelector(".mx-foot");
      if (foot) foot.before(sec); else host.append(sec);
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
