// The landing-site navigator (docs/SITE_NAVIGATOR.md): the score mirrors the backend's (same shared cases), the weights,
// the "which site has the most ice?" answer, the number formats, and the gesture / intent wiring.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CRITERIA_IDS, PRESETS, score, criterion, bestFor, presetOf } from "../src/mission/navigator_score.js";
import { INTENTS } from "../src/input/intents.js";
import { ROUTER_INTENTS } from "../src/input/defaults.js";
import { SCREEN_MAP, screenKey } from "../src/gesture/map.js";

const CASES = JSON.parse(readFileSync(new URL("./fixtures/navigator_cases.json", import.meta.url)));
const place = v => ({ sunlight_pct: { value: v.sunlight_pct }, earth_pct: { value: v.earth_pct }, ice_km: { value: v.ice_km }, slope_deg: { value: v.slope_deg } });

test("the score matches backend/app/mission/navigator.py on every shared case", () => {
  for (const c of CASES) assert.equal(score(place(c.values), PRESETS[c.preset]), c.score, `${c.place} ${c.preset}`);
});

test("criteria: more sun and Earth is better, less ice distance and slope is better, clamped 0..1", () => {
  const p = place({ sunlight_pct: 90, earth_pct: 100, ice_km: 0, slope_deg: 0 });
  for (const id of CRITERIA_IDS) assert.equal(criterion(p, id), 1, id);
  const q = place({ sunlight_pct: 10, earth_pct: 0, ice_km: 40, slope_deg: 30 });
  for (const id of CRITERIA_IDS) assert.equal(criterion(q, id), 0, id);
  assert.equal(criterion({ sunlight_pct: { value: null } }, "power"), 0);   // a missing number never wins
});

test("weights: presets, all-zero counts as balanced, and the sliders name their preset", () => {
  const p = place({ sunlight_pct: 87, earth_pct: 54, ice_km: 2.9, slope_deg: 11 });
  assert.equal(score(p, { power: 0, comms: 0, ice: 0, safety: 0 }), score(p, PRESETS.balanced));
  assert.ok(score(p, PRESETS.power_first) > score(p, PRESETS.safety_first));
  assert.equal(presetOf({ power: 1, comms: 1, ice: 3, safety: 1 }), "ice_first");
  assert.equal(presetOf({ power: 2, comms: 1, ice: 3, safety: 1 }), null);
});

test("which site has the most ice / sun / Earth / the flattest", () => {
  const ps = [
    { id: "a", ...place({ sunlight_pct: 87, earth_pct: 54, ice_km: 2.9, slope_deg: 11 }) },
    { id: "b", ...place({ sunlight_pct: 0, earth_pct: 0, ice_km: 0.1, slope_deg: 4 }) },
    { id: "c", ...place({ sunlight_pct: 66, earth_pct: 64, ice_km: 12.1, slope_deg: 8 }) },
  ];
  assert.equal(bestFor(ps, "ice").id, "b");
  assert.equal(bestFor(ps, "sunlight").id, "a");
  assert.equal(bestFor(ps, "earth").id, "c");
  assert.equal(bestFor(ps, "slope").id, "b");
  assert.ok(["a", "b", "c"].includes(bestFor(ps, "best", PRESETS.balanced).id));
  assert.equal(bestFor(ps, "nonsense"), null);
});

test("the navigator's intents are on the bus and in the shell's router vocabulary", () => {
  for (const n of ["site_layer", "site_query", "site_preset", "pick_site"]) {
    assert.ok(INTENTS[n], n);
    assert.ok(ROUTER_INTENTS.has(n), n);
  }
});

test("gestures on the site picker: the fist moves the map, the pinch zooms it, thumbs up picks then flies", () => {
  const k = screenKey({ screen: "brief" });
  assert.equal(k, "sites");
  const m = SCREEN_MAP.sites;
  assert.match(m.fist, /map/i);
  assert.match(m.pinch, /zoom/i);
  assert.match(m.thumbs_up, /^Yes: pick/);
  assert.equal(screenKey({ screen: "debrief" }), "menu");   // the debrief keeps the menu gestures
});

test("navigator.js: the panel keeps the picker contract tools rely on (radio rows, #mStart)", () => {
  const src = readFileSync(new URL("../src/mission/navigator.js", import.meta.url), "utf8");
  assert.match(src, /class="mx-site nv-row" role="radio" data-site=/);
  assert.match(src, /id="mStart"/);
  assert.match(src, /Map layers downloading/);
  for (const l of ["sunlight", "slope", "ice", "earth"]) assert.match(src, new RegExp(`${l}:`));
});

test("numbers read kid-sized, and the spoken answers stay short", async () => {
  const { fmt, queryLine, LAYER_SAY } = await import("../src/mission/navigator_score.js");
  const floor = { name: "Shackleton Crater Floor", playable: true, ice_km: { value: 0.1 }, longest_dark_h: { value: 8761 }, sunlight_pct: { value: 0 } };
  assert.equal(fmt(floor, "ice_km"), "here");
  assert.equal(fmt(floor, "longest_dark_h"), "never lit");
  assert.equal(fmt({ longest_dark_h: { value: 64 } }, "longest_dark_h"), "64 h");
  assert.equal(fmt({ longest_dark_h: { value: 413 } }, "longest_dark_h"), "17.2 days");
  assert.equal(fmt({ slope_deg: { value: 10.6 } }, "slope_deg"), "11°");
  assert.equal(fmt({}, "earth_pct"), "–");
  const line = queryLine(floor, "ice");
  assert.match(line, /^Shackleton Floor\. Ice can last right there\./);
  assert.ok(line.split(/\s+/).length <= 20, line);
  const reg = { name: "Haworth", playable: false, earth_pct: { value: 65 } };
  assert.match(queryLine(reg, "earth"), /can't fly it yet/);
  for (const t of Object.values(LAYER_SAY)) assert.ok(t.split(/\s+/).length <= 14, t);
});
