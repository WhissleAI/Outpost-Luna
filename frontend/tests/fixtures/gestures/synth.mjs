// Synthetic MediaPipe landmarks for the gesture tests: a 21-point hand and a 6-point face detection, in the same
// normalised MIRROR space the classifier reads (docs/GESTURES.md §Testing). Proportions follow MediaPipe's canonical
// hand (wrist → middle knuckle = 1 unit). Deterministic jitter (seeded) stands in for landmark noise.
//
//   node tests/fixtures/gestures/make_fixtures.mjs     regenerates the JSON fixtures from these sequences

// Hand in hand units: x to the kid's right (a right hand, palm to the camera, seen in the mirror: thumb on the left),
// y up. Order: wrist, thumb cmc/mcp/ip/tip, index mcp/pip/dip/tip, middle…, ring…, pinky….
const MCP = { index: [-0.32, 0.95], middle: [0, 1.0], ring: [0.28, 0.95], pinky: [0.52, 0.83] };
const LEN = { index: 0.92, middle: 1.0, ring: 0.92, pinky: 0.72 };
const DIR = { index: [-0.12, 1], middle: [0, 1], ring: [0.1, 1], pinky: [0.22, 1] };

// fingers shown to count: spread like a V (the classifier needs the tips apart; a relaxed hand keeps them together)
const VEE = { index: [-0.42, 1], middle: [0.05, 1], ring: [0.4, 1], pinky: [0.6, 1] };
function finger(name, extended, vee = false) {
  const [mx, my] = MCP[name], L = LEN[name];
  if (extended) {
    const [dx, dy] = (vee ? VEE : DIR)[name], n = Math.hypot(dx, dy);
    return [0.45, 0.75, 1.0].map(f => [mx + dx / n * L * f, my + dy / n * L * f]);
  }
  // curled: up a little, then folded back down onto the palm
  return [[mx, my + 0.32], [mx + 0.02, my + 0.08], [mx + 0.03, my - 0.32]];
}
function thumb(kind) {
  switch (kind) {
    case "out": return [[-0.35, 0.25], [-0.6, 0.42], [-0.85, 0.55], [-1.08, 0.66]];
    case "up": return [[-0.36, 0.3], [-0.5, 0.75], [-0.55, 1.2], [-0.58, 1.65]];
    case "down": return [[-0.36, 0.2], [-0.48, -0.2], [-0.52, -0.6], [-0.55, -1.0]];
    default: return [[-0.32, 0.25], [-0.42, 0.5], [-0.25, 0.62], [-0.06, 0.58]];   // tucked across the palm
  }
}
const POSES = {
  palm: { f: [1, 1, 1, 1], t: "out" },
  open: { f: [1, 1, 1, 1], t: "tuck" },
  point: { f: [1, 0, 0, 0], t: "tuck" },
  fist: { f: [0, 0, 0, 0], t: "tuck" },
  thumbs_up: { f: [0, 0, 0, 0], t: "up" },
  thumbs_down: { f: [0, 0, 0, 0], t: "down" },
  pinch: { f: [1, 0, 0, 0], t: "pinch" },   // phase 2's two-hand pinch: a straight index, the thumb at its tip
  // the one-hand zoom's pinch: the index part-bent to meet the thumb tip; the others curled (pinch1) or out (ok sign)
  pinch1: { f: [0, 0, 0, 0], t: "meet" }, ok: { f: [0, 1, 1, 1], t: "meet" },
  relaxed: { f: [1, 1, 0, 0], t: "tuck" },   // a half-open resting hand: not a gesture
  two: { f: [1, 1, 0, 0], t: "tuck", v: true }, three: { f: [1, 1, 1, 0], t: "tuck", v: true }, four: { f: [1, 1, 1, 1], t: "tuck", v: true },
};

/** Mulberry32: deterministic noise. */
export function rng(seed = 1) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/**
 * A hand: pose name, centre of the wrist (cx, cy normalised), scale s (normalised wrist → middle knuckle, ~0.12 at
 * arm's length), side "right" | "left", rot (radians, + = clockwise on screen), noise (normalised), pitch (radians,
 * + = knuckles tipped toward the camera), twist (radians, + = the pinky side turned away; MediaPipe-style z).
 */
export function hand(pose, { cx = 0.5, cy = 0.7, s = 0.12, side = "right", rot = 0, pitch = 0, twist = 0, gap = 0, aspect = 4 / 3, noise = 0, rand = Math.random, score = 0.95 } = {}) {
  const P = POSES[pose]; if (!P) throw new Error("unknown pose " + pose);
  let pts;
  if (P.t === "meet") {
    // gap: how far the thumb tip sits from the index tip (hand-lengths), to test the hysteresis
    const tip = [-0.68, 1.42];
    pts = [[0, 0], [-0.35, 0.25], [-0.55, 0.6], [-0.66, 1.0], [tip[0] - 0.02 - gap, tip[1] - 0.06], MCP.index, [-0.42, 1.28], [-0.56, 1.45], tip,
      MCP.middle, ...finger("middle", !!P.f[1]), MCP.ring, ...finger("ring", !!P.f[2]), MCP.pinky, ...finger("pinky", !!P.f[3])];
  } else if (pose === "pinch") {
    const idx = finger("index", true), tip = idx[2];
    pts = [[0, 0], [-0.35, 0.25], [-0.55, 0.5], [tip[0] - 0.15, tip[1] - 0.2], [tip[0] - 0.05, tip[1] - 0.08], MCP.index, ...idx,
      MCP.middle, ...finger("middle", false), MCP.ring, ...finger("ring", false), MCP.pinky, ...finger("pinky", false)];
  } else {
    pts = [[0, 0], ...thumb(P.t), MCP.index, ...finger("index", !!P.f[0], P.v), MCP.middle, ...finger("middle", !!P.f[1], P.v),
      MCP.ring, ...finger("ring", !!P.f[2], P.v), MCP.pinky, ...finger("pinky", !!P.f[3], P.v)];
  }
  const m = side === "left" ? -1 : 1, c = Math.cos(rot), sn = Math.sin(rot);
  const cp = Math.cos(pitch), sp = Math.sin(pitch), ct = Math.cos(twist), st = Math.sin(twist);
  const lm = pts.map(([x, y], i) => {
    // pitch tips the hand about the wrist's x axis, twist turns it about its own long axis; depth goes into z
    const depth = -y * sp + x * st;
    const X = x * ct * m, Y = y * cp, rx = X * c + Y * sn, ry = -X * sn + Y * c;
    const j = () => (noise ? (rand() - 0.5) * 2 * noise : 0);
    const z = (i ? -0.02 : 0) + (pitch || twist ? depth * s / aspect : 0);
    return [+(cx + rx * s / aspect + j()).toFixed(5), +(cy - ry * s + j()).toFixed(5), +z.toFixed(4)];
  });
  return { lm, side, score };
}

/** A face detection: centre (cx, cy), width w, yaw (-1 left … 1 right, in eye distances of nose offset). */
export function face({ cx = 0.5, cy = 0.35, w = 0.22, yaw = 0, aspect = 4 / 3, score = 0.95 } = {}) {
  const h = w * aspect * 0.95, ex = w * 0.2, ey = cy - h * 0.12;
  const kp = [[cx - ex, ey], [cx + ex, ey], [cx + yaw * 2 * ex, cy + h * 0.08], [cx + yaw * ex, cy + h * 0.26], [cx - w * 0.48, cy], [cx + w * 0.48, cy]];
  return { box: { x: cx - w / 2, y: cy - h / 2, w, h }, kp: kp.map(p => p.map(v => +v.toFixed(5))), score };
}

/** Build a frame sequence at `fps` from a function of (i, t) → {hands, faces}. */
export function seq(ms, fn, { fps = 30, t0 = 1000, aspect = 4 / 3 } = {}) {
  const n = Math.round(ms * fps / 1000), out = [];
  for (let i = 0; i < n; i++) { const t = Math.round(t0 + i * 1000 / fps); out.push({ t, aspect, hands: [], faces: [], ...fn(i, t, i / Math.max(1, n - 1)) }); }
  return out;
}
/** Concatenate sequences, re-timing each to follow the last. */
export function chain(...parts) {
  const out = []; let t = null;
  parts.forEach(p => { if (!p.length) return; const off = t == null ? 0 : t + 33 - p[0].t; p.forEach(f => out.push({ ...f, t: f.t + off })); t = out[out.length - 1].t; });
  return out;
}
const ease = x => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2);

// ---------- the named sequences (true positives and false positives) ----------
export function sequences() {
  const R = rng(7), N = 0.003;
  const still = (pose, ms, o = {}) => seq(ms, () => ({ hands: [hand(pose, { noise: N, rand: R, ...o })] }));
  const none = ms => seq(ms, () => ({}));
  const swipe = (from, to, ms = 300, pose = "open") => seq(ms, (i, t, k) => ({ hands: [hand(pose, { cx: from + (to - from) * ease(k), noise: N, rand: R })] }));
  return {
    // ----- true positives -----
    palm_hold: { expect: ["palm_hold"], frames: chain(none(100), still("palm", 800)) },
    thumbs_up: { expect: ["thumbs_up"], frames: chain(none(100), still("thumbs_up", 600)) },
    thumbs_down: { expect: ["thumbs_down"], frames: chain(none(100), still("thumbs_down", 600)) },
    swipe_left: { expect: ["swipe_left"], frames: chain(still("open", 150, { cx: 0.75 }), swipe(0.75, 0.3), still("open", 100, { cx: 0.3 })) },
    swipe_right: { expect: ["swipe_right"], frames: chain(still("open", 150, { cx: 0.3 }), swipe(0.3, 0.75), still("open", 100, { cx: 0.75 })) },
    swipe_left_return: { expect: ["swipe_left"], note: "the hand comes back after a swipe: one step, not two",
      frames: chain(still("open", 150, { cx: 0.75 }), swipe(0.75, 0.3), still("open", 400, { cx: 0.3 }), swipe(0.3, 0.75, 350), still("open", 100, { cx: 0.75 })) },
    two_swipes: { expect: ["swipe_left", "swipe_left"], note: "two deliberate swipes after the cooldown are two steps",
      frames: chain(still("open", 150, { cx: 0.75 }), swipe(0.75, 0.3), none(400), still("open", 300, { cx: 0.75 }), swipe(0.75, 0.3), still("open", 100, { cx: 0.3 })) },
    point_dwell: { expect: ["select"], frames: chain(none(100), still("point", 1300, { cx: 0.5, cy: 0.75 })) },
    grab_drag: { expect: ["grab_start", "grab_move", "grab_end"],
      frames: chain(still("fist", 250, { cx: 0.4 }), seq(400, (i, t, k) => ({ hands: [hand("fist", { cx: 0.4 + 0.2 * k, noise: N, rand: R })] })), still("palm", 300, { cx: 0.6 })) },
    lean_in_back: { expect: ["lean_in", "lean_back"],
      frames: chain(seq(500, () => ({ faces: [face({ w: 0.2 })] })), seq(700, () => ({ faces: [face({ w: 0.27 })] })), seq(900, () => ({ faces: [face({ w: 0.2 })] }))) },
    look_right: { expect: ["head"], frames: chain(seq(300, () => ({ faces: [face({ cx: 0.5 })] })), seq(500, (i, t, k) => ({ faces: [face({ cx: 0.5 + 0.12 * k, yaw: 0.2 * k })] }))) },
    // ----- false positives: nothing (or only cursor / head motion) may fire -----
    brief_palm: { expect: [], note: "palm shown for 300 ms (< 0.5 s hold)", frames: chain(none(100), still("palm", 300), none(300)) },
    brief_thumb: { expect: [], note: "thumb up for 200 ms", frames: chain(none(100), still("thumbs_up", 200), none(300)) },
    slow_drift: { expect: [], note: "an open hand drifting sideways slowly is not a swipe",
      frames: seq(2000, (i, t, k) => ({ hands: [hand("open", { cx: 0.3 + 0.4 * k, noise: N, rand: R })] })) },
    vertical_wave: { expect: [], note: "an up-down wave is not a swipe",
      frames: seq(900, (i, t, k) => ({ hands: [hand("open", { cy: 0.6 + 0.25 * Math.sin(k * Math.PI * 2), noise: N, rand: R })] })) },
    moving_palm: { expect: [], note: "a palm that keeps moving (waving hello) is not a stop",
      frames: seq(1200, (i, t, k) => ({ hands: [hand("palm", { cx: 0.5 + 0.07 * Math.sin(k * Math.PI * 6), noise: N, rand: R })] })) },
    background_person: { expect: [], note: "a small (far) hand behind the kid giving a thumbs up is ignored",
      frames: chain(none(100), seq(800, () => ({ hands: [hand("thumbs_up", { s: 0.035, cx: 0.8, cy: 0.4 })] }))) },
    nearest_wins: { expect: ["thumbs_up"], note: "the kid's (large) thumb up counts; a far thumb down does not",
      frames: chain(none(100), seq(700, () => ({ hands: [hand("thumbs_down", { s: 0.05, cx: 0.85, cy: 0.35 }), hand("thumbs_up", { s: 0.13, cx: 0.4 })] }))) },
    flicker: { expect: [], note: "a hand that is never stable for 3 frames does nothing",
      frames: seq(900, i => (i % 3 === 0 ? { hands: [hand("thumbs_up")] } : {})) },
    relaxed_hand: { expect: [], note: "a half-open resting hand", frames: still("relaxed", 1500) },
    point_moving: { expect: [], note: "a pointing finger that keeps moving never dwells",
      frames: seq(1500, (i, t, k) => ({ hands: [hand("point", { cx: 0.25 + 0.5 * k, noise: N, rand: R })] })) },
    // ----- the fist as a joystick: grab, lean / move one way and hold, open the hand (8 directions) -----
    ...Object.fromEntries(Object.entries(FIST_DIRS).map(([d, v]) => [`fist_spin_${d}`, { expect: ["grab_start", "grab_move", "grab_end"],
      note: `fist grabs, leans ${d.replace("_", "-")} and holds, then the hand opens`, dir: v, frames: fistSpin(v, R, N) }])),
    // the owner's 0.1.2 problem: the same spins with the wrist rolling ±0.5 rad (twist) as the fist leans: never a zoom
    ...Object.fromEntries(Object.entries(FIST_DIRS).map(([d, v], i) => [`fist_spin_roll_${d}`, { expect: ["grab_start", "grab_move", "grab_end"],
      note: `fist leans ${d.replace("_", "-")} with the wrist rolled ${i % 2 ? "-" : "+"}0.5 rad: it turns, never zooms`, dir: v,
      frames: fistSpin(v, R, N, { twist: i % 2 ? -0.5 : 0.5 }) }])),
    // the one-hand zoom: pinch, hold still, slide up (closer) or down (farther), then open the hand
    pinch_slide_up: { expect: ["pinch_start", "pinch_move", "pinch_end"], note: "pinch, slide up 0.8 hand-lengths: zoom in", frames: pinchSlide(-0.8, R, N) },
    pinch_slide_down: { expect: ["pinch_start", "pinch_move", "pinch_end"], note: "pinch, slide down 0.8 hand-lengths: zoom out", frames: pinchSlide(0.8, R, N) },
    pinch_hold: { expect: ["pinch_start", "pinch_move", "pinch_end"], note: "a still pinch (the calibration's 'Pinch your fingers')", frames: pinchSlide(0, R, N, { holdMs: 600 }) },
    other_face_bigger_later: { expect: [], note: "head events only; a second, smaller face never drives the view",
      frames: seq(600, () => ({ faces: [face({ w: 0.2 }), face({ cx: 0.85, w: 0.08, yaw: 0.8 })] })) },
  };
}

/** The 8 stick directions: [x, y], x > 0 = the kid's right, y > 0 = down. */
export const FIST_DIRS = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1], up_left: [-0.71, -0.71], up_right: [0.71, -0.71], down_left: [-0.71, 0.71], down_right: [0.71, 0.71] };
/** A fist that grabs at (0.5, 0.62), moves 0.75 hand-lengths and leans (roll / pitch) towards v, holds, then opens. */
export function fistSpin(v, R = rng(11), N = 0.003, { holdMs = 900, s = 0.12, aspect = 4 / 3, twist = 0 } = {}) {
  // twist: the wrist roll (doorknob) a kid adds while leaning, in radians, ramped in with the lean (owner's 0.1.2 report)
  const at = k => ({ cx: 0.5 + v[0] * 0.75 * s / aspect * k, cy: 0.62 + v[1] * 0.75 * s * k, rot: v[0] * 0.3 * k, pitch: -v[1] * 0.3 * k, twist: twist * k });
  const f = (pose, k) => ({ hands: [hand(pose, { ...at(k), s, noise: N, rand: R })] });
  return chain(seq(450, () => f("fist", 0)), seq(300, (i, t, k) => f("fist", ease(k))), seq(holdMs, () => f("fist", 1)), seq(350, () => f("palm", 1)));
}

/** A pinch that engages at (0.5, 0.6), slides `dy` hand-lengths (− = up = closer), holds, then opens into a palm. */
export function pinchSlide(dy, R = rng(13), N = 0.003, { holdMs = 900, s = 0.12, pose = "pinch1" } = {}) {
  const f = (p, k) => ({ hands: [hand(p, { cx: 0.5, cy: 0.6 + dy * s * k, s, noise: N, rand: R })] });
  return chain(seq(450, () => f(pose, 0)), seq(300, (i, t, k) => f(pose, ease(k))), seq(holdMs, () => f(pose, 1)), seq(350, () => f("palm", 1)));
}
