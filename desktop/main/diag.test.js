"use strict";
// [#92] diag.js: the shell's structured log (scrubbed, rotated), crash-free sessions, the diagnostics file hand-over.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const D = require("./diag");

const TOKEN = "Zq3-very-secret-launch-token-0123456789abcdefXYZ";
const SAID = "fly me to shackleton crater please";
const tmp = (p) => fs.mkdtempSync(path.join(os.tmpdir(), `luna-diag-${p}-`));

test("the same sensitive keys as the Python servers (app/diag.py)", () => {
  const py = fs.readFileSync(path.join(__dirname, "../../backend/app/diag.py"), "utf8");
  const keys = py.match(/SENSITIVE_KEYS = frozenset\(\{([\s\S]*?)\}\)/)[1].match(/"([^"]+)"/g).map((x) => x.slice(1, -1));
  assert.deepStrictEqual([...D.SENSITIVE_KEYS].sort(), keys.sort());
  const suf = py.match(/SENSITIVE_SUFFIXES = \(([^)]*)\)/)[1].match(/"([^"]+)"/g).map((x) => x.slice(1, -1));
  assert.deepStrictEqual(D.SENSITIVE_SUFFIXES, suf);
});

test("a log call with a transcript, a name or the token never writes them", () => {
  const dir = tmp("log");
  const log = D.createJsonLog({ dir, svc: "main", token: TOKEN });
  log.event("turn", { text: SAID, names: ["Charlie Duke"], heard: "Charlie Duke", token: TOKEN, audio: Buffer.from("RIFF"),
    msg: `GET /api/reset/confirm?token=${TOKEN}`, note: `X-Luna-Token: ${TOKEN}`, where: path.join(os.homedir(), "Library"), child: "models", code: 1 });
  const raw = fs.readFileSync(path.join(dir, "main.jsonl"), "utf8");
  for (const bad of [SAID, "Charlie Duke", TOKEN, os.homedir() + path.sep]) assert.ok(!raw.includes(bad), bad);
  const rec = JSON.parse(raw.trim());
  assert.strictEqual(rec.svc, "main");
  assert.strictEqual(rec.event, "turn");
  assert.strictEqual(rec.child, "models");
  assert.strictEqual(rec.code, 1);
  assert.strictEqual(rec.where, "~/Library");
});

test("rotation caps the files and their size", () => {
  const dir = tmp("rot");
  const log = D.createJsonLog({ dir, svc: "main", maxBytes: 1500, keep: 3 });
  for (let i = 0; i < 300; i++) log.event("tick", { i, pad: "z".repeat(40) });
  const files = fs.readdirSync(dir).sort();
  assert.deepStrictEqual(files, ["main.jsonl", "main.jsonl.1", "main.jsonl.2"]);
  for (const f of files) assert.ok(fs.statSync(path.join(dir, f)).size <= 1500, f);
  assert.strictEqual(D.LOG_MAX_BYTES, 5 * 1024 * 1024);
  assert.strictEqual(D.LOG_KEEP, 5);
  const t = path.join(dir, "main.log");
  fs.writeFileSync(t, "x".repeat(2000));
  assert.ok(D.rotateText(t, 1000));
  assert.ok(fs.existsSync(t + ".1") && !fs.existsSync(t));
});

test("crash-free sessions: clean quit yes; a child restart no; an unfinished launch no", () => {
  const dir = tmp("ses");
  let t = new Date(2026, 10, 16, 10).getTime();
  const tr = () => D.createTracker({ dir, version: "0.3.8", now: () => t });
  let a = tr();
  assert.strictEqual(a.begin().previous, null);
  assert.strictEqual(a.end(), true);                               // 1: clean
  a = tr();
  assert.strictEqual(a.begin().previous, "clean");
  a.restart("models");
  assert.strictEqual(a.end(), false);                              // 2: a child crashed and restarted
  a = tr();
  a.begin();                                                       // 3: never ends (the app was killed)
  a = tr();
  assert.strictEqual(a.begin().previous, "crashed");               // 4: counts 3 as not crash-free
  a.end(true);                                                     // 4: failed to start (the error box)
  const doc = JSON.parse(fs.readFileSync(path.join(dir, "daily-main.json"), "utf8"));
  const c = doc.days["2026-11-16"].counters;
  assert.strictEqual(c.sessions, 4);
  assert.strictEqual(c.sessions_crash_free, 1);
  assert.strictEqual(c.sessions_not_crash_free, 3);
  assert.strictEqual(c["restarts{child=models}"], 1);
  const s = tr().snapshot();
  assert.deepStrictEqual(s.crash_free_sessions_30d, { crash_free: 1, not_crash_free: 3, rate: 0.25 });
});

test("the daily summary keeps 30 days", () => {
  const f = path.join(tmp("days"), "daily-main.json");
  for (let i = 0; i < 40; i++) D.addDaily(f, { sessions: 1 }, new Date(2026, 0, 1 + i).getTime());
  assert.strictEqual(Object.keys(JSON.parse(fs.readFileSync(f, "utf8")).days).length, D.KEEP_DAYS);
});

test("shell info: no token, no host or user name", () => {
  const info = D.shellInfo({ appVersion: "0.3.8", packaged: true,
    engine: { format: 1, backend: "http://127.0.0.1:48310", token: TOKEN, pid: 1 }, appMetrics: [{ type: "Browser", pid: 1, memory: { workingSetSize: 204800 } }] });
  const s = JSON.stringify(info);
  assert.ok(!s.includes(TOKEN));
  assert.ok(!s.includes(os.hostname()) || os.hostname().length < 3);
  assert.ok(!s.includes(os.userInfo().username + "/"));
  assert.strictEqual(info.engine.backend, "http://127.0.0.1:48310");
  assert.strictEqual(info.main_metrics.memory_mb[0].rss_mb, 200);
  assert.ok(info.hardware.cores >= 1 && info.app.version === "0.3.8");
});

test("the page's request: only our own origin's /__outpost/diagnostics", () => {
  const o = "http://127.0.0.1:48310";
  assert.ok(D.isDiagUrl(`${o}/__outpost/diagnostics`, o));
  assert.ok(!D.isDiagUrl("http://evil.example/__outpost/diagnostics", o));
  assert.ok(!D.isDiagUrl(`${o}/__outpost/reset?level=all`, o));
  assert.match(D.defaultName(new Date(2026, 10, 16).getTime()), /^outpost-luna-diagnostics-2026-11-16\.zip$/);
});

test("saveBundle: sends the token header, writes only a zip, where the user chose", async () => {
  const dir = tmp("save"), file = path.join(dir, "d.zip");
  const zip = Buffer.concat([Buffer.from([0x50, 0x4b, 0x03, 0x04]), Buffer.alloc(40)]);
  let seen;
  const n = await D.saveBundle({ backend: "http://127.0.0.1:1", token: TOKEN, shell: { app: {} }, file,
    fetchFn: async (url, o) => { seen = { url, o }; return { ok: true, arrayBuffer: async () => zip }; } });
  assert.strictEqual(n, zip.length);
  assert.strictEqual(seen.url, "http://127.0.0.1:1/api/diagnostics/bundle");
  assert.strictEqual(seen.o.headers["X-Luna-Token"], TOKEN);
  assert.deepStrictEqual(fs.readdirSync(dir), ["d.zip"]);
  await assert.rejects(D.saveBundle({ backend: "x", token: TOKEN, shell: {}, file: path.join(dir, "e.zip"),
    fetchFn: async () => ({ ok: true, arrayBuffer: async () => Buffer.from("<html>") }) }), /not send a zip/);
  await assert.rejects(D.saveBundle({ backend: "x", token: TOKEN, shell: {}, file: path.join(dir, "e.zip"),
    fetchFn: async () => ({ ok: false, status: 401 }) }), /401/);
  assert.deepStrictEqual(fs.readdirSync(dir), ["d.zip"]);
});
