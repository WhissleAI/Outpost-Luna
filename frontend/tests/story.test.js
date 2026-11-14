// The story arc, the cabin tour and the "what now" strip (docs/STORY.md): copy budgets, and the objective picked from
// the sim state for each situation the owner hit ("I am lost what to do").
import { test } from "node:test";
import assert from "node:assert/strict";
import * as S from "../src/story.js";
import { nowObjective, nowSpoken, debriefStory } from "../src/mission/objective.js";
import { tourBeats } from "../src/mission/tour.js";

const words = s => String(s).trim().split(/\s+/).filter(Boolean).length;
const EMOJI = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/u;

test("tour: every beat 12 words or fewer, Cadet full and Commander two beats", () => {
  const cadet = tourBeats("cadet"), cmd = tourBeats("commander");
  assert.equal(cmd.length, 2);
  assert.ok(cadet.length >= 8);
  for (const b of [...cadet, ...cmd]) { assert.ok(words(b.text) <= 12, `${words(b.text)}: ${b.text}`); assert.ok(!EMOJI.test(b.text)); assert.ok(b.show); }
  // the six beats of the brief, in order: window, three screens, panels, lights, goal, first job
  const order = cadet.map(b => b.show.split(":")[0]);
  assert.equal(order[0], "window");
  assert.deepEqual(cadet.filter(b => b.show.startsWith("du:")).map(b => b.show), ["du:0", "du:1", "du:2"]);
  assert.deepEqual(cadet.filter(b => b.show.startsWith("panel:")).map(b => b.show.slice(6)).sort(), ["comm", "habitat", "power", "radiation", "rover"]);
  assert.ok(order.indexOf("lamps") > order.lastIndexOf("panel"));
  assert.equal(cadet[cadet.length - 1].show, "start");
  assert.match(cadet[cadet.length - 1].text, /shields.*Play/i);   // the live clock: set power, then start time
  assert.match(cadet.find(b => b.show === "goals").text, /ten safe days.*science.*ice/i);
  for (const k of ["next", "done", "skip", "replay"]) assert.ok(words(S.TOUR[k]) <= 3);
});

test("transitions: spoken lines <= 20 words, on-screen lines <= 12, no emoji", () => {
  const T = S.TRANSITION;
  for (const t of [T.firstMap, T.toRide]) { assert.ok(words(t.say) <= 20, t.say); assert.ok(words(t.line) <= 12, t.line); assert.ok(words(t.where) <= 6); }
  assert.ok(words(T.qualified.line) <= 12 && words(T.picker.line) <= 12);
  for (const n of [0, 3, 6, 7]) assert.ok(words(T.patchProgress(n, 7)) <= 12, T.patchProgress(n, 7));
  assert.equal(T.patchProgress(6, 7), "6 of 7 patches. One lesson to go.");
  assert.ok(words(S.PICKER.why) <= 12 && words(S.PICKER.recLine) <= 12 && words(S.PICKER.recTag) <= 3);
  for (const t of Object.values(S.HELP)) assert.ok(words(t) <= 20, t);
  for (const t of [S.OFFER.resume, S.OFFER.firstLesson]) assert.ok(words(t) <= 6);
  for (const v of Object.values(S.NOW)) { const t = typeof v === "function" ? v(12) : v; assert.ok(words(t) <= 12, t); assert.ok(!EMOJI.test(t)); }
  assert.ok(words(S.NOW.ask + " " + S.NOW.warning(12)) <= 20);
});

test("CAPCOM's beats are CAPCOM speaking: no narrator copy, no question it won't wait for (QA-02)", () => {
  const spokenByCapcom = [...Object.values(S.LESSON_STORY).map(b => S.CAPCOM.lessonHello("Pulsar", b.beat)), S.TRANSITION.firstMap.say,
    S.TRANSITION.toRide.say, ...S.TOUR.cadet.map(b => b.text), ...S.TOUR.commander.map(b => b.text), S.PICKER.why, S.PICKER.recLine,
    S.CAPCOM.missionBrief("Pulsar"), S.CAPCOM.missionStart("Pulsar", "Shackleton Crater Rim")];
  for (const t of spokenByCapcom) {
    assert.doesNotMatch(t, /\bCAPCOM\b/, `third person: ${t}`);
    assert.doesNotMatch(t, /\?/, `a question nobody waits for: ${t}`);
  }
});

const base = () => ({ mission_time_h: 0, over: false, shelter: false, power_save: false, loads: { shields: 20 },
  resources: { power_pct: 90, life_support_pct: 80, dose_msv: 1, dose_limit_msv: 50 },
  env: { in_sun: true, next_sun_change_h: 100, storm: { active: false }, warning: null }, rover: { busy: false }, alerts: [],
  objectives: { science: { goal: 120, got: 0, met: false }, ice: { goal: 1, got: 0, met: false } } });

test("objective: the first job is set power; any power change moves it on to start the clock (owner's bug)", () => {
  const o = nowObjective(base());
  assert.equal(o.key, "first_shift"); assert.equal(o.text, S.NOW.firstShift); assert.equal(o.target, "shields"); assert.equal(o.panel, "radiation");
  assert.equal(nowSpoken(base()), `${S.NOW.ask} ${S.NOW.firstShift}`);
  const acted = { ...base(), acted: { allocate: 1 } };   // any allocate counts (the sim's `acted`)
  const clock = { started: false, running: false, warp: 1 };
  assert.equal(nowObjective(acted, clock).key, "start_clock"); assert.equal(nowObjective(acted, clock).target, "play");
  assert.equal(nowObjective(acted, { started: true, running: true, warp: 1 }).key, "ice");   // the clock runs: the next job
});

test("objective: storms, warnings, power, air, rover and the night, most urgent first", () => {
  const s = base(); s.mission_time_h = 30;
  s.env.storm = { active: true }; assert.equal(nowObjective(s).key, "storm_hit"); assert.equal(nowObjective(s).target, "shelter");
  s.shelter = true; assert.equal(nowObjective(s).key, "sheltered"); assert.equal(nowObjective(s).target, "skip");
  const weak = base(); weak.mission_time_h = 30; weak.env.storm = { active: true, sep: false };
  assert.equal(nowObjective(weak).key, "weak_storm");   // QA-27: few particles, no shelter rush
  const w = base(); w.mission_time_h = 30; w.env.warning = { confidence: "likely", eta_h: 6 };
  assert.match(nowObjective(w).text, /about 6 hours to get ready/); assert.doesNotMatch(nowObjective(w).text, /arrive|hits? in/i);   // QA-64 assert.equal(nowObjective(w).target, "shields");
  w.loads.shields = 40; assert.equal(nowObjective(w).target, "shelter");
  const p = base(); p.mission_time_h = 30; p.alerts = ["low_power"]; assert.equal(nowObjective(p).target, "night");
  const a = base(); a.mission_time_h = 30; a.resources.life_support_pct = 20; assert.equal(nowObjective(a).target, "rover:collect_ice");
  const r = base(); r.mission_time_h = 30; r.rover = { busy: true, task: "collect_ice", eta_h: 8 }; r.env.next_sun_change_h = 4;
  assert.equal(nowObjective(r).key, "rover_dark"); assert.match(nowObjective(r).text, /before dark/);
  r.env.next_sun_change_h = 50; assert.equal(nowObjective(r).key, "rover_out"); assert.match(nowObjective(r).text, /8 hours/);
  const n = base(); n.mission_time_h = 30; n.env.next_sun_change_h = 5; assert.equal(nowObjective(n).key, "sunset");
  const d = base(); d.mission_time_h = 30; d.env.in_sun = false; assert.equal(nowObjective(d).key, "dark");
  const i = base(); i.mission_time_h = 30; assert.equal(nowObjective(i).key, "ice");
  i.objectives.ice.met = true; assert.equal(nowObjective(i).key, "steady"); assert.equal(nowObjective(i).target, "warp");
  assert.match(nowObjective(i).text, /Time warp/);   // "when nothing is urgent it says so"
  assert.equal(nowObjective({ ...base(), over: true }), null);
});

test("debrief story: three beats, a try line and one clear choice", () => {
  const tl = Array.from({ length: 20 }, (_, k) => ({ t_h: (k + 1) * 6, events: k === 8 || k === 9 ? ["solar_storm"] : [] }));
  const st = { ...base(), mission_time_h: 239, over: true, outcome: "survived", site: { name: "Shackleton Crater Rim" }, day: 10 };
  const won = debriefStory({ outcome: "survived", timeline: tl, objectives: { science: { met: true }, ice: { met: false } } }, st);
  assert.equal(won.beats.length, 3);
  assert.equal(won.beats[0], "You ran Shackleton Crater Rim for 10 days.");
  assert.match(won.beats[1], /A real solar storm hit\. Your crew stayed safe/);
  assert.equal(won.beats[2], S.DEBRIEF.goalsScience);
  assert.equal(won.choice, "again");
  for (const b of won.beats) assert.ok(words(b) <= 12, b);
  const lost = debriefStory({ outcome: "dose_limit", try: "Shelter when Houston warns, not when it hits.", timeline: tl },
    { ...st, outcome: "dose_limit", resources: { dose_msv: 50, dose_limit_msv: 50 } });
  assert.match(lost.beats[1], /big dose/); assert.equal(lost.beats[2], S.DEBRIEF.endLost);
  assert.equal(lost.tryLine, "Shelter when Houston warns, not when it hits.");
  const paused = debriefStory({}, { ...base(), mission_time_h: 30, day: 2, site: { name: "Malapert Massif" } });
  assert.equal(paused.choice, "resume"); assert.match(paused.end, /day 2/);
});
