// [0.6] Haptics (src/haptics.js): four mission moments on a controller's rumble and navigator.vibrate, under the
// "Vibrate for alerts" and "Less motion" settings. docs/ACCESSIBILITY.md §Haptics.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { PATTERNS, ALERTS, plan, vibratePattern, momentOf, buzz, _reset } from "../src/haptics.js";

const pad = () => { const calls = []; return { calls, vibrationActuator: { playEffect: (type, o) => { calls.push({ type, ...o }); return Promise.resolve("complete"); } } }; };
const deps = (o = {}) => { let t = 0; const timers = [];
  return { settings: () => ({ vibrate: true, reducedMotion: false, ...(o.settings || {}) }), reduced: () => !!o.reduced, pads: () => o.pads || [],
    vibrate: o.vibrate, now: () => (t += 5000), later: (fn, ms) => timers.push([ms, fn]), timers }; };

test("haptics: storm warning is short, storm hit long, boulder a bump, rover home two taps", () => {
  const len = k => PATTERNS[k].reduce((a, p) => a + p[0] + p[3], 0);
  assert.ok(len("storm_warning") < 300 && len("storm_hit") >= 800);
  assert.ok(len("storm_hit") > 3 * len("storm_warning"));
  assert.equal(PATTERNS.boulder.length, 2); assert.equal(PATTERNS.rover_home.length, 2);
  for (const p of Object.values(PATTERNS)) for (const [ms, s, w] of p) assert.ok(ms > 0 && ms <= 1000 && s >= 0 && s <= 1 && w >= 0 && w <= 1);
});

test("haptics: the vibrate setting turns all of it off; less motion keeps only the storm alerts, softer", () => {
  assert.equal(plan("storm_hit", { vibrate: false }), null);
  assert.equal(plan("nope"), null);
  assert.equal(plan("boulder", { reduced: true }), null);
  assert.equal(plan("rover_home", { reduced: true }), null);
  const hit = plan("storm_hit"), soft = plan("storm_hit", { reduced: true });
  assert.ok(soft && soft[0].strong < hit[0].strong && soft[0].ms === hit[0].ms);
  assert.deepEqual([...ALERTS].sort(), ["storm_hit", "storm_warning"]);
});

test("haptics: navigator.vibrate pattern alternates on / off", () => {
  assert.deepEqual(vibratePattern(plan("boulder")), [90, 70, 60]);
  assert.deepEqual(vibratePattern(plan("storm_hit")), [900]);
  assert.deepEqual(vibratePattern([]), []);
});

test("haptics: sim events map to one moment, strongest first", () => {
  assert.equal(momentOf([{ kind: "rover_back" }, { kind: "solar_storm" }]), "storm_hit");
  assert.equal(momentOf([{ kind: "solar_storm", sep: false }]), "storm_warning");   // a near miss is not a hit
  assert.equal(momentOf([{ kind: "storm_warning" }]), "storm_warning");
  assert.equal(momentOf([{ kind: "task", phase: "ready", step: "steer" }]), "boulder");
  assert.equal(momentOf([{ kind: "task", phase: "start", step: "steer" }]), null);
  assert.equal(momentOf([{ kind: "rover_back" }]), "rover_home");
  assert.equal(momentOf([{ kind: "sunset" }]), null); assert.equal(momentOf(null), null);
});

test("haptics: a controller rumbles (dual-rumble, one pulse at a time) and a tablet vibrates", () => {
  _reset();
  const p = pad(), vib = [];
  const d = deps({ pads: [p, null], vibrate: x => { vib.push(x); return true; } });
  const r = buzz("boulder", d);
  assert.deepEqual(r, { pads: 1, vibrate: true });
  assert.equal(p.calls.length, 1); assert.equal(p.calls[0].type, "dual-rumble"); assert.equal(p.calls[0].duration, 90);
  assert.equal(d.timers.length, 1); assert.equal(d.timers[0][0], 160); d.timers[0][1]();   // the second pulse after the first + gap
  assert.equal(p.calls.length, 2); assert.equal(p.calls[1].duration, 60);
  assert.deepEqual(vib, [[90, 70, 60]]);
});

test("haptics: Firefox's hapticActuators pulse; a laptop with neither does nothing", () => {
  _reset();
  const got = []; const ff = { hapticActuators: [{ pulse: (v, ms) => got.push([v, ms]) }] };
  assert.deepEqual(buzz("storm_warning", deps({ pads: [ff] })), { pads: 1, vibrate: false });
  assert.deepEqual(got, [[0.45, 160]]);
  _reset();
  assert.deepEqual(buzz("storm_hit", deps({ pads: [{ id: "no motors" }] })), { pads: 0, vibrate: false });
});

test("haptics: off in Settings, and the same moment from two paths buzzes once", () => {
  _reset();
  const p = pad();
  assert.equal(buzz("storm_hit", deps({ pads: [p], settings: { vibrate: false } })), null);
  assert.equal(p.calls.length, 0);
  _reset();
  let t = 0; const d = { ...deps({ pads: [p] }), now: () => t };
  assert.ok(buzz("storm_hit", d)); t = 500; assert.equal(buzz("storm_hit", d), null); t = 2500; assert.ok(buzz("storm_hit", d));
});

test("haptics: every call site in the cabin sits beside a sound or a visual", () => {
  const ui = readFileSync(new URL("../src/mission/ui.js", import.meta.url), "utf8");
  assert.match(ui, /function handleEvents\(evs\) \{\n\s+if \(!evs\.length\) return;\n\s+feel\(evs\);/);
  assert.equal((ui.match(/buzz\(/g) || []).length, 1);     // one place: the events the cabin already shows and sounds
  const a11y = readFileSync(new URL("../src/a11y.js", import.meta.url), "utf8");
  assert.match(a11y, /Vibrate for alerts", "Phones, tablets and game controllers"/);
});
