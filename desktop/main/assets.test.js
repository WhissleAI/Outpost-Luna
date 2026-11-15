"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const crypto = require("crypto");
const zlib = require("zlib");
const A = require("./assets");

const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");

/** A tiny ustar archive of {path: Buffer}. */
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

/** A zip of {name: Buffer}; method 0 (stored) or 8 (deflate). */
function zip(files, method = 0) {
  const locals = [], cds = [];
  let off = 0;
  for (const [name, data] of Object.entries(files)) {
    const body = method === 8 ? zlib.deflateRawSync(data) : data;
    const n = Buffer.from(name);
    const lh = Buffer.alloc(30);
    lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt16LE(method, 8);
    lh.writeUInt32LE(body.length, 18); lh.writeUInt32LE(data.length, 22); lh.writeUInt16LE(n.length, 26);
    const cd = Buffer.alloc(46);
    cd.writeUInt32LE(0x02014b50, 0); cd.writeUInt16LE(20, 6); cd.writeUInt16LE(method, 10);
    cd.writeUInt32LE(body.length, 20); cd.writeUInt32LE(data.length, 24); cd.writeUInt16LE(n.length, 28);
    cd.writeUInt32LE(off, 42);
    locals.push(lh, n, body); cds.push(cd, n);
    off += 30 + n.length + body.length;
  }
  const cdBuf = Buffer.concat(cds);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(Object.keys(files).length, 8); end.writeUInt16LE(Object.keys(files).length, 10);
  end.writeUInt32LE(cdBuf.length, 12); end.writeUInt32LE(off, 16);
  return Buffer.concat([...locals, cdBuf, end]);
}

function fixture() {
  const files = { "LICENSE": Buffer.from("licence text\n"), "nft2/config.json": Buffer.from('{"a":1}'),
    "nft2/big.bin": crypto.randomBytes(70000) };
  const t = tar(files);
  const asset = { id: "ear", title: "Ear", required: true, file: "x-ear.tar", sha256: sha(t), size: t.length,
    unpacked_size: 70100, env: "ARC_SPACE_DIR", subdir: "nft2",
    files: Object.entries(files).map(([p, b]) => ({ path: p, size: b.length })) };
  return { files, tarBuf: t, asset };
}

/** HTTP server with Range; `cut` drops the first full response after that many bytes (to test resume). */
function serve(routes, { cut = 0 } = {}) {
  const hits = [];
  let cutLeft = cut;
  const srv = http.createServer((req, res) => {
    const body = routes[req.url.split("?")[0]];
    hits.push({ url: req.url, range: req.headers.range || null });
    if (!body) { res.writeHead(404); return res.end(); }
    const m = /bytes=(\d+)-/.exec(req.headers.range || "");
    if (m) {
      const a = Number(m[1]);
      if (a >= body.length) { res.writeHead(416); return res.end(); }
      res.writeHead(206, { "Content-Length": body.length - a, "Content-Range": `bytes ${a}-${body.length - 1}/${body.length}` });
      return res.end(body.subarray(a));
    }
    res.writeHead(200, { "Content-Length": body.length });
    if (cutLeft) { const n = cutLeft; cutLeft = 0; res.write(body.subarray(0, n)); return setTimeout(() => res.destroy(), 20); }
    res.end(body);
  });
  return new Promise((r) => srv.listen(0, "127.0.0.1", () => r({ srv, hits, base: `http://127.0.0.1:${srv.address().port}` })));
}

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "ol-assets-"));

test("extractTar writes files and rejects unsafe paths", async () => {
  const d = tmp();
  const { tarBuf, files } = fixture();
  fs.writeFileSync(path.join(d, "a.tar"), tarBuf);
  const got = await A.extractTar(path.join(d, "a.tar"), path.join(d, "out"));
  assert.equal(got.length, 3);
  assert.deepEqual(fs.readFileSync(path.join(d, "out/nft2/big.bin")), files["nft2/big.bin"]);
  fs.writeFileSync(path.join(d, "bad.tar"), tar({ "../evil": Buffer.from("x") }));
  await assert.rejects(A.extractTar(path.join(d, "bad.tar"), path.join(d, "out2")), /unsafe/);
});

test("download resumes after a dropped connection, verifies sha256, installs atomically", async () => {
  const { tarBuf, asset, files } = fixture();
  const { srv, hits, base } = await serve({ "/ear.tar": tarBuf }, { cut: 30000 });
  try {
    const dir = tmp();
    const a = { ...asset, url: base + "/ear.tar" };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1 });
    assert.equal(store.check(a), "missing");
    const seen = [];
    await store.download(a, { onProgress: (p) => seen.push(p.phase) });
    assert.equal(store.check(a), "installed");
    assert.ok(hits.some((h) => h.range === "bytes=30000-"), "second request resumed with Range");
    assert.deepEqual(fs.readFileSync(path.join(dir, "ear/nft2/big.bin")), files["nft2/big.bin"]);
    assert.ok(seen.includes("verify") && seen.includes("install"));
    assert.ok(!fs.existsSync(path.join(dir, ".dl", a.file + ".part")), "the tar is removed after install");
    assert.equal(store.envPaths().ARC_SPACE_DIR, path.join(dir, "ear", "nft2"));
    // corrupt one file: the size check notices, a repair download fixes it
    fs.writeFileSync(path.join(dir, "ear/nft2/config.json"), "broken!!!");
    assert.equal(store.check(a), "corrupt");
    await store.ensure(["ear"]);
    assert.equal(store.check(a), "installed");
  } finally { srv.close(); }
});

test("a sha256 mismatch never installs; the fallback file source is used", async () => {
  const { tarBuf, asset, files } = fixture();
  const routes = { "/ear.tar": Buffer.from(tarBuf).fill(1, 600, 700) };
  for (const [p, b] of Object.entries(files)) routes["/hf/" + p] = b;
  const { srv, base } = await serve(routes);
  try {
    const dir = tmp();
    const logs = [];
    const a = { ...asset, url: base + "/ear.tar",
      fallback: { kind: "files", base: base + "/hf/", files: Object.entries(files).map(([p, b]) => ({ path: p, size: b.length, sha256: sha(b) })) } };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1, retries: 2, log: (m) => logs.push(m) });
    await store.download(a);
    assert.equal(store.check(a), "installed");
    assert.ok(logs.some((l) => /fallback/.test(l)));
    assert.deepEqual(fs.readFileSync(path.join(dir, "ear/LICENSE")), files.LICENSE);
  } finally { srv.close(); }
});

test("no network -> isNetworkError (the first-run screen shows the offline message)", async () => {
  const { asset } = fixture();
  const dir = tmp();
  const a = { ...asset, url: "http://127.0.0.1:1/ear.tar" };
  const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1, retries: 1 });
  await assert.rejects(store.download(a), (e) => A.isNetworkError(e));
  assert.equal(A.isNetworkError(new Error("HTTP 500")), false);
});

test("cancel aborts and keeps the .part for later", async () => {
  const { tarBuf, asset } = fixture();
  const { srv, base } = await serve({ "/ear.tar": tarBuf }, { cut: 20000 });
  try {
    const dir = tmp();
    const a = { ...asset, url: base + "/ear.tar" };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 5000 });
    const ac = new AbortController();
    const p = store.download(a, { signal: ac.signal });
    setTimeout(() => ac.abort(), 200);
    await assert.rejects(p, (e) => e.name === "AbortError");
    assert.equal(fs.statSync(path.join(dir, ".dl", a.file + ".part")).size, 20000);
  } finally { srv.close(); }
});

test("importOfflinePack installs from a stored or deflated zip, checks sha256", async () => {
  for (const method of [0, 8]) {
    const { tarBuf, asset } = fixture();
    const other = tar({ "trim.json": Buffer.from("{}") });
    const crew = { id: "crew", title: "Crew", required: false, file: "x-crew.tar", sha256: sha(other), size: other.length,
      files: [{ path: "trim.json", size: 2 }] };
    const d = tmp();
    const z = path.join(d, "pack.zip");
    fs.writeFileSync(z, zip({ "assets.manifest.json": Buffer.from("{}"), "x-ear.tar": tarBuf, "x-crew.tar": other }, method));
    const ents = await A.readZipEntries(z);
    assert.equal(ents.length, 3);
    const store = A.createStore({ dir: path.join(d, "assets"), manifest: { assets: [asset, crew] } });
    const got = await store.importOfflinePack(z);
    assert.deepEqual(got, ["ear", "crew"]);
    assert.deepEqual(store.status().map((s) => s.state), ["installed", "installed"]);
    // a damaged pack is refused
    const bad = { ...asset, sha256: "0".repeat(64) };
    const s2 = A.createStore({ dir: path.join(d, "assets2"), manifest: { assets: [bad] } });
    await assert.rejects(s2.importOfflinePack(z), /damaged/);
    assert.equal(s2.check(bad), "missing");
  }
});

test("the bundled manifest lists the required assets with sizes and sha256s", () => {
  const m = A.loadManifest(path.join(__dirname, "..", "assets.manifest.json"));
  for (const id of A.REQUIRED_IDS) {
    const a = m.assets.find((x) => x.id === id);
    assert.ok(a && a.required && /^[0-9a-f]{64}$/.test(a.sha256) && a.size > 0 && a.files.length, id);
  }
  const ear = m.assets.find((x) => x.id === "ear");
  assert.ok(ear.licence.includes("LICENSE") && ear.licence.includes("NOTICE"));
  assert.ok(ear.files.some((f) => f.path === "LICENSE") && ear.files.some((f) => f.path === "NOTICE"));
  assert.equal(ear.fallback.kind, "files");
  assert.ok(A.requiredBytes(m) > 400e6);
});
