// The Systems drawer (docs/GAMEPLAY.md §17, docs/MISSION_POLISH_SPEC.md wave 3): the cabin's systems as one big panel
// at a time, on the right wall under the window keys, with labels of 20 px and up. LB / RB on a controller, [ / ] on
// the keyboard, "show power" / "next panel" by voice and the Systems key open it and step it. What a player sees
// follows the level (Settings → Level): Cadet has Power, Radiation and Rover; Commander adds Life support and Radio;
// Engineer has all five plus the real numbers and the equations. The 3D consoles stay in the cabin as its art.
//
// Every control sends the same order as its twin on a 3D console (cabin.js), through the same onCommand. The drawer
// never says what to do: the Now card does (one instruction at a time, §10). When the drawer is open and the Now job's
// control lives in one of its panels, the drawer shows that panel and lights the control; when it is closed, or the
// control is in a panel this level hides, the Now card's own button does the job. Never a dead end.
//
// Pure: systemsFor, systemOfTarget, controlSel, stepSystem, systemWord, commandFor, panelHtml (tests/systems.test.js).
// DOM: createSystems(cab, deps) -> the drawer and its Systems key.
import { icon } from "../assets/icons.js";
import { pretendLabel } from "../pretend.js";
import { LOADS } from "./cockpit.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clamp = (v, a = 0, b = 100) => Math.max(a, Math.min(b, +v || 0));
const ic = (n, size = 20) => icon(n, { size });

/** The five panels, in drawer order. gauge: the Why card its (i) and a controller's Y open. */
export const SYSTEMS = Object.freeze([
  { id: "power", name: "Power", icon: "power", gauge: "battery" },
  { id: "radiation", name: "Radiation", icon: "radiation", gauge: "dose" },
  { id: "rover", name: "Rover", icon: "rover", gauge: "rover" },
  { id: "life", name: "Life support", icon: "air", gauge: "life_support" },
  { id: "radio", name: "Radio", icon: "radio", gauge: null },
]);
const LEVEL_IDS = { cadet: ["power", "radiation", "rover"], commander: ["power", "radiation", "rover", "life", "radio"],
  engineer: ["power", "radiation", "rover", "life", "radio"] };
const levelOf = l => (LEVEL_IDS[l] ? l : "commander");

/** The panels a level shows (Cadet 3, Commander 5, Engineer 5 with numbers). */
export function systemsFor(level) { const ids = LEVEL_IDS[levelOf(level)]; return SYSTEMS.filter(s => ids.includes(s.id)); }
/** Engineer sees the real units and the equations on every gauge. */
export const numbersFor = level => levelOf(level) === "engineer";

/** The drawer panel a Now card's target (objective.js) lives on, at this level; null when it has none there. */
export function systemOfTarget(target, level) {
  const k = String(target || "").split(":")[0];
  const id = { shields: "radiation", shelter: "radiation", night: "power", heaters: "power", science: "power", load: "power", rover: "rover", houston: "radio" }[k] || null;
  return id && LEVEL_IDS[levelOf(level)].includes(id) ? id : null;
}
/** The drawer control a target lights (a CSS selector inside the drawer), at this level. Cadet has no power split:
 *  its Heaters and Science switches stand for those two loads. */
export function controlSel(target, level) {
  const [k, v] = String(target || "").split(":");
  if (!systemOfTarget(target, level)) return null;
  const cadet = levelOf(level) === "cadet";
  if (k === "load") return cadet ? (v === "heaters" || v === "science" ? `[data-target="${v}"]` : null) : `[data-target="load:${v}"]`;
  if ((k === "heaters" || k === "science") && !cadet) return `[data-target="load:${k}"]`;
  return `[data-target="${k}${v ? ":" + v : ""}"]`;
}

/** LB / RB: the next panel in this level's list (wraps). From nothing, RB starts at the first and LB at the last. */
export function stepSystem(ids, cur, d) {
  if (!ids.length) return null;
  const i = ids.indexOf(cur);
  if (i < 0) return d < 0 ? ids[ids.length - 1] : ids[0];
  return ids[(i + (d < 0 ? -1 : 1) + ids.length) % ids.length];
}

/** Spoken or typed drawer words. -> {open: id | null} | {step: 1 | -1} | {close: true} | null.
 *  "show power", "the rover panel", "open life support", "systems", "next panel", "close systems". "Show me the rover"
 *  stays the window's rover view, and "back to my seat" stays the seat (both handled elsewhere). */
const NAMES = [[/^(power|energy|battery|batteries)$/, "power"], [/^(radiation|rad|shields?|dose)$/, "radiation"], [/^rover$/, "rover"],
  [/^(life support|air|habitat|hab|air system)$/, "life"], [/^(radio|comms?|communications?|comm)$/, "radio"]];
const nameOf = w => { const m = NAMES.find(([re]) => re.test(w)); return m ? m[1] : null; };
export function systemWord(text) {
  const w = String(text || "").toLowerCase().replace(/[^a-z ]/g, " ").replace(/\s+/g, " ").trim().replace(/ (please|now)$/, "");
  if (!w) return null;
  if (/^(?:(?:show|open|bring up|pull up)(?: me)?(?: the| my)? )?systems?(?: drawer| panels?)?$/.test(w)) return { open: null };
  if (/^(?:close|hide|shut)(?: the)? (?:systems?|drawer|systems? drawer)$/.test(w)) return { close: true };
  if (/^(?:next) (?:panel|system|page)$/.test(w)) return { step: 1 };
  if (/^(?:previous|prev|last|back one) (?:panel|system|page)$/.test(w)) return { step: -1 };
  let m = w.match(/^(?:show|open|bring up|pull up|go to|switch to)(?: me)?(?: the| my)? (.+?)(?: (?:panel|system|systems|page))?$/);
  if (m) { const id = nameOf(m[1]); if (id && !(id === "rover" && /^show/.test(w) && !/ (panel|system|page)$/.test(w))) return { open: id }; }
  m = w.match(/^(?:the )?(.+?) (?:panel|system|page)$/);
  if (m) { const id = nameOf(m[1]); if (id) return { open: id }; }
  return null;
}

/** A drawer control's order, the same one its 3D twin sends (cabin.js). act: the control's data-act; d: its data. */
export function commandFor(act, d = {}, s = null) {
  if (!s) return null;
  const L = s.loads || {};
  if (act === "night") return { type: "power_save", on: !s.power_save };
  if (act === "switch" && (d.sw === "heaters" || d.sw === "science")) {
    const on = d.sw === "heaters" ? (L.heaters || 0) >= 8 : (L.science || 0) > 0;
    return { type: "allocate", to: d.sw, amount: { kind: "percent", value: on ? 0 : 15 }, from: null };
  }
  if (act === "load" && d.k) return { type: "allocate", to: d.k, amount: { kind: "delta", value: +d.d || 0 }, from: null };
  if (act === "shelter") return { type: "shelter", on: !s.shelter };
  if (act === "shields") return { type: "allocate", to: "shields", amount: { kind: "percent", value: clamp(Math.round(((L.shields || 0) + (+d.d || 0)) / 10) * 10, 0, 60) }, from: null };
  if (act === "rover" && d.task) return { type: "dispatch", vehicle: "rover", task: d.task, target: null };
  return null;
}

// ---------------------------------------------------------------- the panels (pure HTML) ----------------------------

const TASK = { collect_ice: "Ice run", explore: "Exploring", repair_array: "Array fix", return: "Heading home" };
const ROVER = [["collect_ice", "Ice", "ice"], ["explore", "Explore", "explore"], ["return", "Home", "outpost"]];
const kw = v => `${(+v || 0).toFixed(Math.abs(+v || 0) < 10 ? 1 : 0)} kW`;
const whyB = (id, name) => `<button type="button" class="sys-why cb-whyb" data-why="${id}" aria-label="Why? ${esc(name)}" title="Why?">${icon("info", { size: 18 })}</button>`;
const bar = (v, max = 100, red = null, warn = false) => `<span class="sys-bar${warn ? " is-warn" : ""}" aria-hidden="true"><i style="width:${clamp(v / max * 100).toFixed(1)}%"></i>${red != null ? `<em style="left:${red * 100}%"></em>` : ""}</span>`;
const row = (k, v, cls = "") => `<div class="sys-row${cls ? " " + cls : ""}"><span>${k}</span><b>${v}</b></div>`;
/** Engineer: the gauge's equation with today's numbers (the Why card's own line, from the sim's state.why). */
function eqLine(s, gauge, numbers) {
  const c = numbers && gauge && s.why && s.why[gauge]; if (!c) return "";
  const t = c.eng || c.formula; return t ? `<p class="sys-eq">${esc(t)}</p>` : "";
}
function gauge(s, { id, name, val, unit, warn, pct, max = 100, red = null, numbers }) {
  return `<div class="sys-gauge${warn ? " is-warn" : ""}" role="group" aria-label="${esc(name)}">
    <div class="sys-gl"><span>${esc(name)}</span>${id ? whyB(id, name) : ""}</div>
    <div class="sys-gv"><b class="num">${val}</b><small>${unit}</small></div>${bar(pct, max, red, warn)}${eqLine(s, id, numbers)}</div>`;
}
const sw = (target, label, on, act, extra = "", html = null) => `<button type="button" class="sys-sw${on ? " is-on" : ""}" data-act="${act}" data-target="${target}" ${extra}
  aria-pressed="${!!on}" aria-label="${esc(label)}: ${on ? "on" : "off"}"><span class="sys-swl">${html || esc(label)}</span><b class="sys-lamp">${on ? "On" : "Off"}</b></button>`;

/** One panel's HTML from the sim state. o: {level, numbers}. */
export function panelHtml(id, s, o = {}) {
  if (!s) return "";
  const level = levelOf(o.level), numbers = o.numbers ?? numbersFor(level), cadet = level === "cadet";
  const r = s.resources || {}, e = s.env || {}, L = s.loads || {}, rv = s.rover || {}, U = numbers && s.units ? s.units : null;
  if (id === "power") {
    const pw = Math.round(r.power_pct || 0);
    const head = U ? gauge(s, { id: "battery", name: "Battery", val: Math.round(U.battery_kwh), unit: ` kWh · ${pw}%`, warn: pw < 25, pct: pw, numbers })
      : gauge(s, { id: "battery", name: "Battery", val: pw, unit: "%", warn: pw < 25, pct: pw, numbers });
    const sunCh = e.next_sun_change_h != null ? row(e.in_sun ? "Sunset in" : "Sunrise in", `${Math.round(e.next_sun_change_h)} h`, e.in_sun && e.next_sun_change_h <= 6 ? "is-warn" : "") : "";
    const solar = row(`Solar panels${whyB("power", "Solar power")}`, U ? kw(U.solar_kw) : s.units && s.units.lit_pct != null ? `${Math.round(s.units.lit_pct)}% lit` : e.in_sun ? "Lit" : "Dark");
    const net = U ? row("Load", kw(U.load_kw)) + row("Net", `${U.net_kw >= 0 ? "+" : "−"}${kw(Math.abs(U.net_kw))}`, U.net_kw < 0 ? "is-warn" : "") : "";
    const night = s.power_save != null ? sw("night", "Night mode", !!s.power_save, "night") : "";
    const sws = cadet ? sw("heaters", "Heaters", (L.heaters || 0) >= 8, "switch", 'data-sw="heaters"') + sw("science", "Science", (L.science || 0) > 0, "switch", 'data-sw="science"') : "";
    const split = cadet ? "" : `<div class="sys-split" role="group" aria-label="Power to each system"><p class="sys-h">Power to each system</p>${LOADS.map(([k, n]) => {
      const v = Math.round(L[k] || 0), nm = k === "shields" || k === "greenhouse" ? pretendLabel(n) : esc(n);
      return `<div class="sys-load" data-target="load:${k}"><span class="sys-ln">${nm}</span><span class="sys-lv"><i style="width:${clamp(v)}%"></i></span><b class="num">${v}</b>
        <button type="button" class="sys-mini" data-act="load" data-k="${k}" data-d="-5" aria-label="Less power to ${esc(n)}">−</button><button type="button" class="sys-mini" data-act="load" data-k="${k}" data-d="5" aria-label="More power to ${esc(n)}">+</button></div>`; }).join("")}</div>`;
    return `${head}${solar}${sunCh}${net}<div class="sys-sws">${night}${sws}</div>${split}`;
  }
  if (id === "radiation") {
    const lim = r.dose_limit_msv || 50, dose = +r.dose_msv || 0, rate = (+r.dose_rate_msv_h || 0).toFixed(2), sh = Math.round(L.shields || 0);
    const w = s.env && (e.warning || e.storm_warning || e.storm_forecast), storm = !!(e.storm && e.storm.active);
    const wn = !storm && w && w.active !== false ? `${(w.lead_h ?? w.eta_h) != null ? `in about ${w.lead_h ?? w.eta_h} h` : "on its way"}` : "";
    return `${gauge(s, { id: "dose", name: "Dose", val: dose.toFixed(1), unit: numbers ? ` of ${lim} mSv` : ` of ${lim}`, warn: dose / lim > .7, pct: dose, max: lim, red: .8, numbers })}
      ${row("Rate", numbers ? `${rate} mSv/h` : `${rate} an hour`, (+r.dose_rate_msv_h || 0) > .1 ? "is-warn" : "")}${storm ? row("Solar storm", "Now", "is-warn") : wn ? row("Storm warning", wn, "is-caution") : ""}
      ${s.shelter_ready_in_h > 0 ? row("Shelter ready in", `${s.shelter_ready_in_h} h`) : ""}
      <div class="sys-sws">${sw("shelter", "Shelter", !!s.shelter, "shelter", "", s.shelter ? "Crew in the shelter" : "Shelter")}</div>
      <div class="sys-knob" data-target="shields" role="group" aria-label="Shields">
        <span class="sys-kl">${pretendLabel("Shields")}${whyB("shields", "Shields")}</span>
        <button type="button" class="sys-mini" data-act="shields" data-d="-10" aria-label="Shields down 10" ${sh <= 0 ? "disabled" : ""}>−</button>
        <b class="num" aria-live="polite">${sh}<small>%</small></b>
        <button type="button" class="sys-mini" data-act="shields" data-d="10" aria-label="Shields up 10" ${sh >= 60 ? "disabled" : ""}>+</button></div>${eqLine(s, "shields", numbers)}`;
  }
  if (id === "rover") {
    const busy = !!rv.busy;
    return `<div class="sys-gauge" role="group" aria-label="Rover"><div class="sys-gl"><span>Rover</span>${whyB("rover", "Rover and ice")}</div>
        <div class="sys-gv sys-gtext"><b>${busy ? `${esc(TASK[rv.task] || "Out")}` : "Parked"}</b>${busy && rv.eta_h != null ? `<small> · back in ${esc(rv.eta_h)} h</small>` : ""}</div>${eqLine(s, "rover", numbers)}</div>
      ${rv.battery_pct != null ? row("Battery", Math.round(rv.battery_pct) + "%") : ""}${!cadet && rv.dose_msv != null ? row("Rover dose", (+rv.dose_msv).toFixed(1) + (numbers ? " mSv" : "")) : ""}
      ${s.ice_runs != null ? row("Ice runs", esc(s.ice_runs)) : ""}
      <div class="sys-seg" role="group" aria-label="Send the rover">${ROVER.map(([t, n, i]) => {
        const on = busy && rv.task === t, off = t === "return" ? !busy || rv.task === "return" : busy;
        return `<button type="button" class="sys-rv" data-act="rover" data-task="${t}" data-target="rover:${t}" aria-pressed="${on}" ${off ? "disabled" : ""}>${ic(i, 22)}<span>${n}</span></button>`; }).join("")}</div>`;
  }
  if (id === "life") {
    const lp = Math.round(r.life_support_pct || 0);
    return `${gauge(s, { id: "life_support", name: "Life support", val: lp, unit: "%", warn: lp < 25, pct: lp, numbers })}
      ${row("Air system", Math.round(L.life_support || 0) + "%")}${row(pretendLabel("Greenhouse"), Math.round(L.greenhouse || 0) + "%")}
      ${row(`Heaters${whyB("heaters", "Heaters")}`, U ? `${kw(U.heater_kw)} · ${U.heater_duty_pct}%` : Math.round(L.heaters || 0) + "%")}${eqLine(s, "heaters", numbers)}
      ${U && U.outside_k != null ? row("Outside", `${U.outside_k} K · ${U.outside_c} °C`) : ""}`;
  }
  if (id === "radio") {
    const lines = (o.log || []).slice(-3);
    return `<div class="sys-gauge" role="group" aria-label="Radio"><div class="sys-gl"><span>Earth</span></div>
        <div class="sys-gv sys-gtext"><b>${e.earth_visible ? "In view" : "Below the horizon"}</b></div></div>
      ${!e.earth_visible && e.next_comm_window_h != null ? row("Next window", `${e.next_comm_window_h} h`) : ""}
      ${e.earth_visible ? row("Radio delay", `${((e.comm_delay_s || 2.6) / 2).toFixed(1)} s each way`) : ""}${s.science_waiting != null ? row("Science to send", Math.round(s.science_waiting)) : ""}
      <button type="button" class="sys-call" data-act="houston" data-target="houston" ${o.calling ? "disabled" : ""}>${ic("houston", 22)}<span>${o.calling ? "Signal travelling" : "Call Houston"}</span></button>
      ${lines.length ? `<ol class="sys-log" aria-label="Radio log">${lines.map(l => `<li><b>${esc(l.who)}</b> ${esc(l.text)}</li>`).join("")}</ol>` : ""}`;
  }
  return "";
}

// ---------------------------------------------------------------- DOM -----------------------------------------------

/**
 * cab: the cabin's .cb. deps: {onCommand(cmd), onHouston(), level() -> "cadet" | "commander" | "engineer", onToggle(open),
 * log() -> [{who, text}]}. Returns the drawer's API; `key` is the Systems key for the window-key row.
 */
export function createSystems(cab, deps = {}) {
  const d = { onCommand() {}, onHouston() {}, level: () => "commander", onToggle() {}, log: () => [], ...deps };
  const el = document.createElement("section");
  el.className = "cb-sys"; el.id = "cbSys"; el.hidden = true; el.setAttribute("aria-label", "Systems");
  el.innerHTML = `<header class="sys-head"><h2 class="sys-t" id="cbSysT"></h2><span class="sys-n" id="cbSysN"></span>
      <button type="button" class="sys-x" id="cbSysX" aria-label="Close Systems" title="Close (Esc)">${ic("close", 20)}</button></header>
    <nav class="sys-tabs" aria-label="Systems panels"><kbd class="sys-kb" data-k="prev" aria-hidden="true"></kbd><span class="sys-tl" role="tablist" id="cbSysTabs"></span><kbd class="sys-kb" data-k="next" aria-hidden="true"></kbd></nav>
    <div class="sys-body" id="cbSysBody" role="tabpanel" aria-labelledby="cbSysT"></div>`;
  cab.append(el);
  const key = document.createElement("button");
  key.type = "button"; key.className = "cb-syskey"; key.id = "cbSysKey";
  key.setAttribute("aria-expanded", "false"); key.setAttribute("aria-controls", "cbSys"); key.setAttribute("aria-keyshortcuts", "] [");
  key.title = "Systems: power, radiation, rover ( [ and ] )";
  key.innerHTML = `${ic("view", 18)}<span>Systems</span>`;
  const q = s => el.querySelector(s);
  let cur = null, st = null, target = null, calling = false, renderKey = "";
  const list = () => systemsFor(d.level()).map(s => s.id);
  const sysOf = id => SYSTEMS.find(s => s.id === id);

  /** The drawer sits under the window keys, down to the radio row, on the right wall. */
  function place() {
    if (el.hidden) return;
    const C = cab.getBoundingClientRect(), vb = cab.querySelector(".cb-viewbar"), V = vb && vb.getClientRects().length ? vb.getBoundingClientRect() : null;
    const cr = cab.querySelector(".cb-commrow"), R = cr && cr.getClientRects().length ? cr.getBoundingClientRect() : null;
    const top = Math.round((V ? V.bottom : C.top + 120) - C.top + 8);
    el.style.top = top + "px";
    el.style.bottom = Math.round(R && R.top > C.top + top + 160 ? C.bottom - R.top + 8 : 12) + "px";
  }
  let tabsKey = "";
  function paintTabs() {
    const ids = list(), i = ids.indexOf(cur), pad = document.documentElement.dataset.input === "pad";
    el.querySelectorAll(".sys-kb").forEach(k => { k.textContent = k.dataset.k === "prev" ? (pad ? "LB" : "[") : (pad ? "RB" : "]"); });
    if (tabsKey === ids.join() + "|" + cur) return;   // a state tick never rebuilds the tabs (a focused tab keeps focus)
    tabsKey = ids.join() + "|" + cur;
    q("#cbSysT").textContent = (sysOf(cur) || {}).name || "";
    q("#cbSysN").textContent = ids.length > 1 ? `${i + 1} of ${ids.length}` : "";
    const ft = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.sys : null;
    q("#cbSysTabs").innerHTML = ids.map(id => { const s = sysOf(id);
      return `<button type="button" role="tab" class="sys-tab" data-sys="${id}" aria-selected="${id === cur}" aria-label="${esc(s.name)}" title="${esc(s.name)}">${ic(s.icon, 22)}</button>`; }).join("");
    if (ft) { const n = q(`.sys-tab[data-sys="${ft}"]`); if (n) n.focus({ preventScroll: true }); }
  }
  function paintBody(force) {
    if (el.hidden || !cur) return;
    const html = panelHtml(cur, st, { level: d.level(), log: d.log(), calling });
    const k = cur + "|" + html;
    if (!force && k === renderKey) return;
    // a re-render keeps the focused control (by its act / data) so the arrows and a held A never lose their place
    const a = document.activeElement, keyOf = n => n && n.dataset ? [n.dataset.act, n.dataset.k, n.dataset.d, n.dataset.task, n.dataset.sw, n.dataset.why].join("|") : null;
    const had = a && el.querySelector("#cbSysBody").contains(a) ? keyOf(a) : null;
    renderKey = k; q("#cbSysBody").innerHTML = html;
    if (had) { const n = [...el.querySelectorAll("#cbSysBody button")].find(b => keyOf(b) === had && !b.disabled); if (n) n.focus({ preventScroll: true }); }
    light();
  }
  /** The Now job's control in this panel wears the cabin's glow (.is-point); nothing else in the drawer is lit. */
  function light() {
    el.querySelectorAll(".is-point").forEach(n => n.classList.remove("is-point"));
    const sel = controlSel(target, d.level()), n = sel && q("#cbSysBody " + sel);
    if (n) n.classList.add("is-point");
    return n || null;
  }
  function firstControl() { return q("#cbSysBody .is-point") || [...el.querySelectorAll("#cbSysBody button")].find(b => !b.disabled && !b.classList.contains("sys-why")) || q(`.sys-tab[data-sys="${cur}"]`); }
  function focusIn() { requestAnimationFrame(() => { const n = firstControl(); if (n) n.focus({ preventScroll: true }); }); }
  /** Open at a panel (id), or at the Now job's panel, the last one shown, or the first. focus: move focus inside. */
  function open(id, { focus = false } = {}) {
    const ids = list(); if (!ids.length) return false;
    const want = id && ids.includes(id) ? id : !id ? (systemOfTarget(target, d.level()) || (ids.includes(cur) ? cur : ids[0])) : null;
    if (!want) return false;
    const was = !el.hidden; cur = want; el.hidden = false; el.dataset.sys = cur; el.dataset.gauge = (sysOf(cur) || {}).gauge || "";
    key.setAttribute("aria-expanded", "true"); key.classList.add("is-open"); cab.classList.add("has-sys");
    paintTabs(); place(); paintBody(true);
    if (!was) d.onToggle(true);
    if (focus) focusIn();
    return true;
  }
  function close({ focus = false } = {}) {
    if (el.hidden) return false;
    const had = el.contains(document.activeElement);
    el.hidden = true; key.setAttribute("aria-expanded", "false"); key.classList.remove("is-open"); cab.classList.remove("has-sys");
    d.onToggle(false);
    if (focus || had) key.focus({ preventScroll: true });
    return true;
  }
  function step(dir, { focus = false } = {}) {
    if (el.hidden) return open(null, { focus });
    const inside = el.contains(document.activeElement);   // before the re-render drops the focused control
    const ok = open(stepSystem(list(), cur, dir));
    if (ok && (focus || inside)) focusIn();
    return ok;
  }

  key.addEventListener("click", e => (el.hidden ? open(null, { focus: e.detail === 0 }) : close({ focus: e.detail === 0 })));   // detail 0: Enter / A
  q("#cbSysX").onclick = e => close({ focus: true });
  el.addEventListener("click", e => {
    const t = e.target.closest && e.target.closest("button"); if (!t || !el.contains(t) || t.disabled) return;
    if (t.dataset.sys) { open(t.dataset.sys); return; }   // paintTabs keeps focus on the tab pressed
    const act = t.dataset.act; if (!act) return;   // (i): the cabin's own Why handler takes it (data-why, capture)
    if (act === "houston") { d.onHouston(); return; }
    const cmd = commandFor(act, t.dataset, st); if (cmd) d.onCommand(cmd);
  });
  // Esc / B: the app's back (mission/ui.js) closes a Why card first, then the drawer, and focus goes to the Systems key
  const onResize = () => place(); addEventListener("resize", onResize);

  return {
    el, key, open, close, step, place,
    toggle: (opts = {}) => (el.hidden ? open(null, opts) : close(opts)),
    get isOpen() { return !el.hidden; }, get current() { return el.hidden ? null : cur; }, get list() { return list(); },
    /** The main gauge of the panel on show (Y on a controller, I on the keys: its Why card). */
    get gauge() { if (el.hidden) return null; const f = document.activeElement; const w = f && el.contains(f) && f.dataset && f.dataset.why; return w || (sysOf(cur) || {}).gauge || null; },
    update(s) { st = s; if (!el.hidden) { const ids = list(); if (!ids.includes(cur)) { open(ids[0]); return; } paintTabs(); paintBody(); } },
    /** The Now job's target (objective.js). A new job whose control is in another panel brings that panel up (only
     *  while the drawer is open; a closed drawer stays closed: the Now card's button is enough). */
    point(t) {
      const was = target; target = t || null;
      if (!el.hidden && target !== was) { const id = systemOfTarget(target, d.level()); if (id && id !== cur) { const f = el.contains(document.activeElement); open(id); if (f) focusIn(); } }
      return light();
    },
    /** The control a target points at, if it is on screen in the drawer (the done pulse). */
    controlFor(t) { const sel = !el.hidden && controlSel(t, d.level()); return sel ? q("#cbSysBody " + sel) : null; },
    calling(on) { calling = !!on; paintBody(); },
    refresh() { paintTabs(); paintBody(true); },
    dispose() { removeEventListener("resize", onResize); el.remove(); key.remove(); },
  };
}
