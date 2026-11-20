// My Brain (src/brain.js, src/brain_store.js; docs/BRAIN.md): the practice-count aggregate, the cadet's page and the
// grown-ups' blocks. Every aggregate keeps ids and counts only: no words, names or call signs leave it.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = globalThis.window || {};
const S = await import("../src/brain_store.js");
const B = await import("../src/brain.js");
const P = await import("../src/progress.js");
const { PROFILE_KEYS } = await import("../src/prefs.js");
const { PROGRESS_KEYS, isProgressKey } = await import("../src/reset.js");

function mem(obj = {}) { return { getItem: k => (k in obj ? obj[k] : null), setItem: (k, v) => { obj[k] = String(v); }, removeItem: k => { delete obj[k]; }, obj }; }
const L = (id, extra = {}) => ({ id, title: "T " + id, badge: { id: "b-" + id, name: "Patch " + id }, steps: [{}, {}, {}], ...extra });
const LESSONS = [L("moon"), L("phases"), L("power"), L("checkride", { ride: true }), L("gravity", { track: "explorer" }),
  L("craters", { track: "field" }), L("c-room5-tides", { track: "class", title: "Tides" })];

// ---------- brain_store: record ----------
test("record: first try, with help, shown, misses and early pause hints", () => {
  let s = S.blank();
  s = S.record(s, { lesson: "moon", type: "choice", status: "passed", misses: 0, helped: false, step_s: 12 }, "2026-11-18");
  s = S.record(s, { lesson: "moon", type: "tap", status: "hint", hes: true }, "2026-11-18");
  s = S.record(s, { lesson: "moon", type: "tap", status: "passed", misses: 1, step_s: 30 }, "2026-11-18");
  s = S.record(s, { lesson: "moon", type: "choice", status: "passed", misses: 0, helped: true, step_s: 9 }, "2026-11-19");
  s = S.record(s, { lesson: "moon", type: "route", status: "passed", shown: true, misses: 3, step_s: 4000 }, "2026-11-19");
  assert.deepEqual(s.lessons.moon, { steps: 4, first: 1, helped: 2, shown: 1, misses: 1, pause: 1, secs: 12 + 30 + 9 + S.STEP_CAP_S });
  assert.deepEqual(s.days, ["2026-11-18", "2026-11-19"]);
});

test("record: guesses, videos, partial progress and ignored turns never count", () => {
  let s = S.blank();
  for (const ev of [{ lesson: "phases", type: "video", status: "passed" }, { lesson: "phases", type: "predict", status: "passed" },
    { lesson: "phases", type: "describe", status: "progress" }, { lesson: "phases", type: "choice", status: "ignored" },
    { lesson: "phases", type: "choice", status: "help" }, { lesson: "Bad Id!", type: "choice", status: "passed" }, null])
    s = S.record(s, ev, "2026-11-19");
  assert.deepEqual(s, S.blank());
});

test("record: a check-ride order the world moved past counts as shown", () => {
  const s = S.record(S.blank(), { lesson: "checkride", type: "command", status: "missed", ride: true }, "2026-11-19");
  assert.equal(s.lessons.checkride.shown, 1);
  assert.equal(s.lessons.checkride.steps, 1);
});

test("clean: no words, names or call signs survive, whatever is stored", () => {
  const dirty = { v: 1, callsign: "Comet", text: "my name is Alex", lessons: { moon: { steps: 2, first: "1", said: "shackleton", heard: "Alex" },
    "Alex Smith": { steps: 3 }, "<script>": { steps: 1 } }, days: ["2026-11-19", "Tuesday", "Alex", 5] };
  const c = S.clean(dirty), raw = JSON.stringify(c);
  for (const w of ["Comet", "Alex", "shackleton", "script", "Tuesday", "said", "heard", "callsign", "text"]) assert.ok(!raw.includes(w), w);
  assert.deepEqual(Object.keys(c.lessons), ["moon"]);
  assert.deepEqual(c.lessons.moon, { steps: 2, first: 1, helped: 0, shown: 0, misses: 0, pause: 0, secs: 0 });
  assert.deepEqual(c.days, ["2026-11-19"]);
  assert.equal(c.course, "moon", "the default course");
  assert.equal(S.clean({ course: "archaeology" }).course, "archaeology");
  assert.equal(S.clean({ course: "Alex's notes" }).course, "moon", "a course id is a slug, never text");
});

test("store: add / load / wipe on a Storage; at most 60 days", () => {
  const st = mem();
  for (let d = 1; d <= 70; d++) S.add({ lesson: "moon", type: "choice", status: "passed", misses: 0 }, st, `2026-0${1 + Math.floor((d - 1) / 28)}-${String(1 + ((d - 1) % 28)).padStart(2, "0")}`);
  const s = S.load(st);
  assert.equal(s.lessons.moon.steps, 70);
  assert.equal(s.days.length, S.MAX_DAYS);
  assert.equal(s.days[s.days.length - 1], "2026-03-14");
  S.wipe(st);
  assert.deepEqual(S.load(st), S.blank());
});

test("the practice counts are per cadet, kept by Start over, erased with progress and by Reset progress", () => {
  assert.ok(PROFILE_KEYS.includes(S.KEY), "moves with the cadet's profile");
  assert.ok(PROGRESS_KEYS.includes(S.KEY) && isProgressKey(S.KEY), "a progress key (reset.js)");
  const src = readFileSync(new URL("../src/prefs.js", import.meta.url), "utf8");
  assert.match(src, /function resetProgress\(\) \{[^}]*"outpost-brain", null/, "Settings → Reset progress clears it too");
});

// ---------- aggregates ----------
test("streak: days in a row ending today or yesterday", () => {
  assert.equal(B.streak(["2026-11-17", "2026-11-18", "2026-11-19"], "2026-11-19"), 3);
  assert.equal(B.streak(["2026-11-17", "2026-11-18"], "2026-11-19"), 2, "this morning doesn't break it yet");
  assert.equal(B.streak(["2026-11-15", "2026-11-17"], "2026-11-19"), 0);
  assert.equal(B.streak(["2026-10-31", "2026-11-01"], "2026-11-01"), 2, "across a month");
  assert.equal(B.streak([], "2026-11-19"), 0);
});

test("practice, totals and hardest: course order, first-try share, minutes, NGSS hooks", () => {
  const brain = { lessons: { phases: { steps: 4, first: 1, helped: 2, shown: 1, misses: 5, pause: 1, secs: 600 },
    moon: { steps: 3, first: 3, secs: 90 }, craters: { steps: 1, helped: 1 }, ghost: { steps: 9 } }, days: [] };
  const rows = B.practice(brain, LESSONS);
  assert.deepEqual(rows.map(r => r.id), ["moon", "phases", "craters"], "course order; lessons not in the course are dropped");
  assert.equal(rows[0].firstPct, 100);
  assert.equal(rows[1].firstPct, 25);
  assert.equal(rows[1].mins, 10);
  assert.deepEqual(rows[1].ngss, ["1-ESS1-1", "MS-ESS1-1"]);
  const t = B.totals(rows);
  assert.deepEqual([t.steps, t.first, t.misses, t.pause, t.firstPct], [8, 4, 5, 1, 50]);
  assert.deepEqual(B.hardest(rows).map(r => r.id), ["phases"], "needs 3+ steps and some help");
});

test("stars: lit when the patch is earned, practising when started, dim otherwise", () => {
  const st = B.stars(LESSONS, { badges: ["b-moon"], steps: { power: { i: 1, n: 3 } } }, { lessons: { phases: { steps: 1 } } });
  const by = Object.fromEntries(st.map(s => [s.id, s.state]));
  assert.deepEqual(by, { moon: "lit", phases: "practising", power: "practising", checkride: "dim", gravity: "dim", craters: "dim", "c-room5-tides": "dim" });
  assert.equal(st.find(s => s.id === "moon").star, "One face");
  assert.equal(st.find(s => s.id === "c-room5-tides").track, "class");
  const pts = B.layout(st);
  assert.ok(pts.every(p => p.x >= 0 && p.x <= 640 && p.y >= 0 && p.y <= 280), "every star inside the map");
});

test("voiceLines: learned names in kid words, the waiting habit only after a few turns", () => {
  assert.deepEqual(B.voiceLines(null), []);
  const v = B.voiceLines({ aliases: [{ heard: "ticko", name: "Tycho" }], habits: { turns: 12, end_silence_s: 0.7 } });
  assert.deepEqual(v, ["You say “ticko”. The outpost knows you mean Tycho.", B.COPY.waits]);
  assert.deepEqual(B.voiceLines({ aliases: [], habits: { turns: 2, end_silence_s: 0.8 } }), []);
  assert.deepEqual(B.voiceLines({ habits: { turns: 9, end_silence_s: 0.5 } }), [B.COPY.quick]);
});

// ---------- the cadet's page ----------
test("cadetHtml: call sign, rank, stars, try next, voice and how the outpost thinks; escaped", () => {
  const h = B.cadetHtml({ callsign: "<b>Nova</b>", academy: { badges: ["b-moon"], qualified: false }, flown: [], lessons: LESSONS,
    brain: { lessons: { phases: { steps: 1 } }, days: ["2026-11-19"] }, learned: { aliases: [{ heard: "ticko", name: "Tycho" }] }, today: "2026-11-19" });
  assert.ok(!h.includes("<b>Nova</b>") && h.includes("&lt;b&gt;Nova&lt;/b&gt;"));
  for (const s of ["My Brain", "Your star map", "Try next", "How the outpost knows your voice", "How the outpost thinks", "It keeps your words private", "Change call sign"].slice(1))
    assert.ok(h.includes(s), s);
  assert.match(h, /1<small> of 7<\/small>/, "1 of 7 stars lit");
  assert.ok(h.includes("Lesson: T phases."), "try next names the next lesson");
  assert.ok(h.includes(">Cadet<") && !h.includes("<script"));
  assert.ok(!/\b(smart|slow|struggl|weak|anxious|nervous|IQ|diagnos)/i.test(h), "no ability or emotion labels");
});

test("cadet copy: short, plain, no age words", () => {
  const all = [B.COPY.mapLine, B.COPY.voiceEmpty, B.COPY.waits, B.COPY.quick, B.COPY.foot, ...B.COPY.think.flatMap(t => t.slice(1))];
  for (const t of all) {
    assert.ok(t.split(/\s+/).length <= 16, t);
    assert.ok(!/\b(kids?|child|children|years? old|age)\b/i.test(t), t);
  }
});

// ---------- the grown-ups' blocks ----------
test("practiceHtml: totals, pause hints, hardest, table with NGSS hooks; empty state", () => {
  assert.ok(B.practiceHtml(S.blank(), LESSONS).includes(B.GROWN.none));
  const h = B.practiceHtml({ lessons: { phases: { steps: 4, first: 1, helped: 2, shown: 1, misses: 5, pause: 2, secs: 600 } }, days: ["2026-11-19"] }, LESSONS);
  for (const s of ["4 steps answered, 25% on the first try", "5 tries weren't right yet. The app gave 2 hints early", "Needed the most help: T phases", "MS-ESS1-1", "Not an alignment review", "Practised on 1 day"])
    assert.ok(h.includes(s), s);
});

test("computerHtml: talk, room, safety and adapted counts; the log-off state; never words", () => {
  const s = { talk: { turns: 20, voice: 15, typed: 5, answered: 16, passed_by: 4, days: 3, room: { calm: 18, busy: 2, loud: 0 } },
    safety: { guarded: 2, care: 0 }, adapted: { names: 1, wait_s: 0.7, turns: 30, waits_longer: true } };
  const h = B.computerHtml(s);
  for (const t of ["20 turns on 3 days: 15 by voice, 5 typed.", "let 4 pass", "busy 2", "2 turns kept private", "Learned 1 name", "a little longer"])
    assert.ok(h.includes(t), t);
  assert.ok(B.computerHtml(null).includes(B.COMPUTER.off));
  assert.ok(B.computerHtml({ talk: { turns: 0 }, safety: { guarded: 0, care: 1 } }).includes("suggested a break"));
});

test("progress sheet: practice per cadet, this computer's counts on the playing cadet's card only", () => {
  const STORE = mem({
    "outpost-profiles": JSON.stringify({ active: "p1", list: [{ id: "p1", data: null }, { id: "p2", data: { "outpost-callsign": "Nova",
      "outpost-brain": JSON.stringify({ lessons: { moon: { steps: 3, first: 3 } }, days: [] }) } }] }),
    "outpost-callsign": "Comet", "atm-academy": JSON.stringify({ badges: [] }),
    "outpost-brain": JSON.stringify({ lessons: { phases: { steps: 2, first: 1, helped: 1 } }, days: [] }),
  });
  assert.equal(B.brainOf("p1", STORE).lessons.phases.steps, 2, "the playing cadet: the live key");
  assert.equal(B.brainOf("p2", STORE).lessons.moon.steps, 3, "another cadet: their snapshot");
  const cadets = P.readCadets(STORE), brains = { p1: B.brainOf("p1", STORE), p2: B.brainOf("p2", STORE) };
  const h = P.sheetHtml({ cadets, lessons: LESSONS, brains, summary: { talk: { turns: 1, voice: 1, typed: 0, answered: 1, passed_by: 0, days: 1, room: { calm: 1, busy: 0, loud: 0 } }, safety: { guarded: 0, care: 0 } } });
  const cards = h.split('<article class="pg-cadet');
  assert.ok(cards[1].includes("Talking with the app") && cards[1].includes("T phases"));
  assert.ok(!cards[2].includes("Talking with the app") && cards[2].includes("T moon"));
});

test("loadData asks for the playing cadet's summary by profile id only (no call sign in the URL)", async () => {
  const urls = [];
  const fetchFn = async u => { urls.push(u); return { ok: true, json: async () => (u.includes("course") ? { lessons: LESSONS } : {}) }; };
  const STORE = mem({ "outpost-profiles": JSON.stringify({ active: "p2", list: [{ id: "p1", data: null }, { id: "p2", data: null }] }), "outpost-callsign": "Comet" });
  const d = await P.loadData({ fetchFn, storage: STORE });
  assert.ok(urls.includes("/api/brain/summary?profile=p2"));
  assert.ok(urls.every(u => !u.includes("Comet")));
  assert.ok(d.brains.p1 && d.brains.p2);
});

test("wiring: the top bar button, B key, router intent, the map chip and the CSP (no inline script or handler)", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  assert.match(html, /id="brainBtn"/);
  assert.ok(!/\son[a-z]+="/i.test(html.match(/<button[^>]*id="brainBtn"[^>]*>/)[0]));
  const keys = readFileSync(new URL("../src/input/keys.js", import.meta.url), "utf8");
  assert.match(keys, /case "b": return \{ intent: "brain"/);
  const ui = readFileSync(new URL("../src/academy/ui.js", import.meta.url), "utf8");
  assert.match(ui, /O\.brain\.open\(\)/);
  const src = readFileSync(new URL("../src/brain.js", import.meta.url), "utf8");
  assert.ok(!/<script|\son[a-z]+=\\?"/i.test(src), "no inline script or handler attribute in the drawer's HTML");
});
