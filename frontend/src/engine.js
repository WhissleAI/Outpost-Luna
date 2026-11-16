// The local engine's state, as the desktop shell sees it (#87; desktop/main/main.js pushEngine): the shell supervises
// the model server ("the ear") and the backend, restarts a crashed one with a back-off, and calls
// window.__lunaEngine({ear, backend}) on every change (and after every page load). Each is
// "starting" | "ok" | "restarting" | "down" (the shell gave up). In a browser (make dev) nobody calls it: all "ok".
// What the page does with it: the voice bar shows "Ear restarting…" (.is-ear-restarting, styles.css) or "Voice off ·
// type" (.is-ear-down) while typing keeps working, and voice.js reconnects the mic as soon as the ear is back.

let state = { ear: "ok", backend: "ok" };
const subs = new Set();

export function engineState() { return state; }

/** fn(state, previous) on every change. Returns an unsubscribe function. */
export function onEngine(fn) { subs.add(fn); return () => subs.delete(fn); }

export function setEngine(next) {
  const prev = state;
  state = { ...state, ...(next && typeof next === "object" ? next : {}) };
  if (prev.ear === state.ear && prev.backend === state.backend) return;
  for (const fn of subs) { try { fn(state, prev); } catch (e) { console.warn("engine listener:", e); } }
}

/** The voice bar's classes for an engine state (only the ear matters: without the backend there is no page). */
export function askbarClasses(s = state) {
  return { "is-ear-restarting": s.ear === "restarting", "is-ear-down": s.ear === "down" };
}

/** The hint line under the voice bar while the ear is not there ("" when it is). */
export function earNote(s = state) {
  return s.ear === "restarting" ? "Ear restarting…" : s.ear === "down" ? "Voice is off. Type to ask." : "";
}

if (typeof window !== "undefined") window.__lunaEngine = setEngine;
