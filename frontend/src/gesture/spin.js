// Fist spin: the fist as a joystick (docs/GESTURES.md §Fist spin). Pure (no DOM), so the math is unit-tested.
//
//   fistReading(hand)             one frame's fist: palm position, size, lean (roll), tilt (pitch), twist
//   rawStick(reading, neutral)    the offset from where the fist grabbed, in "default full" units (1 = full speed)
//   calibrated(raw, cal)          divided by the kid's own comfortable range per direction (gesture/calibration.js)
//   shapeStick(v)                 radial dead zone + gain curve, |v| ≤ 1
//   createSpinner()               stick → eased angular speed, max speed, release momentum that decays
//   pinchFeatures(hand)           the one-hand zoom's pinch: thumb to index distance, reach and angle (hysteresis)
//   createZoomer()                zoom rate → eased zoom factor (pinch slide, +/- keys, triggers, voice steps)
//   oneEuro()                     the One Euro filter (Casiez et al. 2012): jitter out, little lag
//
// The fist only turns the Moon: its twist is read (fistReading) but never zooms. Zoom is the pinch and slide.
//
// Sign convention: stick x > 0 = the kid's right (mirror space), y > 0 = down (image space). The spinner's dx / dy
// are the same "surface moves that way" convention as a drag (globe.rotateBy): fist right → the surface keeps turning
// right, fist down → it turns down (the north comes into view). SPIN.invert flips it.
import { DEFAULTS, SPIN, PINCH, ZOOM } from "./tuning.js";

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
  const w = cfg.fistTiltWeight;
  return { x: px + w * roll, y: py - w * pitchSign * pitch, px, py, roll, pitch };
}

/** Apply the kid's calibration: each direction divided by its own comfortable range. cal null = defaults. */
export function calibrated(raw, cal) {
  if (!cal) return { x: raw.x, y: raw.y };
  const x = raw.x / (raw.x < 0 ? cal.left : cal.right) || 0, y = raw.y / (raw.y < 0 ? cal.up : cal.down) || 0;
  return { x: clamp(x, -1.5, 1.5), y: clamp(y, -1.5, 1.5) };
}

/** Radial dead zone + gain curve. Returns {x, y, m}: direction kept, magnitude m in 0..1. */
export function shapeStick(v, { dead = SPIN.dead, expo = SPIN.expo } = {}) {
  const m = Math.hypot(v.x || 0, v.y || 0);
  if (m <= dead) return { x: 0, y: 0, m: 0 };
  const k = Math.pow(clamp((m - dead) / (1 - dead), 0, 1), expo);
  return { x: v.x / m * k, y: v.y / m * k, m: k };
}
/** The same for one axis (the pinch slide → zoom rate). */
export function shapeAxis(v, { dead = ZOOM.dead, expo = ZOOM.expo } = {}) {
  const m = Math.abs(v); if (m <= dead) return 0;
  return Math.sign(v) * Math.pow(clamp((m - dead) / (1 - dead), 0, 1), expo);
}

/**
 * Rate control. set(stick) while the fist holds ({x, y} in -1..1 calibrated, before shaping), set(null) on release.
 * step(dt seconds, {distance}) → {dx, dy, vx, vy, speed, grabbed}: dx / dy are radians to turn this frame
 * (surface-follows convention). It never zooms.
 */
export function createSpinner(opts = {}) {
  const T = { ...SPIN, ...opts };
  let stick = null, vx = 0, vy = 0, released = false;
  return {
    set(s) {
      if (s) { stick = { x: +s.x || 0, y: +s.y || 0 }; released = false; }
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
      if (stick) {
        const sh = shapeStick(stick, T), tx = sh.x * T.maxSpeed * ds * sgn, ty = sh.y * T.maxSpeed * ds * sgn;
        const k = 1 - Math.exp(-dt / T.easeTau);
        let ax = (tx - vx) * k, ay = (ty - vy) * k;
        const lim = T.maxAccel * dt, am = Math.hypot(ax, ay);
        if (am > lim) { ax *= lim / am; ay *= lim / am; }
        vx += ax; vy += ay;
      } else {
        if (released) { vx *= T.releaseCarry; vy *= T.releaseCarry; released = false; }
        const d = Math.exp(-dt / T.decayTau); vx *= d; vy *= d;
        if (Math.hypot(vx, vy) < T.stopBelow) vx = vy = 0;
      }
      return { dx: vx * dt, dy: vy * dt, vx, vy, speed: Math.hypot(vx, vy), grabbed: !!stick };
    },
  };
}

/**
 * The pinch's features from one hand (aspect-corrected, in hand-lengths): d = thumb tip to index tip; idxReach = index
 * tip to index knuckle (a fist folds it: small); thReach = thumb tip to thumb base (a fist tucks it: small); cos = the
 * angle between where the thumb tip and the index tip point (a pinch: they point at each other, cos low).
 * isPinch(f, was, th) applies the thresholds with hysteresis: harder to start than to keep.
 */
export function pinchFeatures(hand, aspect = 4 / 3) {
  const L = hand.lm.map(P3).map(p => [p[0] * aspect, p[1]]);
  const d2 = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const s = d2(L[9], L[0]) || 1e-6;
  const tv = [L[4][0] - L[3][0], L[4][1] - L[3][1]], iv = [L[8][0] - L[7][0], L[8][1] - L[7][1]];
  const cos = (tv[0] * iv[0] + tv[1] * iv[1]) / ((Math.hypot(...tv) * Math.hypot(...iv)) || 1e-6);
  const mid = [(L[4][0] + L[8][0]) / 2 / aspect, (L[4][1] + L[8][1]) / 2];
  return { d: d2(L[4], L[8]) / s, idxReach: d2(L[8], L[5]) / s, thReach: d2(L[4], L[1]) / s, cos, mid, scale: s };
}
/** Pinch thresholds for a calibrated pinch distance (null = the defaults). */
export function pinchThresholds(calPinch, P = PINCH) {
  if (!(calPinch > 0)) return { on: P.on, off: P.off };
  const on = clamp(calPinch * P.calOnK, P.onMin, P.onMax);
  return { on, off: Math.max(on * P.offK, on + 0.08) };
}
export function isPinch(f, was = false, th = { on: PINCH.on, off: PINCH.off }, P = PINCH) {
  if (was) return f.d < th.off && f.idxReach >= P.minIndexReachStay && f.thReach >= P.minThumbReachStay;
  return f.d < th.on && f.idxReach >= P.minIndexReach && f.thReach >= P.minThumbReach && f.cos < P.maxTipCos;
}

/**
 * Zoom rate control. set(rate) while held (-1..1, + = closer, before shaping), set(null) on release (the rate dies
 * fast: no coasting zoom). nudge(factor) eases a step (voice, a quick key tap). step(dt) → {factor, rate, active}:
 * factor multiplies the zoom (> 1 = closer). A press shorter than a tap still zooms at least tapStep (minStep: true).
 */
export function createZoomer(opts = {}) {
  const T = { ...ZOOM, ...opts };
  let target = null, v = 0, acc = 0, minStep = false, pend = 0, pendRate = 0;
  return {
    set(r, { tap = false } = {}) {
      if (r != null) { if (target == null) { acc = 0; minStep = tap; } target = clamp(+r || 0, -1, 1); return; }
      if (target != null && minStep) {   // a quick tap: top it up to a tap step, eased
        const want = Math.log(T.tapStep) * Math.sign(target || v || 1);
        if (Math.abs(acc) < Math.abs(want)) this.nudge(Math.exp(want - acc));
      }
      target = null; minStep = false;
    },
    nudge(f) { if (!(f > 0)) return; pend += Math.log(f); pendRate = Math.abs(pend) / (T.stepMs / 1000); },
    halt() { target = null; v = 0; pend = 0; acc = 0; minStep = false; },
    configure(o) { Object.assign(T, o); },
    get held() { return target != null; },
    get active() { return target != null || Math.abs(v) > 1e-3 || Math.abs(pend) > 1e-4; },
    get rate() { return v; },
    step(dt) {
      dt = clamp(dt, 0, 0.25);   // a slow frame (a busy machine) keeps the rate in wall-clock time; a stalled tab never jumps far
      const goal = target != null ? shapeAxis(target, T) * T.maxRate : 0;
      v += (goal - v) * (1 - Math.exp(-dt / (target != null ? T.easeTau : T.stopTau)));
      if (target == null && Math.abs(v) < 1e-3) v = 0;
      let ln = v * dt;
      if (pend) { const p = Math.sign(pend) * Math.min(Math.abs(pend), pendRate * dt); pend -= p; ln += p; if (Math.abs(pend) < 1e-5) pend = 0; }
      if (target != null) acc += ln;
      return { factor: Math.exp(ln), rate: v, active: this.active };
    },
  };
}
