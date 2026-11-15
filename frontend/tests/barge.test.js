// Barge-in policy (src/barge.js): a line stops only for a real, intentional interruption.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { decideBarge, isCommand, isStopCommand, BARGE_TUNING } from "../src/barge.js";
import { isEcho, turnIsEcho } from "../src/floor.js";

const LINE = "Doctors count radiation in mSv. So what is an mSv?";
const refs = [LINE];
beforeEach(() => { delete globalThis.window; });

test("commands: the stop / skip words, and nothing else", () => {
  for (const t of ["Stop.", "wait", "Be quiet!", "never mind", "okay stop", "pause", "skip", "next", "quiet"]) assert.ok(isCommand(t), t);
  for (const t of ["stop it", "wait what", "the rover", "go to the map"]) assert.ok(!isCommand(t), t);
  assert.ok(isStopCommand("Wait!") && !isStopCommand("skip"));
});

test("echo: spelled-out letters, the spoken form and near-miss spellings of our own line", () => {
  assert.ok(isEcho("doctors count radiation in m s v", refs));
  assert.ok(isEcho("so what is an m s v", refs));
  assert.ok(isEcho("so what is a millisievert", refs));
  assert.ok(isEcho("doctors count radiation in millie sieverts", refs));
  assert.ok(!isEcho("a radiation dose", refs));
  assert.ok(!isEcho("go to the map", refs));
});

test("decideBarge: never on words alone that are noise, echo, room talk or too quiet", () => {
  const base = { refs, final: true };
  assert.equal(decideBarge({ ...base, text: "" }).act, "hold");
  assert.equal(decideBarge({ ...base, text: "um" }).reason, "filler");
  assert.equal(decideBarge({ ...base, text: "so what is an m s v" }).reason, "echo");
  assert.equal(decideBarge({ ...base, text: "rocket" }).reason, "too_short");
  assert.equal(decideBarge({ ...base, text: "the rover" }).reason, "two_words");
  assert.equal(decideBarge({ ...base, text: "can you pass the salt", dd: 0.2 }).reason, "not_directed");
  assert.equal(decideBarge({ ...base, text: "go to the map", energy: { loud: 2 } }).reason, "low_energy");
  assert.equal(decideBarge({ ...base, text: "go to the map", energy: { loud: BARGE_TUNING.ENERGY_FRAMES } }).act, "barge");
  assert.equal(decideBarge({ ...base, text: "I don't know if that's correct", rated: false }).reason, "not_rated");
  assert.equal(decideBarge({ ...base, text: "stop", rated: false }).act, "barge");
  // the stop words pass the directed check; other commands don't
  assert.equal(decideBarge({ ...base, text: "stop", dd: 0.2 }).act, "barge");
  assert.equal(decideBarge({ ...base, text: "skip", dd: 0.2 }).act, "hold");
  assert.equal(decideBarge({ ...base, text: "a radiation dose", dd: 0.8 }).act, "barge");
  assert.equal(decideBarge({ ...base, text: "go to the map" }).act, "barge");
});

test("decideBarge: sustained speech and the grace windows hold the turn, then let it through", () => {
  const w = decideBarge({ text: "go to the map", refs, speechMs: 100 });
  assert.equal(w.act, "wait"); assert.equal(w.reason, "short_speech"); assert.equal(w.retryMs, BARGE_TUNING.MIN_SPEECH_MS - 100);
  const g = decideBarge({ text: "stop", refs, speechMs: 500, sinceLineMs: 200 });
  assert.equal(g.act, "wait"); assert.equal(g.reason, "grace_line"); assert.equal(g.retryMs, BARGE_TUNING.LINE_GRACE_MS - 200);
  assert.equal(decideBarge({ text: "stop", refs, speechMs: 500, sinceLineMs: 5000, sinceSentenceMs: 100 }).reason, "grace_resume");
  assert.equal(decideBarge({ text: "stop", refs, speechMs: 400, sinceLineMs: 5000, sinceSentenceMs: 5000 }).act, "barge");
  // a partial that is not yet enough waits for more words (no timer), a finished one is held
  assert.deepEqual(decideBarge({ text: "rocket", refs }), { act: "wait", reason: "too_short", retryMs: 0 });
});

test("turnIsEcho: the tail's near-verbatim replay of a lesson prompt is an echo; a real answer is not", () => {
  const frame = { screen: "lesson", step_type: "choice", step_options: ["A radiation dose", "A kind of rocket", "Moon soil"] };
  assert.equal(turnIsEcho({ text: "so what is an m s v", frame, onAir: false, refs }), true);
  assert.equal(turnIsEcho({ text: "a radiation dose", frame, onAir: false, refs }), false);
  assert.equal(turnIsEcho({ text: "is it a kind of rocket", frame, onAir: false, refs }), false);
});
