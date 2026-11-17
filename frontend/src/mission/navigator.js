// The landing-site navigator (docs/SITE_NAVIGATOR.md): "Choose your landing site" before a mission.
//
// A south-pole map (LOLA relief + one NASA layer: sunlight, slope, ice, Earth view) beside the briefing panel: the 5
// sites we can fly and NASA's 9 Artemis III regions, each with real numbers from NASA's Lunar Reconnaissance Orbiter
// (GET /api/sites/navigator, built by backend/pipeline/site_physics.py), a source per number, and a score on NASA's
// own criteria that the kid can weigh (presets or 4 sliders). The layers are an optional download: without them the
// globe and its pins stay, and the map says it is downloading.
//
// Every input reaches it: mouse (drag, wheel, click), keyboard (the rows are a radio group; the map takes arrows and
// + / -), a controller (right stick pans, triggers zoom, D-pad + A), voice ("show sunlight", "which site has the most
// ice?", "ice first", "pick Malapert": turn_router site_layer / site_query / site_preset / pick_site) and gestures (fist
// pans, pinch and slide zooms, thumbs up picks the site you are pointing at, then flies it).
import { CRITERIA, CRITERIA_IDS, PRESETS, PRESET_LABEL, score, bestFor, presetOf, LAYER_SAY, TAG, fmt, queryLine, short } from "./navigator_score.js";
import { createSpinner, createZoomer } from "../gesture/spin.js";
import { icon } from "../assets/icons.js";
import "./navigator.css";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ic = (n, size = 14) => icon(n, { size });
const W_KEY = "outpost-nav-weights", L_KEY = "outpost-nav-layer";
const store = { get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } } };

export const LAYERS = ["sunlight", "slope", "ice", "earth"];
export const LAYER_LABEL = { sunlight: "Sunlight", slope: "Slope", ice: "Ice", earth: "Earth view" };
const LAYER_ICON = { sunlight: "sun", slope: "site", ice: "ice", earth: "earth" };
/** What CAPCOM says when a layer comes on (≤ 14 words). */
export function createNavigator({ panel, say = () => {}, onPick = () => {}, onStart = () => {}, active = () => true, onMapChange = () => {},
  missionText = () => "" } = {}) {
  let homed = false, data = null, places = [], weights = { ...PRESETS.balanced, ...store.get(W_KEY, {}) }, layer = store.get(L_KEY, "sunlight");
  let focus = null;                    // the place shown in the detail card (a site or a region)
  let selected = null, mapEl = null, canvas = null, imgs = {}, view = { x: 0, y: 0, z: 1 }, raf = 0, pollT = 0, watchT = 0;
  const spinner = createSpinner({ invert: false }), zoomer = createZoomer();
  if (!LAYERS.includes(layer) && layer !== "off") layer = "sunlight";

  const byId = id => places.find(p => p.id === id);
  const sources = () => (data && data.sources) || {};
  const layersReady = () => !!(data && data.layers && data.layers.state === "ready");
  const playableIds = () => places.filter(p => p.playable).map(p => p.id);

  async function load() {
    try {
      const r = await fetch("/api/sites/navigator");
      if (!r.ok) return false;
      data = await r.json(); places = data.places || [];
      return places.length > 0;
    } catch (e) { return false; }
  }

  // ---------------------------------------------------------------- the panel
  const srcLink = (key, label) => {
    const s = sources()[key]; if (!s) return "";
    return `<a class="mx-src nv-src" href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.title)}">${esc(label || s.label)}</a>`;
  };
  const rng = (p, key, unit = "") => {
    const r = p[key] && p[key].range; if (!r || r[0] == null || r[1] == null || r[0] === r[1]) return "";
    return `<small class="nv-rng">range ${esc(r[0])}–${esc(r[1])}${unit}</small>`;
  };
  function row(p, isSite) {
    const sc = score(p, weights), sel = isSite ? p.id === selected : p.id === (focus && focus.id);
    const nums = `<span class="nv-nums">
        <span title="Sunlight, % of the year">${ic("sun", 12)}${fmt(p, "sunlight_pct")}</span>
        <span title="Earth in view, % of the time">${ic("earth", 12)}${fmt(p, "earth_pct")}</span>
        <span title="Distance to ice">${ic("ice", 12)}${fmt(p, "ice_km")}</span>
        <span title="Slope at the landing spot">${ic("site", 12)}${fmt(p, "slope_deg")}</span></span>`;
    const tag = `<em class="nv-tag is-${esc(p.status)}">${esc(TAG[p.status] || "")}</em>`;
    const label = `${p.name}: score ${sc} of 100. ${TAG[p.status] || ""}. Sunlight ${fmt(p, "sunlight_pct")} of the year, Earth in view ${fmt(p, "earth_pct")}, ice ${fmt(p, "ice_km")}, slope ${fmt(p, "slope_deg")}`;
    if (isSite) {
      return `<button type="button" class="mx-site nv-row" role="radio" data-site="${esc(p.id)}" aria-checked="${sel}" tabindex="${sel ? 0 : -1}" aria-label="${esc(label)}">
        <span class="nv-top"><b>${esc(p.name)}</b><span class="nv-score" aria-hidden="true">${sc}</span></span>${tag}${nums}</button>`;
    }
    return `<button type="button" class="nv-row nv-region" data-place="${esc(p.id)}" aria-pressed="${sel}" aria-label="${esc(label)}">
      <span class="nv-top"><b>${esc(p.name)}</b><span class="nv-score" aria-hidden="true">${sc}</span></span>${nums}</button>`;
  }
  function detail(p) {
    if (!p) return "";
    const t = p.temp_c || {}, tr = t.range || [];
    const lines = [
      ["sun", "Sunlight", `${fmt(p, "sunlight_pct")} of the year`, rng(p, "sunlight_pct", "%"), "illum"],
      ["low-power", "Longest dark", fmt(p, "longest_dark_h"), `<small class="nv-rng">in 2026</small>`, "horizons"],
      ["earth", "Earth in view", `${fmt(p, "earth_pct")} of the time`, rng(p, "earth_pct", "%"), "earth"],
      ["ice", "Ice can last", p.ice_km.value != null && p.ice_km.value < 0.15 ? "right here" : `${fmt(p, "ice_km")} away`,
        p.ice_km.range && p.ice_km.range[0] != null ? `<small class="nv-rng">buried ice ${esc(p.ice_km.range[0])} km</small>` : "", "diviner"],
      ["site", "Slope at the pad", fmt(p, "slope_deg"), rng(p, "slope_deg", "°"), "slope"],
      ["heater", "Ground temperature", tr[0] != null ? `${tr[0]} to ${tr[1]} °C` : "–", `<small class="nv-rng">average to warmest</small>`, "diviner"],
      ["shelter", "Never-sunlit ground", fmt(p, "psr_km") === "here" ? "right here" : `${fmt(p, "psr_km")} away`, "", "psr"],
    ];
    const mt = p.playable ? missionText(p.id) : "";
    const mission = mt ? `<p class="nv-mission">${ic("mission", 14)}<span>In your mission: ${esc(mt)}</span></p>` : "";
    const where = p.kind === "region" ? `<p class="nv-note">${p.site ? `Our ${esc(short((byId(p.site) || {}).name))} outpost is in this region.` : "Compare only: no mission model here yet."}
      ${p.position && p.position.source === "regionmap" ? " Position read off NASA's map, about ±5 km." : ""}</p>` : "";
    return `<section class="nv-detail" aria-label="${esc(p.name)}: the numbers">
      <h3 class="nv-dh">${esc(p.name)}${p.kind === "region" ? ` <em class="nv-tag is-${esc(p.status)}">${esc(TAG[p.status] || "")}</em>` : ""}</h3>
      <dl class="nv-dl">${lines.map(([i, k, v, r, s]) => `<div><dt>${ic(i, 14)}${esc(k)}</dt><dd><b>${esc(v)}</b>${r}${srcLink(s)}</dd></div>`).join("")}</dl>
      ${mission}${where}</section>`;
  }
  function weightsHtml() {
    const cur = presetOf(weights);
    return `<div class="nv-weights" role="group" aria-label="What matters most">
      <div class="nv-presets">${Object.keys(PRESETS).map(k => `<button type="button" class="nv-chip" data-preset="${k}" aria-pressed="${cur === k}">${esc(PRESET_LABEL[k])}</button>`).join("")}</div>
      <details class="nv-sliders"${cur ? "" : " open"}><summary>Weigh it yourself</summary>
        ${CRITERIA_IDS.map(id => `<label class="nv-sl">${ic(CRITERIA[id].icon, 14)}<span>${esc(CRITERIA[id].label)}</span>
          <input type="range" min="0" max="3" step="1" value="${weights[id]}" data-w="${id}" aria-label="${esc(CRITERIA[id].label)} weight"><output>${weights[id]}</output></label>`).join("")}
      </details>
      <p class="nv-crit">NASA picks Artemis sites for sunlight, radio, ice and a safe landing. ${srcLink("criteria", "NASA, 2026")}</p></div>`;
  }

  function render({ site, firstPick = false, recommended = null, recTag = "" } = {}) {
    selected = site ? site.id : (selected || playableIds()[0]);
    if (!focus || (focus.kind === "site" && focus.id !== selected) || !byId(focus.id)) focus = byId(selected);
    const sites = places.filter(p => p.playable), regions = places.filter(p => p.kind === "region");
    const sel = byId(selected);
    panel.classList.add("mx-brief", "nv");
    panel.innerHTML = `
      <header class="mx-head"><span class="eyebrow">Briefing · Landing site</span></header>
      <h2 class="mx-title">Choose your landing site</h2>
      ${weightsHtml()}
      <div class="nv-scroll">
        <div class="mx-sites nv-list" role="radiogroup" aria-label="Outpost site">
          ${sites.map(p => row(p, true).replace("<b>", firstPick && p.id === recommended ? `<b data-rec>` : "<b>") +
            (focus && focus.id === p.id ? detail(p) : "")).join("")}
        </div>
        <details class="nv-regions"${focus && focus.kind === "region" ? " open" : ""}><summary>NASA's 9 Artemis III regions <small>compare</small></summary>
          <div class="nv-list">${regions.map(p => row(p, false) + (focus && focus.id === p.id ? detail(p) : "")).join("")}</div></details>
      </div>
      <button type="button" class="mx-go" id="mStart">Start<small>${esc(short(sel && sel.name))}</small></button>`;
    if (firstPick && recommended) {
      const b = panel.querySelector("b[data-rec]"); if (b) b.insertAdjacentHTML("beforeend", `<em class="mx-rectag">${esc(recTag)}</em>`);
    }
    bindPanel();
    ensureMap();
  }

  function bindPanel() {
    panel.querySelectorAll(".mx-site").forEach(b => {
      b.onclick = () => pick(b.dataset.site, { from: "tap" });
      b.onpointerenter = () => hot(b.dataset.site, true); b.onpointerleave = () => hot(b.dataset.site, false);
    });
    panel.querySelectorAll(".nv-region").forEach(b => {
      b.onclick = () => showPlace(b.dataset.place, { fly: true });
      b.onpointerenter = () => hot(b.dataset.place, true); b.onpointerleave = () => hot(b.dataset.place, false);
    });
    const list = panel.querySelector(".mx-sites");
    if (list) list.addEventListener("keydown", e => {
      const d = { ArrowDown: 1, ArrowUp: -1 }[e.key]; if (!d) return;
      const ids = playableIds(), k = ids.indexOf(selected) + d; if (k < 0 || k >= ids.length) return;
      e.preventDefault(); e.stopPropagation(); pick(ids[k], { from: "key" });
    });
    panel.querySelectorAll("[data-preset]").forEach(b => { b.onclick = () => setPreset(b.dataset.preset); });
    panel.querySelectorAll("input[data-w]").forEach(inp => {
      inp.oninput = () => { weights = { ...weights, [inp.dataset.w]: +inp.value }; store.set(W_KEY, weights); inp.nextElementSibling.textContent = inp.value; rescore(); };
    });
    const st = panel.querySelector("#mStart"); if (st) st.onclick = () => onStart();
  }
  /** New weights: only the scores and the preset chips change (the sliders keep focus). */
  function rescore() {
    panel.querySelectorAll("[data-site],[data-place]").forEach(b => {
      const p = byId(b.dataset.site || b.dataset.place), s = b.querySelector(".nv-score"); if (p && s) s.textContent = score(p, weights);
      if (p && b.getAttribute("aria-label")) b.setAttribute("aria-label", b.getAttribute("aria-label").replace(/score \d+ of 100/, `score ${score(p, weights)} of 100`));
    });
    const cur = presetOf(weights);
    panel.querySelectorAll("[data-preset]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.preset === cur)));
    drawPins();
  }
  function setPreset(id) {
    if (!PRESETS[id]) return false;
    weights = { ...PRESETS[id] }; store.set(W_KEY, weights);
    panel.querySelectorAll("input[data-w]").forEach(inp => { inp.value = weights[inp.dataset.w]; inp.nextElementSibling.textContent = inp.value; });
    rescore();
    return true;
  }
  function hot(id, on) {
    document.querySelectorAll(`[data-site="${CSS.escape(id)}"], [data-place="${CSS.escape(id)}"]`).forEach(n => n.classList.toggle("is-hot", on));
  }

  /** Select a site we can fly (the radio row), or show a region. */
  function pick(id, { from = "tap", fly = false } = {}) {
    const p = byId(id); if (!p) return false;
    if (!p.playable) return showPlace(id, { fly: true, from });
    focus = p; selected = id;
    if (fly) flyTo(p, Math.max(view.z, 3));
    else keepInView(p);
    onPick(id, from);
    return true;
  }
  function showPlace(id, { fly = false } = {}) {
    const p = byId(id); if (!p) return false;
    focus = p;
    const keep = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.place : null;
    render({ site: byId(selected) });
    if (fly) flyTo(p, Math.max(view.z, 2.5));
    const n = keep && panel.querySelector(`[data-place="${CSS.escape(keep)}"]`); if (n) n.focus({ preventScroll: true });
    const d = panel.querySelector(".nv-detail"); if (d && d.scrollIntoView) d.scrollIntoView({ block: "nearest" });
    return true;
  }

  // ---------------------------------------------------------------- the map
  const E = () => (data && data.layers && data.layers.extent_km ? data.layers.extent_km : 210) * 1000;
  function ensureMap() {
    if (!layersReady()) { showDownloading(); return; }
    if (!mapEl) buildMap();
    const first = mapEl.hidden || !homed;
    mapEl.hidden = false; layout();
    if (first) { Object.assign(view, home()); clampView(); homed = true; }
    setLayer(layer, { quiet: true }); drawPins(); watch();
    onMapChange(true);
  }
  function showDownloading() {
    if (!mapEl) { mapEl = document.createElement("div"); mapEl.className = "nv-map is-pending"; panel.parentNode.insertBefore(mapEl, panel); }
    const st = data && data.layers ? data.layers.state : "missing";
    mapEl.innerHTML = `<p class="nv-pending" role="status">${ic("map", 16)}${st === "downloading" ? "Map layers downloading…" : data && data.layers && data.layers.managed ? "Map layers download when you're online." : "Map layers are not on this computer yet."}</p>`;
    mapEl.hidden = false; onMapChange(false); watch();
    if (st === "missing" && data && data.layers && data.layers.managed) fetch("/api/sites/layers/want", { method: "POST" }).catch(() => {});
    clearTimeout(pollT);
    pollT = setTimeout(async () => {
      if (!active()) return;
      const ok = await load();
      if (ok && layersReady()) { mapEl.remove(); mapEl = null; render({ site: byId(selected) }); }
      else if (active()) showDownloading();
    }, 5000);
  }
  function buildMap() {
    mapEl = document.createElement("div"); mapEl.className = "nv-map";
    mapEl.innerHTML = `<canvas class="nv-canvas" aria-hidden="true"></canvas>
      <div class="nv-hit" tabindex="0" role="application" aria-label="South pole map. Arrow keys move it, plus and minus zoom. Pick a site from the list."></div>
      <div class="nv-pins"></div>
      <div class="nv-bar" role="group" aria-label="Map layers">
        ${LAYERS.map(l => `<button type="button" class="nv-layer" data-layer="${l}" aria-pressed="false">${ic(LAYER_ICON[l], 14)}${LAYER_LABEL[l]}</button>`).join("")}
      </div>
      <div class="nv-zoom" role="group" aria-label="Zoom"><button type="button" data-z="in" aria-label="Zoom in">+</button><button type="button" data-z="out" aria-label="Zoom out">−</button><button type="button" data-z="home" aria-label="Whole south pole">${ic("orbit", 14)}</button></div>
      <div class="nv-legend" aria-live="polite"></div>`;
    panel.parentNode.insertBefore(mapEl, panel);
    canvas = mapEl.querySelector("canvas");
    const files = { base: data.layers.base.file, ...Object.fromEntries(LAYERS.map(l => [l, data.layers.layers[l].file])) };
    Object.entries(files).forEach(([k, f]) => { const im = new Image(); im.onload = draw; im.src = "/api/sites/layers/" + f; imgs[k] = im; });
    mapEl.querySelectorAll(".nv-layer").forEach(b => { b.onclick = () => setLayer(layer === b.dataset.layer ? "off" : b.dataset.layer); });
    mapEl.querySelectorAll("[data-z]").forEach(b => { b.onclick = () => { const z = b.dataset.z; if (z === "home") { const hv = home(); flyTo({ spot: { x_m: hv.x, y_m: hv.y } }, hv.z); } else zoomer.nudge(z === "in" ? 1.6 : 1 / 1.6), run(); }; });
    // mouse: drag pans, the wheel zooms about the cursor, a click on empty map picks the nearest pin within 24 px
    const hit = mapEl.querySelector(".nv-hit");
    let drag = null;
    hit.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY, moved: 0 }; hit.setPointerCapture(e.pointerId); });
    hit.addEventListener("pointermove", e => {
      if (!drag) { hoverAt(e.clientX, e.clientY); return; }
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.x = e.clientX; drag.y = e.clientY; drag.moved += Math.abs(dx) + Math.abs(dy);
      panBy(-dx, -dy);
    });
    hit.addEventListener("pointerup", e => { const d = drag; drag = null; if (d && d.moved < 6) { const p = nearestPin(e.clientX, e.clientY); if (p) pick(p.id, { from: "map" }); } });
    hit.addEventListener("wheel", e => { e.preventDefault(); zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY); }, { passive: false });
    hit.addEventListener("keydown", e => {
      const step = 60, k = e.key;
      const m = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[k];
      if (m) { e.preventDefault(); e.stopPropagation(); panBy(m[0], m[1]); return; }
      if (k === "+" || k === "=") { e.preventDefault(); e.stopPropagation(); zoomer.nudge(1.5); run(); }
      if (k === "-" || k === "_") { e.preventDefault(); e.stopPropagation(); zoomer.nudge(1 / 1.5); run(); }
    });
    addEventListener("resize", () => { if (mapEl && !mapEl.hidden) { layout(); draw(); drawPins(); } });
  }
  /** The map fills the stage left of the panel, above the voice bar and the caption line wherever they sit. */
  function layout() {
    if (!mapEl || !mapEl.parentNode) return;
    const st = mapEl.parentNode.getBoundingClientRect(), pr = panel.getBoundingClientRect();
    const gap = 16, right = Math.max(gap, st.right - pr.left + gap);
    let bottom = gap;
    ["askbar", "captionBar", "voicebar"].forEach(id => {
      const el = document.getElementById(id); if (!el) return;
      const r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
      // the caption line comes and goes above the ask bar: keep its room (about 56 px) even while it is empty
      const top = id === "askbar" ? r.top - 56 : r.top;
      if (r.left < pr.left - gap && r.top > st.top + st.height / 2) bottom = Math.max(bottom, st.bottom - top + 12);
    });
    document.querySelectorAll(".vbar, .voicebar, .comm-strip").forEach(el => {
      const r = el.getBoundingClientRect(); if (!r.width || el.closest(".nv-map")) return;
      if (r.left < pr.left - gap && r.top > st.top + st.height / 2) bottom = Math.max(bottom, st.bottom - r.top + 12);
    });
    Object.assign(mapEl.style, { left: gap + "px", top: gap + "px", right: right + "px", bottom: bottom + "px" });
    // the panel ends above a voice bar that sits under it (a narrow window centres the bar)
    let pb = st.bottom - gap;
    ["askbar", "captionBar"].forEach(id => {
      const el = document.getElementById(id); if (!el || el.closest("#mPanel")) return;
      const r = el.getBoundingClientRect(); if (!r.width || !r.height) return;
      if (r.right > pr.left + 4 && r.left < pr.right - 4 && r.top > st.top + st.height / 2) pb = Math.min(pb, r.top - 8);
    });
    panel.style.maxHeight = Math.max(240, pb - pr.top) + "px";
    const r = mapEl.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
    canvas.width = Math.max(1, Math.round(r.width * dpr)); canvas.height = Math.max(1, Math.round(r.height * dpr));
    canvas.style.width = r.width + "px"; canvas.style.height = r.height + "px";
  }
  const size = () => { const r = mapEl.getBoundingClientRect(); return { w: r.width, h: r.height, l: r.left, t: r.top }; };
  const mpp = () => { const { w, h } = size(); return (2 * E()) / Math.max(1, Math.min(w, h)) / view.z; };
  const toScreen = (x, y) => { const { w, h } = size(), m = mpp(); return { x: w / 2 + (x - view.x) / m, y: h / 2 - (y - view.y) / m }; };
  /** Keep the map on the data: the view never shows past the layers' edge (unless the window is wider than the map). */
  const clampView = () => {
    view.z = Math.max(1, Math.min(14, view.z));
    const { w, h } = size(), m = mpp(), lim = E();
    const hx = Math.max(0, lim - (w / 2) * m), hy = Math.max(0, lim - (h / 2) * m);
    view.x = Math.max(-hx, Math.min(hx, view.x)); view.y = Math.max(-hy, Math.min(hy, view.y));
  };
  function panBy(dx, dy) { const m = mpp(); view.x += dx * m; view.y -= dy * m; clampView(); draw(); drawPins(); }
  function zoomAt(f, cx, cy) {
    const { w, h, l, t } = size(), m0 = mpp();
    const wx = view.x + (cx - l - w / 2) * m0, wy = view.y - (cy - t - h / 2) * m0;
    view.z *= f; clampView(); const m1 = mpp();
    view.x = wx - (cx - l - w / 2) * m1; view.y = wy + (cy - t - h / 2) * m1; clampView(); draw(); drawPins();
  }
  let flyAnim = 0;
  function flyTo(p, z) {
    if (!mapEl || !p) return;
    const s = p.spot || p, from = { ...view }, to = { x: s.x_m, y: s.y_m, z: z || view.z }, t0 = performance.now();
    cancelAnimationFrame(flyAnim);
    const reduce = document.documentElement.dataset.motion === "reduce";
    const step = now => {
      const k = reduce ? 1 : Math.min(1, (now - t0) / 700), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      view.x = from.x + (to.x - from.x) * e; view.y = from.y + (to.y - from.y) * e; view.z = from.z * Math.pow(to.z / from.z, e);
      clampView(); draw(); drawPins();
      if (k < 1) flyAnim = requestAnimationFrame(step);
    };
    flyAnim = requestAnimationFrame(step);
  }
  function keepInView(p) {
    if (!mapEl || !p || !p.spot) return;
    const s = toScreen(p.spot.x_m, p.spot.y_m), { w, h } = size();
    if (s.x < 40 || s.y < 60 || s.x > w - 40 || s.y > h - 70) flyTo(p, view.z);
    else drawPins();
  }
  function draw() {
    if (!canvas || !mapEl || mapEl.hidden) return;
    const ctx = canvas.getContext("2d"), dpr = canvas.width / Math.max(1, size().w);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const { w, h } = size(); ctx.clearRect(0, 0, w, h);
    const a = toScreen(-E(), E()), side = 2 * E() / mpp();
    ctx.imageSmoothingEnabled = true;
    if (imgs.base && imgs.base.complete && imgs.base.naturalWidth) ctx.drawImage(imgs.base, a.x, a.y, side, side);
    const im = imgs[layer];
    if (layer !== "off" && im && im.complete && im.naturalWidth) ctx.drawImage(im, a.x, a.y, side, side);
    // the pole and a 100 km ring, for scale
    const p0 = toScreen(0, 0), r100 = 100000 / mpp();
    ctx.strokeStyle = "rgba(255,255,255,.35)"; ctx.setLineDash([4, 5]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(p0.x, p0.y, r100, 0, Math.PI * 2); ctx.stroke(); ctx.setLineDash([]);
    ctx.fillStyle = "rgba(255,255,255,.8)"; ctx.font = "600 11px system-ui, sans-serif";
    ctx.fillText("100 km from the pole", p0.x + r100 * .72 + 4, p0.y - r100 * .72);
    ctx.beginPath(); ctx.arc(p0.x, p0.y, 3, 0, Math.PI * 2); ctx.fill();
  }
  /** Pins: every site and region; labels placed greedily (the selected and the focused first), never overlapping. */
  function drawPins() {
    if (!mapEl || mapEl.hidden) return;
    const host = mapEl.querySelector(".nv-pins"); if (!host) return;
    const { w, h } = size();
    const order = places.slice().sort((a, b) => rank(b) - rank(a));
    function rank(p) { return (p.id === selected ? 100 : 0) + (focus && p.id === focus.id ? 50 : 0) + (p.playable ? 10 : 0) + score(p, weights) / 100; }
    const placed = [], out = [];
    const dots = order.map(p => { const s = toScreen(p.spot.x_m, p.spot.y_m); return { id: p.id, x: s.x - 7, y: s.y - 7, w: 14, h: 14 }; });
    // the map's own controls: the layer bar, the zoom buttons, the legend (labels never sit on them)
    const mr = mapEl.getBoundingClientRect();
    [".nv-bar", ".nv-zoom", ".nv-legend"].forEach(q => { const e = mapEl.querySelector(q); if (!e || !e.offsetParent) return;
      const r = e.getBoundingClientRect(); if (r.width) placed.push({ id: q, x: r.left - mr.left - 4, y: r.top - mr.top - 4, w: r.width + 8, h: r.height + 8 }); });
    for (const p of order) {
      const s = toScreen(p.spot.x_m, p.spot.y_m);
      if (s.x < -20 || s.y < -20 || s.x > w + 20 || s.y > h + 20) continue;
      const label = short(p.name), lw = textW(label) + 44, lh = 24;
      const quiet = p.kind === "region" && p.site && p.id !== (focus && focus.id);   // the region our own site stands in
      let box = null;
      if (quiet) { out.push({ p, s, box: null, label }); continue; }
      for (const [dx, dy] of [[10, -lh / 2], [-10 - lw, -lh / 2], [-lw / 2, -lh - 8], [-lw / 2, 8]]) {
        const b = { x: s.x + dx, y: s.y + dy, w: lw, h: lh };
        if (b.x < 4 || b.y < 4 || b.x + b.w > w - 4 || b.y + b.h > h - 4) continue;
        const hit = o => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y;
        if (!placed.some(hit) && !dots.some(o => o.id !== p.id && hit(o))) { box = b; break; }
      }
      if (!box && p.id === selected) {   // the picked site always gets its label: other pins' dots may sit under it
        for (const [dx, dy] of [[10, -lh / 2], [-10 - lw, -lh / 2], [-lw / 2, -lh - 8], [-lw / 2, 8]]) {
          const b = { x: s.x + dx, y: s.y + dy, w: lw, h: lh };
          if (b.x < 4 || b.y < 4 || b.x + b.w > w - 4 || b.y + b.h > h - 4) continue;
          if (!placed.some(o => b.x < o.x + o.w && b.x + b.w > o.x && b.y < o.y + o.h && b.y + b.h > o.y)) { box = b; break; }
        }
      }
      if (box) placed.push(box);
      out.push({ p, s, box, label });
    }
    host.innerHTML = out.map(({ p, s, box, label }) => {
      const cls = `nv-pin${p.playable ? " is-site" : " is-region"}${p.id === selected ? " is-sel" : ""}${focus && p.id === focus.id ? " is-focus" : ""} is-${p.status}`;
      const dot = `<i class="${cls}" style="transform:translate(${s.x.toFixed(1)}px,${s.y.toFixed(1)}px)" data-pin="${esc(p.id)}"></i>`;
      const lab = box ? `<button type="button" tabindex="-1" class="nv-plab${p.id === selected ? " is-sel" : ""}${p.playable ? "" : " is-region"}" data-pin="${esc(p.id)}" style="transform:translate(${box.x.toFixed(1)}px,${box.y.toFixed(1)}px)">${esc(label)}<span class="nv-ps">${score(p, weights)}</span></button>` : "";
      return dot + lab;
    }).join("");
    host.querySelectorAll("button[data-pin]").forEach(b => {
      b.onclick = () => pick(b.dataset.pin, { from: "map" });
      b.onpointerenter = () => hot(b.dataset.pin, true); b.onpointerleave = () => hot(b.dataset.pin, false);
    });
  }
  let measure = null;
  function textW(t) {
    if (!measure) { measure = document.createElement("canvas").getContext("2d"); measure.font = "600 12px Inter Variable, system-ui, sans-serif"; }
    return Math.ceil(measure.measureText(t).width);
  }
  /** The first view: every site and region in frame, as big as fits. */
  function home() {
    const xs = places.map(p => p.spot.x_m), ys = places.map(p => p.spot.y_m);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const { w, h } = size(), base = (2 * E()) / Math.max(1, Math.min(w, h));
    const need = Math.max((x1 - x0) * 1.25 / Math.max(1, w - 60), (y1 - y0) * 1.3 / Math.max(1, h - 150));
    return { x: (x0 + x1) / 2, y: (y0 + y1) / 2 - 8 * need, z: Math.max(1, Math.min(4, base / need)) };
  }
  function nearestPin(cx, cy) {
    const { l, t } = size(); let best = null, bd = 24;
    for (const p of places) { const s = toScreen(p.spot.x_m, p.spot.y_m), d = Math.hypot(s.x + l - cx, s.y + t - cy); if (d < bd) { bd = d; best = p; } }
    return best;
  }
  let pointed = null, hovered = null;   // pointed: the gesture's index finger (the thumbs up target); hovered: the mouse
  function hoverAt(cx, cy, gesture = false) {
    const p = nearestPin(cx, cy), cur = gesture ? pointed : hovered;
    if ((p && p.id) === (cur && cur.id)) return;
    if (cur) hot(cur.id, false);
    if (gesture) pointed = p; else hovered = p;
    if (p) hot(p.id, true);
  }

  function setLayer(id, { quiet = false } = {}) {
    if (id !== "off" && !LAYERS.includes(id)) return false;
    layer = id; store.set(L_KEY, id);
    if (mapEl) {
      mapEl.querySelectorAll(".nv-layer").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.layer === id)));
      mapEl.dataset.layer = id;
      legend(); draw();
    }
    if (!quiet) Promise.resolve(say(LAYER_SAY[id])).catch(() => {});
    return true;
  }
  function legend() {
    const el = mapEl && mapEl.querySelector(".nv-legend"); if (!el || !data) return;
    const L = data.layers.layers[layer], base = data.layers.base;
    const credit = `<p class="nv-credit">${L ? `${esc(LAYER_LABEL[layer])}: <a href="${esc(L.url)}" target="_blank" rel="noopener">${esc(L.credit)}</a>${L.credit2 ? ` · ${esc(L.credit2)}` : ""} · ` : ""}Terrain: <a href="${esc(base.url)}" target="_blank" rel="noopener">${esc(base.credit)}</a></p>`;
    if (!L) { el.innerHTML = credit; return; }
    let key;
    if (layer === "ice") {
      key = `<span class="nv-sw" style="--c:rgba(60,110,240,.9)"></span>${esc(L.legend[0][1])}<span class="nv-sw" style="--c:rgb(215,252,255)"></span>${esc(L.legend[1][1])}`;
    } else {
      const lo = L.ramp[0][0], hi = L.ramp[L.ramp.length - 1][0];
      const stops = L.ramp.map(([v, c]) => `rgba(${c[0]},${c[1]},${c[2]},${Math.max(.35, c[3] / 255).toFixed(2)}) ${((v - lo) / (hi - lo) * 100).toFixed(0)}%`).join(",");
      key = `<span class="nv-ramp" style="background:linear-gradient(90deg,${stops})">${L.legend.map(([v, t]) => `<i style="left:${((v - lo) / (hi - lo) * 100).toFixed(0)}%">${esc(t)}</i>`).join("")}</span>`;
    }
    el.innerHTML = `<p class="nv-lt"><b>${esc(L.title)}</b>${L.unit ? ` <small>${esc(L.unit)}</small>` : ""}</p><div class="nv-key">${key}</div>${credit}`;
  }

  // the continuous inputs (fist / right stick pans, pinch / triggers zoom) on one animation loop
  let last = 0;
  function frame(now) {
    const dt = last ? (now - last) / 1000 : 1 / 60; last = now;
    const d = spinner.step(dt), z = zoomer.step(dt);
    if (d.dx || d.dy) panBy(d.dx * 220, -d.dy * 220);
    if (Math.abs(z.factor - 1) > 1e-6) { const { l, t, w, h } = size(); zoomAt(z.factor, l + w / 2, t + h / 2); }
    if (spinner.active || zoomer.active) raf = requestAnimationFrame(frame); else { raf = 0; last = 0; }
  }
  function run() { if (!raf) { last = 0; raf = requestAnimationFrame(frame); } }
  const mapUp = () => !!(mapEl && !mapEl.hidden && canvas && active());

  /** Bus intents (input/intents.js), priority above the globe's defaults while the map is up. */
  const busHandlers = {
    spin: a => { if (!mapUp()) return false; spinner.set(a.phase === "end" ? null : a); run(); return true; },
    rotate: a => { if (!mapUp()) return false; if (a.phase === "move") { const { w } = size(); panBy(-a.dx * w * .8, -a.dy * w * .8); } return true; },
    zoom_rate: a => { if (!mapUp()) return false; zoomer.set(a.phase === "end" ? null : +a.rate || 0, { tap: !!a.tap }); run(); return true; },
    zoom: a => { if (!mapUp() || !(a.factor > 0)) return false; const { l, t, w, h } = size(); zoomAt(a.factor, l + w / 2, t + h / 2); return true; },
    zoom_in: () => { if (!mapUp()) return false; zoomer.nudge(1.6); run(); return true; },
    zoom_out: () => { if (!mapUp()) return false; zoomer.nudge(1 / 1.6); run(); return true; },
    point: a => { if (!mapUp() || a.x == null) return false; hoverAt(a.x, a.y, true); return false; },
    // thumbs up: the site you point at (or the focused row) is picked first; a second thumbs up flies it
    yes: () => {
      if (!active() || !data) return false;
      // an offer card on top (the Moon Base video, a yes / no) answers its own yes
      if ([...document.querySelectorAll('[data-intent="yes"], [data-intent="no"]')].some(b => b.offsetParent !== null && !panel.contains(b))) return false;
      const el = document.activeElement, rowId = el && el.dataset && (el.dataset.site || el.dataset.place);
      const target = rowId || (pointed && pointed.id);
      if (target && target !== selected && (!focus || target !== focus.id) && byId(target)) { pick(target, { from: "gesture", fly: true }); pointed = null; return true; }
      onStart();                    // the picked site again: fly it
      return true;
    },
  };
  let busOff = [];
  import("../input/intents.js").then(m => {
    busOff = Object.entries(busHandlers).map(([n, fn]) => m.onIntent(n, a => fn(a || {}) === true, { priority: n === "yes" ? 25 : 12 }));
  }).catch(() => {});

  /** Leave the screen: the map goes away (the globe is the background again). */
  function hide() {
    clearTimeout(pollT); clearInterval(watchT); watchT = 0; cancelAnimationFrame(raf); raf = 0; spinner.halt(); zoomer.halt();
    if (mapEl) mapEl.hidden = true;
    panel.classList.remove("nv"); panel.style.maxHeight = "";
  }
  function watch() { if (!watchT) watchT = setInterval(() => { if (!active()) hide(); else if (mapEl && !mapEl.hidden && canvas) { layout(); draw(); drawPins(); } }, 700); }

  /** Router / shell intents on the picker. Returns true when handled. */
  function nav(intent, arg) {
    if (!data) return false;
    if (intent === "site_layer") {
      if (!layersReady()) { say(data.layers && data.layers.state === "downloading" ? "The map layers are still downloading." : "The map layers aren't on this computer yet."); return true; }
      return setLayer(arg || "sunlight");
    }
    if (intent === "site_query") {
      const pool = places.filter(p => p.playable);
      const best = bestFor(pool, arg, weights), all = bestFor(places, arg, weights);
      if (!best) return false;
      const lay = { ice: "ice", sunlight: "sunlight", earth: "earth", slope: "slope" }[arg];
      if (lay && layersReady()) setLayer(lay, { quiet: true });
      pick(best.id, { from: "voice", fly: true });
      let line = queryLine(best, arg);
      if (all && all.id !== best.id && !all.playable) line += ` On NASA's list: ${short(all.name)}.`;
      Promise.resolve(say(line)).catch(() => {});
      return true;
    }
    if (intent === "site_preset") {
      if (!setPreset(arg || "balanced")) return false;
      const top = bestFor(places.filter(p => p.playable), "best", weights);
      Promise.resolve(say(`${PRESET_LABEL[arg] || "Balanced"}. ${top ? short(top.name) + " scores best now." : ""}`)).catch(() => {});
      return true;
    }
    if (intent === "pick_site" && byId(arg) && !byId(arg).playable) {
      const p = byId(arg); showPlace(arg, { fly: true });
      Promise.resolve(say(p.site ? `${short(p.name)}. Our ${short(byId(p.site).name)} outpost is there.` : `${short(p.name)}. It's on NASA's list. We can't fly it yet.`)).catch(() => {});
      return true;
    }
    return false;
  }

  return {
    load, render, hide, nav, pick, setLayer, setPreset,
    get ready() { return !!data && places.length > 0; },
    get mapShown() { return !!(mapEl && !mapEl.hidden && canvas); },
    get layer() { return layer; }, get weights() { return { ...weights }; }, get focus() { return focus && focus.id; },
    get view() { return { ...view }; },
    place: byId, get places() { return places.slice(); },
    destroy() { hide(); busOff.forEach(f => f()); if (mapEl) mapEl.remove(); mapEl = null; },
  };
}
