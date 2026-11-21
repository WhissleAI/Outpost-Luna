// [courses playtest] The Archaeology novice playtest (Karan, 0.5.2: "the whole experience in archaeology is a bit
// choppy"): a first-time high-schooler who picks Archaeology never met CAPCOM, Houston, a check ride or a mission. The
// app's own words follow the course; the Moon keeps every line it had. e2e: tests/e2e/arch_workflows_e2e.py.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as C from "../src/courses.js";
import { doLine, introFor, INTRO, DO } from "../src/academy/guide.js";
import { parseCommand } from "../src/a11y.js";
import { runDirective } from "../src/academy/globe_steps.js";
import * as B from "../src/brain.js";
import { COPY as PCOPY } from "../src/progress.js";
import { COPY as CCOPY } from "../src/class_editor.js";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const ARCH = JSON.parse(src("../../backend/data/courses/archaeology/course.json"));
const MANIFEST = JSON.parse(src("../../backend/data/courses/archaeology.json"));
const ARCH_INFO = { id: "archaeology", title: "Archaeology", program: MANIFEST.program, grades: "9-12", labels: MANIFEST.labels,
  globe: MANIFEST.globe, big_ideas: MANIFEST.big_ideas, missions: null };
const MOON_INFO = { id: "moon", title: "The Moon", globe: { body: "moon" }, labels: {}, missions: "outpost" };
function as(course, fn) {
  const was = { ...C.courseState };
  Object.assign(C.courseState, course === "moon" ? { active: "moon", info: MOON_INFO } : { active: "archaeology", info: ARCH_INFO });
  C.setRoles(course === "moon" ? null : ARCH.roles);
  try { return fn(); } finally { Object.assign(C.courseState, was); C.setRoles(null); }
}

test("the course names its own voices: Field Director and The Lab; the Moon keeps CAPCOM and Houston", () => {
  as("archaeology", () => {
    assert.equal(C.roleName("capcom", "CAPCOM"), "Field Director");
    assert.equal(C.roleName("houston", "Houston"), "The Lab");
    assert.equal(C.roleName("nobody", "Guide"), "Guide");
  });
  as("moon", () => { assert.equal(C.roleName("capcom", "CAPCOM"), "CAPCOM"); assert.equal(C.roleName("houston", "Houston"), "Houston"); });
  // the caption bar, the transcript and the answer card all ask roleName (they hard-coded "CAPCOM")
  assert.match(src("../src/caption.js"), /get capcom\(\) \{ return roleName\("capcom", "CAPCOM"\); \}/);
  assert.match(src("../src/a11y.js"), /e\.who === "capcom" \? roleName\("capcom", "CAPCOM"\)/);
  assert.equal((src("../src/main.js").match(/title: "CAPCOM"/g) || []).length, 0, "no answer card is titled CAPCOM in every course");
});

test("a keywords step names a term in Archaeology (no 'radio practice', no 'say the order back')", () => {
  const st = { accept: { type: "keywords" } };
  as("archaeology", () => {
    assert.equal(doLine(st), "Say the word, or type it");
    assert.equal(introFor("keywords"), "New: name it. Say the word, or type it.");
    assert.doesNotMatch(doLine({ accept: { type: "globe_side" } }), /Moon/);
    assert.equal(introFor("layers"), INTRO.layers, "the archaeology steps keep their own lines");
  });
  as("moon", () => { assert.equal(doLine(st), DO.keywords); assert.equal(introFor("keywords"), INTRO.keywords); });
  for (const l of ARCH.lessons) for (const s of l.steps) as("archaeology", () => {
    const words = `${doLine(s)} ${introFor(s.accept.type) || ""}`;
    assert.doesNotMatch(words, /\b(radio|order back|Moon|CAPCOM|Houston|NASA video)\b/i, `${l.id}/${s.accept.type}: ${words}`);
  });
});

test("a hesitant 'um, I don't know' climbs the hint ladder like the bare words; a filler alone stays nothing", () => {
  for (const t of ["um I don't know", "Um, I dont know", "uh hmm I don't know", "so what do I do", "okay um help"]) assert.deepEqual(parseCommand(t), { cmd: "help" }, t);
  assert.deepEqual(parseCommand("hmm what"), { cmd: "confused" });
  assert.equal(parseCommand("um"), null);
  assert.equal(parseCommand("um the bottom layer"), null, "an answer after a filler is still an answer");
});

test("a find step flown to a neighbour never names the neighbour on the spot to find (Four Corners over Mesa Verde)", () => {
  const calls = [];
  const globe = new Proxy({}, { get: (_, k) => (...a) => calls.push([k, ...a.map(x => (x && x.id) || x)]) });
  const placeById = id => ({ id, lat: 37, lon: -109 });
  runDirective(globe, { do: "fly", place: "four_corners" }, { target: "mesa_verde", placeById });
  assert.deepEqual(calls.map(c => c[0]), ["showFeature", "clearHighlight"], "flown there, then the ring and its name are cleared");
  calls.length = 0;
  runDirective(globe, { do: "fly", place: "tycho" }, { target: null, placeById });
  assert.deepEqual(calls.map(c => c[0]), ["showFeature"], "the Moon's fly steps (no find target) keep their ring");
  calls.length = 0;
  runDirective(globe, { do: "fly", place: "mesa_verde" }, { target: "mesa_verde", placeById });
  assert.deepEqual(calls.map(c => c[0]), ["showFeature"]);
  const ARCH_FLY = ARCH.lessons.flatMap(l => l.steps).filter(s => s.globe && s.globe.do === "fly" && ["intent", "tap"].includes(s.accept.type));
  assert.ok(ARCH_FLY.some(s => s.globe.place !== s.accept.place), "the content case this guards (what_is: Four Corners -> Mesa Verde)");
});

test("My Brain in Archaeology: no Cadet / Commander rank, no Missions count, no CAPCOM; the Moon's page as it was", () => {
  const LESSONS = ARCH.lessons.map(l => ({ ...l, id: `archaeology:${l.id}` }));
  const html = as("archaeology", () => B.cadetHtml({ callsign: "Pulsar", academy: { badges: [], qualified: false }, flown: [], lessons: LESSONS, brain: null, learned: null }));
  assert.match(html, /<p>Field crew<\/p>/);
  assert.doesNotMatch(html, /Missions|CAPCOM|Cadet|Commander|outpost/i, "no Moon words on the page");
  assert.match(html, /Field Director/);
  // the big ideas: one star per lesson with its own idea (they were the patch names)
  for (const l of ARCH.lessons) {
    const b = MANIFEST.big_ideas[l.id];
    assert.ok(b && b.star && b.idea && b.star.length <= 14, `${l.id}: a big idea with a short star name`);
    assert.notEqual(b.star, l.badge.name, `${l.id}: the star is the idea, not the patch name`);
    as("archaeology", () => assert.equal(B.skillOf({ ...l, id: `archaeology:${l.id}` }).star, b.star));
  }
  const moon = as("moon", () => B.cadetHtml({ callsign: "Nova", academy: { badges: [], qualified: false }, flown: [], lessons: [], brain: null, learned: null }));
  assert.match(moon, /<p>Cadet<\/p>/); assert.match(moon, /Missions/); assert.match(moon, /Talking to CAPCOM\?/);
});

test("For grown-ups in Archaeology: no missions in Progress, Class lessons sit in Field School (not next to NASA's)", () => {
  as("archaeology", () => {
    assert.doesNotMatch(PCOPY.line, /missions/);
    assert.equal(CCOPY.line, "Write lessons for your class. They show up in Field School next to the course's own.");
  });
  as("moon", () => {
    assert.match(PCOPY.line, /patches and missions/);
    assert.equal(CCOPY.line, "Write lessons for your class. They show up in Flight School next to NASA's.");
  });
  assert.match(src("../src/progress.js"), /hasMissions\(\) \|\| cadet\.flown\.length \? stat\(COPY\.missions/);
});

test("Archaeology's lesson text never sends a first-time teen to the Moon's jargon", () => {
  for (const l of ARCH.lessons) {
    if (l.bridge === "moon") continue;   // Moonrise at Chimney Rock is the bridge lesson: the Moon is its subject
    const words = JSON.stringify({ t: l.title, b: l.brief, s: l.steps.map(s => [s.prompt, s.hint, s.success, s.fail]) });
    assert.doesNotMatch(words, /\b(CAPCOM|Houston|astronaut|Flight School|check ride|Artemis)\b/, l.id);
  }
});

test("the Archaeology call-sign screen is the course's own (not 'Nobody's landed at the pole yet' over Africa)", () => {
  const ui = src("../src/academy/ui.js");
  assert.match(ui, /if \(region\) globe\.flyTo\(region\.lat, region\.lon, region\.dist\); else globe\.flyTo\(-20, 10, 3\.2\)/);
  assert.match(ui, /lines: \[info\.program \|\| info\.title \|\| "", `\$\{courseLabel\("school", "Field School"\)\} starts here\.`\]/);
  assert.match(ui, /<p class="h-credit">\$\{esc\(mapCredit\(\)\)\}<\/p>/, "the course's imagery credit, not NASA's Artemis line");
});
