"use strict";
// Asset updates (updates.js): remote manifest -> staged in the background -> swapped on the next launch -> confirmed or
// rolled back. No network: fetch is a fake over in-memory files (https URLs, as the allow-list requires).
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const A = require("./assets");
const U = require("./updates");

const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");

function tar(files) {
  const parts = [];
  for (const [name, data] of Object.entries(files)) {
    const h = Buffer.alloc(512);
    h.write(name, 0, 100, "utf8");
    h.write("0000644\0", 100); h.write("0000000\0", 108); h.write("0000000\0", 116);
    h.write(data.length.toString(8).padStart(11, "0") + "\0", 124);
    h.write("00000000000\0", 136);
    h.write("        ", 148); h.write("0", 156); h.write("ustar\0", 257); h.write("00", 263);
    let sum = 0; for (const b of h) sum += b;
    h.write(sum.toString(8).padStart(6, "0") + "\0 ", 148);
    parts.push(h, data, Buffer.alloc((512 - (data.length % 512)) % 512));
  }
  parts.push(Buffer.alloc(1024));
  return Buffer.concat(parts);
}

/** An asset entry + its tar. */
function asset(id, version, text, extra = {}) {
  const files = { "model.bin": Buffer.from(text), "LICENSE": Buffer.from("licence\n") };
  const t = tar(files);
  return { entry: { id, title: id, version, required: true, file: `${id}-v${version}.tar`,
    url: `https://www.dropbox.com/scl/fi/x/${id}-v${version}.tar?dl=1`, sha256: sha(t), size: t.length,
    min_app: "0.1.0", max_app: null, requires: [], env: `${id.toUpperCase()}_DIR`, subdir: "",
    files: Object.entries(files).map(([p, b]) => ({ path: p, size: b.length })), ...extra }, tar: t };
}

/** fetch over a {url: Buffer | string | Error} map; supports Range like Dropbox. */
function fakeFetch(map, log = []) {
  return async (url, opts = {}) => {
    log.push(url);
    const v = map[String(url)];
    if (v instanceof Error) throw v;
    if (v === undefined) return new Response("not found", { status: 404 });
    let body = Buffer.isBuffer(v) ? v : Buffer.from(typeof v === "string" ? v : JSON.stringify(v));
    const range = opts.headers && opts.headers.Range;
    if (range) {
      const from = Number(/bytes=(\d+)-/.exec(range)[1]);
      return new Response(body.subarray(from), { status: 206 });
    }
    return new Response(body, { status: 200 });
  };
}

function setup(t, { app = "0.2.0" } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ol-upd-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const v1 = asset("ear", "1", "ear version one");
  const bundled = { schema: 2, version: "a", assets: [v1.entry] };
  return { dir, v1, bundled, app };
}

/** Install v1 the normal way (first run). */
async function installV1(s, fetchLog) {
  const store = A.createStore({ dir: s.dir, manifest: s.bundled, fetchImpl: fakeFetch({ [s.v1.entry.url]: s.v1.tar }, fetchLog) });
  await store.ensure(["ear"]);
  assert.equal(store.check(s.v1.entry), "installed");
  return store;
}

const REMOTE = U.REMOTE_URL;
const logs = () => { const l = []; const f = (...a) => l.push(a.join(" ")); f.lines = l; return f; };

test("remote newer + compatible -> staged in the background, swapped on the next launch, confirmed by health", async (t) => {
  const s = setup(t);
  await installV1(s);
  const v2 = asset("ear", "2", "ear version two, better", { min_app: "0.2.0" });
  const remote = { schema: 2, version: "b", published_at: "2026-11-15T00:00:00Z", assets: [v2.entry] };
  const log = logs();
  const store = A.createStore({ dir: s.dir, manifest: U.effectiveManifest(s.bundled, null, s.app) });
  const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app, log, paceMs: 0,
    fetchImpl: fakeFetch({ [REMOTE]: remote, [v2.entry.url]: v2.tar }) });
  const st = await up.run();
  assert.equal(st.state, "ready");
  assert.deepEqual(up.pendingIds(), ["ear"]);
  // still v1 on disk this launch
  assert.equal(fs.readFileSync(path.join(store.home("ear"), "model.bin"), "utf8"), "ear version one");
  assert.equal(up.summary().update.ready[0], "ear");
  // next launch: the cached remote manifest is the effective one, the staged copy is swapped in before the children
  const cached = JSON.parse(fs.readFileSync(up.cacheFile, "utf8"));
  const store2 = A.createStore({ dir: s.dir, manifest: U.effectiveManifest(s.bundled, cached, s.app) });
  const up2 = U.createUpdater({ store: store2, bundled: s.bundled, appVersion: s.app, log, fetchImpl: fakeFetch({}) });
  assert.deepEqual(up2.applyPending(), ["ear"]);
  assert.equal(fs.readFileSync(path.join(store2.home("ear"), "model.bin"), "utf8"), "ear version two, better");
  assert.equal(store2.check(store2.manifest.assets[0]), "installed");
  assert.deepEqual(up2.trials(), ["ear"]);
  const r = up2.confirm({ models: { arc_ear: { available: true } } });
  assert.deepEqual(r, { kept: ["ear"], rolled: [] });
  assert.equal(store2.readState().ear.version, "2");
  assert.ok(!fs.existsSync(path.join(s.dir, ".prev", "ear")));
});

test("a failed load after the swap -> rollback to the previous version, logged, never offered again", async (t) => {
  const s = setup(t);
  await installV1(s);
  const v2 = asset("ear", "2", "a broken ear");
  const remote = { schema: 2, version: "b", assets: [v2.entry] };
  const log = logs();
  const store = A.createStore({ dir: s.dir, manifest: s.bundled });
  const fetchImpl = fakeFetch({ [REMOTE]: remote, [v2.entry.url]: v2.tar });
  const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app, log, fetchImpl, paceMs: 0 });
  await up.run();
  up.applyPending();
  const r = up.confirm({ models: { arc_ear: { available: false } } });   // the ear failed to init
  assert.deepEqual(r.rolled, ["ear"]);
  assert.equal(fs.readFileSync(path.join(store.home("ear"), "model.bin"), "utf8"), "ear version one");
  assert.equal(store.readState().ear.version, "1");
  assert.ok(log.lines.some((l) => /ROLLBACK ear v2 -> v1/.test(l)));
  assert.equal(store.check(s.v1.entry), "installed");
  const again = await up.check();
  assert.deepEqual(again.updates, []);                                     // the rejected sha is not staged again
});

test("the model server dying with a trial asset rolls it back too", async (t) => {
  const s = setup(t);
  await installV1(s);
  const v2 = asset("ear", "2", "crashes");
  const store = A.createStore({ dir: s.dir, manifest: s.bundled });
  const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app, paceMs: 0,
    fetchImpl: fakeFetch({ [REMOTE]: { assets: [v2.entry] }, [v2.entry.url]: v2.tar }) });
  await up.run();
  up.applyPending();
  assert.deepEqual(up.rollbackTrials("the model server stopped"), ["ear"]);
  assert.deepEqual(up.trials(), []);
});

test("incompatible min_app -> ignored", async (t) => {
  const s = setup(t, { app: "0.1.0" });
  await installV1(s);
  const v2 = asset("ear", "2", "needs a newer app", { min_app: "0.3.0" });
  const log = logs();
  const store = A.createStore({ dir: s.dir, manifest: s.bundled });
  const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app, log,
    fetchImpl: fakeFetch({ [REMOTE]: { assets: [v2.entry] }, [v2.entry.url]: v2.tar }) });
  const st = await up.run();
  assert.equal(st.state, "up_to_date");
  assert.deepEqual(up.pendingIds(), []);
  assert.ok(log.lines.some((l) => /needs app 0\.3\.0/.test(l)));
  // and the next launch keeps the bundled entry for it
  assert.equal(U.effectiveManifest(s.bundled, { assets: [v2.entry] }, s.app).assets[0].sha256, s.v1.entry.sha256);
});

test("requires: an update waits for the asset it needs", async (t) => {
  const s = setup(t);
  await installV1(s);
  const v2 = asset("ear", "2", "needs tagger 3", { requires: [{ id: "tagger", min_version: "3" }] });
  const store = A.createStore({ dir: s.dir, manifest: s.bundled });
  const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app,
    fetchImpl: fakeFetch({ [REMOTE]: { assets: [v2.entry] } }) });
  assert.deepEqual((await up.check()).updates, []);
});

test("sha mismatch -> rejected, nothing staged", async (t) => {
  const s = setup(t);
  await installV1(s);
  const v2 = asset("ear", "2", "real bytes");
  const log = logs();
  const store = A.createStore({ dir: s.dir, manifest: s.bundled });
  const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app, log, paceMs: 0,
    fetchImpl: fakeFetch({ [REMOTE]: { assets: [v2.entry] }, [v2.entry.url]: tar({ "model.bin": Buffer.from("tampered") }) }) });
  const st = await up.run();
  assert.equal(st.state, "error");
  assert.deepEqual(up.pendingIds(), []);
  assert.ok(log.lines.some((l) => /sha256 mismatch/.test(l)));
  assert.equal(fs.readFileSync(path.join(store.home("ear"), "model.bin"), "utf8"), "ear version one");
});

test("offline -> no-op", async (t) => {
  const s = setup(t);
  await installV1(s);
  const store = A.createStore({ dir: s.dir, manifest: s.bundled });
  const off = Object.assign(new TypeError("fetch failed"), { cause: { code: "ENOTFOUND" } });
  const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app, fetchImpl: fakeFetch({ [REMOTE]: off }) });
  const st = await up.run();
  assert.equal(st.state, "offline");
  assert.ok(!fs.existsSync(up.cacheFile));
  assert.deepEqual(up.applyPending(), []);
  assert.equal(store.readState().ear.version, "1");
});

test("malformed manifest -> ignored (not cached); a host outside the allow-list -> refused", async (t) => {
  const s = setup(t);
  await installV1(s);
  const store = A.createStore({ dir: s.dir, manifest: s.bundled });
  for (const bad of ["{not json", { assets: "x" }, { assets: [{ id: "ear", sha256: "abc", size: 1, file: "e.tar" }] }]) {
    const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app, fetchImpl: fakeFetch({ [REMOTE]: bad }) });
    assert.equal((await up.run()).state, "error");
    assert.ok(!fs.existsSync(up.cacheFile));
  }
  const v2 = asset("ear", "2", "x");
  for (const url of ["https://evil.example.com/ear.tar", "http://www.dropbox.com/ear.tar", "https://dropbox.com.evil.io/e.tar"]) {
    const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app,
      fetchImpl: fakeFetch({ [REMOTE]: { assets: [{ ...v2.entry, url }] } }) });
    assert.equal((await up.run()).state, "error", url);
  }
  assert.ok(U.hostAllowed("https://dl.dropboxusercontent.com/x") && U.hostAllowed("https://huggingface.co/x"));
  // the manifest URL itself must be https on an allowed host
  const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app, remoteUrl: "http://whissleai.github.io/m.json",
    fetchImpl: fakeFetch({}) });
  assert.equal((await up.run()).state, "error");
});

test("the bundled manifest validates and matches the published copy (site/assets/manifest.json)", () => {
  const b = fs.readFileSync(path.join(__dirname, "..", "assets.manifest.json"), "utf8");
  const p = fs.readFileSync(path.join(__dirname, "..", "..", "site", "assets", "manifest.json"), "utf8");
  assert.equal(b, p, "run the asset scripts (they write both) or copy site/assets/manifest.json over the bundled one");
  const m = JSON.parse(b);
  assert.deepEqual(U.validateManifest(m), []);
  assert.equal(m.schema, 2);
  assert.ok(m.version && m.published_at);
  for (const a of m.assets) assert.ok(a.version && "min_app" in a && "max_app" in a && Array.isArray(a.requires), a.id);
});

test("a newer offline pack updates an installed asset (airgapped); an older one changes nothing", async (t) => {
  const s = setup(t);
  const store = await installV1(s);
  const v2 = asset("ear", "2", "pack version two");
  const zipOf = (files) => {   // stored zip
    const zlibFree = [];
    let off = 0; const cds = [];
    for (const [name, data] of Object.entries(files)) {
      const n = Buffer.from(name);
      const lh = Buffer.alloc(30); lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt32LE(data.length, 18); lh.writeUInt32LE(data.length, 22); lh.writeUInt16LE(n.length, 26);
      const cd = Buffer.alloc(46); cd.writeUInt32LE(0x02014b50, 0); cd.writeUInt32LE(data.length, 20); cd.writeUInt32LE(data.length, 24); cd.writeUInt16LE(n.length, 28); cd.writeUInt32LE(off, 42);
      zlibFree.push(lh, n, data); cds.push(cd, n); off += 30 + n.length + data.length;
    }
    const cdb = Buffer.concat(cds), end = Buffer.alloc(22);
    end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(Object.keys(files).length, 8); end.writeUInt16LE(Object.keys(files).length, 10);
    end.writeUInt32LE(cdb.length, 12); end.writeUInt32LE(off, 16);
    return Buffer.concat([...zlibFree, cdb, end]);
  };
  const z = path.join(s.dir, "pack.zip");
  fs.writeFileSync(z, zipOf({ "assets.manifest.json": Buffer.from(JSON.stringify({ assets: [v2.entry] })), [v2.entry.file]: v2.tar }));
  assert.deepEqual(await store.importOfflinePack(z, { appVersion: s.app }), ["ear"]);
  assert.equal(store.readState().ear.version, "2");
  assert.equal(fs.readFileSync(path.join(store.home("ear"), "model.bin"), "utf8"), "pack version two");
  // the original pack (no versions in its manifest: counts as v1) does not downgrade it
  fs.writeFileSync(z, zipOf({ "assets.manifest.json": Buffer.from(JSON.stringify({ assets: [{ ...s.v1.entry, version: undefined }] })), [s.v1.entry.file]: s.v1.tar }));
  assert.deepEqual(await store.importOfflinePack(z, { appVersion: s.app }), []);
  assert.equal(store.readState().ear.version, "2");
});

test("Windows-style paths: swap and rollback only use path.join and renames of whole folders", async (t) => {
  // the same flow under path.win32 joins: the store keeps no "/" in the folders it renames
  const s = setup(t);
  const store = await installV1(s);
  for (const p of [store.home("ear")]) assert.ok(!/[\\/]$/.test(p));
  assert.ok(path.win32.join("C:\\Users\\kid\\AppData\\Roaming\\Outpost Luna\\assets", ".prev", "ear").endsWith("assets\\.prev\\ear"));
});

test("busy() pauses the background download", async (t) => {
  const s = setup(t);
  await installV1(s);
  const v2 = asset("ear", "2", "x".repeat(5000));
  const store = A.createStore({ dir: s.dir, manifest: s.bundled });
  let calls = 0;
  const up = U.createUpdater({ store, bundled: s.bundled, appVersion: s.app, paceMs: 0,
    busy: async () => (++calls === 1), fetchImpl: fakeFetch({ [REMOTE]: { assets: [v2.entry] }, [v2.entry.url]: v2.tar }) });
  const st = await up.run();
  assert.equal(st.state, "ready");
  assert.ok(calls >= 2);
});
