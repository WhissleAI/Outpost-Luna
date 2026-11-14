// Flight School globe steps (docs/LEARNING_DESIGN.md §3, contract §9.2). Minimal renderers; the UX lead owns the final
// look. Grading is server-side (backend/app/academy/grade.py); these draw the step, move the globe, and send
// {choice} / {tap} / {taps} / {view} / {text}. Every step also works by voice alone: the Academy sends the kid's words.
//
// Registered on window.__outpost.stepRenderers[type] as a factory
//   ({step, acc, answer, say, playCrew, esc, captions, globe}) -> {html, bind(el), onTap?(p)}
// `onTap(p)` (p = {lat, lon}) is called by academy/ui.js for a tap on the Moon while this step is open.
// The step's `globe` directive ({do: fly|side|pole|sun|pair|earth|route, ...}) runs when the step opens.

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };
O.stepRenderers = O.stepRenderers || {};

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Buttons for options, numbered so "option 2" works by voice and Tab/Enter by keyboard. */
export function optionsHtml(options, cls = "") {
  return `<div class="a-choices g-opts ${cls}" role="group" aria-label="Answers">${(options || []).map((o, k) =>
    `<button type="button" class="a-choice" data-c="${esc(o.id)}"><span class="a-key" aria-hidden="true">${k + 1}</span>${esc(o.label)}</button>`).join("")}</div>`;
}
function bindOptions(root, ctx) {
  root.querySelectorAll(".a-choice").forEach(b => (b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)));
}

/** Run a step's globe directive. Missing globe features are skipped (older globe.js), never an error. */
export function runDirective(globe, g) {
  if (!globe || !g) return;
  const call = (fn, ...a) => (typeof globe[fn] === "function" ? globe[fn](...a) : undefined);
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
  bind: root => { runDirective(ctx.globe, ctx.step.globe); if (extra.bind) extra.bind(root); },
});

O.stepRenderers.predict = ctx => withDirective(ctx, {
  html: `<p class="a-how">Make your guess, then we check the data</p>${optionsHtml(ctx.acc.options)}`,
  bind: root => bindOptions(root, ctx),
});

O.stepRenderers.earth_view = ctx => withDirective(ctx, {
  html: `<p class="a-how">Is Earth in the sky from there?</p>${optionsHtml(ctx.acc.options, "is-row")}`,
  bind: root => bindOptions(root, ctx),
});

O.stepRenderers.globe_side = ctx => withDirective(ctx, {
  html: `<p class="a-how">Turn the Moon, or pick a side</p>
    <div class="a-choices g-opts is-row" role="group" aria-label="Sides">
      <button type="button" class="a-choice" data-c="near"><span class="a-key" aria-hidden="true">1</span>Near side</button>
      <button type="button" class="a-choice" data-c="far"><span class="a-key" aria-hidden="true">2</span>Far side</button>
      <button type="button" class="pill" data-view>This side</button></div>`,
  bind: root => {
    root.querySelectorAll(".a-choice").forEach(b => (b.onclick = () => {
      if (ctx.globe) ctx.globe.flyTo(0, b.dataset.c === "far" ? 180 : 0, 3.4);
      ctx.answer({ choice: b.dataset.c }, b);
    }));
    const v = root.querySelector("[data-view]");
    if (v) v.onclick = () => ctx.globe && ctx.answer({ view: ctx.globe.centerLatLon() }, v);
  },
});

O.stepRenderers.terminator = ctx => withDirective(ctx, {
  html: `<p class="a-how">Tap the Moon where light turns to dark, or say it</p>`,
  bind: () => { if (ctx.globe && ctx.globe.setSunDir) ctx.globe.setSunDir(0, ctx.acc.sun_lon); },
  onTap: p => ctx.answer({ tap: { lat: p.lat, lon: p.lon } }),
});

O.stepRenderers.compare = ctx => withDirective(ctx, {
  html: `<p class="a-how">Pick one: tap a card, a site on the Moon, or say its name</p>${optionsHtml(ctx.acc.options, "is-row")}`,
  bind: root => bindOptions(root, ctx),
  onTap: p => ctx.answer({ tap: { lat: p.lat, lon: p.lon } }),
});

O.stepRenderers.route = ctx => {
  const taps = [], n = (ctx.acc.stops || []).length;
  let live = null;
  return withDirective(ctx, {
    html: `<p class="a-how">Tap the stops in order, or say them in order</p>
      <p class="g-route" aria-live="polite" data-progress>Stop 1 of ${n}</p>
      <button type="button" class="pill" data-reset>Start over</button>`,
    bind: root => {
      live = root.querySelector("[data-progress]");
      const r = root.querySelector("[data-reset]");
      if (r) r.onclick = () => { taps.length = 0; if (live) live.textContent = `Stop 1 of ${n}`; };
    },
    onTap: p => {
      taps.push({ lat: p.lat, lon: p.lon });
      if (live) live.textContent = taps.length < n ? `Stop ${taps.length + 1} of ${n}` : "Checking your route";
      if (taps.length >= n) { const sent = taps.splice(0); ctx.answer({ taps: sent }); }
    },
  });
};

export const GLOBE_STEP_TYPES = ["predict", "earth_view", "globe_side", "terminator", "compare", "route"];
