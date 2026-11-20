// Archaeology steps (docs/COURSES.md §3.2): layers (the dig), rings (tree-ring match), hillshade (read the land from
// above) and decide (an ethics call). Grading is server-side (backend/app/academy/arch_steps.py); these draw the step
// and send {text} / {choice} / {tap: {x, y}}. Every step works three ways:
//   voice     the Academy sends the student's words ("oldest first: sandstone, floor...", "twelve seventy-five")
//   keys      every control is a button (Tab / arrows / Enter, numbers for options); the ring slider is a role=slider
//             (Left / Right slide it, Enter locks it in); the hillshade takes arrows to move a crosshair and Enter to tap
//   taps      chips, buttons, the image itself
// No inline scripts or handlers (the app's CSP): everything is bound in bind(el).
//
// Registered on window.__outpost.stepRenderers[type] as a factory
//   ({step, acc, answer, esc, state, locked, guide}) -> {html, bind(el)}
// `state` is the step's per-step state in academy/ui.js (the server's `got` for the build-up steps; the slider
// position; a decide step's law card); `guide` is the hint-ladder state (focus / answer ids to glow).
import { icon } from "../assets/icons.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };
O.stepRenderers = O.stepRenderers || {};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const gotOf = ctx => (ctx.state && Array.isArray(ctx.state.got) ? ctx.state.got : []);
const src = s => s && s.url ? `<a class="chip-src" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : "";

/** The archaeology step types that build up over turns (the reply's `got` goes back with the next answer). */
export const ARCH_BUILDUP_TYPES = ["layers", "hillshade"];
export const ARCH_STEP_TYPES = ["layers", "rings", "hillshade", "decide"];

// ---------------------------------------------------------------------------------------------------- layers ----
/** Earth tones for the trench (fills), by layer `tone` or position. Muted, so the labels stay readable. */
const TONES = { soil: "#6b5137", rubble: "#8a7563", ash: "#4a4a50", floor: "#a8865a", rock: "#c19a6b", fill: "#3d2f24" };
const ORDER_TONES = ["soil", "rubble", "ash", "floor", "rock", "rock"];

/** The trench drawing's geometry: [{id, label, letter, y, h, fill}] top to bottom, plus the pit polygon. Pure (tested). */
export function trenchLayout(acc, { width = 320, height = 168 } = {}) {
  const ls = acc.layers || [];
  const total = ls.reduce((s, l) => s + (+l.h || 1), 0) || 1;
  let y = 0;
  const rows = ls.map((l, k) => {
    const h = ((+l.h || 1) / total) * height;
    const r = { id: l.id, label: l.label, finds: l.finds || "", letter: "ABCDEF"[k], y, h, fill: TONES[l.tone] || TONES[ORDER_TONES[k]] || TONES.soil };
    y += h;
    return r;
  });
  let pit = null;
  if (acc.pit) {
    const a = rows.find(r => r.id === acc.pit.from), b = rows.find(r => r.id === acc.pit.to);
    if (a && b) {
      const top = a.y + a.h, bottom = b.y + b.h * 0.6, x0 = width * 0.7, x1 = width * 0.9;
      pit = { id: acc.pit.id, label: acc.pit.label, top, bottom, x0, x1,
        d: `M${x0.toFixed(1)} ${top.toFixed(1)} L${(x0 + 8).toFixed(1)} ${bottom.toFixed(1)} Q${((x0 + x1) / 2).toFixed(1)} ${(bottom + 10).toFixed(1)} ${(x1 - 8).toFixed(1)} ${bottom.toFixed(1)} L${x1.toFixed(1)} ${top.toFixed(1)} Z` };
    }
  }
  return { rows, pit, width, height };
}

function trenchSvg(acc) {
  const { rows, pit, width, height } = trenchLayout(acc);
  const lab = (x, y, t, cls = "") => `<text x="${x}" y="${y.toFixed(1)}" class="ar-t ${cls}">${esc(t)}</text>`;
  return `<svg class="ar-trench" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(`Trench wall, top to bottom: ${rows.map(r => `${r.letter} ${r.label}`).join(", ")}${pit ? `. A ${pit.label.toLowerCase()} cuts down from below ${rows.find(r => r.id === acc.pit.from).label.toLowerCase()} into ${rows.find(r => r.id === acc.pit.to).label.toLowerCase()}` : ""}.`)}">
    ${rows.map(r => `<rect x="0" y="${r.y.toFixed(1)}" width="${width}" height="${r.h.toFixed(1)}" fill="${r.fill}"/>
      <line x1="0" x2="${width}" y1="${r.y.toFixed(1)}" y2="${r.y.toFixed(1)}" class="ar-edge"/>
      ${lab(8, r.y + r.h / 2 + 4, `${r.letter}  ${r.label}`)}${r.finds ? lab(118, r.y + r.h / 2 + 4, `◆ ${r.finds}`, "ar-find") : ""}`).join("")}
    ${pit ? `<path d="${pit.d}" fill="${TONES.fill}" class="ar-pit"/>${lab(pit.x0 + 10, pit.top + (pit.bottom - pit.top) / 2 + 4, pit.label, "ar-pit-t")}` : ""}
  </svg>`;
}

/** The chips in a fixed jumbled order (by label), the pit among them: the order is the answer. Pure (tested). */
export const layerChips = acc => [...(acc.layers || []), ...(acc.pit ? [acc.pit] : [])]
  .map(l => ({ id: l.id, label: l.label })).sort((a, b) => a.label.localeCompare(b.label));

O.stepRenderers.layers = ctx => {
  const got = gotOf(ctx), chips = layerChips(ctx.acc), byId = Object.fromEntries(chips.map(c => [c.id, c]));
  const g = ctx.guide || {};
  return {
    html: `<div class="ar-dig">
        ${trenchSvg(ctx.acc)}
        <p class="ar-cap">${esc("Oldest first")}</p>
        <ol class="f-seq ar-order" aria-label="Your order, oldest first">${chips.map((_, k) => {
          const it = byId[got[k]];
          return `<li class="${it ? "is-done" : k === got.length ? "is-now" : ""}"><span class="f-seq-n" aria-hidden="true">${k + 1}</span>${it ? esc(it.label) : `<span class="sr-only">empty</span>`}</li>`;
        }).join("")}</ol>
        <div class="a-choices f-seq-chips" role="group" aria-label="Layers">${chips.map(c =>
          `<button type="button" class="a-choice f-chip${g.answer === c.id ? " is-cue" : ""}" data-c="${esc(c.id)}"${got.includes(c.id) ? " disabled" : ""}>${esc(c.label)}</button>`).join("")}</div>
      </div>`,
    bind: el => {
      if (!el || !el.querySelectorAll) return;
      el.querySelectorAll(".f-chip").forEach(b => (b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)));
    },
  };
};

// ----------------------------------------------------------------------------------------------------- rings ----
/** Where the beam sits: its outer (bark) year, clamped so the whole beam stays on the master strip. Pure (tested). */
export function clampOuter(acc, outer) {
  const m = acc.master || {}, n = (acc.beam && acc.beam.n) || 0;
  const lo = (m.from || 0) + n - 1, hi = m.to || 0;
  return Math.max(lo, Math.min(hi, Math.round(outer)));
}
/** Bars for one strip: [{x, h, year?}] at a fixed step per year (a skeleton-plot-like bar chart of ring width). */
export function bars(ws, { x0 = 0, step = 6, max = 2.2, height = 56 } = {}) {
  return (ws || []).map((w, k) => ({ x: x0 + k * step, h: Math.max(2, Math.min(1, (+w || 0) / max) * height) }));
}
const RING_STEP = 5.2;
function ringsSvg(acc, outer) {
  const m = acc.master || { from: 0, to: 0, w: [] }, n = acc.beam.n, step = RING_STEP, pad = 34;
  const W = pad * 2 + (m.to - m.from + 1) * step, H = 228, top = 78, bot = 186;
  const mb = bars(m.w, { x0: pad, step });
  const start = outer - n + 1, bx = pad + (start - m.from) * step;
  const bb = bars(acc.beam.w, { x0: bx, step });
  const ticks = [];
  for (let y = Math.ceil(m.from / 10) * 10; y <= m.to; y += 10) ticks.push(y);
  return `<svg class="ar-rings" viewBox="0 0 ${W.toFixed(0)} ${H}" role="img" aria-label="${esc(`Master tree-ring pattern ${m.from} to ${m.to}, and the beam's ${n} rings below it, outer ring at ${outer}.`)}">
    <text x="${pad}" y="16" class="ar-t ar-small">Master pattern: Mesa Verde Douglas-fir</text>
    ${mb.map(b => `<rect x="${b.x.toFixed(1)}" y="${(top - b.h).toFixed(1)}" width="${(step - 1.4).toFixed(1)}" height="${b.h.toFixed(1)}" class="ar-bar"/>`).join("")}
    ${ticks.map(y => `<line x1="${(pad + (y - m.from) * step + step / 2).toFixed(1)}" x2="${(pad + (y - m.from) * step + step / 2).toFixed(1)}" y1="${top + 2}" y2="${top + 8}" class="ar-tick"/><text x="${(pad + (y - m.from) * step + step / 2).toFixed(1)}" y="${top + 24}" class="ar-t ar-small ar-mid">${y}</text>`).join("")}
    <rect x="${(bx - 2).toFixed(1)}" y="${bot - 60}" width="${(n * step + 2).toFixed(1)}" height="64" rx="4" class="ar-beam-bg"/>
    ${bb.map(b => `<rect x="${b.x.toFixed(1)}" y="${(bot - b.h).toFixed(1)}" width="${(step - 1.4).toFixed(1)}" height="${b.h.toFixed(1)}" class="ar-bar ar-bar-beam"/>`).join("")}
    <line x1="${(bx + n * step - 0.7).toFixed(1)}" x2="${(bx + n * step - 0.7).toFixed(1)}" y1="${top - 56}" y2="${bot + 6}" class="ar-outer"/>
    <text x="${(bx + n * step).toFixed(1)}" y="${bot + 22}" class="ar-t ar-small ar-end">bark edge ${outer}</text>
    <text x="${pad}" y="${bot - 66}" class="ar-t ar-small">Undated beam · taller bar = wider ring (wetter year)</text>
  </svg>`;
}

O.stepRenderers.rings = ctx => {
  const acc = ctx.acc, st = ctx.state || {};
  if (st.outer == null) st.outer = clampOuter(acc, acc.start != null ? acc.start : acc.master.to);
  const outer = clampOuter(acc, st.outer);
  return {
    html: `<div class="ar-ringbox">
        <div class="ar-slider" role="slider" tabindex="0" aria-label="Beam position: its outer ring year. Left and Right slide it, Enter locks it in"
          aria-valuemin="${clampOuter(acc, -1e9)}" aria-valuemax="${clampOuter(acc, 1e9)}" aria-valuenow="${outer}" aria-valuetext="Outer ring ${outer}">${ringsSvg(acc, outer)}</div>
        <div class="ar-ring-row" role="group" aria-label="Slide the beam">
          <button type="button" class="a-choice ar-move" data-move="-5" aria-label="5 years earlier">${icon("chevron-left", { size: 16 })}${icon("chevron-left", { size: 16 })}</button>
          <button type="button" class="a-choice ar-move" data-move="-1" aria-label="1 year earlier">${icon("chevron-left", { size: 16 })}Earlier</button>
          <span class="ar-year" aria-live="polite">Outer ring: <b>${outer}</b></span>
          <button type="button" class="a-choice ar-move" data-move="1" aria-label="1 year later">Later${icon("chevron-right", { size: 16 })}</button>
          <button type="button" class="a-choice ar-move" data-move="5" aria-label="5 years later">${icon("chevron-right", { size: 16 })}${icon("chevron-right", { size: 16 })}</button>
        </div>
        <button type="button" class="btn-primary ar-lock" data-c="${outer}">Lock in ${outer}</button>
        ${acc.source ? `<p class="ar-src">${icon("info", { size: 14 })}<span>Real data: ${src(acc.source)}</span></p>` : ""}
      </div>`,
    bind: el => {
      if (!el || !el.querySelector) return;
      const box = el.querySelector(".ar-ringbox"); if (!box) return;
      const set = v => {
        st.outer = clampOuter(acc, v);
        const sl = box.querySelector(".ar-slider");
        sl.innerHTML = ringsSvg(acc, st.outer);
        sl.setAttribute("aria-valuenow", st.outer); sl.setAttribute("aria-valuetext", `Outer ring ${st.outer}`);
        box.querySelector(".ar-year b").textContent = st.outer;
        const lk = box.querySelector(".ar-lock"); lk.dataset.c = st.outer; lk.textContent = `Lock in ${st.outer}`;
      };
      box.querySelectorAll(".ar-move").forEach(b => (b.onclick = () => set(st.outer + +b.dataset.move)));
      const lock = box.querySelector(".ar-lock");
      lock.onclick = () => ctx.answer({ choice: String(st.outer) }, lock);
      const sl = box.querySelector(".ar-slider");
      sl.onkeydown = e => {
        const d = { ArrowLeft: -1, ArrowRight: 1, PageDown: -5, PageUp: 5 }[e.key];
        if (d) { e.preventDefault(); set(st.outer + (e.shiftKey ? d * 5 : d)); return; }
        if (e.key === "Home" || e.key === "End") { e.preventDefault(); set(e.key === "Home" ? -1e9 : 1e9); return; }
        if (e.key === "Enter") { e.preventDefault(); ctx.answer({ choice: String(st.outer) }, lock); }
      };
      // drag: one ring per RING_STEP px of the drawing
      let drag = null;
      sl.onpointerdown = e => { drag = { x: e.clientX, o: st.outer, w: sl.getBoundingClientRect().width }; try { sl.setPointerCapture(e.pointerId); } catch (_) { /* old browsers */ } };
      sl.onpointermove = e => {
        if (!drag) return;
        const svg = sl.querySelector("svg"), vb = svg && svg.viewBox && svg.viewBox.baseVal ? svg.viewBox.baseVal.width : drag.w;
        const years = Math.round(((e.clientX - drag.x) * (vb / drag.w)) / RING_STEP);
        if (drag.o + years !== st.outer) set(drag.o + years);
      };
      sl.onpointerup = sl.onpointercancel = () => { drag = null; };
    },
  };
};

// ------------------------------------------------------------------------------------------------- hillshade ----
/** A tap's position as image fractions (0..1), from a click in the image's box. Pure (tested). */
export function tapFraction(rect, clientX, clientY) {
  const x = (clientX - rect.left) / (rect.width || 1), y = (clientY - rect.top) / (rect.height || 1);
  return { x: Math.round(Math.max(0, Math.min(1, x)) * 1000) / 1000, y: Math.round(Math.max(0, Math.min(1, y)) * 1000) / 1000 };
}
/** Move the keyboard crosshair; null when the move would leave the image (the arrow then leaves the step). */
export function moveCross(p, key, stepSize = 0.025) {
  const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[key];
  if (!d) return null;
  const x = p.x + d[0] * stepSize, y = p.y + d[1] * stepSize;
  if (x < 0 || x > 1 || y < 0 || y > 1) return null;
  return { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 };
}

O.stepRenderers.hillshade = ctx => {
  const acc = ctx.acc, im = acc.image || {}, st = ctx.state || {}, got = gotOf(ctx), g = ctx.guide || {};
  if (!st.sun) st.sun = "low";
  if (!st.cross) st.cross = { x: 0.5, y: 0.5 };
  const url = st.sun === "high" && im.high_url ? im.high_url : im.low_url;
  const ts = acc.targets || [];
  const found = ts.filter(t => got.includes(t.id) || ctx.locked);
  const focus = ts.find(t => (g.focus || []).includes(t.id) || g.answer === t.id);
  const ring = (t, cls) => `<circle cx="${t.x * 100}" cy="${t.y * 100 * (im.h / im.w || 1)}" r="${Math.max(2.5, t.r * 100)}" class="${cls}"/>`;
  const asp = (im.h / im.w) || 0.7;
  const scale = im.width_m ? Math.round(im.width_m / 5 / 50) * 50 || 100 : 0;
  return {
    html: `<figure class="ar-hill">
        <div class="ar-hill-img" tabindex="0" role="application" aria-roledescription="lidar map"
          aria-label="${esc(`${im.alt || "Lidar hillshade"}. ${found.length} of ${acc.need} found. Arrows move the crosshair, Enter taps.`)}" style="aspect-ratio:${im.w || 4} / ${im.h || 3}">
          <img src="${esc(url)}" alt="" draggable="false">
          <svg viewBox="0 0 100 ${(100 * asp).toFixed(2)}" preserveAspectRatio="none" aria-hidden="true">
            ${found.map(t => ring(t, "ar-found")).join("")}
            ${focus && !got.includes(focus.id) && !ctx.locked ? ring(focus, "ar-glow") : ""}
            <g class="ar-cross" transform="translate(${(st.cross.x * 100).toFixed(2)} ${(st.cross.y * 100 * asp).toFixed(2)})"><line x1="-3" x2="3" y1="0" y2="0"/><line x1="0" x2="0" y1="-3" y2="3"/></g>
          </svg>
          ${found.map((t, k) => `<span class="ar-tag${k % 2 ? " is-below" : ""}" style="left:${(t.x * 100).toFixed(1)}%;top:${(t.y * 100).toFixed(1)}%">${esc(t.label)}</span>`).join("")}
          ${scale ? `<span class="ar-scale" style="width:${((scale / im.width_m) * 100).toFixed(1)}%">${scale} m</span>` : ""}
        </div>
        <figcaption class="ar-hill-cap">
          <span class="f-count" aria-live="polite">${Math.min(found.length, acc.need)} of ${acc.need} found</span>
          ${im.high_url ? `<button type="button" class="a-choice f-chip ar-sun" aria-pressed="${st.sun === "low"}">${icon("sun", { size: 16 })}${st.sun === "low" ? "Low sun" : "High sun"}</button>` : ""}
          <span class="ar-credit">${esc(im.credit || "")} ${src(im.source)}</span>
        </figcaption>
      </figure>`,
    bind: el => {
      if (!el || !el.querySelector) return;
      const box = el.querySelector(".ar-hill-img"); if (!box) return;
      const sun = el.querySelector(".ar-sun");
      const rerender = () => { const h = O.stepRenderers.hillshade(ctx); el.innerHTML = h.html; h.bind(el); };
      if (sun) sun.onclick = () => { st.sun = st.sun === "low" ? "high" : "low"; rerender(); const s = el.querySelector(".ar-sun"); if (s) s.focus(); };
      if (ctx.locked) return;
      box.onclick = e => { const p = tapFraction(box.getBoundingClientRect(), e.clientX, e.clientY); st.cross = p; ctx.answer({ tap: p }); };
      box.onkeydown = e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ctx.answer({ tap: { ...st.cross } }); return; }
        const p = moveCross(st.cross, e.key, e.shiftKey ? 0.08 : 0.025);
        if (!p) return;   // at the edge: the arrow leaves the map (spatial navigation)
        e.preventDefault(); st.cross = p;
        const c = box.querySelector(".ar-cross"); if (c) c.setAttribute("transform", `translate(${(p.x * 100).toFixed(2)} ${(p.y * 100 * asp).toFixed(2)})`);
      };
    },
  };
};

// ---------------------------------------------------------------------------------------------------- decide ----
O.stepRenderers.decide = ctx => {
  const law = ctx.locked && ctx.state && ctx.state.law;
  return {
    html: `<div class="a-choices g-opts ar-decide" role="group" aria-label="What you would do">${(ctx.acc.options || []).map((o, k) =>
        `<button type="button" class="a-choice" data-c="${esc(o.id)}"><span class="a-key" aria-hidden="true">${k + 1}</span><span>${esc(o.label)}</span></button>`).join("")}</div>
      ${law ? `<aside class="ar-law" aria-label="The law">${icon("library", { size: 16 })}<div><b>${esc(law.title)}</b><p>${esc(law.text)} ${src(law.source)}</p></div></aside>` : ""}`,
    bind: el => {
      if (!el || !el.querySelectorAll) return;
      el.querySelectorAll(".ar-decide .a-choice").forEach(b => (b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)));
    },
  };
};
