// Gestures blended into answering (src/input/choices.js, docs/GESTURES.md §Answers): option semantics for thumbs up /
// down, and the classifier's finger count (1-4) with hysteresis.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const { polarity, resolveYesNo } = await import("../src/input/choices.js");
const { createGestureClassifier, handPose } = await import("../src/gesture/classifier.js");
const { gestureIntents } = await import("../src/gesture/bind.js");
const { hand, seq, chain } = await import("./fixtures/gestures/synth.mjs");

const o = label => ({ label });

test("yes / no by what the option means, not where it sits", () => {
  for (const l of ["Yes", "Yeah!", "Do it", "Watch (2 min)", "Done", "I did it", "Shelter now", "Take it", "OK", "Start lesson", "Fly again"]) assert.equal(polarity(o(l)), "yes", l);
  for (const l of ["No", "No thanks", "Skip", "Skip for now", "Not now", "Decline", "Cancel", "Wait a shift", "Not yet"]) assert.equal(polarity(o(l)), "no", l);
  for (const l of ["Sometimes", "Steer left", "Steer right", "Go back", "Start over", "Near side", "Shields up to 30", ""]) assert.equal(polarity(o(l)), null, l);
  // L1 step 2: Yes / No / Sometimes; reordered, the meaning still wins
  assert.equal(resolveYesNo([o("Yes"), o("No"), o("Sometimes")], "yes"), 0);
  assert.equal(resolveYesNo([o("Yes"), o("No"), o("Sometimes")], "no"), 1);
  assert.equal(resolveYesNo([o("Sometimes"), o("No"), o("Yes")], "yes"), 2);
  assert.equal(resolveYesNo([o("Steer left"), o("Steer right")], "yes"), -1);
  assert.equal(resolveYesNo([o("Steer left"), o("Steer right")], "no"), -1);
});

test("explicit hooks (data-yes / data-no / data-intent) beat the words", () => {
  assert.equal(resolveYesNo([o("Yes, but later"), { label: "Go", yes: true }], "yes"), 1);
  assert.equal(resolveYesNo([{ label: "Back to base", intent: "no" }, o("Skip")], "no"), 0);
  assert.equal(polarity({ label: "Launch", intent: "yes" }), "yes");
  assert.equal(polarity({ label: "Abort", no: true }), "no");
});

const N = 0.003;
let seed = 3; const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
const still = (pose, ms, o2 = {}) => seq(ms, () => ({ hands: [hand(pose, { noise: N, rand, ...o2 })] }));
const fingers = evs => evs.filter(e => e.type === "fingers").map(e => e.n);
const run = frames => { const c = createGestureClassifier(); return frames.flatMap(f => c.push(f)); };

test("finger count: the pose geometry (V-spread two / three, four with the thumb tucked; palm is not a count)", () => {
  assert.equal(handPose(hand("point"), 4 / 3).count, 1);
  assert.equal(handPose(hand("two"), 4 / 3).count, 2);
  assert.equal(handPose(hand("three"), 4 / 3).count, 3);
  assert.equal(handPose(hand("four"), 4 / 3).count, 4);
  assert.equal(handPose(hand("palm"), 4 / 3).count, 0, "an open hand with the thumb out is stop, never 5 / 4");
  assert.equal(handPose(hand("relaxed"), 4 / 3).count, 0, "a relaxed half-open hand is not two");
  assert.equal(handPose(hand("fist"), 4 / 3).count, 0);
  assert.equal(handPose(hand("thumbs_up"), 4 / 3).count, 0);
});

test("finger count: held still ~0.5 s fires once; a brief flash, a moving hand and a fist never do", () => {
  assert.deepEqual(fingers(run(still("three", 1200))), [3]);
  assert.deepEqual(fingers(run(still("two", 1500))), [2], "held longer: still once");
  assert.deepEqual(fingers(run(still("three", 300))), [], "too short");
  // passing through 1 and 2 on the way to 3 (each ~150 ms) never fires them
  assert.deepEqual(fingers(run(chain(still("point", 150), still("two", 150), still("three", 1000)))), [3]);
  // a hand moving across the view (a wave) is not a count
  const moving = seq(1500, (i, t, k) => ({ hands: [hand("three", { cx: 0.2 + 0.6 * k, noise: N, rand })] }));
  assert.deepEqual(fingers(run(moving)), []);
  // a fist held (spinning the Moon) never counts, even with a finger flickering out
  assert.deepEqual(fingers(run(chain(still("fist", 800), still("point", 120), still("fist", 400)))), []);
  // lowered and shown again: a second pick (after the cooldown)
  assert.deepEqual(fingers(run(chain(still("two", 900), seq(1200, () => ({})), still("two", 900)))), [2, 2]);
});

test("one finger: a pick only when the index is NOT on a control (else it is point-and-hold)", () => {
  assert.deepEqual(gestureIntents({ type: "fingers", n: 1 }, { pointingAtControl: false }), [["pick", { n: 1, fingers: true }]]);
  assert.deepEqual(gestureIntents({ type: "fingers", n: 1 }, { pointingAtControl: true }), []);
  assert.deepEqual(gestureIntents({ type: "fingers", n: 3 }, { pointingAtControl: true }), [["pick", { n: 3, fingers: true }]]);
});
