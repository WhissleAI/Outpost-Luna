// D1-D4 on the client (docs/BRAIN.md §7, §9): crew rotation (src/crew.js, prefs.js crewState / turnProfileId), the
// practice counts landing on the cadet on turn (brain.js recordFor), the grown-ups' safety block by kind and channel
// with its caveat, care flags with "Mark as seen", the gate's safety-note count. The kid's page shows no counts.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
globalThis.dispatchEvent = globalThis.dispatchEvent || (() => true);
globalThis.CustomEvent = globalThis.CustomEvent || class { constructor(t, o) { this.type = t; this.detail = o && o.detail; } };
const { crewState, turnProfileId, CREW_KEY } = await import("../src/prefs.js");
const C = await import("../src/crew.js");
const B = await import("../src/brain.js");
const S = await import("../src/brain_store.js");
const P = await import("../src/progress.js");
const A = await import("../src/a11y.js");

function mem(obj = {}) { return { getItem: k => (k in obj ? obj[k] : null), setItem: (k, v) => { obj[k] = String(v); }, removeItem: k => { delete obj[k]; }, obj }; }
const two = () => mem({ "outpost-profiles": JSON.stringify({ active: "p1", list: [{ id: "p1", data: null }, { id: "p2", data: { "outpost-callsign": "Nova" } }] }) });
const fakePrefs = (listen = "handsfree") => { const api = { value: { listen }, update(p) { api.value = { ...api.value, ...p }; api.updates.push(p); }, updates: [] }; return api; };

// ---------- crew rotation ----------
test("crewState: off by default; needs two cadets; the turn starts with the playing cadet", () => {
  const st = two();
  assert.deepEqual([crewState(st).on, crewState(st).turn], [false, null]);
  assert.equal(turnProfileId(st), "p1");
  const one = mem({ "outpost-profiles": JSON.stringify({ active: "p1", list: [{ id: "p1" }] }) });
  assert.equal(C.setCrew(true, { storage: one, prefsApi: fakePrefs() }), false);
  assert.equal(crewState(one).on, false);
  assert.equal(C.setCrew(true, { storage: st, prefsApi: fakePrefs() }), true);
  assert.equal(crewState(st).on, true);
  assert.equal(crewState(st).turn, "p1");
});

test("passTurn: the session's profile follows the tap; unknown ids and a stale turn are refused", () => {
  const st = two();
  assert.equal(C.passTurn("p2", { storage: st }), false, "off: no turn to pass");
  C.setCrew(true, { storage: st, prefsApi: fakePrefs() });
  assert.equal(C.passTurn("p2", { storage: st }), true);
  assert.equal(turnProfileId(st), "p2");
  assert.equal(C.passTurn("p9", { storage: st }), false);
  st.setItem(CREW_KEY, JSON.stringify({ on: true, turn: "p7" }));   // a cadet who was removed
  assert.equal(turnProfileId(st), "p1");
});

test("push-to-talk per cadet: on sets Hold to talk, off restores the old choice", () => {
  const st = two(), pa = fakePrefs("handsfree");
  C.setCrew(true, { storage: st, prefsApi: pa });
  assert.equal(pa.value.listen, "ptt");
  C.passTurn("p2", { storage: st });
  C.setCrew(false, { storage: st, prefsApi: pa });
  assert.equal(pa.value.listen, "handsfree");
  assert.equal(st.getItem(CREW_KEY), null);
  assert.equal(turnProfileId(st), "p1");
});

test("crewBarHtml: names only, the cadet on turn lit, no counts or scores", () => {
  const h = C.crewBarHtml([{ id: "p1", callsign: "Comet" }, { id: "p2", callsign: "Nova<x>" }], "p2");
  assert.match(h, /data-crew-turn="p2"[^>]*aria-pressed="true"/);
  assert.match(h, /Nova&lt;x&gt;: hold Space to talk/);
  assert.ok(!/\d+\s*(filtered|turns|stars|points)/i.test(h));
  assert.equal(C.COPY.turn("Nova"), "Nova, your turn.");
});

test("recordFor: a step counts for the cadet on turn (her saved profile), the live keys for the playing cadet", () => {
  const st = two();
  B.recordFor("p2", { lesson: "moon", type: "choice", status: "passed", misses: 0, step_s: 10 }, st);
  const snap = JSON.parse(JSON.parse(st.getItem("outpost-profiles")).list[1].data["outpost-brain"]);
  assert.equal(snap.lessons.moon.first, 1);
  assert.equal(st.getItem("outpost-brain"), null, "the playing cadet's counts are untouched");
  assert.equal(JSON.parse(st.getItem("outpost-profiles")).list[1].data["outpost-callsign"], "Nova", "the rest of her save stays");
  B.recordFor("p1", { lesson: "moon", type: "choice", status: "passed", misses: 0, step_s: 10 }, st);
  assert.equal(S.load(st).lessons.moon.first, 1);
  assert.equal(B.brainOf("p2", st).lessons.moon.first, 1);
});

// ---------- the grown-ups' safety block ----------
const CADET = { scope: "cadet", talk: { turns: 4, days: 2, voice: 2, typed: 2, answered: 3, passed_by: 1, room: { calm: 4, busy: 0, loud: 0 } },
  safety: { guarded: 6, filtered: 5, privacy: 1, care: 1,
    by_kind: { profanity: { typed: 1, ptt: 1, directed: 0, room: 2 }, mask: { typed: 0, ptt: 0, directed: 1, room: 0 } },
    care_flags: [{ id: "a1b2c3d4", kind: "self_harm", day: "2026-11-20", n: 2 }, { id: "zz", kind: "feelings", day: "2026-11-20", n: 1 }],
    weeks: [{ week: "2026-W44", profanity: 0, mask: 0 }, { week: "2026-W45", profanity: 1, mask: 0 }, { week: "2026-W46", profanity: 0, mask: 0 }, { week: "2026-W47", profanity: 4, mask: 1 }] } };

test("computerHtml (cadet scope): profanity split by channel, privacy apart, the open-mic caveat, the trend, Clear", () => {
  const h = B.computerHtml(CADET, "p2");
  assert.ok(h.includes("This cadet, last 30 days"));
  assert.ok(h.includes("Rude words filtered:</b> 1 typed, 1 push-to-talk, 0 said to the app, 2 heard in the room."), h);
  assert.ok(h.includes("Other words filtered (unkind or not suitable):</b> 0 typed, 0 push-to-talk, 1 said to the app"));
  assert.ok(h.includes("Kept private by the privacy guard (names, addresses): 1 turn."));
  assert.ok(h.includes("mean heard near the app"), "the honest caveat");
  assert.ok(h.includes("the last 4 weeks (oldest first): 0, 1, 0, 5."));
  assert.match(h, /data-safety-clear="p2"/);
});

test("careHtml: kind and day only, Mark as seen, never the words; unknown kinds dropped", () => {
  const h = B.careHtml(CADET.safety.care_flags);
  assert.ok(h.includes("Words about getting hurt came up on 2026-11-20 (2 times that day)"));
  assert.match(h, /data-care-ack="a1b2c3d4"/);
  assert.ok(!h.includes("feelings") && !h.includes('data-care-ack="zz"'));
  assert.ok(h.includes("no note does not mean all clear"));
  assert.equal(B.careHtml([]), "");
  assert.ok(B.computerHtml(CADET, "p2").startsWith(B.careHtml(CADET.safety.care_flags)), "the notes come first");
});

test("the kid's page: no counts, nothing punitive; the shield card tells the cadet grown-ups see how many", () => {
  const h = B.cadetHtml({ callsign: "Nova", academy: { badges: [] }, flown: [], lessons: [], brain: S.blank(), learned: null });
  assert.ok(!/filtered|safety note|push-to-talk|heard in the room/i.test(h));
  assert.ok(h.includes("Grown-ups see how many, never the word."));
});

test("sheetHtml: every cadet card gets her own block when the counts are per cadet", () => {
  const st = mem({ "outpost-profiles": JSON.stringify({ active: "p1", list: [{ id: "p1", data: null }, { id: "p2", data: { "outpost-callsign": "Nova" } }] }), "outpost-callsign": "Comet" });
  const cadets = P.readCadets(st);
  const h = P.sheetHtml({ cadets, lessons: [], summaries: { p1: { ...CADET, safety: { ...CADET.safety, care_flags: [] } }, p2: CADET } });
  assert.equal((h.match(/class="pg-block pg-safety"/g) || []).length, 2);
  assert.equal((h.match(/data-care-ack=/g) || []).length, 1);
});

test("loadData: one summary per cadet, GETs only", async () => {
  const st = mem({ "outpost-profiles": JSON.stringify({ active: "p1", list: [{ id: "p1", data: null }, { id: "p2", data: {} }, { id: "p3", data: {} }] }) });
  const calls = [];
  const fetchFn = async (url, o) => { calls.push([url, o && o.method]); return { ok: true, json: async () => (url.startsWith("/api/brain/summary") ? { scope: "cadet", safety: {} } : {}) }; };
  const d = await P.loadData({ fetchFn, storage: st });
  assert.deepEqual(Object.keys(d.summaries).sort(), ["p1", "p2", "p3"]);
  assert.ok(calls.every(([, m]) => !m || m === "GET"));
});

test("the gate's safety-note count", async () => {
  assert.equal(A.GROWNUPS.notes(1), "1 safety note in Progress");
  assert.equal(A.GROWNUPS.notes(2), "2 safety notes in Progress");
  assert.equal(await A.safetyNotes(async () => ({ ok: true, json: async () => ({ flags: [{}, {}] }) })), 2);
  assert.equal(await A.safetyNotes(async () => ({ ok: false })), 0);
  assert.equal(await A.safetyNotes(async () => { throw new Error("down"); }), 0);
  assert.match(A.grownupsHtml({ open: false }), /data-gu-notes[^>]*hidden/);
});
