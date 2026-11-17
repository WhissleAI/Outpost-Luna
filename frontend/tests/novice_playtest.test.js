// The first-time-player playtest of 2026-11-16 (docs/playtest/NOVICE_PLAYTEST_2026-11-16.md), Flight School findings:
// every step doable without outside knowledge, a hint ladder (highlight, label, show), feedback that says what to do
// next, the camera reveals what it names, and the app acknowledges what the kid did.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

globalThis.window = globalThis.window || {};
const { marks, doLine, INTRO, firstUse, resetSeen } = await import("../src/academy/guide.js");
const { parseCommand } = await import("../src/a11y.js");
const { unlocked, isExplorer } = await import("../src/explorer.js");
const C = await import("../src/media/commands.js");
const V = await import("../src/media/video_ui.js");
const S = await import("../src/story.js");

const course = JSON.parse(fs.readFileSync(new URL("../../backend/data/academy/course.json", import.meta.url)));
const places = JSON.parse(fs.readFileSync(new URL("../../backend/data/places.json", import.meta.url)));
const arts = JSON.parse(fs.readFileSync(new URL("../../backend/data/artifacts.json", import.meta.url)));
const P = Object.fromEntries([...(places.places || places), ...(arts.artifacts || arts)].map(p => [p.id, { ...p, km: p.diameter_km }]));
const find = id => P[id] || null;
const lesson = id => course.lessons.find(l => l.id === id);
const steps = course.lessons.flatMap(l => l.steps);

test("#1: help, I don't know, where is it climb the ladder; what? and huh re-explain (never silence)", () => {
  for (const t of ["help", "I don't know", "i dont know", "idk", "where is it?", "Where's it", "where", "I can't find it", "i cant find it", "show me where"])
    assert.deepEqual(parseCommand(t), { cmd: "help" }, t);
  for (const t of ["what?", "What", "huh", "what do you mean", "i dont understand"]) assert.deepEqual(parseCommand(t), { cmd: "confused" }, t);
  // answers are never swallowed
  for (const t of ["the sea of tranquility", "far side", "everyone into the shelter", "not sure", "yes"]) assert.equal(parseCommand(t), null, t);
});

test("#2: the day/night line is a dotted line pole to pole, labelled, and stays drawn after the answer", () => {
  const st = steps.find(s => s.accept.type === "terminator");
  assert.equal(st.globe.view_lon, st.accept.sun_lon - 90, "the camera faces the edge, so it runs down the middle");
  const r1 = marks(st, { rung: 1, line_lon: -45 }, find);
  assert.ok(r1.length >= 30 && r1.every(m => m.line && m.lon === -45) && !r1.some(m => m.label), "rung 1: the line glows");
  const r2 = marks(st, { rung: 2, line_lon: -45, label_line: true }, find);
  assert.deepEqual(r2.filter(m => m.label).map(m => m.label), ["Day meets night"]);
  const done = marks(st, { done: true, line_lon: -45, label_line: true }, find);
  assert.ok(done.length >= 30 && done.some(m => m.label === "Day meets night"), "the reveal points at something");
});

test("#5: a find-a-place step says to tap the glowing ring; the ring is there before any miss", () => {
  for (const st of steps.filter(s => ["intent", "tap"].includes(s.accept.type) && !(s.ring || []).length)) {
    assert.match(doLine(st), /glowing ring/, st.prompt);
    const m = marks(st, { rung: 1, focus: [st.accept.place] }, find);
    assert.ok(m.length === 1 && m[0].ring && m[0].pulse && !m[0].label, "rung 1: highlight, no name yet");
  }
});

test("#6: the Cabeus step's label is the word the prompt uses", () => {
  const st = lesson("life").steps.find(s => s.accept.type === "tap");
  assert.match(st.prompt, /Find Cabeus crater/);
  const m = marks(st, { rung: 2, focus: [st.accept.place], label: [st.accept.place] }, find);
  assert.deepEqual(m.map(x => x.label), ["Cabeus crater"]);
  assert.ok(!JSON.stringify(m).includes("Centaur"));
});

test("#7: guess chips on every 'Guess, then watch' step; typed words pick a chip; plain video steps drop 'Guess'", () => {
  for (const st of steps.filter(s => s.accept.type === "video")) {
    const g = (st.accept.guess || {}).options;
    if (/guess/i.test(st.prompt)) assert.ok(g && g.length >= 2, st.prompt);
    else assert.doesNotMatch(doLine(st), /guess/i, st.prompt);
  }
  const eclipse = steps.find(s => s.media === "lunar_eclipse").accept.guess.options;
  assert.equal(V.guessOf("shadow", eclipse), "shadow");
  assert.equal(V.guessOf("the sun", eclipse), "sun");
  assert.equal(V.guessOf("number two", eclipse), "cloud");
  assert.equal(V.guessOf("watch", eclipse), null);
  const far = steps.find(s => s.media === "far_side_view").accept.guess.options;
  assert.equal(V.guessOf("yes", far), "yes"); assert.equal(V.guessOf("nope", far), "no"); assert.equal(V.guessOf("skip", far), null);
  assert.ok(V.GUESS_ACK.split(" ").length <= 10 && /Watch/.test(V.GUESS_ACK), "the guess is acknowledged, then what's next");
});

test("#7: a guess, then Watch or Skip, sends the guess with the video result", async () => {
  const R = window.__outpost.stepRenderers;
  V.deps.getVideo = async id => ({ id, duration_s: 48 }); V.deps.isAvailable = async () => "cached";
  V.deps.openVideo = async () => ({ watched: true, seconds: 40 });
  const chip = c => ({ dataset: { c }, setAttribute() {}, onclick: null, focus() {} });
  const chips = [chip("shadow"), chip("cloud"), chip("sun")];
  const mk = () => ({ textContent: "", hidden: true, onclick: null, isConnected: true, classList: { add() {} }, focus() {}, querySelector: () => ({ textContent: "" }) });
  const nodes = { "[data-watch]": mk(), "[data-skip]": mk(), "[data-note]": mk(), ".vs-guess .a-choice": chips[0] };
  const el = { querySelector: s => nodes[s], querySelectorAll: () => chips };
  const sent = [], said = [], state = {};
  const acc = steps.find(s => s.media === "lunar_eclipse").accept;
  const r = R.video({ step: { media: "lunar_eclipse" }, acc, answer: x => sent.push(x), say: t => said.push(t), state });
  assert.match(r.html, /vs-guess/); assert.match(r.html, /Earth&#39;s shadow/);
  r.bind(el);
  assert.ok(state.video.needsGuess());
  assert.ok(state.video.guessText("a big cloud"));
  assert.equal(state.guess, "cloud"); assert.deepEqual(said, [V.GUESS_ACK]); assert.ok(!state.video.needsGuess());
  state.video.skip();
  assert.deepEqual(sent, [{ video: { watched: false, seconds: 0, skipped: true, guess: "cloud" } }]);
});

test("#9: one count: the core lessons, then the check ride", () => {
  assert.equal(S.TRANSITION.patchProgress(3, 6), "3 of 6 lessons done. 3 to go, then your check ride.");
  assert.equal(S.SCHOOL.lessonsCount(0, 6), "0 of 6 lessons");
  assert.ok(S.TRANSITION.firstMap.intro.length === 3 && S.TRANSITION.firstMap.intro.every(t => t.split(" ").length <= 9));
  assert.equal(S.EXPLORER.eyebrow, "Bonus lesson");
});

test("#10: a wrong order teaches; no step answers a kid with 'Say again?'", () => {
  for (const st of steps) assert.doesNotMatch(st.fail, /^Say again/, st.prompt);
  const storm = lesson("radiation").steps.find(s => s.accept.type === "command");
  assert.match(storm.wrong.shields, /shelter is safer/);
});

test("#11: the check ride asks only what the screen shows", () => {
  const ride = lesson("checkride");
  assert.ok(ride.ride.start_h >= 160, "Earth is up over the rim from the first step (Horizons model)");
  assert.ok(ride.steps.every(s => !/day 2/i.test(s.prompt)));
  assert.doesNotMatch(doLine(ride.steps[0]), /guess/i, "a qualifying test never says 'any guess is fine'");
});

test("#22: Lessons from Apollo (the trace step) opens after the check ride", () => {
  const hist = lesson("history");
  assert.ok(isExplorer(hist) && hist.unlock_after === "checkride");
  assert.ok(!unlocked(hist, 0, false) && unlocked(hist, 0, true));
});

test("#25: a 1:29 video is not 'Watch (1 min)'", () => {
  assert.equal(C.watchLabel({ duration_s: 89 }), "Watch (1½ min)");
  assert.equal(C.watchLabel({ duration_s: 118 }), "Watch (2 min)");
  assert.match(C.NO_PLAY_LESSON, /answer/);
});

test("#30: 'New: find a place' is said once for both kinds of find step", () => {
  resetSeen();
  const mem = new Map(), st = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  assert.ok(firstUse("intent", st));
  assert.ok(!firstUse("tap", st));
  assert.equal(INTRO.intent, INTRO.tap);
});

test("#8: Try at home is optional, with a way out for 'I don't have one'", () => {
  assert.equal(S.PREP.skip, "Not now");
  assert.match(S.PREP.missingSay, /Not now/);
  assert.doesNotMatch(S.PREP.intro, /first/i);
});
