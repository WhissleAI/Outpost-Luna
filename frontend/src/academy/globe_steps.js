// Flight School globe steps (docs/LEARNING_DESIGN.md §3, contract §9.2). The Moon is the answer surface; the glass
// card stays small and some steps have no answer buttons at all. Grading is server-side (backend/app/academy/grade.py);
// these draw the step, move the globe, and send {choice} / {tap} / {taps} / {view} / {text}. Every step also works by
// voice alone: the Academy sends the kid's words.
//
// Registered on window.__outpost.stepRenderers[type] as a factory
//   ({step, acc, answer, say, playCrew, esc, captions, globe}) -> {html, bind(el), onTap?(p)}
// `onTap(p)` (p = {lat, lon}) is called by academy/ui.js for a tap on the Moon while this step is open.
// The step's `globe` directive ({do: fly|side|pole|sun|pair|earth|route, ...}) runs when the step opens.
// After the answer, academy/ui.js re-renders the same html locked, marks the guess / the answer / CAPCOM's shown
// answer, and draws `compare` data and the route (see `result` below).
import { icon } from "../assets/icons.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };
O.stepRenderers = O.stepRenderers || {};

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// The "do this" line under the question comes from academy/guide.js (DO, or the step's own `do`), drawn by ui.js.

/** Buttons for options, numbered so "option 2" works by voice and Tab/Enter by keyboard. */
export function optionsHtml(options, cls = "") {
  return `<div class="a-choices g-opts ${cls}" role="group" aria-label="Answers">${(options || []).map((o, k) =>
    `<button type="button" class="a-choice" data-c="${esc(o.id)}"><span class="a-key" aria-hidden="true">${k + 1}</span><span>${esc(o.label)}</span></button>`).join("")}</div>`;
}
function bindOptions(root, ctx) {
  root.querySelectorAll(".a-choice").forEach(b => (b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)));
}

/** Run a step's globe directive. Missing globe features are skipped (older globe.js), never an error. */
export function runDirective(globe, g) {
  if (!globe || !g) return;
  const call = (fn, ...a) => (typeof globe[fn] === "function" ? globe[fn](...a) : undefined);
  if (g.do !== "fly" && g.do !== "earth") call("clearHighlight");   // the lesson's place ring would distract
  switch (g.do) {
    case "pole": call("poleView", g.pole || "south", g.dist); break;
    case "side": call("flyTo", 0, g.lon != null ? g.lon : g.side === "far" ? 180 : 0, g.dist || 3.4); break;
    case "sun": call("setSunDir", 0, g.sun_lon); call("flyTo", 0, g.view_lon != null ? g.view_lon : 0, g.dist || 3.4); break;
    case "fly": case "earth": if (g.place && O.placeById) { const f = O.placeById(g.place); if (f) call("showFeature", f); } else if (g.lat != null) call("flyTo", g.lat, g.lon, g.dist); break;
    case "pair": case "route": call("poleView", "south", g.dist || 2.4); break;
    case "zoom": call("flyTo", g.lat || 0, g.lon || 0, 4.5); setTimeout(() => call("poleView", "south", 1.8), 1400); break;
    default: break;
  }
}
const withDirective = (ctx, extra) => ({
  ...extra,
  bind: root => { if (!ctx.locked) runDirective(ctx.globe, ctx.step.globe); if (extra.bind) extra.bind(root); },
});

/** Predict: guess first. Never wrong: any guess reveals the real number (the reply's say + the step's reveal source). */
O.stepRenderers.predict = ctx => withDirective(ctx, {
  html: `${optionsHtml(ctx.acc.options)}`,
  bind: root => bindOptions(root, ctx),
});

/** Can you see Earth from here: three compact answers in a row. */
O.stepRenderers.earth_view = ctx => withDirective(ctx, {
  html: `${optionsHtml(ctx.acc.options, "is-row")}`,
  bind: root => bindOptions(root, ctx),
});

/** Turn the Moon: drag the globe, or the two big side buttons; "Check this view" grades where the camera looks. */
O.stepRenderers.globe_side = ctx => withDirective(ctx, {
  html: `<div class="g-sides" role="group" aria-label="Sides">
      <button type="button" class="a-choice g-side" data-c="near"><span class="g-disc is-near" aria-hidden="true"></span><span>Near side</span></button>
      <button type="button" class="a-choice g-side" data-c="far"><span class="g-disc is-far" aria-hidden="true"></span><span>Far side</span></button>
    </div>
    <button type="button" class="btn-quiet g-view" data-view>${icon("check", { size: 16 })}Check this view</button>`,
  bind: root => {
    root.querySelectorAll(".a-choice").forEach(b => (b.onclick = () => {
      if (ctx.globe) ctx.globe.flyTo(0, b.dataset.c === "far" ? 180 : 0, 3.4);
      ctx.answer({ choice: b.dataset.c }, b);
    }));
    const v = root.querySelector("[data-view]");
    if (v) v.onclick = () => ctx.globe && ctx.answer({ view: ctx.globe.centerLatLon() }, v);
  },
});

/** Tap the terminator: no buttons; the Moon is lit from the step's Sun and the tap is the answer. */
O.stepRenderers.terminator = ctx => withDirective(ctx, {
  html: "",
  bind: () => { if (!ctx.locked && ctx.globe && ctx.globe.setSunDir) ctx.globe.setSunDir(0, ctx.acc.sun_lon); },
  onTap: p => ctx.answer({ tap: { lat: p.lat, lon: p.lon } }),
});

/** The mission sites (for pins on the Moon), fetched once. */
let sitesP = null;
const missionSites = () => (sitesP = sitesP || fetch("/api/mission/sites").then(r => r.json()).then(d => d.sites || []).catch(() => []));
/** Labelled pins for the two sites on the Moon (the globe's route layer); tapping one answers. */
function sitePins(ctx) {
  const g = ctx.globe; if (!g || !g.route || typeof document === "undefined") return;
  missionSites().then(all => {
    if (ctx.locked) return;
    const pins = (ctx.acc.options || []).map((o, k) => {
      const site = all.find(x => x.id === o.id); if (!site) return null;
      const el = document.createElement("button"); el.type = "button"; el.className = "g-sitepin";
      el.innerHTML = `<span class="g-sitedot" aria-hidden="true">${k + 1}</span><span>${esc(o.label)}</span>`;
      el.setAttribute("aria-label", `${k + 1}. ${o.label}`);
      el.onclick = () => ctx.answer({ choice: o.id }, el);
      return { id: o.id, lat: site.lat, lon: site.lon, el };
    }).filter(Boolean);
    g.route.set(pins, 0);
  });
}

/** Compare two sites: two pins on the Moon and two cards side by side; after the answer the cards carry the data. */
O.stepRenderers.compare = ctx => withDirective(ctx, {
  html: `<div class="g-pair" role="group" aria-label="Sites">${(ctx.acc.options || []).map((o, k) => `
      <button type="button" class="a-choice g-site" data-c="${esc(o.id)}" data-place="${esc(o.place || "")}">
        <span class="a-key" aria-hidden="true">${k + 1}</span><b>${esc(o.label)}</b><span class="g-data" data-for="${esc(o.place || o.id)}"></span></button>`).join("")}</div>`,
  bind: root => { bindOptions(root, ctx); sitePins(ctx); },
  onTap: p => ctx.answer({ tap: { lat: p.lat, lon: p.lon } }),
});

/** Trace a route: tap the stops in order. Each tap is graded as it lands (a right stop is "progress", not a miss),
 *  so the kid hears "Yes, Orientale. Now Ohm." The taps live in ctx.state (academy/ui.js), which survives re-renders. */
O.stepRenderers.route = ctx => {
  const S = ctx.state || { taps: [] }, taps = S.taps || (S.taps = []), n = (ctx.acc.stops || []).length;
  const nameOf = id => { const f = O.placeById && O.placeById(id); return f ? String(f.name).split(" (")[0].replace(/^Mare /, "") : id; };
  const stopLine = k => `Tap ${k + 1}: ${nameOf(ctx.acc.stops[k])}`;   // "Tap 1: Orientale", matching the numbered ring
  let root = null;
  const paint = () => {
    if (!root || !root.querySelector) return;
    const dots = root.querySelector("[data-progress]");
    if (dots) dots.innerHTML = Array.from({ length: n }, (_, k) => `<i class="${k < taps.length ? "is-done" : k === taps.length ? "is-now" : ""}"></i>`).join("");
    const label = root.querySelector("[data-label]");
    if (label) label.textContent = taps.length < n ? stopLine(taps.length) : "Checking your route";
    const reset = root.querySelector("[data-reset]"); if (reset) reset.hidden = !taps.length;
  };
  const draw = () => {   // the legs so far, on the Moon (the globe's route layer; academy/ui.js clears it on the next screen)
    const g = ctx.globe; if (!g || !g.route || typeof document === "undefined") return;
    g.route.set(taps.map((t, k) => { const el = document.createElement("span"); el.className = "g-tapdot"; el.textContent = String(k + 1); return { id: "t" + k, lat: t.lat, lon: t.lon, el }; }), taps.length);
  };
  return withDirective(ctx, {
    html: `<div class="g-route"><span class="g-dots" data-progress aria-hidden="true"></span><span class="g-label" data-label aria-live="polite">${esc(stopLine(taps.length))}</span>
      <button type="button" class="btn-quiet" data-reset hidden>${icon("retry", { size: 16 })}Start over</button></div>`,
    bind: el => {
      root = el; paint(); if (!ctx.locked) draw();
      const r = el && el.querySelector && el.querySelector("[data-reset]");
      if (r) r.onclick = () => { taps.length = 0; paint(); draw(); };
    },
    onTap: p => {
      if (taps.length >= n) return;
      taps.push({ lat: p.lat, lon: p.lon }); paint(); draw();
      ctx.answer({ taps: taps.slice() });
    },
  });
};

export const GLOBE_STEP_TYPES = ["predict", "earth_view", "globe_side", "terminator", "compare", "route"];
