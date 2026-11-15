// Multi-step flows (the Library tour, the cabin tour, a crew clip, a paused mission clock, the paused debrief): one place
// that knows what is running, why it paused, and how to resume it, for every device (docs/FLOWS.md).
//
// Owner bug (fix/flow-resume): the Library tour "got stopped in between and then saying continue also didn't work".
// Any stop ended the tour for good (the card said "Tour stopped" with no way back), and the router had no "continue"
// for the Library. Now a stop is a PAUSE with a reason, a Resume button (focused), Previous / Next and Close, and
// "continue", a thumbs up, Enter or Space (on the focused Resume) bring it back.
//
//   registerFlow({ name, active(), paused(), pause(src), resume(src), next?(src), prev?(src), repeat?(src), close?(src),
//                  keys: true })          → a flow; the first active one (registration rank order) gets the intents
//   flowLog({ flow, event, source, ... })  → window.__outpost.flowLog (every pause / resume / step / close and WHY)
//   flowFrame()                            → { flow, flow_state } for the router's screen frame (turn_router Ctx.flow)
//
// Intents (input/intents.js, priority 30, above the screens): stop (open hand, Alt+.) pauses; the router's `pause`
// ("stop", "wait", "hold on") pauses; `resume` ("continue", "keep going", "go on") resumes; yes / start / accept_offer
// resume a PAUSED flow (a thumbs up); next / prev / back step; repeat re-speaks the stop. Left / right arrows step a
// flow that has steps (keys: true); Enter with nothing focused resumes. Esc pauses a running flow; on a paused one it
// is the keyboard's usual back (keys.js), which closes the card.
import { onIntent } from "./input/intents.js";

/** Why a flow paused, as the caption under it ("Paused: you said stop"). Copy: short, kid words, no blame. */
export const PAUSE_WHY = Object.freeze({
  voice: "you said stop", gesture: "hand signal", barge: "you started talking", keyboard: "key press", gamepad: "controller",
  tap: "you tapped something", question: "you asked something", video: "a video is playing", crew: "the crew is talking",
  button: "you pressed Pause", router: "you asked something", timer: "time ran out", error: "something went wrong",
});
export const pauseCaption = source => `Paused: ${PAUSE_WHY[source] || "stopped"}`;

const LOG_MAX = 200;
const log = [];
/** Record a flow event. Never holds camera frames, audio or kid text: names, sources, steps and times only. */
export function flowLog(e) {
  const entry = { t: Math.round(typeof performance !== "undefined" ? performance.now() : Date.now()), ...e };
  log.push(entry); if (log.length > LOG_MAX) log.shift();
  return entry;
}
export const flowEvents = () => log.map(e => ({ ...e }));

const flows = [];
const safe = (f, d = false) => { try { return f ? !!f() : d; } catch (e) { return d; } };
/** Register a flow; returns an unregister function. Lower rank wins when two are active (default 50). */
export function registerFlow(def) {
  const f = { rank: 50, keys: true, ...def };
  flows.push(f); flows.sort((a, b) => a.rank - b.rank);
  return () => { const i = flows.indexOf(f); if (i >= 0) flows.splice(i, 1); };
}
export function currentFlow() { return flows.find(f => safe(f.active)) || null; }
export const isPaused = f => !!(f && safe(f.paused));
/** A real control has keyboard focus (then arrows and Enter belong to it, not to the flow). */
export function focusedControl(doc = typeof document !== "undefined" ? document : null) {
  const el = doc && doc.activeElement;
  return !!(el && el !== doc.body && el.matches && el.matches("button, a[href], input, select, [role=button]"));
}
/** The router's view of the flow on screen: running / paused, or nothing. */
export function flowFrame() {
  const f = currentFlow();
  return f ? { flow: f.name, flow_state: isPaused(f) ? "paused" : "running" } : {};
}

// The router's flow phrases (backend/app/turn_router.py FLOW_NAV), for the no-session path (POST /api/ask): the same
// words reach a flow with or without the socket.
const W = t => String(t || "").toLowerCase().replace(/[’']/g, " ").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim()
  .replace(/^(?:(?:okay|ok|please|um|uh|so|hey|capcom) )+/, "").replace(/(?: (?:please|now|capcom))+$/, "");
export const FLOW_WORDS = Object.freeze([
  ["resume", /^(?:continue|resume|keep going|go on|carry on|unpause|play|keep playing|go ahead|start again|(?:continue|resume|restart) (?:the )?(?:tour|clip|story|mission|video))$/],
  ["pause", /^(?:stop|stop it|stop talking|pause|pause it|wait|wait a (?:sec|second|minute)|hold on|hang on|one sec|one second|(?:stop|pause) (?:the )?(?:tour|clip|story))$/],
  ["repeat", /^(?:again|repeat|repeat that|say (?:that|it) again|one more time)$/],
  ["next", /^(?:next|next one|next stop|skip|skip it)$/],
  ["back", /^(?:back|go back|previous|previous one|previous stop|last one)$/],
]);
/** "Keep going, please." → "resume" while a flow is on screen; else null. */
export function flowWord(text) {
  if (!currentFlow()) return null;
  const q = W(text), hit = FLOW_WORDS.find(([, rx]) => rx.test(q));
  return hit ? hit[0] : null;
}

/** Run one flow action and log it. Returns true when the flow took it. */
function run(f, action, source, extra) {
  const fn = f && f[action];
  if (typeof fn !== "function") return false;
  let r;
  try { r = fn(source, extra); } catch (e) { console.error(`[flows] ${f.name}.${action} failed`, e); return false; }
  if (r === false) return false;
  return true;
}

/** The intent handlers (once). Every handler passes (false) when no flow is active, so the screens behave as before. */
let installed = false;
export function installFlowIntents() {
  if (installed) return; installed = true;
  const P = { priority: 30 };
  const on = (name, fn) => onIntent(name, (a, ev) => { const f = currentFlow(); return f ? fn(f, a || {}, ev || {}) === true : false; }, P);
  // open hand / Alt+. / the router's pause: a running flow pauses (and the intent is consumed: the shell's stopAll would
  // end it); a paused one stays paused (a second open hand never closes it)
  const pause = (f, ev) => (isPaused(f) ? true : run(f, "pause", ev.source === "voice" ? "voice" : ev.source || "gesture"));
  on("stop", (f, a, ev) => (isPaused(f) ? false : pause(f, ev)));   // already paused: the shell's stop still hushes speech
  on("pause", (f, a, ev) => pause(f, ev));
  on("resume", (f, a, ev) => (isPaused(f) ? run(f, "resume", ev.source || "voice") : true));   // running: nothing to do
  for (const n of ["yes", "start", "accept_offer"]) on(n, (f, a, ev) => (isPaused(f) ? run(f, "resume", ev.source || "voice") : false));
  on("next", (f, a, ev) => run(f, "next", ev.source || "voice"));
  on("prev", (f, a, ev) => run(f, "prev", ev.source || "voice"));
  // "go back" / "previous" by voice steps back. Esc / Backspace (keyboard "back", controller B): the first press pauses
  // a running flow, the next one is the keys' own back (closes the card / skips the tour)
  on("back", (f, a, ev) => (["keyboard", "gamepad"].includes(ev.source) ? (isPaused(f) ? false : pause(f, ev)) : run(f, "prev", ev.source || "voice")));
  on("repeat", (f, a, ev) => run(f, "repeat", ev.source || "voice"));
  // keys: left / right step a flow with steps; Enter with nothing focused resumes a paused one
  on("move", (f, a, ev) => {
    if (!f.keys || !["keyboard", "gamepad"].includes(ev.source)) return false;
    if (a.dir !== "left" && a.dir !== "right") return false;
    // with a control focused (Resume, Next, ×, a chip…) the arrows move focus like everywhere else, so a paused card never
    // traps it: they can leave to the top bar. With nothing focused they step the flow (the card's own buttons still do).
    if (focusedControl()) return false;
    return run(f, a.dir === "right" ? "next" : "prev", ev.source);
  });
  on("select", (f, a, ev) => {
    if (a.x != null || !isPaused(f) || !["keyboard", "gamepad"].includes(ev.source)) return false;
    if (focusedControl()) return false;   // the focused control
    return run(f, "resume", ev.source);
  });
}

if (typeof window !== "undefined") {
  window.__outpost = window.__outpost || {};
  Object.assign(window.__outpost, { flowLog: log, flows: { current: () => { const f = currentFlow(); return f ? { name: f.name, paused: isPaused(f) } : null; }, frame: flowFrame, events: flowEvents } });
}
