// [0.3.12] P0: the check-ride cockpit was clipped beside the lesson card (31_cr_q1, 42_cr_storm_alert): Radiation cut,
// Rover off the left edge, the globe behind the card, "Shift 1 ·" with no site, "Day 8" on a two-day ride, and no
// caution & warning strip in the storm. One cabin across the stage; the seat view fits left of the card.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { clockDay, clockSub, rideInset, RIDE_PANELS } from "../src/mission/ride.js";
import { fitFov, baseFov, FIT_MAX_FOV, RIDE_LAYOUT } from "../src/mission/cockpit3d.js";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const strip = h => h.replace(/<[^>]+>/g, "");

test("the ride's clock: 'Day 1 of 2' (its own days), the site named, never a dangling '·'", () => {
  assert.equal(strip(clockDay({ ride: { day: 1, days: 2 } }, 168)), "Day 1 of 2");
  assert.equal(strip(clockDay({ ride: { day: 3, days: 2 } }, 216)), "Day 2 of 2", "clamped to the ride");
  assert.equal(strip(clockDay({}, 168)), "Day 8", "a mission keeps its own day");
  assert.equal(strip(clockDay({}, 999)), "Day 10");
  assert.equal(clockSub(1, { name: "Shackleton Crater Rim (connecting ridge)" }), "Shift 1 · Shackleton Crater Rim");
  assert.equal(clockSub(1, null), "Shift 1");
  assert.equal(clockSub(2, { name: "" }), "Shift 2");
});

test("the ride shows the caution & warning strip (pedestal) with the master alarm, its End shift hidden", () => {
  assert.ok(RIDE_PANELS.ride.includes("pedestal"));
  for (const p of ["displays", "radiation", "rover"]) assert.ok(RIDE_PANELS.ride.includes(p), p);
  assert.ok(!RIDE_PANELS.ride.includes("habitat") && !RIDE_PANELS.ride.includes("comm"));
  assert.match(src("../src/cabin.css"), /\.a-ridecabin\.is-ride \.cb-ped\{display:none\}/);
  assert.match(src("../src/mission/cabin.js"), /RIDE_PANELS\[o\.mode\]/);
});

test("the Rover takes the Habitat's high seat in the ride, facing the seat (no low, slanted console off-screen)", () => {
  assert.deepEqual(RIDE_LAYOUT.rover.pos, [-1.25, 1.14, -1.2]);
  assert.ok(Math.abs(RIDE_LAYOUT.rover.rot[0]) <= 0.25, "pitched back no more than the Radiation panel");
});

test("fitFov widens the seat view until every console is inside the free area (scaled, never clipped)", () => {
  // a fake projection: the faces' span shrinks as the field of view grows
  const span = (lo, hi) => fov => [lo + (fov - 56) * 6, hi - (fov - 56) * 6];
  assert.equal(fitFov(1.8, 1400, span(40, 1360)), 56, "fits already: the base, unchanged (no regression for a mission)");
  assert.equal(baseFov(1.15), 66);
  const f = fitFov(1.15, 970, span(-120, 1100));
  assert.ok(f > 66 && f < FIT_MAX_FOV, "widened just enough");
  const [x0, x1] = span(-120, 1100)(f); assert.ok(x0 >= 12 && x1 <= 970 - 12);
  assert.equal(fitFov(1.0, 300, () => [-9999, 9999]), FIT_MAX_FOV, "capped");
});

test("rideInset: the card's width plus a gap when it floats over the cabin's right edge; 0 when hidden or stacked", () => {
  const box = (left, width) => ({ getBoundingClientRect: () => ({ left, width, right: left + width }) });
  assert.equal(rideInset(box(0, 1440), box(985, 440)), 1440 - 985 + 12);
  assert.equal(rideInset(box(0, 1440), { ...box(985, 440), hidden: true }), 0);
  assert.equal(rideInset(box(0, 800), box(16, 768)), 0, "a narrow layout stacks the card: nothing to inset");
});

test("one cabin across the stage: no globe beside it; deck and view switch keep clear of the card", () => {
  const css = src("../src/cabin.css"), school = src("../src/school.css");
  assert.match(school, /\.m-cabin\.a-ridecabin\{right:0\}/);
  assert.match(css, /\.m-cabin\.a-ridecabin \.cb-deck,\.m-cabin\.a-ridecabin \.cb>\.cb-viewbar\{right:calc\(var\(--ride-inset, 0px\) \+ var\(--rail\)\)\}/);
  const ck = src("../src/mission/cockpit3d.js");
  assert.match(ck, /setViewOffset\(fw, h, 0, 0, w, h\)/, "the seat view is centred in the free area");
  assert.match(src("../src/academy/ui.js"), /insetRight/);
});
