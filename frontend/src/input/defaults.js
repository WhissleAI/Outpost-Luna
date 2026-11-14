// The shell's default intent handlers (priority 0) and the keyboard source. Screens register their own handlers at
// priority 10 (input/intents.js) and win; these are the fallbacks that make every intent do something sensible on
// today's screens without the screen knowing which device sent it. docs/GESTURES.md §"The input bus".
import { onIntent, emitIntent } from "./intents.js";

const visible = el => !!(el && !el.hidden && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden");
const CLICKABLE = "button, a[href], [role=button], [role=option], [role=radio], input, select, label, summary, [tabindex]:not([tabindex='-1'])";
const OURS = ".gx-ui, .gx-cursor";   // the gesture layer's own overlay never receives a synthetic tap

/** What a tap at (x, y) would hit, ignoring the gesture overlay. */
export function hitAt(x, y) {
  const stack = document.elementsFromPoint ? document.elementsFromPoint(x, y) : [document.elementFromPoint(x, y)];
  return stack.find(e => e && !e.closest(OURS)) || null;
}

/** A synthetic tap: a control gets focus + click; a canvas (the Moon) gets the pointerdown / up it listens for. */
export function tapAt(x, y) {
  const el = hitAt(x, y); if (!el) return false;
  if (el.tagName === "CANVAS") {
    const o = { clientX: x, clientY: y, bubbles: true, pointerId: 77, pointerType: "touch", isPrimary: true };
    el.dispatchEvent(new PointerEvent("pointerdown", o)); el.dispatchEvent(new PointerEvent("pointerup", o));
    return true;
  }
  const c = el.closest(CLICKABLE);
  if (!c || c.disabled) return false;
  if (c.focus) c.focus({ preventScroll: true });
  if (c.tagName === "INPUT" && /^(text|search|email|number)$/.test(c.type)) return true;   // focus a field, don't click it
  c.click();
  return true;
}

/** Cycle the pressed button of a segmented group (aria-pressed / aria-selected) by `dir`. True when it moved. */
export function cycleGroup(buttons, dir) {
  const b = [...buttons].filter(visible); if (b.length < 2) return false;
  const i = b.findIndex(x => x.getAttribute("aria-pressed") === "true" || x.getAttribute("aria-selected") === "true");
  const n = b[((i < 0 ? 0 : i + dir) % b.length + b.length) % b.length];
  n.click(); return true;
}

// The 3D cabin (feat/ux-mission cockpit3d.js) parallaxes on pointermove over its host; until it exposes look(x, y),
// head-look drives it the same way: a synthetic pointermove at the matching spot.
function cabinHost() { return document.querySelector("[data-panel] .c3-css")?.parentElement || document.querySelector("[data-panel]"); }
function lookAt(x, y) {
  const h = cabinHost(); if (!h) return false;
  const r = h.getBoundingClientRect();
  h.dispatchEvent(new PointerEvent("pointermove", { clientX: r.left + (x * 0.5 + 0.5) * r.width, clientY: r.top + (y * 0.5 + 0.5) * r.height, bubbles: true }));
  return true;
}
const CABIN_PANELS = ["habitat", "power", "comm"];

/**
 * deps: { nav(intent, arg, text) – the shell's own navigation (main.js shellNav), stopAll(), globe, inCabin(),
 *         a11y – the a11y module (help), ask(text) – a turn through the normal path }
 */
export function installDefaultIntents({ nav, stopAll, globe, inCabin = () => false, a11y = null, ask = null } = {}) {
  const offs = [];
  const on = (n, h) => offs.push(onIntent(n, h, { priority: 0 }));
  const panel = () => (cabinHost() && cabinHost().dataset.panel) || (document.querySelector("[data-panel]") || {}).dataset?.panel || null;

  on("stop", () => { stopAll(); if (globe && globe.halt) globe.halt(); return true; });

  // yes / no: a visible confirm (data-intent="yes|no", or the mission confirm card) first, then the current offer
  const confirmBtn = kind => [...document.querySelectorAll(`[data-intent="${kind}"]`)].find(visible)
    // the mission's confirm card (askConfirm) is the answer card with "Yes" / "No" actions
    || [...document.querySelectorAll("#card button, dialog[open] button, [role=dialog]:not([hidden]) button")]
      .find(b => visible(b) && b.textContent.trim().toLowerCase() === kind && !b.closest(".a11y-panel"));
  on("yes", () => { const b = confirmBtn("yes"); if (b) { b.click(); return true; } nav("accept_offer"); return true; });
  on("no", () => { const b = confirmBtn("no"); if (b) { b.click(); return true; } nav("decline_offer"); return true; });

  // next / prev in the cabin: an open panel steps to the neighbouring panel; at the seat, the window view steps
  const cabinStep = dir => {
    if (!inCabin()) return false;
    const p = panel();
    if (p && p !== "seat" && CABIN_PANELS.includes(p)) { const i = CABIN_PANELS.indexOf(p); nav("panel_" + CABIN_PANELS[(i + dir + 3) % 3]); return true; }
    return cycleGroup(document.querySelectorAll(".cb-view, [data-view-btn]"), dir);
  };
  on("next", () => cabinStep(1));        // not handled → the shell's nav("next") (wildcard, below)
  on("prev", () => cabinStep(-1));       // elsewhere a screen handler decides (lesson step back, map pin, …)

  on("select", a => tapAt(a.x, a.y));
  on("rotate", a => {
    if (inCabin()) { if (a.phase === "move") { rot.x = Math.max(-1, Math.min(1, rot.x + a.dx * 4)); rot.y = Math.max(-1, Math.min(1, rot.y + a.dy * 4)); lookAt(rot.x, rot.y); } if (a.phase === "end") { rot.x = rot.y = 0; } return true; }
    if (globe && a.phase === "move") globe.rotateBy(a.dx, a.dy);
    return !!globe;
  });
  const rot = { x: 0, y: 0 };
  on("look", a => inCabin() && lookAt(a.x, a.y));
  on("panel_open", a => { if (!inCabin()) return false; nav("panel_" + (a.panel || "power")); return true; });
  on("zoom", a => { if (globe && globe.zoomBy) { globe.zoomBy(a.factor); return true; } return false; });
  on("call_houston", () => { if (inCabin() && ask) { ask("call Houston"); return true; } return false; });
  on("help", () => { if (a11y) { a11y.handleText("what can I do"); return true; } return false; });

  // The shell's navigation is the last resort for every router intent (voice decisions arrive here too).
  offs.push(onIntent("*", (a, ev) => {
    if (!ROUTER_INTENTS.has(ev.name)) return false;
    nav(ev.name, a.arg, a.text);
    return true;
  }, { priority: -10 }));

  return () => offs.forEach(f => f());
}

/** Intents the shell's nav() understands (the hands-free router's nav vocabulary). */
export const ROUTER_INTENTS = new Set(["next", "back", "start", "accept_offer", "decline_offer", "repeat", "slower", "faster", "settings",
  "a11y", "answer", "academy", "library", "go_mission", "lesson", "map", "take_command", "pick_site", "debrief", "fly_again",
  "new_site", "view_orbit", "view_site", "view_rover", "view_earth", "panel_power", "panel_comm", "panel_habitat", "panel_rover",
  "panel_radiation", "panel_back", "repeat_step", "end_shift"]);

/** Keyboard source: Alt+→ / Alt+← next / previous, Alt+Y / Alt+N yes / no, Alt+. stop. Never while typing in a field. */
export function installKeyboardIntents() {
  const h = e => {
    if (!e.altKey || e.ctrlKey || e.metaKey) return;
    const t = e.target; if (t && t.closest && t.closest("input, textarea, select, [contenteditable=true]")) return;
    const name = { ArrowRight: "next", ArrowLeft: "prev", KeyY: "yes", KeyN: "no", Period: "stop" }[e.code];
    if (!name) return;
    e.preventDefault(); emitIntent(name, {}, "keyboard");
  };
  addEventListener("keydown", h);
  return () => removeEventListener("keydown", h);
}
