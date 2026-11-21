// Hands-free RC bug: "Oh, it's." / "Okay." heard while CAPCOM's lines played back to back counted as lesson answers.
// voice.js must hold its hard mute across a whole queued CAPCOM sequence (brief → beat → prompt), including the gaps
// while the next line's audio is still loading, and the floor must tell the session that more is coming (`more`).
// Drives the real createVoice + createFloor with a fake ear, fake TTS fetches and a fake <audio>.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

// ---- a tiny DOM + browser surface (only what voice.js and floor.js touch) ----
function el() {
  const cls = new Set();
  return {
    classList: { add: (...c) => c.forEach(x => cls.add(x)), remove: (...c) => c.forEach(x => cls.delete(x)), toggle: (c, on) => (on ?? !cls.has(c)) ? cls.add(c) : cls.delete(c), contains: c => cls.has(c) },
    style: { setProperty() {} }, setAttribute() {}, insertBefore() {}, append() {}, textContent: "", title: "", hidden: false,
    lastElementChild: { textContent: "" },
  };
}
const els = {};
globalThis.window = globalThis;
globalThis.document = { getElementById: id => (els[id] = els[id] || el()), createElement: () => el(), activeElement: null };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
let audios = [];
globalThis.Audio = class { constructor() { this.paused = true; audios.push(this); } setAttribute() {} play() { this.paused = false; return Promise.resolve(); } pause() { this.paused = true; } };
URL.createObjectURL = () => "blob:x"; URL.revokeObjectURL = () => {};
let fetches = [];   // each TTS fetch waits until the test releases it (the gap between lines is the fetch latency)
globalThis.fetch = () => new Promise(res => fetches.push(() => res({ status: 200, ok: true, blob: async () => ({}), headers: { get: () => "" } })));

const { createFloor } = await import("../src/floor.js");
const { createVoice } = await import("../src/voice.js");
const { BARGE_TUNING } = await import("../src/barge.js");

const tick = () => new Promise(r => setTimeout(r, 0));
async function settle(n = 6) { for (let k = 0; k < n; k++) await tick(); }
async function releaseFetch() { while (!fetches.length) await tick(); fetches.shift()(); await settle(); }
function endAudio() { const a = audios[audios.length - 1]; a.paused = true; a.onended && a.onended(); }

let floor, ear, turns, barges, events;
beforeEach(() => {
  audios = []; fetches = []; turns = []; barges = 0; events = [];
  floor = createFloor();
  floor.on("playback", e => events.push(e));
  createVoice({
    onTurn: async t => { turns.push(t); }, onBargeIn: () => { barges++; }, onKidDone() {},
    screen: () => ({ screen: "lesson", step_type: "vocab_match", step_options: ["A dark, flat sea of old cooled lava."], lesson_id: "history", step: 0 }),
    floor, createListener: on => { ear = on; return { start: async () => false, stop() {}, send() {} }; },
  });
});
function hear(text, dd) {
  ear.message({ t: "turn", state: "start", text: "" });
  if (dd != null) ear.message({ t: "arc", device_directed: dd });
  ear.message({ t: "words", text, final: true });
  ear.message({ t: "turn", state: "end", text });
}

const LINES = ["Every crew learns from the crews before.", "Every mission teaches the next one, cadet.", "Apollo 11 landed on a mare. What does mare mean?"];

test("a multi-line say is one on-air span: chatter between its lines never becomes a turn", async () => {
  const done = floor.say(LINES, { voice: "capcom" });
  await releaseFetch();                       // line 1 audio arrives and plays
  assert.equal(floor.holder, "guide");
  endAudio(); await settle();                 // line 1 ends; line 2's audio is still loading: the gap
  assert.equal(floor.holder, "guide", "the floor stays with CAPCOM between queued lines");
  assert.equal(floor.onAir, true);
  hear("Okay.");
  hear("Oh, it's.");
  await releaseFetch(); endAudio(); await settle();   // line 2
  hear("Oh, it's.");
  while (fetches.length || audios[audios.length - 1].paused === false) { if (fetches.length) await releaseFetch(); else { endAudio(); await settle(); } }
  assert.equal(await done, true, "CAPCOM finished the whole sequence: nothing barged in");
  assert.deepEqual(turns, []);
  assert.equal(barges, 0);
  const pb = events.filter(e => e.kind === "guide");
  assert.deepEqual(pb.map(e => e.state), ["start", "end"], "one playback span for the three lines");
});

test("back-to-back says: the gap while the next one loads is on air, and the line's end says more is coming", async () => {
  const a = floor.say(LINES[0], { voice: "capcom" });
  const b = floor.say(LINES[1], { voice: "capcom", priority: 4 });   // queued behind it
  await releaseFetch(); endAudio(); await settle();
  assert.equal(events.find(e => e.state === "end").more, true);
  assert.equal(floor.onAir, true, "the next line is queued: still on air while its audio loads");
  hear("Oh, it's.");
  await releaseFetch(); endAudio(); await settle();
  assert.equal(await a, true); assert.equal(await b, true);
  assert.equal(events.filter(e => e.state === "end").pop().more, undefined, "the last line has nothing after it");
  assert.deepEqual(turns, []); assert.equal(barges, 0);
  assert.equal(floor.onAir, false);
});

// One utterance per user action (packaged-app bug: a tap on the Moon said its line twice, in two voices).
test("floor: the same line asked for twice within 3 s, in any voice, is spoken once; an explicit repeat is not dropped", async () => {
  const line = "Not quite. Try the near side of the Moon.";
  const a = floor.say(line, { voice: "capcom" });
  const b = floor.say("Not quite, try the near side of the Moon!", { voice: "guide", priority: 4 });   // near-identical
  assert.equal(await b, false, "the duplicate is dropped at once");
  await releaseFetch(); endAudio(); await settle();
  assert.equal(await a, true);
  assert.equal(await floor.say(line, { voice: "story" }), false, "just said: still a duplicate");
  const c = floor.say(line, { voice: "capcom", repeat: true });   // "Hear it again"
  await releaseFetch(); endAudio(); await settle();
  assert.equal(await c, true);
  assert.equal(events.filter(e => e.state === "start").length, 2);
});

test("floor: a sentence that errors after it was heard is not said again in the browser voice", async () => {
  const done = floor.say("Copy. The Sea of Tranquility, July 1969.", { voice: "capcom" });
  await releaseFetch();
  const a = audios[audios.length - 1];
  a.onplaying && a.onplaying(); a.currentTime = 1.2;
  a.onerror && a.onerror();                        // a late decode error at the very end
  await settle();
  assert.equal(await done, true, "the line ended once; no speechSynthesis replay");
});

test("the gate is not deaf: a clearly directed answer still barges into the sequence", async () => {
  const done = floor.say(LINES, { voice: "capcom" });
  await releaseFetch(); endAudio(); await settle();
  hear("a dark flat sea of lava", 0.9);
  await settle();
  assert.equal(barges, 0, "held inside the line's first LINE_GRACE_MS (the onset echo burst), not dropped");
  await new Promise(r => setTimeout(r, BARGE_TUNING.LINE_GRACE_MS + 30)); await settle();
  assert.equal(barges, 1);
  assert.deepEqual(turns, ["a dark flat sea of lava"]);
  while (fetches.length) await releaseFetch();
  assert.equal(await done, false, "the kid's barge-in stopped CAPCOM");
});

// Owner bug (Flight School Radiation step 5): the line was cut by our own voice / noise. The fixes, end to end.
const wait = ms => new Promise(r => setTimeout(r, ms));
async function finishAll() { for (let k = 0; k < 20 && (fetches.length || (audios.length && !audios[audios.length - 1].paused)); k++) { if (fetches.length) await releaseFetch(); else { endAudio(); await settle(); } } }

test("barge-in: our own line spelled back by the ear ('m s v') never stops it, and lands in the barge log", async () => {
  const keep = { ...BARGE_TUNING }; Object.assign(BARGE_TUNING, { LINE_GRACE_MS: 0, RESUME_GRACE_MS: 0 });
  try {
    const done = floor.say("Doctors count radiation in mSv. So what is an mSv?", { voice: "capcom" });
    await releaseFetch();
    hear("doctors count radiation in m s v", 0.95);
    hear("so what is an m s v", 0.95);
    await settle();
    assert.equal(barges, 0);
    await finishAll();
    assert.equal(await done, true, "the line completed");
    assert.ok((window.__outpost.bargeLog.counts["held:echo"] || 0) >= 2);
  } finally { Object.assign(BARGE_TUNING, keep); }
});

test("barge-in: a stop word interrupts; outpost:barge names the line; a stop is never resumed", async () => {
  const keep = { ...BARGE_TUNING }; Object.assign(BARGE_TUNING, { LINE_GRACE_MS: 0, RESUME_GRACE_MS: 0, RECOVER_MS: 60 });
  const fired = []; const de = globalThis.dispatchEvent; globalThis.dispatchEvent = e => { fired.push(e); return true; };
  try {
    const done = floor.say("Doctors count radiation in mSv. So what is an mSv?", { voice: "capcom" });
    await releaseFetch();
    hear("Stop.", 0.2);   // a stop word even when Arc rates it as not directed
    await settle();
    assert.equal(barges, 1);
    assert.equal(await done, false);
    const ev = fired.find(e => e.type === "outpost:barge");
    assert.ok(ev && ev.detail.reason === "command" && ev.detail.lineText.startsWith("Doctors"));
    const starts = events.filter(e => e.state === "start").length;
    await wait(200); while (fetches.length) await releaseFetch();
    assert.equal(events.filter(e => e.state === "start").length, starts, "nothing said again after 'stop'");
  } finally { Object.assign(BARGE_TUNING, keep); globalThis.dispatchEvent = de; }
});

test("barge-in: a false interruption (no actionable turn) says the interrupted sentence again, once", async () => {
  const keep = { ...BARGE_TUNING }; Object.assign(BARGE_TUNING, { LINE_GRACE_MS: 0, RESUME_GRACE_MS: 0, RECOVER_MS: 60 });
  try {
    const done = floor.say("Doctors count radiation in mSv. So what is an mSv?", { voice: "capcom" });
    await releaseFetch();
    hear("the rover is parked by the crater", 0.9);   // a real-looking turn the app does nothing with
    await settle();
    assert.equal(barges, 1); assert.equal(await done, false);
    const starts = () => events.filter(e => e.kind === "guide" && e.state === "start").length, s0 = starts();
    await wait(250); while (fetches.length) await releaseFetch();
    assert.equal(starts(), s0 + 1, "the interrupted sentence is said again");
    assert.equal(events.filter(e => e.state === "start").pop().text, "Doctors count radiation in mSv. So what is an mSv?");
    hear("the rover is parked by the big crater", 0.9);   // cut again: stays cut
    await settle(); await wait(250); while (fetches.length) await releaseFetch();
    assert.equal(starts(), s0 + 1, "a resumed line that is cut again is not said a third time");
    assert.equal(window.__outpost.bargeLog.counts["resume:barge:speech"], 1);
  } finally { Object.assign(BARGE_TUNING, keep); }
});

test("barge-in: muted, our line plays silently and open-mic speech never stops it", async () => {
  window.__outpost = { ...(window.__outpost || {}), levels: { master: 1, alarms: 1, muted: true } };
  try {
    const done = floor.say("Doctors count radiation in mSv. So what is an mSv?", { voice: "capcom" });
    await releaseFetch();
    hear("go to the map please", 0.9);
    await settle();
    assert.deepEqual(turns, ["go to the map please"], "the turn is still heard");
    await finishAll();
    assert.equal(await done, true, "the silent line (captions) ran to its end");
  } finally { delete window.__outpost.levels; }
});
