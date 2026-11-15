// Fist spin (docs/GESTURES.md §Fist spin): the rate-control math (dead zone, gain curve, max speed, easing, release
// momentum), the One Euro filter, the fist's hysteresis, all 8 directions through the classifier, the calibration
// (measurement and storage) and the one gesture → action map.
import test from "node:test";
import assert from "node:assert/strict";
import { shapeStick, shapeAxis, createSpinner, oneEuro, fistReading, rawStick, calibrated } from "../src/gesture/spin.js";
import { SPIN, DEFAULTS, CALIBRATION } from "../src/gesture/tuning.js";
import { createGestureClassifier } from "../src/gesture/classifier.js";
import { createFistCalibration, loadSpinCal, saveSpinCal, clearSpinCal, validCal, SPIN_CAL_KEY } from "../src/gesture/calibration.js";
import { GESTURES, SCREEN_MAP, EVENT_GESTURE, screenKey, helpRows, coachRows } from "../src/gesture/map.js";
import { gestureIntents } from "../src/gesture/bind.js";
import { hand, seq, chain, rng, sequences, FIST_DIRS, fistSpin } from "./fixtures/gestures/synth.mjs";

const run = (frames, opts) => { const c = createGestureClassifier(opts); return frames.flatMap(f => c.push(f)); };
const memStore = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), m }; };
/** Run a spinner for `ms` at 60 fps; returns the total turn and the last step. */
function spinFor(sp, ms, opts) { let dx = 0, dy = 0, last = null; for (let t = 0; t < ms; t += 1000 / 60) { last = sp.step(1 / 60, opts); dx += last.dx; dy += last.dy; } return { dx, dy, last }; }

// ---------- rate-control math ----------
test("dead zone: a small wobble never spins; just past it is slow, full stick is 1", () => {
  assert.deepEqual(shapeStick({ x: 0.1, y: 0.05 }), { x: 0, y: 0, m: 0 });
  assert.equal(shapeStick({ x: SPIN.dead, y: 0 }).m, 0);
  const just = shapeStick({ x: SPIN.dead + 0.05, y: 0 }).m;
  assert.ok(just > 0 && just < 0.05, `just past the dead zone is slow (${just})`);
  assert.equal(+shapeStick({ x: 1, y: 0 }).m.toFixed(6), 1);
  assert.equal(+shapeStick({ x: 3, y: 4 }).m.toFixed(6), 1, "clamped at full");
  assert.equal(shapeAxis(0.2), 0, "twist has its own, bigger dead zone");
});

test("gain curve: monotonic, fine near the middle (expo), direction kept", () => {
  let prev = -1;
  for (let m = 0; m <= 1.0001; m += 0.05) { const k = shapeStick({ x: m, y: 0 }).m; assert.ok(k >= prev, `monotonic at ${m}`); prev = k; }
  const mid = shapeStick({ x: (1 + SPIN.dead) / 2, y: 0 }).m;
  assert.ok(mid < 0.5, `half-way stick is less than half speed (${mid.toFixed(3)})`);
  const d = shapeStick({ x: -0.6, y: 0.6 });
  assert.ok(d.x < 0 && d.y > 0 && Math.abs(Math.abs(d.x) - Math.abs(d.y)) < 1e-9, "a diagonal stays diagonal");
});

test("spinner: eases up to the max speed (never above it, never a jolt) and holds it", () => {
  const sp = createSpinner(); sp.set({ x: 1, y: 0 });
  const first = sp.step(1 / 60);
  assert.ok(first.speed <= SPIN.maxAccel / 60 + 1e-9, "acceleration limited on the first frame");
  const { last } = spinFor(sp, 1500);
  assert.ok(Math.abs(last.speed - SPIN.maxSpeed) < 0.02, `reaches max speed (${last.speed.toFixed(3)})`);
  spinFor(sp, 1000);
  assert.ok(sp.velocity.speed <= SPIN.maxSpeed + 1e-9, "never above it");
  assert.ok(last.vx > 0 && Math.abs(last.vy) < 1e-9, "fist right: surface turns right");
  const half = createSpinner(); half.set({ x: 0.6, y: 0 }); spinFor(half, 1500);
  assert.ok(half.velocity.speed < SPIN.maxSpeed * 0.5, "a smaller lean is slower (rate, not position)");
});

test("spinner: zoomed in turns slower; invert flips; a long frame never jumps", () => {
  const near = createSpinner(); near.set({ x: 1, y: 0 }); spinFor(near, 1500, { distance: 1.6 });
  const far = createSpinner(); far.set({ x: 1, y: 0 }); spinFor(far, 1500, { distance: SPIN.refDistance });
  assert.ok(near.velocity.speed < far.velocity.speed * 0.5);
  const inv = createSpinner({ invert: true }); inv.set({ x: 1, y: 0 }); spinFor(inv, 500);
  assert.ok(inv.velocity.vx < 0);
  const j = createSpinner(); j.set({ x: 1, y: 0 }); const s = j.step(5);
  assert.ok(s.dx <= SPIN.maxAccel * 0.1 * 0.1 + 1e-9, "dt is capped at 0.1 s");
});

test("release momentum: keeps a share of the speed, decays smoothly to a stop", () => {
  const sp = createSpinner(); sp.set({ x: 0, y: -1 }); spinFor(sp, 1500);
  const v0 = sp.velocity.speed; sp.set(null);
  const a = sp.step(1 / 60);
  assert.ok(Math.abs(a.speed - v0 * SPIN.releaseCarry * Math.exp(-1 / 60 / SPIN.decayTau)) < 1e-6, "carry then decay");
  assert.ok(a.vy < 0, "still turning the same way");
  let prev = a.speed, coast = 0, t = 0;
  while (sp.active && t < 5) { const s = sp.step(1 / 60); assert.ok(s.speed <= prev); prev = s.speed; coast += Math.abs(s.dy); t += 1 / 60; }
  assert.ok(!sp.active && t < 2.5, `stopped after ${t.toFixed(2)} s`);
  const expect = v0 * SPIN.releaseCarry * SPIN.decayTau;
  assert.ok(coast > expect * 0.6 && coast < expect * 1.2, `a little momentum: ${(coast * 180 / Math.PI).toFixed(1)}° of coast`);
  sp.set({ x: 1, y: 0 }); spinFor(sp, 300); sp.halt();
  assert.ok(!sp.active && sp.velocity.speed === 0, "halt (stop) kills the momentum");
});

test("twist zooms only past its dead zone, and only while held", () => {
  const sp = createSpinner(); sp.set({ x: 0, y: 0, z: 0.2 });
  assert.equal(sp.step(1 / 60).zoom, 1);
  sp.set({ x: 0, y: 0, z: 1 }); const z = sp.step(0.1).zoom;
  assert.ok(Math.abs(Math.log(z) - SPIN.zoomRate * 0.1) < 1e-9, "full twist: zoomRate per second");
  sp.set({ x: 0, y: 0, z: -1 }); assert.ok(sp.step(0.1).zoom < 1, "the other way zooms out");
  sp.set(null); assert.equal(sp.step(0.1).zoom, 1);
});

test("One Euro: cuts jitter on a still hand, follows a fast move with little lag", () => {
  const f = oneEuro(DEFAULTS.fistFilter), R = rng(3);
  let raw = 0, filt = 0;
  for (let i = 0; i < 90; i++) { const v = 0.5 + (R() - 0.5) * 0.1, o = f(v, i / 30); if (i > 10) { raw += Math.abs(v - 0.5); filt += Math.abs(o - 0.5); } }
  assert.ok(filt < raw * 0.6, `jitter down (${(filt / raw).toFixed(2)}×)`);
  const g = oneEuro(DEFAULTS.fistFilter); let o = 0;
  for (let i = 0; i < 30; i++) o = g(i < 10 ? 0 : 1, i / 30);
  assert.ok(o > 0.9, `a step is followed within ~0.6 s (${o.toFixed(2)})`);
});

// ---------- the fist through the classifier ----------
test("fist reading: lean, tilt and twist read from the landmarks", () => {
  const r0 = fistReading(hand("fist")), rR = fistReading(hand("fist", { rot: 0.3 })), rP = fistReading(hand("fist", { pitch: 0.3 })), rT = fistReading(hand("fist", { twist: 0.4 }));
  assert.ok(Math.abs(r0.roll) < 0.01 && Math.abs(rR.roll - 0.3) < 0.02, "roll");
  assert.ok(rP.pitch > 0.2, `pitch toward the screen (${rP.pitch.toFixed(2)})`);
  assert.ok(rT.twist > 0.2, `twist (${rT.twist.toFixed(2)})`);
  // the synthetic left hand is the mirror image: the same anatomical turn is the opposite knob direction on screen,
  // so it reads as the opposite twist (a knob turned clockwise zooms in, whichever hand turns it)
  const lT = fistReading(hand("fist", { twist: 0.4, side: "left" }));
  assert.ok(lT.twist < -0.2, "the mirrored turn reads as the other knob direction");
  const st = rawStick(rR, r0);
  assert.ok(st.x > 0.4 && Math.abs(st.y) < 0.2, "a lean right is stick right");
});

test("all 8 directions: the stick points the way the fist went; grab, move, release once each", () => {
  for (const [d, v] of Object.entries(FIST_DIRS)) {
    const ev = run(fistSpin(v));
    const kinds = ev.map(e => e.type).filter(t => t !== "grab_move" && t !== "point" && t !== "point_end");
    assert.deepEqual(kinds, ["grab_start", "grab_end"], d);
    const moves = ev.filter(e => e.type === "grab_move"), held = moves.slice(-12);
    const mx = held.reduce((a, e) => a + e.stick.x, 0) / held.length, my = held.reduce((a, e) => a + e.stick.y, 0) / held.length;
    if (v[0]) assert.ok(Math.sign(mx) === Math.sign(v[0]) && Math.abs(mx) > 0.5, `${d}: x ${mx.toFixed(2)}`); else assert.ok(Math.abs(mx) < 0.25, `${d}: no x (${mx.toFixed(2)})`);
    if (v[1]) assert.ok(Math.sign(my) === Math.sign(v[1]) && Math.abs(my) > 0.5, `${d}: y ${my.toFixed(2)}`); else assert.ok(Math.abs(my) < 0.25, `${d}: no y (${my.toFixed(2)})`);
    assert.equal(ev[ev.length - 1].how, "open", `${d}: released by opening the hand`);
    // the very first moves are near the neutral pose: grabbing never spins by itself
    assert.ok(Math.hypot(moves[0].stick.x, moves[0].stick.y) < SPIN.dead, `${d}: grab starts in the dead zone`);
  }
});

test("fist hysteresis: a flickering finger or a thumb popping out never lets go, and never says yes", () => {
  const R = rng(5);
  const frames = chain(seq(400, () => ({ hands: [hand("fist")] })),
    seq(1200, i => ({ hands: [hand(i % 4 === 0 ? "point" : i % 7 === 0 ? "thumbs_up" : i % 9 === 0 ? "open" : "fist", { cx: 0.55, noise: 0.003, rand: R })] })));
  const ev = run(frames);
  assert.equal(ev.filter(e => e.type === "grab_start").length, 1);
  assert.equal(ev.filter(e => e.type === "grab_end").length, 0, "still holding");
  assert.ok(!ev.some(e => ["thumbs_up", "palm_hold", "swipe_left", "swipe_right", "select"].includes(e.type)), "nothing else fires while the fist holds");
  // a brief fist (< grabHoldMs) never grabs
  assert.ok(!run(chain(seq(150, () => ({ hands: [hand("fist")] })), seq(400, () => ({ hands: [hand("open")] })))).some(e => e.type === "grab_start"));
  // the hand gone ends the grab
  const lost = run(chain(seq(500, () => ({ hands: [hand("fist")] })), seq(500, () => ({}))));
  assert.equal(lost[lost.length - 1].type, "grab_end"); assert.equal(lost[lost.length - 1].how, "lost");
});

test("after a release, the open hand is not a stop and not a swipe", () => {
  const R = rng(9);
  const release = chain(seq(500, () => ({ hands: [hand("fist", { cx: 0.6 })] })), seq(1500, () => ({ hands: [hand("palm", { cx: 0.6, noise: 0.002, rand: R })] })));
  assert.ok(!run(release).some(e => e.type === "palm_hold"), "a palm held after letting go is not stop");
  const flick = chain(seq(500, () => ({ hands: [hand("fist", { cx: 0.7 })] })), seq(250, (i, t, k) => ({ hands: [hand("open", { cx: 0.7 - 0.45 * k })] })));
  assert.ok(!run(flick).some(e => e.type.startsWith("swipe")), "opening with a flick is not a swipe");
  // shown again later (a fresh palm) it is a stop
  const again = chain(release, seq(600, () => ({})), seq(800, () => ({ hands: [hand("palm")] })));
  assert.ok(run(again).some(e => e.type === "palm_hold"));
});

test("cross cooldown: one movement fires one discrete gesture", () => {
  const S = sequences();
  // a swipe straight into a thumbs up: the thumb counts only after crossCooldownMs
  const ev = run(chain(S.swipe_left.frames, seq(DEFAULTS.thumbHoldMs - 50, () => ({ hands: [hand("thumbs_up")] }))));
  assert.deepEqual(ev.filter(e => !["point", "point_end", "head"].includes(e.type)).map(e => e.type), ["swipe_left"]);
});

test("not confidently present: a low-score hand or face does nothing", () => {
  assert.deepEqual(run(seq(1500, () => ({ hands: [{ ...hand("palm"), score: 0.4 }] }))), []);
  const c = createGestureClassifier();
  assert.ok(!seq(800, () => ({ faces: [{ box: { x: 0.4, y: 0.2, w: 0.2, h: 0.27 }, kp: [[0.46, 0.3], [0.54, 0.3], [0.5, 0.35]], score: 0.3 }] })).flatMap(f => c.push(f)).length);
});

test("calibration applies per direction: the stick is scaled by the kid's own range that way", () => {
  const cal = { v: 1, left: 0.5, right: 1, up: 1, down: 0.5, pitchSign: 1 };
  assert.deepEqual(calibrated({ x: -0.5, y: 0.25, z: 0 }, cal), { x: -1, y: 0.5, z: 0 });
  assert.deepEqual(calibrated({ x: 0.5, y: -0.5, z: 0.3 }, null), { x: 0.5, y: -0.5, z: 0.3 });
  const ev = run(fistSpin(FIST_DIRS.left, rng(2), 0.003), { spinCal: { ...cal, left: 2 } }).filter(e => e.type === "grab_move").slice(-10);
  const evD = run(fistSpin(FIST_DIRS.left, rng(2), 0.003)).filter(e => e.type === "grab_move").slice(-10);
  assert.ok(Math.abs(ev[0].stick.x) < Math.abs(evD[0].stick.x) * 0.6, `a kid with a big range needs a bigger lean (${ev[0].stick.x.toFixed(2)} vs ${evD[0].stick.x.toFixed(2)})`);
});

// ---------- calibration ----------
function calibrateWith(shape) {   // shape: per direction, how far the kid moves (k) and which way they tilt for "up"
  const c = createFistCalibration(); const R = rng(4);
  c.begin(fistReading(hand("fist", { cx: 0.5, cy: 0.62 })));
  let t = 0;
  for (const dir of ["left", "right", "up", "down"]) {
    const v = FIST_DIRS[dir], k = shape[dir];
    let done = false;
    for (let i = 0; i < 200 && !done; i++) {
      t += 33; const e = Math.min(1, i / 10);
      const pitch = (shape.flipPitch ? 1 : -1) * v[1] * 0.3 * k * e;
      const r = fistReading(hand("fist", { cx: 0.5 + v[0] * 0.75 * 0.09 * k * e, cy: 0.62 + v[1] * 0.75 * 0.12 * k * e, rot: v[0] * 0.3 * k * e, pitch, noise: 0.002, rand: R }));
      done = c.feed(dir, r, t).done;
    }
    assert.ok(done, dir);
  }
  return c.result(123);
}
test("calibration measures each kid's comfortable range and the tilt direction", () => {
  const full = calibrateWith({ left: 1, right: 1, up: 1, down: 1 });
  const small = calibrateWith({ left: 0.4, right: 1, up: 0.5, down: 1 });
  assert.ok(validCal(full) && validCal(small));
  assert.ok(small.left < full.left * 0.7, `small left range (${small.left} < ${full.left})`);
  assert.ok(small.up < full.up * 0.8, `small up range (${small.up} < ${full.up})`);
  assert.ok(Math.abs(small.right - full.right) < 0.1);
  assert.equal(full.pitchSign, 1);
  assert.equal(calibrateWith({ left: 1, right: 1, up: 1, down: 1, flipPitch: true }).pitchSign, -1, "a kid who tilts the other way for up");
  // no hand movement at all: each direction times out and keeps the default
  const c = createFistCalibration(); const r0 = fistReading(hand("fist")); c.begin(r0);
  let t = 0, d = false; while (!d) { t += 33; d = c.feed("left", r0, t).done; }
  assert.ok(t >= CALIBRATION.stepMaxMs);
  assert.equal(c.result().left, 1);
});

test("calibration storage: saved locally, validated, cleared; junk is ignored", () => {
  const st = memStore();
  assert.equal(loadSpinCal(st), null, "none yet: the defaults");
  const cal = { v: 1, left: 0.8, right: 0.9, up: 0.7, down: 1.1, pitchSign: -1, at: 5 };
  assert.ok(saveSpinCal(cal, st));
  assert.deepEqual(loadSpinCal(st), cal);
  st.setItem(SPIN_CAL_KEY, "{not json"); assert.equal(loadSpinCal(st), null);
  st.setItem(SPIN_CAL_KEY, JSON.stringify({ ...cal, left: 0.01 })); assert.equal(loadSpinCal(st), null, "out of range");
  st.setItem(SPIN_CAL_KEY, JSON.stringify({ ...cal, v: 0 })); assert.equal(loadSpinCal(st), null, "old version");
  assert.equal(saveSpinCal({ ...cal, pitchSign: 0 }, st), false);
  clearSpinCal(st); assert.equal(loadSpinCal(st), null);
  const throwing = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
  assert.equal(loadSpinCal(throwing), null); assert.equal(saveSpinCal(cal, throwing), false); clearSpinCal(throwing);
});

// ---------- the one gesture → action map ----------
test("map: same gesture, same intent on every screen; bind.js follows the map", () => {
  const evs = { palm_hold: "palm", thumbs_up: "thumbs_up", thumbs_down: "thumbs_down", swipe_left: "swipe_left", swipe_right: "swipe_right" };
  for (const [ev, g] of Object.entries(evs)) {
    for (const ctx of [{}, { cabin: true }, { cabin: true, panel: "comm" }]) assert.equal(gestureIntents({ type: ev }, ctx)[0][0], GESTURES[g].intent, ev);
  }
  assert.equal(gestureIntents({ type: "select", x: 0, y: 0 })[0][0], GESTURES.point.intent);
  assert.equal(gestureIntents({ type: "grab_move", stick: { x: 1, y: 0 } })[0][0], GESTURES.fist.intent);
  for (const [k, m] of Object.entries(SCREEN_MAP)) {
    for (const [g, does] of Object.entries(m)) {
      assert.ok(GESTURES[g], `${k}.${g} is a known gesture`);
      assert.ok(does.split(" ").length <= 6, `${k}.${g}: "${does}" ≤ 6 words`);
      assert.ok(!/\p{Extended_Pictographic}/u.test(does));
    }
    if (m.palm) assert.match(m.palm, /^(Stop|Pause)/, `${k}: an open hand always stops or pauses`);
    if (m.thumbs_up) assert.match(m.thumbs_up, /^Yes/, `${k}: thumbs up is always yes`);
    if (m.thumbs_down) assert.match(m.thumbs_down, /^No/, `${k}: thumbs down is always no`);
  }
  for (const g of Object.values(EVENT_GESTURE)) assert.ok(GESTURES[g]);
  assert.ok(SCREEN_MAP.video && SCREEN_MAP.video.palm, "the video overlay hook: open hand = pause");
});

test("map: screen keys, help rows and coach marks", () => {
  assert.equal(screenKey({ screen: "library" }), "moon");
  assert.equal(screenKey({ screen: "map" }), "moon");
  assert.equal(screenKey({ screen: "lesson", step_type: "tap" }), "lesson");
  assert.equal(screenKey({ screen: "brief" }), "menu");
  assert.equal(screenKey({ screen: "cabin" }, { cabin: true }), "cabin");
  assert.equal(screenKey({ screen: "map" }, { settings: true }), "settings");
  assert.equal(screenKey({ screen: "cabin" }, { cabin: true, video: true }), "video");
  const moon = helpRows("moon").map(r => r.id);
  assert.ok(moon.includes("fist") && moon.includes("twist") && !moon.includes("pinch2") && !moon.includes("head"));
  assert.ok(helpRows("moon", { phase2: true }).some(r => r.id === "pinch2"));
  assert.ok(!helpRows("cabin", { headLook: false }).some(r => r.id === "head" || r.id === "lean"));
  for (const k of Object.keys(SCREEN_MAP)) assert.ok(coachRows(k).length >= 1 && coachRows(k).length <= 3, k);
});
