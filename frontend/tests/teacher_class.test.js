// D7 (docs/BRAIN.md §12): the teacher PIN after the hold (src/teacher_pin.js, a11y.js gate) and the one-computer
// class summary (src/class_summary.js): alphabetical, counts only, never a ranking or words.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = globalThis.window || {};
const T = await import("../src/teacher_pin.js");
const CS = await import("../src/class_summary.js");
const A = await import("../src/a11y.js");

function mem(obj = {}) { return { getItem: k => (k in obj ? obj[k] : null), setItem: (k, v) => { obj[k] = String(v); }, removeItem: k => { delete obj[k]; }, obj }; }

test("PIN: 4-8 digits only; stored as a salted hash, never the digits", async () => {
  const st = mem();
  for (const bad of ["123", "123456789", "12a4", "", null]) assert.equal(await T.setPin(bad, st), false, String(bad));
  assert.equal(T.pinSet(st), false);
  assert.equal(await T.setPin("4821", st), true);
  assert.equal(T.pinSet(st), true);
  const raw = st.getItem(T.KEY);
  assert.ok(!raw.includes("4821"));
  const r = JSON.parse(raw);
  assert.match(r.salt, /^[0-9a-f]{32}$/); assert.match(r.hash, /^[0-9a-f]{64}$/);
  await T.setPin("4821", st);
  assert.notEqual(JSON.parse(st.getItem(T.KEY)).salt, r.salt, "a new salt each time");
});

test("PIN: right opens, wrong doesn't, five wrong wait 30 s; no PIN = the hold alone", async () => {
  T._resetTries();
  const st = mem();
  assert.deepEqual(await T.checkPin("", st), { ok: true });
  await T.setPin("4821", st);
  assert.equal((await T.checkPin("4821", st)).ok, true);
  const t0 = 1_000_000;
  for (let k = 0; k < 4; k++) assert.deepEqual(await T.checkPin("0000", st, t0), { ok: false });
  assert.deepEqual(await T.checkPin("0000", st, t0), { ok: false, wait: 30 });
  assert.deepEqual(await T.checkPin("4821", st, t0 + 1000), { ok: false, wait: 29 }, "even the right PIN waits");
  assert.equal((await T.checkPin("4821", st, t0 + 31000)).ok, true);
  T.clearPin(st);
  assert.equal(T.pinSet(st), false);
  T._resetTries();
});

test("the gate: after the hold, the PIN step; the part sets, changes or removes it", () => {
  const g = A.grownupsHtml({ open: false, pin: true, pinMsg: T.COPY.wrong });
  assert.match(g, /data-gu-pin-form/); assert.match(g, /type="password" inputmode="numeric"/);
  assert.ok(g.includes("That PIN isn't right.")); assert.ok(!g.includes("data-gu-open"), "no second hold");
  assert.match(A.grownupsHtml({ open: false }), /data-gu-open/);
  assert.ok(A.GROWNUPS.inside.includes("Teacher PIN") && A.GROWNUPS.inside.includes("Class summary"));
  assert.ok(T.partHtml(false).includes("Set PIN") && !T.partHtml(false).includes("data-tp-remove"));
  assert.ok(T.partHtml(true).includes("Change PIN") && T.partHtml(true).includes("data-tp-remove"));
  const src = readFileSync(new URL("../src/a11y.js", import.meta.url), "utf8");
  assert.match(src, /if \(pinSet\(\)\) \{ guPin = true;/, "the hold asks for the PIN when one is set");
});

// ---------- the class summary ----------
const L = (id, extra = {}) => ({ id, title: "T " + id, badge: { id: "b-" + id, name: "P " + id }, steps: [{}, {}], ...extra });
const LESSONS = [L("moon"), L("phases"), L("power")];
const cadet = (id, callsign, badges = []) => ({ id, callsign, active: id === "p1", academy: { badges, qualified: false, steps: {}, current: null }, flown: [], speech: {} });
const counts = { safety: { filtered: 4, privacy: 1, care: 1, by_kind: { profanity: { typed: 1, ptt: 1, directed: 0, room: 2 }, mask: { typed: 0, ptt: 0, directed: 0, room: 0 } } } };

test("class summary: alphabetical by call sign (a new cadet last), never by a count", () => {
  const data = { cadets: [cadet("p1", "Zed", ["b-moon", "b-phases"]), cadet("p2", "amy"), cadet("p3", ""), cadet("p4", "Nova", ["b-moon"])], lessons: LESSONS,
    brains: { p1: { lessons: { moon: { steps: 4, first: 4, helped: 0, shown: 0, misses: 0, pause: 0, secs: 60 } }, days: ["2026-11-19"] } },
    counts: { p2: counts }, meta: {} };
  assert.deepEqual(CS.rows(data).map(r => r.name), ["amy", "Nova", "Zed", "New cadet"]);
  const z = CS.rows(data).find(r => r.name === "Zed");
  assert.deepEqual([z.lessons, z.steps, z.first, z.days], ["2 of 3", 4, "100%", 1]);
  const a = CS.rows(data).find(r => r.name === "amy");
  assert.deepEqual([a.filtered, a.privacy, a.notes], ["2 / 2", 1, 1], "own (typed + push-to-talk) / heard near the app");
});

test("class summary page: counts only, says it is not a ranking nor for grading; printable", () => {
  const h = CS.sheetHtml({ cadets: [cadet("p1", "Nova<x>")], lessons: LESSONS, brains: {}, counts: { p1: counts }, meta: {} }, "20 November 2026");
  assert.ok(h.includes("Nova&lt;x&gt;") && h.includes("Outpost Luna class summary · 20 November 2026"));
  assert.ok(h.includes("Not a ranking, and not for grading."), "on paper");
  assert.ok(CS.default.html().includes("Not a ranking, and not for grading."), "on screen");
  assert.ok(!/\b(best|worst|top|bottom|ranked)\b/i.test(h));
  assert.match(CS.default.html(), /data-cs-print/);
  assert.equal(CS.default.grownup, true);
  assert.match(CS.sheetHtml({ cadets: [] }), /No cadets yet/);
});

test("class summary loadData: GETs only, one class read for every cadet", async () => {
  const st = mem({ "outpost-profiles": JSON.stringify({ active: "p1", list: [{ id: "p1", data: null }, { id: "p2", data: { "outpost-callsign": "Nova" } }] }) });
  const calls = [];
  const fetchFn = async (url, o) => { calls.push([url, o && o.method]); return { ok: true, json: async () => (url.startsWith("/api/brain/class") ? { cadets: { p1: counts, p2: counts } } : {}) }; };
  const d = await CS.loadData({ fetchFn, storage: st });
  assert.ok(calls.some(([u]) => u === "/api/brain/class?profiles=p1,p2"));
  assert.ok(calls.every(([, m]) => !m || m === "GET"));
  assert.equal(d.counts.p2.safety.filtered, 4);
});
