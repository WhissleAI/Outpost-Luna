// One input layer for every device (docs/GESTURES.md §"The input bus").
//
// Voice (the router's nav decisions), tap / pointer, keyboard and camera gestures all emit the SAME intents onto this
// bus. Screens subscribe by intent, never by device:
//
//   import { onIntent, emitIntent } from "./input/intents.js";
//   const off = onIntent("next", (args, ev) => { if (!myScreenIsUp) return false; goNext(); return true; }, { priority: 10 });
//   emitIntent("next", {}, "gesture");          // → true when a handler consumed it
//
// Dispatch: handlers run highest `priority` first (ties: the most recently registered first). A handler that returns
// true (or a promise of true) consumes the intent and the rest are skipped; false / undefined passes it on. Screen
// handlers use priority 10, the shell's defaults priority 0, so a screen always gets first say and the shell is the
// fallback. `onIntent("*", h)` sees every intent (h gets (args, ev) with ev.name).
//
// Privacy: the bus carries intents only. Never put camera frames, landmarks or audio on it; the log below keeps the
// last discrete intents (name, source, time) for "what just happened" debugging and the tests.

/** The intent vocabulary. Nav names match the hands-free router (backend/app/turn_router.py) so a voice decision and a
 *  gesture are the same event. Gesture-born intents are listed with the gesture that makes them (docs/GESTURES.md). */
export const INTENTS = Object.freeze({
  // shared with the router
  next: "next step / lesson / panel / view / pin",
  back: "back (the router's 'go back')",
  start: "start", accept_offer: "yes to the current offer", decline_offer: "no to the current offer",
  repeat: "say that again", settings: "open settings", a11y: "an accessibility command (text)",
  map: "the course map", lesson: "open lesson (arg)", academy: "Flight School", library: "the Library", go_mission: "Mission",
  take_command: "start the shift", pick_site: "pick a landing site (arg)",
  site_layer: "navigator: a map layer (arg: sunlight|slope|ice|earth|off)", site_query: "navigator: which site wins (arg: ice|sunlight|earth|slope|best)",
  site_preset: "navigator: weigh the criteria (arg: balanced|power_first|ice_first|comms_first|safety_first)", debrief: "the debrief", fly_again: "fly again",
  new_site: "another site", view_orbit: "window: ORBIT", view_site: "window: SITE", view_rover: "window: ROVER", view_earth: "window: EARTH",
  panel_power: "cabin: power panel", panel_comm: "cabin: comm panel", panel_habitat: "cabin: habitat panel",
  panel_rover: "cabin: rover panel", panel_radiation: "cabin: radiation panel", panel_back: "cabin: back to the seat",
  answer: "the current step's answer (text)", end_shift: "end the shift (early, on the live clock)",
  // the live mission clock and the Now task card (docs/GAMEPLAY.md)
  skip_event: "skip to the next event (E)", time_pause: "pause the mission clock", time_resume: "run the mission clock",
  time_warp: "time warp {warp?: 1|2|4}; none = the next speed (W)", time_toggle: "pause / run the mission clock (K)",
  pause_menu: "the cabin's pause menu: resume, time speed, restart shift, settings, quit to hub (Esc at the seat, Start, voice 'pause')",
  time_ff: "hold to fast-forward {on: true|false} (hold F, hold Skip ahead, hold RT)",
  task_step: "do the Now card's step (T)", why: "the cabin's \"Why?\" card for a gauge {arg?: power|battery|life_support|dose|heaters|shields|rover} (I, voice 'why is power low?')", task_choice: "pick a choice on the Now card (arg: its label)",
  recenter: "cabin: Center view, the seat pose (R, voice 'center'; a gesture may emit it)",
  mute: "sound on / off: the top bar's Mute (Shift+M)", mute_sound: "sound off (voice: mute)", unmute_sound: "sound on (voice: unmute)",
  skip_tour: "end the cabin tour", cabin_tour: "replay the cabin tour ('show me around')",
  // device-neutral intents that gestures (and keys) make
  stop: "stop / pause: interrupts speech and motion (open palm)",
  yes: "yes / confirm (thumbs up)", no: "no / cancel (thumbs down)",
  prev: "previous step / panel / view / pin (swipe right)",
  point: "a hover cursor at {x, y} in CSS px (index finger)", select: "select what is at {x, y} (point + dwell)",
  rotate: "drag-rotate {dx, dy, phase}: the surface follows (a drag)", look: "look around {x, y} in -1..1 (head pose)",
  spin: "steer the view at a rate {phase: start|move|end, x, y} in -1..1: the Moon spins that way; the cabin looks (fist, right stick). Never zooms",
  panel_open: "open the highlighted / looked-at panel {panel?} (lean in)",
  zoom: "zoom by {factor} (phase 2: two-hand pinch)",
  zoom_rate: "zoom at a rate {phase: start|move|end, rate: -1..1, + = closer, tap?} (pinch and slide, held +/- keys, controller triggers)",
  zoom_in: "zoom a step closer (voice: 'zoom in', 'closer')", zoom_out: "zoom a step farther (voice: 'zoom out', 'farther')", call_houston: "call Houston (voice; the cabin asks Houston)",
  help: "what can I do? (keys / controller: the help sheet of every key)",
  // [keys] the keyboard as a TV remote and game controllers (docs/KEYBOARD.md)
  move: "spatial focus {dir: left|right|up|down, shift?} (arrows, D-pad, left stick)",
  mic: "mic on / off (M, controller X)", captions: "captions on / off (C)", focus_input: "focus the text box (/)",
  pick: "pick answer / option {n} (1–4, A–D)", view_next: "cabin window view: next (V)", view_prev: "cabin window view: previous",
});

/** Continuous intents: delivered like the others but kept out of the log (they fire at frame rate). */
export const CONTINUOUS = new Set(["point", "rotate", "spin", "look", "zoom", "zoom_rate"]);
export const SOURCES = ["voice", "tap", "keyboard", "gesture", "gamepad", "typed", "system"];

export function createIntentBus({ logSize = 50, now = () => Date.now() } = {}) {
  const handlers = new Map();   // name → [{fn, priority, seq}]
  let seq = 0;
  const log = [];

  function onIntent(name, fn, { priority = 0 } = {}) {
    if (typeof fn !== "function") throw new TypeError("onIntent: handler must be a function");
    const list = handlers.get(name) || [];
    const h = { fn, priority, seq: ++seq };
    list.push(h); list.sort((a, b) => b.priority - a.priority || b.seq - a.seq);
    handlers.set(name, list);
    return () => { const l = handlers.get(name); if (!l) return; const i = l.indexOf(h); if (i >= 0) l.splice(i, 1); };
  }

  /** Emit an intent. Resolves true when a handler consumed it. Sync handlers run synchronously (in order). */
  function emitIntent(name, args = {}, source = "system") {
    const ev = { name, args: args || {}, source, t: now(), handled: false };
    if (!CONTINUOUS.has(name)) { log.push(ev); if (log.length > logSize) log.shift(); }
    const list = [...(handlers.get(name) || []), ...(handlers.get("*") || [])]
      .sort((a, b) => b.priority - a.priority || b.seq - a.seq);
    let i = 0;
    const step = () => {
      for (; i < list.length; i++) {
        let r;
        try { r = list[i].fn(ev.args, ev); }
        catch (e) { console.error(`[intents] ${name} handler failed`, e); continue; }
        if (r && typeof r.then === "function") {
          i++;
          return r.then(v => (v === true ? done(true) : step()), e => { console.error(`[intents] ${name} handler failed`, e); return step(); });
        }
        if (r === true) { i++; return done(true); }
      }
      return done(false);
    };
    const done = v => { ev.handled = v; return v; };
    const out = step();
    return out && typeof out.then === "function" ? out : Promise.resolve(out);
  }

  return {
    onIntent, emitIntent,
    /** The last discrete intents, oldest first: [{name, args, source, t, handled}]. Intents only, never frames. */
    recent: () => log.map(e => ({ ...e })),
    clearLog: () => { log.length = 0; },
    has: name => (handlers.get(name) || []).length > 0,
  };
}

// The app-wide bus. Modules import these; tests make their own with createIntentBus().
const bus = createIntentBus();
export const onIntent = bus.onIntent;
export const emitIntent = bus.emitIntent;
export const recentIntents = bus.recent;
export default bus;

if (typeof window !== "undefined") {
  window.__outpost = window.__outpost || {};
  window.__outpost.intents = { onIntent, emitIntent, recent: recentIntents, INTENTS };
}
