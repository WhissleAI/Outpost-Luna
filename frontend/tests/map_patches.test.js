// [0.4.1] Earned patches on the Flight School map (academy/earned.js; e2e: tests/e2e/map_patches_e2e.py).
// The map faces the next stop; from lesson 3 on it is at the south pole, and the near-side pins of Lessons 1 and 2 are
// round the limb (faded out). The earned patches therefore also sit in the map header, always in view.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { earnedPatches, patchStripHtml } from "../src/academy/earned.js";
import { patch } from "../src/assets/icons.js";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const COURSE = JSON.parse(src("../../backend/data/academy/course.json"));
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ll2v = (lat, lon) => { const p = lat * Math.PI / 180, l = lon * Math.PI / 180; return [Math.cos(p) * Math.cos(l), Math.sin(p), -Math.cos(p) * Math.sin(l)]; };

test("the owner's 0.4.0 progress (badge ids) gives three earned patches, in course order, with their art", () => {
  const list = earnedPatches(COURSE.lessons, ["scout", "watcher", "sun"]);
  assert.deepEqual(list.map(p => p.id), ["moon", "phases", "power"]);
  const html = patchStripHtml(list, { patch, esc });
  assert.equal((html.match(/class="mp-patchbtn"/g) || []).length, 3);
  assert.equal((html.match(/class="patch patch-\w+ is-earned"/g) || []).length, 3, "every strip patch is in colour");
  for (const p of list) assert.match(html, new RegExp(`data-l="${p.id}"[^>]*aria-label="${p.name} patch"`));
});

test("no patches, no strip; unknown badge ids are ignored; every lesson's patch has art", () => {
  assert.equal(patchStripHtml(earnedPatches(COURSE.lessons, []), { patch, esc }), "");
  assert.deepEqual(earnedPatches(COURSE.lessons, ["nope", "moon"]), [], "progress keeps badge ids, not lesson ids");
  assert.deepEqual(earnedPatches(null, ["scout"]), []);
  for (const l of COURSE.lessons) assert.match(patch(l.id, { earned: true }), /is-earned/, `${l.id} has patch art`);
  const all = earnedPatches(COURSE.lessons, COURSE.lessons.map(l => l.badge.id));
  assert.equal(all.length, COURSE.lessons.length, "Field School and bonus patches show too");
});

test("why: from a polar next stop, Lessons 1 and 2 are round the limb (the map's pins fade at n·cam <= 0.3)", () => {
  // the map's polar framing looks from -89° straight down the pole (academy/ui.js showMap: polar ? -89 : lat)
  const cam = ll2v(-89, -1.67), dot = (a, b) => a.reduce((s, x, i) => s + x * b[i], 0);
  const places = JSON.parse(src("../../backend/data/places.json"));
  const at = id => { const f = places.places.find(x => x.id === id); return [f.lat, f.lon]; };
  const near = ["moon", "phases"].map(id => COURSE.lessons.find(l => l.id === id)).map(l => at(l.place));
  for (const [lat, lon] of near) assert.ok(dot(ll2v(lat, lon), cam) <= 0.3, `${lat},${lon} is hidden from the polar view`);
});

test("showMap renders the strip from the saved badges and a strip patch acts like its pin", () => {
  const ui = src("../src/academy/ui.js");
  assert.match(ui, /patchStripHtml\(earnedPatches\(ls, prog\.badges\), \{ patch, esc \}\)/);
  assert.match(ui, /querySelectorAll\("\.mp-patchbtn"\)\.forEach\(pb => pb\.onclick = /);
  assert.match(ui, /b\.onclick = \(\) => pickPin\(l, sel\);/);
  assert.match(src("../src/school.css"), /\.mp-patchbtn\{/);
});
