// Flows (fix/flow-resume): every multi-step flow pauses with a reason and resumes by voice, gesture and keys; and the
// open-hand stop needs a deliberate, still, camera-facing palm (gesture/tuning.js palm*). No DOM, no camera.
import test from "node:test";
import assert from "node:assert/strict";
import { createGestureClassifier } from "../src/gesture/classifier.js";
import { DEFAULTS } from "../src/gesture/tuning.js";
import { hand, seq, chain } from "./fixtures/gestures/synth.mjs";
import { emitIntent } from "../src/input/intents.js";
import { registerFlow, installFlowIntents, flowWord, flowFrame, flowEvents, flowLog, pauseCaption, currentFlow } from "../src/flows.js";

const stops = evs => evs.filter(e => e.type === "palm_hold");
const run = (frames, setup) => { const c = createGestureClassifier(); if (setup) setup(c); return frames.flatMap(f => c.push(f)); };
const still = (ms, o = {}, t0 = 1000) => seq(ms, () => ({ hands: [hand("palm", { noise: 0.002, ...o })] }), { t0 });

// ---- the open-hand stop: timing ----
test("tuning: stop needs ~600 ms, a still hand, a camera-facing palm and a 1 s arm after the camera turns on", () => {
  assert.equal(DEFAULTS.palmHoldMs, 600);
  assert.ok(DEFAULTS.palmArmMs >= 1000);
  assert.ok(DEFAULTS.palmMaxSpeed <= 0.8 && DEFAULTS.palmMaxDrift <= 0.3 && DEFAULTS.palmMinFacing >= 0.5);
});

test("a palm held 450 ms is not a stop; held 750 ms it is, once, and only after ~600 ms", () => {
  assert.equal(stops(run(still(450))).length, 0);
  const ev = stops(run(still(750)));
  assert.equal(ev.length, 1);
  assert.ok(ev[0].t - 1000 >= 600, `fired at +${ev[0].t - 1000} ms`);
});

test("the first second after the camera turns on: a hand already up never stops; held on after it, it does", () => {
  // the camera starts (cameraOn), the kid's open hand is in frame from the first frame
  const short = stops(run(still(1300), c => c.cameraOn()));
  assert.equal(short.length, 0, "1.3 s: the arm window (1 s) + less than the 600 ms hold");
  const long = stops(run(still(2000), c => c.cameraOn()));
  assert.equal(long.length, 1);
  assert.ok(long[0].t - 1000 >= DEFAULTS.palmArmMs + DEFAULTS.palmHoldMs - 40, `fired at +${long[0].t - 1000} ms`);
  // without cameraOn (a hand raised later) the normal hold applies
  assert.equal(stops(run(still(800))).length, 1);
});

test("a hand moving through the frame never stops, even slowly", () => {
  // a slow pass: 0.2 of the image across 1.5 s (the hand is 0.12 tall: ~1.1 hand-lengths a second, then slower)
  for (const [dx, ms] of [[0.2, 1500], [0.12, 1600], [0.3, 1200]]) {
    const pass = seq(ms, (i, t, k) => ({ hands: [hand("palm", { cx: 0.4 + dx * k, noise: 0.002 })] }));
    assert.equal(stops(run(pass)).length, 0, `dx ${dx} over ${ms} ms`);
  }
  // drift: still enough frame to frame, but wandering ~0.85 hand-lengths (0.6 a second)
  const drift = seq(1400, (i, t, k) => ({ hands: [hand("palm", { cx: 0.5 + 0.1 * k, noise: 0.001 })] }));
  assert.equal(stops(run(drift)).length, 0, "a slow drift is not a hold");
});

test("an edge-on hand (palm not facing the camera) is not a stop", () => {
  assert.equal(stops(run(still(1500, { twist: 1.2 }))).length, 0);
  assert.equal(stops(run(still(1500, { twist: 0.4 }))).length, 1, "a little turned is still a stop sign");
});

test("a moving hand that comes to rest stops ~600 ms after it is still", () => {
  const frames = chain(seq(600, (i, t, k) => ({ hands: [hand("palm", { cx: 0.3 + 0.25 * k })] })), still(900, { cx: 0.55 }));
  const ev = stops(run(frames));
  assert.equal(ev.length, 1);
  const restT = frames.find(f => f.hands[0].lm[0][0] > 0.54 && f.t > 1500).t;
  assert.ok(ev[0].t - restT >= 550, `fired ${ev[0].t - restT} ms after it came to rest`);
});

// ---- the flow registry and the intent routing ----
function fakeFlow(name = "fake", rank = 50) {
  const f = { name, rank, on: false, isPaused: false, calls: [], step: 0 };
  f.off = registerFlow({ name, rank, active: () => f.on, paused: () => f.isPaused,
    pause: src => { f.isPaused = true; f.calls.push(["pause", src]); flowLog({ flow: name, event: "pause", source: src }); return true; },
    resume: src => { f.isPaused = false; f.calls.push(["resume", src]); return true; },
    next: src => { f.step++; f.isPaused = false; f.calls.push(["next", src]); return true; },
    prev: src => { f.step--; f.isPaused = false; f.calls.push(["prev", src]); return true; },
    repeat: src => { f.isPaused = false; f.calls.push(["repeat", src]); return true; } });
  return f;
}
installFlowIntents();

test("no flow on screen: the flow handlers pass every intent on", async () => {
  const f = fakeFlow("idle");
  assert.equal(currentFlow(), null);
  assert.deepEqual(flowFrame(), {});
  assert.equal(await emitIntent("resume", {}, "voice"), false);
  assert.equal(flowWord("continue"), null);
  f.off();
});

test("pause by gesture / voice / key, resume by voice, thumbs up, Enter-select and step by arrows", async () => {
  const f = fakeFlow("tour"); f.on = true;
  assert.deepEqual(flowFrame(), { flow: "tour", flow_state: "running" });
  assert.equal(await emitIntent("stop", {}, "gesture"), true);
  assert.deepEqual(f.calls.at(-1), ["pause", "gesture"]);
  assert.deepEqual(flowFrame(), { flow: "tour", flow_state: "paused" });
  assert.equal(await emitIntent("stop", {}, "gesture"), false, "a second open hand never closes it: the shell's stop just hushes");
  assert.equal(await emitIntent("resume", {}, "voice"), true);
  assert.equal(f.isPaused, false);
  await emitIntent("pause", {}, "voice");
  assert.deepEqual(f.calls.at(-1), ["pause", "voice"]);
  assert.equal(await emitIntent("yes", {}, "gesture"), true, "thumbs up resumes a paused flow");
  assert.deepEqual(f.calls.at(-1), ["resume", "gesture"]);
  assert.equal(await emitIntent("yes", {}, "gesture"), false, "running: thumbs up is the screen's yes");
  await emitIntent("move", { dir: "right" }, "keyboard");
  await emitIntent("move", { dir: "left" }, "keyboard");
  assert.deepEqual(f.calls.slice(-2).map(c => c[0]), ["next", "prev"]);
  assert.equal(await emitIntent("move", { dir: "up" }, "keyboard"), false, "up / down still move focus");
  assert.equal(await emitIntent("back", {}, "keyboard"), true, "Esc on a running flow pauses it");
  assert.deepEqual(f.calls.at(-1), ["pause", "keyboard"]);
  assert.equal(await emitIntent("back", {}, "keyboard"), false, "Esc on a paused flow is the keys' close");
  assert.equal(await emitIntent("back", {}, "voice"), true, "\"go back\" is the stop before");
  assert.equal(await emitIntent("repeat", {}, "voice"), true);
  f.off();
});

test("the first active flow by rank gets the intents (a crew clip over the tour)", async () => {
  const tour = fakeFlow("tour2", 30), clip = fakeFlow("clip", 10);
  tour.on = clip.on = true;
  await emitIntent("stop", {}, "gesture");
  assert.equal(clip.isPaused, true); assert.equal(tour.isPaused, false);
  clip.on = false;
  await emitIntent("stop", {}, "gesture");
  assert.equal(tour.isPaused, true);
  tour.off(); clip.off();
});

test("the no-session words mirror the router's FLOW_NAV; the pause caption says why", () => {
  const f = fakeFlow("w"); f.on = true;
  const want = { continue: "resume", "keep going": "resume", "Go on, please": "resume", "carry on": "resume", stop: "pause",
    "hold on": "pause", "wait a second": "pause", again: "repeat", "next stop": "next", previous: "back", "go back": "back",
    "tell me about the rover": null };
  for (const [t, w] of Object.entries(want)) assert.equal(flowWord(t), w, t);
  f.off();
  assert.equal(pauseCaption("voice"), "Paused: you said stop");
  assert.equal(pauseCaption("gesture"), "Paused: hand signal");
  assert.ok(flowEvents().some(e => e.event === "pause" && e.source === "gesture"), "every pause is in the flow log with its source");
});
