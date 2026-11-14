// The voice bar (#askbar) floats: drag its grip (pointer, touch or keyboard) and it snaps to one of six anchors
// (top/bottom × left/centre/right) inside the stage, never off screen and never under the top bar. The anchor is
// remembered per screen class ("moon" = every screen over the globe, "cabin" = the Mission cabin, where the bar sits in
// the panel's comm row unless the cadet moved it). If the bar would cover a lesson card, the Next-up card, the primary
// action or a dialog, it moves to the nearest free anchor. The caption inside it renders on the side away from the edge.
// Commands (typed, or routed by voice): "move the voice bar to the top / bottom / left / right / top right…",
// "reset the voice bar".

export const ANCHORS = ["tl", "tc", "tr", "bl", "bc", "br"];
const NAME = { tl: "top left", tc: "top", tr: "top right", bl: "bottom left", bc: "bottom", br: "bottom right" };
const KEY = "outpost-voicebar";
const DEFAULT = { moon: "bc", cabin: null };   // cabin: null = docked in the comm row

/** "move the voice bar to the top right" → {cmd: "move", anchor: "tr"}; "reset the voice bar" → {cmd: "reset"}. */
export function parseBarCommand(text, current = "bc") {
  const t = String(text || "").toLowerCase().replace(/[^a-z ]/g, " ").replace(/\s+/g, " ").trim();
  if (/^(reset|restore) (the )?(voice|mic|talk) ?bar( position)?$/.test(t)) return { cmd: "reset" };
  const m = t.match(/^(?:move|put|drag|send) (?:the )?(?:voice|mic|talk) ?bar (?:to |on |onto )?(?:the )?(top|bottom|up|down|left|right|middle|centre|center)(?: (left|right|middle|centre|center))?$/);
  if (!m) return null;
  let [v, h] = [current[0], current[1]];
  [m[1], m[2]].filter(Boolean).forEach(w => {
    if (w === "top" || w === "up") v = "t"; else if (w === "bottom" || w === "down") v = "b";
    else if (w === "left") h = "l"; else if (w === "right") h = "r"; else h = "c";
  });
  if (m[1] === "top" || m[1] === "bottom" || m[1] === "up" || m[1] === "down") { if (!m[2]) h = "c"; }
  return { cmd: "move", anchor: v + h };
}

function load() { try { return { ...DEFAULT, ...(JSON.parse(localStorage.getItem(KEY) || "null") || {}) }; } catch (e) { return { ...DEFAULT }; } }
function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* private mode: this visit only */ } }

export function initVoiceBar({ announce = () => {} } = {}) {
  const bar = document.getElementById("askbar"), stage = document.getElementById("stage"), grip = document.getElementById("vsGrip");
  if (!bar || !stage || !grip) return null;
  let saved = load(), anchor = null, free = null;
  const extra = new Set();   // more things the bar must not cover (e.g. the gesture self-view): addObstacle(selector)   // free = {x, y} while dragging / nudging
  const M = 16;                                       // margin from the stage edge (--gut)
  const reduced = () => document.documentElement.dataset.motion === "reduce" || !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  const klass = () => (document.body.dataset.cabin === "1" ? "cabin" : "moon");
  const docked = () => !!bar.closest("#cbAskSlot");

  /** Top-left (px, stage coordinates) of an anchor for the bar's current size. */
  // real (on-screen) size, and the CSS zoom of Settings → Text size (left/top on a zoomed element are zoomed too)
  const bw = () => bar.getBoundingClientRect().width, bh = () => bar.getBoundingClientRect().height;
  const zoom = () => { const z = parseFloat(getComputedStyle(bar).zoom); return z > 0 ? z : 1; };
  function spot(a) {
    const W = stage.clientWidth, H = stage.clientHeight, w = bw(), h = bh();
    const x = a[1] === "l" ? M : a[1] === "r" ? W - w - M : (W - w) / 2, y = a[0] === "t" ? M : H - h - M;
    return { x: Math.max(M, Math.min(W - w - M, x)), y: Math.max(M, Math.min(H - h - M, y)) };
  }
  function place(x, y, animate) {
    bar.classList.toggle("is-snapping", !!animate && !reduced());
    const z = zoom(); bar.style.left = Math.round(x / z) + "px"; bar.style.top = Math.round(y / z) + "px";
  }
  /** What the bar must not cover on this screen. */
  function obstacles(a) {
    const sel = ["#aPanel.is-lesson", "#aPanel.is-ride", "#aPanel.is-badge", ".mp-card", "#mPanel:not([hidden])", "#mDebrief:not([hidden])",
      "#card:not([hidden])", ".h-form", ".mp-credit", ".h-credit", ".mp-top", ".m-debrief:not([hidden])"];
    // a lesson / ride card already keeps clear of a bar at the bottom (its max-height uses --strip-h): only a top anchor can collide
    const list = a && a[0] === "b" ? sel.filter(s => !/is-lesson|is-ride|mp-card/.test(s)) : sel;
    return list.concat([...extra]).flatMap(s => [...document.querySelectorAll(s)]).filter(e => !e.hidden && e.getClientRects().length).map(e => e.getBoundingClientRect());
  }
  const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  function covers(a) {
    const s = stage.getBoundingClientRect(), p = spot(a), r = { left: s.left + p.x, top: s.top + p.y, right: s.left + p.x + bw(), bottom: s.top + p.y + bh() };
    return obstacles(a).some(o => overlaps(r, o));
  }
  /** The anchor nearest to `want` that covers nothing (or `want` itself when everything is covered). */
  function free_(want) {
    if (!covers(want)) return want;
    const w = spot(want);
    return ANCHORS.filter(a => a !== want && !covers(a)).sort((a, b) => { const p = spot(a), q = spot(b); return Math.hypot(p.x - w.x, p.y - w.y) - Math.hypot(q.x - w.x, q.y - w.y); })[0] || want;
  }
  function apply(a, { animate = false, say = false, remember = false } = {}) {
    if (docked()) return;
    const want = a || "bc", got = free_(want);
    anchor = got; free = null; stage.dataset.vbar = got;
    bar.dataset.anchor = got; stage.dataset.vbar = got; bar.classList.add("is-floating");
    const p = spot(got); place(p.x, p.y, animate);
    if (remember) { saved[klass()] = want; save(saved); }
    if (say) announce(`Voice bar moved to ${NAME[got]}.`);
    dispatchEvent(new CustomEvent("outpost:voicebar", { detail: { anchor: got, rect: bar.getBoundingClientRect() } }));   // e.g. the self-view picks another anchor
  }
  function nearest(x, y) {
    const cx = x + bw() / 2, cy = y + bh() / 2;
    return ANCHORS.map(a => { const p = spot(a); return [a, Math.hypot(p.x + bw() / 2 - cx, p.y + bh() / 2 - cy)]; }).sort((p, q) => p[1] - q[1])[0][0];
  }
  // ---- cabin: docked in the comm row by default; moving it lifts it out onto the stage ----
  function undock() { if (docked()) stage.append(bar); }
  function redock() { const slot = document.getElementById("cbAskSlot"); if (slot) { bar.classList.remove("is-floating", "is-snapping"); bar.style.left = bar.style.top = ""; delete bar.dataset.anchor; delete stage.dataset.vbar; slot.append(bar); } }
  function sync() {
    if (klass() === "cabin") { if (saved.cabin) { undock(); apply(saved.cabin); } return; }
    apply(saved.moon);
  }

  // ---- pointer + touch drag (from the grip only) ----
  let drag = null;
  grip.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    e.preventDefault(); undock();
    const s = stage.getBoundingClientRect(), r = bar.getBoundingClientRect();
    drag = { dx: e.clientX - r.left, dy: e.clientY - r.top, s }; grip.setPointerCapture(e.pointerId);
    bar.classList.add("is-dragging"); bar.classList.add("is-floating"); place(r.left - s.left, r.top - s.top, false);
  });
  grip.addEventListener("pointermove", e => {
    if (!drag) return;
    const W = stage.clientWidth, H = stage.clientHeight;
    const x = Math.max(M, Math.min(W - bw() - M, e.clientX - drag.s.left - drag.dx)), y = Math.max(M, Math.min(H - bh() - M, e.clientY - drag.s.top - drag.dy));
    free = { x, y }; place(x, y, false);
  });
  const end = () => { if (!drag) return; drag = null; bar.classList.remove("is-dragging"); if (free) apply(nearest(free.x, free.y), { animate: true, say: true, remember: true }); };
  grip.addEventListener("pointerup", end); grip.addEventListener("pointercancel", end);
  grip.addEventListener("dblclick", () => reset());
  // ---- keyboard: arrows nudge by 12 px (Shift: 48); Enter or leaving the grip snaps ----
  grip.addEventListener("keydown", e => {
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (d) {
      e.preventDefault(); e.stopPropagation(); undock();
      const step = e.shiftKey ? 48 : 12, cur = free || spot(anchor || "bc"), W = stage.clientWidth, H = stage.clientHeight;
      free = { x: Math.max(M, Math.min(W - bw() - M, cur.x + d[0] * step)), y: Math.max(M, Math.min(H - bh() - M, cur.y + d[1] * step)) };
      bar.classList.add("is-floating"); place(free.x, free.y, false); return;
    }
    if ((e.key === "Enter" || e.key === "Escape") && free) { e.preventDefault(); apply(nearest(free.x, free.y), { animate: true, say: true, remember: true }); }
  });
  grip.addEventListener("blur", () => { if (free && !drag) apply(nearest(free.x, free.y), { animate: true, say: true, remember: true }); });

  function moveTo(a) { undock(); apply(a, { animate: true, say: true, remember: true }); }
  function reset() {
    saved[klass()] = DEFAULT[klass()]; save(saved);
    if (klass() === "cabin" && !DEFAULT.cabin) { redock(); announce("Voice bar back in the comm row."); return; }
    apply(DEFAULT.moon, { animate: true }); announce("Voice bar back at the bottom.");
  }
  /** A typed or spoken bar command. True when it was one. */
  function handleText(text) {
    const c = parseBarCommand(text, anchor || "bc"); if (!c) return false;
    if (c.cmd === "reset") reset(); else moveTo(c.anchor);
    return true;
  }

  // re-clamp on resize, re-check obstacles when the screen changes, follow the cabin in and out
  // the stage resizing, or the bar itself growing (the caption comes and goes): keep the anchor's edge where it was
  const ro = new ResizeObserver(() => { if (!drag && !docked() && !free && anchor) { const p = spot(anchor); place(p.x, p.y, false); } });
  ro.observe(stage); ro.observe(bar);
  let raf = 0; const recheck = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => { if (!drag && !free && !docked()) apply(saved[klass()] || anchor || "bc"); }); };
  ["aPanel", "mPanel", "mDebrief", "card"].forEach(id => { const el = document.getElementById(id); if (el) new MutationObserver(recheck).observe(el, { attributes: true, attributeFilter: ["hidden", "class"], childList: true }); });
  new MutationObserver(() => setTimeout(sync, 60)).observe(document.body, { attributes: true, attributeFilter: ["data-cabin"] });
  requestAnimationFrame(sync);

  const api = { moveTo, reset, handleText, get anchor() { return anchor; }, get rect() { return bar.getBoundingClientRect(); },
    /** Other floating things (the gesture self-view, the hint chip) register so the bar keeps clear of them. */
    addObstacle(sel) { extra.add(sel); recheck(); }, removeObstacle(sel) { extra.delete(sel); recheck(); }, ANCHORS, spot };
  (window.__outpost = window.__outpost || {}).voiceBar = api;
  return api;
}
