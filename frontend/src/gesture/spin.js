// Fist spin: the fist as a joystick (docs/GESTURES.md §Fist spin). Pure (no DOM), so the math is unit-tested.
//
//   fistReading(hand)             one frame's fist: palm position, size, lean (roll), tilt (pitch), twist
//   rawStick(reading, neutral)    the offset from where the fist grabbed, in "default full" units (1 = full speed)
//   calibrated(raw, cal)          divided by the kid's own comfortable range per direction (gesture/calibration.js)
//   shapeStick(v)                 radial dead zone + gain curve, |v| ≤ 1
//   createSpinner()               stick → eased angular speed, max speed, release momentum that decays
//   oneEuro()                     the One Euro filter (Casiez et al. 2012): jitter out, little lag
//
// Sign convention: stick x > 0 = the kid's right (mirror space), y > 0 = down (image space). The spinner's dx / dy
// are the same "surface moves that way" convention as a drag (globe.rotateBy): fist right → the surface keeps turning
// right, fist down → it turns down (the north comes into view). SPIN.invert flips it.
import { DEFAULTS, SPIN } from "./tuning.js";

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const wrapPi = a => { while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; };
const P3 = p => (Array.isArray(p) ? [p[0], p[1], p[2] || 0] : [p.x, p.y, p.z || 0]);

/** One Euro filter for a scalar. f(value, tSeconds) → filtered. Adaptive cutoff: slow = smooth, fast = responsive. */
export function oneEuro({ minCutoff = 1, beta = 0, dCutoff = 1 } = {}) {
  let x = null, dx = 0, t0 = null;
  const alpha = (cut, dt) => { const tau = 1 / (2 * Math.PI * cut); return 1 / (1 + tau / dt); };
  const f = (v, t) => {
    if (x == null || t0 == null || t <= t0) { x = v; dx = 0; t0 = t; return v; }
    const dt = t - t0; t0 = t;
    const d = (v - x) / dt;
    dx += alpha(dCutoff, dt) * (d - dx);
    x += alpha(minCutoff + beta * Math.abs(dx), dt) * (v - x);
    return x;
  };
  f.reset = () => { x = null; dx = 0; t0 = null; };
  return f;
}

/**
 * One frame's fist. hand: { lm: 21 × [x, y, z], side }. MediaPipe z is depth relative to the wrist (smaller = nearer
 * the camera), on about the same scale as x.
 *   palm: [x, y] normalised · scale: wrist → middle knuckle (aspect-corrected) · roll: lean of that bone in the image
 *   (0 = knuckles straight up, + = leaning to the kid's right) · pitch: + = knuckles tipped toward the screen ·
 *   twist: + = turned like a doorknob clockwise (as the kid sees it), either hand.
 */
export function fistReading(hand, aspect = 4 / 3) {
  const L = hand.lm.map(P3).map(p => [p[0] * aspect, p[1], p[2] * aspect]);
  const W = L[0], M = L[9], I = L[5], K = L[17];
  const v = [M[0] - W[0], M[1] - W[1]], len = Math.hypot(v[0], v[1]) || 1e-6;
  const roll = Math.atan2(v[0], -v[1]);
  const pitch = Math.atan2(W[2] - M[2], len);
  const row = [K[0] - I[0], K[1] - I[1]], rowLen = Math.hypot(row[0], row[1]) || 1e-6;
  const twist = Math.atan2(K[2] - I[2], rowLen) * (hand.side === "left" ? -1 : 1);
  const C = [0, 5, 9, 13, 17].map(i => L[i]);
  const palm = [C.reduce((a, p) => a + p[0], 0) / 5 / aspect, C.reduce((a, p) => a + p[1], 0) / 5];
  return { palm, scale: len, roll, pitch, twist, aspect };
}

/**
 * The stick from where the fist grabbed (neutral) to now, uncalibrated: 1 = the default full offset.
 * x = sideways move + lean; y = up/down move − tilt toward the screen (tilting the knuckles toward the screen is
 * "up", like pushing a joystick forward); z = twist. pitchSign (calibration) flips the tilt for kids who tilt the
 * other way. Also returns the parts (the calibration needs them).
 */
export function rawStick(r, n, cfg = DEFAULTS, pitchSign = 1) {
  const s = n.scale || r.scale || 1e-3, a = n.aspect || r.aspect || 4 / 3;
  const px = ((r.palm[0] - n.palm[0]) * a / s) / cfg.fistPosRange;
  const py = ((r.palm[1] - n.palm[1]) / s) / cfg.fistPosRange;
  const roll = wrapPi(r.roll - n.roll) / cfg.fistRollRange;
  const pitch = wrapPi(r.pitch - n.pitch) / cfg.fistPitchRange;
  const twist = wrapPi(r.twist - n.twist) / cfg.fistTwistRange;
  const w = cfg.fistTiltWeight;
  return { x: px + w * roll, y: py - w * pitchSign * pitch, z: twist, px, py, roll, pitch };
}

/** Apply the kid's calibration: each direction divided by its own comfortable range. cal null = defaults. */
export function calibrated(raw, cal) {
  if (!cal) return { x: raw.x, y: raw.y, z: raw.z };
  const x = raw.x / (raw.x < 0 ? cal.left : cal.right) || 0, y = raw.y / (raw.y < 0 ? cal.up : cal.down) || 0;
  return { x: clamp(x, -1.5, 1.5), y: clamp(y, -1.5, 1.5), z: raw.z };
}

/** Radial dead zone + gain curve. Returns {x, y, m}: direction kept, magnitude m in 0..1. */
export function shapeStick(v, { dead = SPIN.dead, expo = SPIN.expo } = {}) {
  const m = Math.hypot(v.x || 0, v.y || 0);
  if (m <= dead) return { x: 0, y: 0, m: 0 };
  const k = Math.pow(clamp((m - dead) / (1 - dead), 0, 1), expo);
  return { x: v.x / m * k, y: v.y / m * k, m: k };
}
/** The same for one axis (twist → zoom). */
export function shapeAxis(v, { dead = SPIN.twistDead, expo = SPIN.expo } = {}) {
  const m = Math.abs(v); if (m <= dead) return 0;
  return Math.sign(v) * Math.pow(clamp((m - dead) / (1 - dead), 0, 1), expo);
}

/**
 * Rate control. set(stick) while the fist holds ({x, y, z} in -1..1 calibrated, before shaping), set(null) on release.
 * step(dt seconds, {distance}) → {dx, dy, zoom, vx, vy, speed, grabbed}: dx / dy are radians to turn this frame
 * (surface-follows convention), zoom a multiplicative factor (> 1 = closer).
 */
export function createSpinner(opts = {}) {
  const T = { ...SPIN, ...opts };
  let stick = null, vx = 0, vy = 0, released = false;
  return {
    set(s) {
      if (s) { stick = { x: +s.x || 0, y: +s.y || 0, z: +s.z || 0 }; released = false; }
      else if (stick) { stick = null; released = true; }
    },
    halt() { stick = null; vx = vy = 0; released = false; },
    configure(o) { Object.assign(T, o); },
    get grabbed() { return !!stick; },
    get active() { return !!stick || Math.hypot(vx, vy) > 0; },
    get velocity() { return { vx, vy, speed: Math.hypot(vx, vy) }; },
    step(dt, { distance = T.refDistance } = {}) {
      dt = clamp(dt, 0, 0.1);   // a long pause (a background tab) never jumps the Moon
      const sgn = T.invert ? -1 : 1;
      const ds = clamp((distance - 1) / (T.refDistance - 1), T.minDistScale, T.maxDistScale);
      let zoom = 1;
      if (stick) {
        const sh = shapeStick(stick, T), tx = sh.x * T.maxSpeed * ds * sgn, ty = sh.y * T.maxSpeed * ds * sgn;
        const k = 1 - Math.exp(-dt / T.easeTau);
        let ax = (tx - vx) * k, ay = (ty - vy) * k;
        const lim = T.maxAccel * dt, am = Math.hypot(ax, ay);
        if (am > lim) { ax *= lim / am; ay *= lim / am; }
        vx += ax; vy += ay;
        if (T.twistZoom && stick.z) zoom = Math.exp(shapeAxis(stick.z, { dead: T.twistDead, expo: T.expo }) * T.zoomRate * dt);
      } else {
        if (released) { vx *= T.releaseCarry; vy *= T.releaseCarry; released = false; }
        const d = Math.exp(-dt / T.decayTau); vx *= d; vy *= d;
        if (Math.hypot(vx, vy) < T.stopBelow) vx = vy = 0;
      }
      return { dx: vx * dt, dy: vy * dt, zoom, vx, vy, speed: Math.hypot(vx, vy), grabbed: !!stick };
    },
  };
}
