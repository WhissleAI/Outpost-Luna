// The room state wired into the voice bar (voice.js + room.js + barge.js): a busy room asks for hold to talk with one line
// in the bar and drops open-mic turns, a tap of the mic still talks, the barge gate goes one level stricter, and the
// router's ignored room talk drives the room busy on its own. Real createVoice with a fake ear (as voice_gate.test.js).
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

function el() {
  const cls = new Set();
  return {
    classList: { add: (...c) => c.forEach(x => cls.add(x)), remove: (...c) => c.forEach(x => cls.delete(x)), toggle: (c, on) => (on ?? !cls.has(c)) ? cls.add(c) : cls.delete(c), contains: c => cls.has(c) },
    style: { setProperty() {} }, setAttribute() {}, insertBefore() {}, append() {}, textContent: "", title: "", hidden: false,
    dataset: {}, lastElementChild: { textContent: "" },
  };
}
let els = {};
globalThis.window = globalThis;
globalThis.document = { getElementById: id => (els[id] = els[id] || el()), createElement: () => el(), activeElement: null, querySelector: () => null };
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.dispatchEvent = () => true;
globalThis.CustomEvent = class { constructor(n, o) { this.type = n; this.detail = o && o.detail; } };
globalThis.AudioWorkletNode = class {};
Object.defineProperty(globalThis, "navigator", { value: { mediaDevices: {} }, configurable: true });

const { createVoice } = await import("../src/voice.js");
const { decideBarge } = await import("../src/barge.js");
const { ROOM_LINES } = await import("../src/room.js");

const tick = () => new Promise(r => setTimeout(r, 0));
let ear, turns;
beforeEach(() => {
  els = { spaceHint: el(), q: el() };
  els.spaceHint.lastElementChild.textContent = "Hold to talk"; els.q.placeholder = "Type instead";
  turns = [];
  window.__outpost = { prefs: { filter: "normal", listen: "handsfree" } };
  createVoice({
    onTurn: async (t, o) => { turns.push({ t, ptt: !!(o && o.ptt) }); }, onBargeIn() {}, onKidDone() {}, onEmotion() {},
    screen: () => ({ screen: "map" }),
    createListener: on => { ear = on; return { start: async () => true, stop() {}, send() {} }; },
  });
});
function hear(text, dd) {
  ear.message({ t: "turn", state: "start", text: "" });
  if (dd != null) ear.message({ t: "arc", device_directed: dd });
  ear.message({ t: "words", text, final: true });
  ear.message({ t: "turn", state: "end", text });
}

test("busy room: one line in the bar, open-mic turns dropped, a tap of the mic still talks", async () => {
  const room = window.__outpost.room;
  assert.equal(room.state, "calm");
  hear("tell me about tycho", 0.9);
  assert.equal(turns.length, 1, "calm: the open mic works");
  room.force("busy");
  assert.equal(room.mode, "hold");
  assert.equal(els.spaceHint.lastElementChild.textContent, ROOM_LINES.hold);
  assert.equal(els.spaceHint.dataset.room, "hold");
  hear("show me the far side", 0.9);
  assert.equal(turns.length, 1, "hold to talk: open-mic turns are not sent");
  await els.mic.onclick();                  // the first tap opens the mic (needs a gesture)
  await els.mic.onclick();                  // the next tap talks (latched until the ear's turn end)
  hear("show me the far side", 0.9);
  await new Promise(r => setTimeout(r, 650));
  assert.deepEqual(turns[1], { t: "show me the far side", ptt: true });
  room.force(null);                          // automatic again; a calm room returns to open voice silently
  assert.equal(room.mode, "open");
  assert.equal(els.spaceHint.lastElementChild.textContent, "Hold to talk");
});

test("too noisy: typing is offered, then the text box says type instead", () => {
  const room = window.__outpost.room;
  room.force("loud", "type");
  assert.equal(els.spaceHint.lastElementChild.textContent, ROOM_LINES.type);
  assert.equal(els.q.placeholder, ROOM_LINES.type);
  room.force(null);
  assert.equal(els.q.placeholder, "Type instead");
});

test("a busy room raises the barge gate one level (never looser than the kid's filter)", () => {
  const turn = { text: "tell me about the crater please", dd: 0.6, final: true };
  assert.equal(decideBarge(turn).act, "barge", "normal: 0.6 is directed enough");
  window.__outpost.room.force("busy");
  assert.equal(decideBarge(turn).reason, "not_directed", "busy: strict needs 0.65");
  window.__outpost.prefs.filter = "strict";
  assert.equal(window.__outpost.room.filter(), "strict");
  window.__outpost.room.force(null);
});

test("room talk the router ignores makes the room busy and asks for hold to talk, on its own", async () => {
  const v = window.__outpost.room;
  // the voice api is not exposed here: drive decided() through a fresh voice
  let api;
  els = { spaceHint: el(), q: el() }; els.spaceHint.lastElementChild.textContent = "Hold to talk";
  api = createVoice({ onTurn: async () => {}, onBargeIn() {}, onKidDone() {}, onEmotion() {}, screen: () => ({ screen: "map" }),
    createListener: on => { ear = on; return { start: async () => true, stop() {}, send() {} }; } });
  const room = window.__outpost.room;
  for (let i = 0; i < 4; i++) {
    const text = `so then she said ${i} things`;
    hear(text, 0.3);
    api.decided("ignore", text, { reason: "not_directed" });
    await tick();
  }
  assert.equal(room.state, "busy");
  assert.equal(room.mode, "hold");
  assert.equal(els.spaceHint.lastElementChild.textContent, ROOM_LINES.hold);
  void v;
});
