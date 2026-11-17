// Mission polish 4 (docs/MISSION_POLISH_SPEC.md, waves 4 and 5): the hub, the 3-card briefing, teach by doing in
// place of the 12-step tour, the debrief with stars first and its buttons always on screen, one wording for the
// storm's shields order, and Up from the cabin's own controls never dropping back onto a console.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { HUB, BRIEFING, COACH, DEBRIEF, NOW, HELP, PICKER } from "../src/story.js";
import { COACH_STEPS, COACH_MAX_MS, coachText } from "../src/mission/coach.js";

const words = t => String(t).trim().split(/\s+/).length;
const src = p => readFileSync(new URL(p, import.meta.url), "utf8");

test("hub: one mission, one Start; the navigator and the why are one press away", () => {
  assert.equal(HUB.start, "Start");
  assert.equal(HUB.choose, "Choose site");
  assert.equal(HUB.eyebrow(1), "Mission 1 · 10 days");
  assert.ok(words(HUB.whatLine) <= 20, HUB.whatLine);
  assert.match(HUB.video, /1-min briefing/);
  assert.equal(PICKER.go, "Start");   // the navigator's primary goes on to the briefing too
  const ui = src("../src/mission/ui.js");
  assert.match(ui, /function hub\(\)/);
  assert.match(ui, /id="mStart"><span>\$\{esc\(HUB\.start\)\}/);
  assert.match(ui, /id="mHubSite"/);
  // entering Mission lands on the hub, not the data-sheet picker
  assert.match(ui, /showHud\(\); return; \}[^\n]*\n\s*hub\(\);/);
});

test("briefing: three cards of 12 words or fewer, then Take command", () => {
  assert.deepEqual(BRIEFING.cards.map(c => c.label), ["Goal", "Danger", "Bonus"]);
  for (const c of BRIEFING.cards) assert.ok(words(c.text) <= 12, c.text);
  assert.equal(BRIEFING.cards[0].text, "Keep the crew safe for 10 days.");
  assert.equal(BRIEFING.go, "Take command");
  assert.ok(words(BRIEFING.say) <= 20);
  assert.ok(HELP.hub && HELP.briefing);
});

test("the Moon Base video is a chip on the hub, never a blocking yes / no before the cabin", () => {
  const ml = src("../src/mission_learning.js");
  assert.doesNotMatch(ml, /closest\("#mStart"\)/);          // no click interceptor on Start / Take command
  assert.doesNotMatch(ml, /role", "dialog"/);
  assert.match(ml, /mHubVideo/);
});

test("teach by doing: three prompts, words for keys / controller / touch, no buttons, tour only in Help", () => {
  assert.deepEqual(COACH_STEPS, ["now", "time", "menu"]);
  for (const id of COACH_STEPS) {
    assert.match(coachText(id, "keys"), id === "now" ? /Press T/ : id === "time" ? /Hold F/ : /Esc/);
    assert.match(coachText(id, "pad"), id === "now" ? /\bA\b/ : id === "time" ? /RT/ : /Start/);
    assert.ok(coachText(id, "mouse").length > 0);
    for (const m of ["keys", "pad", "touch"]) assert.ok(words(COACH[id][m]) <= 12, COACH[id][m]);
  }
  assert.equal(COACH_MAX_MS.now, 0);   // the first prompt waits for the press
  const coach = src("../src/mission/coach.js");
  assert.doesNotMatch(coach, /<button/);
  const ui = src("../src/mission/ui.js");
  assert.doesNotMatch(ui, /tour\.start\(band\(level\)/);   // the first mission no longer starts the 12-step tour
  assert.match(ui, /tour\.start\(band\(levelNow\(\)\)\)/);  // "Show me around" still replays it
  assert.match(ui, /coach\.did\("now"\)/);
});

test("debrief: stars first, Next mission / Fly again sit above the scrolling body", () => {
  assert.equal(DEBRIEF.next, "Next mission");
  assert.equal(DEBRIEF.choiceAgain, "Fly again");
  const ui = src("../src/mission/ui.js");
  const i = ui.indexOf('class="mx-db-top mx-db-hero"'), f = ui.indexOf('<div class="mx-foot">${foot}'), body = ui.indexOf('<div class="mx-db-body">');
  assert.ok(i > 0 && f > i && body > f, "hero, then the buttons, then the body");
  assert.ok(ui.indexOf("${starsHtml}") > i && ui.indexOf("${starsHtml}") < ui.indexOf('<h2 class="mx-title">${head}'), "stars before the title");
  assert.match(ui, /won \? btn\("mNext", "mx-go", DEBRIEF\.next\)/);
  const css = src("../src/mission/mission.css");
  assert.match(css, /\.mx-db-body\{flex:1 1 auto;min-height:0;overflow:auto/);
  assert.match(css, /\.mx-debrief \.mx-foot\{flex:none\}/);
  // Learn more goes into the body, not under the buttons
  assert.match(src("../src/mission_learning.js"), /body\.append\(sec\)/);
});

test("one wording for the storm's orders: the sim's 'Shields to 40' and 'Crew into the shelter' everywhere", () => {
  assert.equal(NOW.shieldsBtn, "Shields to 40");
  assert.equal(NOW.shelterBtn, "Crew into the shelter");
  const py = src("../../backend/app/session.py");
  assert.doesNotMatch(py, /Set shields to 40|"Go to shelter"/);
  assert.match(py, /"label": "Shields to 40"/);
  assert.match(py, /"label": "Crew into the shelter"/);
  assert.match(src("../../backend/app/mission/gameplay.py"), /"Shields to 40"/);
});

test("keys: Up from the view bar / deck / Now card never lands on a 3D console (the Orbit <-> seat trap)", () => {
  const sp = src("../src/input/spatial.js");
  assert.match(sp, /const hudUp = dir === "up" && a !== seatEl/);
  assert.match(sp, /\.\.\.\(hudUp \? \[\] : panelEls\(\)\)/);
  assert.match(sp, /"#mBriefGo", "#mDebrief\[data-primary=next\] #mNext", "#mAgain"/);
});

test("a story moment's 'Day N' never prints over a window marker (OUTPOST, ROVER...)", () => {
  const cab = src("../src/mission/cabin.js");
  assert.match(cab, /function clearMarks\(\)/);
  assert.match(src("../src/cabin.css"), /\.tv-mark\.is-under\{opacity:0!important/);
});
