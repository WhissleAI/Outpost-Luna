"use strict";
// The first-run screen (firstrun.html + firstrun_progress.js): overall total and percent, speed and time left, the
// "one time, then offline" line, and the app's own font shipped next to the page (no network, CSP allows only 'self').
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const P = require("./firstrun_progress");

const MANIFEST = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "assets.manifest.json"), "utf8"));
const REQUIRED = MANIFEST.assets.filter((a) => a.required).map((a) => ({ id: a.id, title: a.title, size: a.size, done: 0, state: "missing" }));

test("summarize: the required assets add up to the ~452 MB the docs promise; installed counts in full", () => {
  const s = P.summarize(REQUIRED);
  assert.equal(P.bytes(s.total), "452 MB");
  assert.equal(s.pct, 0);
  const half = REQUIRED.map((a) => (a.id === "ear" ? { ...a, done: a.size / 2 } : { ...a, state: "installed" }));
  const h = P.summarize(half);
  assert.equal(h.pct, Math.floor((100 * (h.total - REQUIRED.find((a) => a.id === "ear").size / 2)) / h.total));
  assert.equal(P.summarize(REQUIRED.map((a) => ({ ...a, state: "installed" }))).complete, true);
  // garbage never breaks the screen
  assert.deepEqual(P.summarize([{ size: 100, done: 900 }, { size: "x", done: -5 }]), { total: 100, done: 100, left: 0, pct: 100, complete: true });
  assert.equal(P.summarize([]).pct, 0);
});

test("rate: bytes per second over a sliding window; unknown until 1.5 s of samples; a drop restarts it", () => {
  const r = P.createRate();
  r.add(0, 0);
  assert.equal(r.speed(), 0);
  r.add(1000, 5e6);
  assert.equal(r.speed(), 0);            // too short a span to trust
  r.add(2000, 10e6);
  assert.equal(r.speed(), 5e6);
  for (let t = 3000; t <= 20000; t += 1000) r.add(t, 10e6 + (t - 2000) * 2000);   // slows to 2 MB/s
  assert.ok(Math.abs(r.speed() - 2e6) < 1, String(r.speed()));
  r.add(21000, 1e6);                     // an import restarted: bytes went down
  assert.equal(r.speed(), 0);
});

test("eta and lines: plain words, nothing when the speed is unknown", () => {
  assert.equal(P.eta(10e6, 0), "");
  assert.equal(P.eta(10e6, 1e6), "under a minute left");
  assert.equal(P.eta(300e6, 1e6), "about 5 min left");
  assert.equal(P.eta(5000e6, 1e6), "about 1 h 23 min left");
  assert.equal(P.eta(3600e6, 1e6), "about 1 h left");
  const s = P.summarize([{ size: 510e6, done: 312e6 }]);
  assert.deepEqual(P.lines(s, 2.5e6), { top: "312 MB of 510 MB · 61%", rate: "2.5 MB/s · about 1 min left" });
  assert.deepEqual(P.lines(s, 0), { top: "312 MB of 510 MB · 61%", rate: "" });
  assert.equal(P.lines(P.summarize([{ size: 1, state: "installed" }]), 9e6).rate, "");
  assert.equal(P.bytes(13.78e6), "14 MB");
  assert.equal(P.bytes(2.5e6), "2.5 MB");
  assert.equal(P.bytes(3e6), "3 MB");
  assert.equal(P.bytes(1.2e9), "1.2 GB");
});

test("firstrun.html: total bar, speed, the one-time line, the app font; all offline (CSP 'self' only)", () => {
  const html = fs.readFileSync(path.join(__dirname, "firstrun.html"), "utf8");
  const csp = /Content-Security-Policy" content="([^"]+)"/.exec(html)[1];
  assert.match(csp, /default-src 'none'/);
  assert.match(csp, /script-src 'self' 'unsafe-inline'/);
  assert.match(csp, /font-src 'self'(;|$)/);
  assert.doesNotMatch(html, /https?:\/\//);                         // nothing remote
  assert.match(html, /<script src="firstrun_progress\.js"><\/script>/);
  assert.match(html, /One time only\. After this, Outpost Luna runs fully offline\./);
  assert.match(html, /id="totalTop"/);
  assert.match(html, /id="totalRate"/);
  assert.match(html, /role="progressbar"/);
  const font = /url\((fonts\/[^)]+\.woff2)\)/.exec(html)[1];
  assert.ok(fs.statSync(path.join(__dirname, font)).size > 10000, font);
  assert.ok(fs.existsSync(path.join(__dirname, "fonts", "Inter-OFL.txt")));
  assert.match(html, /font:15px\/1\.4 "Inter Variable"/);
});

test("firstrun.html's script runs against a fake page: the total shows bytes, percent and (while busy) the speed", () => {
  const html = fs.readFileSync(path.join(__dirname, "firstrun.html"), "utf8");
  const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]).join("\n");
  const els = {};
  const el = (id) => (els[id] = els[id] || { id, hidden: false, textContent: "", className: "", disabled: false, style: {}, attrs: {},
    setAttribute(k, v) { this.attrs[k] = v; }, replaceChildren(...c) { this.children = c; } });
  let onState = null;
  let now = 0;
  const window = { firstrun: { onState: (cb) => { onState = cb; }, retry() {}, later() {}, importPack() {} } };
  const ctx = { window, document: { getElementById: el, createElement: () => ({ innerHTML: "", querySelector: () => ({ textContent: "", style: {} }) }) },
    Date: { now: () => now } };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "firstrun_progress.js"), "utf8"), ctx);
  vm.runInContext(inline, ctx);
  const send = (done) => onState({ busy: true, title: "Getting Outpost Luna ready", assets: [{ id: "ear", title: "Ear", size: 500e6, done, state: "missing" }] });
  send(0); now = 1000; send(5e6); now = 2000; send(10e6);
  assert.equal(els.total.hidden, false);
  assert.equal(els.totalTop.textContent, "10 MB of 500 MB · 2%");
  assert.equal(els.totalRate.textContent, "5 MB/s · about 2 min left");
  assert.equal(els.totalFill.style.width, "2%");
  assert.equal(els.totalBar.attrs["aria-valuenow"], "2");
  onState({ busy: false, problem: true, message: "offline", assets: [{ id: "ear", title: "Ear", size: 500e6, done: 10e6 }] });
  assert.equal(els.totalRate.textContent, "");                       // stopped: no stale speed
});
