// Settings → App version (src/app_update_ui.js): the row's states, the shell hand-over, the opt-in, the notice.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const AU = await import("../src/app_update_ui.js");
const { normalizePrefs, PREF_DEFAULTS } = await import("../src/prefs.js");
const words = s => s.trim().split(/\s+/).length;
const DL = "https://github.com/WhissleAI/Outpost-Luna/releases/download/v0.3.9/Outpost-Luna-mac-arm64.dmg";

test("registered after Help & diagnostics as App version; desktop only", () => {
  const sec = window.__outpost.settingsSections.find(x => x.id === "appupdate");
  assert.equal(sec.title, "App version");
  assert.equal(sec.after, "diagnostics");
  assert.equal(sec.html(), "");   // no Electron user agent here: a browser (make dev) has no shell to ask
  const ua = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { value: { userAgent: "Mozilla/5.0 Electron/44.10.0" }, configurable: true });
  try {
    const html = sec.html();
    assert.match(html, /Check for updates</);
    assert.match(html, /data-pb="update_check"/);
    assert.doesNotMatch(html, /data-pb="update_check" checked/);   // off by default
    assert.match(html, /data-au-ver/);
  } finally { if (ua) Object.defineProperty(globalThis, "navigator", ua); else delete globalThis.navigator; }
});

test("one short line of copy, and it promises nothing installs by itself", () => {
  assert.ok(words(AU.COPY.line) <= 12, AU.COPY.line);
  assert.match(AU.COPY.line, /Nothing installs by itself/);
  assert.ok(words(AU.COPY.check) <= 4);
});

test("states: idle, checking, up to date, available, available for another OS, offline", () => {
  assert.deepEqual(AU.view({ state: "idle", current: "0.3.8" }), { line: "", notes: "", action: null });
  assert.equal(AU.view({ state: "checking" }).busy, true);
  assert.equal(AU.view({ state: "up_to_date", current: "0.3.8", latest: "0.3.8" }).line, "You're up to date (0.3.8)");
  const a = AU.view({ state: "available", current: "0.3.8", latest: "0.3.9", download: DL, notes: "Check for updates in Settings.\nFixes." });
  assert.equal(a.line, "Outpost Luna 0.3.9 is available");
  assert.equal(a.notes, "Check for updates in Settings.\nFixes.");
  assert.deepEqual(a.action, { what: "download", label: "Download" });
  const w = AU.view({ state: "available", latest: "0.3.9", download: null, others: ["Mac"], platform: "Windows" });
  assert.equal(w.line, "0.3.9 is out for Mac; the Windows installer is coming");
  assert.deepEqual(w.action, { what: "release", label: "Open the release page" });
  const e = AU.view({ state: "error", reason: "offline" });
  assert.equal(e.line, "Couldn't check right now. You can also download from whissleai.github.io/Outpost-Luna");
  assert.equal(e.action.what, "site");
  assert.equal(AU.view({ state: "error", reason: "rate_limited" }).line, e.line);
});

test("the page only asks the shell: a check and an open by name, never a URL", () => {
  const w = { location: { href: "/" } };
  AU.check(w);
  assert.equal(w.location.href, "/__outpost/update?do=check");
  AU.open("download", w);
  assert.equal(w.location.href, "/__outpost/update?do=open&what=download");
});

test("the opt-in: off by default, only an explicit true turns it on; the shell is told through __lunaUpdate", () => {
  assert.equal(PREF_DEFAULTS.update_check, false);
  assert.equal(normalizePrefs({}).update_check, false);
  assert.equal(normalizePrefs({ update_check: "true" }).update_check, false);
  assert.equal(normalizePrefs({ update_check: true }).update_check, true);
  assert.equal(window.__lunaUpdate, AU.receive);
  assert.equal(AU.autoOn({ prefsApi: { value: { update_check: true } } }), true);
  assert.equal(AU.autoOn({}, { getItem: () => JSON.stringify({ update_check: true }) }), true);
  assert.equal(AU.autoOn({}, { getItem: () => null }), false);
  assert.equal(AU.autoOn({}, { getItem: () => "{junk" }), false);
  assert.deepEqual(AU.receive({ state: "idle", current: "0.3.8" }), { auto: false });
});

test("the notice: shown for an update, with the same Download; nothing for no update", () => {
  const made = [];
  const el = () => { const n = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, remove() { this.removed = true; } }; made.push(n); return n; };
  const doc = { body: { appendChild(n) { doc.byId[n.id] = n; } }, byId: {}, getElementById(id) { return this.byId[id] || null; }, createElement: el };
  const n = AU.showNotice({ state: "available", latest: "0.3.9", download: DL }, doc);
  assert.equal(n.className, "au-notice");
  assert.equal(n.attrs.role, "status");
  assert.match(n.innerHTML, /Outpost Luna 0\.3\.9 is available/);
  assert.match(n.innerHTML, /data-au-open="download">Download</);
  assert.doesNotMatch(n.innerHTML, /https?:/);   // the page holds no URL to open
  assert.equal(AU.showNotice({ state: "up_to_date", current: "0.3.8" }, doc), null);
});
