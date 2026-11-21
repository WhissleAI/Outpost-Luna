// [brain-signals] (docs/BRAIN.md "Signals → Brain"): mix-ups, help-seeking and persistence in the practice counts, the
// grown-ups' computer block (sensitive counts off by default), and the care banner. Kinds and counts only, never words.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = globalThis.window || {};
const S = await import("../src/brain_store.js");
const B = await import("../src/brain.js");
const P = await import("../src/progress.js");
const { isProgressKey } = await import("../src/reset.js");
const { PROFILE_KEYS } = await import("../src/prefs.js");

function mem(obj = {}) { return { getItem: k => (k in obj ? obj[k] : null), setItem: (k, v) => { obj[k] = String(v); }, removeItem: k => { delete obj[k]; }, obj }; }
const L = (id, extra = {}) => ({ id, title: "T " + id, badge: { id: "b-" + id, name: "Patch " + id }, steps: [{}, {}, {}], ...extra });
const LESSONS = [L("moon"), L("phases"), L("power")];

test("traps: a miss's mixup kind is counted per lesson step; a retry counts the trap but not a miss", () => {
  let s = S.blank();
  s = S.record(s, { lesson: "phases", type: "choice", status: "hint", mixup: "pick", step: 2 }, "2026-11-18");
  s = S.record(s, { lesson: "phases", type: "choice", status: "hint", mixup: "pick", step: 2 }, "2026-11-18");
  s = S.record(s, { lesson: "phases", type: "command", status: "retry", mixup: "order", step: 0 }, "2026-11-18");
  s = S.record(s, { lesson: "phases", type: "choice", status: "hint", mixup: "<script>", step: 1 }, "2026-11-18");
  s = S.record(s, { lesson: "phases", type: "choice", status: "hint", mixup: "pick", step: "two" }, "2026-11-18");
  assert.deepEqual(s.lessons.phases.traps, { "pick@2": 2, "order@0": 1 });
  assert.equal(s.lessons.phases.misses, 4, "the retry is not a miss");
  assert.deepEqual(S.clean(JSON.parse(JSON.stringify(s))).lessons.phases.traps, { "pick@2": 2, "order@0": 1 });
});

test("traps: clean keeps only known kinds and caps them per lesson", () => {
  const raw = { lessons: { moon: { steps: 1, traps: { "pit@1": 2, "alex said hi@1": 3, "pick@x": 1, "sequence@4": "2", ...Object.fromEntries(Array.from({ length: 20 }, (_, k) => [`pick@${k + 10}`, 1])) } } } };
  const t = S.clean(raw).lessons.moon.traps;
  assert.equal(t["pit@1"], 2); assert.equal(t["sequence@4"], 2);
  assert.ok(!JSON.stringify(t).includes("alex"));
  assert.ok(Object.keys(t).length <= S.MAX_TRAPS);
});

test("asks: help-seeking counts per lesson and never touches graded counts or days", () => {
  const s = S.record(S.blank(), { lesson: "moon", status: "asked" }, "2026-11-18");
  assert.equal(s.lessons.moon.asks, 1);
  assert.equal(s.lessons.moon.steps + s.lessons.moon.misses, 0);
  assert.deepEqual(s.days, []);
});

test("mixups: n >= 2 only, most first, with plain labels and step numbers from 1", () => {
  let s = S.blank();
  for (let k = 0; k < 3; k++) s = S.record(s, { lesson: "power", status: "hint", mixup: "pit", step: 1 }, "2026-11-18");
  s = S.record(s, { lesson: "moon", status: "hint", mixup: "pick", step: 0 }, "2026-11-18");
  const m = B.mixups(s, LESSONS);
  assert.deepEqual(m.map(x => [x.lesson, x.kind, x.step, x.n]), [["power", "pit", 1, 3]]);
  const html = B.practiceHtml(s, LESSONS);
  assert.match(html, /Common mix-ups/);
  assert.match(html, /T power, step 2: named the pit before the layers it cuts \(3 times\)/);
});

test("persistence: a rate only from MIN_N steps; the cadet page shows good news only", () => {
  assert.equal(B.persistence({ helped: 1, shown: 1 }).rate, null);
  assert.equal(B.persistence({ helped: 3, shown: 1 }).rate, 75);
  assert.deepEqual(B.cheerLines(S.blank()), []);
  let s = S.record(S.blank(), { lesson: "moon", status: "passed", misses: 1, step_s: 3 }, "2026-11-18");
  s = S.record(s, { lesson: "moon", status: "asked" }, "2026-11-18");
  const lines = B.cheerLines(s);
  assert.equal(lines.length, 2);
  for (const t of lines) assert.doesNotMatch(t, /wrong|bad|fail|struggl|behind|only|rude|aggress|risk/i);
  // shown answers or misses alone never produce a line
  const shown = S.record(S.blank(), { lesson: "moon", status: "passed", shown: true, misses: 3 }, "2026-11-18");
  assert.deepEqual(B.cheerLines(shown), []);
});

const SUM = { talk: { turns: 12, voice: 8, typed: 4, answered: 10, passed_by: 2, days: 3, room: { calm: 12, busy: 0, loud: 0 },
  signals: { hint: 1, pass: 3, repeat: 2, negate: 1, undo: 0, retap: 1, confirm_cancel: 0 }, retried: 4, min_n: 10, shadow: { interruptions: 5 } },
safety: { guarded: 3, guard: { pii: 1, name: 1 }, care: 0 }, adapted: null };

test("computer block: the app's retries framed as the app's miss; sensitive counts off by default; shadow never shown", () => {
  const html = B.computerHtml(SUM);
  assert.match(html, /The app had to try again 4 times \(33% of turns\)/);
  assert.match(html, /the app's miss, not the cadet's/);
  assert.match(html, /data-pg-sensitive/);
  assert.doesNotMatch(html, /data-pg-sensitive checked/);
  assert.doesNotMatch(html, /for language/);
  assert.doesNotMatch(html, /interrupt/i);
  const few = B.computerHtml({ ...SUM, talk: { ...SUM.talk, turns: 5 } });
  assert.doesNotMatch(few, /% of turns/, "no rate under min_n");
  const on = B.computerHtml({ ...SUM, safety: { ...SUM.safety, weekly: { "2026-W46": { language: 2, unkind: 0 } } } }, { sensitive: true });
  assert.match(on, /data-pg-sensitive checked/);
  assert.match(on, /Week 2026-W46: 2 for language, 0 unkind\./);
  for (const w of ["aggressive", "at risk", "rude kid", "bully"]) assert.ok(!on.toLowerCase().includes(w), w);
});

test("care banner: per cadet and day, no words, dismissed rows hidden, resources shown", () => {
  const cadets = [{ id: "p1", callsign: "Comet" }, { id: "p2", callsign: "" }];
  const care = { flags: [{ kind: "care", profile: "p1", day: "2026-11-18", n: 1, dismissed: false },
    { kind: "care", profile: "p2", day: "2026-11-17", n: 2, dismissed: true },
    { kind: "care", profile: "p1", day: "<b>", n: 1, dismissed: false }], line: "Let's take a break. Talk to a grown-up you trust." };
  const html = P.careHtml(care, cadets);
  assert.match(html, /Comet: The guide suggested a break and a trusted grown-up on 2026-11-18\./);
  assert.doesNotMatch(html, /2026-11-17/);
  assert.doesNotMatch(html, /<b>/);
  assert.match(html, /988/);
  assert.match(html, /data-pg-care-dismiss data-profile="p1" data-day="2026-11-18"/);
  assert.equal(P.careHtml({ flags: [] }, cadets), "");
  assert.equal(P.careHtml(null, cadets), "");
  // printed sheets never carry the banner
  assert.doesNotMatch(P.sheetHtml({ cadets: [{ id: "p1", active: true, callsign: "Comet", academy: { badges: [], qualified: false, steps: {}, current: null }, flown: [] }], care, date: "today" }), /trusted grown-up on/);
});

test("the grown-up toggle: off by default, this computer's (not a cadet's), cleared by Reset (not progress)", () => {
  const st = mem();
  assert.equal(S.sensitiveOn(st), false);
  S.setSensitive(true, st);
  assert.equal(S.sensitiveOn(st), true);
  assert.ok(!PROFILE_KEYS.includes(S.GROWNUP_KEY));
  assert.ok(!isProgressKey(S.GROWNUP_KEY) && S.GROWNUP_KEY.startsWith("outpost"));
  assert.equal(S.sensitiveOn(mem({ "outpost-grownup": "{bad" })), false);
});

test("loadData: sensitive=1 only when the grown-up turned it on; the care flags are read; never a write", async () => {
  const calls = [];
  const fetchFn = async (u, o) => { calls.push([u, o && o.method]); return { ok: true, json: async () => (u.includes("academy/course") ? { lessons: LESSONS } : {}) }; };
  await P.loadData({ fetchFn, storage: mem() });
  assert.ok(calls.some(([u]) => u === "/api/safety/flags"));
  assert.ok(calls.every(([u]) => !u.includes("sensitive")));
  assert.ok(calls.every(([, m]) => !m || m === "GET"));
  calls.length = 0;
  await P.loadData({ fetchFn, storage: mem({ "outpost-grownup": JSON.stringify({ sensitive: true }) }) });
  assert.ok(calls.some(([u]) => u.startsWith("/api/brain/summary?") && u.includes("&sensitive=1")));
});

test("wiring: the lesson reply's mixup and the help ask reach the practice counts (academy/ui.js)", () => {
  const ui = readFileSync(new URL("../src/academy/ui.js", import.meta.url), "utf8");
  assert.match(ui, /mixup: r\.mixup, step: i/);
  assert.match(ui, /status: "asked", lesson: L\.id/);
});

test("emotion stays quarantined in the client (main.js EMOTION_INPUT = false)", () => {
  const main = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
  assert.match(main, /const EMOTION_INPUT = false;/);
  assert.match(main, /onEmotion: label => \{ if \(EMOTION_INPUT\) turn\.emotion = label; \}/);
});
