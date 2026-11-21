// [P0] The owner's "keeps flickering badly": room chatter cycled the voice bar Hearing you -> Thinking -> Listening and
// printed the overheard words ("Oh.", "Shit. Shit."). The bar now shows an open-mic turn's words only once the router
// took it, "Thinking" only for a turn that wasn't ignored, and every displayed state has a minimum dwell.
// Drives the real createVoice with a fake ear and a fake DOM (same harness as voice_gate.test.js).
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";

function el() {
  const cls = new Set();
  return {
    classList: { add: (...c) => c.forEach(x => cls.add(x)), remove: (...c) => c.forEach(x => cls.delete(x)), toggle: (c, on) => (on ?? !cls.has(c)) ? cls.add(c) : cls.delete(c), contains: c => cls.has(c) },
    style: { setProperty() {} }, setAttribute() {}, insertBefore() {}, append() {}, textContent: "", title: "", hidden: false,
    lastElementChild: { textContent: "" }, cls,
  };
}
let els = {};
globalThis.window = globalThis;
globalThis.document = { getElementById: id => (els[id] = els[id] || el()), createElement: () => el(), activeElement: null };
const listeners = {};
globalThis.addEventListener = (t, f) => { (listeners[t] = listeners[t] || []).push(f); };
globalThis.removeEventListener = () => {};
globalThis.AudioWorkletNode = function () {};
if (!globalThis.navigator) globalThis.navigator = {};
try { globalThis.navigator.mediaDevices = {}; } catch (e) { Object.defineProperty(globalThis, "navigator", { value: { mediaDevices: {} }, configurable: true }); }

const { createVoice, DISPLAY } = await import("../src/voice.js");
Object.assign(DISPLAY, { DWELL: 60, THINK_AFTER: 40, THINK_MAX: 400, NOTICE_MS: 120, DECIDED_MS: 1000 });
const wait = ms => new Promise(r => setTimeout(r, ms));

let ear, voice, turns, trace, sampler;
async function boot(onTurn = async t => { turns.push(t); return "session"; }) {
  els = {}; turns = []; trace = [];
  voice = createVoice({
    onTurn, onBargeIn() {}, onKidDone() {},
    screen: () => ({ screen: "map", offer: "next_lesson" }), floor: null,
    createListener: on => { ear = on; return { start: async () => true, stop() {}, send() {} }; },
  });
  listeners.pointerdown.forEach(f => f({}));   // the first gesture opens the (fake) mic
  await wait(5);
  ear.message({ t: "ready" });
  await wait(DISPLAY.DWELL + 10);
  sampler = setInterval(() => trace.push({ shown: voice.displayed, words: els.liveWords.textContent, label: els.listenState.textContent }), 5);
}
const stop = () => clearInterval(sampler);
function hear(text) {
  ear.message({ t: "turn", state: "start", text: "" });
  ear.message({ t: "words", text, final: false });
  ear.message({ t: "words", text, final: true });
  ear.message({ t: "turn", state: "end", text });
}
const changes = () => trace.reduce((n, s, i) => n + (i && s.shown !== trace[i - 1].shown ? 1 : 0), 0);

beforeEach(() => { for (const k of Object.keys(listeners)) delete listeners[k]; });

test("room chatter the router ignores: no words, no Thinking, no state change", async () => {
  await boot();
  for (const t of ["Oh.", "um", "Shit. Shit.", "did you call your mother about Sunday", "yeah I think she said three"]) {
    hear(t);
    await wait(15);
    voice.decided("ignore", t);   // the router's verdict (the session's `heard` decision)
    await wait(30);
  }
  await wait(DISPLAY.DWELL * 2);
  stop();
  assert.ok(trace.length > 20);
  assert.equal(trace.filter(s => s.words).length, 0, "overheard words shown: " + JSON.stringify(trace.find(s => s.words)));
  assert.equal(trace.filter(s => s.shown === "thinking" || s.shown === "hearing").length, 0, "Thinking / Hearing shown for chatter");
  assert.ok(changes() <= 1, "state changes: " + changes());
  assert.ok(turns.length >= 3, "non-filler turns still go to the router");
  assert.ok(!turns.includes("Oh.") && !turns.includes("um"), "filler never leaves the client");
});

test("a decision that beats the client's own turn end (the ear relay) is used: no Thinking for an ignored turn", async () => {
  await boot();
  voice.decided("ignore", "shit shit oh");
  hear("shit shit oh");
  await wait(DISPLAY.THINK_AFTER * 3);
  stop();
  assert.equal(trace.filter(s => s.shown === "thinking").length, 0);
});

test("a turn the router takes shows Thinking (and only after the decision or THINK_AFTER)", async () => {
  await boot();
  hear("start the lesson please");
  await wait(10);
  assert.notEqual(voice.displayed, "thinking", "no Thinking before the decision");
  voice.decided("navigate", "start the lesson please");
  await wait(DISPLAY.DWELL + 20);
  assert.equal(voice.displayed, "thinking");
  await wait(DISPLAY.THINK_MAX + DISPLAY.DWELL);
  assert.equal(voice.displayed, "listening", "Thinking never sticks");
  stop();
});

test("an undecided turn shows Thinking after THINK_AFTER (no session: the answer ends it)", async () => {
  let release;
  await boot(() => new Promise(r => { release = r; }));
  hear("where did apollo eleven land");
  await wait(DISPLAY.THINK_AFTER + DISPLAY.DWELL + 20);
  assert.equal(voice.displayed, "thinking");
  release(undefined);
  await wait(DISPLAY.DWELL + 20);
  assert.equal(voice.displayed, "listening");
  stop();
});

test("Space held (push-to-talk) is explicit: Hearing you and the words show at once, masked", async () => {
  await boot();
  listeners.keydown.forEach(f => f({ code: "Space", target: null, preventDefault() {}, repeat: false }));
  await wait(DISPLAY.DWELL + 20);
  ear.message({ t: "words", text: "oh shit the next lesson", final: false });
  await wait(5);
  assert.equal(voice.displayed, "hearing");
  assert.equal(els.liveWords.textContent, "oh s*** the next lesson");
  stop();
});

test("every displayed state lasts at least the dwell", async () => {
  await boot();
  voice.show("speaking"); await wait(5); voice.show("idle"); await wait(5); voice.show("speaking"); await wait(5); voice.show("idle");
  await wait(DISPLAY.DWELL * 3);
  stop();
  const runs = []; let cur = null, n = 0;
  for (const s of trace) { if (s.shown !== cur) { if (cur) runs.push([cur, n]); cur = s.shown; n = 0; } n++; }
  // each run except the last lasted >= the dwell (samples every 5 ms; allow timer slack)
  runs.slice(1).forEach(([s, k]) => assert.ok(k * 5 >= DISPLAY.DWELL * 0.7, `${s} shown only ~${k * 5} ms`));
});

test("[0.4.1] crew talk: room talk kept off a guess or a choice shows \"Crew talk\" briefly, then Listening", async () => {
  const { CREW_TALK } = await import("../src/voice.js");
  await boot();
  hear("yes it is");
  await wait(15);
  voice.decided("ignore", "yes it is");
  voice.notice(CREW_TALK);
  await wait(DISPLAY.DWELL + 20);
  assert.equal(els.listenState.textContent, "Crew talk");
  assert.equal(els.liveWords.textContent, "", "the overheard words never show");
  await wait(DISPLAY.NOTICE_MS + DISPLAY.DWELL + 40);
  stop();
  assert.notEqual(els.listenState.textContent, "Crew talk");
});
