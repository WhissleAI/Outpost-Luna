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
  return s.ear === "restarting" ? "Ear restarting…" : s.ear === "down" ? "Voice is off. Type to ask." : earFail ? VOICE_FIX : "";
}

// ---- [0.3.12] "Starting voice…" only while the ear is really starting ----
// The audit's P0: with the ear already failed, the bar said "Starting voice…" for up to 3 minutes. Now the bar turns to
// "Voice off · type" (grey mic, VOICE_FIX in the hint slot) the moment /api/health reports the ear's load error, or on
// the ear's first {"t":"error"} (voice.js). A later good start clears it.
export const WARM_MS = 180000;
/** The one how-to-fix line while the voice is off (docs/COPY.md: 12 words or fewer, no example commands). */
export const VOICE_FIX = "Voice didn't load. Restart the app.";
let earFail = false;
const failSubs = new Set();
/** The ear failed (true) or came back (false); fn(on) for the voice bar. */
export function setEarFailed(on) {
  on = !!on; if (on === earFail) return; earFail = on;
  for (const fn of failSubs) { try { fn(on); } catch (e) { console.warn("ear-fail listener:", e); } }
}
export function earFailed() { return earFail; }
export function onEarFailed(fn) { failSubs.add(fn); return () => failSubs.delete(fn); }

/** Is an ear {"t":"error"} message (backend listen.py) a dead ear, not a blip? A failed or disabled local ear with no
 *  fallback, or a missing / unreachable Deepgram, is dead; the model server still starting ("unreachable", no
 *  handshake), a full session pool, a reload after a hung decode or a dropped stream ("closed") reconnect by themselves. */
export function earErrorIsFatal(message) {
  const m = String(message || "");
  if (/unreachable|handshake|MAX_SESSIONS|reloading|closed/i.test(m)) return false;
  return /unavailable|not set|could not reach|deepgram:/i.test(m);
}

/** /api/health + time since the page started waiting -> "ready" | "warming" | "off". "off" at once when the local ear
 *  reports a load error and nothing falls back to it (no Deepgram key); a reload after a hung decode is still warming. */
export function warmState(h, elapsedMs = 0) {
  const ms = (h && h.model_server) || {}, m = ms.models || {}, ear = m.arc_ear || {}, tts = m.tts || {};
  const route = (h && h.voice) || {}, cloud = route.ear === "deepgram" || !!route.fallback;
  const earUp = ear.decoder_loaded !== false || cloud;
  if (ms.ok && earUp && tts.loaded !== false) return "ready";
  const failed = !cloud && ear.available === false && !!ear.error && !/reloading/i.test(String(ear.error));
  if (failed) return "off";
  return elapsedMs >= WARM_MS ? "off" : "warming";
}

if (typeof window !== "undefined") window.__lunaEngine = setEngine;
