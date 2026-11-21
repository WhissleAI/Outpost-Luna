// [arch QA 0.5.2] The Archaeology course's flow fixes: per-course words (no "cadet", "radio practice", "Flight School"
// or "Missions 0" in Archaeology), zoom-aware map clusters, the download's phases, the grown-ups' standards, and the
// lesson-screen helpers. The Moon keeps every line as it was.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = globalThis.window || {};
const C = await import("../src/courses.js");
const G = await import("../src/academy/guide.js");
const PINS = await import("../src/academy/pins.js");
const PICK = await import("../src/course_pick.js");
const STORE = await import("../src/course_store_ui.js");
const B = await import("../src/brain.js");
const STORY = await import("../src/story.js");
const CE = await import("../src/class_editor.js");
const src = p => readFileSync(new URL(p, import.meta.url), "utf8");

const ARCH = JSON.parse(src("../../backend/data/courses/archaeology.json"));
const ARCH_COURSE = JSON.parse(src("../../backend/data/courses/archaeology/course.json"));
const PLACES = Object.fromEntries(JSON.parse(src("../../backend/data/courses/archaeology/places.json")).places.map(p => [p.id, p]));
const onCourse = (id, info) => { C.courseState.active = id; C.courseState.info = info; };
const MOON = C.courseState.info;

test("keywords steps: the do-line and the intro are not the Moon's radio drill outside the Moon", () => {
  assert.equal(G.introFor("keywords", true), "New: radio practice. Say the order back.");
  assert.doesNotMatch(G.introFor("keywords", false), /radio|order/i);
  assert.match(G.introFor("keywords", false), /say|type/i);
  assert.doesNotMatch(G.COURSE_DO.keywords, /order/i);
  assert.match(G.COURSE_DO.keywords, /type it/i);
  // the Moon's own keywords steps keep their own do-line (course.json `do`), so the Moon reads as before
  const moon = JSON.parse(src("../../backend/data/academy/course.json"));
  moon.lessons.flatMap(l => l.steps).filter(s => s.accept.type === "keywords").forEach(s => assert.ok(s.do, s.prompt));
  assert.equal(G.introFor("layers", false), G.INTRO.layers);
});

test("a learner with no spoken call sign: 'Here we go.' (no 'cadet' outside the Moon)", () => {
  assert.equal(STORY.CAPCOM.lessonHello("", "Dirt piles up."), "Dirt piles up. Here we go.");
  assert.equal(STORY.CAPCOM.lessonHello("Nova", "Beat."), "Beat. Here we go, Nova.");
  assert.equal(STORY.CAPCOM.patch("", "Field Scout"), "Patch earned: Field Scout. Nice work.");
  const ui = src("../src/academy/ui.js");
  assert.doesNotMatch(ui, /callSign\.spoken\("cadet"\)|callSign\.spoken\("Cadet"\)/);
  assert.match(ui, /const learner = \(cap = false\) => \(moonCourse\(\) \? \(cap \? "Cadet" : "cadet"\) : ""\)/);
});

test("Archaeology words: class editor, My Brain (no Cadet, no Missions 0)", () => {
  onCourse("archaeology", { ...ARCH, labels: ARCH.labels, missions: null });
  try {
    assert.doesNotMatch(CE.COPY.line, /Flight School|NASA/);
    assert.match(CE.COPY.line, /Field School/);
    assert.equal(CE.COPY.saved, "Saved. It's in Field School now.");
    const html = B.cadetHtml({ callsign: "Nova", academy: { badges: [], qualified: false }, flown: [], lessons: [], brain: null });
    assert.doesNotMatch(html, /Missions|>Cadet</);
  } finally { onCourse("moon", MOON); }
  assert.equal(CE.COPY.saved, "Saved. It's in Flight School now.");
  assert.match(B.cadetHtml({ callsign: "Nova", academy: { badges: [], qualified: false }, flown: [], lessons: [], brain: null }), /Missions/);
});

test("Progress: what each Archaeology lesson teaches (never its title again) and its standards", () => {
  onCourse("archaeology", { ...ARCH });
  try {
    for (const l of ARCH_COURSE.lessons) {
      const lesson = { ...l, id: `archaeology:${l.id}` };
      const sk = B.skillOf(lesson);
      assert.notEqual(sk.idea, l.title, l.id);
      assert.ok(sk.idea.split(/\s+/).length >= 6, `${l.id}: a real line`);
      assert.deepEqual(sk.ngss, l.standards, l.id);
    }
    assert.equal(B.GROWN.ngss, "Standards");
    assert.match(B.GROWN.frameworks(ARCH.standards), /Colorado Academic Standards.*History 1\.1/);
    // an older pack without big ideas: the unit, not the title
    onCourse("archaeology", { ...ARCH, big_ideas: {} });
    assert.equal(B.skillOf({ id: "archaeology:layers", title: "Layers tell time", unit: "Excavation and stratigraphy", standards: ["CO SS History 1.1"], badge: { name: "Layer Reader" } }).idea, "Excavation and stratigraphy");
  } finally { onCourse("moon", MOON); }
  assert.equal(B.GROWN.ngss, "NGSS hooks");
});

test("map: nine Mesa Verde pins are one cluster; it fans out only when the fan fits the zoom", () => {
  const stops = ARCH_COURSE.lessons.map(l => PLACES[l.place]);
  const cl = PINS.clusterOf(stops);
  assert.ok(cl.every(c => c && c.g === cl[0].g), "Chimney Rock (1 degree east) shares the Mesa Verde spot");
  assert.equal(cl[0].n, stops.length);
  // ~110 px fan: whole-continent zoom (~7 px per degree) collapses; the region view (~45 px per degree) fans out
  assert.equal(PINS.fanFits(110, 7), false);
  assert.equal(PINS.fanFits(110, 45), true);
  assert.equal(PINS.fanFits(110, NaN), false);
  assert.ok(PINS.REGION_DIST >= 1.5 && PINS.REGION_DIST < 2, "within the globe's zoom limits, near the region");
  const ui = src("../src/academy/ui.js"), globe = src("../src/globe.js");
  assert.match(ui, /globe\.flyTo\(region\.lat, region\.lon, region\.dist\)/);   // lands on the region (pins.regionOf)
  assert.match(ui, /moonGlobe\(\) \? 2\.6 : REGION_DIST/);            // a lesson flies to its place
  assert.match(ui, /stops\[k\]\.group = groups\[k\]/);                // the fan's pins know their spot (count pin)
  assert.match(globe, /g\.collapsed = !fanFits\(fan, ppd\)/);
});

test("the Moon -> Earth bridge: a lesson's bridge shows the Moon, then flies to its place on Earth", () => {
  const cr = ARCH_COURSE.lessons.find(l => l.id === "chimney_rock");
  assert.equal(cr.bridge, "moon");
  const ui = src("../src/academy/ui.js"), globe = src("../src/globe.js");
  assert.match(ui, /L\.bridge === "moon" && !moonGlobe\(\) && globe\.bridgeFrom/);
  assert.match(globe, /function bridgeFrom\(map = MOON_BODY\.map/);
});

test("first download: percent, then the real phases, then 'Opening <course>…'", () => {
  assert.equal(PICK.stateLine({ state: "queued" }, "Archaeology"), PICK.COPY.waiting);
  assert.equal(PICK.stateLine({ state: "downloading", progress: 0.42 }, "Archaeology"), "42%");
  assert.equal(PICK.stateLine({ state: "downloading", progress: 1 }, "Archaeology"), PICK.COPY.verify);   // an older desktop app
  assert.equal(PICK.stateLine({ state: "downloading", progress: 1, phase: "verify" }, "Archaeology"), "Checking the download…");
  assert.equal(PICK.stateLine({ state: "downloading", progress: 1, phase: "install" }, "Archaeology"), "Installing…");
  assert.equal(PICK.stateLine({ state: "installed", progress: 1 }, "Archaeology"), "Opening Archaeology…");
  assert.match(src("../../desktop/main/assets.js"), /\$\{ph !== "download" \? ` \$\{ph\}` : ""\}/);
});

test("Course storage: a download shows its percent and phase", () => {
  const p = o => ({ id: "archaeology", title: "Course: Archaeology", size: 55e6, version: "3", state: "downloading", active: false, blocked: false, ...o });
  assert.equal(STORE.rowOf(p({ progress: 0.37 })).note, "Downloading… 37%");
  assert.equal(STORE.rowOf(p({ progress: 0.37 })).bar, 37);
  assert.equal(STORE.rowOf(p({})).note, "Downloading…");
  assert.equal(STORE.rowOf(p({ progress: 1, phase: "install" })).note, "Installing…");
});

test("removing the playing course says so after the reload", () => {
  assert.match(C.REMOVED_COPY("Archaeology"), /^Archaeology was removed\. You're on the Moon course now\. Get it again in Settings → For grown-ups → Course storage\.$/);
  assert.match(src("../src/course_store_ui.js"), /sessionStorage\.setItem\(REMOVED_KEY/);
  assert.match(src("../src/academy/ui.js"), /sessionStorage\.getItem\(REMOVED_KEY\)/);
});

test("lesson screen: decide's other call offers Try again; the ring reveal moves the beam; every course done has a next step", () => {
  const ui = src("../src/academy/ui.js");
  assert.match(ui, /stepState\.retry = acc\.type === "decide" && r\.best === false/);
  assert.match(ui, /id="aRetry"/);
  assert.match(ui, /if \(acc\.type === "rings" && y != null && Number\.isFinite\(\+y\)\) stepState\.outer = \+y/);
  assert.match(ui, /id="aDoneLib"/);
  assert.match(STORY.COURSE_DONE.next, /grown-up/); assert.match(STORY.COURSE_DONE.library, /Library/);
  assert.match(src("../src/school.css"), /\.a-where\{[^}]*white-space:nowrap/);
  assert.match(src("../src/academy/arch_steps.js"), /class="ar-glow-row"/);
});

test("describe steps that say 'this' or 'on the map' show their picture", () => {
  for (const l of ARCH_COURSE.lessons) l.steps.forEach((s, k) => {
    if (s.accept.type !== "describe") return;
    assert.ok(s.photo && s.photo.file && s.photo.alt && s.photo.credit, `${l.id} step ${k + 1}: ${s.prompt}`);
    assert.doesNotMatch(s.prompt, /potsherd/i, "no licensed potsherd photo in the pack: the step describes what it shows");
  });
  assert.match(src("../src/academy/ui.js"), /\$\{st\.photo \? photoHook\(/);
});
