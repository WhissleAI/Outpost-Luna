// The fist-spin calibration (docs/GESTURES.md §Calibration): "Make a fist… now tilt it left… right… up… down."
// It measures each kid's comfortable range per direction, so full speed is a comfortable tilt for that kid, not the
// default one. Pure (no DOM); stored in localStorage on this device only. Without it the defaults (tuning.js) apply.
import { DEFAULTS, CALIBRATION } from "./tuning.js";
import { rawStick } from "./spin.js";

export const SPIN_CAL_KEY = "outpost-gestures-spin";
export const CAL_STEPS = ["fist", "left", "right", "up", "down"];
const DIRS = { left: ["x", -1], right: ["x", 1], up: ["y", -1], down: ["y", 1] };
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** A stored calibration is used only when every field is a sane number (anything else = the defaults). */
export function validCal(c, T = CALIBRATION) {
  if (!c || typeof c !== "object" || c.v !== T.version) return null;
  const ok = ["left", "right", "up", "down"].every(k => Number.isFinite(c[k]) && c[k] >= T.minRange && c[k] <= T.maxRange);
  if (!ok || (c.pitchSign !== 1 && c.pitchSign !== -1)) return null;
  const out = { v: c.v, left: c.left, right: c.right, up: c.up, down: c.down, pitchSign: c.pitchSign, at: c.at || 0 };
  // the kid's pinch (thumb to index, hand-lengths), from "Pinch your fingers"; optional (skippable), dropped if odd
  if (Number.isFinite(c.pinch) && c.pinch >= T.pinchMin && c.pinch <= T.pinchMax) out.pinch = c.pinch;
  return out;
}
export function loadSpinCal(storage = globalThis.localStorage) {
  try { return validCal(JSON.parse(storage.getItem(SPIN_CAL_KEY) || "null")); } catch (e) { return null; }
}
export function saveSpinCal(cal, storage = globalThis.localStorage) {
  const c = validCal(cal); if (!c) return false;
  try { storage.setItem(SPIN_CAL_KEY, JSON.stringify(c)); return true; } catch (e) { return false; }
}
export function clearSpinCal(storage = globalThis.localStorage) { try { storage.removeItem(SPIN_CAL_KEY); } catch (e) { /* private mode */ } }

/**
 * One calibration run. begin(reading) sets the neutral fist; feed(dir, reading, tMs) records a frame of the
 * "tilt it <dir>" step and says when the step is done (moved ≥ minMove that way and held stepHoldMs, or stepMaxMs
 * passed); result() is the calibration to store. Directions never reached keep the default (1).
 */
/** The pinch step's measurement: the median thumb to index distance over the hold (hand-lengths), or null. */
export function measurePinch(ds, T = CALIBRATION) {
  const v = ds.filter(d => Number.isFinite(d) && d > 0).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v[Math.floor(v.length / 2)];
  return m >= T.pinchMin && m <= T.pinchMax ? +m.toFixed(3) : null;
}

export function createFistCalibration(opts = {}) {
  const C = { ...DEFAULTS, ...CALIBRATION, ...opts };
  let neutral = null;
  const samples = { left: [], right: [], up: [], down: [] }, step = {};
  // how far "that way" a frame is, before the tilt sign is known (up / down accept either tilt sign)
  const along = (dir, r) => {
    const [ax, s] = DIRS[dir];
    if (ax === "x") return s * r.x;
    return s * r.py + C.fistTiltWeight * Math.abs(r.pitch);
  };
  return {
    begin(reading) { neutral = reading; for (const k in samples) samples[k].length = 0; },
    get ready() { return !!neutral; },
    feed(dir, reading, t) {
      if (!neutral || !DIRS[dir]) return { progress: 0, done: false };
      const r = rawStick(reading, neutral, C, 1);
      samples[dir].push(r);
      const st = step[dir] || (step[dir] = { t0: t, since: null });
      const a = along(dir, r);
      if (a >= C.minMove) { if (st.since == null) st.since = t; } else st.since = null;
      const held = st.since == null ? 0 : t - st.since;
      const done = held >= C.stepHoldMs || t - st.t0 >= C.stepMaxMs;
      return { progress: clamp(held / C.stepHoldMs, 0, 1), done, amount: a };
    },
    result(now = Date.now()) {
      // the tilt sign: "up" should tip the knuckles toward the screen (+pitch). If this kid's up tips them away, flip.
      const ext = arr => arr.reduce((b, r) => (Math.abs(r.pitch) > Math.abs(b) ? r.pitch : b), 0);
      const pu = ext(samples.up), pd = ext(samples.down);
      const pitchSign = pu - pd < -0.2 ? -1 : 1;
      const range = dir => {
        const [ax, s] = DIRS[dir], arr = samples[dir];
        if (!arr.length) return 1;
        const best = Math.max(...arr.map(r => (ax === "x" ? s * r.x : s * (r.py - C.fistTiltWeight * pitchSign * r.pitch))));
        if (!(best >= C.minMove)) return 1;   // never got there: keep the default
        return +clamp(best * C.comfort, C.minRange, C.maxRange).toFixed(3);
      };
      return { v: C.version, left: range("left"), right: range("right"), up: range("up"), down: range("down"), pitchSign, at: now };
    },
  };
}
