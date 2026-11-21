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
    onTurn: async () => {}, onBargeIn() {}, onKidDone() {},
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

// ---- [0.3.12] P0: no "Starting voice…" for minutes when the ear already failed ----
const H = (ear, extra = {}) => ({ model_server: { ok: true, models: { arc_ear: ear, tts: { loaded: true } } }, ...extra });

test("warmState: a loaded ear is ready; a starting model server is warming; an ear load error is off at once", () => {
  assert.equal(E.warmState(H({ available: true, decoder_loaded: true, error: null }), 1000), "ready");
  assert.equal(E.warmState({ model_server: { ok: false, error: "model server unreachable" } }, 1000), "warming");
  assert.equal(E.warmState(H({ available: false, decoder_loaded: false, error: "FileNotFoundError: libarc not built" }), 500), "off");
  assert.equal(E.warmState(H({ available: false, decoder_loaded: false, error: "ARC_EAR=off (disabled)" }), 0), "off");
  // a reload after a hung decode comes back by itself: still warming
  assert.equal(E.warmState(H({ available: false, decoder_loaded: false, error: "reloading after a hung decode (x)" }), 500), "warming");
  // no error yet (still loading): warming until the 3-minute limit, then off
  assert.equal(E.warmState(H({ available: false, decoder_loaded: false, error: null }), 10000), "warming");
  assert.equal(E.warmState(H({ available: false, decoder_loaded: false, error: null }), E.WARM_MS), "off");
  // Deepgram serves the voice (configured, or the fallback for a failed local ear): ready
  assert.equal(E.warmState(H({ available: false, decoder_loaded: false, error: "x" }, { voice: { ear: "arc", fallback: true } }), 0), "ready");
});

test("earErrorIsFatal: a dead ear vs a blip that reconnects", () => {
  assert.equal(E.earErrorIsFatal("local ear unavailable (FileNotFoundError: libarc not built) and no DEEPGRAM_API_KEY"), true);
  assert.equal(E.earErrorIsFatal("DEEPGRAM_API_KEY is not set on the backend"), true);
  assert.equal(E.earErrorIsFatal("local ear unavailable (model server unreachable: ConnectError) and no DEEPGRAM_API_KEY"), false);
  assert.equal(E.earErrorIsFatal("local ear unavailable (META_MAX_SESSIONS reached) and no DEEPGRAM_API_KEY"), false);
  assert.equal(E.earErrorIsFatal("local ear closed"), false);
  assert.ok(E.VOICE_FIX.split(/\s+/).length <= 12, "one short line (COPY.md)");
});

test("the ear's first fatal error turns the hint to the fix line at once; an ear that answers clears it", async () => {
  await els.mic.onclick(); await tick();
  const seen = []; const off = E.onEarFailed(on => seen.push(on));
  ear.message({ t: "error", message: "local ear unavailable (FileNotFoundError: libarc not built) and no DEEPGRAM_API_KEY" });
  assert.equal(E.earFailed(), true);
  assert.equal(hint(), E.VOICE_FIX);
  ear.close();
  assert.equal(hint(), E.VOICE_FIX, "the reconnect back-off keeps the fix line, not 'Reconnecting…'");
  ear.message({ t: "ready" });
  assert.equal(E.earFailed(), false);
  assert.equal(hint(), "Hold to talk");
  off();
  assert.deepEqual(seen, [true, false]);
});

test("a blip (ear closed) is not voice off", async () => {
  await els.mic.onclick(); await tick();
  ear.message({ t: "error", message: "local ear closed" });
  assert.equal(E.earFailed(), false);
  assert.equal(hint(), "Voice paused. Reconnecting…");
});
