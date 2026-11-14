// Outpost Luna cockpit: the mission-control console on the right of the Mission screen (and, in "mini" mode, the
// check ride's simplified console in the Academy, so the real one feels familiar).
// Panels: mission clock + sky, gauges (power, life support, dose with a red zone), Caution & Warning annunciators,
// power-split levers (7, keyboard + pointer), comms (Earth light, window countdown, Call Houston, radio log),
// rover + shelter, End shift. Pure view: every control calls back; state comes in through update().
import { callSign } from "../story.js";

export const LOADS = [
  ["shields", "Shields", "", "Blocks radiation"], ["life_support", "Air", "", "Makes air and water"],
  ["greenhouse", "Greenhouse", "", "Plants make oxygen"], ["science", "Science", "", "Earns points"],
  ["rover", "Rover", "", "Drives the rover"], ["comms", "Radio", "", "Talks to Earth"], ["heaters", "Heaters", "", "Keeps pipes from freezing"],
];
const TASK = { collect_ice: "Getting ice", explore: "Exploring", repair_array: "Fixing a panel", return: "Driving home" };
const TARGET = { collect_ice: "Shackleton ice", explore: "Cabeus", repair_array: "Solar array", return: "Outpost" };
const TOTAL_H = { collect_ice: 10, explore: 8, repair_array: 5, return: 5 };

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clamp = (v, a = 0, b = 100) => Math.max(a, Math.min(b, +v || 0));
const r5 = v => Math.round(clamp(v) / 5) * 5;

// ---- gauge geometry: a 180° dial, centre (50,54), radius 40 ----
const pt = f => [50 - 40 * Math.cos(Math.PI * f), 54 - 40 * Math.sin(Math.PI * f)].map(n => n.toFixed(2)).join(" ");
const arc = (a, b) => `M ${pt(a)} A 40 40 0 0 1 ${pt(b)}`;
function gauge(id, name, { red = null, amber = null } = {}) {
  const ticks = [0, .25, .5, .75, 1].map(f => { const [x1, y1] = [50 - 44 * Math.cos(Math.PI * f), 54 - 44 * Math.sin(Math.PI * f)], [x2, y2] = [50 - 48 * Math.cos(Math.PI * f), 54 - 48 * Math.sin(Math.PI * f)];
    return `<line class="g-tick" x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`; }).join("");
  return `<figure class="ck-gauge" id="ckg-${id}" role="meter" aria-label="${esc(name)}" aria-valuemin="0" aria-valuemax="100">
    <svg viewBox="0 -2 100 62" aria-hidden="true">
      <path class="g-bg" d="${arc(0, 1)}"/>
      ${amber ? `<path class="g-amber" d="${arc(amber[0], amber[1])}"/>` : ""}${red ? `<path class="g-red" d="${arc(red[0], red[1])}"/>` : ""}
      ${ticks}<path class="g-val" d="${arc(0, 1)}" pathLength="100" stroke-dasharray="0 100"/>
      <g class="g-needle"><line x1="50" y1="54" x2="16" y2="54"/><circle cx="50" cy="54" r="4"/></g>
    </svg>
    <figcaption><b>${esc(name)}</b><span class="g-num">–</span></figcaption></figure>`;
}

/** Caution & Warning: [id, label, level, lit(state)] */
const CW = [
  ["storm", "Solar storm", "red", s => !!(s.env.storm && s.env.storm.active)],
  ["dose", "High dose", "red", s => (s.alerts || []).some(a => a === "dose_rate_high" || a === "dose_near_limit") || s.resources.dose_msv / (s.resources.dose_limit_msv || 50) > .7],
  ["power", "Low power", "amber", s => (s.alerts || []).includes("low_power") || s.resources.power_pct < 25],
  ["life", "Life support low", "amber", s => (s.alerts || []).includes("life_support_low") || s.resources.life_support_pct < 25],
  ["comm", "Comm closed", "amber", s => !s.env.earth_visible],
  ["rover", "Rover out", "blue", s => !!(s.rover && s.rover.busy)],
  ["array", "Array damage", "amber", s => (s.alerts || []).includes("array_damaged")],
  ["shelter", "In shelter", "green", s => !!s.shelter],
];
const MASTER = ["storm", "dose", "power", "life"];   // the master alarm lights when any of these is lit

/**
 * @param {HTMLElement} root  where the console renders
 * @param {object} o
 * @param {"full"|"mini"} [o.mode]  mini = check ride: clock, gauges, C&W, read-only levers
 */
export function createCockpit(root, o = {}) {
  const mode = o.mode || "full", full = mode === "full";
  const cb = { onAllocate() {}, onShelter() {}, onRover() {}, onHouston() {}, onEndShift() {}, onDebrief() {}, badges: () => [], ...o };
  let st = null, lastLoads = null, lastLit = new Set(), logLines = [], dragging = null;

  root.innerHTML = `
  <div class="ck ck-${mode}">
    <section class="ck-clock" aria-label="Mission clock">
      <div class="ck-time"><span class="ck-lbl">Mission clock</span><b id="ckDay">Day 1 · shift 1</b></div>
      <svg class="ck-sky" viewBox="0 0 96 40" aria-hidden="true"><rect class="sky-bg" x="0" y="0" width="96" height="40" rx="6"/>
        <line class="sky-hz" x1="4" x2="92" y1="26" y2="26"/><path class="sky-ridge" d="M4 26 L18 22 L28 25 L40 19 L52 24 L64 21 L78 25 L92 23 L92 26 Z"/>
        <circle class="sky-sun" id="ckSun" cx="30" cy="22" r="5"/><circle class="sky-earth" id="ckEarth" cx="70" cy="18" r="4"/></svg>
      <div class="ck-sunv"><span class="ck-lbl">Sun</span><b id="ckSunDeg">–</b></div>
      ${full ? `<div class="ck-patches" id="ckPatches" aria-label="Flight School patches"></div><div class="ck-score"><span class="ck-lbl">Score</span><b id="ckScore">0</b></div>` : ""}
    </section>
    <section class="ck-gauges" aria-label="Gauges">
      ${gauge("power", "Power", { red: [0, .2], amber: [.2, .3] })}${gauge("life", "Air & water", { red: [0, .2], amber: [.2, .3] })}${gauge("dose", "Radiation dose", { amber: [.6, .8], red: [.8, 1] })}
    </section>
    <section class="ck-cw" aria-label="Caution and warning lights" aria-live="polite">
      ${CW.map(([id, label, lvl]) => `<span class="ck-ann is-${lvl}" id="cka-${id}"><span>${esc(label)}</span></span>`).join("")}
      <span class="ck-ann is-master" id="cka-master"><span>Master alarm</span></span>
    </section>
    <section class="ck-levers" aria-label="Power split. Use the arrow keys on a lever.">
      <header><span class="ck-lbl">Power split</span><small id="ckSum"></small></header>
      <div class="ck-lvrow">${LOADS.map(([k, n, ico, help]) => `
        <div class="ck-lever" data-k="${k}">
          <span class="ck-lv-val">0</span>
          <div class="ck-track" role="slider" tabindex="${full ? 0 : -1}" aria-orientation="vertical" aria-label="${esc(n)}: ${esc(help)}"
            aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"${full ? "" : ` aria-readonly="true"`}><i class="ck-fill"></i><b class="ck-knob"></b></div>
          <span class="ck-lname">${esc(n)}</span>
        </div>`).join("")}</div>
    </section>
    ${full ? `
    <section class="ck-comms" aria-label="Comms">
      <header><span class="ck-lbl">Comms</span><span class="ck-earthlamp" id="ckEarthLamp"><i></i><span>Earth in view</span></span></header>
      <p class="ck-window" id="ckWindow"></p>
      <button type="button" class="ck-call" id="ckCall"><span>Call Houston</span><i class="ck-waves" aria-hidden="true"></i></button>
      <ol class="ck-log" id="ckLog" aria-label="Radio log"></ol>
    </section>
    <section class="ck-rover" aria-label="Rover and crew">
      <header><span class="ck-lbl">Rover</span><b id="ckRoverSt">Parked</b></header>
      <svg class="ck-path" viewBox="0 0 160 34" aria-hidden="true"><path class="p-line" d="M10 22 C 50 4, 100 34, 150 14"/>
        <circle class="p-base" cx="10" cy="22" r="5"/><circle class="p-goal" cx="150" cy="14" r="5"/><circle class="p-rover" id="ckRoverDot" cx="10" cy="22" r="4.5"/></svg>
      <p class="ck-rtgt" id="ckRoverTgt">At the outpost</p>
      <div class="ck-rbtns"><button type="button" class="ck-btn" data-task="collect_ice">Get ice</button><button type="button" class="ck-btn" data-task="explore">Explore</button></div>
      <button type="button" class="ck-switch" id="ckShelter" role="switch" aria-checked="false"><i aria-hidden="true"></i><span>Crew shelter</span></button>
    </section>
    <div class="ck-foot"><button type="button" class="ck-end" id="ckEnd"><span>End shift</span><small id="ckEndSub">Shift 1 of 4</small></button>
      <button type="button" class="ck-db" id="ckDebrief">Debrief</button></div>` : ""}
  </div>`;
  const q = s => root.querySelector(s);
  const path = full ? q(".ck-path .p-line") : null;

  // ---- levers: pointer drag (sets a share) and keys (nudge) ----
  root.querySelectorAll(".ck-lever").forEach(lv => {
    const k = lv.dataset.k, tr = lv.querySelector(".ck-track");
    if (!full) return;
    const valAt = y => { const r = tr.getBoundingClientRect(); return clamp((r.bottom - y) / r.height * 100); };
    tr.addEventListener("pointerdown", e => { e.preventDefault(); tr.setPointerCapture(e.pointerId); tr.focus({ preventScroll: true }); dragging = { k, v: valAt(e.clientY) }; paintLever(lv, dragging.v); lv.classList.add("is-drag"); });
    tr.addEventListener("pointermove", e => { if (dragging && dragging.k === k) { dragging.v = valAt(e.clientY); paintLever(lv, dragging.v); } });
    const up = () => { if (!dragging || dragging.k !== k) return; const v = r5(dragging.v); dragging = null; lv.classList.remove("is-drag");
      if (st && v !== Math.round(st.loads[k] || 0)) cb.onAllocate(k, { kind: "percent", value: v }); else if (st) paintLever(lv, st.loads[k]); };
    tr.addEventListener("pointerup", up); tr.addEventListener("pointercancel", up);
    tr.addEventListener("keydown", e => {
      const d = { ArrowUp: 5, ArrowRight: 5, ArrowDown: -5, ArrowLeft: -5, PageUp: 10, PageDown: -10 }[e.key];
      if (d == null) return; e.preventDefault(); e.stopPropagation(); cb.onAllocate(k, { kind: "delta", value: d });
    });
  });
  function paintLever(lv, v) {
    v = clamp(v); lv.style.setProperty("--v", v);
    lv.querySelector(".ck-lv-val").textContent = Math.round(v) + "%";
    const tr = lv.querySelector(".ck-track"); tr.setAttribute("aria-valuenow", Math.round(v)); tr.setAttribute("aria-valuetext", Math.round(v) + " percent");
  }
  if (full) {
    q("#ckCall").onclick = () => cb.onHouston();
    q("#ckEnd").onclick = () => cb.onEndShift();
    q("#ckDebrief").onclick = () => cb.onDebrief();
    q("#ckShelter").onclick = () => st && cb.onShelter(!st.shelter);
    root.querySelectorAll("[data-task]").forEach(b => b.onclick = () => cb.onRover(b.dataset.task));
  }

  function setGauge(id, frac, text, valNow) {
    const g = q("#ckg-" + id); if (!g) return;
    frac = clamp(frac * 100) / 100;
    g.querySelector(".g-val").setAttribute("stroke-dasharray", `${(frac * 100).toFixed(1)} 100`);
    g.querySelector(".g-needle").style.transform = `rotate(${(frac * 180).toFixed(1)}deg)`;
    g.querySelector(".g-num").textContent = text;
    g.setAttribute("aria-valuenow", Math.round(valNow)); g.setAttribute("aria-valuetext", text);
    const danger = id === "dose" ? frac >= .8 : frac < .2, warn = id === "dose" ? frac >= .6 : frac < .3;
    g.classList.toggle("is-red", danger); g.classList.toggle("is-amber", !danger && warn);
  }
  function gauges(r, lim) {
    setGauge("power", r.power_pct / 100, Math.round(r.power_pct) + "%", r.power_pct);
    setGauge("life", r.life_support_pct / 100, Math.round(r.life_support_pct) + "%", r.life_support_pct);
    setGauge("dose", r.dose_msv / lim, `${(+r.dose_msv).toFixed(1)} / ${lim} mSv`, r.dose_msv / lim * 100);
  }
  function sky(sunDeg, earthDeg, earthUp) {
    const y = d => clamp(26 - d * 2.2, 4, 38);   // exaggerated: the polar Sun only ever skims the horizon
    const sun = q("#ckSun"), earth = q("#ckEarth");
    sun.setAttribute("cy", y(sunDeg).toFixed(1)); sun.classList.toggle("is-down", sunDeg < 0);
    earth.setAttribute("cy", y(earthDeg ?? (earthUp ? 3 : -3)).toFixed(1)); earth.classList.toggle("is-down", !earthUp);
    q("#ckSunDeg").textContent = `${(+sunDeg || 0).toFixed(1)}°`;
  }

  /** Paint the whole console from a mission State. */
  function update(s) {
    if (!s) return; st = s;
    const r = s.resources, e = s.env || {}, lim = r.dose_limit_msv || 50;
    q("#ckDay").textContent = `Day ${s.day} · shift ${s.shift}`;
    sky(+e.sun_elev_deg || 0, e.earth_elev_deg, !!e.earth_visible);
    gauges(r, lim);
    // annunciators: a light that just came on flashes once
    const lit = new Set();
    CW.forEach(([id, , , f]) => { let on = false; try { on = f(s); } catch (x) { /* partial state */ } const el = q("#cka-" + id); el.classList.toggle("is-lit", on);
      if (on) { lit.add(id); if (!lastLit.has(id)) { el.classList.remove("is-new"); void el.offsetWidth; el.classList.add("is-new"); } } });
    lastLit = lit;
    const m = MASTER.some(id => lit.has(id)), me = q("#cka-master"); if (me) { me.classList.toggle("is-lit", m); }
    // levers: the one the order moved animates to its new spot
    let sum = 0;
    root.querySelectorAll(".ck-lever").forEach(lv => {
      const k = lv.dataset.k, v = Math.round(s.loads[k] || 0); sum += v;
      if (dragging && dragging.k === k) return;
      paintLever(lv, v);
      if (lastLoads && Math.abs((lastLoads[k] || 0) - v) >= 1) { lv.classList.remove("is-moved"); void lv.offsetWidth; lv.classList.add("is-moved"); setTimeout(() => lv.classList.remove("is-moved"), 1400); }
    });
    lastLoads = { ...s.loads };
    q("#ckSum").textContent = `${sum}% of power in use`;
    if (!full) return;
    q("#ckScore").textContent = String(s.score || 0);
    q("#ckPatches").innerHTML = cb.badges().map(b => `<span class="ck-patch" title="${esc(b.name)}">${b.patch}</span>`).join("");
    // comms
    const up = !!e.earth_visible;
    q("#ckEarthLamp").classList.toggle("is-on", up); q("#ckEarthLamp span").textContent = up ? "Earth in view" : "Earth hidden";
    q("#ckCall").classList.toggle("is-nosignal", !up);
    q("#ckWindow").innerHTML = up ? `Window open · radio takes <b>${((e.comm_delay_s || 2.6) / 2).toFixed(1)} s</b> each way`
      : `Next window in <b>${e.next_comm_window_h ?? "?"} h</b>`;
    // rover + shelter
    const rv = s.rover || {}, busy = !!rv.busy;
    q("#ckRoverSt").textContent = busy ? TASK[rv.task] || rv.task : "Parked";
    q("#ckRoverTgt").textContent = busy ? `${TARGET[rv.task] || "Out"} · back in ${rv.eta_h} h` : "At the outpost. Ready to roll.";
    const p = busy ? 1 - (rv.eta_h || 0) / (TOTAL_H[rv.task] || 8) : 0, f = p < .5 ? p * 2 : (1 - p) * 2;
    if (path) { const L = path.getTotalLength(), P = path.getPointAtLength(clamp(f, 0, 1) * L); const d = q("#ckRoverDot"); d.setAttribute("cx", P.x.toFixed(1)); d.setAttribute("cy", P.y.toFixed(1)); }
    root.querySelectorAll("[data-task]").forEach(b => { b.disabled = busy; });
    const sh = q("#ckShelter"); sh.setAttribute("aria-checked", !!s.shelter);
    q("#ckEndSub").textContent = s.over ? "Mission over" : `Shift ${s.shift} of 4 · day ${s.day} of 10`;
  }
  /** Live telemetry frames between shifts: gauges + sky only. */
  function telemetry(f) {
    if (!st) return;
    const lim = st.resources.dose_limit_msv || 50;
    gauges({ power_pct: f.power, life_support_pct: f.life_support, dose_msv: f.dose_msv }, lim);
    if (f.sun_elev_deg != null) sky(f.sun_elev_deg, f.earth_elev_deg, f.comm ? f.comm === "open" : st.env.earth_visible);
  }
  /** Radio log: CAPCOM, Houston and the kid's own orders (labelled with the call sign). */
  function log(who, text) {
    if (!full || !text) return;
    const last = logLines[logLines.length - 1]; if (last && last.text === text) return;
    logLines.push({ who, text }); logLines = logLines.slice(-12);
    const el = q("#ckLog");
    el.innerHTML = logLines.slice(-4).map(l => `<li class="is-${l.who}"><b>${esc(l.who === "kid" ? callSign.shown() : l.who === "houston" ? "Houston" : "CAPCOM")}</b> ${esc(l.text)}</li>`).join("");
  }
  function calling(on) { if (full) { const b = q("#ckCall"); b.classList.toggle("is-calling", !!on); b.disabled = !!on; } }
  function busy(on) { if (full) q("#ckEnd").disabled = !!on; }
  return { update, telemetry, log, calling, busy, get state() { return st; } };
}
