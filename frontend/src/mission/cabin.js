// Outpost Luna cabin: the Mission screen as the inside of a spacecraft. Top: a window onto the south-pole horizon
// (Sun, Earth and the rover placed from the sim's real elevations; storm banner on the glass). Bottom: an instrument
// panel: three glass display units with softkeys (PWR / LIFE / RAD / COMM pages), hab-system lever switches (the
// shelter and rover recall sit under red flip-up guards), a rotary shield knob, a caution & warning matrix with a
// MASTER ALARM pushbutton, PTT · HOUSTON, END SHIFT, and a phosphor caption strip.
// Pure view, same API as cockpit.js: update(state), telemetry(frame), log(who, text), calling(on), busy(on).
// Every control is a <button> (or role=slider) with an aria-label that states its state; lamps carry text.
// Cabin fonts ship with the app (the desktop build runs offline): stencil legends + the phosphor display face.
import "@fontsource/barlow-condensed/latin-600.css";
import "@fontsource/barlow-condensed/latin-700.css";
import "@fontsource/share-tech-mono/latin-400.css";
import "../cabin.css";
import { callSign } from "../story.js";
import { LOADS } from "./cockpit.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clamp = (v, a = 0, b = 100) => Math.max(a, Math.min(b, +v || 0));
const PAGES = ["PWR", "LIFE", "RAD", "COMM"];
/** Window zoom levels on the real NASA globe (globe.js): orbit, the site approach, the rover's route. */
export const VIEWS = [["orbit", "ORBIT"], ["site", "SITE"], ["rover", "ROVER"], ["earth", "EARTH"]];
const TASK = { collect_ice: "ICE RUN", explore: "EXPLORE", repair_array: "ARRAY FIX", return: "RETURNING" };
/** [id, text, level, lit(state)] — level: warn (red) | caution (amber) | info (blue) */
const LAMPS = [
  ["storm", "SOLAR STORM", "warn", s => !!(s.env.storm && s.env.storm.active)],
  ["dose", "DOSE RATE", "warn", s => (s.alerts || []).some(a => a === "dose_rate_high" || a === "dose_near_limit") || s.resources.dose_msv / (s.resources.dose_limit_msv || 50) > .7],
  ["power", "LOW POWER", "caution", s => (s.alerts || []).includes("low_power") || s.resources.power_pct < 25],
  ["life", "LOW AIR", "caution", s => (s.alerts || []).includes("life_support_low") || s.resources.life_support_pct < 25],
  ["array", "ARRAY DMG", "caution", s => (s.alerts || []).includes("array_damaged")],
  ["comm", "NO EARTH", "caution", s => !s.env.earth_visible],
  ["rover", "ROVER OUT", "info", s => !!(s.rover && s.rover.busy)],
  ["night", "NIGHT", "info", s => !s.env.in_sun],
];
/** Hab lever switches: [id, label, guarded, on(state), command(on)] */
const LEVERS = [
  ["shelter", "Storm shelter", true, s => !!s.shelter, on => ({ type: "shelter", on })],
  ["heaters", "Cabin heaters", false, s => (s.loads.heaters || 0) >= 8, on => ({ type: "allocate", to: "heaters", amount: { kind: "percent", value: on ? 15 : 0 }, from: null })],
  ["science", "Science lab", false, s => (s.loads.science || 0) > 0, on => ({ type: "allocate", to: "science", amount: { kind: "percent", value: on ? 15 : 0 }, from: null })],
  ["recall", "Rover recall", true, s => !!(s.rover && s.rover.busy && s.rover.task === "return"), () => ({ type: "dispatch", vehicle: "rover", task: "return", target: null })],
];

export function createCabin(root, o = {}) {
  const cb = { onCommand() {}, onHouston() {}, onEndShift() {}, onDebrief() {}, onView() {}, badges: () => [], ...o };
  let view = "site";
  let st = null, prev = null, pages = ["PWR", "LIFE", "RAD"], sel = 0, logLines = [], litBefore = new Set(), masterOn = false, capT = null;
  const guards = { shelter: false, recall: false };

  root.innerHTML = `
  <div class="cb">
    <section class="cb-window" aria-label="Window: the south-pole horizon">
      <svg class="cb-bulk" id="cbBulk" aria-hidden="true"></svg>
      <div class="cb-glass">
        <div class="cb-tint" aria-hidden="true"></div>
        <div class="cb-reveal" aria-hidden="true"></div>
        <nav class="cb-crumbs" aria-label="View"><ol id="cbCrumbs"></ol></nav>
        <div class="cb-views" role="group" aria-label="Window view">${VIEWS.map(([id, n]) => `<button type="button" class="cb-view" data-view="${id}" aria-pressed="${id === "site"}">${n}</button>`).join("")}</div>
        <div class="cb-rover" id="cbRover" hidden><span id="cbRoverTxt"></span></div>
        <div class="cb-storm" id="cbStorm" hidden role="status"></div>
        <div class="cb-read" id="cbRead"></div>
        <div class="cb-clock" id="cbClock"></div>
      </div>
    </section>
    <section class="cb-panel" aria-label="Instrument panel">
      <div class="cb-dus">${[0, 1, 2].map(d => `
        <div class="cb-du" data-du="${d}">
          <div class="cb-keys">${PAGES.map(p => `<button type="button" class="cb-sk" data-du="${d}" data-page="${p}" aria-pressed="false" aria-label="Display ${d + 1}: show ${p} page">${p}</button>`).join("")}</div>
          <div class="cb-screen" aria-live="off"><div class="cb-scr" id="cbDu${d}"></div><i class="cb-glare" aria-hidden="true"></i></div>
          <div class="cb-keys is-r" id="cbRk${d}"></div>
          <span class="cb-dulab" aria-hidden="true">DU ${d + 1}</span>
        </div>`).join("")}
      </div>
      <div class="cb-row">
        <section class="cb-plate cb-hab" aria-label="Hab systems"><h3>Hab systems</h3>
          <div class="cb-levers">${LEVERS.map(([id, label, guarded]) => `
            <div class="cb-lv" data-lv="${id}">
              <b>${esc(label)}</b>
              <span class="cb-tb" aria-hidden="true"></span>
              <div class="cb-lvbox">
                <span class="cb-onoff" aria-hidden="true"><em>${id === "recall" ? "RTN" : "ON"}</em><em>${id === "recall" ? "—" : "OFF"}</em></span>
                <button type="button" class="cb-lever" data-lv="${id}" aria-pressed="false" aria-label="${esc(label)}"><i aria-hidden="true"></i></button>
                ${guarded ? `<button type="button" class="cb-guard" data-guard="${id}" aria-pressed="false" aria-label="${esc(label)} guard: closed. Lift the guard first"><span aria-hidden="true"></span></button>` : ""}
              </div>
              <small class="cb-lvst"></small>
            </div>`).join("")}</div>
        </section>
        <section class="cb-plate cb-shield" aria-label="Shield power"><h3>Shield power %</h3>
          <div class="cb-knobwrap">
            <svg class="cb-dial" viewBox="0 0 120 120" aria-hidden="true">${[0, 10, 20, 30, 40, 50, 60].map(v => { const a = (-135 + v / 60 * 270) * Math.PI / 180;
              return `<line x1="${60 + 46 * Math.sin(a)}" y1="${60 - 46 * Math.cos(a)}" x2="${60 + 54 * Math.sin(a)}" y2="${60 - 54 * Math.cos(a)}"/><text x="${60 + 38 * Math.sin(a)}" y="${63 - 38 * Math.cos(a)}">${v}</text>`; }).join("")}</svg>
            <div class="cb-knob" id="cbKnob" role="slider" tabindex="0" aria-label="Shield power" aria-valuemin="0" aria-valuemax="60" aria-valuenow="0"><i aria-hidden="true"></i><u aria-hidden="true"></u></div>
          </div>
          <div class="cb-knobrow"><button type="button" class="cb-mini" id="cbShMinus" aria-label="Shields down 10">−10</button><b id="cbShVal">0%</b><button type="button" class="cb-mini" id="cbShPlus" aria-label="Shields up 10">+10</button></div>
        </section>
        <section class="cb-plate cb-cw" aria-label="Caution and warning"><h3>Caution &amp; warning
          <button type="button" class="cb-master" id="cbMaster" aria-label="Master alarm: off">MASTER<br>ALARM</button></h3>
          <div class="cb-lamps" role="list">${LAMPS.map(([id, t, lvl]) => `<span class="cb-lamp is-${lvl}" id="cbl-${id}" role="listitem"><span class="cb-lens">${t}</span><span class="cb-vh">: off</span></span>`).join("")}</div>
        </section>
        <section class="cb-plate cb-comm" aria-label="Comms and shift"><h3>Comm · shift</h3>
          <button type="button" class="cb-ptt" id="cbPtt" aria-label="Push to talk: call Houston"><span>PTT · HOUSTON</span><small id="cbPttSub"></small></button>
          <div class="cb-ends"><button type="button" class="cb-end" id="cbEnd" aria-label="End shift"><span>END SHIFT</span><small id="cbEndSub"></small></button>
          <button type="button" class="cb-db" id="cbDb">Debrief</button></div>
        </section>
      </div>
      <p class="cb-caption" id="cbCap" aria-live="polite"><b>CAPCOM ▸</b> <span id="cbCapTxt">Standing by.</span></p>
    </section>
  </div>`;
  const q = s => root.querySelector(s);

  // ---- window view switcher + breadcrumb (always a way back up to orbit) ----
  function setView(v, quiet) {
    view = v; root.querySelectorAll(".cb-view").forEach(b => b.setAttribute("aria-pressed", b.dataset.view === v));
    const site = st && st.site ? st.site.name.split(" (")[0] : "Outpost";
    const trail = [["orbit", "Moon"], ["site", "South pole · " + site], ...(v === "rover" ? [["rover", "Rover route"]] : v === "earth" ? [["earth", "Earth from the site"]] : [])]
      .slice(0, v === "orbit" ? 1 : 3);
    q("#cbCrumbs").innerHTML = trail.map(([id, n], i) => `<li>${i < trail.length - 1 ? `<button type="button" data-crumb="${id}">${esc(n)}</button>` : `<span aria-current="page">${esc(n)}</span>`}</li>`).join("");
    q("#cbCrumbs").querySelectorAll("[data-crumb]").forEach(b => b.onclick = () => setView(b.dataset.crumb));
    if (!quiet) cb.onView(v);
  }
  root.querySelectorAll(".cb-view").forEach(b => b.onclick = () => setView(b.dataset.view));
  // ---- softkeys: page switching (left) and page actions (right) ----
  root.querySelectorAll(".cb-sk").forEach(b => b.onclick = () => { pages[+b.dataset.du] = b.dataset.page; paintDus(); });
  // ---- levers + guards ----
  root.querySelectorAll(".cb-guard").forEach(g => g.onclick = () => { const id = g.dataset.guard; guards[id] = !guards[id]; paintLevers(); });
  root.querySelectorAll(".cb-lever").forEach(b => b.onclick = () => {
    const id = b.dataset.lv, L = LEVERS.find(l => l[0] === id); if (!st) return;
    if (L[2] && !guards[id]) { const g = q(`[data-guard="${id}"]`); g.classList.remove("is-nudge"); void g.offsetWidth; g.classList.add("is-nudge"); return; }
    cb.onCommand(L[4](!L[3](st))); if (L[2]) { guards[id] = false; }
  });
  // ---- shield knob ----
  const shield = d => st && cb.onCommand({ type: "allocate", to: "shields", amount: { kind: "percent", value: clamp(Math.round(((st.loads.shields || 0) + d) / 10) * 10, 0, 60) }, from: null });
  q("#cbShMinus").onclick = () => shield(-10); q("#cbShPlus").onclick = () => shield(10);
  q("#cbKnob").addEventListener("keydown", e => { const d = { ArrowUp: 10, ArrowRight: 10, ArrowDown: -10, ArrowLeft: -10 }[e.key]; if (d) { e.preventDefault(); e.stopPropagation(); shield(d); } });
  q("#cbKnob").addEventListener("click", e => { const r = e.currentTarget.getBoundingClientRect(); shield(e.clientX > r.left + r.width / 2 ? 10 : -10); });
  // ---- master alarm, PTT, end shift ----
  q("#cbMaster").onclick = () => { masterOn = false; paintMaster(); };
  q("#cbPtt").onclick = () => cb.onHouston();
  q("#cbEnd").onclick = () => cb.onEndShift();
  q("#cbDb").onclick = () => cb.onDebrief();

  function paintMaster() {
    const m = q("#cbMaster"); m.classList.toggle("is-lit", masterOn); m.setAttribute("aria-label", `Master alarm: ${masterOn ? "on. Press to reset" : "off"}`);
    q(".cb-glass").classList.toggle("is-alarm", masterOn);   // the cabin goes to red light until the alarm is reset
    root.querySelector(".cb").classList.toggle("is-alarm", masterOn);
  }

  // ---- the bulkhead round the window: anodised plate with a hole, a gasket + bolted frame ring, Dzus fasteners.
  // Drawn as SVG to the window's size (the hole must let the globe canvas behind show through in ORBIT).
  const winEl = q(".cb-window"), glassEl = q(".cb-glass");
  function rr(x, y, w, h, r) { return `M${x + r},${y}H${x + w - r}A${r},${r} 0 0 1 ${x + w},${y + r}V${y + h - r}A${r},${r} 0 0 1 ${x + w - r},${y + h}H${x + r}A${r},${r} 0 0 1 ${x},${y + h - r}V${y + r}A${r},${r} 0 0 1 ${x + r},${y}Z`; }
  function drawBulk() {
    const W = winEl.clientWidth, H = winEl.clientHeight; if (!W || !H) return;
    const wr = winEl.getBoundingClientRect(), g = glassEl.getBoundingClientRect();
    const x = g.left - wr.left, y = g.top - wr.top, w = g.width, h = g.height, r = parseFloat(getComputedStyle(glassEl).borderTopLeftRadius) || 40;
    const bolts = [], P = 2 * (w + h) + 40, n = Math.max(12, Math.round(P / 74));
    // bolts on the frame ring, 22px outside the glass
    const bx = x - 22, by = y - 22, bw = w + 44, bh = h + 44;
    for (let i = 0; i < n; i++) {
      let t = i / n * (2 * (bw + bh)), px, py;
      if (t < bw) { px = bx + t; py = by; } else if ((t -= bw) < bh) { px = bx + bw; py = by + t; } else if ((t -= bh) < bw) { px = bx + bw - t; py = by + bh; } else { t -= bw; px = bx; py = by + bh - t; }
      if (py > H - 4 || px < 6 || px > W - 6 || py < 4) continue;
      const k = 22, cx = Math.max(bx + k, Math.min(bx + bw - k, px)), cy = Math.max(by + k, Math.min(by + bh - k, py));
      bolts.push(`<use href="#cbBolt" x="${cx.toFixed(1)}" y="${cy.toFixed(1)}"/>`);
    }
    const dz = [[14, 14], [W - 14, 14], [14, H - 14], [W - 14, H - 14]].filter(([, yy]) => yy < y + h).map(([a, b]) => `<use href="#cbDzus" x="${a}" y="${b}"/>`);
    q("#cbBulk").setAttribute("viewBox", `0 0 ${W} ${H}`);
    q("#cbBulk").innerHTML = `<defs>
      <linearGradient id="cbBhG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--bh-hi)"/><stop offset="1" style="stop-color:var(--bh-lo)"/></linearGradient>
      <linearGradient id="cbRingG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--ring-hi)"/><stop offset=".5" style="stop-color:var(--ring-mid)"/><stop offset="1" style="stop-color:var(--ring-lo)"/></linearGradient>
      <radialGradient id="cbBoltG" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#f2f4f5"/><stop offset=".45" stop-color="#9aa0a6"/><stop offset="1" stop-color="#3c4045"/></radialGradient>
      <filter id="cbGrain" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/>
        <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .55 -.22"/></filter>
      <filter id="cbBrush" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency=".004 .6" numOctaves="1" seed="3"/>
        <feColorMatrix values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .5 -.2"/></filter>
      <clipPath id="cbHole"><path clip-rule="evenodd" d="M0,0H${W}V${H}H0Z${rr(x - 1, y - 1, w + 2, h + 2, r + 1)}"/></clipPath>
      <g id="cbBolt"><circle r="5.2" fill="#15171a" opacity=".55" cx=".8" cy="1.2"/><circle r="4.6" fill="url(#cbBoltG)"/><path d="M-2.6,0L-1.3,-2.25H1.3L2.6,0L1.3,2.25H-1.3Z" fill="none" stroke="#2a2d31" stroke-width=".9" opacity=".8"/></g>
      <g id="cbDzus"><circle r="7.5" fill="#101214" opacity=".5" cx=".8" cy="1.2"/><circle r="7" fill="url(#cbBoltG)"/><circle r="5.2" fill="none" stroke="#4a4f55" stroke-width=".8"/><rect x="-4.6" y="-.9" width="9.2" height="1.8" rx=".6" fill="#1d2023" transform="rotate(35)"/></g>
    </defs>
    <g clip-path="url(#cbHole)">
      <rect width="${W}" height="${H}" fill="url(#cbBhG)"/>
      <rect width="${W}" height="${H}" filter="url(#cbBrush)" class="cb-tex"/>
      <rect width="${W}" height="${H}" filter="url(#cbGrain)" class="cb-tex" opacity=".5"/>
      <path d="${rr(x - 32, y - 32, w + 64, h + 64, r + 32)}" fill="none" stroke="rgba(0,0,0,.4)" stroke-width="3" transform="translate(0 2.5)"/>
      <path d="${rr(x - 22, y - 22, w + 44, h + 44, r + 22)}" fill="none" stroke="url(#cbRingG)" stroke-width="19"/>
      <path d="${rr(x - 32, y - 32, w + 64, h + 64, r + 32)}" fill="none" style="stroke:var(--ring-edge)" stroke-width="1.2"/>
      <path d="${rr(x - 8, y - 8, w + 16, h + 16, r + 8)}" fill="none" stroke="#0c0d0f" stroke-width="16"/>
      <path d="${rr(x - 13, y - 13, w + 26, h + 26, r + 13)}" fill="none" stroke="rgba(255,255,255,.14)" stroke-width="1"/>
      ${bolts.join("")}${dz.join("")}
    </g>`;
  }
  new ResizeObserver(() => drawBulk()).observe(winEl);
  requestAnimationFrame(drawBulk);
  // Parallax: the window well has depth, so its inner edge slides a few pixels against the view as the head moves.
  const reduceMo = () => document.documentElement.dataset.motion === "reduce" || (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  root.addEventListener("pointermove", e => { if (reduceMo()) return; const r = winEl.getBoundingClientRect();
    glassEl.style.setProperty("--px", (((e.clientX - r.left) / r.width - .5) * -10).toFixed(1) + "px");
    glassEl.style.setProperty("--py", (((e.clientY - r.top) / r.height - .5) * -6).toFixed(1) + "px"); });
  root.addEventListener("pointerleave", () => { glassEl.style.setProperty("--px", "0px"); glassEl.style.setProperty("--py", "0px"); });

  const bar = (v, max = 100, red = null) => `<span class="du-bar${red != null && v / max >= red ? " is-red" : ""}"><i style="width:${clamp(v / max * 100)}%"></i>${red != null ? `<em style="left:${red * 100}%"></em>` : ""}</span>`;
  const row = (k, v, cls = "") => `<div class="du-row ${cls}"><span>${k}</span><b>${v}</b></div>`;
  function page(p, d) {
    const s = st; if (!s) return "";
    const r = s.resources, e = s.env, L = s.loads, lim = r.dose_limit_msv || 50, pr = prev && prev.resources;
    const tr = (a, b) => b == null ? "" : a > b + .4 ? " ▲" : a < b - .4 ? " ▼" : " —";
    if (p === "PWR") return `<header><span>DU${d + 1} · POWER</span><span>${Math.round(r.power_pct)} %${tr(r.power_pct, pr && pr.power_pct)}</span></header>
      ${bar(r.power_pct)}${row("SOLAR IN", e.in_sun ? `SUN ${(+e.sun_elev_deg) >= 0 ? "+" : ""}${(+e.sun_elev_deg).toFixed(1)}°` : "NONE · NIGHT")}
      <div class="du-loads">${LOADS.map(([k, n], i) => `<div class="du-load${i === sel ? " is-sel" : ""}" data-k="${k}"><span>${n.toUpperCase()}</span><i style="width:${clamp(L[k])}%"></i><b>${Math.round(L[k] || 0)}</b></div>`).join("")}</div>`;
    if (p === "LIFE") return `<header><span>DU${d + 1} · LIFE</span><span>${Math.round(r.life_support_pct)} %${tr(r.life_support_pct, pr && pr.life_support_pct)}</span></header>
      ${row("O2 / H2O", Math.round(r.life_support_pct) + " %")}${bar(r.life_support_pct)}
      ${row("AIR LOAD", Math.round(L.life_support) + " %")}${row("GREENHOUSE", Math.round(L.greenhouse) + " %")}${row("HEATERS", Math.round(L.heaters) + " %")}
      ${row("ROVER", s.rover && s.rover.busy ? `${TASK[s.rover.task] || "OUT"} · ${s.rover.eta_h} H` : "PARKED")}`;
    if (p === "RAD") return `<header><span>DU${d + 1} · RADIATION</span><span>${(+r.dose_msv).toFixed(1)} / ${lim} mSv</span></header>
      ${bar(r.dose_msv, lim, .8)}${row("RATE", `+${(+r.dose_rate_msv_h || 0).toFixed(2)} mSv/H`, (r.dose_rate_msv_h || 0) > .1 ? "is-warn" : "")}
      ${row("STORM", e.storm && e.storm.active ? `ACTIVE · SEV ${e.storm.severity || "?"}` : "NONE", e.storm && e.storm.active ? "is-warn" : "")}
      ${row("SHIELDS", Math.round(L.shields) + " %")}${row("SHELTER", s.shelter ? "CREW INSIDE" : "OPEN")}`;
    return `<header><span>DU${d + 1} · COMM</span><span>${e.earth_visible ? "EARTH IN VIEW" : "NO EARTH"}</span></header>
      ${row(e.earth_visible ? "DELAY" : "NEXT WINDOW", e.earth_visible ? `${((e.comm_delay_s || 2.6) / 2).toFixed(1)} S EACH WAY` : `${e.next_comm_window_h ?? "?"} H`)}
      <ol class="du-log">${logLines.slice(-4).map(l => `<li><b>${esc(l.who === "kid" ? callSign.shown().toUpperCase() : l.who === "houston" ? "HOUSTON" : "CAPCOM")} ▸</b> ${esc(l.text)}</li>`).join("") || "<li>RADIO QUIET</li>"}</ol>`;
  }
  function paintDus() {
    [0, 1, 2].forEach(d => {
      q("#cbDu" + d).innerHTML = page(pages[d], d);
      root.querySelectorAll(`.cb-sk[data-du="${d}"]`).forEach(b => b.setAttribute("aria-pressed", b.dataset.page === pages[d]));
      const rk = q("#cbRk" + d);
      if (pages[d] === "PWR") {
        rk.innerHTML = `<button type="button" class="cb-sk" data-a="up" aria-label="Select the load above">SEL▲</button><button type="button" class="cb-sk" data-a="dn" aria-label="Select the load below">SEL▼</button>
          <button type="button" class="cb-sk" data-a="plus" aria-label="More power to ${LOADS[sel][1]}">+5</button><button type="button" class="cb-sk" data-a="minus" aria-label="Less power to ${LOADS[sel][1]}">−5</button>`;
        rk.querySelectorAll("[data-a]").forEach(b => b.onclick = () => {
          const a = b.dataset.a;
          if (a === "up" || a === "dn") { sel = (sel + (a === "up" ? LOADS.length - 1 : 1)) % LOADS.length; paintDus(); return; }
          cb.onCommand({ type: "allocate", to: LOADS[sel][0], amount: { kind: "delta", value: a === "plus" ? 5 : -5 }, from: null });
        });
      } else rk.innerHTML = "";
    });
  }
  function paintLevers() {
    if (!st) return;
    LEVERS.forEach(([id, label, guarded, on]) => {
      const box = q(`.cb-lv[data-lv="${id}"]`), b = box.querySelector(".cb-lever"), v = on(st);
      b.setAttribute("aria-pressed", v);
      const locked = guarded && !guards[id];
      b.setAttribute("aria-label", `${label}: ${v ? "on" : "off"}${locked ? ". Guard closed" : ""}`);
      box.querySelector(".cb-tb").classList.toggle("is-on", !!v);   // talkback flag: grey = on, barber pole = off
      box.querySelector(".cb-lvst").textContent = id === "recall" ? (st.rover && st.rover.busy ? (v ? "RETURNING" : "ROVER OUT") : "PARKED") : v ? "ON" : "OFF";
      if (guarded) { const g = box.querySelector(".cb-guard"); g.setAttribute("aria-pressed", guards[id]); g.classList.toggle("is-open", guards[id]);
        g.setAttribute("aria-label", `${label} guard: ${guards[id] ? "lifted. Close the guard" : "closed. Lift the guard first"}`); }
      if (id === "recall") b.disabled = !(st.rover && st.rover.busy) || v;
    });
  }
  function moved(sel_) { const el = q(sel_); if (!el) return; el.classList.remove("is-moved"); void el.offsetWidth; el.classList.add("is-moved"); }

  function update(s) {
    if (!s) return; prev = st; st = s;
    const r = s.resources, e = s.env || {};
    // window
    if (!prev) setView(view, true);
    sky(+e.sun_elev_deg || 0, e.earth_elev_deg, !!e.earth_visible);
    const storm = e.storm && e.storm.active, sb = q("#cbStorm");
    sb.hidden = !storm; if (storm) sb.innerHTML = `<i aria-hidden="true"></i>SOLAR STORM · ${esc(e.storm.real_date ? "REAL EVENT " + e.storm.real_date : e.storm.name || "")} · SOURCE NASA ${esc(e.storm.source || "DONKI")}`;
    const rv = s.rover || {}, ro = q("#cbRover");
    ro.hidden = !rv.busy;
    if (rv.busy) { const tot = { collect_ice: 10, explore: 8, repair_array: 5, return: 5 }[rv.task] || 8, p = 1 - (rv.eta_h || 0) / tot, f = rv.task === "return" ? 1 - p : p < .5 ? p * 2 : (1 - p) * 2;
      void f; q("#cbRoverTxt").textContent = `ROVER · ${TASK[rv.task] || "OUT"} · BACK IN ${rv.eta_h} H`; }
    q("#cbClock").innerHTML = `<b>DAY ${s.day} · SHIFT ${s.shift}</b><span>MET ${String(Math.floor((s.mission_time_h || 0))).padStart(3, "0")}:00 · ★ ${s.score || 0}</span>`;
    // panel
    paintDus(); paintLevers();
    const sh = Math.round(s.loads.shields || 0), kn = q("#cbKnob");
    kn.style.setProperty("--a", (-135 + clamp(sh, 0, 60) / 60 * 270) + "deg"); kn.setAttribute("aria-valuenow", sh); kn.setAttribute("aria-valuetext", sh + " percent");
    q("#cbShVal").textContent = sh + "%";
    if (prev) {
      if (Math.round(prev.loads.shields || 0) !== sh) moved(".cb-knobwrap");
      LEVERS.forEach(([id, , , on]) => { if (on(prev) !== on(s)) moved(`.cb-lv[data-lv="${id}"]`); });
      LOADS.forEach(([k]) => { if (Math.round(prev.loads[k] || 0) !== Math.round(s.loads[k] || 0)) root.querySelectorAll(`.du-load[data-k="${k}"]`).forEach(x => x.classList.add("is-moved")); });
    }
    const lit = new Set();
    LAMPS.forEach(([id, , lvl, f]) => { let on = false; try { on = f(s); } catch (x) { /* partial */ }
      const el = q("#cbl-" + id); el.classList.toggle("is-lit", on); el.querySelector(".cb-vh").textContent = on ? ": lit" : ": off";
      if (on) { lit.add(id); if (lvl !== "info" && !litBefore.has(id) && prev) masterOn = true; } });
    litBefore = lit; paintMaster();
    q(".cb-glass").classList.toggle("is-storm", !!storm);
    q("#cbPttSub").textContent = e.earth_visible ? "EARTH IN VIEW" : `NO SIGNAL · WINDOW IN ${e.next_comm_window_h ?? "?"} H`;
    q("#cbPtt").classList.toggle("is-nosignal", !e.earth_visible);
    q("#cbEndSub").textContent = s.over ? "MISSION OVER" : `SHIFT ${s.shift}/4 · DAY ${s.day}/10`;
  }
  function sky(sunDeg, earthDeg, up) {
    q("#cbRead").innerHTML = `SUN EL ${sunDeg >= 0 ? "+" : ""}${(+sunDeg).toFixed(1)}°<br>EARTH EL ${earthDeg == null ? (up ? "UP" : "BELOW") : `${earthDeg >= 0 ? "+" : ""}${(+earthDeg).toFixed(1)}°${up ? "" : " (BELOW)"}`}<br>${esc(((st && st.site && st.site.name) || "").toUpperCase())}`;
  }
  function telemetry(f) { if (!st) return; if (f.sun_elev_deg != null) sky(f.sun_elev_deg, f.earth_elev_deg, f.comm ? f.comm === "open" : st.env.earth_visible); }
  /** Radio log (COMM page) + caption strip, word by word. */
  function log(who, text) {
    if (!text) return;
    const last = logLines[logLines.length - 1]; if (last && last.text === text) return;
    logLines.push({ who, text }); logLines = logLines.slice(-12);
    if (pages.includes("COMM")) paintDus();
    const name = who === "kid" ? callSign.shown().toUpperCase() : who === "houston" ? "HOUSTON" : "CAPCOM";
    q("#cbCap b").textContent = name + " ▸";
    const words = String(text).split(/\s+/), el = q("#cbCapTxt");
    el.innerHTML = words.map((w, i) => `<span data-i="${i}">${esc(w)}</span>`).join(" ");
    clearInterval(capT); let i = 0;
    const reduce = matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || who === "kid") return;
    capT = setInterval(() => { el.querySelectorAll(".is-now").forEach(x => x.classList.remove("is-now")); const w = el.querySelector(`[data-i="${i++}"]`); if (w) w.classList.add("is-now"); else clearInterval(capT); }, 330);
  }
  function calling(on) { const b = q("#cbPtt"); b.classList.toggle("is-calling", !!on); b.disabled = !!on; }
  function busy(on) { q("#cbEnd").disabled = !!on; }
  return { update, telemetry, log, calling, busy, setView, get view() { return view; }, get state() { return st; } };
}
