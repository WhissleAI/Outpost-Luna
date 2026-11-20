// Speech learning steps (docs/SPEECH_LEARNING.md): the renderers send what the server grades (taps, typed words, the
// whole summary), the summary collects words until "that's it", spaced repetition orders the words, and Progress shows
// counts only, never what a cadet said.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = globalThis.window || {};
const SP = await import("../src/academy/speech_steps.js");
const ST = await import("../src/academy/speech_store.js");
const P = await import("../src/progress.js");
const CP = await import("../src/academy/class_patch.js");
const R = window.__outpost.stepRenderers;
const COURSE = JSON.parse(readFileSync(new URL("../../backend/data/academy/course.json", import.meta.url), "utf8"));
const DAY = 86400000;

/** A tiny element stand-in: buttons (class, data-c) with onclick, and one form. */
function fakeEl(html) {
  const btns = [...html.matchAll(/<button[^>]*>/g)].map(([tag]) => {
    const at = k => (tag.match(new RegExp(`${k}="([^"]*)"`)) || [])[1];
    return { cls: at("class") || "", dataset: { ...(at("data-c") != null ? { c: at("data-c") } : {}) }, attrs: tag, onclick: null };
  });
  const forms = [...html.matchAll(/<form class="sp-type"/g)].map(() => ({ input: { value: "" }, onsubmit: null, querySelector(s) { return s === "input" ? this.input : {}; } }));
  return { btns, forms, querySelector: s => btns.find(b => b.attrs.includes(s.replace(/[[\]]/g, ""))) || null,
    querySelectorAll: s => (s === ".sp-type" ? forms : btns.filter(b => b.cls.split(" ").includes(s.replace(".", "")))) };
}
const pub = (lid, type) => {   // the client's view of a step (the server's public() shape, built here from the data)
  const st = COURSE.lessons.find(l => l.id === lid).steps.find(s => s.accept.type === type);
  return st;
};

test("read: the passage, a choice question with lettered buttons, taps send the option id", () => {
  const acc = { type: "read", passage: { title: "Ice in the dark", text: "One. Two.", sentences: ["One.", "Two."] },
    questions: [{ id: "q1", kind: "choice", prompt: "Why?", options: [{ id: "a", label: "Dark" }, { id: "b", label: "Rain" }] },
      { id: "q2", kind: "find", prompt: "Find it." }] };
  const sent = [];
  const r = R.read({ acc, answer: i => sent.push(i), state: {}, say: () => {} });
  assert.match(r.html, /Ice in the dark/); assert.match(r.html, /1 of 2/); assert.match(r.html, /data-listen/); assert.match(r.html, /data-aloud/);
  const el = fakeEl(r.html); r.bind(el);
  el.btns.find(b => b.dataset.c === "a").onclick();
  assert.deepEqual(sent, [{ choice: "a" }]);
  // the find question: every sentence is a numbered button (s1..sN)
  const f = R.read({ acc, answer: () => {}, state: { got: ["q1"] } });
  assert.match(f.html, /data-c="s1"/); assert.match(f.html, /data-c="s2"/); assert.match(f.html, /2 of 2/);
});

test("read: a short-answer question has a type box that sends the words", () => {
  const acc = { type: "read", passage: { text: "A. B.", sentences: ["A.", "B."] }, questions: [{ id: "q", kind: "say", prompt: "What?" }] };
  const sent = [];
  const r = R.read({ acc, answer: i => sent.push(i), state: {} });
  const el = fakeEl(r.html); r.bind(el);
  el.forms[0].input.value = "cabeus crater"; el.forms[0].onsubmit({ preventDefault() {} });
  assert.deepEqual(sent, [{ text: "cabeus crater" }]);
});

test("vocab: the meaning, word buttons, the plan comes from spaced repetition and stays for the step", () => {
  const acc = { type: "vocab", ask: 2, items: [
    { id: "a", kind: "word", define: "A round hole.", options: [{ id: "o1", label: "crater" }, { id: "o2", label: "creator" }] },
    { id: "b", kind: "word", define: "Melted rock.", options: [{ id: "o1", label: "lava" }, { id: "o2", label: "larva" }] }] };
  const state = {}, sent = [];
  const r = R.vocab({ acc, answer: i => sent.push(i), state, lesson: { id: "wordlab" } });
  assert.deepEqual(state.plan.length, 2);
  assert.match(r.html, /data-hear/); assert.match(r.html, /creator|larva/);
  const el = fakeEl(r.html); r.bind(el); el.btns.find(b => b.dataset.c === "o2").onclick();
  assert.deepEqual(sent, [{ choice: "o2" }]);
  const again = R.vocab({ acc, answer: () => {}, state, lesson: { id: "wordlab" } });
  assert.ok(again.html.includes(acc.items.find(i => i.id === state.plan[0]).define));
});

test("summary: words collect over turns, 'that's it' sends the whole summary, typing sends too", () => {
  const acc = { type: "summary", source: { kind: "video", media: "hammer_feather" }, need: 2, points: [{ id: "p" }, { id: "q" }] };
  const sent = [], state = {};
  const r = R.summary({ acc, answer: i => sent.push(i), state });
  assert.match(r.html, /data-watch/); assert.match(r.html, /0 of 2 key points/); assert.match(r.html, /data-tell-done/);
  assert.equal(state.onText("he dropped a hammer"), true);
  assert.equal(state.onText("and a feather and that's it"), true);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].long_text, "he dropped a hammer and a feather and");
  assert.equal(sent[0].rich, undefined);                 // the rewrite is off unless a grown-up turns it on
  const el = fakeEl(r.html); r.bind(el);
  el.forms[0].input.value = "they landed together"; el.forms[0].onsubmit({ preventDefault() {} });
  assert.equal(sent[1].long_text, "they landed together");
  clearTimeout(state.rec.timer);
});

test("with a page (document present) the live counters look the card up without recursing", () => {
  const seen = [];
  globalThis.document = { querySelector: sel => { seen.push(sel); return null; } };
  try {
    const state = {};
    R.summary({ acc: { type: "summary", source: { kind: "video", media: "x" }, need: 1, points: [{ id: "p" }] }, answer: () => {}, state });
    assert.equal(state.onText("a few words here"), true);
    assert.ok(seen.includes("#aInput .sp-count"));
    clearTimeout(state.rec.timer);
  } finally { delete globalThis.document; }
});

test("addSegment, wordCount, readingSeconds", () => {
  assert.deepEqual(SP.addSegment([], "I'm done"), { texts: [], done: true });
  assert.deepEqual(SP.addSegment(["a"], "b c"), { texts: ["a", "b c"], done: false });
  assert.equal(SP.wordCount("the Moon's soil, 2 times"), 5);
  assert.equal(SP.readingSeconds(12.5, 30), 12.5);
  assert.equal(SP.readingSeconds(0, 30), 30);
});

test("spaced repetition: due words first, then new, then later; right moves up a box, a miss back to box 1", () => {
  const now = 1_000 * DAY, s = ST.parse(null);
  ST.recordWord(s, "moon", "crater", true, now - 2 * DAY);      // box 1, due a day after: overdue now
  ST.recordWord(s, "moon", "lava", true, now);
  ST.recordWord(s, "moon", "lava", true, now);                   // box 2, due in 3 days
  const items = [{ id: "l", term: "lava" }, { id: "n", term: "basin" }, { id: "c", term: "crater" }];
  assert.deepEqual(ST.planFor(items, s, "moon", now), ["c", "n", "l"]);
  assert.equal(s.c.moon.words.lava.box, 2);
  ST.recordWord(s, "moon", "lava", false, now);
  assert.equal(s.c.moon.words.lava.box, 1);
  assert.deepEqual(ST.planFor(items, s, "archaeology", now), ["l", "n", "c"]);   // per course: nothing seen there yet
});

test("store: replies become counts; never the words; junk is dropped; courses from lesson ids", () => {
  const s = ST.parse("{not json");
  ST.applyReply(s, { lesson_id: "reading", step_type: "read", status: "progress", reply: { got: ["q1"] }, input: {} });
  ST.applyReply(s, { lesson_id: "reading", step_type: "read", status: "passed", reply: { got: ["q1", "q2"] }, input: { got: ["q1"] } });
  ST.applyReply(s, { lesson_id: "wordlab", step_type: "vocab", status: "progress", reply: { got: ["crater"], term: "crater" }, input: {} });
  ST.applyReply(s, { lesson_id: "archaeology:dating", step_type: "summary", status: "passed", reply: { got: ["a", "b", "c"], say: "You said..." }, input: { long_text: "secret words" } });
  ST.applyReply(s, { lesson_id: "reading", step_type: "choice", status: "passed", reply: {} });
  assert.equal(s.c.moon.read, 1); assert.equal(s.c.moon.questions, 2);
  assert.equal(s.c.moon.words.crater.box, 1);
  assert.deepEqual([s.c.archaeology.summaries, s.c.archaeology.points], [1, 3]);
  assert.ok(!JSON.stringify(s).includes("secret") && !JSON.stringify(s).includes("You said"));
  assert.equal(ST.courseOf("archaeology:dating"), "archaeology"); assert.equal(ST.courseOf("reading"), "moon");
  const back = ST.parse(JSON.stringify({ c: { moon: { read: "3", words: { crater: { box: 9, due: 1, n: 2 } } }, "BAD KEY!": {} } }));
  assert.equal(back.c.moon.read, 3); assert.equal(back.c.moon.words.crater.box, 4); assert.equal(back.c["BAD KEY!"], undefined);
});

test("Progress: reading / words / summaries as counts, per course, and the key is per cadet and kept by Start over", async () => {
  const s = ST.parse(null);
  ST.addCount(s, "moon", "read"); ST.addCount(s, "moon", "questions", 3); ST.addCount(s, "moon", "aloud"); ST.addCount(s, "moon", "aloud_words", 84);
  ST.recordWord(s, "moon", "crater", true); ST.addCount(s, "moon", "summaries"); ST.addCount(s, "moon", "points", 2);
  const html = P.speechHtml(ST.summary(s));
  assert.match(html, /Reading and speaking/); assert.match(html, /Passages read 1, questions answered 3/);
  assert.match(html, /Read aloud 1 time, 84 words read/); assert.match(html, /Words practised 1, learned 0, to review 0/);
  assert.match(html, /Summaries told 1, key points 2/);
  assert.equal(P.speechHtml({}), "");
  const mem = { "outpost-brain": JSON.stringify({ v: 1, course: "moon", lessons: {}, days: [], speech: s }) }, storage = { getItem: k => mem[k] ?? null };
  const [cadet] = P.readCadets(storage);
  assert.equal(cadet.speech.moon.read, 1);
  // it lives in the cadet's Brain store: per cadet, kept by Start over, and Brain's own writes keep it
  const prefs = readFileSync(new URL("../src/prefs.js", import.meta.url), "utf8");
  assert.match(prefs, /PROFILE_KEYS = \[[^\]]*"outpost-brain"/);
  const { PROGRESS_KEYS } = await import("../src/reset.js");
  assert.ok(PROGRESS_KEYS.includes("outpost-brain"));
  const B = await import("../src/brain_store.js");
  const kept = B.record(JSON.parse(mem["outpost-brain"]), { lesson: "reading", type: "read", status: "passed" }, "2026-11-19");
  assert.equal(kept.speech.c.moon.read, 1); assert.equal(kept.lessons.reading.steps, 1);
  assert.equal(B.clean({ speech: { c: { moon: { words: { "<script>": { box: 1 } } } } } }).speech, undefined);
  const w = {}; const st2 = { getItem: k => w[k] ?? null, setItem: (k, v) => { w[k] = v; } };
  w["outpost-brain"] = JSON.stringify(B.record(B.blank(), { lesson: "moon", type: "intent", status: "passed" }, "2026-11-19"));
  ST.save(s, st2);
  assert.equal(JSON.parse(w["outpost-brain"]).lessons.moon.steps, 1); assert.equal(ST.load(st2).c.moon.read, 1);
});

test("the three Moon sample lessons have drawn patches; a lesson without art gets a letter patch", () => {
  const ls = COURSE.lessons.filter(l => ["reading", "wordlab", "retell"].includes(l.id));
  assert.equal(ls.length, 3);
  for (const l of ls) assert.match(CP.anyPatch(l.id, { size: 44 }), new RegExp(`patch-${l.id}`));
  CP.registerClassLessons([{ id: "archaeology:dating", track: "core", title: "Dating", badge: { id: "ringer", glyph: "D" } }]);
  assert.match(CP.anyPatch("archaeology:dating"), />D<\/text>/);
});

test("each speech step has a do-line and a first-use intro", async () => {
  const { DO, INTRO } = await import("../src/academy/guide.js");
  for (const t of SP.SPEECH_STEP_TYPES) {
    assert.ok(DO[t] && DO[t].split(/\s+/).length <= 10, t);
    assert.ok(INTRO[t] && INTRO[t].startsWith("New:") && INTRO[t].split(/\s+/).length <= 12, t);
  }
});

test("copy budgets: buttons are 1-3 words, card lines 12 words or fewer, no grade words", () => {
  for (const k of ["listen", "aloud", "done", "again", "send", "hear", "watch"]) assert.ok(SP.COPY[k].split(" ").length <= 3, k);
  for (const k of ["aloudOn", "findHow", "sayHow", "pickHow", "tellHow"]) assert.ok(SP.COPY[k].split(" ").length <= 12, k);
  assert.ok(!/score|grade|wrong|level/i.test(JSON.stringify(Object.values(SP.COPY).map(v => typeof v === "function" ? v("x", 1) : v))));
  assert.ok(pub("retell", "summary").accept.points.length >= 2);
});
