// [0.5.6] The picture viewer: a lesson's photo or figure, a lidar map, a bundled document's pages, seen big, with zoom and
// pan. Owner playtest 0.5.5: the pictures in the lesson card were too small to read, and the NPS rack card the lesson
// cites was a dead link (the app is offline-first: its pages now ship in the course pack and open here).
//
//   openLightbox({title, items: [{src, alt, caption?, credit?}], index?})   pictures (a document: one item per page)
//   openLightbox({title, live: {render(host), aspect?, caption?}})          a live step (the lidar hillshade): the step
//       draws itself into the viewer, so a tap there counts, its found rings show and Low sun works; the Academy
//       re-draws it after every answer ("outpost:step-render", academy/ui.js render)
//
// Pointer: drag pans (a press that moves less than 5 px is a tap and goes through), wheel or pinch zooms round the
// pointer, double-click zooms in (pictures only). Keys: + / - zoom, 0 fits, arrows pan (or turn the page when not zoomed),
// Page Up / Page Down turn the page, Esc or the Close button closes and focus goes back where it was. Tab stays inside.
// Voice: "back" / "close" closes (the intents bus, input/intents.js). No inline handlers (the app's CSP).
import { onIntent } from "../input/intents.js";

const MIN = 1, MAX = 6, TAP_PX = 5;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Where the content sits: scale s round the view's centre plus a pan, kept so the content covers the view where it can
 *  (never dragged off into empty space). Pure (tests/lightbox.test.js). view, box: {w, h} (box = the content at s = 1). */
export function clampPan({ s, tx, ty }, view, box) {
  const w = box.w * s, h = box.h * s;
  const lim = (t, size, v) => (size <= v ? (v - size) / 2 : Math.max(v - size, Math.min(0, t)));
  return { s, tx: lim(tx, w, view.w), ty: lim(ty, h, view.h) };
}
/** Zoom to `s2` keeping the content point under (px, py) (view coordinates) where it is. Pure. */
export function zoomAt({ s, tx, ty }, s2, px, py) {
  const k = Math.max(MIN, Math.min(MAX, s2)) / s;
  return { s: s * k, tx: px - (px - tx) * k, ty: py - (py - ty) * k };
}
/** The content's size at s = 1: as big as fits the view, keeping its aspect (w / h). Pure. */
export function fitBox(view, aspect) {
  const a = aspect > 0 ? aspect : 4 / 3;
  return view.w / view.h > a ? { w: Math.round(view.h * a), h: view.h } : { w: view.w, h: Math.round(view.w / a) };
}

let cur = null;   // the open viewer: {el, view, canvas, st, box, opts, k, back, off: [unsubscribe fns]}

export function isOpen() { return !!cur; }

export function closeLightbox() {
  if (!cur) return false;
  const c = cur; cur = null;
  c.off.forEach(f => { try { f(); } catch (e) { /* */ } });
  c.el.remove();
  document.body.classList.remove("has-lightbox");
  if (c.back && c.back.isConnected) c.back.focus({ preventScroll: true });
  if (c.opts.onClose) c.opts.onClose();
  return true;
}

export function openLightbox(opts = {}) {
  closeLightbox();
  const items = opts.items || [];
  const el = document.createElement("div");
  el.className = "lbx" + (opts.live ? " is-live" : "");
  el.setAttribute("role", "dialog"); el.setAttribute("aria-modal", "true"); el.setAttribute("aria-labelledby", "lbxTitle");
  el.innerHTML = `
    <header class="lbx-head">
      <h2 id="lbxTitle">${esc(opts.title || "Picture")}</h2>
      <span class="lbx-count" aria-live="polite"></span>
      <div class="lbx-tools" role="group" aria-label="Zoom">
        <button type="button" class="lbx-btn" data-z="out" aria-label="Zoom out" title="Zoom out (-)">&minus;</button>
        <output class="lbx-pct" aria-live="polite">100%</output>
        <button type="button" class="lbx-btn" data-z="in" aria-label="Zoom in" title="Zoom in (+)">+</button>
        <button type="button" class="lbx-btn lbx-fit" data-z="fit" title="Fit (0)">Fit</button>
      </div>
      <button type="button" class="lbx-close" aria-label="Close the viewer (Esc)" title="Close (Esc)"><span aria-hidden="true">&times;</span> Close</button>
    </header>
    <div class="lbx-view" tabindex="0" aria-roledescription="zoomable view" aria-label="${esc(opts.live ? "The map, enlarged. Plus and minus zoom; drag to move." : "Plus and minus zoom; arrows move the picture.")}">
      <div class="lbx-canvas"></div>
    </div>
    <footer class="lbx-foot">
      <button type="button" class="lbx-btn lbx-page" data-p="-1" aria-label="Previous page">&lsaquo; Previous</button>
      <p class="lbx-cap"></p>
      <button type="button" class="lbx-btn lbx-page" data-p="1" aria-label="Next page">Next &rsaquo;</button>
    </footer>`;
  (opts.parent || document.body).append(el);
  document.body.classList.add("has-lightbox");
  const view = el.querySelector(".lbx-view"), canvas = el.querySelector(".lbx-canvas");
  const c = cur = { el, view, canvas, st: { s: 1, tx: 0, ty: 0 }, box: { w: 1, h: 1 }, aspect: opts.live ? opts.live.aspect || 4 / 3 : 4 / 3,
    opts, k: Math.max(0, Math.min(items.length - 1, opts.index | 0)), back: document.activeElement, off: [] };
  const vsize = () => ({ w: view.clientWidth || 1, h: view.clientHeight || 1 });
  const apply = () => {
    c.st = clampPan(c.st, vsize(), c.box);
    canvas.style.width = c.box.w + "px"; canvas.style.height = opts.live ? "" : c.box.h + "px";
    canvas.style.transform = `translate(${c.st.tx.toFixed(1)}px,${c.st.ty.toFixed(1)}px) scale(${c.st.s.toFixed(3)})`;
    el.querySelector(".lbx-pct").textContent = `${Math.round(c.st.s * 100)}%`;
    el.classList.toggle("is-zoomed", c.st.s > 1.01);
  };
  const fit = () => {
    const v = vsize();
    c.box = fitBox(v, c.aspect);
    if (opts.live) {   // the step draws its own caption under the map: fit the whole figure
      canvas.style.width = c.box.w + "px"; canvas.style.height = "";
      const h = canvas.scrollHeight || c.box.h;
      if (h > v.h) { const k = v.h / h; c.box = { w: Math.round(c.box.w * k), h: v.h }; canvas.style.width = c.box.w + "px"; }
      c.box.h = Math.min(v.h, canvas.scrollHeight || c.box.h);
    }
    c.st = { s: 1, tx: (v.w - c.box.w) / 2, ty: (v.h - c.box.h) / 2 };
    apply();
  };
  c.fit = fit;
  const zoom = (f, px, py) => { const v = vsize(); c.st = zoomAt(c.st, c.st.s * f, px ?? v.w / 2, py ?? v.h / 2); apply(); };
  const show = k => {
    if (opts.live) return;
    c.k = Math.max(0, Math.min(items.length - 1, k));
    const it = items[c.k] || {};
    canvas.innerHTML = `<img src="${esc(it.src)}" alt="${esc(it.alt || "")}" draggable="false">`;
    el.querySelector(".lbx-cap").innerHTML = `${esc(it.caption || it.alt || "")}${it.credit ? ` <small>${esc(it.credit)}</small>` : ""}`;
    el.querySelector(".lbx-count").textContent = items.length > 1 ? `Page ${c.k + 1} of ${items.length}` : "";
    el.querySelectorAll(".lbx-page").forEach(b => { b.hidden = items.length < 2; b.disabled = (+b.dataset.p < 0 && c.k === 0) || (+b.dataset.p > 0 && c.k === items.length - 1); });
    const img = canvas.querySelector("img");
    const ready = () => { if (img.naturalWidth) c.aspect = img.naturalWidth / img.naturalHeight; fit(); };
    if (img.complete && img.naturalWidth) ready(); else { img.onload = ready; fit(); }
  };
  const renderLive = () => {
    const had = canvas.contains(document.activeElement);
    opts.live.render(canvas);
    el.querySelector(".lbx-cap").textContent = opts.live.caption || "";
    if (had) { const f = canvas.querySelector("[tabindex='0'], button"); if (f) f.focus({ preventScroll: true }); }
  };
  if (opts.live) {
    el.querySelectorAll(".lbx-page").forEach(b => { b.hidden = true; });
    renderLive(); fit();
    const re = () => { if (cur === c) { renderLive(); apply(); } };
    addEventListener("outpost:step-render", re); c.off.push(() => removeEventListener("outpost:step-render", re));
  } else show(c.k);
  c.show = show;

  // buttons
  el.querySelector(".lbx-close").onclick = () => closeLightbox();
  el.querySelectorAll("[data-z]").forEach(b => b.onclick = () => (b.dataset.z === "fit" ? fit() : zoom(b.dataset.z === "in" ? 1.5 : 1 / 1.5)));
  el.querySelectorAll("[data-p]").forEach(b => b.onclick = () => show(c.k + +b.dataset.p));

  // pointer: drag pans, a short press is a tap (it reaches the live step), two fingers pinch
  const pts = new Map(); let drag = null, moved = false, pinch = null;
  const rel = e => { const r = view.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
  view.addEventListener("pointerdown", e => {
    if (e.button !== 0 && e.pointerType === "mouse") return;
    pts.set(e.pointerId, rel(e)); moved = false;
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), s: c.st.s }; drag = null; }
    else drag = { p: rel(e), tx: c.st.tx, ty: c.st.ty, id: e.pointerId };
  });
  view.addEventListener("pointermove", e => {
    if (!pts.has(e.pointerId)) return;
    const p = rel(e); pts.set(e.pointerId, p);
    if (pinch && pts.size === 2) {
      const [a, b] = [...pts.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
      c.st = zoomAt(c.st, pinch.s * d / (pinch.d || 1), (a.x + b.x) / 2, (a.y + b.y) / 2); moved = true; apply(); return;
    }
    if (!drag) return;
    const dx = p.x - drag.p.x, dy = p.y - drag.p.y;
    if (!moved && Math.hypot(dx, dy) < TAP_PX) return;
    if (!moved) { moved = true; try { view.setPointerCapture(e.pointerId); } catch (er) { /* */ } }
    c.st = { ...c.st, tx: drag.tx + dx, ty: drag.ty + dy }; apply();
  });
  const up = e => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (!pts.size) drag = null; };
  view.addEventListener("pointerup", up); view.addEventListener("pointercancel", up);
  // a drag never counts as a tap on the live map
  view.addEventListener("click", e => { if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; } }, true);
  view.addEventListener("wheel", e => { e.preventDefault(); const p = rel(e); zoom(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0025)), p.x, p.y); }, { passive: false });
  view.addEventListener("dblclick", e => { if (opts.live) return; const p = rel(e); if (c.st.s > 1.01) fit(); else zoom(2.5, p.x, p.y); });

  // keys (capture, before the app's TV-remote keys): Esc closes; zoom, pan and pages; Tab stays in the viewer
  const onKey = e => {
    if (cur !== c) return;
    const inLive = opts.live && canvas.contains(e.target) && e.target.closest(".ar-hill-img, [role=application], [role=slider]");
    const stop = () => { e.preventDefault(); e.stopImmediatePropagation(); };
    if (e.key === "Escape") { stop(); closeLightbox(); return; }
    if (e.key === "Tab") {
      const f = [...el.querySelectorAll("button:not([disabled]):not([hidden]), [tabindex='0'], a[href]")].filter(x => x.offsetParent);
      if (!f.length) return;
      const i = f.indexOf(document.activeElement), n = e.shiftKey ? (i <= 0 ? f.length - 1 : i - 1) : (i === f.length - 1 ? 0 : i + 1);
      stop(); f[n].focus(); return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "+" || e.key === "=") { stop(); zoom(1.5); return; }
    if (e.key === "-" || e.key === "_") { stop(); zoom(1 / 1.5); return; }
    if (e.key === "0") { stop(); fit(); return; }
    if (inLive) return;   // arrows and Enter move and tap the live map's crosshair (its own handler)
    if (e.key === "PageDown" || e.key === "PageUp") { stop(); show(c.k + (e.key === "PageDown" ? 1 : -1)); return; }
    const d = { ArrowLeft: [1, 0], ArrowRight: [-1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[e.key];
    if (d && (e.target === view || el.contains(e.target)) && !(e.target.closest && e.target.closest("button"))) {
      stop();
      if (c.st.s > 1.01) { c.st = { ...c.st, tx: c.st.tx + d[0] * 60, ty: c.st.ty + d[1] * 60 }; apply(); }
      else if (d[0]) show(c.k - d[0]);
    }
  };
  addEventListener("keydown", onKey, true); c.off.push(() => removeEventListener("keydown", onKey, true));
  // focus never wanders behind the viewer (the lesson card re-renders under it after an answer)
  const onFocus = e => { if (cur === c && !el.contains(e.target)) view.focus({ preventScroll: true }); };
  document.addEventListener("focusin", onFocus); c.off.push(() => document.removeEventListener("focusin", onFocus));
  const onResize = () => { if (cur === c) fit(); };
  addEventListener("resize", onResize); c.off.push(() => removeEventListener("resize", onResize));
  try { c.off.push(onIntent("back", () => (cur === c ? closeLightbox() : false), { priority: 40 }) || (() => {})); } catch (e) { /* tests */ }
  (opts.live ? (canvas.querySelector(".ar-hill-img") || view) : view).focus({ preventScroll: true });
  return c;
}

/** Tests and tools: what the viewer shows. */
export function lightboxState() {
  if (!cur) return null;
  const v = cur.view.getBoundingClientRect(), r = cur.canvas.getBoundingClientRect();
  return { open: true, title: cur.el.querySelector("#lbxTitle").textContent, live: !!cur.opts.live, page: cur.k, pages: (cur.opts.items || []).length,
    scale: +cur.st.s.toFixed(3), view: [Math.round(v.width), Math.round(v.height)], content: [Math.round(r.width), Math.round(r.height)],
    src: (cur.canvas.querySelector("img") || {}).src || null };
}

try { const O = (window.__outpost = window.__outpost || {}); O.lightbox = { open: openLightbox, close: closeLightbox, get state() { return lightboxState(); } }; } catch (e) { /* node tests */ }
