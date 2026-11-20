// Settings → For grown-ups → Progress (src/progress.js): per cadet on this computer, from what the app already saves.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = globalThis.window || {};
const P = await import("../src/progress.js");

function store(obj) { return { getItem: k => (k in obj ? obj[k] : null) }; }
const L = (id, extra = {}) => ({ id, title: "T " + id, badge: { id: "b-" + id, name: "Patch " + id }, steps: [{}, {}, {}, {}], ...extra });
const LESSONS = [L("moon"), L("phases"), L("power"), L("checkride", { ride: true }), L("history", { track: "explorer", unlock_after_missions: 1 }),
  L("craters", { track: "field", unlock_after: "checkride" }),
  L("c-room5-tides", { track: "class", pack: { id: "room5", title: "Room 5" }, badge: { id: "c-room5-tides", name: "Tides", glyph: "T" } }),
  L("c-room5-ice", { track: "class", pack: { id: "room5", title: "Room 5" }, badge: { id: "c-room5-ice", name: "Ice", glyph: "I" } })];

const STORAGE = store({
  "outpost-profiles": JSON.stringify({ active: "p1", list: [{ id: "p1", data: null }, { id: "p2", data: {
    "outpost-callsign": "Nova", "atm-academy": JSON.stringify({ badges: ["b-moon", "b-phases", "b-power", "b-checkride"], qualified: true }) } }] }),
  "outpost-callsign": "Comet",
  "atm-academy": JSON.stringify({ badges: ["b-moon", "c-room5-tides"], qualified: false, steps: { phases: { i: 2, n: 4 } }, current: "phases" }),
  "outpost-missions-flown:Nova": JSON.stringify(["m-aaaa1111", "m-bbbb2222"]),
});

test("readCadets: the playing cadet from the live keys, the others from their snapshot; missions by call sign", () => {
  const cs = P.readCadets(STORAGE);
  assert.equal(cs.length, 2);
  assert.deepEqual(cs.map(c => [c.id, c.active, c.callsign]), [["p1", true, "Comet"], ["p2", false, "Nova"]]);
  assert.deepEqual(cs[0].academy.badges, ["b-moon", "c-room5-tides"]);
  assert.equal(cs[1].academy.qualified, true);
  assert.deepEqual(cs[1].flown, ["m-aaaa1111", "m-bbbb2222"]);
  assert.deepEqual(cs[0].flown, []);
});

test("readCadets: no profiles saved yet, or broken JSON, is one cadet and never throws", () => {
  const cs = P.readCadets(store({ "outpost-profiles": "{bad", "atm-academy": "nope" }));
  assert.equal(cs.length, 1); assert.deepEqual(cs[0].academy.badges, []);
  assert.equal(P.readCadets(null).length, 1);
});

test("summarize: NASA counts leave class lessons out; class lessons grouped by pack; resume step; try next", () => {
  const [comet, nova] = P.readCadets(STORAGE);
  const s = P.summarize(comet, LESSONS);
  assert.equal(s.nasa.total, 6, "class lessons never count toward NASA patches");
  assert.deepEqual(s.nasa.earned.map(p => p.id), ["moon"]);
  assert.deepEqual(s.core, { done: 1, of: 3 });
  assert.equal(s.classes.length, 1); assert.equal(s.classes[0].title, "Room 5");
  assert.deepEqual(s.classes[0].lessons.map(l => [l.id, l.done]), [["c-room5-tides", true], ["c-room5-ice", false]]);
  assert.deepEqual(s.current, { title: "T phases", i: 2, n: 4 });
  assert.equal(s.next[0], "Lesson: T phases.");
  const n = P.summarize(nova, LESSONS);
  assert.equal(n.current, null);
  assert.ok(n.next.includes("Field School: T craters."), n.next.join(" | "));
  assert.ok(n.next.length <= 2);
});

test("cadetHtml: patches, stats, class group, try next; missions without a debrief are counted only", () => {
  const [comet, nova] = P.readCadets(STORAGE);
  const fakePatch = id => (id === "moon" || id === "phases" ? `<svg class="patch patch-${id}"></svg>` : "");
  const h = P.cadetHtml(comet, LESSONS, { patch: fakePatch });
  assert.match(h, /Comet/); assert.match(h, /Playing/);
  assert.match(h, /patch-moon/);
  assert.match(h, /Class lessons · Room 5/);
  assert.match(h, /pg-glyph is-earned[^>]*>T</, "a class patch without art gets its glyph badge");
  assert.match(h, /In progress/);
  assert.match(h, /Try next/);
  assert.doesNotMatch(h, /pg-missions/, "no missions flown: no missions block");
  const hn = P.cadetHtml(nova, LESSONS, { patch: fakePatch, debriefs: { "m-aaaa1111": null } });
  assert.match(hn, /Qualified/);
  assert.match(hn, /Mission 1/); assert.match(hn, /Mission 2/);
  assert.match(hn, /is-counted/);
  assert.doesNotMatch(hn, /Grade/, "no debrief held: no grade invented");
});

test("missionHtml: a held debrief shows its stars, grade, site and the debrief's three checks", () => {
  const d = { outcome: "survived", grade: "A", stars: 2, site: { name: "Malapert Massif (south)" }, timeline: [],
    objectives: { science: { met: true, got: 130, goal: 120 }, ice: { met: false, got: 0 } }, final: { science: 130, science_sent: 130 }, try: "Send the rover for ice early. Then rest." };
  const h = P.missionHtml(3, d);
  assert.match(h, /Mission 3 · Malapert Massif</);
  assert.match(h, /aria-label="2 of 3 stars"/);
  assert.equal((h.match(/class="is-on"/g) || []).length, 2);
  assert.match(h, /mx-grade">A</);
  assert.equal((h.match(/<li class="is-(ok|no)"/g) || []).length, 3);
  assert.match(h, /Try next<\/b> Send the rover for ice early\./);
  assert.match(P.missionHtml(1, { outcome: "in_progress" }), /is-counted/);
});

test("sheetHtml: every cadet, the paused mission; zone has a Print button; empty state", () => {
  const cadets = P.readCadets(STORAGE);
  const h = P.sheetHtml({ cadets, lessons: LESSONS, saved: { site_name: "Shackleton Rim (x)", day: 4 }, patch: () => "", date: "19 November 2026" });
  assert.equal((h.match(/class="pg-cadet/g) || []).length, 2);
  assert.match(h, /Paused at Shackleton Rim, day 4 of 10\./);
  assert.match(h, /Outpost Luna progress · 19 November 2026/);
  assert.match(P.zoneHtml(), /<button type="button" class="btn" data-pg-print>Print<\/button>/);
  assert.match(P.sheetHtml({ cadets: [] }), /No cadets yet/);
});

test("loadData reads only: GETs for the course, held debriefs and the saved mission; never a write", async () => {
  const calls = [];
  const fetchFn = async (url, opts) => {
    calls.push([url, opts && opts.method]);
    if (url === "/api/academy/course") return { ok: true, json: async () => ({ lessons: LESSONS }) };
    if (url === "/api/mission/m-aaaa1111/debrief") return { ok: true, json: async () => ({ outcome: "power_out", grade: "D", stars: 0 }) };
    if (url === "/api/mission/saved") return { ok: true, json: async () => ({ saved: null }) };
    return { ok: false };
  };
  const d = await P.loadData({ fetchFn, storage: STORAGE });
  assert.ok(calls.every(([, m]) => !m || m === "GET"));
  assert.equal(d.lessons.length, LESSONS.length);
  assert.equal(d.debriefs["m-aaaa1111"].grade, "D");
  assert.equal(d.debriefs["m-bbbb2222"], null);
  assert.equal(d.saved, null);
});

test("section: a grown-up part, listed first; no age words; no new storage writes", () => {
  assert.equal(P.default.id, "progress"); assert.equal(P.default.grownup, true); assert.equal(P.default.first, true);
  assert.ok(window.__outpost.settingsSections.some(s => s.id === "progress"));
  const src = readFileSync(new URL("../src/progress.js", import.meta.url), "utf8");
  assert.doesNotMatch(src, /setItem|removeItem/, "Progress never stores anything");
  const copy = JSON.stringify(Object.fromEntries(Object.entries(P.COPY).map(([k, v]) => [k, typeof v === "function" ? v("X", 1) : v])));
  const cadets = P.readCadets(STORAGE);
  const html = copy + P.sheetHtml({ cadets, lessons: LESSONS, patch: () => "" }) + P.zoneHtml();
  assert.doesNotMatch(html, /\b(kids?|child(ren)?|ages?|years? old|7.9|10.12)\b/i);
  const a11y = readFileSync(new URL("../src/a11y.js", import.meta.url), "utf8");
  assert.match(a11y, /guExtras\.filter\(x => x\.first\)/);
});

test("print stylesheet prints the sheet alone, light, one cadet per page", () => {
  const css = readFileSync(new URL("../src/progress.css", import.meta.url), "utf8");
  assert.match(css, /@media print/);
  assert.match(css, /body\.pg-printing > :not\(#pgPrint\)\{display:none !important\}/);
  assert.match(css, /#pgPrint \.pg-cadet\{break-after:page/);
  assert.match(css, /--color-bg:#fff/);
});
