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

test("one instruction per step: the 'New' chip replaces the bullet on first use; TTS and captions never say 'New:'", async () => {
  const { INTRO, introText, doLine } = await import("../src/academy/guide.js");
  for (const t of Object.values(INTRO)) { assert.doesNotMatch(introText(t), /^New\b/i, t); assert.match(introText(t), /^[A-Z]/, t); }
  assert.equal(introText("New: find a place. Tap the glowing ring."), "Find a place. Tap the glowing ring.");
  const ui = src("../src/academy/ui.js");
  assert.match(ui, /const showIntro = !!intro && !waitingNext && !feedback;/);
  assert.match(ui, /how && !waitingNext && !showIntro \? `<p class="a-how a-do">/);
  // every spoken intro goes through introText (no raw INTRO line reaches say())
  assert.doesNotMatch(ui, /\.\.\.\(intro \? \[intro\] : \[\]\)/);
  assert.doesNotMatch(ui, /say\(intro \? \[st\.prompt, intro\]/);
  assert.ok(doLine({ accept: { type: "tap" } }), "the bullet still exists for later steps");
});

test("the map never explains its own card: no 'Tap Start lesson', no 'Next: <title>' over the Next up card", async () => {
  const { TRANSITION } = await import("../src/story.js");
  assert.ok(!TRANSITION.firstMap.intro.some(t => /Start lesson/.test(t)));
  assert.doesNotMatch(src("../src/academy/ui.js"), /`Next: \$\{nx\.title\}\.`/);
});

test("predict before watch: Watch how waits in the Brief until the guess; core steps show NASA videos only", async () => {
  const { prepVideos, prepPlace } = await import("../src/academy/guide.js");
  const cat = [{ id: "a", prep: "p", nasa: false }, { id: "b", prep: "p" }, { id: "c", prep: "q" }];
  assert.deepEqual(prepVideos(cat, "p").map(v => v.id), ["b", "a"], "NASA first");
  assert.deepEqual(prepVideos(cat, "p", { nasaOnly: true }).map(v => v.id), ["b"], "no 'Not from NASA' extra on a core step");
  assert.equal(prepPlace({ prep: { id: "p" } }, 0, false), "brief", "before the guess: only behind the Brief");
  assert.equal(prepPlace({ prep: { id: "p" } }, 0, true), "step", "after the guess: under the answer");
});

test("captions fold a spoken line that is already on the card (the lead and the 'New' line too)", () => {
  assert.match(src("../src/main.js"), /#aPanel \.a-lead, #aPanel \.a-intro/);
});
