// Game controllers (PlayStation, Xbox, generic "standard" mapping) as one more remote (docs/KEYBOARD.md §Controller).
// Off until a controller connects ("Controller connected" toast); then a rAF poll maps it to the SAME intents the keys
// emit: D-pad / left stick → move, A/Cross → select, B/Circle → back, X/Square → mic, Y/Triangle → help,
// shoulders → prev / next, right stick → turn the Moon (rotate) or look around the cabin (look).
// Settings → Keyboard & controller → Left-handed swaps the sticks. The pure part (readPad, createPadReader) is unit-tested.
import { emitIntent } from "./intents.js";

/** Standard-mapping button indices (https://w3c.github.io/gamepad/#remapping). */
export const BTN = Object.freeze({ a: 0, b: 1, x: 2, y: 3, lb: 4, rb: 5, back: 8, start: 9, up: 12, down: 13, left: 14, right: 15 });
const DEAD = 0.5, LOOK_DEAD = 0.18;

/** One Gamepad (or a stub) → {dir, buttons:{a,b,x,y,lb,rb,start}, look:{x,y}}. lefty swaps the sticks. */
export function readPad(pad, { lefty = false } = {}) {
  const b = i => !!(pad && pad.buttons && pad.buttons[i] && (pad.buttons[i].pressed || pad.buttons[i].value > 0.5));
  const ax = i => (pad && pad.axes && +pad.axes[i]) || 0;
  const [mx, my, lx, ly] = lefty ? [ax(2), ax(3), ax(0), ax(1)] : [ax(0), ax(1), ax(2), ax(3)];
  let dir = b(BTN.up) ? "up" : b(BTN.down) ? "down" : b(BTN.left) ? "left" : b(BTN.right) ? "right" : null;
  if (!dir && Math.max(Math.abs(mx), Math.abs(my)) > DEAD) dir = Math.abs(mx) > Math.abs(my) ? (mx > 0 ? "right" : "left") : (my > 0 ? "down" : "up");
  const dz = v => (Math.abs(v) < LOOK_DEAD ? 0 : v);
  return { dir, buttons: { a: b(BTN.a), b: b(BTN.b), x: b(BTN.x), y: b(BTN.y), lb: b(BTN.lb), rb: b(BTN.rb), start: b(BTN.start) }, look: { x: dz(lx), y: dz(ly) } };
}

const PRESS = { a: ["select"], b: ["back"], x: ["mic"], y: ["help"], lb: ["prev"], rb: ["next"], start: ["settings"] };

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
      prev = f; void dirT;
      return out;
    },
  };
}

/** deps: { settings() → {lefty, repeat}, repeatMs(), inCabin(), onConnect(on, id), setMode() } */
export function installGamepad({ settings = () => ({}), repeatMs = () => 150, inCabin = () => false, onConnect = () => {}, setMode = () => {} } = {}) {
  if (typeof navigator === "undefined" || !navigator.getGamepads) return null;
  const reader = createPadReader({ repeat: repeatMs });
  let raf = 0, active = false;
  const pads = () => [...(navigator.getGamepads() || [])].filter(Boolean);
  function frame() {
    raf = 0;
    const p = pads()[0]; if (!p) { stop(); return; }
    const f = readPad(p, { lefty: !!settings().lefty });
    const acts = reader.step(f, performance.now());
    if (acts.length) setMode();
    acts.forEach(a => {
      if (a.intent) { emitIntent(a.intent, a.args, "gamepad"); return; }
      if (inCabin()) emitIntent("look", { x: a.look.x, y: a.look.y }, "gamepad");   // the stick is the look offset; centre recentres
      else if (!a.end) emitIntent("rotate", { phase: "move", dx: a.look.x * 0.012, dy: a.look.y * 0.012 }, "gamepad");
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
