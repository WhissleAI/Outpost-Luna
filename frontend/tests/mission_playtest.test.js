// The first-time-player playtest's Mission findings (docs/playtest/NOVICE_PLAYTEST_2026-11-16.md): the Now card never
// claims time moves when it doesn't (3, 21), never asks for a storm order already done (16), the debrief's checklist
// agrees with its stars (19), and the cabin holds time behind Settings (17).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { nowCard, clockTruth, debriefStory } from "../src/mission/objective.js";
import { NOW, DEBRIEF } from "../src/story.js";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const base = () => ({ mission_time_h: 0, env: { in_sun: true, next_sun_change_h: 100 }, resources: { power_pct: 80, life_support_pct: 80 },
  loads: { shields: 30 }, rover: { busy: false }, alerts: [], objectives: { ice: { goal: 1, met: true }, science: { goal: 120, met: false } },
  acted: { allocate: 1 } });

test("[3] a resumed mission (clock ready, time > 0): the card says press Play, with a Play button", () => {
  const s = { ...base(), mission_time_h: 129 };   // Day 6, 09:00
  const ready = { started: false, running: false, paused: true, warp: 1, held: null };
  const c = nowCard(s, ready);
  assert.equal(c.text, NOW.resumePlay);
  assert.equal(c.target, "play");
  assert.deepEqual(c.buttons, [{ label: NOW.resumeBtn, clock: "play" }]);
  assert.equal(c.auto, false, "never auto-skips on a clock that isn't running");
  assert.doesNotMatch(c.text, /fast-forward|skips/i);
  // the clock runs: the wait card is back, and it says time skips (true: the auto-skip fires)
  const run = nowCard(s, { started: true, running: true, paused: false, warp: 1, held: null });
  assert.equal(run.target, "skip"); assert.match(run.text, /Time skips/);
});

test("[3] a paused clock under a wait card says Play; a held clock (a decision, Settings) keeps its card", () => {
  const s = { ...base(), mission_time_h: 40, rover: { busy: true, task: "explore", eta_h: 9 } };
  const paused = nowCard(s, { started: true, running: false, paused: true, warp: 1, held: null });
  assert.equal(paused.text, NOW.paused); assert.equal(paused.target, "play");
  const held = nowCard(s, { started: true, running: false, paused: false, warp: 1, held: "settings" });
  assert.equal(held.key, "rover_out");
  // an order card is never replaced: pressing the order is the job (and it starts a ready clock, ui.js run())
  const order = clockTruth({ key: "task:x:go", text: "Night mode on", auto: false, buttons: [{ label: "Night mode on", cmd: {} }] }, s,
    { started: false, paused: true, held: null });
  assert.equal(order.text, "Night mode on");
  assert.match(src("../src/mission/ui.js"), /!mclock\.started && !tour\.active\) mclock\.play\(\);/);
});

test("[16] a storm warning with the crew already sheltered: wait, never 'Crew into the shelter' again", () => {
  const s = { ...base(), mission_time_h: 20, shelter: true, env: { ...base().env, warning: { confidence: "likely", eta_h: 4 } } };
  const c = nowCard(s, { started: true, running: true, paused: false, warp: 1, held: null });
  assert.equal(c.key, "warning_safe"); assert.equal(c.text, NOW.warningSafe);
  assert.ok(!(c.buttons || []).some(b => /shelter|shields/i.test(b.label)));
  const ui = src("../src/mission/ui.js");
  assert.match(ui, /const doneAction = /);   // the Director's storm offer drops the orders already carried out
  assert.match(ui, /NOW\.stormReady/);
});

test("[17] Settings, About or a video over the cabin holds the mission clock", () => {
  const ui = src("../src/mission/ui.js");
  assert.match(ui, /\.a11y-panel:not\(\[hidden\]\), dialog\[open\]"\)\) return "settings"/);
});

test("[19] the debrief checklist says the same as the stars: crew, ice, science with its count", () => {
  const st = { mission_time_h: 240, over: true, outcome: "survived", site: { name: "Shackleton Crater Rim" }, day: 10, resources: { dose_msv: 10, dose_limit_msv: 50 } };
  const d = { outcome: "survived", timeline: [], objectives: { science: { goal: 120, got: 58, met: false }, ice: { goal: 1, got: 1, met: true } },
    final: { science: 61, science_sent: 58 }, try: "Do every science job and science drive: it all goes home when Earth is up." };
  const s = debriefStory(d, st);
  assert.deepEqual(s.checks.map(c => c.ok), [true, true, false]);
  assert.equal(s.checks[0].text, DEBRIEF.checkSafe);
  assert.equal(s.checks[2].text, "Science home: 58 of 120 (3 still on board)");
  assert.doesNotMatch(s.tryLine, /shelter/i, "the try line names the missed goal, not the shelter the game skipped");
  assert.doesNotMatch(s.beats.join(" "), /still waiting/);
  const ui = src("../src/mission/ui.js");
  assert.match(ui, /<details class="mx-grown"/);   // the numbers and citations wait behind one press
});

test("[18] the folded Now card keeps its button; the 3D consoles have a readable floor", () => {
  const css = src("../src/cabin.css");
  assert.match(css, /\.cb-now\.is-folded \.cb-now-more>:not\(\.cb-now-btns\)\{display:none\}/);
  assert.doesNotMatch(css, /\.cb-now\.is-folded \.cb-now-more\{display:none\}/);
  assert.match(css, /\.c3 \.c3-panel\[data-panel="pedestal"\] \.cb-lamp\{font-size:27px/);
});

test("[4] the progress strip counts science on board; the chapter card names stored science", () => {
  const cab = src("../src/mission/cabin.js");
  assert.match(cab, /science_stored/);
  assert.match(cab, /Saved on board for Earthrise/);
});
