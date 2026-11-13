// node --test tests/  — pure audio-floor logic: sentence splitter, echo check, barge-in rule, Space handling,
// mic error copy, and the mic worklet's 16 kHz resampler. No DOM needed.
import test from "node:test";
import assert from "node:assert/strict";
import { splitSentences, normWords, isEcho, shouldBargeIn, spaceAction, micErrorText } from "../src/floor.js";
import { WORKLET } from "../src/listen.js";

test("splitSentences: sentence ends, decimals kept, tiny fragments folded, long text capped", () => {
  assert.deepEqual(splitSentences("The rover drove 3.5 km. Then it parked!  Why? Dust."),
    ["The rover drove 3.5 km.", "Then it parked! Why?", "Dust."]);
  assert.deepEqual(splitSentences("Wow! The Moon is far away from us."), ["Wow! The Moon is far away from us."]);
  assert.deepEqual(splitSentences(""), []);
  const long = Array.from({ length: 120 }, (_, i) => `word${i}`).join(" ") + ", and more words here until the end.";
  const parts = splitSentences(long, 280);
  assert.ok(parts.length > 1 && parts.every(p => p.length <= 280));
  assert.equal(parts.join(" ").replace(/\s+/g, " "), long);
  // 600-char server cap is never exceeded with the default max
  assert.ok(splitSentences("a ".repeat(2000)).every(p => p.length <= 600));
});

test("normWords strips case and punctuation", () => {
  assert.deepEqual(normWords("Shields, to 40!  Don’t"), ["shields", "to", "40", "dont"]);
});

test("isEcho: ≥ 60% of heard words in what we play", () => {
  const guide = "Apollo 16 landed in the Descartes highlands. Charlie Duke drove the rover.";
  assert.equal(isEcho("charlie duke drove the rover", [guide]), true);
  assert.equal(isEcho("Descartes highlands.", [guide]), true);
  assert.equal(isEcho("wait can we go to mars instead", [guide]), false);
  assert.equal(isEcho("what is the rover made of", [guide]), false);   // 2/6 overlap ("the", "rover")
  assert.equal(isEcho("anything", []), false);
});

test("shouldBargeIn: start + ≥2 words + not echo + device_directed ≥ 0.5 when present", () => {
  const refs = ["Copy. Shields are at forty percent. The storm arrives in two hours."];
  assert.equal(shouldBargeIn({ started: true, text: "the storm arrives", refs }), false);            // echo
  assert.equal(shouldBargeIn({ started: true, text: "stop", refs }), false);                          // 1 word
  assert.equal(shouldBargeIn({ started: false, text: "send the rover now", refs }), false);           // no StartOfTurn
  assert.equal(shouldBargeIn({ started: true, text: "send the rover now", refs }), true);
  assert.equal(shouldBargeIn({ started: true, text: "send the rover now", refs, dd: 0.3 }), false);   // chatter
  assert.equal(shouldBargeIn({ started: true, text: "send the rover now", refs, dd: 0.9 }), true);
});

test("open-mic barge-in over a fake listener sequence: echo ignored, real words interrupt", () => {
  // Mirrors voice.js gate(): Flux sends the whole current turn text with every words/turn message.
  const refs = ["Here is the hardware people left on the Moon. Twelve stops!"];
  const run = msgs => { let g = null; for (const m of msgs) {
    if (m.t === "turn" && m.state === "start") { g = { text: m.text || "" }; continue; }
    if (!g) continue; if (m.text) g.text = m.text;
    if (shouldBargeIn({ started: true, text: g.text, refs })) return g.text;
    if (m.t === "turn" && m.state === "end") g = null;
  } return null; };
  assert.equal(run([{ t: "turn", state: "start" }, { t: "words", text: "here is the hardware" }, { t: "words", text: "here is the hardware people left" },
    { t: "turn", state: "end", text: "here is the hardware people left" }]), null);
  assert.equal(run([{ t: "turn", state: "start" }, { t: "words", text: "wait" }, { t: "words", text: "wait show me apollo eleven" }]),
    "wait show me apollo eleven");
});

// Fake DOM targets: closest(sel) answers from a small selector → element table.
const el = (tag, attrs = {}) => ({
  tag, ...attrs,
  closest(sel) {
    for (const part of sel.split(",").map(x => x.trim())) {
      if (part === tag) return this;
      if (part.startsWith("[contenteditable]") && this.contenteditable) return this;
      if (part === "[role='button']" && this.role === "button") return this;
      if (part === "[tabindex]" && this.tabindex != null) return this;
    }
    return null;
  },
});

test("spaceAction: Space is push-to-talk everywhere but text boxes; a focused button is blurred", () => {
  assert.equal(spaceAction(el("button")), "blur");
  assert.equal(spaceAction(el("input", { type: "submit" })), "blur");
  assert.equal(spaceAction(el("input", { type: "text" })), "ignore");
  assert.equal(spaceAction(el("input", {})), "ignore");
  assert.equal(spaceAction(el("textarea")), "ignore");
  assert.equal(spaceAction(el("div", { contenteditable: true })), "ignore");
  assert.equal(spaceAction(el("div", { role: "button" })), "blur");
  assert.equal(spaceAction(el("body")), "ptt");
  assert.equal(spaceAction(null), "ptt");
});

test("micErrorText explains a denied mic", () => {
  assert.match(micErrorText({ name: "NotAllowedError" }), /blocked/i);
  assert.match(micErrorText({ name: "NotFoundError" }), /No microphone/);
});

/** Run the AudioWorklet source in node with a stub runtime; feed `secs` of a 440 Hz sine at `rate`. */
function resample(rate, secs = 1) {
  let Proc = null; const out = [];
  const fn = new Function("AudioWorkletProcessor", "registerProcessor", "sampleRate", WORKLET);
  fn(class { constructor() { this.port = { postMessage: b => out.push(...new Int16Array(b)) }; } }, (_, C) => { Proc = C; }, rate);
  const p = new Proc(), N = Math.round(rate * secs);
  for (let s = 0; s < N; s += 128) {
    const blk = new Float32Array(Math.min(128, N - s)).map((_, k) => 0.5 * Math.sin(2 * Math.PI * 440 * (s + k) / rate));
    p.process([[blk]]);
  }
  return out;
}

for (const rate of [48000, 44100, 16000]) {
  test(`mic worklet resamples ${rate} Hz → 16 kHz PCM16 without drift`, () => {
    const out = resample(rate, 1);
    // full 80 ms frames only: 1 s → 12 frames (15360 samples); the 640-sample remainder waits for the next frame
    assert.equal(out.length, 15360);
    // phase check at the last sample: matches the 440 Hz sine at 16 kHz (no time drift across blocks)
    const n = out.length - 1, want = 0.5 * Math.sin(2 * Math.PI * 440 * n / 16000) * 0x7fff;
    assert.ok(Math.abs(out[n] - want) < 0x7fff * 0.02, `sample ${n}: ${out[n]} vs ${want.toFixed(0)}`);
  });
}

test("ttsUrlFor: the style and the sentence's place are in the URL (so caches key on them)", async () => {
  const { ttsUrlFor, sayStyle } = await import("../src/floor.js");
  const plain = new URL(ttsUrlFor("/api/tts", "Hi.", "guide", null, 0, 1, ""), "http://x");
  assert.equal(plain.searchParams.get("style"), null);
  assert.equal(plain.searchParams.get("i"), null);
  const st = { tag: "determined", controls: { rate: 0.6, loud: 0.8 } };
  const u = new URL(ttsUrlFor("/api/tts", "Storm is here!", "capcom", st, 0, 2, "Into the shelter."), "http://x");
  assert.deepEqual(JSON.parse(u.searchParams.get("style")), st);
  assert.equal(u.searchParams.get("i"), "0");
  assert.equal(u.searchParams.get("n"), "2");
  assert.equal(u.searchParams.get("next"), "Into the shelter.");
  const calm = ttsUrlFor("/api/tts", "Storm is here!", "capcom", { tag: "serenity" }, 0, 1, "");
  assert.notEqual(calm, ttsUrlFor("/api/tts", "Storm is here!", "capcom", st, 0, 1, ""));
  assert.deepEqual(sayStyle({ decisions: [{ t: "card" }, { t: "say", style: st }] }), st);
  assert.equal(sayStyle({}), undefined);
});
