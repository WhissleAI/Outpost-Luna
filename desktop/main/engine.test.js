"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const E = require("./engine");

test("newToken: 43 URL-safe chars, different every launch", () => {
  const a = E.newToken(), b = E.newToken();
  assert.match(a, /^[A-Za-z0-9_-]{43}$/);
  assert.notStrictEqual(a, b);
});

test("discovery file: the documented record, 0600, atomic, removed only by its owner", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luna-engine-"));
  const f = E.discoveryFile(dir);
  assert.strictEqual(path.basename(f), "engine.json");
  const rec = E.discoveryRecord({ backendPort: 47310, modelsPort: 47210, token: "tok", pid: 4242, version: "0.3.3", startedAt: 0 });
  assert.deepStrictEqual(Object.keys(rec), ["format", "backend", "model_server", "token", "pid", "version", "started_at"]);
  assert.strictEqual(rec.backend, "http://127.0.0.1:47310");
  assert.strictEqual(rec.model_server, "http://127.0.0.1:47210");
  E.writeDiscovery(f, rec);
  E.writeDiscovery(f, rec);   // rewriting (a restart) works
  assert.deepStrictEqual(E.readDiscovery(f), rec);
  if (process.platform !== "win32") assert.strictEqual(fs.statSync(f).mode & 0o777, 0o600);
  assert.deepStrictEqual(fs.readdirSync(dir), ["engine.json"]);   // no temp file left behind
  assert.strictEqual(E.removeDiscovery(f, 1), false);           // another instance's: kept
  assert.ok(fs.existsSync(f));
  assert.strictEqual(E.removeDiscovery(f, 4242), true);
  assert.ok(!fs.existsSync(f));
  fs.rmSync(dir, { recursive: true });
});

test("RestartPolicy: exponential back-off, capped, gives up after N fast crashes", () => {
  const p = new E.RestartPolicy({ baseMs: 1000, capMs: 8000, maxRestarts: 5, stableMs: 60000 });
  const delays = [];
  let t = 0;
  for (let i = 0; i < 5; i++) { const r = p.crashed(t += 100); assert.strictEqual(r.action, "restart"); delays.push(r.delayMs); }
  assert.deepStrictEqual(delays, [1000, 2000, 4000, 8000, 8000]);
  assert.strictEqual(p.crashed(t += 100).action, "giveup");
});

test("RestartPolicy: a child that ran healthy for a while starts over at the short delay", () => {
  const p = new E.RestartPolicy({ baseMs: 1000, maxRestarts: 3, stableMs: 60000 });
  p.crashed(0); p.crashed(10); assert.strictEqual(p.crashed(20).delayMs, 4000);
  p.healthy(1000);
  assert.strictEqual(p.crashed(1000 + 61000).delayMs, 1000);   // stable for > 60 s: forgiven
  p.healthy(70000);
  assert.strictEqual(p.crashed(70000 + 5000).delayMs, 2000);   // healthy only 5 s: still counts
});

test("HangWatch: hung after N misses in a row; one answer resets it", () => {
  const h = new E.HangWatch({ strikes: 3 });
  assert.strictEqual(h.miss(), false); assert.strictEqual(h.miss(), false);
  h.ok();
  assert.strictEqual(h.miss(), false); assert.strictEqual(h.miss(), false); assert.strictEqual(h.miss(), true);
});
