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

/** The 3D cabin's camera state: cockpit3d.js sets data-panel ("seat" or a panel id) on its host (the .c3-gl parent). */
export function cabinPanel() { const gl = document.querySelector(".c3-gl"); return gl && gl.parentElement ? gl.parentElement.dataset.panel || null : null; }

/**
 * deps: { nav(intent, arg, text) – the shell's own navigation (main.js shellNav), stopAll(), globe, inCabin(),
 *         mission – missionUI (its intent(name, arg) is the cabin's one path: look, highlight_panel, panel_open /
 *         panel_next / panel_prev, view_next / view_prev, confirm / cancel, and the router's nav intents),
 *         lookTarget(x, y) – the panel a head aim points at, a11y – the a11y module (help), ask(text) }
 */
export function installDefaultIntents({ nav, stopAll, globe, inCabin = () => false, mission = null, lookTarget = null, a11y = null, ask = null } = {}) {
  const offs = [];
  const on = (n, h) => offs.push(onIntent(n, h, { priority: 0 }));
  const cabin = (name, arg) => !!(inCabin() && mission && mission.intent && mission.intent(name, arg));
  const atSeat = () => { const p = cabinPanel(); return !p || p === "seat"; };

  on("stop", () => { stopAll(); if (globe && globe.halt) globe.halt(); return true; });

  // yes / no: the cabin's pending confirm, then a visible confirm (data-intent="yes|no", or a Yes / No card), then the offer
  const confirmBtn = kind => [...document.querySelectorAll(`[data-intent="${kind}"]`)].find(visible)
    || [...document.querySelectorAll("#card button, dialog[open] button, [role=dialog]:not([hidden]) button")]
      .find(b => visible(b) && b.textContent.trim().toLowerCase() === kind && !b.closest(".a11y-panel"));
  on("yes", () => { if (cabin("confirm")) return true; const b = confirmBtn("yes"); if (b) { b.click(); return true; } nav("accept_offer"); return true; });
  on("no", () => { if (cabin("cancel")) return true; const b = confirmBtn("no"); if (b) { b.click(); return true; } nav("decline_offer"); return true; });

  // next / prev in the cabin: an open panel steps to the neighbouring panel; at the seat, the window view steps
  on("next", () => (inCabin() ? cabin(atSeat() ? "view_next" : "panel_next") : false));   // not handled → shellNav("next")
  on("prev", () => (inCabin() ? cabin(atSeat() ? "view_prev" : "panel_prev") : false));   // elsewhere a screen decides

  on("select", a => tapAt(a.x, a.y));
  // fist + drag: the Moon turns; in the cabin it looks around (springs back to centre on release)
  const rot = { x: 0, y: 0 };
  on("rotate", a => {
    if (inCabin()) {
      if (a.phase === "move") { rot.x = Math.max(-1, Math.min(1, rot.x + a.dx * 4)); rot.y = Math.max(-1, Math.min(1, rot.y + a.dy * 4)); }
      if (a.phase === "end") rot.x = rot.y = 0;
      return cabin("look", { dx: rot.x, dy: rot.y });
    }
    if (globe && a.phase === "move") globe.rotateBy(a.dx, a.dy);
    return !!globe;
  });
  // head: look around, and light up the panel the head is aimed at (the one a lean opens)
  let lit = null;
  on("look", a => {
    if (!inCabin()) return false;
    cabin("look", { dx: a.x, dy: a.y });
    const t = atSeat() && lookTarget ? lookTarget(a.x, a.y) : null;
    if (t !== lit) { lit = t; cabin("highlight_panel", t); }
    return true;
  });
  on("panel_open", a => (inCabin() ? cabin("panel_open", a.panel || lit || "power") : false));
  on("panel_back", () => (inCabin() ? cabin("panel_back") : false));
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
