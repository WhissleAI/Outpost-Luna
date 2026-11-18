// Outpost Luna cabin: the Mission screen as the inside of a spacecraft, on one grid, read top to bottom:
//   1. the window (ORBIT on the NASA globe, SITE / ROVER / EARTH on LOLA terrain), with the clock, the view switcher,
//      the sky readout and, only when something is really wrong, an alert strip along its top edge;
//   2. three display units (POWER / LIFE / RADIATION by default; any of PWR LIFE RAD COMM per unit);
//   3. the controls: hab switches, rover, shield knob, caution & warning, Houston + END SHIFT (the one primary action);
//   4. the comm strip (captions + the ask dock, moved in by ui.js).
// Pure view: update(state), telemetry(frame), log(who, text), calling(on, ms), busy(on), alert(a), setView(v),
// clock(c) (the live clock's controls), card(c) (the Now task card), moment(beat), missionLog(entries).
// Every control is a <button> (or role=slider) whose aria-label states its state. An order that changes a control
// (by voice or by click) animates that control (.is-moved). Colours and sizes come from tokens.css only.
import { pretendLabel } from "../pretend.js";   // the "pretend tech" mark
import "../cabin.css";
import * as story from "../story.js";
const { callSign } = story;
import { LOADS } from "./cockpit.js";
import { icon, patch } from "../assets/icons.js";
import { normPatches, patchSig, newPatches, keyLabel, trackSummary, patchKeyHtml, patchListHtml } from "./patches.js";   // the cockpit's patch key
import { createCockpit3D, PANELS, RIDE_LAYOUT } from "./cockpit3d.js";
import { clockDay, clockSub, RIDE_PANELS } from "./ride.js";   // [0.3.12] the check ride's clock and panels
import { createTerrainView } from "./terrain.js";
import { whenViews, earthBelow, earthInsetHtml, earthPhoto, sun as realSun, loopFrames, preloadSun, flareOnCanvas, SUN_CREDIT, SUN_SOURCE } from "./cabin_views.js";   // [0.4] real NASA views (optional pack)

const DONKI = "https://kauai.ccmc.gsfc.nasa.gov/DONKI/";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/** Invented hardware gets a small mark glued to its label (src/pretend.js, docs/ACCURACY_AUDIT.md). */
const pretend = label => pretendLabel(label);
const clamp = (v, a = 0, b = 100) => Math.max(a, Math.min(b, +v || 0));
const deg = v => `${v >= 0 ? "+" : "−"}${Math.abs(+v || 0).toFixed(1)}°`;
const PAGES = [["PWR", "Power"], ["LIFE", "Life support"], ["RAD", "Radiation"], ["COMM", "Comms"]];
/** Window views: ORBIT is the globe, the others the LOLA terrain. */
export const VIEWS = [["orbit", "Orbit"], ["site", "Site"], ["rover", "Rover"], ["earth", "Earth"]];
const TASK = { collect_ice: "Ice run", explore: "Exploring", repair_array: "Array fix", return: "Heading home" };
const TOTAL_H = { collect_ice: 10, explore: 8, repair_array: 5, return: 5 };
/** Caution & warning: [id, legend, level, lit(state)]. Red = warning, amber = caution, blue = status (never an alarm). */
const LAMPS = [
  ["storm", "SOLAR STORM", "warn", s => !!(s.env.storm && s.env.storm.active)],
  ["watch", "STORM WATCH", "caution", s => !!stormWarning(s)],
  ["dose", "HIGH DOSE", "warn", s => (s.alerts || []).some(a => a === "dose_rate_high" || a === "dose_near_limit") || s.resources.dose_msv / (s.resources.dose_limit_msv || 50) > .7],
  ["power", "LOW POWER", "caution", s => (s.alerts || []).includes("low_power") || s.resources.power_pct < 25],
  ["life", "LOW AIR", "caution", s => (s.alerts || []).includes("life_support_low") || s.resources.life_support_pct < 25],
  ["array", "ARRAY DAMAGE", "caution", s => (s.alerts || []).includes("array_damaged")],
  ["shelter", "IN SHELTER", "info", s => !!s.shelter],
  ["rover", "ROVER OUT", "info", s => !!(s.rover && s.rover.busy)],
];
/** A storm forecast, if the sim sends one (the game redesign: lead time + confidence). Accepts env.storm_warning or
 *  env.storm_forecast with lead_h | eta_h, confidence | probability (0–1 or %), real_date, source. null when none. */
export function stormWarning(s) {
  const w = s && s.env && (s.env.warning || s.env.storm_warning || s.env.storm_forecast);
  if (!w || w.active === false || (s.env.storm && s.env.storm.active)) return null;
  // the sim sends a word ("likely" | "possible"); older shapes sent a number (0-1 or %)
  const c = w.confidence ?? w.probability, num = typeof c === "number" ? c : (c != null && c !== "" && !isNaN(+c) ? +c : null);
  const conf = num == null ? null : Math.round(num > 1 ? num : num * 100);
  const word = typeof c === "string" && isNaN(+c) ? c[0].toUpperCase() + c.slice(1) : null;
  return { lead: w.lead_h ?? w.eta_h ?? null, conf, word, date: w.real_date || null, source: w.source || "DONKI", name: w.name || "", by: w.by || null };
}
/** Hab switches: [id, label, guarded, on(state), command(on)] */
const SWITCHES = [
  ["shelter", "Shelter", true, s => !!s.shelter, on => ({ type: "shelter", on })],
  ["heaters", "Heaters", false, s => (s.loads.heaters || 0) >= 8, on => ({ type: "allocate", to: "heaters", amount: { kind: "percent", value: on ? 15 : 0 }, from: null })],
  ["science", "Science", false, s => (s.loads.science || 0) > 0, on => ({ type: "allocate", to: "science", amount: { kind: "percent", value: on ? 15 : 0 }, from: null })],
];
const ROVER = [["collect_ice", "Ice", "ice"], ["explore", "Explore", "explore"], ["return", "Home", "outpost"]];
const ic = (n, size = 18) => icon(n, { size });
/** The "Why?" cards (docs/PHYSICS.md): one small button per gauge; the card's words come from the sim (state.why). */
export const WHY = { power: "Solar power", battery: "Battery", life_support: "Life support", dose: "Radiation dose", heaters: "Heaters",
  shields: "Shields", rover: "Rover and ice" };
const whyBtn = id => `<button type="button" class="cb-whyb" data-why="${id}" aria-label="Why? ${esc(WHY[id])}" title="Why?">${icon("info", { size: 14 })}</button>`;
/** Engineer mode (Settings → Level): gauges in real units, from state.units (physics.py). */
const kw = v => `${(+v || 0).toFixed(Math.abs(+v || 0) < 10 ? 1 : 0)} kW`;
const VIEW_ICON = { orbit: "orbit", site: "site", rover: "rover", earth: "earth" };

/** [0.4] The app header folds into the cockpit's own top bar while a cabin is on screen (the mission cabin and the
 *  check ride): the header's sections and icons stay the same nodes (keyboard path, Mute next to Settings, the tests'
 *  selectors), drawn over the two ends of the cabin's deck as bezel keys (cabin.css "[0.4]"), and the deck leaves room
 *  for them. One owner at a time (the newest cabin); dispose gives the header back. -> off() */
let foldOwner = null;
export function foldHeader(root, o = {}) {
  const tb = document.querySelector(".topbar"), deck = root.querySelector(".cb-deck"); if (!tb || !deck) return () => {};
  const me = {}, html = document.documentElement, vis = e => !!(e && e.getClientRects().length);
  foldOwner = me; document.body.dataset.cockpit = "1";
  const place = () => {
    if (foldOwner !== me || !deck.isConnected) return;
    html.style.setProperty("--cockpit-right", Math.max(0, Math.round(+(o.insetRight ? o.insetRight() : 0) || 0)) + "px");
    const D = deck.getBoundingClientRect(); if (!D.width) return;
    const left = [...tb.querySelectorAll(".brand, .modes")].filter(vis).reduce((m, e) => Math.max(m, e.getBoundingClientRect().right), D.left);
    const nav = tb.querySelector(".topnav"), right = vis(nav) ? nav.getBoundingClientRect().left : D.right;
    deck.style.setProperty("--cp-l", Math.max(0, Math.round(left - D.left)) + "px");
    deck.style.setProperty("--cp-r", Math.max(0, Math.round(D.right - right)) + "px");
  };
  const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => requestAnimationFrame(place)) : null;
  if (ro) { ro.observe(tb); ro.observe(deck); [...tb.children].forEach(c => ro.observe(c)); }
  addEventListener("resize", place); requestAnimationFrame(place); setTimeout(place, 400);
  return () => {
    if (ro) ro.disconnect(); removeEventListener("resize", place);
    if (foldOwner === me) { foldOwner = null; delete document.body.dataset.cockpit; html.style.removeProperty("--cockpit-right"); }
  };
}

export function createCabin(root, o = {}) {
  const cb = { onCommand() {}, onHouston() {}, onEndShift() {}, onDebrief() {}, onView() {}, onClock() {}, onTask() {}, badges: () => [], ...o };
  let view = "site", st = null, prev = null, pages = ["PWR", "LIFE", "RAD"], sel = 0, logLines = [], litBefore = new Set(), masterOn = false;
  let flash = null, flashT = null;
  const guards = { shelter: false };

  const sw = id => { const [, label, guarded] = SWITCHES.find(x => x[0] === id); return `
          <div class="cb-sw" data-sw="${id}">
            <div class="cb-swbox">
              <button type="button" class="cb-toggle" data-sw="${id}" aria-pressed="false" aria-label="${esc(label)}"><i aria-hidden="true"></i></button>
              ${guarded ? `<button type="button" class="cb-guard" data-guard="${id}" aria-pressed="false" aria-label="${esc(label)} cover: closed">${ic("lock", 16)}</button>` : ""}
            </div>
            <span class="cb-swl">${esc(label)}${id === "heaters" ? whyBtn("heaters") : ""}</span><span class="cb-swst" aria-hidden="true"></span>
          </div>`; };
  root.innerHTML = `
  <div class="cb">
    <header class="cb-deck" aria-label="Mission clock">
      <div class="cb-dsp" role="group" aria-label="Mission status">
        <div class="cb-dsp-a">
          <div class="cb-clock" id="cbClock"></div>
          ${o.mode === "ride" ? "" : `<span class="cb-state" id="cbState"><i aria-hidden="true"></i><span id="cbHeld" role="status" aria-live="polite"></span></span>`}
          <div class="cb-sky" id="cbSky" aria-label="Sky"></div>
        </div>
        ${o.mode === "ride" ? "" : `<div class="cb-prog" id="cbProg" aria-label="Mission progress"></div>`}
      </div>
      ${o.mode === "ride" ? "" : `<div class="cb-time" id="cbTime" role="group" aria-label="Mission clock controls" data-state="paused">
        <button type="button" class="cb-tbtn cb-play" id="cbPlay" aria-label="Start the clock">${ic("play", 18)}<span>Play</span></button>
        <button type="button" class="cb-tbtn cb-skip" id="cbSkip" aria-label="Skip ahead to the next event. Hold to fast-forward." title="Tap: skip ahead (E). Hold: fast-forward (hold F)">${ic("next", 18)}<span>Skip</span></button>
        <button type="button" class="cb-tbtn cb-menub" id="cbMenuBtn" aria-haspopup="dialog" aria-label="Menu: speed, restart, settings" title="Menu (Esc)">${ic("menu", 18)}<span>Menu</span></button>
      </div>`}
    </header>
    <section class="cb-mlog" id="cbMlog" hidden aria-label="Mission log"></section>
    <div class="cb-viewbar" aria-label="Window">
      <div class="cb-views" role="group" aria-label="Window view">${VIEWS.map(([id, n]) => `<button type="button" class="cb-view" data-view="${id}" aria-pressed="${id === "site"}">${ic(VIEW_ICON[id], 16)}<span>${n}</span></button>`).join("")}</div>
      ${o.mode === "ride" ? "" : `<button type="button" class="cb-center" id="cbCenter" aria-keyshortcuts="R" title="Center view (R)">${ic("site", 16)}<span>Center view</span></button>`}
    </div>
    <section class="cb-now" id="cbNow" hidden aria-label="Now">
      <div class="cb-now-head"><b class="cb-now-l">${esc((story.NOW || {}).label || "Now")}</b><span class="cb-now-title" id="cbNowTitle"></span>
        <button type="button" class="cb-now-fold" id="cbNowFold" aria-expanded="true" aria-controls="cbNowMore" aria-label="Fold the Now panel">${ic("chevron-up", 16)}</button></div>
      <p class="cb-now-step" id="cbNowT" role="status" aria-live="polite"></p>
      <div class="cb-now-more" id="cbNowMore"></div>
    </section>
    <section class="cb-window" aria-label="Window">
      <div class="cb-glass" data-view="site">
        <div class="cb-tint" aria-hidden="true"></div>
        <div class="cb-alert" id="cbAlert" hidden role="alert"></div>
        <div class="cb-moment" id="cbMoment" hidden aria-hidden="true"></div>
        <p class="cb-earthnote" id="cbEarthNote" hidden role="status"></p>
        <div class="cb-rover" id="cbRover" hidden></div>
      </div>
    </section>

    <section class="cb-dus" data-panel="displays" aria-label="Displays">${[0, 1, 2].map(d => `
      <div class="cb-du" data-du="${d}">
        <div class="cb-screen" id="cbDu${d}"></div>
        ${d === 0 ? `<div class="cb-keys" role="group" aria-label="Power to the selected system"><span class="cb-acts" id="cbAct0"></span></div>` : ""}
      </div>`).join("")}
    </section>

    <section class="cb-controls" aria-label="Controls">
      <div class="cb-grp" data-panel="habitat" role="group" aria-label="Habitat panel">
        <div class="cb-plate cb-hab"><h3>Habitat</h3><div class="cb-info" id="cbInfoHab"></div><div class="cb-sws">${sw("heaters")}${sw("science")}${o.mode === "ride" ? "" : `<div class="cb-patchrow"><button type="button" class="cb-patchkey" id="cbPatchKey" hidden aria-haspopup="dialog" aria-expanded="false" aria-controls="cbPatchPop" title="Your patches"></button><span class="cb-vh" id="cbPatchNews" role="status" aria-live="polite"></span></div>`}</div><ol class="cb-obj" id="cbObj" hidden></ol></div>
      </div>
      <div class="cb-grp" data-panel="rover" role="group" aria-label="Rover panel">
        <div class="cb-plate cb-rv"><h3>Rover</h3>
          <div class="cb-rvrow"><span class="cb-rvst" id="cbRvSt"></span>${whyBtn("rover")}</div>
          <div class="cb-seg">${ROVER.map(([t, n, i]) => `<button type="button" class="cb-rvb" data-task="${t}" aria-pressed="false">${ic(i, 16)}<span>${n}</span></button>`).join("")}</div>
          <svg class="cb-route" id="cbRoute" viewBox="0 0 200 64" aria-hidden="true"></svg>
          <div class="cb-info" id="cbInfoRv"></div>
        </div>
      </div>
      <div class="cb-grp" data-panel="radiation" role="group" aria-label="Radiation panel">
        <div class="cb-plate cb-shield"><h3>Radiation</h3><div class="cb-radtop"><div class="cb-info" id="cbInfoRad"></div>
          <figure class="cb-sunmon" id="cbSunMon" hidden><span class="cb-sun-disc" style="--fx:${(flareOnCanvas()[0] * 100).toFixed(1)}%;--fy:${(flareOnCanvas()[1] * 100).toFixed(1)}%"><canvas class="cb-sun-cv" width="320" height="320" role="img" aria-label="The Sun in extreme ultraviolet on 14 May 2024, the day of a huge flare (NASA SDO)"></canvas><i class="cb-sun-ring" aria-hidden="true"></i><em class="cb-sun-tag" aria-hidden="true">X8.7 flare</em></span>
            <figcaption><b>${esc(SUN_CREDIT.split(", ")[0])},</b><span>${esc(SUN_CREDIT.split(", ").slice(1).join(", "))} · ${esc(SUN_SOURCE)}</span><span class="cb-sun-time"></span></figcaption></figure></div>
          <div class="cb-radrow">${sw("shelter")}
          <div class="cb-knobrow">
            <span class="cb-shl">${pretend("Shields")}${whyBtn("shields")}</span>
            <button type="button" class="cb-mini" id="cbShMinus" aria-label="Shields down 10">−</button>
            <div class="cb-knob" id="cbKnob" role="slider" tabindex="0" aria-label="Shield power" aria-valuemin="0" aria-valuemax="60" aria-valuenow="0">
              <svg viewBox="0 0 80 80" aria-hidden="true"><circle class="k-track" cx="40" cy="40" r="32" pathLength="100"/><circle class="k-val" id="cbKval" cx="40" cy="40" r="32" pathLength="100"/></svg>
              <b id="cbShVal">0</b><small>%</small>
            </div>
            <button type="button" class="cb-mini" id="cbShPlus" aria-label="Shields up 10">+</button>
          </div></div>
        </div>
      </div>
      <div class="cb-grp" data-panel="pedestal" role="group" aria-label="Caution and warning, end shift">
        <div class="cb-plate cb-cw"><h3>Caution &amp; warning</h3>
          <button type="button" class="cb-master" id="cbMaster" aria-label="Master alarm: off">Master alarm</button>
          <div class="cb-lamps" role="list">${LAMPS.map(([id, t, lvl]) => `<span class="cb-lamp is-${lvl}" id="cbl-${id}" role="listitem">${t}<span class="cb-vh">: off</span></span>`).join("")}</div>
        </div>
        <div class="cb-plate cb-ped">
          <button type="button" class="cb-end" id="cbEnd"><span>${o.mode === "ride" ? "End shift" : "End shift early"}</span><small id="cbEndSub"></small></button>
          <button type="button" class="cb-db" id="cbDb">See debrief</button>
        </div>
      </div>
      <div class="cb-grp" data-panel="comm" role="group" aria-label="Comm panel">
        <div class="cb-plate cb-comm"><h3>Comm</h3><div class="cb-tl" id="cbCommTl" aria-hidden="true"></div><div class="cb-info" id="cbInfoComm"></div><ul class="cb-fc" id="cbFc" hidden></ul>
          <button type="button" class="cb-ptt" id="cbPtt" aria-label="Call Houston"><span class="cb-ptt-t">${ic("houston", 18)}<span>Call Houston</span></span><small id="cbPttSub"></small><i class="cb-trip" aria-hidden="true"></i></button>
        </div>
      </div>
    </section>

    <aside class="cb-why" id="cbWhy" hidden role="dialog" aria-modal="false" aria-labelledby="cbWhyT">
      <header><b id="cbWhyT"></b><button type="button" class="cb-why-x" id="cbWhyX" aria-label="Close the Why card">${ic("close", 14)}</button></header>
      <p class="cb-why-text" id="cbWhyText" aria-live="polite"></p>
      <p class="cb-why-f" id="cbWhyF"></p><p class="cb-why-eq" id="cbWhyEq"></p>
      <p class="cb-why-src" id="cbWhySrc"></p>
    </aside>
    ${o.mode === "ride" ? "" : `<section class="cb-patchpop" id="cbPatchPop" hidden role="dialog" aria-modal="false" aria-labelledby="cbPatchPopT">
      <header><b id="cbPatchPopT">Your patches</b><button type="button" class="cb-patchpop-x" id="cbPatchPopX" aria-label="Close your patches">${ic("close", 16)}</button></header>
      <p class="cb-patchsum" id="cbPatchSum"></p>
      <ul class="cb-patchlist" id="cbPatchList"></ul>
    </section>`}
    <section class="cb-commrow" aria-label="Radio">
      <div class="cb-capwrap"><p class="cb-caption" id="cbCap"><b id="cbCapWho">CAPCOM</b> <span id="cbCapTxt">Standing by.</span></p><div class="cb-capslot" id="cbCapSlot"></div></div>
      <div class="cb-askslot" id="cbAskSlot" role="group" aria-label="Talk to CAPCOM"></div>
    </section>
    ${o.mode === "ride" ? "" : `<div class="cb-pm" id="cbMenu" hidden role="dialog" aria-modal="true" aria-labelledby="cbMenuT">
      <div class="cb-pm-box">
        <header><p class="cb-pm-eye" id="cbMenuEye"></p><h2 id="cbMenuT">Paused</h2></header>
        <button type="button" class="cb-pm-b is-hot" data-m="resume">${ic("play", 20)}<span>Resume</span><kbd>Esc</kbd></button>
        <div class="cb-pm-speed" role="group" aria-label="Time speed"><span>${ic("speed", 20)}Time speed</span>
          <span class="cb-pm-seg">${[1, 2, 4].map(w => `<button type="button" class="cb-pm-sp" data-m="speed" data-warp="${w}" aria-pressed="${w === 1}" aria-label="Time speed ${w} times">${w}×</button>`).join("")}</span></div>
        <button type="button" class="cb-pm-b" data-m="restart">${ic("replay", 20)}<span>Restart shift</span><small id="cbMenuShift"></small></button>
        <button type="button" class="cb-pm-b" data-m="settings">${ic("settings", 20)}<span>Settings</span></button>
        <button type="button" class="cb-pm-b" data-m="quit">${ic("home", 20)}<span>Quit to hub</span><small>Your mission saves</small></button>
        <p class="cb-pm-tip">Hold <kbd>F</kbd>, hold <b>Skip</b> or hold <kbd>RT</kbd> to fast-forward.</p>
      </div>
    </div>
    <div class="cb-ch" id="cbChapter" hidden role="dialog" aria-modal="true" aria-labelledby="cbChT">
      <div class="cb-ch-box">
        <p class="cb-ch-eye" id="cbChEye"></p>
        <h2 id="cbChT"></h2>
        <ul class="cb-ch-stars" id="cbChStars" aria-label="Stars"></ul>
        <p class="cb-ch-cap"><b>CAPCOM</b> <span id="cbChCap"></span></p>
        <p class="cb-ch-saved">${ic("check", 16)}<span>Saved. You can quit and pick up here.</span></p>
        <button type="button" class="cb-pm-b is-hot" id="cbChGo">${ic("play", 20)}<span id="cbChGoT">Next chapter</span><kbd>Enter</kbd></button>
      </div>
    </div>`}
  </div>`;
  const q = s => root.querySelector(s);
  const glassEl = q(".cb-glass");
  // only what belongs to the view rides on the glass; the clock, the controls and the Now panel are the cabin's own
  const HUD = [".cb-alert", ".cb-rover", ".cb-moment", ".cb-earthnote"];

  // ---- 3D cabin (cockpit3d.js): the panels above become real DOM mounted on the console faces; flat grid if no WebGL ----
  let c3 = null, qualityOff = () => {}, escOff = () => {}, ownTv = null;
  if (o.terrain && o.site) {
    const tvHost = document.createElement("div"); tvHost.className = "tv"; glassEl.prepend(tvHost);
    ownTv = createTerrainView(tvHost, { reduced: () => document.documentElement.dataset.motion === "reduce" });
    if (ownTv) { Promise.resolve(ownTv.setSite(o.site)).then(() => ownTv.setView("site")).catch(() => {}); }
  }
  const reducedMo = () => document.documentElement.dataset.motion === "reduce" || !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  if (o.mode3d !== false && document.documentElement.dataset.quality !== "low") {
    const cabEl = q(".cb"), host = document.createElement("div"); host.className = "c3";
    const holeEl = document.createElement("div"); holeEl.className = "cb-hole";
    HUD.forEach(sel => { const n = q(sel); if (n) holeEl.append(n); });
    const backEl = document.createElement("button"); backEl.type = "button"; backEl.className = "c3-back"; backEl.hidden = true; backEl.innerHTML = `${ic("back", 18)}<span>Seat</span>`;
    backEl.setAttribute("aria-label", "Back to the seat view");
    cabEl.classList.add("is-3d"); cabEl.prepend(host); cabEl.append(holeEl, backEl);
    const ids = RIDE_PANELS[o.mode] || ["displays", "habitat", "rover", "radiation", "pedestal", "comm"];
    const panelEls = Object.fromEntries(ids.map(k => [k, q(`[data-panel="${k}"]`)]));
    if (o.mode === "ride") { root.classList.add("is-ride"); ["habitat", "comm"].forEach(k => { const el = q(`[data-panel="${k}"]`); if (el) el.hidden = true; }); }
    c3 = createCockpit3D(host, { panels: panelEls, hole: holeEl, glass: glassEl, reduced: reducedMo, insetRight: o.insetRight, layout: o.mode === "ride" ? RIDE_LAYOUT : null, onPanel: id => { backEl.hidden = !id; cb.onPanel && cb.onPanel(id); } });
    if (!c3) { cabEl.classList.remove("is-3d"); host.remove(); backEl.remove(); HUD.forEach(sel => { const n = holeEl.querySelector(sel); if (n) glassEl.append(n); }); holeEl.remove(); }
    else {
      // graphics quality (Settings): "low" = fewer lights, no reflections, 1× pixels
      // Settings (prefs.js) writes <html data-graphics="high|low">; follow it live
      const html = document.documentElement, applyQ = () => c3 && c3.setQuality(html.dataset.graphics === "low" ? "low" : "high"); applyQ();
      const mo = new MutationObserver(applyQ); mo.observe(html, { attributes: true, attributeFilter: ["data-graphics"] }); qualityOff = () => mo.disconnect();
      backEl.onclick = () => c3.back();
      // [qa] root (#mCabin) outlives this cabin: the listener is removed in dispose(), or every rebuilt cabin stays alive
      const onEsc = e => { if (e.key === "Escape" && c3 && c3.panel) { e.preventDefault(); c3.back(); } };
      root.addEventListener("keydown", onEsc); escOff = () => root.removeEventListener("keydown", onEsc);
      Object.entries(panelEls).forEach(([id, el]) => {
        el.classList.add("c3-panel"); el.dataset.label = (PANELS.find(p => p[0] === id) || [])[1] || "";
        // the displays: a click on DU1 opens the Power panel (DU1 + the power split); elsewhere it opens all three
        const target = e => id === "displays" ? (e.target.closest('[data-du="0"]') ? "power" : "displays") : id;
        // seat view: a click on a panel opens it (the camera dollies in); a control works once its panel is open
        el.addEventListener("click", e => { const t = target(e); if (c3.panel !== t && !(t === "power" && c3.panel === "displays")) { e.preventDefault(); e.stopPropagation(); c3.open(t); } }, true);
        // keyboard: tabbing into a panel opens it, so the focused control is always big and on screen
        el.addEventListener("focusin", e => { const t = target(e); if (c3.panel !== t && !(t === "power" && c3.panel === "displays")) c3.open(t); });
      });
    }
  }

  // ---- [0.4] the app header folds into the cockpit's top bar; the real NASA views arrive when the pack is installed ----
  const foldOff = foldHeader(root, o);
  // [0.4 cabin 2] the SDO frames are toned and cached as soon as the pack is in, so a storm's Sun is never dark
  const viewsOff = whenViews(() => { earthKey = ""; alertKey = ""; sunMonOn = false; const sv = realSun(); if (sv) preloadSun(sv.frames); if (st) { paintEarthNote(); paintAlert(); } });

  // ---- window view switcher ----
  function setView(v, quiet) {
    view = v; root.querySelectorAll(".cb-view").forEach(b => b.setAttribute("aria-pressed", b.dataset.view === v));
    glassEl.dataset.view = v;
    paintEarthNote();
    if (!quiet) cb.onView(v);
  }
  /** [playtest 20] The Earth view with Earth below the horizon: say so, and when it rises (Horizons, the sim's own
   *  comm windows), instead of a grey slope and a black sky with no words. */
  // [0.4] with the nasa_views pack the note is a small inset: the real Earthrise (Apollo 8) or Earthset (Artemis II)
  // photo, "Earth rises Day N", and an arrow with the elevation and its trend (the sim's Horizons numbers)
  let earthEl0 = null, earthTrend = null, earthKey = "";
  function paintEarthNote() {
    const n = q("#cbEarthNote"); if (!n) return;
    const e = (st && st.env) || {}, show = view === "earth" && !!st && !e.earth_visible;
    n.hidden = !show; if (!show) { earthKey = ""; return; }
    const info = earthBelow(e, st.mission_time_h || 0, earthTrend);
    const photo = info ? earthPhoto(info.photo) : null;
    n.classList.toggle("is-inset", !!photo);
    const key = JSON.stringify([info.line, info.trend, info.el != null ? info.el.toFixed(1) : null, photo && photo.url]);
    if (key === earthKey) return; earthKey = key;   // the photo is not reloaded every second
    n.innerHTML = earthInsetHtml(info, photo, ic);
  }
  function trackEarth(el) { if (el == null) return; if (earthEl0 != null && Math.abs(el - earthEl0) > 0.005) earthTrend = earthEl0; earthEl0 = +el; }
  root.querySelectorAll(".cb-view").forEach(b => b.onclick = () => setView(b.dataset.view));
  if (q("#cbCenter")) q("#cbCenter").onclick = () => { if (c3) c3.recenter(); setView("site"); cb.onCenter && cb.onCenter(); };
  const offT = setInterval(() => { const cab = root.querySelector(".cb"); if (!cab || !c3) return; const p = c3.pose;
    const off = Math.abs(p.yaw) > 0.02 || Math.abs(p.pitch) > 0.02 || (p.panel && p.panel !== "seat");
    // back at the seat after a look or a dolly: re-fit the Now panel against where the consoles really are
    if (!off && !p.moving && cab.dataset.offcentre === "1") fitNow();
    cab.dataset.offcentre = off ? "1" : ""; }, 300);

  // ---- display softkeys ----
  root.querySelectorAll(".cb-sk[data-page]").forEach(b => b.onclick = () => { pages[+b.dataset.du] = b.dataset.page; paintDus(); });

  // ---- hab switches (the shelter sits under a cover: lift it, then flip) ----
  root.querySelectorAll(".cb-guard").forEach(g => g.onclick = () => { const id = g.dataset.guard; guards[id] = !guards[id]; paintSwitches(); if (guards[id]) q(`.cb-toggle[data-sw="${id}"]`).focus(); });
  root.querySelectorAll(".cb-toggle").forEach(b => b.onclick = () => {
    const id = b.dataset.sw, S = SWITCHES.find(l => l[0] === id); if (!st) return;
    if (S[2] && !guards[id]) { const g = q(`[data-guard="${id}"]`); g.classList.remove("is-nudge"); void g.offsetWidth; g.classList.add("is-nudge"); return; }
    cb.onCommand(S[4](!S[3](st))); if (S[2]) guards[id] = false;
  });

  // ---- rover ----
  root.querySelectorAll(".cb-rvb").forEach(b => b.onclick = () => st && cb.onCommand({ type: "dispatch", vehicle: "rover", task: b.dataset.task, target: null }));

  // ---- shield knob ----
  const shield = d => st && cb.onCommand({ type: "allocate", to: "shields", amount: { kind: "percent", value: clamp(Math.round(((st.loads.shields || 0) + d) / 10) * 10, 0, 60) }, from: null });
  q("#cbShMinus").onclick = () => shield(-10); q("#cbShPlus").onclick = () => shield(10);
  q("#cbKnob").addEventListener("keydown", e => { const d = { ArrowRight: 10, ArrowLeft: -10, PageUp: 10, PageDown: -10 }[e.key]; if (d) { e.preventDefault(); e.stopPropagation(); shield(d); } });
  q("#cbKnob").addEventListener("click", e => { const r = e.currentTarget.getBoundingClientRect(); shield(e.clientX > r.left + r.width / 2 ? 10 : -10); });

  // ---- master alarm, Houston, end shift ----
  q("#cbMaster").onclick = () => { masterOn = false; paintMaster(); };
  q("#cbPtt").onclick = () => cb.onHouston();
  q("#cbEnd").onclick = () => cb.onEndShift();
  // ---- the live clock: play / pause, time warp, skip to next event (mission/clock.js owns the timing) ----
  if (q("#cbPlay")) {
    q("#cbPlay").onclick = () => cb.onClock("toggle");
    // [polish 2] Skip ahead: a tap skips to the next event; a hold fast-forwards until you let go
    const sk = q("#cbSkip"); let holdT = 0, held = false, swallow = false;
    const up = () => { clearTimeout(holdT); if (held) { held = false; swallow = true; cb.onClock("ff:off"); } };
    sk.addEventListener("pointerdown", e => { if (e.button) return; swallow = false; holdT = setTimeout(() => { held = true; cb.onClock("ff:on"); }, 320); });
    ["pointerup", "pointerleave", "pointercancel", "blur"].forEach(ev => sk.addEventListener(ev, up));
    sk.onclick = () => { if (swallow) { swallow = false; return; } cb.onClock("skip"); };   // a hold's release isn't a tap
    q("#cbMenuBtn").onclick = () => (cb.onMenu || (() => {}))("open");
    root.querySelectorAll("#cbMenu [data-m]").forEach(b => b.onclick = () => (cb.onMenu || (() => {}))(b.dataset.m, b.dataset.warp));
    q("#cbChGo").onclick = () => (cb.onChapter || (() => {}))("go");
  }
  if (q("#cbProg")) q("#cbProg").addEventListener("click", e => { if (e.target.closest(".cb-logbtn")) toggleLog(); });
  // the Now panel folds to its one line (title + the step), remembered on this device
  let folded = false; try { folded = localStorage.getItem("outpost-now-folded") === "1"; } catch (e) { /* blocked */ }
  const paintFold = () => { const n = q("#cbNow"), b = q("#cbNowFold"); n.classList.toggle("is-folded", folded); b.setAttribute("aria-expanded", String(!folded));
    b.setAttribute("aria-label", folded ? "Open the Now panel" : "Fold the Now panel"); b.innerHTML = ic(folded ? "chevron-down" : "chevron-up", 16); };
  q("#cbNowFold").onclick = () => { folded = !folded; try { localStorage.setItem("outpost-now-folded", folded ? "1" : "0"); } catch (e) { /* blocked */ } paintFold(); };
  paintFold();
  q("#cbDb").onclick = () => cb.onDebrief();

  function paintMaster() {
    const m = q("#cbMaster"); m.classList.toggle("is-lit", masterOn); m.setAttribute("aria-label", `Master alarm: ${masterOn ? "on. Press to reset" : "off"}`);
    glassEl.classList.toggle("is-alarm", masterOn);
  }

  // ---- "Why?" cards: tap a gauge's (i), press I, or ask "why is power low?" (docs/PHYSICS.md) ----
  let whyId = null, whyT = null, whyFrom = null;
  function whyCard(id) { return st && st.why && st.why[id] ? st.why[id] : null; }
  function placeWhy() {
    const el = q("#cbWhy"), vb = q(".cb-viewbar"), cab = q(".cb"); if (!el || el.hidden || !cab) return;
    const C = cab.getBoundingClientRect(), V = vb && vb.getClientRects().length ? vb.getBoundingClientRect() : null;
    el.style.top = `${Math.round((V ? V.bottom : C.top + 120) - C.top + 8)}px`;
    el.style.right = `${Math.round(V ? C.right - V.right : 16)}px`;
  }
  function paintWhy() {
    const el = q("#cbWhy"); if (!el || el.hidden || !whyId) return;
    const c = whyCard(whyId); if (!c) { closeWhy(); return; }
    q("#cbWhyT").innerHTML = c.pretend ? pretend(c.title) : esc(c.title);
    if (q("#cbWhyText").textContent !== c.text) q("#cbWhyText").textContent = c.text;
    const f = q("#cbWhyF"), eq = q("#cbWhyEq");
    f.textContent = c.formula || ""; f.hidden = !c.formula;
    eq.textContent = st && st.engineer && c.eng ? c.eng : ""; eq.hidden = !(st && st.engineer && c.eng);   // Engineer: the equation, with numbers
    const srcs = c.sources && c.sources.length ? c.sources : c.source ? [c.source] : [];
    q("#cbWhySrc").innerHTML = srcs.length ? "Source: " + srcs.map(x => `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title)}</a>`).join(" · ") : "";
  }
  function openWhy(id, from) {
    const c = whyCard(id); if (!c) return null;
    whyId = id; whyFrom = from; const el = q("#cbWhy"); el.hidden = false; el.dataset.why = id;
    paintWhy(); placeWhy();
    root.querySelectorAll(".cb-whyb.is-open").forEach(n => n.classList.remove("is-open"));
    root.querySelectorAll(`.cb-whyb[data-why="${id}"]`).forEach(n => n.classList.add("is-open"));
    clearTimeout(whyT); whyT = setTimeout(closeWhy, 20000);   // it goes away by itself; the kid can close it sooner
    if (from === "key") requestAnimationFrame(() => { const x = q("#cbWhyX"); if (x) x.focus({ preventScroll: true }); });
    return c;
  }
  function closeWhy() {
    clearTimeout(whyT); const el = q("#cbWhy"); if (!el || el.hidden) return;
    const back = root.querySelector(`.cb-whyb[data-why="${whyId}"]`), had = el.contains(document.activeElement);
    el.hidden = true; whyId = null; root.querySelectorAll(".cb-whyb.is-open").forEach(n => n.classList.remove("is-open"));
    // keyboard / controller: focus goes back to the (i) it came from (a tap or a voice ask leaves focus alone, so the
    // seat view never dollies into a console just because a card closed)
    if (had && back && whyFrom === "key") back.focus({ preventScroll: true });
  }
  q("#cbWhyX").onclick = () => closeWhy();
  q("#cbWhy").addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closeWhy(); } });
  // capture on the root: a tap on (i) opens its card even in the seat view (where a tap on a console opens the console)
  const onWhyTap = e => { const b = e.target.closest && e.target.closest("[data-why]"); if (!b || !root.contains(b)) return;
    e.preventDefault(); e.stopPropagation(); const c = whyId === b.dataset.why ? (closeWhy(), null) : openWhy(b.dataset.why, e.detail === 0 ? "key" : "tap"); if (c) cb.onWhy && cb.onWhy(c, "tap"); };   // detail 0: Enter or a controller A
  // [qa] root (#mCabin) outlives this cabin: both listeners go in dispose()
  root.addEventListener("click", onWhyTap, true); addEventListener("resize", placeWhy);
  const whyOff = () => { root.removeEventListener("click", onWhyTap, true); removeEventListener("resize", placeWhy); clearTimeout(whyT); };

  // ---- earned patches (Flight School + Field School): a key on the display unit, a card that names them ----
  // The Academy hands its badges() over (academy/ui.js); a patch earned while the cabin is up repaints at once
  // ("outpost:patches"), and update() re-checks now and then (a mode switch can land a patch behind the cabin).
  let patchList = [], patchAt = 0;
  function paintPatches(force) {
    const key = q("#cbPatchKey"); if (!key) return;
    let now = []; try { now = normPatches(cb.badges()); } catch (e) { now = []; }
    patchAt = Date.now();
    if (!force && patchSig(now) === patchSig(patchList)) return;
    const fresh = patchList.length || force === "earned" ? newPatches(patchList, now) : [];
    patchList = now;
    key.hidden = !now.length;
    key.innerHTML = patchKeyHtml(now, { patch, esc });
    key.setAttribute("aria-label", keyLabel(now.length));
    if (fresh.length) {
      const last = fresh[fresh.length - 1];
      q("#cbPatchNews").textContent = `New patch: ${last.name}`;
      key.classList.remove("is-new"); void key.offsetWidth; key.classList.add("is-new");
    }
    if (!now.length) closePatches();
    paintPatchPop();
  }
  function paintPatchPop() {
    const pop = q("#cbPatchPop"); if (!pop || pop.hidden) return;
    q("#cbPatchSum").textContent = trackSummary(patchList);
    q("#cbPatchList").innerHTML = patchListHtml(patchList, { patch, esc });
  }
  function openPatches(fromKey) {
    const pop = q("#cbPatchPop"), key = q("#cbPatchKey"); if (!pop || !patchList.length) return;
    pop.hidden = false; key.setAttribute("aria-expanded", "true"); key.classList.add("is-open"); paintPatchPop(); placePatches();
    if (fromKey) { const x = q("#cbPatchPopX"); if (x) x.focus({ preventScroll: true }); }   // shown now: focus moves at once
  }
  /** The card sits beside its key (the Habitat console, wherever the camera has it), inside the cabin, under the deck. */
  function placePatches() {
    const pop = q("#cbPatchPop"), key = q("#cbPatchKey"), cab = q(".cb"); if (!pop || pop.hidden || !cab) return;
    const K = key.getBoundingClientRect(), C = cab.getBoundingClientRect(), w = pop.offsetWidth || 380, h = pop.offsetHeight || 300;
    const deck = q(".cb-deck"), top0 = deck ? deck.getBoundingClientRect().bottom - C.top + 12 : 12;
    const right = K.right - C.left + 12 + w <= C.width - 12, x = right ? K.right - C.left + 12 : K.left - C.left - 12 - w;
    pop.style.left = Math.round(Math.max(12, Math.min(x, C.width - w - 12))) + "px";
    pop.style.top = Math.round(Math.max(top0, Math.min(K.bottom - C.top - h, C.height - h - 12))) + "px";
  }
  function closePatches(back) {
    const pop = q("#cbPatchPop"), key = q("#cbPatchKey"); if (!pop || pop.hidden) return;
    pop.hidden = true; key.setAttribute("aria-expanded", "false"); key.classList.remove("is-open");
    if (back) key.focus({ preventScroll: true });
  }
  let patchOff = () => {};
  if (q("#cbPatchKey")) {
    const togglePatches = byKey => (q("#cbPatchPop").hidden ? openPatches(byKey) : closePatches(byKey));
    q("#cbPatchKey").onclick = e => togglePatches(e.detail === 0);   // detail 0: a controller A (select) or a scripted click
    // keyboard: Enter / Space toggle the card (focus moves into it), Esc on the key closes it; the app's global keys
    // (Enter = select, Esc = back to the menu) never see these
    q("#cbPatchKey").addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); if (!e.repeat) togglePatches(true); }
      else if (e.key === "Escape" && !q("#cbPatchPop").hidden) { e.preventDefault(); e.stopPropagation(); closePatches(true); }
    });
    q("#cbPatchPopX").onclick = e => closePatches(true);
    q("#cbPatchPop").addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePatches(true); } });
    q("#cbPatchKey").addEventListener("animationend", () => q("#cbPatchKey").classList.remove("is-new"));
    const onEarned = e => paintPatches(e && e.detail && e.detail.id ? "earned" : true);   // no id: the course landed, nothing new
    const onResize = () => placePatches();
    addEventListener("outpost:patches", onEarned); addEventListener("resize", onResize);
    patchOff = () => { removeEventListener("outpost:patches", onEarned); removeEventListener("resize", onResize); };
    paintPatches(true);
  }

  // ---- display pages ----
  const bar = (v, max = 100, limit = null) => `<span class="du-bar${limit != null && v / max >= limit ? " is-red" : ""}"><i style="width:${clamp(v / max * 100)}%"></i>${limit != null ? `<em style="left:${limit * 100}%"></em>` : ""}</span>`;
  const row = (k, v, cls = "") => `<div class="du-row ${cls}"><span>${k}</span><b>${v}</b></div>`;
  const big = (name, val, unit, warn, why) => `<header class="du-head${warn ? " is-warn" : ""}"><span>${name}${why ? whyBtn(why) : ""}</span><b>${val}<small>${unit}</small></b></header>`;
  function page(p) {
    const s = st; if (!s) return "";
    const r = s.resources, e = s.env, L = s.loads, lim = r.dose_limit_msv || 50;
    const sunCh = e.next_sun_change_h != null ? row(e.in_sun ? "Sunset in" : "Sunrise in", `${Math.round(e.next_sun_change_h)} h`, e.in_sun && e.next_sun_change_h <= 6 ? "is-warn" : "") : "";
    const U = s.engineer && s.units ? s.units : null;   // Engineer: real units (W, kWh, K, % state of charge)
    const panels = row(`Panels${whyBtn("power")}`, U ? kw(U.solar_kw) : s.units ? `${Math.round(s.units.lit_pct)}%` : (e.in_sun ? "Lit" : "Dark"));
    if (p === "PWR") return `${U ? big("Battery", Math.round(U.battery_kwh), ` kWh · ${Math.round(r.power_pct)}%`, r.power_pct < 25, "battery") : big("Power", Math.round(r.power_pct), "%", r.power_pct < 25, "battery")}${bar(r.power_pct)}${panels}${U ? row("Load", kw(U.load_kw)) + row("Net", `${U.net_kw >= 0 ? "+" : "−"}${kw(Math.abs(U.net_kw))}`, U.net_kw < 0 ? "is-warn" : "") : ""}${sunCh}${s.power_save ? row("Night mode", "On") : ""}
      <div class="du-loads" role="listbox" aria-label="Power to each system">${LOADS.map(([k, n], i) => `<button type="button" role="option" class="du-load${i === sel ? " is-sel" : ""}" data-k="${k}" data-i="${i}" aria-selected="${i === sel}" aria-label="${esc(n)}: ${Math.round(L[k] || 0)} percent"><span>${k === "shields" || k === "greenhouse" ? pretend(n) : esc(n)}</span><i style="--w:${clamp(L[k])}%"></i><b>${Math.round(L[k] || 0)}</b></button>`).join("")}</div>`;
    if (p === "LIFE") return `${big("Life support", Math.round(r.life_support_pct), "%", r.life_support_pct < 25, "life_support")}${bar(r.life_support_pct)}
      ${row("Air system", Math.round(L.life_support) + "%")}${row(pretend("Greenhouse"), Math.round(L.greenhouse) + "%")}${row(`Heaters${whyBtn("heaters")}`, U ? `${kw(U.heater_kw)} · ${U.heater_duty_pct}% duty` : Math.round(L.heaters) + "%")}${U && U.outside_k != null ? row("Outside", `${U.outside_k} K · ${U.outside_c} °C`) : ""}`;
    if (p === "RAD") { const hot = (r.dose_rate_msv_h || 0) > .1;
      return `${big("Dose", (+r.dose_msv).toFixed(1), ` / ${lim} mSv`, r.dose_msv / lim > .7, "dose")}${bar(r.dose_msv, lim, .8)}
      ${row("Rate", `${(+r.dose_rate_msv_h || 0).toFixed(2)} mSv/h`, hot ? "is-warn" : "")}${row(pretend("Shields"), Math.round(L.shields) + "%")}${row("Shelter", s.shelter ? "Crew inside" : "Open")}`; }
    return `${big("Comms", e.earth_visible ? "Open" : "Closed", "", false)}
      ${row(e.earth_visible ? "Radio delay" : "Next window", e.earth_visible ? `${((e.comm_delay_s || 2.6) / 2).toFixed(1)} s each way` : `${e.next_comm_window_h ?? "?"} h`)}
      <ol class="du-log">${logLines.slice(-3).map(l => `<li><b>${esc(l.who === "kid" ? callSign.shown() : l.who === "houston" ? "Houston" : "CAPCOM")}</b> ${esc(l.text)}</li>`).join("")}</ol>`;
  }
  function paintDus() {
    const fw = document.activeElement && document.activeElement.closest && document.activeElement.closest(".cb-screen [data-why]");
    const fwKey = fw ? [fw.closest(".cb-screen").id, fw.dataset.why] : null;   // a focused "Why?" survives the re-render
    [0, 1, 2].forEach(d => {
      const scr = q("#cbDu" + d); scr.innerHTML = page(pages[d]); scr.dataset.page = pages[d];
      if (fwKey && fwKey[0] === scr.id) { const n = scr.querySelector(`[data-why="${fwKey[1]}"]`); if (n) n.focus({ preventScroll: true }); }

      scr.querySelectorAll(".du-load").forEach(b => b.onclick = () => { sel = +b.dataset.i; paintDus(); const n = q(`#cbDu${d} .du-load[data-i="${sel}"]`); if (n) n.focus(); });
      const act = q("#cbAct" + d);
      if (act && pages[d] === "PWR") {
        const n = LOADS[sel][1];
        const night = st && st.power_save != null ? `<button type="button" class="cb-sk is-night" aria-pressed="${!!st.power_save}" aria-label="Night mode: ${st.power_save ? "on" : "off"}">${ic("moon", 14)}Night</button>` : "";
        act.innerHTML = `${night}<span class="cb-actl">${esc(n)}</span><button type="button" class="cb-sk is-act" data-a="-5" aria-label="Less power to ${esc(n)}">−5</button><button type="button" class="cb-sk is-act" data-a="5" aria-label="More power to ${esc(n)}">+5</button>`;
        const nb = act.querySelector(".is-night"); if (nb) nb.onclick = () => cb.onCommand({ type: "power_save", on: !st.power_save });
        act.querySelectorAll("[data-a]").forEach(b => b.onclick = () => cb.onCommand({ type: "allocate", to: LOADS[sel][0], amount: { kind: "delta", value: +b.dataset.a }, from: null }));
      } else if (act) act.innerHTML = "";
    });
  }
  function paintSwitches() {
    if (!st) return;
    SWITCHES.forEach(([id, label, guarded, on]) => {
      const box = q(`.cb-sw[data-sw="${id}"]`), b = box.querySelector(".cb-toggle"), v = on(st), locked = guarded && !guards[id];
      b.setAttribute("aria-pressed", v); box.classList.toggle("is-on", !!v);
      b.setAttribute("aria-label", `${label}: ${v ? "on" : "off"}${locked ? ". Cover closed" : ""}`);
      box.querySelector(".cb-swst").textContent = v ? "On" : "Off";
      if (guarded) { const g = box.querySelector(".cb-guard"); g.setAttribute("aria-pressed", guards[id]); g.classList.toggle("is-open", guards[id]);
        g.setAttribute("aria-label", `${label} cover: ${guards[id] ? "open. Close the cover" : "closed. Lift the cover first"}`); }
    });
  }
  function paintRover() {
    const rv = st.rover || {}, busy = !!rv.busy;
    root.querySelectorAll(".cb-rvb").forEach(b => {
      const t = b.dataset.task, on = busy && rv.task === t;
      b.setAttribute("aria-pressed", on); b.disabled = t === "return" ? !busy || rv.task === "return" : busy;
    });
    q("#cbRvSt").textContent = busy ? `${TASK[rv.task] || "Out"} · back in ${rv.eta_h} h` : "Parked";
    const ro = q("#cbRover"); ro.hidden = !busy;
    if (busy) { const p = clamp(1 - (rv.eta_h || 0) / (TOTAL_H[rv.task] || 8), 0, 1);
      ro.innerHTML = `<span>Rover · ${esc(TASK[rv.task] || "Out")}</span><i style="--p:${(p * 100).toFixed(0)}%" aria-hidden="true"></i><span>${rv.eta_h} h</span>`; }
  }
  const PANEL_ORDER = ["habitat", "rover", "power", "displays", "radiation", "comm", "pedestal"];
  function stepPanel(d) { if (!c3) return; const i = PANEL_ORDER.indexOf(c3.panel); c3.open(PANEL_ORDER[(i + d + PANEL_ORDER.length) % PANEL_ORDER.length]); }
  let cueT = null, wins = null;   // wins: {hours, earth: [[s, e]], sun: [[s, e]]} from /api/mission/{id}/windows
  function applyCue(move) {
    root.querySelectorAll(".is-cue").forEach(n => n.classList.remove("is-cue")); if (!cueT) return null;
    const [k, v] = String(cueT).split(":");
    if (k === "load" && move) { const i = LOADS.findIndex(l => l[0] === v); if (i >= 0 && i !== sel) { sel = i; paintDus(); } }
    const css = { heaters: '.cb-sw[data-sw="heaters"]', science: '.cb-sw[data-sw="science"]', shelter: '.cb-sw[data-sw="shelter"]', shields: ".cb-knobrow",
      end_shift: "#cbEnd", houston: "#cbPtt", load: `.du-load[data-k="${v}"]`, rover: `.cb-rvb[data-task="${v}"]` }[k];
    const node = css && q(css); if (!node) return null;
    node.classList.add("is-cue");
    const panel = node.closest("[data-panel]"); if (move && c3 && panel) c3.open(k === "load" ? "power" : panel.dataset.panel);
    return node;
  }
  /** Panel read-outs (real fields when the sim sends them; nothing is shown for a field that is absent). */
  const mbar = (v, max = 100, cls = "") => `<i class="cb-mbar ${cls}"><b style="width:${clamp(v / max * 100)}%"></b></i>`;
  const irow = (k, v, bar = "") => `<div class="cb-irow"><span>${k}</span>${bar}<b>${v}</b></div>`;
  function paintInfo(s) {
    const r = s.resources, e = s.env || {}, L = s.loads, rv = s.rover || {}, lim = r.dose_limit_msv || 50;
    const hab = q("#cbInfoHab"); if (hab) hab.innerHTML = irow("Life support", Math.round(r.life_support_pct) + "%", mbar(r.life_support_pct, 100, r.life_support_pct < 25 ? "is-warn" : ""))
      + irow(pretend("Greenhouse"), Math.round(L.greenhouse || 0) + "%", mbar(L.greenhouse || 0))
      + (s.engineer && s.units ? irow("Heaters", `${kw(s.units.heater_kw)} · ${s.units.heater_duty_pct}%`, mbar(s.units.heater_duty_pct)) : irow("Heaters", Math.round(L.heaters || 0) + "%", mbar(L.heaters || 0)));
    const obj = q("#cbObj"), O0 = s.objectives || null;
    const O = Array.isArray(O0) ? O0 : O0 ? Object.entries(O0).filter(([, v]) => v && typeof v === "object" && "goal" in v)
      .map(([k, v]) => ({ text: `${k === "ice" ? "Ice" : k === "science" ? "Science" : k} ${Math.round(v.got || 0)} / ${v.goal}`, done: !!v.met })) : null;
    if (obj) { obj.hidden = !(O && O.length); if (O && O.length) obj.innerHTML = O.slice(0, 4).map(o => `<li class="${o.done ? "is-done" : ""}">${ic(o.done ? "star" : "todo", 14)}<span>${esc(o.text || o.title || "")}</span></li>`).join(""); }
    const rad = q("#cbInfoRad"), wn = stormWarning(s);
    if (rad) rad.innerHTML = irow("Dose", `${(+r.dose_msv).toFixed(1)} / ${lim} mSv`, mbar(r.dose_msv, lim, r.dose_msv / lim > .7 ? "is-warn" : ""))
      + irow("Rate", `${(+r.dose_rate_msv_h || 0).toFixed(2)} mSv/h`) + (s.shelter_ready_in_h > 0 ? irow("Shelter ready in", `${s.shelter_ready_in_h} h`) : "") + (wn ? irow("Warning", `${wn.lead != null ? `~${wn.lead} h` : "soon"}${wn.conf != null ? ` · ${wn.conf}% sure` : wn.word ? ` · ${wn.word}` : ""}`, wn.conf != null ? mbar(wn.conf, 100, "is-caution") : "") : "");
    const ri = q("#cbInfoRv"); if (ri) ri.innerHTML = (rv.busy ? irow("Back in", `${rv.eta_h} h`) : "") + (rv.battery_pct != null ? irow("Battery", Math.round(rv.battery_pct) + "%", mbar(rv.battery_pct)) : "")
      + (rv.dose_msv != null ? irow("Rover dose", (+rv.dose_msv).toFixed(1) + " mSv") : "") + (s.ice_runs != null ? irow("Ice runs", s.ice_runs) : "");
    const rt = q("#cbRoute"); if (rt) { const tot = TOTAL_H[rv.task] || 8, pr = rv.busy ? clamp(1 - (rv.eta_h || 0) / tot, 0, 1) : 0, out = rv.task === "return" ? 1 - pr : pr < .5 ? pr * 2 : (1 - pr) * 2;
      const x = 20 + out * 160, y = 40 - Math.sin(out * Math.PI) * 18;
      rt.innerHTML = `<path class="r-line" d="M20 40 Q100 4 180 40"/><circle class="r-base" cx="20" cy="40" r="6"/><circle class="r-goal" cx="180" cy="40" r="6"/>
        <circle class="r-rover${rv.busy ? " is-on" : ""}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5"/><text x="20" y="60">Base</text><text x="180" y="60" text-anchor="end">${rv.task === "explore" ? "Cabeus" : "Ice"}</text>`; }
    const tl = q("#cbCommTl"); if (tl) { const H = (wins && wins.hours) || 240, t = (s.mission_time_h || 0) / H, E = wins ? wins.earth : null;
      tl.innerHTML = E ? `<div class="tl-bar" role="img" aria-label="Earth in view ${E.map(([a, b]) => `from hour ${a} to ${b}`).join(", ") || "never"} of ${H}">${E.map(([a, b]) => `<i style="left:${(a / H * 100).toFixed(2)}%;width:${((b - a) / H * 100).toFixed(2)}%"></i>`).join("")}<em style="left:${clamp(t * 100)}%"></em></div>
        <span>Day 1</span><span class="tl-key"><i></i>Earth up</span><span>Day 10</span>` : ""; tl.hidden = !E; }
    const ci = q("#cbInfoComm"); if (ci) ci.innerHTML = irow("Earth", e.earth_visible ? "In view" : "Below the horizon") + (!e.earth_visible && e.next_comm_window_h != null ? irow("Next window", `${e.next_comm_window_h} h`) : "")
      + (e.earth_visible ? irow("Radio delay", `${((e.comm_delay_s || 2.6) / 2).toFixed(1)} s each way`) : "") + (s.science_waiting != null ? irow("Science to send", Math.round(s.science_waiting)) : "");
    const fc = q("#cbFc"), F = s.forecasts || null;
    if (fc) { fc.hidden = !(F && F.length); if (F && F.length) fc.innerHTML = F.slice(0, 3).map(f => { const c = f.confidence ?? f.probability, cp = c == null ? null : Math.round(c > 1 ? c : c * 100);
      return `<li>${ic("storm", 14)}<span>${esc(f.name || "Solar storm")}</span><b>${f.lead_h != null ? `in ~${f.lead_h} h` : ""}${cp != null ? ` · ${cp}%` : ""}</b></li>`; }).join(""); }
  }
  function moved(el) { if (!el) return; el.classList.remove("is-moved"); void el.offsetWidth; el.classList.add("is-moved"); }

  function update(s) {
    if (!s) return; prev = st; st = s;
    if (Date.now() - patchAt > 3000) paintPatches();
    const r = s.resources, e = s.env || {};
    if (!prev) setView(view, true);
    trackEarth(e.earth_elev_deg); paintEarthNote();
    sky(+e.sun_elev_deg || 0, e.earth_elev_deg, !!e.earth_visible, e.in_sun);
    paintClock(s, null);
    paintDus(); paintSwitches(); paintRover();
    const sh = Math.round(s.loads.shields || 0), kn = q("#cbKnob");
    q("#cbKval").style.strokeDasharray = `${(clamp(sh, 0, 60) / 60 * 75).toFixed(1)} 100`;
    kn.setAttribute("aria-valuenow", sh); kn.setAttribute("aria-valuetext", sh + " percent");
    q("#cbShVal").textContent = sh;
    if (prev) {
      if (Math.round(prev.loads.shields || 0) !== sh) moved(q(".cb-shield"));
      SWITCHES.forEach(([id, , , on]) => { if (on(prev) !== on(s)) moved(q(`.cb-sw[data-sw="${id}"]`)); });
      LOADS.forEach(([k]) => { if (Math.round(prev.loads[k] || 0) !== Math.round(s.loads[k] || 0)) root.querySelectorAll(`.du-load[data-k="${k}"]`).forEach(x => moved(x)); });
      const pr = prev.rover || {}, rv = s.rover || {};
      if (!!pr.busy !== !!rv.busy || pr.task !== rv.task) moved(q(".cb-rv"));
    }
    const lit = new Set(); let newWarn = false;
    LAMPS.forEach(([id, , lvl, f]) => { let on = false; try { on = f(s); } catch (x) { /* partial state */ }
      const el = q("#cbl-" + id); el.classList.toggle("is-lit", on); el.querySelector(".cb-vh").textContent = on ? ": lit" : ": off";
      if (on) { lit.add(id); if (lvl !== "info" && !litBefore.has(id) && prev) { masterOn = true; if (lvl === "warn") newWarn = true; } } });
    // a new warning brings the commander back to the seat: the window's alert strip and the lit panel are both in view
    if (newWarn && c3 && c3.panel) c3.back();
    litBefore = lit; paintMaster();
    // each alarm lights the panel it belongs to (warn beats caution)
    const ALARM_PANEL = { storm: "radiation", watch: "radiation", dose: "radiation", power: "displays", array: "displays", life: "habitat" };
    const lvlOf = id => (LAMPS.find(l => l[0] === id) || [])[2];
    ["displays", "habitat", "rover", "radiation", "pedestal", "comm"].forEach(pid => {
      const el = q(`[data-panel="${pid}"]`); if (!el) return;
      const ids = [...lit].filter(id => ALARM_PANEL[id] === pid), lv = ids.some(id => lvlOf(id) === "warn") ? "warn" : ids.length ? "caution" : "";
      if (lv) el.dataset.alarm = lv; else delete el.dataset.alarm;
      // never colour alone: the panel's label chip says it too
      const base = (PANELS.find(x => x[0] === pid) || [])[1] || ""; if (base) el.dataset.label = lv ? `${base} · ${lv === "warn" ? "Alert" : "Check"}` : base;
    });
    const storm = e.storm && e.storm.active;
    glassEl.classList.toggle("is-storm", !!storm);
    // [0.4 cabin 2] red alert light in the room (the WebGL shell); the consoles' faces stay readable
    const cabS = root.querySelector(".cb"); if (cabS) cabS.classList.toggle("is-storm", !!storm);
    if (c3 && c3.alerting !== !!storm) c3.alert(!!storm);
    paintAlert();
    q("#cbPttSub").textContent = e.earth_visible ? "Earth in view" : "No signal";
    q("#cbPtt").classList.toggle("is-nosignal", !e.earth_visible);
    q("#cbEndSub").textContent = s.over ? "Mission over" : o.mode === "ride" ? `Shift ${s.shift} of 4` : `Jump to shift ${s.shift % 4 + 1}`;
    paintProg(s);
    applyCue(false); paintInfo(s); paintWhy();
    if (ownTv) { ownTv.setSun(+e.sun_elev_deg || 0, s.mission_time_h || 0); ownTv.setEarth(e.earth_elev_deg); ownTv.setRover(s.rover || {}, 0); ownTv.setStorm(!!(e.storm && e.storm.active)); }
  }

  let alertKey = "", stopAlertSun = () => {}, stopSunMon = () => {}, sunMonOn = false;
  /** [0.4] The Radiation console's Sun monitor: the SDO loop while a storm is on or forecast (only with the pack). */
  function paintSunMon(on) {
    const f = q("#cbSunMon"); if (!f) return;
    const v = on ? realSun() : null; f.hidden = !v;
    if (!!v === sunMonOn) return; sunMonOn = !!v; stopSunMon();
    if (v) stopSunMon = loopFrames(f.querySelector("canvas"), v.frames, { reduced: reducedMo }); else stopSunMon = () => {};
  }
  /** The alert strip on the window's top edge: the storm (stays while it lasts) or a short-lived warning. No buttons. */
  function alert(a) { clearTimeout(flashT); flash = a; paintAlert(); if (a) flashT = setTimeout(() => { flash = null; paintAlert(); }, 7000); }
  function paintAlert() {
    const el = q("#cbAlert"), stm = st && st.env && st.env.storm && st.env.storm.active ? st.env.storm : null;
    const wn = stormWarning(st);
    const weak = !!stm && stm.sep === false;   // QA-27: few particles reach the Moon
    const a = stm ? { level: weak ? "caution" : "warn", icon: "storm", title: weak ? (story.STORM.weak || "Storm at Earth") : story.STORM.name, link: { url: stm.url || DONKI, text: "NASA " + (stm.source || "DONKI") },
        text: [weak ? story.STORM.weakText : "", stm.real_date ? `Real event, ${stm.real_date}` : "Real event", stm.ends_in_h != null ? `Ends in ~${stm.ends_in_h} h` : "", st.shelter ? "Crew sheltered" : ""].filter(Boolean).join(" · ") }
      : wn ? { level: "caution", icon: "storm", title: wn.word ? `Storm warning · ${wn.word}` : "Storm warning", conf: wn.conf, link: { url: DONKI, text: "NASA " + wn.source },
        text: [wn.lead != null ? `Forecast ~${wn.lead} h (game)` : "On its way", wn.date ? `Real event, ${wn.date}` : ""].filter(Boolean).join(" · ") }
      : flash;
    el.hidden = !a; glassEl.classList.toggle("has-alert", !!a);
    const hole = root.querySelector(".cb-hole"); if (hole) hole.classList.toggle("has-alert", !!a);
    paintSunMon(!!(stm || wn));
    if (!a) { el.innerHTML = ""; alertKey = ""; stopAlertSun(); return; }
    // [0.4] a storm (or its warning) shows the real Sun: the SDO frames of 14 May 2024, credited, in place of the icon
    const sunV = (stm || wn) && a.icon === "storm" ? realSun() : null;
    const key = JSON.stringify([a.level, a.title, a.text, a.conf, a.link && a.link.url, !!sunV]);
    if (key === alertKey) return; alertKey = key;   // the strip repaints every tick: rebuild only on a change (the loop keeps running)
    stopAlertSun();
    el.className = "cb-alert is-" + a.level + (sunV ? " has-sun" : "");
    el.innerHTML = `${sunV ? `<span class="cb-al-sun"><canvas class="cb-sun-cv" width="160" height="160" role="img" aria-label="The real Sun on 14 May 2024 (NASA SDO)"></canvas></span>` : `<span class="cb-al-i">${ic(a.icon || (a.level === "info" ? "info" : "warning"), 20)}</span>`}<span class="cb-al-body"><span class="cb-al-l1"><b>${esc(a.title)}</b>${a.conf != null ? `<span class="cb-al-conf" role="meter" aria-label="Forecast confidence" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${a.conf}"><i style="width:${(a.conf * .56).toFixed(0)}px"></i><em>${a.conf}% sure</em></span>` : ""}<span class="cb-al-t">${esc(a.text || "")}${a.link ? ` · <a class="cb-al-src" href="${esc(a.link.url)}" target="_blank" rel="noopener">${esc(a.link.text)}</a>` : ""}</span></span>${sunV ? `<small class="cb-al-sunc">${esc(SUN_CREDIT)} · ${esc(SUN_SOURCE)}</small>` : ""}</span>`;
    if (sunV) stopAlertSun = loopFrames(el.querySelector(".cb-al-sun canvas"), sunV.frames, { reduced: reducedMo });
    // [polish 3] the strip says what is happening; what to do about it is on the Now card (one instruction at a time)
    // QA-23: the HUD row below the strip moves down by the strip's real height (it wraps on narrow windows)
    requestAnimationFrame(() => { const h = el.offsetHeight; [hole, glassEl].forEach(n => n && n.style.setProperty("--alert-h", h + "px")); });
  }

  /** QA-24: the sim's "in sun" (a ridge-top site stays lit with the Sun a degree under the flat horizon) decides the
   *  word; the elevation stays in the tooltip for the curious. */
  function sky(sunDeg, earthDeg, up, inSun) {
    const lit = inSun == null ? sunDeg > 0 : !!inSun;
    q("#cbSky").innerHTML = `<span title="Sun elevation ${deg(sunDeg)}"><em>Sun</em> ${lit ? "up" : "down"}</span><span><em>Earth</em> ${earthDeg == null ? (up ? "up" : "down") : up ? deg(earthDeg) : "below"}</span>`;
  }
  function telemetry(f) { if (!st) return; trackEarth(f.earth_elev_deg); if (f.sun_elev_deg != null) sky(f.sun_elev_deg, f.earth_elev_deg, f.comm ? f.comm === "open" : st.env.earth_visible, f.in_sun != null ? f.in_sun : st.env.in_sun); }
  /** Radio log (COMM page) + the fallback caption line (the caption bar takes over when captions are on). */
  function log(who, text, quiet = false) {
    if (!text) return;
    const last = logLines[logLines.length - 1]; if (last && last.text === text) return;
    logLines.push({ who, text }); logLines = logLines.slice(-12);
    if (quiet) { if (pages.includes("COMM")) paintDus(); return; }   // [polish 3] in the radio log, not the caption line
    if (pages.includes("COMM")) paintDus();
    q("#cbCapWho").textContent = who === "kid" ? callSign.shown() : who === "houston" ? "Houston" : "CAPCOM";
    q("#cbCapTxt").textContent = text;
  }
  function calling(on, ms = 2600) {
    const b = q("#cbPtt"); b.classList.toggle("is-calling", !!on); b.disabled = !!on;
    b.style.setProperty("--trip", ms + "ms");
    q(".cb-ptt-t span").textContent = on ? "Signal travelling" : "Call Houston";
    if (on) q("#cbPttSub").textContent = `${(ms / 2000).toFixed(1)} s each way`;
    else if (st) q("#cbPttSub").textContent = st.env.earth_visible ? "Earth in view" : "No signal";
  }
  // [playtest 21] while a skip runs, the clock bar says so (the card's "time skips ahead" is then true on both)
  let skipping = false;
  function busy(on) { q("#cbEnd").disabled = !!on; q("#cbEnd").classList.toggle("is-busy", !!on); const sk = q("#cbSkip"); if (sk) sk.disabled = !!on;
    skipping = !!on; if (clockSt) paintTime(clockSt); }

  // ---- the live clock, the task card, progress, story moments, the mission log (docs/GAMEPLAY.md) ----
  const hh = h => String(Math.floor(h % 24)).padStart(2, "0") + ":" + String(Math.floor((h % 1) * 60 / 15) * 15).padStart(2, "0");
  function paintClock(s, tH) {
    const t = tH != null ? tH : (s.clock && s.clock.mission_time_h != null ? s.clock.mission_time_h : s.mission_time_h || 0);
    const shift = Math.floor((t % 24) / 6) + 1;
    q("#cbClock").innerHTML = `<b>${clockDay(s, t)} <span class="num cb-hh">${hh(t)}</span></b><small>${esc(clockSub(shift, s.site))}</small>`;
  }
  let clockSt = null;
  const HELD = { tour: "On hold: the tour", confirm: "On hold: yes or no?", decision: "On hold: your call", choice: "On hold: your choice",
    hidden: "Paused", settings: "Paused: Settings", start: "", over: "", away: "" };
  function paintTime(c) {
    clockSt = c; const p = q("#cbPlay"); if (!p || !c) return;
    const on = c.running, waiting = c.started && !c.paused && c.held;
    p.innerHTML = `${ic(on || waiting ? "pause" : "play", 16)}<span>${on || waiting ? "Pause" : c.started ? "Resume" : "Play"}</span>`;
    p.setAttribute("aria-label", on || waiting ? "Pause the clock" : c.started ? "Resume the clock" : "Start the clock");
    p.classList.toggle("is-on", !!on);
    root.querySelectorAll(".cb-pm-sp").forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.warp === c.warp)));
    const h = q("#cbHeld"); h.textContent = waiting ? (HELD[c.held] ?? "Paused") : !c.started ? "Ready" : c.paused ? "Paused" : c.ff || skipping ? "Fast-forward" : `Running ${c.warp}×`;
    q("#cbSkip").classList.toggle("is-ff", !!c.ff);
    q("#cbTime").dataset.state = on ? "run" : waiting ? "held" : "paused";
    const cab = root.querySelector(".cb"); if (cab) cab.dataset.clock = on ? "run" : waiting ? "held" : "paused";
  }
  function paintProg(s) {
    const P = s.progress, el = q("#cbProg"); if (!el) return;
    if (!P) { el.innerHTML = ""; el.hidden = true; return; }
    el.hidden = false;
    const sci = Math.min(1, P.science_sent / (P.science_goal || 120)), ice = Math.min(1, P.ice / (P.ice_goal || 1));
    const bit = (cls, title, name, val, of, p) => `<span class="pg${cls}" title="${title}"><em>${name}</em><b class="num">${val}<small>/${of}</small></b><i style="--p:${(p * 100).toFixed(1)}%"></i></span>`;
    // [playtest 4] science gathered but not home yet counts too: "+14 on board" under the sent-home number
    const aboard = Math.round(P.science_stored || 0);
    const sciTitle = `Science sent home${aboard ? `. ${aboard} more on board, sent when Earth is up` : ""}`;
    el.innerHTML = bit("", "Days survived", "Days", P.days_done.toFixed(1), P.days_total, P.days_done / P.days_total)
      + bit(sci >= 1 ? " is-met" : "", sciTitle, "Science", Math.round(P.science_sent), P.science_goal, sci).replace("</b>", `${aboard ? `<small class="pg-aboard"> +${aboard}<span class="pg-ab-l"> on board</span></small>` : ""}</b>`)
      + bit(ice >= 1 ? " is-met" : "", "Ice runs", "Ice", P.ice, P.ice_goal, ice)
      + `<button type="button" class="cb-logbtn" aria-expanded="${!q("#cbMlog").hidden}" aria-controls="cbMlog" aria-label="Mission log, ${logEntries.length} entries">${ic("todo", 16)}<span>Log</span>${logEntries.length ? `<small class="num">${logEntries.length}</small>` : ""}</button>`;
  }
  let logEntries = [];
  function toggleLog(force) { const el = q("#cbMlog"); el.hidden = force != null ? !force : !el.hidden; paintLog(); if (st) paintProg(st); }
  function paintLog() {
    const el = q("#cbMlog"); if (!el || el.hidden) return;
    el.innerHTML = `<header><b>Mission log</b><button type="button" class="cb-mlog-x" aria-label="Close the mission log">${ic("close", 14)}</button></header>
      <ol>${logEntries.slice().reverse().map(e => `<li class="is-${esc(e.kind)}"><span class="ml-d">Day ${e.day}</span><b>${esc(e.title)}</b><span>${esc(e.text)}</span></li>`).join("") || "<li>Nothing yet.</li>"}</ol>`;
    el.querySelector(".cb-mlog-x").onclick = () => toggleLog(false);
  }
  let momentT = null;
  /** A story beat's moment in the window: the title over the glass, and the sky's mood (storm glow, dusk, Earthrise). */
  function moment(b) {
    const el = q("#cbMoment"); if (!el) return;
    clearTimeout(momentT);
    const slot = on => [root.querySelector(".cb-hole"), glassEl].forEach(n => n && n.classList.toggle("has-moment", on));
    if (!b) { el.hidden = true; slot(false); return; }
    glassEl.dataset.moment = b.visual || "";
    el.className = "cb-moment is-" + (b.visual || "site");
    // [polish 3] the title only: the beat's objective line was a second instruction beside the Now card
    el.innerHTML = `<small>Day ${Math.floor((b.t_h || 0) / 24) + 1}</small><b>${esc(b.title)}</b>`;
    el.hidden = false; slot(true); clearMarks();
    momentT = setTimeout(() => { el.hidden = true; slot(false); delete glassEl.dataset.moment; }, 5200);
  }
  // [polish 4] the window's markers (OUTPOST, ROVER, EARTH, SUN) follow the 3D camera; one that drifts under the
  // story moment ("Day 3 · On our own") steps aside (hides) while the moment shows, so the two never print over each other
  let markRaf = 0;
  function clearMarks() {
    cancelAnimationFrame(markRaf);
    const tick = () => {
      const el = q("#cbMoment"), on = el && !el.hidden && el.isConnected;
      const marks = root.querySelectorAll(".tv-mark");
      if (!on) { marks.forEach(m => m.classList.remove("is-under")); markRaf = 0; return; }
      const r = el.getBoundingClientRect(), pad = 6;
      // measure first, then toggle (a remove + re-add each frame restarted the fade, so it never faded)
      const hits = [...marks].map(m => { const k = m.getBoundingClientRect();
        return k.width > 0 && !(k.right < r.left - pad || k.left > r.right + pad || k.bottom < r.top - pad || k.top > r.bottom + pad); });
      marks.forEach((m, i) => m.classList.toggle("is-under", hits[i]));
      markRaf = requestAnimationFrame(tick);
    };
    tick();
  }
  let cardKey = "";
  const ringMax = {};
  const flat = t => String(t || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  /** The word a kid can say for each option: the one word no other option has ("Steer left" / "Steer right" -> left,
   *  right). The router's task_choice matches the same words (backend turn_router.task_choice). */
  function sayWords(labels) {
    const W = l => String(l).toLowerCase().replace(/[^a-z ]/g, " ").split(/\s+/).filter(w => w.length > 1 && !["to", "the", "an", "or", "and"].includes(w));
    // one option ("Lights on"): its first word is the one to say
    return labels.length > 1 ? labels.map((l, i) => W(l).find(w => labels.every((o, j) => j === i || !W(o).includes(w))) || W(l)[0]).filter(Boolean)
      : labels.length === 1 ? W(labels[0]).slice(0, 1) : [];
  }
  const DECKHINT = { skip: "Skip is in the clock bar (E).", warp: "Time speed is in the menu (Esc), or press W.", play: "Play is in the clock bar (K)." };
  const NOWSAY = (ws, keys) => `Say ${ws.map(w => `“${w}”`).join(" or ")}, or press ${(keys || ws.map((_, i) => String(i + 1))).join(" or ")}.`;
  /** The Now task card: title, the step to do, progress (2 of 3), the countdown, the buttons, the lesson that helps. */
  function card(c, { ack = null, cadet = false } = {}) {
    const el = q("#cbNow"); if (!el) return;
    const cab = root.querySelector(".cb");
    el.hidden = !c; if (!c) { cardKey = ""; if (cab) cab.classList.remove("is-takeover"); return; }
    const own0 = (c.buttons || []).filter(b => !b.clock);
    // [polish 3] the event takeover: a question CAPCOM asks, a storm, a decision with a deadline. The cabin dims around
    // the Now card, so its buttons are the one thing to press (the deck, the voice bar and the panels still work).
    const take = own0.length > 0 && (!!c.offer || c.level === "warn" || (c.choice && c.level === "caution"));
    // a step whose one button says the same words: the button carries them (the line stays for screen readers)
    const same = !c.choice && own0.length === 1 && flat(own0[0].label) === flat(c.text);
    el.className = `cb-now is-${c.level || "info"}${c.progress ? " is-task" : ""}${cadet ? " is-cadet" : ""}${c.choice ? " is-choice" : ""}${take ? " is-takeover" : ""}${same ? " is-same" : ""}${folded && !take ? " is-folded" : ""}`;
    if (cab) cab.classList.toggle("is-takeover", take);
    q("#cbNowTitle").textContent = c.title && c.title !== (story.NOW || {}).label ? c.title : "";
    q("#cbNowT").textContent = c.text;
    const left = c.left_h != null ? (c.left_h >= 1 ? `${Math.round(c.left_h)} h left` : `${Math.max(1, Math.round(c.left_h * 60))} min left`) : "";
    // the countdown ring: the share of this job's time still left (its first reading is the full ring)
    const rk = c.task || c.key; if (c.left_h != null) ringMax[rk] = Math.max(ringMax[rk] || 0, c.left_h);
    const ringP = c.left_h != null && ringMax[rk] > 0 ? Math.max(0, Math.min(1, c.left_h / ringMax[rk])) : null;
    // Rebuild the card (and its buttons) only when its structure changes. The countdown and readouts tick about once a
    // second; re-rendering the buttons that often replaced them mid-click, so a real mouse click could be lost.
    const key = JSON.stringify([c.key, (c.buttons || []).map(b => b.label), ack, (c.readouts || []).map(r => r.k), c.progress, c.hint, c.why, !!left, take, c.lesson && c.lesson.id]);
    if (key === cardKey) {
      requestAnimationFrame(fitNow);
      const lt = q("#cbNowMore .cb-now-left"); if (lt && left) { lt.lastChild.textContent = left; lt.classList.toggle("is-low", c.left_h != null && c.left_h <= 2); }
      const rg = q("#cbNowMore .cb-now-ring"); if (rg && ringP != null) { rg.style.setProperty("--p", ringP.toFixed(3)); rg.classList.toggle("is-low", c.left_h <= 2); }
      q("#cbNowMore").querySelectorAll(".cb-now-ro").forEach((n, i) => { const r = (c.readouts || [])[i]; if (r) n.lastChild.textContent = " " + r.v; });
      const own2 = (c.buttons || []).filter(b => !b.clock || b.clock === "play");
      q("#cbNowMore").querySelectorAll("[data-b]").forEach(b => b.onclick = () => cb.onTask(own2[+b.dataset.b], c));   // latest task object
      return;
    }
    cardKey = key;
    const steps = c.progress ? `<span class="cb-now-steps" aria-label="Step ${Math.min(c.progress.done + 1, c.progress.total)} of ${c.progress.total}">${Array.from({ length: c.progress.total }, (_, i) => `<i class="${i < c.progress.done ? "is-done" : ""}"></i>`).join("")}<em>${c.progress.done} of ${c.progress.total}</em></span>` : "";
    const lessonText = !c.lesson ? "" : c.lesson.track === "field" && c.lesson.title ? (story.NOW.fieldHelps || (t => t))(c.lesson.title)
      : c.lesson.n ? (story.NOW.lessonHelps || (n => `Lesson ${n}`))(c.lesson.n) : "";
    const lesson = lessonText ? `<span class="cb-now-lesson" title="${esc(c.lesson.title || "")}">${esc(lessonText)}</span>` : "";
    const ro = (c.readouts || []).map(r => `<span class="cb-now-ro"><em>${esc(r.k)}</em><span> ${esc(r.v)}</span></span>`).join("");
    // a choice: each option is its own button with its number and the word to say; anything else: one hot button (T)
    const words = sayWords((c.buttons || []).map(b => b.label));
    // Skip ahead / the speed are the deck's, shown once there. [playtest 3] Play is the card's own button too: a clock
    // that is ready (a resumed mission) or paused makes Play the one job, so it sits where every job sits.
    const own = (c.buttons || []).filter(b => !b.clock || b.clock === "play");
    const deckB = (c.buttons || []).find(b => b.clock && b.clock !== "play");
    const deckHint = deckB ? `<p class="cb-now-say">${esc(DECKHINT[deckB.clock] || "")}</p>` : "";
    // the key on each button: 1 / 2 for a choice, Y / N for a yes / no (Y and N answer it), T for the one job
    const keyOf = (b, i) => (b.intent === "yes" ? "Y" : b.intent === "no" ? "N" : c.choice ? String(i + 1) : "T");
    const btns = own.map((b, i) => `<button type="button" class="cb-now-b${(i || c.choice) && b.intent !== "yes" ? "" : " is-hot"}" data-b="${i}" ${b.intent ? `data-intent="${b.intent}"` : i === 0 && !c.choice ? 'data-intent="yes"' : ""}
      aria-keyshortcuts="${keyOf(b, i)}"><kbd aria-hidden="true">${keyOf(b, i)}</kbd><span class="cb-now-bl">${esc(b.label)}${b.hint ? `<small>${esc(b.hint)}</small>` : ""}</span></button>`).join("");
    const ring = take && ringP != null ? `<span class="cb-now-ring${c.left_h <= 2 ? " is-low" : ""}" style="--p:${ringP.toFixed(3)}" role="img" aria-label="${esc(left)}"><svg viewBox="0 0 36 36" aria-hidden="true"><circle cx="18" cy="18" r="15.9"/><circle class="is-arc" cx="18" cy="18" r="15.9" pathLength="100"/></svg></span>` : "";
    const sayLine = c.sayLine ? `<p class="cb-now-say">${esc(c.sayLine)}</p>` : c.choice && words.length ? `<p class="cb-now-say">${esc(NOWSAY(words, own.map(keyOf)))}</p>` : "";
    q("#cbNowMore").innerHTML = `${ack ? `<p class="cb-now-ack" role="status">${ic("check", 14)}${esc(ack)}</p>` : ""}
      <div class="cb-now-meta">${ring}${steps}${left ? `<span class="cb-now-left${c.left_h != null && c.left_h <= 2 ? " is-low" : ""}">${ic("speed", 13)}<span>${esc(left)}</span></span>` : ""}${lesson}</div>
      ${c.why ? `<p class="cb-now-why">${esc(c.why)}</p>` : ""}${c.hint ? `<p class="cb-now-hint">${esc(c.hint)}</p>` : ""}${ro ? `<div class="cb-now-ros">${ro}</div>` : ""}
      ${btns ? `<div class="cb-now-btns${c.choice ? " is-choice" : ""}" role="group" aria-label="${esc(c.title || "Now")}">${btns}</div>` : ""}${sayLine}${deckHint}`;
    q("#cbNowMore").querySelectorAll("[data-b]").forEach(b => b.onclick = () => cb.onTask(own[+b.dataset.b], c));
    fitNow();
    // [polish 3] measure again once the 3D consoles have settled: a card drawn while the cabin's camera still flew in
    // (a returning player skips the tour) measured the consoles mid-flight and stayed squeezed to its button
    clearTimeout(fitT); fitT = setTimeout(() => { fitNow(); fitT = setTimeout(fitNow, 1200); }, 600);
  }
  let fitT = 0;
  /** The Now panel lives on the wall above the Habitat console: when the wall is short (a small window), it drops its
   *  details (read-outs, the hint, then the meta row and the say line) so it never sits on the console. The step and
   *  its buttons always stay. */
  function fitNow() {
    const el = q("#cbNow"), hole = root.querySelector(".cb-hole");
    // the window's own strips start where the Now panel ends (a wide window at 1024 px reaches under the panel)
    if (hole) { const nr = el && !el.hidden ? el.getBoundingClientRect() : null, hr = hole.getBoundingClientRect();
      const seat = !c3 || !c3.panel || c3.panel === "seat";
      const clear = seat && nr && hr.width > 0 && nr.bottom > hr.top && nr.right > hr.left ? Math.min(Math.ceil(nr.right - hr.left + 8), Math.floor(hr.width * 0.45)) : 0;
      hole.style.setProperty("--now-clear", clear + "px"); }
    if (!el || el.hidden) return;
    el.classList.remove("is-tight", "is-tighter", "is-tightest");
    const hab = q('.c3-panel[data-panel="habitat"]') || q('.c3-panel[data-panel="rover"]');
    if (!hab || !c3 || (c3.panel && c3.panel !== "seat")) return;
    const room = () => hab.getBoundingClientRect().top - 40 - el.getBoundingClientRect().bottom;   // 40: the console's label chip
    for (const c of ["is-tight", "is-tighter", "is-tightest"]) { if (room() >= 0) break; el.classList.add(c); }
  }
  addEventListener("resize", () => requestAnimationFrame(fitNow));
  /** An overlay (menu, chapter card) owns focus: the cabin behind it goes inert, so arrows and Tab stay on it. */
  function trap(on) {
    const any = on || [q("#cbMenu"), q("#cbChapter")].some(n => n && !n.hidden);
    root.querySelectorAll(".cb > :not(.cb-pm):not(.cb-ch)").forEach(n => { n.inert = !!any; });
  }
  return { update, telemetry, log, calling, busy, setView, alert, get view() { return view; }, get state() { return st; },
    /** Panels: open("power" | "habitat" | "comm"), back(). No-ops in the flat layout. */
    openPanel: id => c3 && c3.open(id), seat: () => c3 && c3.back(),
    /** Gesture hooks (feat/gestures via the intent bus): look-around, highlight, next / previous panel. */
    look: (dx, dy, opts) => c3 && c3.look(dx, dy, opts), recenter: () => { if (c3) c3.recenter(); setView("site"); }, get pose() { return c3 ? c3.pose : null; }, highlightPanel: id => c3 && c3.highlight(id), get highlighted() { return c3 ? c3.highlighted : null; },
    nextPanel: () => stepPanel(1), prevPanel: () => stepPanel(-1), get panel() { return c3 ? c3.panel : null }, get is3d() { return !!c3; }, get fps() { return c3 ? c3.fps : null; },
    dispose() { clearInterval(offT); foldOff(); viewsOff(); stopAlertSun(); stopSunMon(); clearTimeout(momentT); cancelAnimationFrame(markRaf); clearTimeout(fitT); whyOff(); escOff(); patchOff();   // [qa] a dead cabin's banner timer once hid the new cabin's banner (root outlives it)
      escOff = () => {}; if (c3) c3.dispose(); c3 = null; qualityOff(); if (ownTv) { ownTv.hide(); ownTv.dispose(); ownTv = null; } },
    setQuality: q => c3 && c3.setQuality(q),
    /** The earned patches the key shows (ids), and a repaint (tests; the Academy fires "outpost:patches"). */
    get patches() { return patchList.map(b => b.id); }, paintPatches: () => paintPatches("earned"),
    /** The mission's Earth/Sun spans (client.windows) for the Comm timeline. */
    setWindows(w) { wins = w || null; if (st) paintInfo(st); },
    /** Highlight one control at a time (the check ride's next order): "heaters" | "science" | "shelter" | "shields" |
     *  "end_shift" | "houston" | "load:<key>" | "rover:<task>"; null clears. Opens its panel; returns the control. */
    cue(target) { cueT = target || null; return applyCue(true); },
    /** Glow what the tour or the objective points at, without opening anything (null clears). Targets:
     *  window | du:<0-2> | panel:<id> | lamps | goals | start, or an objective control: end_shift | shelter | shields |
     *  night | houston | rover:<task> | load:<key>. Returns the nodes lit. */
    point(target) {
      root.querySelectorAll(".is-point").forEach(n => n.classList.remove("is-point"));
      if (!target) return [];
      const [k, v] = String(target).split(":");
      const sel = { window: ".cb-views", du: `[data-du="${v}"]`, panel: v === "power" ? '[data-du="0"]' : `[data-panel="${v}"]`, lamps: ".cb-lamps",
        goals: "#cbObj", start: '[data-du="0"], #cbEnd', end_shift: "#cbEnd", shelter: '.cb-sw[data-sw="shelter"]', shields: ".cb-knobrow",
        night: ".cb-sk.is-night", houston: "#cbPtt", rover: `.cb-rvb[data-task="${v}"]`, load: '[data-du="0"]',
        play: "#cbPlay", skip: "#cbSkip", warp: "#cbMenuBtn", task: ".cb-now:not(.is-choice) .cb-now-b.is-hot" }[k];
      // [flows] "Time warp?" glows the 4× button, not the whole 1× / 2× / 4× group: a novice pressing the glowing group
      // toggled between 1× and 2× forever (tools/play_mission.py at 1440×879: "All steady. Time warp?" never moved on)
      const nodes = sel ? [...root.querySelectorAll(sel)] : [];
      if (k === "window") { const h = root.querySelector(".cb-hole") || glassEl; if (h) nodes.push(h); }
      nodes.forEach(n => n.classList.add("is-point"));
      return nodes;
    },
    /** Progressive disclosure (Cadet): the panel the tour or the objective is about stays bright, the rest dim. A panel
     *  with an alarm is never dimmed. null: everything bright. */
    focus(panelId) {
      const ids = (Array.isArray(panelId) ? panelId : [panelId]).filter(Boolean).map(id => (id === "power" ? "displays" : id));
      const cab = root.querySelector(".cb"); if (cab) cab.classList.toggle("is-focus", ids.length > 0);
      root.querySelectorAll("[data-panel]").forEach(n => n.classList.toggle("is-focus", ids.includes(n.dataset.panel)));
    },
    /** The "what now" strip on the window: {text, level} or null (the full task card: card()). */
    objective(o) { card(o); },
    card: (c, opts) => card(c, opts),
    /** Open the "Why?" card for a gauge (power | battery | life_support | dose | heaters | shields | rover); returns it. */
    why: (id, from = "voice") => openWhy(id, from), whyClose: () => closeWhy(), get whyOpen() { return whyId; },
    clock: c => paintTime(c),
    /** [polish 2] The pause menu: open with {eye, shift} (day / chapter line, the shift Restart goes back to), or close. */
    menu(open, info = {}) {
      const m = q("#cbMenu"); if (!m) return false;
      m.hidden = !open; trap(open);
      if (open) { q("#cbMenuEye").textContent = info.eye || ""; q("#cbMenuShift").textContent = info.shift || "";
        requestAnimationFrame(() => { const f = m.querySelector('[data-m="resume"]'); if (f) f.focus({ preventScroll: true }); }); }
      return true;
    },
    get menuOpen() { const m = q("#cbMenu"); return !!(m && !m.hidden); },
    /** [polish 2] The chapter card: {n, of, title, days, stars:{safe, powered, science}, capcom, last}; null closes. */
    chapter(rec) {
      const el = q("#cbChapter"); if (!el) return false;
      el.hidden = !rec; trap(!!rec); if (!rec) return true;
      q("#cbChEye").textContent = `Chapter ${rec.n} of ${rec.of} · Days ${rec.days[0]}–${rec.days[1]}`;
      q("#cbChT").textContent = `${rec.title}: ${rec.count} of 3 stars`;
      // [playtest 4] the Science star follows Earth: with no Earth window in the chapter it counts science gathered (it
      // waits on board for Earthrise), else science sent home; a miss shows how far it got
      const sc = rec.science || null, stored = !!(sc && sc.mode === "stored");
      const sciOn = stored ? "Gathered. Saved on board for Earthrise" : "Science sent home";
      const sciOff = sc ? (stored ? `Gathered ${Math.round(sc.got)} of ${Math.round(sc.goal)}` : `Sent home ${Math.round(sc.sent)} of ${Math.round(sc.goal)}`) : "Missed";
      const S = [["safe", "Safe", "Crew dose and air in range", "Missed"], ["powered", "Powered", "Battery never under 20%", "Missed"], ["science", "Science", sciOn, sciOff]];
      q("#cbChStars").innerHTML = S.map(([k, n, d, off]) => `<li class="${rec.stars[k] ? "is-on" : ""}"><span class="cb-ch-star">${ic("star", 34)}</span><b>${n}</b><small>${rec.stars[k] ? d : off}</small></li>`).join("");
      q("#cbChCap").textContent = rec.capcom || "";
      q("#cbChGoT").textContent = rec.last ? "Open your debrief" : "Next chapter";
      requestAnimationFrame(() => q("#cbChGo").focus({ preventScroll: true }));
      return true;
    },
    get chapterOpen() { const el = q("#cbChapter"); return !!(el && !el.hidden); },
    /** The window's frame between whole hours (the live clock's `live` telemetry): the clock reads smoothly. */
    frame: f => { if (st && f && f.mission_time_h != null) paintClock(st, f.mission_time_h); },
    moment: b => moment(b),
    /** [0.3.12] the free area changed (the side card's width): refit the seat view */
    relayout: () => { if (c3) c3.resize(); },
    get cockpit() { return c3; },
    missionLog: entries => { logEntries = entries || []; paintLog(); }
  };
}
