// Game controllers (PlayStation, Xbox, generic "standard" mapping) as one more remote (docs/KEYBOARD.md §Controller).
// Off until a controller connects ("Controller connected" toast); then a rAF poll maps it to the SAME intents the keys
// emit: D-pad / left stick → move, A/Cross → select, B/Circle → back, X/Square → mic, Y/Triangle → help,
// shoulders → prev / next, right stick → spin the Moon (spin, the same rate control as the fist) or look around the cabin (look). In the cabin the live
// mission clock: View/Select/Share → pause or run, RT/R2 → skip to next event, LT/L2 → time warp (docs/GAMEPLAY.md).
// Outside the cabin the triggers zoom the Moon: RT/R2 closer, LT/L2 farther, as far as you press them (zoom_rate).
// Settings → Keyboard & controller → Left-handed swaps the sticks. The pure part (readPad, createPadReader) is unit-tested.
import { emitIntent } from "./intents.js";

/** Standard-mapping button indices (https://w3c.github.io/gamepad/#remapping). */
export const BTN = Object.freeze({ a: 0, b: 1, x: 2, y: 3, lb: 4, rb: 5, lt: 6, rt: 7, back: 8, start: 9, up: 12, down: 13, left: 14, right: 15 });
const DEAD = 0.5, LOOK_DEAD = 0.18;

/** One Gamepad (or a stub) → {dir, buttons:{a,b,x,y,lb,rb,start}, look:{x,y}}. lefty swaps the sticks. */
export function readPad(pad, { lefty = false } = {}) {
  const b = i => !!(pad && pad.buttons && pad.buttons[i] && (pad.buttons[i].pressed || pad.buttons[i].value > 0.5));
  const ax = i => (pad && pad.axes && +pad.axes[i]) || 0;
  const [mx, my, lx, ly] = lefty ? [ax(2), ax(3), ax(0), ax(1)] : [ax(0), ax(1), ax(2), ax(3)];
  let dir = b(BTN.up) ? "up" : b(BTN.down) ? "down" : b(BTN.left) ? "left" : b(BTN.right) ? "right" : null;
  if (!dir && Math.max(Math.abs(mx), Math.abs(my)) > DEAD) dir = Math.abs(mx) > Math.abs(my) ? (mx > 0 ? "right" : "left") : (my > 0 ? "down" : "up");
  const dz = v => (Math.abs(v) < LOOK_DEAD ? 0 : v);
  // the triggers' travel (0..1): outside the cabin RT zooms in and LT zooms out at the pinch's rates
  const tv = i => { const x = pad && pad.buttons && pad.buttons[i]; const v = x ? (+x.value || (x.pressed ? 1 : 0)) : 0; return v < 0.08 ? 0 : v; };
  return { dir, buttons: { a: b(BTN.a), b: b(BTN.b), x: b(BTN.x), y: b(BTN.y), lb: b(BTN.lb), rb: b(BTN.rb), start: b(BTN.start),
    back: b(BTN.back), lt: b(BTN.lt), rt: b(BTN.rt) }, look: { x: dz(lx), y: dz(ly) }, zoom: tv(BTN.rt) - tv(BTN.lt) };
}

const PRESS = { a: ["select"], b: ["back"], x: ["mic"], y: ["help"], lb: ["prev"], rb: ["next"], start: ["settings"],
  back: ["time_toggle"], rt: ["skip_event"], lt: ["time_warp"] };   // the clock intents do nothing outside the cabin

/**
 * Edges → actions. step(frame, t) returns [{intent, args}] for this frame: a button fires once per press; a held
 * direction fires, waits `delay` ms, then repeats every `repeat` ms; the right stick streams {look} while off-centre
 * and one {look:{x:0,y:0}} when it comes back.
 */
export function createPadReader({ delay = 380, repeat = () => 150 } = {}) {
  let prev = { dir: null, buttons: {}, look: { x: 0, y: 0 } }, dirT = 0, nextT = 0;
  return {
    step(f, t) {
      const out = [];
      if (f.dir && f.dir !== prev.dir) { out.push({ intent: "move", args: { dir: f.dir } }); dirT = t; nextT = t + delay; }
      else if (f.dir && t >= nextT) { out.push({ intent: "move", args: { dir: f.dir } }); nextT = t + (typeof repeat === "function" ? repeat() : repeat); }
      Object.entries(PRESS).forEach(([k, [intent]]) => { if (f.buttons[k] && !prev.buttons[k]) out.push({ intent, args: {} }); });
      const moving = f.look.x || f.look.y, was = prev.look.x || prev.look.y;
      if (moving) out.push({ look: { x: f.look.x, y: f.look.y } });
      else if (was) out.push({ look: { x: 0, y: 0 }, end: true });
      const zw = prev.zoom || 0, zn = f.zoom || 0;
      if (zn) out.push({ zoom: zn, start: !zw });
      else if (zw) out.push({ zoom: 0, end: true });
      prev = f; void dirT;
      return out;
    },
  };
}

/** deps: { settings() → {lefty, repeat}, repeatMs(), inCabin(), onConnect(on, id), setMode() } */
export function installGamepad({ settings = () => ({}), repeatMs = () => 150, inCabin = () => false, onConnect = () => {}, setMode = () => {} } = {}) {
  if (typeof navigator === "undefined" || !navigator.getGamepads) return null;
  const reader = createPadReader({ repeat: repeatMs });
  let raf = 0, active = false, rtAt = 0, rtFF = false;
  const FF_HOLD_MS = 320;   // [polish 2] in the cabin RT is "tap: skip ahead, hold: fast-forward" (like the Skip button)
  const pads = () => [...(navigator.getGamepads() || [])].filter(Boolean);
  function frame() {
    raf = 0;
    const p = pads()[0]; if (!p) { stop(); return; }
    const f = readPad(p, { lefty: !!settings().lefty });
    const acts = reader.step(f, performance.now());
    if (acts.length) setMode();
    acts.forEach(a => {
      if (a.intent) {
        if ((a.intent === "skip_event" || a.intent === "time_warp") && !inCabin()) return;   // the triggers zoom outside the cabin
        if (a.intent === "skip_event") { rtAt = performance.now(); rtFF = false; return; }   // decided on release (below)
        if (a.intent === "settings" && inCabin()) { emitIntent("pause_menu", {}, "gamepad"); return; }   // Start: the pause menu
        emitIntent(a.intent, a.args, "gamepad"); return;
      }
      if ("zoom" in a) {
        if (!inCabin()) { emitIntent("zoom_rate", { phase: a.end ? "end" : a.start ? "start" : "move", rate: a.zoom }, "gamepad"); return; }
        if (!rtAt) return;
        if (a.end) { if (rtFF) emitIntent("time_ff", { on: false }, "gamepad"); else emitIntent("skip_event", {}, "gamepad"); rtAt = 0; rtFF = false; return; }
        if (!rtFF && a.zoom > 0 && performance.now() - rtAt >= FF_HOLD_MS) { rtFF = true; emitIntent("time_ff", { on: true }, "gamepad"); }
        return;
      }
      if (inCabin()) emitIntent("look", { x: a.look.x, y: a.look.y }, "gamepad");   // the stick is the look offset; centre recentres
      else emitIntent("spin", { phase: a.end ? "end" : "move", x: a.look.x, y: a.look.y }, "gamepad");   // the same rate feel as the fist
    });
    raf = requestAnimationFrame(frame);
  }
  function start(id) { if (!active) { active = true; onConnect(true, id || ""); } if (!raf) raf = requestAnimationFrame(frame); }
  function stop() { if (active && !pads().length) { active = false; onConnect(false, ""); } if (raf) cancelAnimationFrame(raf); raf = 0; }
  addEventListener("gamepadconnected", e => start(e.gamepad && e.gamepad.id));
  addEventListener("gamepaddisconnected", () => { if (!pads().length) stop(); });
  // a controller that was plugged in before the app opened shows up on its first button press (Chromium rule)
  if (pads().length) start(pads()[0].id);
  return { get active() { return active; }, start, stop };
}
