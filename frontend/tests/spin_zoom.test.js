// Zoom, cleanly (owner feedback on 0.1.2: "with the fist move control, i end up zooming in/out"): the fist only turns,
// whatever the wrist rolls; zoom is its own deliberate gesture, the pinch and slide. docs/GESTURES.md §Zoom.
import test from "node:test";
import assert from "node:assert/strict";
import { createGestureClassifier, handPose } from "../src/gesture/classifier.js";
import { gestureIntents } from "../src/gesture/bind.js";
import { pinchFeatures, pinchThresholds, isPinch, createZoomer, createSpinner, shapeAxis } from "../src/gesture/spin.js";
import { PINCH, ZOOM, SPIN } from "../src/gesture/tuning.js";
import { validCal, measurePinch } from "../src/gesture/calibration.js";
import { GESTURES, SCREEN_MAP, helpRows, coachRows } from "../src/gesture/map.js";
import { frameDistance } from "../src/globe.js";
import { hand, seq, chain, rng, FIST_DIRS, fistSpin, pinchSlide } from "./fixtures/gestures/synth.mjs";

const run = (frames, opts) => { const c = createGestureClassifier(opts); return frames.flatMap(f => c.push(f)); };
const types = ev => ev.map(e => e.type);
const ZOOMY = new Set(["pinch_start", "pinch_move", "pinch_end", "zoom", "zoom_end"]);
/** Feed the zoom_rate intents of a classifier run through a zoomer at the frames' own timing: the total zoom factor. */
function zoomOf(ev) {
  const z = createZoomer(); let total = 0, lastT = null;
  for (const e of ev) {
    for (const [name, a] of gestureIntents(e, {})) if (name === "zoom_rate") z.set(a.phase === "end" ? null : a.rate);
    if (lastT != null) total += Math.log(z.step((e.t - lastT) / 1000).factor);
    lastT = e.t;
  }
  for (let i = 0; i < 60; i++) total += Math.log(z.step(1 / 60).factor);   // after release: it must die out, not coast
  return Math.exp(total);
}

// ---------- the owner's exact problem: no zoom during a fist spin, whatever the wrist does ----------
test("fist spin in all 8 directions with wrist roll ±0.5 rad never zooms (and still spins the right way)", () => {
  for (const twist of [0.5, -0.5]) {
    for (const [d, v] of Object.entries(FIST_DIRS)) {
      const ev = run(fistSpin(v, rng(21), 0.003, { twist }));
      assert.deepEqual(types(ev).filter(t => t !== "grab_move"), ["grab_start", "grab_end"], `${d} twist ${twist}`);
      assert.ok(!ev.some(e => ZOOMY.has(e.type)), `${d} twist ${twist}: no zoom event`);
      const intents = ev.flatMap(e => gestureIntents(e, {}));
      assert.ok(!intents.some(([n]) => n === "zoom" || n === "zoom_rate"), `${d} twist ${twist}: no zoom intent`);
      assert.ok(intents.filter(([n]) => n === "spin").every(([, a]) => !("z" in a)), "the spin intent has no zoom axis");
      const held = ev.filter(e => e.type === "grab_move").slice(-10), mx = held.reduce((a, e) => a + e.stick.x, 0) / 10, my = held.reduce((a, e) => a + e.stick.y, 0) / 10;
      if (v[0]) assert.equal(Math.sign(mx), Math.sign(v[0]), `${d} x`); if (v[1]) assert.equal(Math.sign(my), Math.sign(v[1]), `${d} y`);
    }
  }
  const sp = createSpinner(); sp.set({ x: 1, y: 0, z: 1 });
  const st = sp.step(1 / 60);
  assert.ok(!("zoom" in st), "the spinner has no zoom output at all");
  assert.ok(!("twistZoom" in SPIN), "no twist-zoom switch left to turn back on");
  assert.ok(!Object.values(GESTURES).some(g => /twist/i.test(g.name)), "no twist gesture in the map");
});

// ---------- the pinch: what it is, and what it is not ----------
test("pinch pose: thumb tip on a part-bent index; never a count of 1, a point, a fist, a thumbs up or another count", () => {
  for (const side of ["right", "left"]) for (const rot of [-0.25, 0, 0.25]) {
    for (const p of ["pinch1", "ok"]) assert.equal(handPose(hand(p, { side, rot }), 4 / 3).pose, "pinch", `${p} ${side} ${rot}`);
    const pt = handPose(hand("point", { side, rot }), 4 / 3);
    assert.equal(pt.pose, "point"); assert.equal(pt.count, 1, "a raised index with the thumb tucked is 1");
    for (const p of ["fist", "thumbs_up", "thumbs_down", "two", "three", "four", "palm", "relaxed"]) assert.notEqual(handPose(hand(p, { side, rot }), 4 / 3).pose, "pinch", `${p} ${side} ${rot}`);
    assert.equal(handPose(hand("pinch1", { side, rot }), 4 / 3).count, 0, "a pinch never counts");
  }
  // the features that separate them
  const f = n => pinchFeatures(hand(n));
  assert.ok(f("pinch1").d < PINCH.on && f("point").d > PINCH.off, "distance: pinch vs count 1");
  assert.ok(f("fist").idxReach < PINCH.minIndexReach && f("fist").thReach < PINCH.minThumbReach, "reach: a fist folds the index and tucks the thumb");
  assert.ok(f("pinch1").cos < PINCH.maxTipCos, "angle: the thumb and index tips point at each other");
});

test("pinch hysteresis: harder to start than to keep; a half-open pinch never starts one", () => {
  const th = { on: PINCH.on, off: PINCH.off };
  const mid = pinchFeatures(hand("pinch1", { gap: (PINCH.on + PINCH.off) / 2 }));
  assert.ok(mid.d > PINCH.on && mid.d < PINCH.off, `between the thresholds (${mid.d.toFixed(2)})`);
  assert.equal(isPinch(mid, false, th), false, "not a pinch from open");
  assert.equal(isPinch(mid, true, th), true, "still a pinch once pinched");
  assert.equal(isPinch(pinchFeatures(hand("pinch1", { gap: PINCH.off + 0.1 })), true, th), false, "fully open: released");
  // a pinch that flickers half-open frame to frame stays one zoom, never a release and re-grab
  const R = rng(3);
  const fl = chain(seq(500, () => ({ hands: [hand("pinch1")] })), seq(800, i => ({ hands: [hand("pinch1", { gap: i % 2 ? 0.25 : 0, cy: 0.6 - 0.002 * i, noise: 0.002, rand: R })] })));
  const ev = run(fl);
  assert.equal(ev.filter(e => e.type === "pinch_start").length, 1);
  assert.equal(ev.filter(e => e.type === "pinch_end").length, 0);
});

test("pinch thresholds come from the kid's calibrated pinch distance", () => {
  assert.deepEqual(pinchThresholds(null), { on: PINCH.on, off: PINCH.off });
  const small = pinchThresholds(0.06);
  assert.ok(small.on === PINCH.onMin && small.off > small.on);
  const big = pinchThresholds(0.15);
  assert.ok(Math.abs(big.on - 0.24) < 1e-9 && big.off > big.on + 0.08 - 1e-9);
  assert.equal(pinchThresholds(1).on, PINCH.onMax, "clamped");
  // a loose pinch (d 0.2) zooms by default, but not for a kid whose own pinch is very tight
  const loose = chain(seq(900, () => ({ hands: [hand("pinch1", { gap: 0.13 })] })));
  assert.ok(run(loose).some(e => e.type === "pinch_start"));
  assert.ok(!run(loose, { spinCal: { v: 1, left: 1, right: 1, up: 1, down: 1, pitchSign: 1, pinch: 0.05 } }).some(e => e.type === "pinch_start"));
});

// ---------- the slide ----------
test("pinch and slide: up zooms in, down zooms out, at a rate; letting go stops it", () => {
  for (const [dy, sign] of [[-0.8, 1], [0.8, -1]]) {
    const ev = run(pinchSlide(dy));
    assert.deepEqual(types(ev).filter(t => t !== "pinch_move"), ["pinch_start", "pinch_end"], `dy ${dy}`);
    const moves = ev.filter(e => e.type === "pinch_move");
    assert.ok(Math.abs(moves[0].z) < ZOOM.dead, "it engages in the dead zone (engaging never zooms)");
    const held = moves.slice(-10), z = held.reduce((a, e) => a + e.z, 0) / held.length;
    assert.ok(Math.sign(z) === sign && Math.abs(z) > 0.7, `slide ${dy}: z ${z.toFixed(2)}`);
    const f = zoomOf(ev);
    assert.ok(sign > 0 ? f > 1.5 : f < 1 / 1.5, `slide ${dy}: zoom ×${f.toFixed(2)}`);
    assert.ok(!ev.some(e => ["palm_hold", "select", "fingers", "thumbs_up", "swipe_left", "swipe_right"].includes(e.type)), "nothing else fires");
  }
  // a still pinch never zooms
  const still = run(chain(seq(1500, () => ({ hands: [hand("pinch1", { noise: 0.003, rand: rng(5) })] }))));
  assert.ok(Math.abs(Math.log(zoomOf(still))) < 0.01);
  // a brief pinch (shorter than holdMs) never engages
  assert.ok(!run(chain(seq(PINCH.holdMs - 80, () => ({ hands: [hand("pinch1")] })), seq(400, () => ({ hands: [hand("palm")] })))).some(e => e.type === "pinch_start"));
  // a pinch that moves while it engages restarts its hold (it must be meant)
  const sweep = seq(600, (i, t, k) => ({ hands: [hand("pinch1", { cy: 0.75 - 0.3 * k })] }));
  assert.ok(!run(sweep).some(e => e.type === "pinch_start"));
});

test("the pinch never engages while a fist holds, nor within afterFistMs of the fist letting go", () => {
  // fist → (still fist-like) pinch: the grab holds; nothing zooms
  const ev1 = run(chain(seq(600, () => ({ hands: [hand("fist")] })), seq(1200, () => ({ hands: [hand("pinch1")] }))));
  assert.ok(ev1.some(e => e.type === "grab_start") && !ev1.some(e => e.type === "pinch_start"), "a pinch shape inside a held fist is still the fist");
  // fist → open into an ok-sign pinch: the grab ends, and the pinch waits afterFistMs
  const ev2 = run(chain(seq(600, () => ({ hands: [hand("fist")] })), seq(1500, () => ({ hands: [hand("ok")] }))));
  const end = ev2.find(e => e.type === "grab_end"), ps = ev2.find(e => e.type === "pinch_start");
  assert.ok(end && ps, "both happen");
  assert.ok(ps.t - end.t >= PINCH.afterFistMs, `the pinch waited ${ps.t - end.t} ms after the fist`);
  // and a fist made during a pinch ends the pinch first (no zoom and spin at once)
  const ev3 = run(chain(seq(600, () => ({ hands: [hand("pinch1")] })), seq(800, () => ({ hands: [hand("fist")] }))));
  const pe = ev3.find(e => e.type === "pinch_end"), gs = ev3.find(e => e.type === "grab_start");
  assert.ok(!gs || (pe && pe.t <= gs.t), "never both at once");
});

test("a pinch is not a point: the dwell never selects and a 1 is never picked while pinching", () => {
  const ev = run(chain(seq(400, () => ({ hands: [hand("point")] })), seq(2000, () => ({ hands: [hand("pinch1")] }))));
  assert.ok(!ev.some(e => e.type === "select" || e.type === "fingers"));
  assert.ok(ev.some(e => e.type === "point_end"), "the cursor goes away when the pinch starts");
  // and a plain count of 1 still picks
  assert.ok(run(seq(1200, () => ({ hands: [hand("point")] }))).some(e => e.type === "fingers" && e.n === 1));
});

test("the cabin has no zoom: the pinch makes no intent there", () => {
  assert.deepEqual(gestureIntents({ type: "pinch_move", z: 0.8 }, { cabin: true }), []);
  assert.deepEqual(gestureIntents({ type: "pinch_move", z: 0.8 }, {}), [["zoom_rate", { phase: "move", rate: 0.8 }]]);
  assert.deepEqual(gestureIntents({ type: "pinch_end", how: "open" }, {}), [["zoom_rate", { phase: "end", rate: 0, how: "open" }]]);
});

// ---------- the zoomer: one rate control for the pinch, the keys, the triggers and voice ----------
test("zoomer: dead zone, gain, max rate, eased; release stops fast (no coasting zoom)", () => {
  const z = createZoomer();
  z.set(ZOOM.dead * 0.8); for (let i = 0; i < 30; i++) assert.equal(z.step(1 / 60).factor, 1, "inside the dead zone");
  z.set(1); const first = z.step(1 / 60);
  assert.ok(Math.log(first.factor) < ZOOM.maxRate / 60, "eases in");
  for (let i = 0; i < 60; i++) z.step(1 / 60);
  assert.ok(Math.abs(z.rate - ZOOM.maxRate) < 0.01, `max rate (${z.rate.toFixed(3)})`);
  const half = createZoomer(); half.set(0.5); for (let i = 0; i < 60; i++) half.step(1 / 60);
  assert.ok(half.rate > 0 && half.rate < ZOOM.maxRate * 0.5, "half a slide is less than half the rate (gain curve)");
  z.set(null); let coast = 0, t = 0;
  while (z.active && t < 2) { coast += Math.log(z.step(1 / 60).factor); t += 1 / 60; }
  assert.ok(t < 0.6 && coast < 0.12, `stops in ${t.toFixed(2)} s, ${(Math.exp(coast) * 100 - 100).toFixed(1)} % more zoom`);
  assert.equal(shapeAxis(-1), -1);
});

test("zoomer: a quick key tap still zooms a tap step; a held key zooms at the pinch's rate; voice steps are eased", () => {
  const z = createZoomer(); let total = 0;
  z.set(1, { tap: true }); total += Math.log(z.step(1 / 60).factor); z.set(null);
  for (let i = 0; i < 60; i++) total += Math.log(z.step(1 / 60).factor);
  assert.ok(Math.abs(total - Math.log(ZOOM.tapStep)) < 0.03, `tap: ×${Math.exp(total).toFixed(3)}`);
  const h = createZoomer(); let held = 0;
  h.set(-1, { tap: true }); for (let i = 0; i < 120; i++) held += Math.log(h.step(1 / 60).factor); h.set(null);
  for (let i = 0; i < 60; i++) held += Math.log(h.step(1 / 60).factor);
  assert.ok(held < -Math.log(ZOOM.tapStep) * 2, `held 2 s: ×${Math.exp(held).toFixed(2)} (rate control, not a tap)`);
  const v = createZoomer(); v.nudge(ZOOM.voiceStep); let vt = 0, frames = 0, firstStep = 0;
  while (v.active && frames < 120) { const s = Math.log(v.step(1 / 60).factor); if (!frames) firstStep = s; vt += s; frames++; }
  assert.ok(Math.abs(vt - Math.log(ZOOM.voiceStep)) < 1e-6, "the whole step");
  assert.ok(firstStep < vt / 5 && frames >= ZOOM.stepMs / 1000 * 60 - 2, `eased over ~${ZOOM.stepMs} ms`);
  v.nudge(2); v.halt(); assert.equal(v.active, false, "stop ends a step too");
});

// ---------- calibration, the map, framing ----------
test("calibration stores the kid's pinch (optional, validated)", () => {
  const base = { v: 1, left: 1, right: 1, up: 1, down: 1, pitchSign: 1, at: 1 };
  assert.equal(validCal({ ...base, pinch: 0.08 }).pinch, 0.08);
  assert.ok(!("pinch" in validCal(base)), "skipped: no pinch");
  assert.ok(!("pinch" in validCal({ ...base, pinch: 0.9 })), "an odd pinch is dropped, the rest kept");
  assert.equal(measurePinch([0.1, 0.07, 0.09, 0.3, 0.08]), 0.09, "the median: one bad frame doesn't move it");
  assert.equal(measurePinch([]), null);
  assert.equal(measurePinch([0.9, 0.95]), null);
});

test("map + help + coach: 'Fist: turn the Moon · Pinch and slide: zoom'", () => {
  assert.equal(GESTURES.pinch.intent, "zoom_rate");
  assert.equal(SCREEN_MAP.moon.fist, "Turn the Moon");
  assert.match(SCREEN_MAP.moon.pinch, /^Zoom/);
  const rows = helpRows("moon");
  assert.ok(rows.some(r => r.id === "fist" && r.name === "Fist") && rows.some(r => r.id === "pinch" && r.name === "Pinch and slide"));
  assert.deepEqual(coachRows("moon").map(r => r.id).slice(0, 2), ["fist", "pinch"]);
  assert.ok(!helpRows("cabin").some(r => r.id === "pinch"), "no zoom in the cabin");
  assert.ok(!Object.values(SCREEN_MAP).some(m => "twist" in m));
});

test("selecting a place eases the zoom to frame it (small craters closer, seas farther)", () => {
  const crater = frameDistance({ km: 85 }), mid = frameDistance({ km: 400 }), sea = frameDistance({ km: 1145 });
  assert.ok(crater < mid && mid < sea, `${crater} < ${mid} < ${sea}`);
  assert.ok(crater >= 2.2 && sea <= 3.4);
  assert.equal(frameDistance({ kind: "artifact", km: 0.01 }), 2.3);
});
