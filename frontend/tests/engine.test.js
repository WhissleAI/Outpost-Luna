// [#87] The desktop shell restarts a crashed ear (the model server) and tells the page (src/engine.js): the voice bar
// says "Ear restarting…", typing keeps working, and the mic reconnects the moment the ear is back (not at the end of
// voice.js's own back-off). Drives the real createVoice with a fake ear.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

function el() {
  const cls = new Set();
  return {
    classList: { add: (...c) => c.forEach(x => cls.add(x)), remove: (...c) => c.forEach(x => cls.delete(x)), toggle: (c, on) => (on ?? !cls.has(c)) ? cls.add(c) : cls.delete(c), contains: c => cls.has(c) },
    style: { setProperty() {} }, setAttribute() {}, insertBefore() {}, append() {}, textContent: "", title: "", hidden: false,
    lastElementChild: { textContent: "Hold to talk" },
  };
}
let els = {};
globalThis.window = globalThis;
globalThis.document = { getElementById: id => (els[id] = els[id] || el()), createElement: () => el(), activeElement: null };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
Object.defineProperty(globalThis, "navigator", { value: { mediaDevices: {} }, configurable: true });
globalThis.AudioWorkletNode = class {};
globalThis.Audio = class { setAttribute() {} play() { return Promise.resolve(); } pause() {} };

const E = await import("../src/engine.js");
const { createVoice } = await import("../src/voice.js");
const tick = () => new Promise(r => setTimeout(r, 0));
const hint = () => els.spaceHint.lastElementChild.textContent;

let ear, cur;   // this test's voice: earlier tests' voices stay subscribed to the engine, each counts its own starts
beforeEach(() => {
  els = {}; const me = cur = { starts: 0 };
  E.setEngine({ ear: "ok", backend: "ok" });
  createVoice({
    onTurn: async () => {}, onBargeIn() {}, onKidDone() {}, onEmotion() {},
    createListener: on => { ear = on; return { start: async () => { me.starts++; return true; }, stop() {}, send() {} }; },
  });
});

test("engine state: the shell's calls reach subscribers once per change; the bar's classes and the hint follow", () => {
  const seen = [];
  const off = E.onEngine((s, prev) => seen.push([prev.ear, s.ear]));
  window.__lunaEngine({ ear: "restarting", backend: "ok" });
  window.__lunaEngine({ ear: "restarting", backend: "ok" });   // no change: no call
  window.__lunaEngine({ ear: "down" });
  off();
  window.__lunaEngine({ ear: "ok" });
  assert.deepEqual(seen, [["ok", "restarting"], ["restarting", "down"]]);
  assert.deepEqual(E.askbarClasses({ ear: "restarting" }), { "is-ear-restarting": true, "is-ear-down": false });
  assert.deepEqual(E.askbarClasses({ ear: "down" }), { "is-ear-restarting": false, "is-ear-down": true });
  assert.equal(E.earNote({ ear: "restarting" }), "Ear restarting…");
  assert.equal(E.earNote({ ear: "ok" }), "");
});

test("the ear restarts: 'Ear restarting…', then the mic reconnects at once when it is back", async () => {
  await els.mic.onclick(); await tick();
  assert.equal(cur.starts, 1);
  assert.equal(hint(), "Hold to talk");
  E.setEngine({ ear: "restarting" });
  ear.close();                                  // the listen socket drops with the model server
  assert.equal(hint(), "Ear restarting…");
  E.setEngine({ ear: "ok" });
  await tick(); await tick();
  assert.equal(cur.starts, 2, "reconnected without waiting for voice.js's own back-off");
  assert.equal(hint(), "Hold to talk");
});

test("the shell gave up: 'Voice is off. Type to ask.'", async () => {
  await els.mic.onclick(); await tick();
  E.setEngine({ ear: "down" });
  ear.close();
  assert.equal(hint(), "Voice is off. Type to ask.");
});

test("a mic that was never on is not opened by the ear coming back (no mic without a gesture)", async () => {
  E.setEngine({ ear: "restarting" });
  E.setEngine({ ear: "ok" });
  await tick();
  assert.equal(cur.starts, 0);
});
