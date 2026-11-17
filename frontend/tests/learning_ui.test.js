// Settings → What the app has learned (src/learning_ui.js, docs/ON_DEVICE_LEARNING.md): the view, removal, reset,
// the active cadet profile, and the diagnostics opt-in for learned names.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const L = await import("../src/learning_ui.js");
const D = await import("../src/diagnostics_ui.js");

test("registered after Help & diagnostics, with Reset learning and the no-recordings promise", () => {
  const sec = window.__outpost.settingsSections.find(x => x.id === "learning");
  assert.equal(sec.title, "What the app has learned");
  assert.equal(sec.after, "diagnostics");
  const html = sec.html();
  assert.match(html, /Reset learning/);
  assert.match(L.COPY.line, /No recordings/);
});

test("the view lists the plain lines and each learned name with a Remove button (escaped)", () => {
  const html = L.viewHtml({ lines: ["Names you say your way: “ticko” means Tycho."],
    learned: { aliases: [{ heard: "ticko", name: "Tycho" }, { heard: "<b>x</b>", name: "Ohm" }] } });
  assert.match(html, /Names you say your way/);
  assert.match(html, /data-lr-forget="ticko"/);
  assert.ok(!html.includes("<b>x</b>"));
  assert.match(L.viewHtml(null), /Nothing learned yet/);
});

test("the active profile comes from prefs.js's profile list, p1 otherwise", () => {
  const st = v => ({ getItem: () => v });
  assert.equal(L.activeProfile(st(JSON.stringify({ active: "p3", list: [] }))), "p3");
  assert.equal(L.activeProfile(st("not json")), "p1");
  assert.equal(L.activeProfile(st(JSON.stringify({ active: "../x" }))), "p1");
});

test("diagnostics: learned names go into the file only when the box is ticked", async () => {
  const sent = [];
  const w = { navigator: { userAgent: "Mozilla" }, document: { createElement: () => ({ click() {}, remove() {} }), body: { appendChild() {} } } };
  globalThis.URL.createObjectURL = () => "blob:x"; globalThis.URL.revokeObjectURL = () => {};
  const fetchFn = async (u, o) => { sent.push(o.body); return { ok: true, blob: async () => new Blob([]) }; };
  await D.save({ w, fetchFn });
  await D.save({ w, fetchFn, names: true });
  assert.equal(sent[0], "{}");
  assert.deepEqual(JSON.parse(sent[1]), { learning_aliases: true });
  const loc = { href: "" }, wd = { navigator: { userAgent: "Electron/30" }, location: loc };
  await D.save({ w: wd, names: true });
  assert.equal(loc.href, "/__outpost/diagnostics?names=1");
});
