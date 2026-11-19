// Class lessons (docs/CURRICULUM.md): the editor's pure parts, the letter patch, the map row and the unlock rules.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { COPY, KINDS, BUDGET, slug, blankPack, blankLesson, blankStep, rekind, getAt, setAt, moveItem, budgetNote, errorsByAt,
  packFileName, cleanPack, listHtml } from "../src/class_editor.js";
import { classPatchSvg, registerClassLessons, anyPatch, isClassPatch } from "../src/academy/class_patch.js";
import { classTrackHtml } from "../src/academy/pins.js";
import { isClass, isBonus, unlocked, coreLessons } from "../src/explorer.js";
import { CLASS } from "../src/story.js";

const SAMPLE = JSON.parse(readFileSync(new URL("../../docs/class_packs/sample_room12.json", import.meta.url)));
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const AGE = /\b(kids?|child(ren)?|ages?|years? old|7–9|10–12)\b/i;

test("paths: get and set a field by the API's error path", () => {
  const p = JSON.parse(JSON.stringify(SAMPLE));
  assert.equal(getAt(p, "lessons[0].steps[1].place"), "copernicus");
  setAt(p, "lessons[0].steps[2].options[1]", "Tycho crater");
  assert.equal(p.lessons[0].steps[2].options[1], "Tycho crater");
  assert.equal(getAt(p, "lessons[3].title"), undefined);
});

test("new lessons and steps start valid-shaped; changing a kind keeps the question and CAPCOM's lines", () => {
  const p = blankPack();
  assert.equal(p.format, "outpost-luna-class-pack");
  const L = blankLesson(p); p.lessons.push(L);
  assert.equal(L.id, "lesson-1"); assert.equal(blankLesson(p).id, "lesson-2");
  assert.deepEqual(blankStep("say").words, []);
  assert.equal(blankStep("predict").reveal, "");
  const s = { kind: "choice", prompt: "Which one?", options: ["A thing", "B thing", "C other"], answer: 2, hint: "Look." };
  const r = rekind(s, "predict");
  assert.equal(r.kind, "predict"); assert.equal(r.prompt, "Which one?"); assert.equal(r.hint, "Look."); assert.equal(r.answer, 2);
  assert.equal(rekind(s, "place").options, undefined);
  assert.equal(KINDS.length, 4);
});

test("reorder, budgets and errors by field", () => {
  assert.deepEqual(moveItem([1, 2, 3], 0, 1), [2, 1, 3]);
  assert.deepEqual(moveItem([1, 2, 3], 0, -1), [1, 2, 3]);
  assert.deepEqual(budgetNote("one two three", BUDGET.prompt), { text: "3 / 20 words", over: false });
  assert.equal(budgetNote("a b c d e f g", BUDGET.fail).over, true);
  assert.match(budgetNote("x".repeat(80), BUDGET.prompt).text, /80 \/ 90 characters/);
  assert.equal(budgetNote("x".repeat(25), BUDGET.title).over, true);
  assert.deepEqual(errorsByAt([{ at: "a", msg: "1" }, { at: "a", msg: "2" }, { at: "b", msg: "3" }]), { a: ["1", "2"], b: ["3"] });
  assert.equal(slug("Room 12: Moon!"), "room-12-moon");
  assert.equal(packFileName({ id: "room-12" }), "outpost-luna-lessons-room-12.json");
});

test("cleanPack splits typed answer words and drops empty lines and facts", () => {
  const p = JSON.parse(JSON.stringify(SAMPLE));
  p.lessons[0].steps[3].words = "ejecta, splash , ";
  p.lessons[0].steps[3].hint = "  ";
  p.lessons[0].facts.push({ text: "", source: { title: "", url: "" } });
  p.saved_at = 1;
  const c = cleanPack(p);
  assert.deepEqual(c.lessons[0].steps[3].words, ["ejecta", "splash"]);
  assert.equal("hint" in c.lessons[0].steps[3], false);
  assert.equal(c.lessons[0].facts.length, 2);
  assert.equal("saved_at" in c, false);
});

test("the list: packs, lessons with Edit / Move, import, the loader's problems; plain words, no age words", () => {
  const html = listHtml({ packs: [{ id: "room-12", pack: SAMPLE }], problems: [{ file: "x.json", msg: "x.json: skipped. Not a JSON file." }], status: "" });
  assert.match(html, /Room 12 Moon unit/); assert.match(html, /Craters up close/);
  assert.match(html, /data-ce="edit"/); assert.match(html, /data-ce="export"/); assert.match(html, /data-ce="import"/);
  assert.match(html, /Couldn't load/); assert.match(html, /x\.json: skipped/);
  const empty = listHtml({ packs: [], problems: [] });
  assert.match(empty, /No class lessons yet/); assert.match(empty, /data-ce="new"/);
  for (const t of [html, empty, JSON.stringify(COPY), JSON.stringify(CLASS)]) assert.doesNotMatch(t.replace(/<[^>]+>/g, " "), AGE);
});

test("the letter patch: earned in colour, locked as a dashed outline; registered lessons draw it", () => {
  const on = classPatchSvg({ name: "Crater Spotter", glyph: "C" }, { size: 44, title: true });
  assert.match(on, /patch-class is-earned/); assert.match(on, />C<\/text>/); assert.match(on, /aria-label="Crater Spotter patch"/);
  const off = classPatchSvg({ name: "Crater Spotter", glyph: "C" }, { earned: false });
  assert.match(off, /is-locked/); assert.match(off, /stroke-dasharray="7 6"/);
  assert.match(classPatchSvg({ glyph: "<" }), /&lt;/);
  registerClassLessons([{ id: "c-room-12-craters", track: "class", title: "Craters up close", pack: { id: "room-12" }, badge: { id: "c-room-12-craters", name: "Crater Spotter", glyph: "C" } },
    { id: "moon", track: "core", badge: { id: "scout" } }]);
  assert.ok(isClassPatch("c-room-12-craters")); assert.ok(!isClassPatch("moon"));
  assert.match(anyPatch("c-room-12-craters", { size: 22 }), /patch-class/);
  assert.match(anyPatch("moon", { size: 22 }), /patch-moon/);   // NASA art untouched
});

test("Class lessons: always open, bonus (never the core count or the ride's gate), one map row per pack", () => {
  const cls = { id: "c-room-12-craters", title: "Craters up close", track: "class", pack: { id: "room-12", title: "Room 12 Moon unit" }, badge: { id: "c-room-12-craters", name: "Crater Spotter", glyph: "C" } };
  const cls2 = { ...cls, id: "c-room-12-tides", title: "Tides", badge: { ...cls.badge, id: "c-room-12-tides" } };
  assert.ok(isClass(cls) && isBonus(cls));
  assert.ok(unlocked(cls, 0, false));
  assert.deepEqual(coreLessons([{ id: "moon" }, cls]).map(l => l.id), ["moon"]);
  const row = classTrackHtml({ lessons: [cls, cls2], has: id => id === "c-room-12-craters", copy: CLASS, esc, patch: anyPatch });
  assert.match(row, /data-class-pack="room-12"/); assert.match(row, /data-l="c-room-12-tides"/);   // the next one not done
  assert.match(row, /1 of 2 done/); assert.match(row, /Class lessons<\/b> · Room 12 Moon unit/);
  assert.equal(classTrackHtml({ lessons: [], has: () => false, copy: CLASS, esc, patch: anyPatch }), "");
});

test("wiring: Flight School shows the rows, Class facts, no route leg, no patch on a preview; NASA count leaves Class out", () => {
  const ui = readFileSync(new URL("../src/academy/ui.js", import.meta.url), "utf8");
  assert.match(ui, /classTrackHtml\(\{ lessons: ls\.filter\(isClass\)/);
  assert.match(ui, /isClass\(L\) \? CLASS\.facts : UI\.facts/);
  assert.match(ui, /noLeg: isClass\(l\)/);
  assert.match(ui, /if \(L && L\.preview\) return;/);
  assert.match(ui, /patchTotal = lessons\(\)\.filter\(l => !isClass\(l\)\)\.length/);
  assert.match(ui, /lessons\(\)\.filter\(l => !l\.preview\)/);
  const main = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
  assert.match(main, /outpost:class-open/);
});
