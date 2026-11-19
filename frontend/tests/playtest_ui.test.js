// Settings → For grown-ups → Voice log and playtest (src/playtest_ui.js): the plain status of the voice log, the
// consent screen before any audio is kept, the top bar tag, the export hand-over, the copy budgets (docs/COPY.md).
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const P = await import("../src/playtest_ui.js");
const A = await import("../src/a11y.js");
const words = s => String(s).trim().split(/\s+/).length;

test("registered in For grown-ups, after What the app has learned", () => {
  const sec = window.__outpost.settingsSections.find(x => x.id === "playtest");
  assert.equal(sec.title, "Voice log and playtest");
  assert.equal(sec.grownup, true);
  assert.equal(sec.after, "learning");
  assert.ok(A.GROWNUPS.inside.includes("Voice log and playtest"), "the locked gate lists it");
});

test("says plainly that the voice log is on and what it keeps", () => {
  const h = P.viewHtml({ st: { on: false, turns: 12, clips: 0 }, improve: true });
  assert.match(h, /The voice log is on\./);
  assert.match(h, /12 turns saved\./);
  assert.match(h, /no names, no audio/);
  assert.match(h, /Nothing is sent/);
  assert.match(h, /data-pt-start/);
  assert.ok(!h.includes("data-pt-export"), "nothing to export without clips");
  assert.match(P.viewHtml({ st: null, improve: false }), /The voice log is off\./);
});

test("the consent screen: Start stays disabled until the grown-up confirms permission", () => {
  const h = P.viewHtml({ view: "consent" });
  assert.match(h, /data-pt-agree/);
  assert.match(h, /<button[^>]*data-pt-go disabled/);
  assert.match(h, /parent or guardian/);
  for (const t of P.COPY.consent) assert.ok(h.includes(t.replace(/'/g, "'")));
});

test("while a playtest runs: the clip count, Export and Stop", () => {
  const h = P.viewHtml({ st: { on: true, turns: 3, clips: 2 }, improve: false });
  assert.match(h, /Playtest on · 2 clips/);
  assert.match(h, /The voice log is on\./, "a playtest logs even with the switch off");
  assert.match(h, /data-pt-export/);
  assert.match(h, /data-pt-stop/);
  assert.match(P.viewHtml({ st: { on: false, turns: 3, clips: 1 } }), /data-pt-export/, "export after the session ends");
});

test("the top bar tag appears while on and goes when off", () => {
  const made = [];
  const nav = { prepend: el => made.push(el) };
  let el = null;
  const doc = { getElementById: () => el, querySelector: () => nav, createElement: () => (el = { setAttribute() {}, remove() { el = null; } }), body: { append() {} } };
  P.setTag(true, doc);
  assert.equal(made.length, 1);
  assert.equal(el.id, "ptTag");
  assert.match(el.innerHTML, /Playtest/);
  P.setTag(false, doc);
  assert.equal(el, null);
});

test("export: the desktop hands over to the shell; the browser downloads; a failure says so", async () => {
  const w = { navigator: { userAgent: "Mozilla/5.0 Electron/44.10.0" }, location: { href: "/" } };
  const states = [];
  assert.equal(await P.exportZip({ w, fetchFn: async () => assert.fail("no fetch on desktop"), onState: s => states.push(s) }), "desktop");
  assert.equal(w.location.href, "/__outpost/playtest-export");
  w.__lunaPlaytest({ state: "saved" });
  assert.deepEqual(states, ["saved"]);
  const s2 = [];
  assert.equal(await P.exportZip({ w: { navigator: { userAgent: "Chrome" } }, fetchFn: async () => ({ ok: false, status: 500 }), onState: s => s2.push(s) }), "error");
  assert.deepEqual(s2, ["saving", "error"]);
});

test("copy budgets: help lines <= 14 words, buttons <= 3", () => {
  const C = P.COPY;
  for (const t of [C.logOn, C.logOff, C.keeps, C.where, C.switchAt, C.ptLine, C.agree, ...C.consent, A.IMPROVE.help]) assert.ok(words(t) <= 14, t);
  for (const t of [C.start, C.go, C.cancel, C.stop, C.export, C.tag, A.IMPROVE.clear]) assert.ok(words(t) <= 3, t);
});
