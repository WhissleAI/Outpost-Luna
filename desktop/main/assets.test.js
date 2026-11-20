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
    if (typeof body === "number") { res.writeHead(body); return res.end("<html>outage</html>"); }   // a status only (503)
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
  // 0.4.3: the lighter ear (fp16 parts) falls back to the previous published pack, which falls back to Hugging Face
  const fb = ear.fallback.kind === "pack" ? ear.fallback.fallback : ear.fallback;
  assert.equal(fb.kind, "files");
  assert.ok(A.requiredBytes(m) > 400e6);
});

test("Windows: a rename held by an antivirus scan (EPERM) is retried; clearAll empties the assets folder", async () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "assets-win-"));
  fs.mkdirSync(path.join(d, "a"));
  const real = fs.promises.rename;
  let n = 0;
  fs.promises.rename = async (a, b) => { if (++n < 3) { const e = new Error("busy"); e.code = "EPERM"; throw e; } return real(a, b); };
  try { await A.renameRetry(path.join(d, "a"), path.join(d, "b")); } finally { fs.promises.rename = real; }
  assert.equal(n, 3);
  assert.ok(fs.existsSync(path.join(d, "b")));
  fs.writeFileSync(path.join(d, "state.json"), "{}");
  assert.equal(A.clearAll(d), 2);
  assert.deepEqual(fs.readdirSync(d), []);
  fs.rmSync(d, { recursive: true, force: true });
});

test("steer: the fallback takes its files out of a bigger tar (the v1 model package) and adds its licence", async () => {
  const model = { "steer-tts-edge/config.json": Buffer.from('{"v":1}'), "steer-tts-edge/onnx/enc.onnx": crypto.randomBytes(9000) };
  const big = tar({ "models/arctag/x.onnx": crypto.randomBytes(5000), "models/steer-tts-edge/config.json": model["steer-tts-edge/config.json"],
    "models/steer-tts-edge/onnx/enc.onnx": model["steer-tts-edge/onnx/enc.onnx"] });
  const lic = "SteerTTS licence\n";
  const files = [...Object.entries(model).map(([p, b]) => ({ path: p, size: b.length })), { path: "LICENSE", size: lic.length }];
  const { srv, base } = await serve({ "/v1.tar": big });
  try {
    const dir = tmp();
    const a = { id: "steer", title: "Steer voice", required: false, file: "s.tar", url: null, sha256: "0".repeat(64), size: 1,
      env: "STEER_TTS_MODEL", subdir: "steer-tts-edge", files,
      fallback: { kind: "tar_members", url: base + "/v1.tar", file: "v1.tar", size: big.length, sha256: sha(big),
        members: Object.entries(model).map(([p, b]) => ({ from: `models/${p}`, path: p, size: b.length, sha256: sha(b) })),
        inline: [{ path: "LICENSE", text: lic }] } };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1 });
    await store.download("steer");
    assert.deepEqual(fs.readFileSync(path.join(dir, "steer/steer-tts-edge/onnx/enc.onnx")), model["steer-tts-edge/onnx/enc.onnx"]);
    assert.equal(fs.readFileSync(path.join(dir, "steer/LICENSE"), "utf8"), lic);
    assert.ok(!fs.existsSync(path.join(dir, "steer/models")));      // only the listed members
    assert.equal(store.envPaths().STEER_TTS_MODEL, path.join(dir, "steer", "steer-tts-edge"));
  } finally { srv.close(); }
});

test("steer: an on-demand ask (.want/<id>) is listed until installed; .active marks a running download", async () => {
  const { tarBuf, asset } = fixture();
  const { srv, base } = await serve({ "/s.tar": tarBuf });
  try {
    const dir = tmp();
    const a = { ...asset, id: "steer", required: false, url: base + "/s.tar" };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1 });
    assert.deepEqual(store.wanted(), []);
    store.want("steer");                                            // what the backend does when the kid picks Steer
    assert.deepEqual(store.wanted(), ["steer"]);
    const p1 = store.download("steer"), p2 = store.download("steer");
    assert.equal(p1, p2);                                           // the background loop and the ask share one download
    assert.ok(fs.existsSync(path.join(dir, ".active/steer")));
    await p1;
    assert.ok(!fs.existsSync(path.join(dir, ".active/steer")) && !fs.existsSync(path.join(dir, ".want/steer")));
    assert.deepEqual(store.wanted(), []);
  } finally { srv.close(); }
});

test("courses: a running download writes '<done> <total>' bytes into .active/<id> (the first-run pick shows it)", async () => {
  const { tarBuf, asset } = fixture();
  const { srv, base } = await serve({ "/c.tar": tarBuf });
  try {
    const dir = tmp();
    const a = { ...asset, id: "course_testland", required: false, on_demand: true, url: base + "/c.tar" };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1 });
    const seen = [], calls = [];
    const orig = fs.writeFileSync;
    fs.writeFileSync = function (f, d, ...r) { if (String(f).endsWith(path.join(".active", "course_testland"))) seen.push(String(d)); return orig.call(this, f, d, ...r); };
    try { await store.download("course_testland", { onProgress: (p) => calls.push(p.phase) }); }
    finally { fs.writeFileSync = orig; }
    assert.equal(seen[0], "");                                       // the flag first, then bytes
    const last = seen[seen.length - 1].split(" ").map(Number);
    assert.ok(seen.length >= 2 && last[1] > 0 && last[0] === last[1], seen.join("|"));
    assert.ok(calls.includes("download"));                           // the caller's own onProgress still runs
    assert.ok(!fs.existsSync(path.join(dir, ".active/course_testland")));
  } finally { srv.close(); }
});

test("videos v1 installed, the 0.3.11 manifest wants v2: outdated, fetched after the UI is up, the old pack kept on failure", async () => {
  const U = require("./updates");
  const m = A.loadManifest(path.join(__dirname, "..", "assets.manifest.json"));
  const vid = m.assets.find((x) => x.id === "videos");
  assert.equal(vid.min_version, "2");
  assert.equal(vid.required, false);                       // never a first-run (blocking) asset
  // an install of the old 8-video pack: state v1 with its own file list
  const dir = tmp();
  const old = { "a.mp4": Buffer.from("old video one"), "b.mp4": Buffer.from("old video two") };
  fs.mkdirSync(path.join(dir, "videos"), { recursive: true });
  for (const [p, b] of Object.entries(old)) fs.writeFileSync(path.join(dir, "videos", p), b);
  fs.writeFileSync(path.join(dir, "state.json"), JSON.stringify({ videos: { version: "1", sha256: "0".repeat(64),
    files: Object.entries(old).map(([p, b]) => ({ path: p, size: b.length })) } }));
  const { srv, base } = await serve({});                  // the v2 pack is not reachable (404)
  try {
    // neither the new pack nor its fallback (the previous published pack) is reachable
    const a = { ...vid, url: base + "/videos.tar", mirrors: [], fallback: vid.fallback && { ...vid.fallback, url: base + "/prev.tar" } };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1 });
    assert.equal(store.check(a), "outdated");
    const needs = U.setupNeeds(store.status(), { assets: [a] });
    assert.deepEqual(needs, { required: [], optional: ["videos"] });   // background (fetchOptional), not the first-run screen
    await assert.rejects(store.ensure(["videos"]));
    for (const [p, b] of Object.entries(old)) assert.deepEqual(fs.readFileSync(path.join(dir, "videos", p)), b);
    assert.equal(JSON.parse(fs.readFileSync(path.join(dir, "state.json"), "utf8")).videos.version, "1");
    assert.equal(store.check(a), "outdated");               // tried again next launch; the old videos still play
  } finally { srv.close(); }
});

test("nasa_views (0.4): optional, fetched in the background, never blocks start; a damaged tar never installs", async () => {
  const U = require("./updates");
  const m = A.loadManifest(path.join(__dirname, "..", "assets.manifest.json"));
  const nv = m.assets.find((x) => x.id === "nasa_views");
  assert.ok(nv, "the bundled manifest lists nasa_views");
  assert.equal(nv.required, false);
  assert.ok(!nv.on_demand, "fetched after the UI is up (fetchOptional), not only on demand");
  assert.equal(nv.env, "NASA_VIEWS_DIR");
  assert.ok(A.cmpVersion(nv.min_app, "0.4.0") >= 0, "only 0.4+ apps know how to show it");
  assert.match(nv.sha256, /^[0-9a-f]{64}$/);
  assert.ok(nv.size > 1e6 && nv.size <= 40e6, `pack size ${nv.size}`);
  assert.ok(nv.licence.includes("NOTICE") && nv.files.some((f) => f.path === "NOTICE") && nv.files.some((f) => f.path === "index.json"));
  for (const f of nv.files) assert.match(f.sha256, /^[0-9a-f]{64}$/, f.path);
  assert.ok(!A.REQUIRED_IDS.includes("nasa_views"));
  // a tiny stand-in pack, served: the store installs it and points NASA_VIEWS_DIR at it
  const files = { "index.json": Buffer.from('{"pack":"nasa_views"}'), "NOTICE": Buffer.from("Uses NASA open data; not endorsed by NASA.\n") };
  const t = tar(files);
  const a = { ...nv, url: null, mirrors: [], file: "nv.tar", sha256: sha(t), size: t.length, unpacked_size: 100,
    files: Object.entries(files).map(([p, b]) => ({ path: p, size: b.length })) };
  const dir = tmp();
  const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1, retries: 1 });
  assert.deepEqual(U.setupNeeds(store.status(), { assets: [a] }), { required: [], optional: ["nasa_views"] });
  await assert.rejects(store.ensure(["nasa_views"]), /no download link/);   // not uploaded yet: logged, next launch tries again
  const bad = Buffer.from(t); bad[600] ^= 0xff;
  const { srv, base } = await serve({ "/nv.tar": t, "/bad.tar": bad });
  try {
    await assert.rejects(store.download({ ...a, url: base + "/bad.tar" }), /sha256 mismatch/);
    assert.equal(store.check(a), "missing");
    await store.download({ ...a, url: base + "/nv.tar" });
    assert.equal(store.check(a), "installed");
    assert.equal(store.envPaths().NASA_VIEWS_DIR, path.join(dir, "nasa_views"));
    assert.ok(fs.existsSync(path.join(dir, "nasa_views", "index.json")));
  } finally { srv.close(); }
});

test("main.js hands NASA_VIEWS_DIR to the backend", () => {
  const src = fs.readFileSync(path.join(__dirname, "main.js"), "utf8");
  assert.match(src, /NASA_VIEWS_DIR: a\.NASA_VIEWS_DIR/);
});

// ---- course packs (docs/COURSES.md §4.2): the first assets a grown-up can delete ----
function coursePack() {
  const files = { "course.manifest.json": Buffer.from('{"id":"testland"}'), "lessons.json": Buffer.from("{}"), "media/earth.jpg": crypto.randomBytes(5000) };
  const t = tar(files);
  return { tarBuf: t, asset: { id: "course_testland", title: "Course: Testland", required: false, on_demand: true, file: "x-course.tar",
    sha256: sha(t), size: t.length, unpacked_size: 5100, env: "", subdir: "", files: Object.entries(files).map(([p, b]) => ({ path: p, size: b.length })) } };
}

test("course pack: downloads on demand, then removes cleanly (folder, state record, flags)", async () => {
  const { tarBuf, asset } = coursePack();
  const { srv, base } = await serve({ "/c.tar": tarBuf });
  try {
    const dir = tmp();
    const a = { ...asset, url: base + "/c.tar" };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1 });
    store.want(a.id);
    assert.deepEqual(store.wanted(), ["course_testland"]);
    await store.download(a.id);
    assert.equal(store.check(a), "installed");
    assert.ok(fs.existsSync(path.join(dir, "course_testland/media/earth.jpg")));
    // the backend asks for it to go (and may have moved it aside already)
    fs.mkdirSync(path.join(dir, ".remove"), { recursive: true }); fs.writeFileSync(path.join(dir, ".remove/course_testland"), "");
    assert.deepEqual(store.removals(), ["course_testland"]);
    await store.remove("course_testland");
    assert.equal(store.check(a), "missing");
    assert.ok(!fs.existsSync(path.join(dir, "course_testland")) && !fs.existsSync(path.join(dir, ".old-course_testland")));
    assert.equal(store.readState().course_testland, undefined);
    assert.deepEqual(store.removals(), []);
    // already moved aside by the backend: still cleaned up
    await store.download(a.id);
    fs.renameSync(path.join(dir, "course_testland"), path.join(dir, ".old-course_testland"));
    await store.remove("course_testland");
    assert.ok(!fs.existsSync(path.join(dir, ".old-course_testland")) && store.readState().course_testland === undefined);
  } finally { srv.close(); }
});

test("course pack: built-in assets are never removable; a failure is recorded for the backend", async () => {
  const dir = tmp();
  const { asset } = fixture();
  const store = A.createStore({ dir, manifest: { assets: [asset, coursePack().asset] } });
  assert.equal(store.removable("ear"), false); assert.equal(store.removable("course_testland"), true);
  await assert.rejects(store.remove("ear"), /not a removable asset/);
  fs.mkdirSync(path.join(dir, ".remove"), { recursive: true }); fs.writeFileSync(path.join(dir, ".remove/ear"), "");
  assert.deepEqual(store.removals(), []);
  store.failed("course_testland", "School network mode is on, so nothing downloads.");
  assert.match(fs.readFileSync(path.join(dir, ".failed/course_testland"), "utf8"), /School network/);
});

test("a lighter pack before its upload (url null) or with a broken link installs the previous pack (fallback kind pack)", async () => {
  const U = require("./updates");
  // v1: the shipped pack (its tar, its files); v2: the lighter re-pack, other files
  const { tarBuf: v1tar, asset: v1, files: v1files } = fixture();
  const v2files = { "LICENSE": Buffer.from("licence text\n"), "nft2/config.json": Buffer.from('{"a":2}'),
    "nft2/big.bin": crypto.randomBytes(30000) };
  const v2tar = tar(v2files);
  const { srv, hits, base } = await serve({ "/v1.tar": v1tar, "/v2.tar": Buffer.from(v2tar).fill(7, 600, 700) });
  try {
    const prev = { kind: "pack", version: "1", file: "v1.tar", url: base + "/v1.tar", sha256: v1.sha256, size: v1.size,
      unpacked_size: v1.unpacked_size, files: v1.files.map((f) => ({ ...f, sha256: sha(v1files[f.path]) })) };
    const v2 = { ...v1, version: "2", file: "v2.tar", url: null, sha256: sha(v2tar), size: v2tar.length,
      unpacked_size: 30100, files: Object.entries(v2files).map(([p, b]) => ({ path: p, size: b.length, sha256: sha(b) })),
      fallback: prev };
    assert.deepEqual(U.validateManifest({ assets: [{ ...v2, fallback: { ...prev, url: "https://www.dropbox.com/v1.tar?dl=1" } }] }), []);
    assert.ok(U.validateManifest({ assets: [{ ...v2, fallback: { ...prev, url: "https://evil.example/v1.tar" } }] }).length);
    assert.ok(U.validateManifest({ assets: [{ ...v2, fallback: { ...prev, url: "https://www.dropbox.com/v1.tar", sha256: "x" } }] }).length);
    // 1. not uploaded yet: the previous pack is installed AS v1 (its files in state.json: the model check reads them)
    const dir = tmp(), logs = [];
    const store = A.createStore({ dir, manifest: { assets: [v2] }, backoffMs: 1, retries: 2, log: (m) => logs.push(m) });
    await store.download(v2);
    const st = JSON.parse(fs.readFileSync(path.join(dir, "state.json"), "utf8")).ear;
    assert.equal(st.version, "1");
    assert.equal(st.sha256, v1.sha256);
    assert.deepEqual(st.files.map((f) => f.path).sort(), Object.keys(v1files).sort());
    assert.ok(st.files.every((f) => /^[0-9a-f]{64}$/.test(f.sha256)));
    assert.deepEqual(fs.readFileSync(path.join(dir, "ear/nft2/big.bin")), v1files["nft2/big.bin"]);
    assert.equal(store.check(v2), "installed");                  // no min_version: the previous pack is a full install
    assert.ok(logs.some((l) => /has no link yet; installing v1/.test(l)));
    // 2. uploaded but its link serves a damaged file: refused, then the previous pack
    const dir2 = tmp();
    const v2up = { ...v2, url: base + "/v2.tar" };
    const s2 = A.createStore({ dir: dir2, manifest: { assets: [v2up] }, backoffMs: 1, retries: 2 });
    await s2.download(v2up);
    assert.equal(JSON.parse(fs.readFileSync(path.join(dir2, "state.json"), "utf8")).ear.version, "1");
    assert.ok(hits.some((h) => h.url === "/v2.tar") && hits.some((h) => h.url === "/v1.tar"));
    // 3. the v1 install is offered v2 by the update check once v2 has a link (and never while it has none)
    const fetchImpl = async () => ({ status: 200, text: async () => JSON.stringify({ assets: [{ ...v2, url: "https://www.dropbox.com/v2.tar?dl=1",
      fallback: { ...prev, url: "https://www.dropbox.com/v1.tar?dl=1" } }] }) });
    const up = U.createUpdater({ store, bundled: { assets: [v2] }, appVersion: "0.4.3", fetchImpl });
    const r = await up.check();
    assert.deepEqual(r.updates.map((x) => x.id), ["ear"]);
    const none = U.createUpdater({ store, bundled: { assets: [v2] }, appVersion: "0.4.3",
      fetchImpl: async () => ({ status: 200, text: async () => JSON.stringify({ assets: [{ ...v2, fallback: { ...prev, url: "https://www.dropbox.com/v1.tar?dl=1" } }] }) }) });
    assert.deepEqual((await none.check()).updates, []);
  } finally { srv.close(); }
});

// ---- mirrors (2026-11-20: Dropbox outage, every first-run asset 503'd): url, then each mirror, then the fallback ----

test("mirrors: the primary link 503s -> the first mirror is used, sha256 checked, installed", async () => {
  const { tarBuf, asset, files } = fixture();
  const { srv, hits, base } = await serve({ "/dbx/ear.tar": 503, "/gh/ear.tar": tarBuf });
  try {
    const dir = tmp(), logs = [];
    const a = { ...asset, url: base + "/dbx/ear.tar", mirrors: [base + "/gh/ear.tar"] };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1, retries: 2, log: (m) => logs.push(m) });
    await store.download(a);
    assert.equal(store.check(a), "installed");
    assert.deepEqual(fs.readFileSync(path.join(dir, "ear/nft2/big.bin")), files["nft2/big.bin"]);
    assert.equal(hits.filter((h) => h.url === "/dbx/ear.tar").length, 2, "the primary got its retries first");
    assert.ok(logs.some((l) => /HTTP 503.*trying mirror/.test(l)));
  } finally { srv.close(); }
});

test("mirrors: a .part from a primary that dropped mid-download resumes from the mirror (Range)", async () => {
  const { tarBuf, asset } = fixture();
  let served = false;
  const srvP = http.createServer((req, res) => {   // primary: half the tar once, then 503 for good
    if (!served) { served = true; res.writeHead(200, { "Content-Length": tarBuf.length }); res.write(tarBuf.subarray(0, 40000)); return setTimeout(() => res.destroy(), 20); }
    res.writeHead(503); res.end();
  });
  await new Promise((r) => srvP.listen(0, "127.0.0.1", r));
  const { srv, hits, base } = await serve({ "/gh/ear.tar": tarBuf });
  try {
    const dir = tmp();
    const a = { ...asset, url: `http://127.0.0.1:${srvP.address().port}/ear.tar`, mirrors: [base + "/gh/ear.tar"] };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1, retries: 2 });
    await store.download(a);
    assert.equal(store.check(a), "installed");
    assert.deepEqual(hits.map((h) => h.range), ["bytes=40000-"], "the mirror sent only the rest");
  } finally { srv.close(); srvP.close(); }
});

test("mirrors: a mirror with the wrong bytes is refused -> the next mirror", async () => {
  const { tarBuf, asset } = fixture();
  const { srv, hits, base } = await serve({ "/dbx/ear.tar": 503, "/m1/ear.tar": Buffer.from(tarBuf).fill(9, 600, 700),
    "/m2/ear.tar": tarBuf });
  try {
    const dir = tmp();
    const a = { ...asset, url: base + "/dbx/ear.tar", mirrors: [base + "/m1/ear.tar", base + "/m2/ear.tar"] };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1, retries: 2 });
    await store.download(a);
    assert.equal(store.check(a), "installed");
    assert.ok(hits.some((h) => h.url === "/m1/ear.tar") && hits.some((h) => h.url === "/m2/ear.tar"));
    assert.equal(A.sha256File && (await A.sha256File(path.join(dir, "ear/nft2/big.bin"))).length, 64);
  } finally { srv.close(); }
});

test("mirrors: an unreachable mirror host (DNS / School network block) moves on, not 'offline'", async () => {
  const { tarBuf, asset } = fixture();
  const { srv, base } = await serve({ "/gh/ear.tar": tarBuf });
  try {
    const dir = tmp();
    const a = { ...asset, url: "http://127.0.0.1:1/ear.tar", mirrors: [base + "/gh/ear.tar"] };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1, retries: 2 });
    await store.download(a);
    assert.equal(store.check(a), "installed");
    // every source unreachable: still the offline error (the first-run screen's "no internet" message)
    const b = { ...asset, url: "http://127.0.0.1:1/ear.tar", mirrors: ["http://127.0.0.1:1/gh.tar"] };
    const s2 = A.createStore({ dir: tmp(), manifest: { assets: [b] }, backoffMs: 1, retries: 2 });
    await assert.rejects(s2.download(b), (e) => A.isNetworkError(e));
  } finally { srv.close(); }
});

test("mirrors: every link fails -> the existing fallback kind still runs", async () => {
  const { tarBuf, asset, files } = fixture();
  const routes = { "/dbx/ear.tar": 503, "/gh/ear.tar": 502 };
  for (const [p, b] of Object.entries(files)) routes["/hf/" + p] = b;
  const { srv, hits, base } = await serve(routes);
  try {
    const dir = tmp(), logs = [];
    const a = { ...asset, url: base + "/dbx/ear.tar", mirrors: [base + "/gh/ear.tar"],
      fallback: { kind: "files", base: base + "/hf/", files: Object.entries(files).map(([p, b]) => ({ path: p, size: b.length, sha256: sha(b) })) } };
    const store = A.createStore({ dir, manifest: { assets: [a] }, backoffMs: 1, retries: 2, log: (m) => logs.push(m) });
    await store.download(a);
    assert.equal(store.check(a), "installed");
    assert.ok(hits.some((h) => h.url === "/gh/ear.tar"), "the mirror was tried before the fallback");
    assert.ok(logs.some((l) => /HTTP 502\); using the fallback source/.test(l)), "the fallback says why: the last link's error");
    // the previous-pack fallback (kind pack) carries its own mirrors too
    const prevRoutes = await serve({ "/v1dbx.tar": 503, "/v1gh.tar": tarBuf, "/v2.tar": 503 });
    try {
      const v2 = { ...asset, version: "2", url: prevRoutes.base + "/v2.tar",
        fallback: { kind: "pack", version: "1", file: "v1.tar", url: prevRoutes.base + "/v1dbx.tar", mirrors: [prevRoutes.base + "/v1gh.tar"],
          sha256: asset.sha256, size: asset.size, unpacked_size: asset.unpacked_size, files: asset.files } };
      const s3 = A.createStore({ dir: tmp(), manifest: { assets: [v2] }, backoffMs: 1, retries: 1 });
      await s3.download(v2);
      assert.equal(s3.readState().ear.version, "1");
    } finally { prevRoutes.srv.close(); }
  } finally { srv.close(); }
});

test("mirrors: an entry without mirrors (an old manifest) downloads exactly as before", async () => {
  const { tarBuf, asset } = fixture();
  const { srv, hits, base } = await serve({ "/ear.tar": tarBuf });
  try {
    const a = { ...asset, url: base + "/ear.tar" };
    assert.deepEqual(A.sourcesOf(a), [base + "/ear.tar"]);
    assert.deepEqual(A.sourcesOf({ url: null, mirrors: "x" }), []);
    assert.deepEqual(A.sourcesOf({ url: "u", mirrors: ["u", "m", null] }), ["u", "m"]);
    const store = A.createStore({ dir: tmp(), manifest: { assets: [a] }, backoffMs: 1 });
    await store.download(a);
    assert.equal(store.check(a), "installed");
    assert.deepEqual(hits.map((h) => h.url), ["/ear.tar"]);
    // a 4xx on the only link still fails at once (no fallback, no retries), as before
    const b = { ...asset, url: base + "/gone.tar" };
    await assert.rejects(A.createStore({ dir: tmp(), manifest: { assets: [b] }, backoffMs: 1 }).download(b), /HTTP 404/);
  } finally { srv.close(); }
});

test("mirrors: the manifest check accepts https mirrors on allowed hosts only; updates use them too", async () => {
  const U = require("./updates");
  const { tarBuf, asset } = fixture();
  const e = { ...asset, version: "1", url: "https://www.dropbox.com/x.tar?dl=1" };
  assert.deepEqual(U.validateManifest({ assets: [{ ...e, mirrors: ["https://github.com/WhissleAI/Outpost-Luna/releases/download/assets-v2/x.tar"] }] }), []);
  assert.ok(U.validateManifest({ assets: [{ ...e, mirrors: ["https://evil.example/x.tar"] }] }).length);
  assert.ok(U.validateManifest({ assets: [{ ...e, mirrors: ["http://github.com/x.tar"] }] }).length);
  assert.ok(U.validateManifest({ assets: [{ ...e, mirrors: "https://github.com/x.tar" }] }).length);
  // the bundled manifest: every mirror is a GitHub release download, and the whole manifest validates
  const m = A.loadManifest(path.join(__dirname, "..", "assets.manifest.json"));
  assert.deepEqual(U.validateManifest(m), []);
  for (const a of m.assets) for (const u of a.mirrors || []) {
    assert.match(u, /^https:\/\/github\.com\/WhissleAI\/Outpost-Luna\/releases\/download\/assets-v\d+\//);
    assert.ok(u.endsWith("/" + a.file), `${a.id}: the mirror serves the same file name`);
  }
  for (const id of A.REQUIRED_IDS) assert.ok((m.assets.find((x) => x.id === id).mirrors || []).length, `${id} has a mirror`);
  void tarBuf;
});
