// Settings v1 prefs (frontend/src/prefs.js): stored values are normalized, never trusted.
import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizePrefs, PREF_DEFAULTS, PROFILE_KEYS } from "../src/prefs.js";

test("prefs: defaults, clamps and option lists", () => {
  assert.deepEqual(normalizePrefs(null), { ...PREF_DEFAULTS });
  const p = normalizePrefs({ volume: 3, alarms: -1, expressiveness: "0.75", listen: "ptt", filter: "loud", theme: "dark", graphics: "low", level: "commander", junk: 1 });
  assert.equal(p.volume, 1); assert.equal(p.alarms, 0); assert.equal(p.expressiveness, 0.75);
  assert.equal(p.listen, "ptt"); assert.equal(p.filter, "normal"); assert.equal(p.theme, "dark");
  assert.equal(p.graphics, "low"); assert.equal(p.level, "commander"); assert.ok(!("junk" in p));
});

test("prefs: a cadet profile carries call sign, progress, settings and the voice-bar spot", () => {
  for (const k of ["outpost-callsign", "atm-academy", "outpost-a11y", "outpost-prefs", "outpost-voicebar"]) assert.ok(PROFILE_KEYS.includes(k), k);
});
