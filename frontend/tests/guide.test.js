// Guidance (src/academy/guide.js, docs/PLAYTEST.md): no step asks for a place without showing it, the hint ladder
// draws more at each rung, and every step type has a "do this" line within the copy budget.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { marks, doLine, DO, INTRO, firstUse, resetSeen, needsTurn } from "../src/academy/guide.js";

const course = JSON.parse(fs.readFileSync(new URL("../../backend/data/academy/course.json", import.meta.url)));
const places = JSON.parse(fs.readFileSync(new URL("../../backend/data/places.json", import.meta.url)));
const P = Object.fromEntries((Array.isArray(places) ? places : places.places).map(p => [p.id, { ...p, km: p.diameter_km }]));
const find = id => P[id] || null;
const route = course.lessons.flatMap(l => l.steps).find(s => s.accept.type === "route");

test("the route step shows both stops, numbered and labelled, before any tap (the owner's stuck moment)", () => {
  const m = marks(route, { rung: 0, next: 0 }, find);
  assert.deepEqual(m.map(x => [x.id, x.num, x.label]), [["orientale", 1, "Orientale"], ["ohm", 2, "Ohm"]]);
  assert.ok(m[0].pulse && !m[1].pulse, "stop 1 pulses first");
  const after = marks(route, { rung: 0, next: 0, done: true, after: [route.after_place] }, find);
  assert.ok(after.some(x => x.id === "integrity" && x.label === "Integrity"), "after the trace, the named crater is labelled");
});

test("a find step shows nothing at rung 0, a glow at rung 1, a label at rung 2", () => {
  const st = course.lessons[0].steps[0];
  assert.equal(st.accept.type, "intent");
  assert.deepEqual(marks(st, { rung: 0 }, find), []);
  const r1 = marks(st, { rung: 1, focus: ["tranquillitatis"] }, find);
  assert.equal(r1.length, 1); assert.ok(r1[0].ring && r1[0].pulse && !r1[0].label);
  const r2 = marks(st, { rung: 2, focus: ["tranquillitatis"], label: ["tranquillitatis"] }, find);
  assert.equal(r2[0].label, "Sea of Tranquility");
});

test("the south-pole step draws the gold ring its prompt promises", () => {
  const st = course.lessons[0].steps.find(s => /gold ring/.test(s.prompt));
  const m = marks(st, { rung: 0 }, find);
  assert.ok(m.some(x => x.gold && x.ring), "gold ring");
});

test("the terminator hint glows along the line and labels it at rung 2", () => {
  const st = { accept: { type: "terminator", sun_lon: 90 } };
  assert.ok(marks(st, { rung: 1, line_lon: 0 }, find).length >= 5);
  assert.ok(marks(st, { rung: 2, line_lon: 0, label_line: true }, find).some(x => x.label === "Day meets night"));
});

test("every step has a do-this line of 10 words or fewer", () => {
  for (const l of course.lessons) for (const s of l.steps) {
    const d = doLine(s);
    if (l.ride) continue;
    assert.ok(d, `${l.id}: ${s.prompt}`);
    assert.ok(d.split(/\s+/).length <= 10, d);
  }
  for (const v of [...Object.values(DO), ...Object.values(INTRO)]) assert.ok(v.split(/\s+/).length <= 12, v);
});

test("every place a step names in its prompt is shown, ringed, or under test", () => {
  for (const l of course.lessons) for (const s of l.steps) {
    const a = s.accept, tested = new Set([a.place, ...(a.also || [])].filter(Boolean));
    for (const [id, p] of Object.entries(P)) {
      const nm = String(p.name).split(" (")[0];
      if (nm.length < 4 || !new RegExp(`\\b${nm}\\b`).test(s.prompt)) continue;
      const shown = (s.show || []).includes(id) || (s.ring || []).includes(id) || tested.has(id) || s.after_place === id || (s.globe && s.globe.place === id);
      assert.ok(shown, `${l.id}: "${s.prompt}" names ${nm} but doesn't show it`);
    }
  }
});

test("a step type's intro shows once per device", () => {
  resetSeen();
  const mem = new Map(), st = { getItem: k => mem.get(k) || null, setItem: (k, v) => mem.set(k, v) };
  assert.equal(firstUse("route", st), true);
  assert.equal(firstUse("route", st), false);
  resetSeen();
  assert.equal(firstUse("route", st), false, "remembered in storage");
  assert.equal(firstUse("choice", st), false, "no intro for plain choices");
});

test("needsTurn: round the back or on the edge", () => {
  assert.equal(needsTurn({ lat: 0, lon: 0 }, () => ({ facing: true, depth: 0.9 })), false);
  assert.equal(needsTurn({ lat: 0, lon: 0 }, () => ({ facing: true, depth: 0.2 })), true);
  assert.equal(needsTurn({ lat: 0, lon: 0 }, () => ({ facing: false, depth: -0.5 })), true);
});
