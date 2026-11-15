// The cabin's "Why?" cards and Engineer mode (docs/PHYSICS.md): every input reaches the same `why` intent.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { keyAction, helpRows } from "../src/input/keys.js";
import { ROUTER_INTENTS } from "../src/input/defaults.js";
import { INTENTS } from "../src/input/intents.js";
import { DEBRIEF } from "../src/story.js";

test("the I key, voice and the bus all name the why intent", () => {
  assert.deepEqual(keyAction({ key: "i" }, {}), { intent: "why", args: {} });
  assert.equal(keyAction({ key: "i" }, { typing: true }), null);   // typing an order never opens a card
  assert.ok(ROUTER_INTENTS.has("why") && "why" in INTENTS);
  for (const s of ["cabin_seat", "cabin_panel"]) assert.ok(helpRows(s)[0].rows.some(([k]) => k === "I"), s);
});

test("every gauge has its (i) and the card reads the sim's words", () => {
  const src = readFileSync(new URL("../src/mission/cabin.js", import.meta.url), "utf8");
  for (const g of ["power", "battery", "life_support", "dose", "heaters", "shields", "rover"]) assert.match(src, new RegExp(`whyBtn\\("${g}"\\)|"${g}"\\)`), g);
  assert.match(src, /st\.why\[id\]/);                     // the words come from state.why (physics.py), never typed here
  assert.match(src, /whyOff\(\)/);                        // its listeners go with the cabin (root outlives it)
});

test("Engineer is a Settings level; the debrief has its numbers title", () => {
  const a11y = readFileSync(new URL("../src/a11y.js", import.meta.url), "utf8"), prefs = readFileSync(new URL("../src/prefs.js", import.meta.url), "utf8");
  assert.match(a11y, /\["engineer", "Engineer/);
  assert.match(prefs, /pick\("level", \["cadet", "commander", "engineer"\]\)/);
  assert.ok(DEBRIEF.numbersTitle && DEBRIEF.numbersTitle.split(" ").length <= 6);
});
