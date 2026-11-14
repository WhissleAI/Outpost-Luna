// Outpost Luna cabin: the Mission screen as the inside of a spacecraft, on one grid, read top to bottom:
//   1. the window (ORBIT on the NASA globe, SITE / ROVER / EARTH on LOLA terrain), with the clock, the view switcher,
//      the sky readout and, only when something is really wrong, an alert strip along its top edge;
//   2. three display units (POWER / LIFE / RADIATION by default; any of PWR LIFE RAD COMM per unit);
//   3. the controls: hab switches, rover, shield knob, caution & warning, Houston + END SHIFT (the one primary action);
//   4. the comm strip (captions + the ask dock, moved in by ui.js).
// Pure view: update(state), telemetry(frame), log(who, text), calling(on, ms), busy(on), alert(a), setView(v).
// Every control is a <button> (or role=slider) whose aria-label states its state. An order that changes a control
// (by voice or by click) animates that control (.is-moved). Colours and sizes come from tokens.css only.
import "../cabin.css";
import * as story from "../story.js";
const { callSign } = story;
import { LOADS } from "./cockpit.js";
import { icon } from "../assets/icons.js";
import { createCockpit3D, PANELS } from "./cockpit3d.js";
import { createTerrainView } from "./terrain.js";

const DONKI = "https://kauai.ccmc.gsfc.nasa.gov/DONKI/";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/** Invented hardware gets a small tag (docs/ACCURACY_AUDIT.md): the copy owner's words when they land. */
const pretend = () => `<span class="cb-pretend" title="Not real NASA hardware">${esc(story.PRETEND_TECH || "Pretend tech")}</span>`;
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
  const c = w.confidence ?? w.probability, conf = c == null ? null : Math.round(c > 1 ? c : c * 100);
  return { lead: w.lead_h ?? w.eta_h ?? null, conf, date: w.real_date || null, source: w.source || "DONKI", name: w.name || "", by: w.by || null };
}
/** Hab switches: [id, label, guarded, on(state), command(on)] */
const SWITCHES = [
  ["shelter", "Shelter", true, s => !!s.shelter, on => ({ type: "shelter", on })],
  ["heaters", "Heaters", false, s => (s.loads.heaters || 0) >= 8, on => ({ type: "allocate", to: "heaters", amount: { kind: "percent", value: on ? 15 : 0 }, from: null })],
  ["science", "Science", false, s => (s.loads.science || 0) > 0, on => ({ type: "allocate", to: "science", amount: { kind: "percent", value: on ? 15 : 0 }, from: null })],
];
const ROVER = [["collect_ice", "Ice", "ice"], ["explore", "Explore", "explore"], ["return", "Home", "outpost"]];
const ic = (n, size = 18) => icon(n, { size });
const VIEW_ICON = { orbit: "orbit", site: "site", rover: "rover", earth: "earth" };

export function createCabin(root, o = {}) {
  const cb = { onCommand() {}, onHouston() {}, onEndShift() {}, onDebrief() {}, onView() {}, badges: () => [], ...o };
  let view = "site", st = null, prev = null, pages = ["PWR", "LIFE", "RAD"], sel = 0, logLines = [], litBefore = new Set(), masterOn = false;
  let flash = null, flashT = null;
  const guards = { shelter: false };

  const sw = id => { const [, label, guarded] = SWITCHES.find(x => x[0] === id); return `
          <div class="cb-sw" data-sw="${id}">
            <div class="cb-swbox">
              <button type="button" class="cb-toggle" data-sw="${id}" aria-pressed="false" aria-label="${esc(label)}"><i aria-hidden="true"></i></button>
              ${guarded ? `<button type="button" class="cb-guard" data-guard="${id}" aria-pressed="false" aria-label="${esc(label)} cover: closed">${ic("lock", 16)}</button>` : ""}
            </div>
            <span class="cb-swl">${esc(label)}</span><span class="cb-swst" aria-hidden="true"></span>
          </div>`; };
  root.innerHTML = `
  <div class="cb">
    <section class="cb-window" aria-label="Window">
      <div class="cb-glass" data-view="site">
        <div class="cb-tint" aria-hidden="true"></div>
        <div class="cb-alert" id="cbAlert" hidden role="alert"></div>
        <div class="cb-top">
          <div class="cb-clock" id="cbClock"></div>
          <div class="cb-views" role="group" aria-label="Window view">${VIEWS.map(([id, n]) => `<button type="button" class="cb-view" data-view="${id}" aria-pressed="${id === "site"}">${ic(VIEW_ICON[id], 16)}<span>${n}</span></button>`).join("")}</div>
        </div>
        <div class="cb-rover" id="cbRover" hidden></div>
        <div class="cb-sky" id="cbSky" aria-label="Sky"></div>
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
        <div class="cb-plate cb-hab"><h3>Habitat</h3><div class="cb-info" id="cbInfoHab"></div><div class="cb-sws">${sw("heaters")}${sw("science")}</div><ol class="cb-obj" id="cbObj" hidden></ol></div>
      </div>
      <div class="cb-grp" data-panel="rover" role="group" aria-label="Rover panel">
        <div class="cb-plate cb-rv"><h3>Rover</h3>
          <div class="cb-seg">${ROVER.map(([t, n, i]) => `<button type="button" class="cb-rvb" data-task="${t}" aria-pressed="false">${ic(i, 16)}<span>${n}</span></button>`).join("")}</div>
          <span class="cb-rvst" id="cbRvSt"></span>
          <svg class="cb-route" id="cbRoute" viewBox="0 0 200 64" aria-hidden="true"></svg>
          <div class="cb-info" id="cbInfoRv"></div>
        </div>
      </div>
      <div class="cb-grp" data-panel="radiation" role="group" aria-label="Radiation panel">
        <div class="cb-plate cb-shield"><h3>Radiation</h3><div class="cb-info" id="cbInfoRad"></div>
          <div class="cb-radrow">${sw("shelter")}
          <div class="cb-knobrow">
            <span class="cb-shl">Shields ${pretend()}</span>
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
          <button type="button" class="cb-end" id="cbEnd"><span>End shift</span><small id="cbEndSub"></small></button>
          <button type="button" class="cb-db" id="cbDb">Finish mission</button>
        </div>
      </div>
      <div class="cb-grp" data-panel="comm" role="group" aria-label="Comm panel">
        <div class="cb-plate cb-comm"><h3>Comm</h3><div class="cb-tl" id="cbCommTl" aria-hidden="true"></div><div class="cb-info" id="cbInfoComm"></div><ul class="cb-fc" id="cbFc" hidden></ul>
          <button type="button" class="cb-ptt" id="cbPtt" aria-label="Call Houston"><span class="cb-ptt-t">${ic("houston", 18)}<span>Call Houston</span></span><small id="cbPttSub"></small><i class="cb-trip" aria-hidden="true"></i></button>
        </div>
      </div>
    </section>

    <section class="cb-commrow" aria-label="Radio">
      <div class="cb-capwrap"><p class="cb-caption" id="cbCap"><b id="cbCapWho">CAPCOM</b> <span id="cbCapTxt">Standing by.</span></p><div class="cb-capslot" id="cbCapSlot"></div></div>
      <div class="cb-askslot" id="cbAskSlot" role="group" aria-label="Talk to CAPCOM"></div>
    </section>
  </div>`;
  const q = s => root.querySelector(s);
  const glassEl = q(".cb-glass");

  // ---- 3D cabin (cockpit3d.js): the panels above become real DOM mounted on the console faces; flat grid if no WebGL ----
  let c3 = null, qualityOff = () => {}, ownTv = null;
  if (o.terrain && o.site) {
    const tvHost = document.createElement("div"); tvHost.className = "tv"; glassEl.prepend(tvHost);
    ownTv = createTerrainView(tvHost, { reduced: () => document.documentElement.dataset.motion === "reduce" });
    if (ownTv) { Promise.resolve(ownTv.setSite(o.site)).then(() => ownTv.setView("site")).catch(() => {}); }
  }
  const reducedMo = () => document.documentElement.dataset.motion === "reduce" || !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  if (o.mode3d !== false && document.documentElement.dataset.quality !== "low") {
    const cabEl = q(".cb"), host = document.createElement("div"); host.className = "c3";
    const holeEl = document.createElement("div"); holeEl.className = "cb-hole";
    [".cb-alert", ".cb-top", ".cb-rover", ".cb-sky"].forEach(sel => holeEl.append(q(sel)));
    const backEl = document.createElement("button"); backEl.type = "button"; backEl.className = "c3-back"; backEl.hidden = true; backEl.innerHTML = `${ic("back", 18)}<span>Seat</span>`;
    backEl.setAttribute("aria-label", "Back to the seat view");
    cabEl.classList.add("is-3d"); cabEl.prepend(host); cabEl.append(holeEl, backEl);
    // ride mode (the Flight School check ride): the first time in the seat, so only the displays, habitat and End shift
    // the check ride's orders are shields, shelter and the rover: those panels and the displays, nothing else
    const ids = o.mode === "ride" ? ["displays", "radiation", "rover"] : ["displays", "habitat", "rover", "radiation", "pedestal", "comm"];
    const panelEls = Object.fromEntries(ids.map(k => [k, q(`[data-panel="${k}"]`)]));
    if (o.mode === "ride") { root.classList.add("is-ride"); ["habitat", "pedestal", "comm"].forEach(k => { const el = q(`[data-panel="${k}"]`); if (el) el.hidden = true; }); }
    c3 = createCockpit3D(host, { panels: panelEls, hole: holeEl, glass: glassEl, reduced: reducedMo, onPanel: id => { backEl.hidden = !id; cb.onPanel && cb.onPanel(id); } });
    if (!c3) { cabEl.classList.remove("is-3d"); host.remove(); backEl.remove(); [".cb-alert", ".cb-top", ".cb-rover", ".cb-sky"].forEach(sel => glassEl.append(holeEl.querySelector(sel))); holeEl.remove(); }
    else {
      // graphics quality (Settings): "low" = fewer lights, no reflections, 1× pixels
      // Settings (prefs.js) writes <html data-graphics="high|low">; follow it live
      const html = document.documentElement, applyQ = () => c3 && c3.setQuality(html.dataset.graphics === "low" ? "low" : "high"); applyQ();
      const mo = new MutationObserver(applyQ); mo.observe(html, { attributes: true, attributeFilter: ["data-graphics"] }); qualityOff = () => mo.disconnect();
      backEl.onclick = () => c3.back();
      root.addEventListener("keydown", e => { if (e.key === "Escape" && c3.panel) { e.preventDefault(); c3.back(); } });
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

  // ---- window view switcher ----
  function setView(v, quiet) {
    view = v; root.querySelectorAll(".cb-view").forEach(b => b.setAttribute("aria-pressed", b.dataset.view === v));
    glassEl.dataset.view = v;
    if (!quiet) cb.onView(v);
  }
  root.querySelectorAll(".cb-view").forEach(b => b.onclick = () => setView(b.dataset.view));

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
  q("#cbDb").onclick = () => cb.onDebrief();

  function paintMaster() {
    const m = q("#cbMaster"); m.classList.toggle("is-lit", masterOn); m.setAttribute("aria-label", `Master alarm: ${masterOn ? "on. Press to reset" : "off"}`);
    glassEl.classList.toggle("is-alarm", masterOn);
  }

  // ---- display pages ----
  const bar = (v, max = 100, limit = null) => `<span class="du-bar${limit != null && v / max >= limit ? " is-red" : ""}"><i style="width:${clamp(v / max * 100)}%"></i>${limit != null ? `<em style="left:${limit * 100}%"></em>` : ""}</span>`;
  const row = (k, v, cls = "") => `<div class="du-row ${cls}"><span>${k}</span><b>${v}</b></div>`;
  const big = (name, val, unit, warn) => `<header class="du-head${warn ? " is-warn" : ""}"><span>${name}</span><b>${val}<small>${unit}</small></b></header>`;
  function page(p) {
    const s = st; if (!s) return "";
    const r = s.resources, e = s.env, L = s.loads, lim = r.dose_limit_msv || 50;
    const sunCh = e.next_sun_change_h != null ? row(e.in_sun ? "Sunset in" : "Sunrise in", `${Math.round(e.next_sun_change_h)} h`, e.in_sun && e.next_sun_change_h <= 6 ? "is-warn" : "") : "";
    if (p === "PWR") return `${big("Power", Math.round(r.power_pct), "%", r.power_pct < 25)}${bar(r.power_pct)}${sunCh}${s.power_save ? row("Night mode", "On") : ""}
      <div class="du-loads" role="listbox" aria-label="Power to each system">${LOADS.map(([k, n], i) => `<button type="button" role="option" class="du-load${i === sel ? " is-sel" : ""}" data-k="${k}" data-i="${i}" aria-selected="${i === sel}" aria-label="${esc(n)}: ${Math.round(L[k] || 0)} percent"><span>${esc(n)}</span><i style="--w:${clamp(L[k])}%"></i><b>${Math.round(L[k] || 0)}</b></button>`).join("")}</div>`;
    if (p === "LIFE") return `${big("Life support", Math.round(r.life_support_pct), "%", r.life_support_pct < 25)}${bar(r.life_support_pct)}
      ${row("Air system", Math.round(L.life_support) + "%")}${row(`Greenhouse ${pretend()}`, Math.round(L.greenhouse) + "%")}${row("Heaters", Math.round(L.heaters) + "%")}`;
    if (p === "RAD") { const hot = (r.dose_rate_msv_h || 0) > .1;
      return `${big("Dose", (+r.dose_msv).toFixed(1), ` / ${lim} mSv`, r.dose_msv / lim > .7)}${bar(r.dose_msv, lim, .8)}
      ${row("Rate", `${(+r.dose_rate_msv_h || 0).toFixed(2)} mSv/h`, hot ? "is-warn" : "")}${row("Shields", Math.round(L.shields) + "%")}${row("Shelter", s.shelter ? "Crew inside" : "Open")}`; }
    return `${big("Comms", e.earth_visible ? "Open" : "Closed", "", false)}
      ${row(e.earth_visible ? "Radio delay" : "Next window", e.earth_visible ? `${((e.comm_delay_s || 2.6) / 2).toFixed(1)} s each way` : `${e.next_comm_window_h ?? "?"} h`)}
      <ol class="du-log">${logLines.slice(-3).map(l => `<li><b>${esc(l.who === "kid" ? callSign.shown() : l.who === "houston" ? "Houston" : "CAPCOM")}</b> ${esc(l.text)}</li>`).join("")}</ol>`;
  }
  function paintDus() {
    [0, 1, 2].forEach(d => {
      const scr = q("#cbDu" + d); scr.innerHTML = page(pages[d]); scr.dataset.page = pages[d];

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
      + irow(`Greenhouse ${pretend()}`, Math.round(L.greenhouse || 0) + "%", mbar(L.greenhouse || 0)) + irow("Heaters", Math.round(L.heaters || 0) + "%", mbar(L.heaters || 0));
    const obj = q("#cbObj"), O0 = s.objectives || null;
    const O = Array.isArray(O0) ? O0 : O0 ? Object.entries(O0).filter(([, v]) => v && typeof v === "object" && "goal" in v)
      .map(([k, v]) => ({ text: `${k === "ice" ? "Ice" : k === "science" ? "Science" : k} ${Math.round(v.got || 0)} / ${v.goal}`, done: !!v.met })) : null;
    if (obj) { obj.hidden = !(O && O.length); if (O && O.length) obj.innerHTML = O.slice(0, 4).map(o => `<li class="${o.done ? "is-done" : ""}">${ic(o.done ? "star" : "todo", 14)}<span>${esc(o.text || o.title || "")}</span></li>`).join(""); }
    const rad = q("#cbInfoRad"), wn = stormWarning(s);
    if (rad) rad.innerHTML = irow("Dose", `${(+r.dose_msv).toFixed(1)} / ${lim} mSv`, mbar(r.dose_msv, lim, r.dose_msv / lim > .7 ? "is-warn" : ""))
      + irow("Rate", `${(+r.dose_rate_msv_h || 0).toFixed(2)} mSv/h`) + (s.shelter_ready_in_h > 0 ? irow("Shelter ready in", `${s.shelter_ready_in_h} h`) : "") + (wn ? irow("Warning", `${wn.lead != null ? `~${wn.lead} h` : "soon"}${wn.conf != null ? ` · ${wn.conf}% sure` : ""}`, wn.conf != null ? mbar(wn.conf, 100, "is-caution") : "") : "");
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
    const r = s.resources, e = s.env || {};
    if (!prev) setView(view, true);
    sky(+e.sun_elev_deg || 0, e.earth_elev_deg, !!e.earth_visible);
    q("#cbClock").innerHTML = `<b>Day ${s.day} <span>· Shift ${s.shift}</span></b><small>${esc(((s.site && s.site.name) || "").split(" (")[0])}</small>`;
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
    paintAlert();
    q("#cbPttSub").textContent = e.earth_visible ? "Earth in view" : "No signal";
    q("#cbPtt").classList.toggle("is-nosignal", !e.earth_visible);
    q("#cbEndSub").textContent = s.over ? "Mission over" : `Shift ${s.shift} of 4`;
    applyCue(false); paintInfo(s);
    if (ownTv) { ownTv.setSun(+e.sun_elev_deg || 0, s.mission_time_h || 0); ownTv.setEarth(e.earth_elev_deg); ownTv.setRover(s.rover || {}, 0); ownTv.setStorm(!!(e.storm && e.storm.active)); }
  }

  /** The alert strip on the window's top edge: the storm (stays while it lasts) or a short-lived warning. */
  function alert(a) { clearTimeout(flashT); flash = a; paintAlert(); if (a) flashT = setTimeout(() => { flash = null; paintAlert(); }, 7000); }
  function paintAlert() {
    const el = q("#cbAlert"), stm = st && st.env && st.env.storm && st.env.storm.active ? st.env.storm : null;
    const wn = stormWarning(st);
    const a = stm ? { level: "warn", icon: "storm", title: "Solar particle storm", link: { url: stm.url || DONKI, text: "NASA " + (stm.source || "DONKI") },
        text: [stm.real_date ? `Real event, ${stm.real_date}` : "Real event", stm.ends_in_h != null ? `Ends in ~${stm.ends_in_h} h` : "", st.shelter ? "Crew sheltered" : ""].filter(Boolean).join(" · "),
        actions: st.shelter ? [] : [["shelter", "Shelter"], ["shields", "Shields 40"]] }
      : wn ? { level: "caution", icon: "storm", title: "Storm warning", conf: wn.conf, link: { url: DONKI, text: "NASA " + wn.source },
        text: [wn.lead != null ? `Arrives in ~${wn.lead} h` : "On its way", wn.date ? `Real event, ${wn.date}` : ""].filter(Boolean).join(" · "),
        actions: (st.loads.shields || 0) >= 40 ? [] : [["shields", "Shields 40"]] }
      : flash;
    el.hidden = !a; glassEl.classList.toggle("has-alert", !!a);
    if (!a) { el.innerHTML = ""; return; }
    el.className = "cb-alert is-" + a.level;
    el.innerHTML = `<span class="cb-al-i">${ic(a.icon || (a.level === "info" ? "info" : "warning"), 20)}</span><b>${esc(a.title)}</b>${a.conf != null ? `<span class="cb-al-conf" role="meter" aria-label="Forecast confidence" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${a.conf}"><i style="width:${(a.conf * .56).toFixed(0)}px"></i><em>${a.conf}% sure</em></span>` : ""}<span class="cb-al-t">${esc(a.text || "")}${a.link ? ` · <a class="cb-al-src" href="${esc(a.link.url)}" target="_blank" rel="noopener">${esc(a.link.text)}</a>` : ""}</span>
      ${(a.actions || []).length ? `<span class="cb-al-acts">${a.actions.map(([k, n], i) => `<button type="button" class="cb-al-b${i ? "" : " is-hot"}" data-act="${k}">${n}</button>`).join("")}</span>` : ""}`;
    el.querySelectorAll("[data-act]").forEach(b => b.onclick = () => cb.onCommand(b.dataset.act === "shelter" ? { type: "shelter", on: true }
      : { type: "allocate", to: "shields", amount: { kind: "percent", value: 40 }, from: null }));
  }

  function sky(sunDeg, earthDeg, up) {
    q("#cbSky").innerHTML = `<span><em>Sun</em> ${deg(sunDeg)}</span><span><em>Earth</em> ${earthDeg == null ? (up ? "up" : "down") : up ? deg(earthDeg) : "below"}</span>`;
  }
  function telemetry(f) { if (!st) return; if (f.sun_elev_deg != null) sky(f.sun_elev_deg, f.earth_elev_deg, f.comm ? f.comm === "open" : st.env.earth_visible); }
  /** Radio log (COMM page) + the fallback caption line (the caption bar takes over when captions are on). */
  function log(who, text) {
    if (!text) return;
    const last = logLines[logLines.length - 1]; if (last && last.text === text) return;
    logLines.push({ who, text }); logLines = logLines.slice(-12);
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
  function busy(on) { q("#cbEnd").disabled = !!on; q("#cbEnd").classList.toggle("is-busy", !!on); }
  return { update, telemetry, log, calling, busy, setView, alert, get view() { return view; }, get state() { return st; },
    /** Panels: open("power" | "habitat" | "comm"), back(). No-ops in the flat layout. */
    openPanel: id => c3 && c3.open(id), seat: () => c3 && c3.back(),
    /** Gesture hooks (feat/gestures via the intent bus): look-around, highlight, next / previous panel. */
    look: (dx, dy) => c3 && c3.look(dx, dy), highlightPanel: id => c3 && c3.highlight(id), get highlighted() { return c3 ? c3.highlighted : null; },
    nextPanel: () => stepPanel(1), prevPanel: () => stepPanel(-1), get panel() { return c3 ? c3.panel : null }, get is3d() { return !!c3; }, get fps() { return c3 ? c3.fps : null; },
    dispose() { if (c3) c3.dispose(); qualityOff(); if (ownTv) { ownTv.hide(); ownTv.dispose(); ownTv = null; } },
    setQuality: q => c3 && c3.setQuality(q),
    /** The mission's Earth/Sun spans (client.windows) for the Comm timeline. */
    setWindows(w) { wins = w || null; if (st) paintInfo(st); },
    /** Highlight one control at a time (the check ride's next order): "heaters" | "science" | "shelter" | "shields" |
     *  "end_shift" | "houston" | "load:<key>" | "rover:<task>"; null clears. Opens its panel; returns the control. */
    cue(target) { cueT = target || null; return applyCue(true); },
    /** Cadet: an offer opens its panel with the choices as two big buttons there (null clears). */
    offer(panelId, actions) {
      root.querySelectorAll(".cb-offer").forEach(n => n.remove());
      if (!panelId || !actions || !actions.length) return;
      const host = q(`[data-panel="${panelId === "power" ? "displays" : panelId}"]`); if (!host) return;
      const box = document.createElement("div"); box.className = "cb-offer"; box.setAttribute("role", "group"); box.setAttribute("aria-label", "CAPCOM offers");
      actions.slice(0, 2).forEach((a, i) => { const b = document.createElement("button"); b.type = "button"; b.className = "cb-offer-b" + (i ? "" : " is-hot"); b.textContent = a.label;
        b.onclick = () => { box.remove(); a.onClick(); }; box.append(b); });
      host.append(box);
      if (c3) c3.open(panelId);
      requestAnimationFrame(() => { const f = box.querySelector("button"); if (f) f.focus({ preventScroll: true }); });
    } };
}
