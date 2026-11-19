// Electron hardening (hardening.js): webPreferences, CSP, navigation and the link allow-list; and main.js / gate.js use
// them for every window (read from the source: main.js needs Electron to run).
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const H = require("./hardening");
const G = require("./gate");

const ORIGIN = "http://127.0.0.1:47310";

test("webPreferences: sandbox, isolation, no Node, no webview, no spell-check download", () => {
  const w = H.WEB_PREFS;
  assert.equal(w.sandbox, true); assert.equal(w.contextIsolation, true); assert.equal(w.nodeIntegration, false);
  assert.equal(w.nodeIntegrationInWorker, false); assert.equal(w.nodeIntegrationInSubFrames, false);
  assert.equal(w.webviewTag, false); assert.equal(w.spellcheck, false); assert.equal(w.webSecurity, true);
  assert.equal(w.allowRunningInsecureContent, false);
  assert.ok(Object.isFrozen(w));
  assert.ok(!("enableRemoteModule" in w) || w.enableRemoteModule === false);
});

test("every BrowserWindow in the shell uses WEB_PREFS; no remote module anywhere", () => {
  for (const f of ["main.js", "gate.js"]) {
    const src = fs.readFileSync(path.join(__dirname, f), "utf8");
    const prefs = [...src.matchAll(/webPreferences:\s*\{([^}]*)\}/g)].map((m) => m[1]);
    assert.ok(prefs.length >= 1, f);
    for (const p of prefs) assert.match(p, /\.\.\.(H\.)?WEB_PREFS/, `${f}: ${p}`);
    assert.doesNotMatch(src, /@electron\/remote|enableRemoteModule:\s*true|nodeIntegration:\s*true|contextIsolation:\s*false|webviewTag:\s*true/);
  }
  const main = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");
  assert.match(main, /web-contents-created/); assert.match(main, /will-attach-webview/);
  assert.match(main, /setSpellCheckerEnabled\(false\)/);
  assert.match(main, /csp: H\.csp\(origin\)/);
  assert.match(main, /globalThis\.fetch = NP\.gateFetch/);
  assert.match(main, /disable-features/);
});

test("CSP: our origin only, no inline script, only the YouTube embed as a frame", () => {
  const c = H.csp(ORIGIN);
  const d = Object.fromEntries(c.split(/;\s*/).map((x) => { const [k, ...v] = x.split(" "); return [k, v]; }));
  assert.deepEqual(d["default-src"], ["'self'"]);
  assert.deepEqual(d["script-src"], ["'self'", "'wasm-unsafe-eval'"]);
  assert.ok(!c.includes("'unsafe-eval'") && !/script-src[^;]*'unsafe-inline'/.test(c));
  assert.deepEqual(d["frame-src"], ["https://www.youtube-nocookie.com"]);
  assert.deepEqual(d["object-src"], ["'none'"]);
  assert.deepEqual(d["frame-ancestors"], ["'none'"]);
  assert.ok(d["connect-src"].includes("ws://127.0.0.1:47310"));
  assert.ok(!c.includes("*"), "no wildcards");
});

test("the built page has no inline script (the CSP would stop it)", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "..", "frontend", "index.html"), "utf8");
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
  assert.ok(scripts.length >= 1);
  for (const [, attrs, body] of scripts) assert.ok(/\bsrc=/.test(attrs) && !body.trim(), `inline script: ${attrs} ${body.slice(0, 60)}`);
  assert.doesNotMatch(html, /\son[a-z]+="/, "no inline event handlers");
});

test("links: the cited sites, our repo and site (https); nothing else", () => {
  for (const u of ["https://www.nasa.gov/moon-base/", "https://kauai.ccmc.gsfc.nasa.gov/DONKI/", "https://doi.org/10.1126/sciadv.aaz1334",
    "https://planetarynames.wr.usgs.gov/Feature/5450", "http://imbrium.mit.edu/DATA/", "https://github.com/WhissleAI/Outpost-Luna/releases/latest", "https://whissleai.github.io/Outpost-Luna/"])
    assert.equal(H.linkAllowed(u), true, u);
  for (const u of ["http://github.com/WhissleAI/Outpost-Luna", "https://evil.example/", "http://evil.example/", "https://nasa.gov.evil.example/", "https://github.com/someone/else",
    "file:///etc/passwd", "smb://fileserver/share", "ms-settings:privacy", "https://user:pw@www.nasa.gov/", "javascript:alert(1)"])
    assert.equal(H.linkAllowed(u), false, u);
});

test("navigation: our origin stays, YouTube goes behind the gate, allowed links out, the rest refused", () => {
  const nav = (u) => H.navigation(u, ORIGIN, G.classifyOpen);
  assert.equal(nav(ORIGIN + "/?x=1"), "ours");
  assert.equal(nav("http://127.0.0.1:47311/"), "refuse", "another loopback port is not ours");
  assert.equal(nav("https://www.youtube.com/watch?v=jdkMHkF7BaA"), "youtube");
  assert.equal(nav("https://www.nasa.gov/"), "external");
  assert.equal(nav("https://evil.example/"), "refuse");
  assert.equal(nav("file:///Users/x/secret.txt"), "refuse");
});

test("Chromium never looks for devices on the network", () => {
  assert.ok(H.CHROMIUM_OFF.includes("MediaRouter"));
});
