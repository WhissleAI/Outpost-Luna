// Courses on the client (src/courses.js, docs/COURSES.md §4): course-prefixed ids, the lossless migration of a
// pre-courses save, per-course progress views, the launch sync and the switch.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const C = await import("../src/courses.js");

function mem(init = {}) {
  const d = { ...init };
  return { d, getItem: k => (k in d ? d[k] : null), setItem: (k, v) => { d[k] = String(v); }, removeItem: k => { delete d[k]; } };
}
// a real 0.4.x save: two NASA patches, qualified, a half-done lesson, a Class lesson patch
const V1 = { badges: ["scout", "phases-patch", "c-mrs-k-planets"], qualified: true, steps: { power: { i: 3, n: 7 } }, current: "power" };

test("ids: <course>:<id>, and a bare id is the Moon's", () => {
  assert.equal(C.qid("archaeology", "dating"), "archaeology:dating");
  assert.deepEqual(C.splitQid("archaeology:dating"), { course: "archaeology", id: "dating" });
  assert.deepEqual(C.splitQid("phases"), { course: "moon", id: "phases" });
  assert.deepEqual(C.splitQid("c-pack-lesson"), { course: "moon", id: "c-pack-lesson" });
  assert.deepEqual(C.splitQid("Bad Course:x"), { course: "moon", id: "Bad Course:x" });   // not a course id: kept whole
  assert.equal(C.qid("Nope!", "x"), "moon:x");
});

test("migration: a v1 save becomes the Moon's progress under prefixed ids, losing nothing", () => {
  const s = C.migrateAcademy({ ...V1, extra: { keep: 1 } });
  assert.equal(s.v, 2);
  assert.deepEqual(s.badges, ["moon:scout", "moon:phases-patch", "moon:c-mrs-k-planets"]);
  assert.deepEqual(s.qualified, ["moon"]);
  assert.deepEqual(s.steps, { "moon:power": { i: 3, n: 7 } });
  assert.deepEqual(s.current, { moon: "moon:power" });
  assert.deepEqual(s.extra, { keep: 1 });                          // unknown fields ride along
  // and the Moon's view is exactly the v1 save
  assert.deepEqual(C.courseView(s, "moon"), { badges: V1.badges, qualified: true, steps: V1.steps, current: "power" });
  assert.deepEqual(C.courseView(s, "archaeology"), { badges: [], qualified: false, steps: {}, current: null });
});

test("migration is idempotent and survives junk", () => {
  const once = C.migrateAcademy(V1), twice = C.migrateAcademy(once);
  assert.deepEqual(twice, once);
  for (const junk of [null, 7, "x", [], { badges: "nope", steps: { a: { i: "1" } }, current: 3 }]) {
    const s = C.migrateAcademy(junk);
    assert.equal(s.v, 2); assert.deepEqual(s.badges, []); assert.deepEqual(s.steps, {});
  }
  const v1empty = C.migrateAcademy({ badges: [], qualified: false });
  assert.deepEqual(C.courseView(v1empty, "moon"), { badges: [], qualified: false, steps: {}, current: null });
});

test("readStore migrates in place once and keeps the original save as atm-academy.v1", () => {
  const raw = JSON.stringify(V1), st = mem({ "atm-academy": raw });
  const s = C.readStore(st);
  assert.equal(st.d["atm-academy.v1"], raw);                       // byte-for-byte
  assert.equal(JSON.parse(st.d["atm-academy"]).v, 2);
  assert.deepEqual(C.readStore(st), s);
  assert.equal(st.d["atm-academy.v1"], raw);                       // a second read never overwrites the copy
  const fresh = mem();
  C.readStore(fresh);
  assert.equal(fresh.d["atm-academy"], undefined);                 // a new cadet: nothing written, no copy
  assert.equal(fresh.d["atm-academy.v1"], undefined);
});

test("per-course views: writing one course leaves the others alone", () => {
  let s = C.migrateAcademy(V1);
  s = C.mergeView(s, "archaeology", { badges: ["archaeology:trowel"], qualified: false, steps: { "archaeology:dating": { i: 2, n: 5 } }, current: "archaeology:dating" });
  assert.deepEqual(C.courseView(s, "moon"), { badges: V1.badges, qualified: true, steps: V1.steps, current: "power" });
  // another course's view uses its lessons' own (prefixed) ids, as the backend serves them
  assert.deepEqual(C.courseView(s, "archaeology"), { badges: ["archaeology:trowel"], qualified: false, steps: { "archaeology:dating": { i: 2, n: 5 } }, current: "archaeology:dating" });
  assert.equal(C.qid("archaeology", "archaeology:dating"), "archaeology:dating");   // idempotent
  // the Moon earns a patch and finishes its lesson: archaeology is untouched
  const m = C.courseView(s, "moon");
  s = C.mergeView(s, "moon", { ...m, badges: [...m.badges, "power-patch"], steps: {}, current: null });
  assert.ok(s.badges.includes("moon:power-patch") && s.badges.includes("archaeology:trowel"));
  assert.deepEqual(s.current, { archaeology: "archaeology:dating" });
  assert.deepEqual(C.migrateAcademy(JSON.parse(JSON.stringify(s))), s);   // a v2 store reads back the same
});

test("viewOfRaw: other cadets' snapshots, any version", () => {
  assert.deepEqual(C.viewOfRaw(JSON.stringify(V1)).badges, V1.badges);
  assert.deepEqual(C.viewOfRaw(null).badges, []);
  assert.deepEqual(C.viewOfRaw("{broken").badges, []);
});

test("the active course is per cadet, default the Moon", () => {
  assert.equal(C.activeCourse(mem()), "moon");
  assert.equal(C.activeCourse(mem({ "outpost-course": "archaeology" })), "archaeology");
  assert.equal(C.activeCourse(mem({ "outpost-course": "<script>" })), "moon");
});

const res = (body, ok = true) => ({ ok, json: async () => body });
const COURSES = { active: "moon", courses: [{ id: "moon", title: "The Moon", status: "builtin", labels: { patches: "NASA patches" } },
  { id: "archaeology", title: "Archaeology", status: "pack", labels: { course: "Archaeology", school: "Field School" } }] };

test("syncCourse: tells the backend this cadet's course; a missing course plays the Moon and keeps the choice", async () => {
  const calls = [];
  const fetchFn = async (url, o) => { calls.push([url, o && o.body]); return url === "/api/courses" ? res(COURSES) : res({ active: "archaeology" }); };
  const st = mem({ "outpost-course": "archaeology" });
  const s = await C.syncCourse({ fetchFn, storage: st });
  assert.equal(s.active, "archaeology"); assert.equal(C.courseLabel("school"), "Field School");
  assert.deepEqual(calls[1], ["/api/courses/active", JSON.stringify({ id: "archaeology" })]);
  const gone = mem({ "outpost-course": "geology" }); calls.length = 0;
  const s2 = await C.syncCourse({ fetchFn, storage: gone });
  assert.equal(s2.active, "moon"); assert.equal(calls.length, 1);   // already the Moon: no POST
  // [arch-patches] the choice survives a launch where the pack is missing (it used to be erased: the owner's
  // archaeology patches "disappeared" behind a Moon map), and the Moon's progress is what this launch reads and writes
  assert.equal(gone.d["outpost-course"], "geology");
  assert.equal(C.playingCourse(gone), "moon");
  assert.equal(C.courseLabel("patches"), "NASA patches");
});

test("syncCourse: an older backend or no network leaves the Moon, never throws", async () => {
  const s = await C.syncCourse({ fetchFn: async () => { throw new Error("offline"); }, storage: mem({ "outpost-course": "archaeology" }) });
  assert.equal(s.active, "moon");
  const s2 = await C.syncCourse({ fetchFn: async () => res({}, false), storage: mem() });
  assert.equal(s2.active, "moon");
});

test("setCourse: stores, announces, reloads; refuses what the backend refuses", async () => {
  const st = mem(); let reloaded = 0, heard = null;
  globalThis.dispatchEvent = e => { heard = e.detail; };
  globalThis.CustomEvent = globalThis.CustomEvent || class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } };
  assert.equal(await C.setCourse("archaeology", { fetchFn: async () => res({ active: "archaeology" }), storage: st, reload: () => reloaded++ }), true);
  assert.equal(st.d["outpost-course"], "archaeology"); assert.equal(reloaded, 1); assert.deepEqual(heard, { id: "archaeology" });
  assert.equal(await C.setCourse("moon", { fetchFn: async () => res({ active: "moon" }), storage: st, reload: () => reloaded++ }), true);
  assert.equal(st.d["outpost-course"], undefined);                 // the Moon is the default: no key
  assert.equal(await C.setCourse("atlantis", { fetchFn: async () => res({}, false), storage: st, reload: () => reloaded++ }), false);
  assert.equal(await C.setCourse("Bad!", { fetchFn: async () => res({}), storage: st }), false);
  assert.equal(reloaded, 2);
});

test("the course choice and the pre-courses copy are profile keys and progress keys", async () => {
  const prefs = await import("../src/prefs.js"), reset = await import("../src/reset.js");
  for (const k of ["outpost-course", "atm-academy.v1"]) {
    assert.ok(prefs.PROFILE_KEYS.includes(k), k);
    assert.ok(reset.isProgressKey(k), k);
  }
});

test("the Brain reads big ideas from the course and keeps counts per course", async () => {
  const B = await import("../src/brain.js");
  C.courseState.active = "moon"; C.courseState.info = { id: "moon", big_ideas: {} };
  assert.equal(B.lessonKey("phases"), "phases");                  // the Moon: bare, so saved counts stay valid
  assert.equal(B.skillOf({ id: "phases" }).star, "Phases");        // the table (the manifest has the same, tests below)
  C.courseState.active = "archaeology"; C.courseState.info = { id: "archaeology", big_ideas: { dating: { star: "Tree rings", idea: "Dating by rings.", codes: ["HS-ESS1-6"] } } };
  assert.equal(B.lessonKey("dating"), "archaeology:dating");
  assert.deepEqual(B.skillOf({ id: "dating", title: "Dating" }), { star: "Tree rings", idea: "Dating by rings.", ngss: ["HS-ESS1-6"] });
  C.courseState.active = "moon"; C.courseState.info = { id: "moon", big_ideas: {} };
});

test("the Moon manifest's big ideas equal the Brain's table", async () => {
  const { readFileSync } = await import("node:fs");
  const B = await import("../src/brain.js");
  const m = JSON.parse(readFileSync(new URL("../../backend/data/courses/moon.json", import.meta.url), "utf8"));
  for (const [id, s] of Object.entries(B.SKILLS)) assert.deepEqual({ star: m.big_ideas[id].star, idea: m.big_ideas[id].idea, ngss: m.big_ideas[id].codes }, s, id);
  assert.deepEqual(Object.keys(m.big_ideas).sort(), Object.keys(B.SKILLS).sort());
});

test("[arch-patches] progress follows the course being played, not just the stored key", async () => {
  const fetchFn = async url => (url === "/api/courses" ? res({ ...COURSES, active: "archaeology" }) : res({ active: "archaeology" }));
  const st = mem({ "outpost-course": "archaeology" });
  await C.syncCourse({ fetchFn, storage: st });
  assert.equal(C.playingCourse(st), "archaeology");
  // the stored key goes away mid-session (another tab, a profile tool): the lessons on screen are still Archaeology's
  delete st.d["outpost-course"];
  assert.equal(C.playingCourse(st), "archaeology");
  // the backend refuses the switch: the course it plays is the one progress uses
  const refusing = async (url, o) => (url === "/api/courses" ? res({ ...COURSES, active: "moon" }) : res({}, false));
  const st2 = mem({ "outpost-course": "archaeology" });
  const s = await C.syncCourse({ fetchFn: refusing, storage: st2 });
  assert.equal(s.active, "moon"); assert.equal(C.playingCourse(st2), "moon");
});

test("[arch-patches] three Archaeology lessons in a row: every patch stays in the store and in the view", () => {
  let store = C.migrateAcademy(null);
  const ids = ["archaeology:field_scout", "archaeology:sky_surveyor", "archaeology:layer_reader"];
  ids.forEach((b, k) => {
    const v = C.courseView(store, "archaeology");
    assert.deepEqual(v.badges, ids.slice(0, k), `before lesson ${k + 1}`);
    v.badges.push(b);
    store = C.mergeView(store, "archaeology", v);
  });
  assert.deepEqual(C.courseView(store, "archaeology").badges, ids);
  assert.deepEqual(store.badges, ids, "prefixed once, never 'archaeology:archaeology:…' or 'moon:archaeology:…'");
  assert.deepEqual(C.courseView(store, "moon").badges, []);
});

test("[arch-patches] the lesson loop's Moon-only lines stay on the Moon (map credit, patch count, facts, patch word)", async () => {
  const S = await import("../src/story.js");
  const { readFileSync } = await import("node:fs");
  const ui = readFileSync(new URL("../src/academy/ui.js", import.meta.url), "utf8");
  assert.equal(S.COURSE_DONE.progress(2, 10), "2 of 10 lessons done. 8 to go.");
  assert.equal(S.COURSE_DONE.progress(9, 10), "9 of 10 lessons done. One to go.");
  assert.equal(S.COURSE_DONE.progress(10, 10), "10 of 10 lessons done. That's every lesson.");
  assert.ok(!/check ride|NASA|Moon/.test(S.COURSE_DONE.progress(3, 10) + S.COURSE_DONE.title(10, "Field patches") + S.COURSE_DONE.sub));
  assert.equal(S.COURSE_DONE.title(10, "Field patches"), "All 10 field patches earned");
  assert.match(S.COURSE_CREDIT.earth, /Blue Marble/); assert.ok(!/Artemis|Moon Base/.test(S.COURSE_CREDIT.earth));
  // the patch screen: "then your check ride" only when the course has one; the map credit by globe; the facts label
  assert.match(ui, /lessons\(\)\.some\(l => l\.ride\) \? TRANSITION\.patchProgress\(c\.n, c\.of\) : COURSE_DONE\.progress\(c\.n, c\.of\)/);
  assert.match(ui, /moonGlobe\(\) \? `\$\{CREDIT\} \$\{PRETEND_BASE\}` : \(COURSE_CREDIT\[/);
  assert.match(ui, /moonCourse\(\) \? "NASA facts" : "Facts"/);
  assert.ok(!/Loading Flight School…|Can&rsquo;t reach Flight School/.test(ui), "loading lines use the course's school name");
});
