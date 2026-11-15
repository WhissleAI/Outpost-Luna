// Settings v1 prefs (frontend/src/prefs.js): stored values are normalized, never trusted.
import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizePrefs, PREF_DEFAULTS, PROFILE_KEYS, moreVoicesHint } from "../src/prefs.js";
import { BARGE, shouldBargeIn } from "../src/floor.js";

test("prefs: defaults, clamps and option lists", () => {
  assert.deepEqual(normalizePrefs(null), { ...PREF_DEFAULTS });
  const p = normalizePrefs({ volume: 3, alarms: -1, expressiveness: "0.75", listen: "ptt", filter: "loud", theme: "dark", graphics: "low", level: "commander", junk: 1 });
  assert.equal(p.volume, 2); assert.equal(p.alarms, 0);   // volume: 0–2 (1 = the −14 LUFS target) assert.equal(p.expressiveness, 0.75);
  assert.equal(p.listen, "ptt"); assert.equal(p.filter, "normal"); assert.equal(p.theme, "dark");
  assert.equal(p.graphics, "low"); assert.equal(p.level, "commander"); assert.ok(!("junk" in p));
});

test("prefs: a cadet profile carries call sign, progress, settings and the voice-bar spot", () => {
  for (const k of ["outpost-callsign", "atm-academy", "outpost-a11y", "outpost-prefs", "outpost-voicebar"]) assert.ok(PROFILE_KEYS.includes(k), k);
});

test("prefs: the barge-in thresholds follow the voice filter (relaxed / normal / strict)", () => {
  assert.deepEqual(BARGE.normal, [0.5, 0.7]); assert.deepEqual(BARGE.relaxed, [0.35, 0.55]); assert.deepEqual(BARGE.strict, [0.65, 0.85]);
  const turn = { started: true, text: "turn the shields up please", refs: [], dd: 0.6 };
  globalThis.window = { __outpost: { prefs: { filter: "strict" } } };
  assert.equal(shouldBargeIn(turn), false);          // 0.6 < strict 0.65
  window.__outpost.prefs.filter = "relaxed";
  assert.equal(shouldBargeIn(turn), true);
  delete globalThis.window;
});

test("prefs: 'Help improve the voice guide' is off by default and only an explicit true turns it on", () => {
  assert.equal(PREF_DEFAULTS.improve, false);
  assert.equal(normalizePrefs({}).improve, false);
  assert.equal(normalizePrefs({ improve: "true" }).improve, false);
  assert.equal(normalizePrefs({ improve: 1 }).improve, false);
  assert.equal(normalizePrefs({ improve: true }).improve, true);
});

// [qa] QA-17: every per-cadet store is in the profile (camera & gestures, the mission tier), so switching cadets swaps them.
test("prefs: a cadet profile also carries the gesture settings and the mission tier", () => {
  for (const k of ["outpost-gestures", "outpost-tier"]) assert.ok(PROFILE_KEYS.includes(k), k);
});

test("prefs: the more-voices hint names the OS's own voice settings, never Siri", () => {
  const mac = moreVoicesHint("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Electron/33");
  const win = moreVoicesHint("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Electron/33");
  assert.match(mac, /macOS voices/); assert.match(mac, /Spoken Content → System voice → Manage Voices/);
  assert.match(win, /Windows voices/); assert.match(win, /Time & language → Speech → Manage voices/);
  assert.equal(moreVoicesHint("Mozilla/5.0 (X11; Linux x86_64)"), "");
  for (const s of [mac, win]) { assert.ok(!/siri/i.test(s)); assert.ok(s.split(/\s+/).length <= 20, s); }
});

test("the recorded guide voice (voice pack) is on by default and only with the default voice", async () => {
  const { packAllowed } = await import("../src/floor.js");
  assert.equal(normalizePrefs({}).pack, true);
  assert.equal(normalizePrefs({ pack: false }).pack, false);
  assert.equal(normalizePrefs({ pack: "no" }).pack, true);
  assert.equal(packAllowed({ pack: true, voice: "" }, "sys"), true);
  assert.equal(packAllowed({ pack: true, voice: "sys" }, "sys"), true);        // the default, picked explicitly
  assert.equal(packAllowed({ pack: true, voice: "other" }, "sys"), false);     // another voice: live lines
  assert.equal(packAllowed({ pack: false, voice: "" }, "sys"), false);         // Settings toggle off
});
