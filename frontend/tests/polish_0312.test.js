// [0.3.12] Polish group A: in-app lesson, cockpit and voice (docs/UX_ROUNDS.md "0.3.12 polish").
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { GATE, rideReady } from "../src/story.js";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const words = t => String(t).trim().split(/\s+/).length;

test("'Fly the check ride' before the lessons are done says when it opens, and opens the next lesson", () => {
  assert.equal(GATE.rideLocked(2, 6), "Unlocks after 6 lessons (2/6)");
  assert.ok(words(GATE.rideLocked(2, 6)) <= 12, "a supporting line (COPY.md)");
  assert.equal(rideReady({ n: 2, of: 6 }), false);
  assert.equal(rideReady({ n: 6, of: 6 }), true);
  assert.equal(rideReady(null), false);
  const ui = src("../src/mission/ui.js"), main = src("../src/main.js"), ac = src("../src/academy/ui.js");
  assert.match(ui, /rideButton\("mx-link", "mRide"\)/);
  assert.match(ui, /rideButton\("mx-go", "mRide2"\)/);
  assert.match(ui, /GATE\.rideLocked\(c\.n, c\.of\)/);
  // goRide: the ride itself when ready, else the next core lesson (never just the map)
  assert.match(main, /goRide: \(\) => \{ const r = academyUI\.rideStatus\(\), id = rideReady\(r\) \? r\.ride : r\.next;/);
  assert.match(main, /academyUI\.nav\("lesson", id\)/);
  assert.match(ac, /rideStatus: \(\) =>/);
});
