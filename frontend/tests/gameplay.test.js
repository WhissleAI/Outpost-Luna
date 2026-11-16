// The live mission clock (mission/clock.js) and the Now task card (mission/objective.js nowCard): docs/GAMEPLAY.md.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createMissionClock, HOUR_MS, WARPS } from "../src/mission/clock.js";
import { nowCard, nudgeLine, leftLabel } from "../src/mission/objective.js";
import { keyAction } from "../src/input/keys.js";
import { readPad, createPadReader, BTN } from "../src/input/gamepad.js";
import { ROUTER_INTENTS } from "../src/input/defaults.js";
import * as S from "../src/story.js";

const words = s => String(s).trim().split(/\s+/).filter(Boolean).length;

/** A fake timer: tick(ms) moves the clock and fires the interval. */
function fake() {
  let t = 0, fn = null;
  return { now: () => t, timers: { setInterval: f => { fn = f; return 1; }, clearInterval: () => { fn = null; } },
    async run(ms, step = 250) { for (let k = 0; k < ms; k += step) { t += step; if (fn) fn(); await Promise.resolve(); await Promise.resolve(); } } };
}

test("clock: waits for play, runs about one sim hour per HOUR_MS at 1x, and posts about once a second", async () => {
  const f = fake(), posts = [];
  const c = createMissionClock({ post: async dt => { posts.push(dt); }, now: f.now, timers: f.timers });
  c.attach();
  await f.run(5000);
  assert.equal(posts.length, 0, "no time before Play");
  c.play();
  await f.run(HOUR_MS);
  const sum = posts.reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(sum - 1) < 0.1, `one hour at 1x, got ${sum}`);
  assert.ok(posts.length >= 8 && posts.length <= 14, `about one post a second, got ${posts.length}`);
  assert.ok(HOUR_MS >= 8000 && HOUR_MS <= 15000, "8-15 s per sim hour (the brief)");
  assert.ok(6 * HOUR_MS / 1000 >= 60 && 6 * HOUR_MS / 1000 <= 120, "a shift is 1-2 min of clock (2-4 min with its tasks)");
});

test("clock: warp 1x / 2x / 4x, drop to 1x on an event, pause, and hold during a decision or when hidden", async () => {
  const f = fake(), posts = []; let why = null;
  const c = createMissionClock({ post: async dt => { posts.push(dt); }, held: () => why, now: f.now, timers: f.timers });
  c.attach(); c.play();
  assert.deepEqual(WARPS, [1, 2, 4]);
  assert.equal(c.setWarp(4), 4);
  await f.run(HOUR_MS);
  assert.ok(Math.abs(posts.reduce((a, b) => a + b, 0) - 4) < 0.3, "4 hours at 4x");
  c.dropWarp(); assert.equal(c.warp, 1);
  assert.equal(c.setWarp(), 2, "no argument: the next speed"); c.setWarp(1);
  posts.length = 0; why = "decision";
  await f.run(5000);
  assert.equal(posts.length, 0, "a decision holds time"); assert.equal(c.held, "decision"); assert.equal(c.running, false);
  why = "hidden"; await f.run(3000); assert.equal(posts.length, 0, "a hidden app holds time");
  why = null; await f.run(3000); assert.ok(posts.length > 0, "time runs again by itself");
  c.pause(); posts.length = 0; await f.run(3000); assert.equal(posts.length, 0, "the kid's pause");
  assert.equal(c.toggle(), true); assert.equal(c.running, true);
});

const st = over => ({ mission_time_h: 10, over: false, shelter: false, power_save: false, loads: { shields: 30 }, acted: { allocate: 1 },
  resources: { power_pct: 80, life_support_pct: 80, dose_msv: 1, dose_limit_msv: 50 }, rover: { busy: false }, alerts: [],
  env: { in_sun: true, next_sun_change_h: 80, storm: { active: false }, warning: null }, objectives: { ice: { goal: 1, met: true } }, ...over });

test("task card: the step, its progress, the countdown, the lesson and the button that does it", () => {
  const task = { id: "storm_prep-3", kind: "storm_prep", title: "Storm prep", panel: "radiation", level: "caution",
    lesson: { id: "radiation", n: 5, title: "Radiation and storms" }, done_count: 1, total: 3, time_left_h: 5.5, readouts: [{ k: "Battery", v: "70%" }],
    steps: [], step: { id: "shields", kind: "order", label: "Shields to 40", ready: true, target: "shields",
      cmd: { type: "allocate", to: "shields", amount: { kind: "percent", value: 40 } } } };
  const c = nowCard(st({ task }));
  assert.equal(c.title, "Storm prep"); assert.equal(c.text, "Shields to 40"); assert.equal(c.target, "shields"); assert.equal(c.panel, "radiation");
  assert.deepEqual(c.progress, { done: 1, total: 3 }); assert.equal(c.left_h, 5.5); assert.equal(c.lesson.n, 5);
  assert.deepEqual(c.buttons[0].cmd, task.step.cmd); assert.equal(c.choice, false);
  assert.equal(leftLabel(5.5), "6 h"); assert.equal(leftLabel(0.5), "30 min");
  assert.ok(words(nudgeLine(st({ task }))) <= 20);
  // a choice: one button per option; the clock holds for it (state.task.decision from the sim)
  const ch = { ...task, kind: "ice_run", step: { id: "route", kind: "choice", label: "Pick a route on the slope map", ready: true, target: "task",
    options: [{ id: "ridge", label: "Ridge route", hint: "Flat. 2 h longer" }, { id: "slope", label: "Crater slope" }], hint: "LOLA slope map" } };
  const cc = nowCard(st({ task: ch }));
  assert.equal(cc.choice, true); assert.equal(cc.buttons.length, 2); assert.deepEqual(cc.buttons[1].task, { type: "task", task: "storm_prep-3", step: "route", choice: "slope" });
  // waiting (the rover is still driving): the job is the clock, Skip ahead glows
  const w = nowCard(st({ task: { ...task, step: { id: "back", kind: "wait", label: "Rover back with ice", ready: false } }, rover: { busy: true, eta_h: 7 } }));
  assert.equal(w.target, "skip"); assert.match(w.text, /7 hours/); assert.equal(w.buttons[0].clock, "skip");
});

test("task card: [polish 1] each step carries its short why; a step waiting on the rover says when it's back", () => {
  const task = { id: "night_prep-4", kind: "night_prep", title: "Night power-down", panel: "power", level: "caution", done_count: 0, total: 2,
    steps: [], step: { id: "night", kind: "order", label: "Night mode on", ready: true, target: "night", why: "Solar arrays make nothing in the dark.",
      cmd: { type: "power_save", on: true } } };
  const c = nowCard(st({ task }));
  assert.equal(c.why, "Solar arrays make nothing in the dark."); assert.ok(words(c.why) <= 12);
  const w = nowCard(st({ task: { ...task, step: { id: "send", kind: "order", label: "Send the rover to fix it", ready: false, wait: "The rover is out. Back in about 9 h." } } }));
  assert.equal(w.text, "The rover is out. Back in about 9 h."); assert.equal(w.auto, true);
});

test("task card: a pending yes / no is the job (never a stale step under it)", () => {
  const c = nowCard(st({ pending: { type: "dispatch", task: "collect_ice" }, task: { id: "ice_run-2", kind: "ice_run", title: "Ice run", steps: [], done_count: 0, total: 3,
    step: { id: "send", kind: "order", label: "Send the rover for ice", ready: true, target: "rover:collect_ice", cmd: { type: "dispatch" } } } }));
  assert.equal(c.key, "confirm"); assert.deepEqual(c.buttons.map(b => b.cmd.type), ["confirm", "cancel"]);
});

test("task card: always reflects reality, and says so when nothing is urgent", () => {
  const steady = nowCard(st(), { started: true, running: true, warp: 1 });
  assert.equal(steady.key, "steady"); assert.equal(steady.text, S.NOW.steady); assert.equal(steady.target, "skip");
  // [polish a] nothing to do: time fast-forwards by itself (auto), "Go now" skips at once; no Time-warp chore
  assert.deepEqual(steady.buttons.map(b => b.clock), ["skip"]); assert.equal(steady.auto, true);
  const fast = nowCard(st(), { started: true, running: true, warp: 4 });   // never a dead "Time warp 4x" at 4x
  assert.equal(fast.key, "steady_fast"); assert.deepEqual(fast.buttons.map(b => b.clock), ["skip"]);
  const paused = nowCard(st(), { started: true, running: false, paused: true, warp: 1 });
  assert.equal(paused.key, "paused"); assert.equal(paused.target, "play");
  assert.equal(nowCard(st({ over: true })), null);
  for (const v of Object.values(S.NOW)) { const t = typeof v === "function" ? v(12, "Storm prep") : v; assert.ok(words(t) <= 12, t); }
});

test("inputs: keys, controller and the router's intents all reach the clock and the card", () => {
  const k = key => keyAction({ key }, {});
  assert.equal(k("t").intent, "task_step"); assert.equal(k("k").intent, "time_toggle"); assert.equal(k("w").intent, "time_warp"); assert.equal(k("e").intent, "skip_event");
  const pad = pressed => ({ buttons: Array.from({ length: 17 }, (_, i) => ({ pressed: pressed.includes(i), value: pressed.includes(i) ? 1 : 0 })), axes: [0, 0, 0, 0] });
  const r = createPadReader();
  r.step(readPad(pad([])), 0);
  // the triggers also report their travel as a zoom (used outside the cabin; installGamepad gates it): {zoom, start/end}
  const rt = r.step(readPad(pad([BTN.rt])), 16);
  assert.deepEqual(rt.filter(a => a.intent).map(a => a.intent), ["skip_event"]);
  assert.deepEqual(rt.filter(a => "zoom" in a), [{ zoom: 1, start: true }], "RT: zoom in");
  assert.deepEqual(r.step(readPad(pad([BTN.back])), 32).filter(a => a.intent || a.end).map(a => a.intent || "zoom_end"), ["time_toggle", "zoom_end"]);
  const lt = r.step(readPad(pad([BTN.lt])), 48);
  assert.deepEqual(lt.filter(a => a.intent).map(a => a.intent), ["time_warp"]);
  assert.deepEqual(lt.filter(a => "zoom" in a), [{ zoom: -1, start: true }], "LT: zoom out");
  for (const n of ["skip_event", "time_pause", "time_resume", "time_warp", "task_choice"]) assert.ok(ROUTER_INTENTS.has(n), n);
});

test("Mission before the check ride: a Cadet, the path, and a practice shift (never 'Commander')", () => {
  assert.equal(S.CAPCOM.missionBrief("Nova", "Cadet"), "Pick a site, Cadet Nova. Keep the crew safe for ten days.");
  assert.match(S.CAPCOM.missionBrief("Nova"), /Commander Nova/);
  const G = S.GATE;
  assert.equal(G.title, "Pass your check ride to take command.");
  assert.match(G.say("Nova"), /^Nova, pass your check ride to take command\. Want to try a practice shift\?$/);
  assert.doesNotMatch(G.say("Nova") + G.doneSay("Nova") + G.title + G.sub + G.doneSub, /Commander/);
  for (const t of [G.title, G.sub, G.doneSub, G.doneTitle]) assert.ok(words(t) <= 12, t);
  for (const t of [G.say("Nova"), G.doneSay("Nova")]) assert.ok(words(t) <= 20, t);
  for (const t of [G.practice, G.ride, G.again]) assert.match(t, /^(Try|Fly|Practice)/);   // QA-69: a verb first
});

test("Houston is relayed by CAPCOM in one voice: \"Houston says: ...\", 20 words or fewer", async () => {
  const { houstonRelay } = await import("../src/mission/objective.js");
  const long = "Houston here. Your words took 1.3 seconds to reach us. Active region on the Sun. A storm is likely in the next two days.";
  const r = houstonRelay(long);
  assert.match(r, /^Houston says: /); assert.doesNotMatch(r, /Houston here/); assert.ok(words(r) <= 20, r);
  assert.equal(houstonRelay("Houston here. We copy you, Commander."), "Houston says: We copy you, Commander.");
});

test("Mute: Shift+M (M stays the mic), a pref that persists, and the router's words", async () => {
  const { keyAction } = await import("../src/input/keys.js");
  assert.equal(keyAction({ key: "m" }, {}).intent, "mic");
  assert.equal(keyAction({ key: "M", shift: true }, {}).intent, "mute");
  const { normalizePrefs, PREF_DEFAULTS } = await import("../src/prefs.js");
  assert.equal(PREF_DEFAULTS.muted, false);
  assert.equal(normalizePrefs({ muted: true }).muted, true);
  assert.equal(normalizePrefs({ muted: "yes" }).muted, false);
  const { ROUTER_INTENTS } = await import("../src/input/defaults.js");
  assert.ok(ROUTER_INTENTS.has("mute_sound") && ROUTER_INTENTS.has("unmute_sound"));
});

test("clock: [polish 2] hold to fast-forward runs FF_WARP while held, only while running; news lets go", async () => {
  const { FF_WARP } = await import("../src/mission/clock.js");
  const f = fake(); const posted = [];
  const c = createMissionClock({ post: async dt => { posted.push(dt); }, now: f.now, timers: f.timers });
  c.attach(); c.play(); c.hold(true);
  assert.equal(c.state.ff, true);
  await f.run(HOUR_MS);
  await c.flush();
  const got = posted.reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(got - FF_WARP) < 0.6, `about ${FF_WARP} sim hours in one real hour-ms (got ${got})`);
  c.dropWarp(); assert.equal(c.state.ff, true, "news drops the speed, not a held fast-forward");
  c.hold(true); c.pause(); assert.equal(c.state.ff, false, "a paused clock never fast-forwards");
  c.play(); c.hold(false); assert.equal(c.state.ff, false); assert.equal(c.state.warp, 1);
});
