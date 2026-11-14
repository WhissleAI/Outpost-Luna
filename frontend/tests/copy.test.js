// Copy rules (docs/COPY.md) for story.js: no emoji, spoken lines <= 20 words, on-screen budgets, typed call signs
// never spoken. The backend twin is backend/tests/test_copy.py.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as S from "../src/story.js";

const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2300}-\u{23FF}\u{FE0F}\u{200D}\u{20E3}]/u;
const words = s => String(s).trim().split(/\s+/).filter(Boolean).length;
const LONGEST_CS = S.CALLSIGNS.reduce((a, b) => (b.length > a.length ? b : a));

test("story.js has no emoji anywhere", () => {
  const src = readFileSync(new URL("../src/story.js", import.meta.url), "utf8");
  src.split("\n").forEach((line, i) => assert.ok(!EMOJI.test(line), `line ${i + 1}: ${line}`));
});

test("spoken lines are 20 words or fewer", () => {
  const cs = LONGEST_CS, site = "Shackleton Crater Rim";
  const spoken = [
    ...Object.values(S.LESSON_STORY).map(b => S.CAPCOM.lessonHello(cs, b.beat)),
    S.CAPCOM.patch(cs, "Mission Commander"), S.CAPCOM.qualified(cs, "Mission Commander"),
    S.CAPCOM.missionBrief(cs), S.CAPCOM.missionStart(cs, site), S.CAPCOM.houstonCalling,
    S.CAPCOM.missionStart(cs, site) + " " + S.CAPCOM.firstShift,
    S.CALLSIGN_COPY.say, ...Object.values(S.OFFER),
    ...Object.keys(S.CALLBACKS).flatMap(k => [S.callbackLine(k, true), S.callbackLine(k, false)]),
    S.DEBRIEF.grade(cs, "A", 1234), S.DEBRIEF.mars,
  ];
  for (const line of spoken) assert.ok(words(line) <= 20, `${words(line)} words: ${line}`);
  assert.ok(words(S.CAPCOM.firstShift) <= 12);
  // patch line + one offer, as the Academy says them together
  assert.ok(words(S.CAPCOM.patch(cs, "Mission Commander") + " " + S.OFFER.nextLesson) <= 20);
});

test("on-screen budgets: headlines 2-6 words, one line <= 12, buttons 1-3", () => {
  for (const b of S.BEATS) { assert.ok(words(b.title) <= 6); assert.ok(words(b.text) <= 12, b.text); }
  for (const t of Object.values(S.LESSON_BLURB)) assert.ok(words(t) <= 12, t);
  for (const k of ["hero", "hero2"]) assert.ok(words(S.SCHOOL[k]) <= 6, S.SCHOOL[k]);
  for (const k of ["sub", "subDone"]) assert.ok(words(S.SCHOOL[k]) <= 12, S.SCHOOL[k]);
  for (const k of ["start", "continue", "ride", "go"]) assert.ok(words(S.SCHOOL[k]) <= 3, S.SCHOOL[k]);
  for (const k of ["save", "random"]) assert.ok(words(S.CALLSIGN_COPY[k]) <= 3);
  for (const k of ["replay", "another", "close"]) assert.ok(words(S.DEBRIEF[k]) <= 3);
  assert.ok(words(S.WHY) <= 12 && words(S.CALLSIGN_COPY.sub) <= 12 && words(S.DEBRIEF.learnedEmpty) <= 12);
  for (const f of [S.MENTOR.first, S.MENTOR.ride, S.MENTOR.done]) assert.ok(words(f(LONGEST_CS)) <= 12);
});

test("credit line is exact; Artemis framing stays true", () => {
  assert.equal(S.CREDIT, "Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA.");
  assert.match(S.FRAMING, /April 2026/);
  assert.match(S.FRAMING, /No crew has landed at the south pole/);
  for (const t of [S.FRAMING, S.WHY, S.SCHOOL.hero, S.SCHOOL.hero2, S.LESSON_BLURB.radiation])
    assert.doesNotMatch(t, /Artemis III|real NASA data|\bG5\b/, t);
  assert.match(S.WHY, /planned/);
  for (const k of ["hero", "hero2"]) assert.ok(S.SCHOOL[k].length <= 32, S.SCHOOL[k]);   // 2 lines at 40px
  assert.equal(S.PRETEND_TECH, "Pretend tech");
  assert.equal(words(S.PRETEND_TECH_TIP), 10);
});

test("a typed call sign is shown, never spoken", () => {
  const store = new Map();
  globalThis.localStorage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)) };
  globalThis.dispatchEvent = () => true;
  globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } };
  S.callSign.set("Priya Sharma");
  assert.equal(S.callSign.shown(), "Priya Sharma");
  assert.equal(S.callSign.spoken(), "Commander");
  S.callSign.set("Nova");
  assert.equal(S.callSign.spoken(), "Nova");
});
