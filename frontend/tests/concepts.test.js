// D5 (docs/BRAIN.md §11): concept-level counts and spaced review per cadet, per course (brain_store.js concepts,
// brain.js reviewList / conceptsHtml / the kid's Quick review). Outcomes and what the app does next, never a trait.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const S = await import("../src/brain_store.js");
const B = await import("../src/brain.js");
const P = await import("../src/progress.js");

const META = {
  radio_words: { label: "Radio words", lesson: "comms", step: 0, mission: true },
  regolith: { label: "Regolith (Moon dust)", lesson: "gravity", step: 4, mission: false },
  storm_shelter: { label: "Shelter from a solar storm", lesson: "radiation", step: 2, mission: true },
};
const pass = (concept, extra = {}) => ({ lesson: "comms", type: "choice", status: "passed", misses: 0, step_s: 5, concept, ...extra });

test("record: first try moves a concept up a box; with help or shown sends it back to box 1", () => {
  let s = S.blank();
  s = S.record(s, pass("radio_words"), "2026-11-01");
  assert.deepEqual(s.concepts.radio_words, { first: 1, helped: 0, shown: 0, box: 1, due: "2026-11-02" });
  s = S.record(s, pass("radio_words"), "2026-11-02");
  assert.equal(s.concepts.radio_words.box, 2); assert.equal(s.concepts.radio_words.due, "2026-11-05");
  s = S.record(s, pass("radio_words"), "2026-11-05");
  s = S.record(s, pass("radio_words"), "2026-11-12");
  assert.equal(s.concepts.radio_words.box, 4); assert.equal(s.concepts.radio_words.due, "2026-11-26");
  s = S.record(s, pass("radio_words", { misses: 1 }), "2026-11-26");
  assert.deepEqual([s.concepts.radio_words.helped, s.concepts.radio_words.box, s.concepts.radio_words.due], [1, 1, "2026-11-27"]);
  s = S.record(s, pass("radio_words", { shown: true }), "2026-11-27");
  assert.equal(s.concepts.radio_words.shown, 1);
  s = S.record(s, { ...pass("regolith"), status: "missed" }, "2026-11-27");   // a missed check-ride order: shown
  assert.equal(s.concepts.regolith.shown, 1);
});

test("record: a try that wasn't right yet, an ungraded step or no concept leaves concepts alone", () => {
  let s = S.blank();
  s = S.record(s, { ...pass("radio_words"), status: "hint" }, "2026-11-01");
  s = S.record(s, { ...pass("regolith"), type: "video" }, "2026-11-01");
  s = S.record(s, pass(undefined), "2026-11-01");
  s = S.record(s, pass("Bad Concept!"), "2026-11-01");
  assert.equal(s.concepts, undefined);
});

test("clean: concept ids, whole counts, a box 0-4 and a real day only", () => {
  const c = S.clean({ concepts: { radio_words: { first: "2", box: 9, due: "soon", note: "my name is alex" }, "Not An Id": { first: 1 } } });
  assert.deepEqual(c.concepts, { radio_words: { first: 2, helped: 0, shown: 0, box: 4, due: null } });
  assert.ok(!JSON.stringify(c).includes("alex"));
});

test("dueConcepts / reviewList: due ones, longest-waiting first, only the course's own", () => {
  const b = { concepts: { radio_words: { first: 1, box: 1, due: "2026-11-10" }, regolith: { first: 1, box: 2, due: "2026-11-05" },
    storm_shelter: { first: 1, box: 3, due: "2026-12-01" }, "archaeology:stratigraphy": { first: 1, box: 1, due: "2026-11-01" } } };
  assert.deepEqual(S.dueConcepts(b, "2026-11-20").map(c => c.id), ["archaeology:stratigraphy", "regolith", "radio_words"]);
  const r = B.reviewList(b, META, "2026-11-20");
  assert.deepEqual(r.map(c => c.id), ["regolith", "radio_words"]);
  assert.deepEqual([r[0].lesson, r[0].step, r[0].label], ["gravity", 4, "Regolith (Moon dust)"]);
});

test("the kid's page: Quick review in kid words, one Review button each, no score", () => {
  const brain = { concepts: { regolith: { first: 1, box: 1, due: "2026-11-05" } } };
  const h = B.cadetHtml({ callsign: "Nova", academy: { badges: [] }, flown: [], lessons: [], brain, learned: null, concepts: META, today: "2026-11-20" });
  assert.ok(h.includes("Quick review") && h.includes("The outpost brings back ideas you haven't seen in a while."));
  assert.match(h, /data-bm-review="regolith"/);
  assert.ok(!/forgot|wrong|fail|score|grade|%/i.test(h.split("Quick review")[1].split("</section>")[0]));
  const none = B.cadetHtml({ callsign: "Nova", academy: { badges: [] }, flown: [], lessons: [], brain: S.blank(), learned: null, concepts: META });
  assert.ok(!none.includes("Quick review"));
});

test("the grown-ups' concept table: outcomes and the next review, never a grade", () => {
  const brain = { concepts: { radio_words: { first: 3, helped: 1, shown: 0, box: 3, due: "2026-11-27" }, regolith: { first: 0, helped: 1, shown: 1, box: 1, due: "2026-11-19" } } };
  const h = B.conceptsHtml(brain, META, "2026-11-20");
  assert.ok(h.includes("Remembered after a week or more: 1 of 2 ideas practised."));
  assert.ok(h.includes("Due for a quick review now: 1."));
  assert.ok(h.includes("2026-11-27 (remembered)") && h.includes(">Now<"));
  assert.ok(!/\b(grade|score|level|mastered|weak|struggl)/i.test(h.replace("not a grade", "")));
  assert.equal(B.conceptsHtml({}, META), "");
  const sheet = P.cadetHtml({ id: "p1", active: true, callsign: "Nova", academy: { badges: [], qualified: false, steps: {} }, flown: [], speech: {} }, [], { brain, concepts: META, patch: () => "" });
  assert.ok(sheet.includes("Ideas, step by step"));
});
