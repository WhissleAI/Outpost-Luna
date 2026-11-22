"use strict";
// playtest.js: the "Export playtest" hand-over (the URL the page navigates to, the file name, writing the zip).
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const P = require("./playtest");

const ORIGIN = "http://127.0.0.1:47310";
const ZIP = Buffer.concat([Buffer.from([0x50, 0x4b, 0x03, 0x04]), Buffer.alloc(40)]);

test("only the page's own export URL is taken over", () => {
  assert.ok(P.isExportUrl(`${ORIGIN}/__outpost/playtest-export`, ORIGIN));
  assert.ok(!P.isExportUrl(`http://evil.example/__outpost/playtest-export`, ORIGIN));
  assert.ok(!P.isExportUrl(`${ORIGIN}/__outpost/diagnostics`, ORIGIN));
  assert.ok(!P.isExportUrl("not a url", ORIGIN));
});

test("the default file name is dated, a zip", () => {
  assert.match(P.defaultName(Date.UTC(2026, 10, 19, 12)), /^outpost-luna-playtest-2026-11-1\d\.zip$/);
});

test("the zip from the backend is written where the grown-up chose, with the token and the app version", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luna-pt-"));
  const file = path.join(dir, "out.zip");
  let seen = null;
  const fetchFn = async (url, opt) => { seen = { url, opt }; return { ok: true, arrayBuffer: async () => ZIP } };
  const n = await P.saveExport({ backend: ORIGIN, token: "t0k", appVersion: "0.4.3", file, fetchFn });
  assert.strictEqual(n, ZIP.length);
  assert.ok(fs.readFileSync(file).equals(ZIP));
  assert.ok(!fs.existsSync(file + ".part"));
  assert.strictEqual(seen.url, `${ORIGIN}/api/playtest/export`);
  assert.strictEqual(seen.opt.headers["X-Luna-Token"], "t0k");
  assert.deepStrictEqual(JSON.parse(seen.opt.body), { app_version: "0.4.3" });
});

test("a backend error or a body that is not a zip writes nothing", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luna-pt-"));
  const file = path.join(dir, "out.zip");
  await assert.rejects(P.saveExport({ backend: ORIGIN, token: "", appVersion: "x", file, fetchFn: async () => ({ ok: false, status: 401 }) }));
  await assert.rejects(P.saveExport({ backend: ORIGIN, token: "", appVersion: "x", file, fetchFn: async () => ({ ok: true, arrayBuffer: async () => Buffer.from("nope, not a zip at all....") }) }));
  assert.ok(!fs.existsSync(file));
});

test("Help improve Outpost Luna: its own export URL, file name and backend route; nothing else is fetched", async () => {
  assert.ok(P.isCollectUrl(`${ORIGIN}/__outpost/collect-export`, ORIGIN));
  assert.ok(!P.isCollectUrl(`${ORIGIN}/__outpost/playtest-export`, ORIGIN));
  assert.ok(!P.isExportUrl(`${ORIGIN}/__outpost/collect-export`, ORIGIN), "the playtest handler does not take it");
  assert.ok(!P.isCollectUrl(`http://evil.example/__outpost/collect-export`, ORIGIN));
  assert.match(P.defaultName(Date.UTC(2026, 10, 22, 12), "collect"), /^outpost-luna-help-2026-11-2\d\.zip$/);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luna-col-"));
  const file = path.join(dir, "help.zip");
  let seen = null;
  const fetchFn = async (url, opt) => { seen = { url, opt }; return { ok: true, arrayBuffer: async () => ZIP }; };
  await P.saveExport({ backend: ORIGIN, token: "t0k", appVersion: "0.5.8", file, fetchFn, api: "/api/collect/export" });
  assert.strictEqual(seen.url, `${ORIGIN}/api/collect/export`);
  assert.strictEqual(seen.opt.headers["X-Outpost-Reset"], "1", "the backend's collect export needs the page header");
  assert.strictEqual(seen.opt.headers["X-Luna-Token"], "t0k");
  assert.ok(fs.readFileSync(file).equals(ZIP));
  await assert.rejects(P.saveExport({ backend: ORIGIN, token: "", appVersion: "x", file, fetchFn, api: "/api/turnlog" }));
});
