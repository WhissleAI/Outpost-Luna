// Camera gestures: the classifier on landmark sequences (true positives, false positives, cooldowns), the gesture →
// intent table, and the hint copy. No camera: recorded / synthesised MediaPipe landmarks (tests/fixtures/gestures).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createGestureClassifier, handPose } from "../src/gesture/classifier.js";
import { gestureIntents, lookTarget } from "../src/gesture/bind.js";
import { hintFor, spokenSummary, CHEATSHEET } from "../src/gesture/guide.js";
import { sequences, hand, face, seq, chain } from "./fixtures/gestures/synth.mjs";

const FIX = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures", "gestures");
const CONTINUOUS = new Set(["point", "point_end", "head", "grab_move"]);
/** Discrete events, plus one grab_move per run of moves (so "grab_start, grab_move, grab_end" reads as a drag). */
function discrete(events, keep = []) {
  const out = [];
  for (const e of events) {
    if (CONTINUOUS.has(e.type) && !keep.includes(e.type)) continue;
    if (CONTINUOUS.has(e.type) && out[out.length - 1] === e.type) continue;
    out.push(e.type);
  }
  return out;
}
const run = (frames, opts) => { const c = createGestureClassifier(opts); return frames.flatMap(f => c.push(f)); };

test("static poses from the synthetic hand", () => {
  const want = { palm: "palm", open: "open", point: "point", fist: "fist", thumbs_up: "thumbs_up", thumbs_down: "thumbs_down", relaxed: "none" };
  for (const [p, pose] of Object.entries(want)) {
    for (const side of ["right", "left"]) for (const rot of [-0.25, 0, 0.25]) {
      assert.equal(handPose(hand(p, { side, rot }), 4 / 3).pose, pose, `${p} ${side} rot ${rot}`);
    }
  }
});

test("every named sequence produces exactly its expected gestures", () => {
  for (const [name, s] of Object.entries(sequences())) {
    const keep = s.expect.filter(e => CONTINUOUS.has(e));
    assert.deepEqual(discrete(run(s.frames), keep), s.expect, name + (s.note ? ` (${s.note})` : ""));
  }
});

test("every JSON fixture (recorded format) produces its expected gestures", () => {
  const files = fs.readdirSync(FIX).filter(f => f.endsWith(".json"));
  assert.ok(files.length >= 10, "fixtures present");
  for (const f of files) {
    const s = JSON.parse(fs.readFileSync(path.join(FIX, f), "utf8"));
    const keep = s.expect.filter(e => CONTINUOUS.has(e));
    assert.deepEqual(discrete(run(s.frames), keep), s.expect, f);
  }
});

test("cooldown: a palm held for 3 s is one stop; shown again after a release it is a second", () => {
  const held = seq(3000, () => ({ hands: [hand("palm")] }));
  assert.deepEqual(discrete(run(held)), ["palm_hold"]);
  const again = chain(seq(800, () => ({ hands: [hand("palm")] })), seq(1200, () => ({})), seq(800, () => ({ hands: [hand("palm")] })));
  assert.deepEqual(discrete(run(again)), ["palm_hold", "palm_hold"]);
});

test("cooldown: a thumb held up is one yes; up, down quickly is yes then no only after the cooldown", () => {
  assert.deepEqual(discrete(run(seq(4000, () => ({ hands: [hand("thumbs_up")] })))), ["thumbs_up"]);
  const fast = chain(seq(500, () => ({ hands: [hand("thumbs_up")] })), seq(500, () => ({ hands: [hand("thumbs_down")] })));
  assert.deepEqual(discrete(run(fast)), ["thumbs_up"], "thumbs down inside the 1.2 s cooldown is ignored");
  const slow = chain(seq(500, () => ({ hands: [hand("thumbs_up")] })), seq(400, () => ({})), seq(900, () => ({ hands: [hand("thumbs_down")] })));
  assert.deepEqual(discrete(run(slow)), ["thumbs_up", "thumbs_down"]);
});

test("swipe: one swipe is one step; the return stroke is ignored; a fist sweep is not a swipe", () => {
  const S = sequences();
  assert.deepEqual(discrete(run(S.swipe_left_return.frames)), ["swipe_left"]);
  assert.deepEqual(discrete(run(S.two_swipes.frames)), ["swipe_left", "swipe_left"]);
  const fistSweep = seq(350, (i, t, k) => ({ hands: [hand("fist", { cx: 0.75 - 0.45 * k })] }));
  assert.ok(!discrete(run(fistSweep)).some(e => e.startsWith("swipe")), "a fist moving fast drags, it doesn't swipe");
});

test("sensitivity: a short swipe counts only when sensitivity is Quick", () => {
  const short = chain(seq(150, () => ({ hands: [hand("open", { cx: 0.6 })] })), seq(300, (i, t, k) => ({ hands: [hand("open", { cx: 0.6 - 0.17 * k })] })));
  assert.deepEqual(discrete(run(short, { sensitivity: 0.6 })), []);
  assert.deepEqual(discrete(run(short, { sensitivity: 1.4 })), ["swipe_left"]);
});

test("point + dwell: the ring fills over 0.8 s, selects once, and re-arms only after moving away", () => {
  const ev = run(seq(2500, () => ({ hands: [hand("point", { cx: 0.5, cy: 0.75 })] })));
  assert.equal(ev.filter(e => e.type === "select").length, 1);
  const pts = ev.filter(e => e.type === "point");
  assert.ok(pts.some(p => p.progress > 0.4 && p.progress < 0.9), "progress is reported while dwelling");
  const sel = ev.find(e => e.type === "select");
  assert.ok(sel.x > 0 && sel.x < 1 && sel.y > 0 && sel.y < 1);
  const moved = chain(seq(1100, () => ({ hands: [hand("point", { cx: 0.35 })] })), seq(1100, () => ({ hands: [hand("point", { cx: 0.65 })] })));
  assert.equal(run(moved).filter(e => e.type === "select").length, 2);
});

test("grab: drag deltas follow the hand; releasing ends the grab", () => {
  const ev = run(sequences().grab_drag.frames);
  const dx = ev.filter(e => e.type === "grab_move").reduce((a, e) => a + e.dx, 0);
  assert.ok(dx > 0.1, `dragged right (${dx.toFixed(3)})`);
  assert.equal(ev.filter(e => e.type === "grab_start").length, 1);
  assert.equal(ev[ev.length - 1].type, "grab_end");
});

test("head: look follows the head; lean in / back; only the largest face counts", () => {
  const ev = run(sequences().look_right.frames);
  const last = ev.filter(e => e.type === "head").pop();
  assert.ok(last.x > 0.3, `looked right (${last.x.toFixed(2)})`);
  assert.deepEqual(discrete(run(sequences().lean_in_back.frames)), ["lean_in", "lean_back"]);
  // a big face stays still while a small one behind moves a lot: no look change
  const two = seq(800, (i, t, k) => ({ faces: [face({ w: 0.2 }), face({ cx: 0.2 + 0.6 * k, w: 0.07 })] }));
  assert.ok(!run(two).some(e => e.type === "head" && Math.abs(e.x) > 0.05));
  assert.deepEqual(discrete(run(sequences().lean_in_back.frames, { headLook: false })), [], "head-look off: nothing");
});

test("phase 2 is off by default; when on, raise hand and two-hand pinch work", () => {
  const raise = seq(1500, () => ({ hands: [hand("palm", { cy: 0.22, s: 0.1 })], faces: [face({ cy: 0.45, w: 0.2 })] }));
  assert.deepEqual(discrete(run(raise)), ["palm_hold"], "off: a raised palm is just stop");
  assert.deepEqual(discrete(run(raise, { phase2: true })), ["raise_hand"]);
  const pinch = seq(800, (i, t, k) => ({ hands: [hand("pinch", { cx: 0.35 - 0.1 * k, side: "right" }), hand("pinch", { cx: 0.65 + 0.1 * k, side: "left" })] }));
  const z = run(pinch, { phase2: true }).filter(e => e.type === "zoom");
  assert.ok(z.length && z.every(e => e.factor > 1), "spreading the hands zooms in");
  assert.equal(run(pinch).filter(e => e.type === "zoom").length, 0, "off by default");
});

test("handedness: the preferred hand wins a tie", () => {
  const both = seq(800, () => ({ hands: [hand("thumbs_down", { side: "right", cx: 0.3 }), hand("thumbs_up", { side: "left", cx: 0.7 })] }));
  assert.deepEqual(discrete(run(both, { handed: "left" })), ["thumbs_up"]);
  assert.deepEqual(discrete(run(both, { handed: "right" })), ["thumbs_down"]);
});

test("gesture → intent table", () => {
  const vw = 1000, vh = 800;
  assert.deepEqual(gestureIntents({ type: "palm_hold" }), [["stop", {}]]);
  assert.deepEqual(gestureIntents({ type: "thumbs_up" }), [["yes", {}]]);
  assert.deepEqual(gestureIntents({ type: "thumbs_down" }), [["no", {}]]);
  assert.deepEqual(gestureIntents({ type: "swipe_left" }), [["next", {}]]);
  assert.deepEqual(gestureIntents({ type: "swipe_right" }), [["prev", {}]]);
  assert.deepEqual(gestureIntents({ type: "select", x: 0.5, y: 0.25 }, { vw, vh }), [["select", { x: 500, y: 200 }]]);
  assert.deepEqual(gestureIntents({ type: "grab_move", dx: 0.1, dy: 0 }), [["rotate", { phase: "move", dx: 0.1, dy: 0 }]]);
  // head intents only in the cabin; lean in opens the looked-at panel only from the seat; lean back only from a panel
  assert.deepEqual(gestureIntents({ type: "head", x: 0.4, y: 0 }, { cabin: false }), []);
  assert.deepEqual(gestureIntents({ type: "head", x: 0.4, y: 0 }, { cabin: true }), [["look", { x: 0.4, y: 0 }]]);
  assert.deepEqual(gestureIntents({ type: "lean_in", x: -0.6 }, { cabin: true, panel: "seat" }), [["panel_open", { panel: "habitat" }]]);
  assert.deepEqual(gestureIntents({ type: "lean_in", x: 0 }, { cabin: true, panel: "comm" }), []);
  assert.deepEqual(gestureIntents({ type: "lean_back" }, { cabin: true, panel: "power" }), [["panel_back", {}]]);
  assert.deepEqual(gestureIntents({ type: "lean_back" }, { cabin: true, panel: "seat" }), []);
  assert.deepEqual(gestureIntents({ type: "raise_hand" }, { phase2: false }), []);
  assert.deepEqual([lookTarget(-0.5), lookTarget(0), lookTarget(0.5)], ["habitat", "power", "comm"]);
});

test("hints: one short, emoji-free line per screen; a confirm wins", () => {
  const screens = [{ screen: "lesson_done" }, { screen: "patch" }, { screen: "lesson", step_type: "tap" }, { screen: "lesson", step_options: ["a", "b"] },
    { screen: "map" }, { screen: "brief" }, { screen: "debrief" }, { screen: "cabin" }, { screen: "library" }];
  for (const s of screens) {
    const h = hintFor(s); assert.ok(h, JSON.stringify(s));
    assert.ok(h.text.split(" ").length <= 6, h.text);
    assert.ok(!/\p{Extended_Pictographic}/u.test(h.text), "no emoji");
  }
  assert.equal(hintFor({ screen: "map" }, { confirm: true }).text, "Thumbs up to confirm");
  assert.equal(hintFor({ screen: "cabin" }, { headLook: false }).text, "Swipe to change the view");
  assert.ok(CHEATSHEET.every(r => !/\p{Extended_Pictographic}/u.test(r.name + r.does)));
  assert.match(spokenSummary({ cabin: true }), /lean in/);
});

test("speed: the classifier keeps up (≤ 0.1 ms a frame)", () => {
  const frames = sequences().point_dwell.frames.concat(sequences().swipe_left.frames, sequences().lean_in_back.frames);
  const c = createGestureClassifier(); const t0 = performance.now();
  for (let r = 0; r < 20; r++) frames.forEach(f => c.push({ ...f, t: f.t + r * 10000 }));
  const per = (performance.now() - t0) / (frames.length * 20);
  assert.ok(per < 0.1, `${per.toFixed(4)} ms/frame`);
});
