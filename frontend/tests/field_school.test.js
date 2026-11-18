// Field School (0.5, docs/LEARNING_DESIGN.md §12): the track opens after the check ride and never blocks it; the three
// step renderers (describe, sequence, rounds) send what the server grades; the rock step falls back to its text clue
// without the nasa_views pack; the copy and the patches cover the four lessons.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = globalThis.window || {};
const F = await import("../src/academy/field_steps.js");
const { isField, isBonus, unlocked, coreLessons, fieldLessons, newlyUnlocked } = await import("../src/explorer.js");
const S = await import("../src/story.js");
const { DO, INTRO } = await import("../src/academy/guide.js");
const { PATCHES } = await import("../src/assets/icons.js");
const R = window.__outpost.stepRenderers;
const COURSE = JSON.parse(readFileSync(new URL("../../backend/data/academy/course.json", import.meta.url), "utf8"));
const FIELD = ["observe", "craters", "rocks", "fieldkit"];
const words = t => String(t).trim().split(/\s+/).length;

/** A tiny element stand-in: querySelectorAll returns buttons with dataset and onclick. */
function fakeEl(html) {
  const btns = [...html.matchAll(/<button[^>]*>/g)].map(([tag]) => {
    const at = k => (tag.match(new RegExp(`${k}="([^"]*)"`)) || [])[1];
    return { cls: at("class") || "", dataset: { ...(at("data-say") != null ? { say: at("data-say") } : {}), ...(at("data-c") != null ? { c: at("data-c") } : {}) }, onclick: null };
  });
  return { btns, querySelector: () => null, querySelectorAll: sel => btns.filter(b => sel.split(",").some(s => b.cls.split(" ").includes(s.trim().split(".").pop()))) };
}
const lesson = id => COURSE.lessons.find(l => l.id === id);
const pubAcc = (lid, type) => {   // the public shape the client gets (content.public), for the renderers
  const a = lesson(lid).steps.find(s => s.accept.type === type).accept;
  if (type === "describe") return { type, need: 3, cats: [["size", "size", ["Big", "Small"]], ["shape", "shape", ["Round", "Odd shape"]], ["tone", "bright or dark", ["Bright", "Dark"]], ["texture", "texture", ["Smooth", "Bumpy"]], ["shadow", "shadows", ["Long shadows", "No shadows"]]].map(([id, label, chips]) => ({ id, label, chips })) };
  if (type === "sequence") return { type, items: a.items.map(o => ({ id: o.id, label: o.label })).sort((x, y) => x.label.localeCompare(y.label)) };
  return { type, options: a.options.map(o => ({ id: o.id, label: o.label })), rounds: a.rounds.map(({ id, prompt, clue, rock }) => ({ id, prompt, clue, rock })) };
};

test("Field School: four lessons, after the explorer lessons, before the ride; open only once qualified", () => {
  const fs = COURSE.lessons.filter(isField);
  assert.deepEqual(fs.map(l => l.id), FIELD);
  assert.deepEqual(fieldLessons(COURSE.lessons).map(l => l.id), FIELD);
  assert.equal(COURSE.lessons.at(-1).id, "checkride");
  for (const l of fs) {
    assert.ok(isBonus(l) && !unlocked(l, 0, false) && !unlocked(l, 5, false) && unlocked(l, 0, true), l.id);
  }
  assert.deepEqual(coreLessons(COURSE.lessons).map(l => l.id), ["moon", "phases", "power", "comms", "radiation", "life"]);
  assert.deepEqual(newlyUnlocked(COURSE.lessons, 1).map(l => l.id), ["gravity"]);   // missions never open Field School
  // the cadet's next lesson skips locked ones: before qualifying, the ride follows the core lessons
  const next = (badges, q) => COURSE.lessons.find(l => !badges.includes(l.badge.id) && unlocked(l, 0, q));
  const core = coreLessons(COURSE.lessons).map(l => l.badge.id);
  assert.equal(next(core, false).id, "checkride");
  assert.equal(next([...core, "commander"], true).id, "history");
  assert.equal(next([...core, "commander", "history"], true).id, "observe");
});

test("describe: the cue card, its chips send their word, a said kind lights up", () => {
  const sent = [], acc = pubAcc("observe", "describe");
  const r = R.describe({ step: {}, acc, answer: x => sent.push(x), state: { got: ["size", "shadow"] } });
  assert.match(r.html, /2 of 3/);
  assert.equal((r.html.match(/f-cue-row is-done/g) || []).length, 2);
  const el = fakeEl(r.html); r.bind(el);
  const dark = el.btns.find(b => b.dataset.say === "dark"); dark.onclick();
  assert.deepEqual(sent, [{ text: "dark" }]);
  assert.deepEqual(F.cueRows(acc, ["tone"]).filter(x => x.done).map(x => x.id), ["tone"]);
});

test("sequence: jumbled chips, one at a time; the order so far fills in", () => {
  const sent = [], acc = pubAcc("fieldkit", "sequence");
  const r = R.sequence({ step: {}, acc, answer: x => sent.push(x), state: { got: ["photo"] } });
  assert.match(r.html, /<li class="is-done">.*Photo/);
  assert.match(r.html, /data-c="photo" disabled/);
  const el = fakeEl(r.html); r.bind(el);
  el.btns.find(b => b.dataset.c === "describe").onclick();
  assert.deepEqual(sent, [{ choice: "describe" }]);
});

test("rounds: the round's prompt and clue; the rock in 3D only with the pack, else the clue alone", () => {
  const sent = [], acc = pubAcc("rocks", "rounds");
  const r = R.rounds({ step: {}, acc, answer: x => sent.push(x), state: { got: ["r15016"] } });
  assert.match(r.html, /Rock 2: pale/);
  assert.match(r.html, /2 of 3/);
  assert.match(r.html, /f-clue/); assert.doesNotMatch(r.html, /<canvas/);       // no pack: text only
  const el = fakeEl(r.html); r.bind(el);
  el.btns.find(b => b.dataset.c === "anorthosite").onclick();
  assert.deepEqual(sent, [{ choice: "anorthosite" }]);
  const views = { rocks: [{ id: "60025", url: "/api/views/file/rocks/60025.glb", credit: "NASA/Astromaterials 3D (CC0)" }] };
  assert.equal(F.roundRock(acc.rounds[1], views).id, "60025");
  assert.equal(F.roundRock(acc.rounds[1], null), null);
  assert.equal(F.currentRound(acc, ["a", "b", "c", "d"]).id, "r79115");     // done: the last round stays shown
});

test("every Field step type has a renderer, a do-line and an intro that fit the budgets", () => {
  for (const t of F.FIELD_STEP_TYPES) {
    assert.equal(typeof R[t], "function", t);
    assert.ok(DO[t] && words(DO[t]) <= 10 && INTRO[t] && words(INTRO[t]) <= 12, t);
  }
});

test("copy and patches: Field School is signposted, every lesson has a blurb, a beat and a patch", () => {
  for (const id of FIELD) {
    assert.ok(S.LESSON_BLURB[id] && words(S.LESSON_BLURB[id]) <= 12, id);
    assert.ok(S.LESSON_STORY[id], id);
    assert.equal(PATCHES[id].name, lesson(id).badge.name);
  }
  assert.deepEqual(S.TRACKS.find(t => t.id === "field").lessons, FIELD);
  assert.equal(S.FIELD.eyebrow(2, 4), "Field School 2 of 4");
  assert.equal(S.FIELD.patchProgress(4, 4), "Field School done: 4 of 4 patches.");
  assert.ok(words(S.FIELD.openTitle) <= 6);
});
