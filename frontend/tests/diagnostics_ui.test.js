// Settings → Help & diagnostics (src/diagnostics_ui.js): the list shown before saving, the desktop hand-over, the copy.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const D = await import("../src/diagnostics_ui.js");
const words = s => s.trim().split(/\s+/).length;

test("registered after Storage & updates, titled Help & diagnostics, with the save button", () => {
  const sec = window.__outpost.settingsSections.find(x => x.id === "diagnostics");
  assert.equal(sec.title, "Help & diagnostics");
  assert.equal(sec.after, "storage");
  const html = sec.html();
  assert.match(html, /Save a diagnostics file…/);
  assert.match(html, /<li>/);   // the list is there before anything is saved
});

test("the list comes from the backend's contents, with a fallback", () => {
  assert.deepEqual(D.items({ items: [{ name: "system.json", what: "App, system and hardware details" }] }), ["App, system and hardware details"]);
  assert.deepEqual(D.items(null), D.FALLBACK);
});

test("one short line of copy; it promises no audio, no words, never uploaded", () => {
  assert.ok(words(D.COPY.line) <= 12, D.COPY.line);
  assert.match(D.COPY.line, /No audio/);
  assert.match(D.COPY.line, /Never uploaded/);
  assert.ok(words(D.COPY.save) <= 4);
});

test("desktop: hands over to the shell (no fetch), and takes its result through window.__lunaDiag", async () => {
  const w = { navigator: { userAgent: "Mozilla/5.0 Electron/44.10.0" }, location: { href: "/" } };
  const states = [];
  let fetched = false;
  const how = await D.save({ w, fetchFn: async () => { fetched = true; }, onState: s => states.push(s) });
  assert.equal(how, "desktop");
  assert.equal(w.location.href, "/__outpost/diagnostics");
  assert.equal(fetched, false);
  w.__lunaDiag({ state: "saved" });
  assert.deepEqual(states, ["saved"]);
});

test("browser: a failed request says so, nothing else happens", async () => {
  const w = { navigator: { userAgent: "Mozilla/5.0 Chrome" } };
  const states = [];
  const how = await D.save({ w, fetchFn: async () => ({ ok: false, status: 401 }), onState: s => states.push(s) });
  assert.equal(how, "error");
  assert.deepEqual(states, ["saving", "error"]);
});
