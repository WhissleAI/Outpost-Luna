// First-run assets (docs/DESKTOP.md "First run: assets"). No Electron imports: unit-tested with node --test.
//
// The installer ships code only. Every model, the voice pack, the crew audio and the pinned NASA videos are ASSETS
// listed in assets.manifest.json (scripts/asset_pack.py): one ustar .tar each, sha256-pinned, at a public link. They are
// installed into <userData>/assets/<id>/ (OUTPOST_ASSETS_DIR overrides) and recorded in <userData>/assets/state.json.
//
//   createStore({ dir, manifest })   .status()  cheap size check of every asset -> installed | missing | corrupt
//                                     .download(asset, { onProgress, signal })   resume (.part + Range), sha256, install
//                                     .ensure(ids, ...)   download what is not installed, in order
//                                     .importOfflinePack(zip, ...)   the offline zip (asset tars + manifest), no network
//   extractTar, readZipEntries, isNetworkError, freeBytes   helpers (exported for the tests)
//
// Install is atomic: extract into .staging/<id>, check every file's size against the manifest, then rename over
// <id>/ (the old copy is moved aside first and removed after). A crash at any point leaves either the old install or
// no install, never a half one; the .part download survives and resumes on the next launch.
"use strict";
const fs = require("fs");
const fsp = require("fs/promises");
const path = require("path");
const crypto = require("crypto");
const zlib = require("zlib");
const { pipeline } = require("stream/promises");
const { Transform } = require("stream");

const REQUIRED_IDS = ["ear", "tagger", "embedder", "voice"];
const UA = "OutpostLuna-desktop (first-run assets)";
const NET_CODES = new Set(["ENOTFOUND", "EAI_AGAIN", "ECONNREFUSED", "ECONNRESET", "ENETUNREACH", "EHOSTUNREACH",
  "ETIMEDOUT", "UND_ERR_CONNECT_TIMEOUT", "UND_ERR_SOCKET", "UND_ERR_HEADERS_TIMEOUT", "UND_ERR_BODY_TIMEOUT"]);

/** Rename with retries: on Windows an antivirus scan or the search indexer can hold a just-written file for a moment
 * (EPERM / EBUSY / EACCES); the same rename succeeds a few hundred ms later. POSIX renames succeed or fail at once. */
const RETRY_CODES = new Set(["EPERM", "EBUSY", "EACCES", "ENOTEMPTY"]);
function sleepSync(ms) { Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms); }
function renameRetrySync(a, b, tries = 8) {
  for (let i = 0; ; i++) {
    try { return fs.renameSync(a, b); } catch (e) {
      if (!RETRY_CODES.has(e.code) || i >= tries - 1) throw e;
      sleepSync(100 * (i + 1));
    }
  }
}
async function renameRetry(a, b, tries = 8) {
  for (let i = 0; ; i++) {
    try { return await fsp.rename(a, b); } catch (e) {
      if (!RETRY_CODES.has(e.code) || i >= tries - 1) throw e;
      await new Promise((r) => setTimeout(r, 100 * (i + 1)));
    }
  }
}

function loadManifest(file) {
  const m = JSON.parse(fs.readFileSync(file, "utf8"));
  if (!m || !Array.isArray(m.assets)) throw new Error(`bad asset manifest: ${file}`);
  return m;
}

/** <userData>/assets, or OUTPOST_ASSETS_DIR. */
function assetsDir(userData, env = process.env) {
  return env.OUTPOST_ASSETS_DIR || path.join(userData, "assets");
}

/** Bytes free on the volume holding dir (its nearest existing parent); null when unknown. */
function freeBytes(dir) {
  let d = dir;
  while (d && !fs.existsSync(d)) { const up = path.dirname(d); if (up === d) break; d = up; }
  try { const s = fs.statfsSync(d); return Number(s.bavail) * Number(s.bsize); } catch { return null; }
}

/** A fetch failure that means "no network" (not a bad link or a server error). */
function isNetworkError(e) {
  if (!e) return false;
  if (e.offline) return true;
  for (let x = e, i = 0; x && i < 4; x = x.cause, i++) {
    if (NET_CODES.has(x.code) || NET_CODES.has(x.errno)) return true;
  }
  return e.name === "TypeError" && /fetch failed/i.test(String(e.message));
}

async function sha256File(p) {
  const h = crypto.createHash("sha256");
  await pipeline(fs.createReadStream(p), new Transform({ transform(c, _e, cb) { h.update(c); cb(); } }));
  return h.digest("hex");
}

function safeRel(name) {
  const n = String(name).replace(/\\/g, "/");
  if (!n || n.startsWith("/") || /^[A-Za-z]:/.test(n) || n.split("/").some((s) => s === ".." )) throw new Error(`unsafe path in archive: ${name}`);
  return n.split("/").filter((s) => s && s !== ".").join("/");
}

function octal(buf, a, b) {
  const s = buf.toString("ascii", a, b).replace(/\0.*$/, "").trim();
  return s ? parseInt(s, 8) : 0;
}

/** Extract a ustar archive (regular files + directories; anything else is skipped) into dest. -> [{path, size}]
 *  map(name) -> the path to write it at, or null to skip that member (a fallback that takes a few files of a bigger tar). */
async function extractTar(tarPath, dest, map = null) {
  const fh = await fsp.open(tarPath, "r");
  const out = [];
  try {
    const hdr = Buffer.alloc(512);
    let pos = 0;
    const buf = Buffer.alloc(1 << 20);
    for (;;) {
      const { bytesRead } = await fh.read(hdr, 0, 512, pos);
      if (bytesRead < 512 || hdr.every((b) => b === 0)) break;
      pos += 512;
      const name = hdr.toString("utf8", 0, 100).replace(/\0.*$/s, "");
      const prefix = hdr.toString("utf8", 345, 500).replace(/\0.*$/s, "");
      const size = octal(hdr, 124, 136);
      const type = String.fromCharCode(hdr[156] || 48);
      const full = prefix ? `${prefix}/${name}` : name;
      const mapped = map ? map(safeRel(full)) : safeRel(full);
      if ((type === "0" || type === "\0") && mapped) {
        const rel = safeRel(mapped);
        const to = path.join(dest, ...rel.split("/"));
        await fsp.mkdir(path.dirname(to), { recursive: true });
        const w = await fsp.open(to, "w");
        try {
          let left = size, at = pos;
          while (left > 0) {
            const n = Math.min(left, buf.length);
            const { bytesRead: r } = await fh.read(buf, 0, n, at);
            if (r <= 0) throw new Error(`truncated archive at ${rel}`);
            await w.write(buf, 0, r);
            left -= r; at += r;
          }
        } finally { await w.close(); }
        out.push({ path: rel, size });
      } else if (type === "5" && !map) {
        await fsp.mkdir(path.join(dest, ...safeRel(full).split("/")), { recursive: true });
      }
      pos += Math.ceil(size / 512) * 512;
    }
  } finally { await fh.close(); }
  return out;
}

/** Central directory of a zip (zip64 aware) -> [{name, method, compSize, size, dataStart}] */
async function readZipEntries(zipPath) {
  const fh = await fsp.open(zipPath, "r");
  try {
    const { size: fileSize } = await fh.stat();
    const tailLen = Math.min(fileSize, 65557);
    const tail = Buffer.alloc(tailLen);
    await fh.read(tail, 0, tailLen, fileSize - tailLen);
    let e = -1;
    for (let i = tailLen - 22; i >= 0; i--) if (tail.readUInt32LE(i) === 0x06054b50) { e = i; break; }
    if (e < 0) throw new Error("not a zip file (no end of central directory)");
    let count = tail.readUInt16LE(e + 10), cdSize = tail.readUInt32LE(e + 12), cdOff = tail.readUInt32LE(e + 16);
    if (e >= 20 && tail.readUInt32LE(e - 20) === 0x07064b50) {   // zip64 locator -> zip64 end record
      const recOff = Number(tail.readBigUInt64LE(e - 20 + 8));
      const rec = Buffer.alloc(56);
      await fh.read(rec, 0, 56, recOff);
      if (rec.readUInt32LE(0) === 0x06064b50) {
        count = Number(rec.readBigUInt64LE(32)); cdSize = Number(rec.readBigUInt64LE(40)); cdOff = Number(rec.readBigUInt64LE(48));
      }
    }
    const cd = Buffer.alloc(cdSize);
    await fh.read(cd, 0, cdSize, cdOff);
    const out = [];
    let p = 0;
    for (let k = 0; k < count; k++) {
      if (cd.readUInt32LE(p) !== 0x02014b50) throw new Error("bad zip central directory");
      const method = cd.readUInt16LE(p + 10);
      let comp = cd.readUInt32LE(p + 20), size = cd.readUInt32LE(p + 24);
      const nl = cd.readUInt16LE(p + 28), xl = cd.readUInt16LE(p + 30), cl = cd.readUInt16LE(p + 32);
      let local = cd.readUInt32LE(p + 42);
      const name = cd.toString("utf8", p + 46, p + 46 + nl);
      let x = p + 46 + nl;
      const xend = x + xl;
      while (x + 4 <= xend) {
        const id = cd.readUInt16LE(x), len = cd.readUInt16LE(x + 2);
        if (id === 0x0001) {
          let q = x + 4;
          if (size === 0xffffffff) { size = Number(cd.readBigUInt64LE(q)); q += 8; }
          if (comp === 0xffffffff) { comp = Number(cd.readBigUInt64LE(q)); q += 8; }
          if (local === 0xffffffff) { local = Number(cd.readBigUInt64LE(q)); q += 8; }
        }
        x += 4 + len;
      }
      const lh = Buffer.alloc(30);
      await fh.read(lh, 0, 30, local);
      if (lh.readUInt32LE(0) !== 0x04034b50) throw new Error(`bad zip local header: ${name}`);
      out.push({ name, method, compSize: comp, size, dataStart: local + 30 + lh.readUInt16LE(26) + lh.readUInt16LE(28) });
      p += 46 + nl + xl + cl;
    }
    return out;
  } finally { await fh.close(); }
}

const sleep = (ms, signal) => new Promise((res, rej) => {
  const t = setTimeout(res, ms);
  if (signal) signal.addEventListener("abort", () => { clearTimeout(t); rej(abortError()); }, { once: true });
});
function abortError() { const e = new Error("cancelled"); e.name = "AbortError"; return e; }

/**
 * Download url into part (resuming what is there). Returns the file's size. Throws on HTTP errors (e.status) and
 * network errors (isNetworkError). onBytes(n) after each chunk with the total so far.
 */
async function downloadTo(url, part, { size, signal, onBytes, pace, fetchImpl = globalThis.fetch } = {}) {
  await fsp.mkdir(path.dirname(part), { recursive: true });
  let have = 0;
  try { have = (await fsp.stat(part)).size; } catch { /* none */ }
  if (size && have > size) { await fsp.rm(part, { force: true }); have = 0; }
  if (size && have === size) { onBytes && onBytes(have); return have; }
  const headers = { "User-Agent": UA };
  if (have) headers.Range = `bytes=${have}-`;
  const r = await fetchImpl(url, { headers, signal, redirect: "follow" });
  let mode = "w";
  if (r.status === 206 && have) mode = "a";
  else if (r.status === 416 && have) { onBytes && onBytes(have); return have; }
  else if (r.status !== 200) { const e = new Error(`HTTP ${r.status}`); e.status = r.status; throw e; }
  else have = 0;
  const w = fs.createWriteStream(part, { flags: mode });
  let n = have;
  try {
    for await (const chunk of r.body) {
      if (signal && signal.aborted) throw abortError();
      if (!w.write(chunk)) await new Promise((res) => w.once("drain", res));
      n += chunk.length;
      onBytes && onBytes(n);
      if (pace) await pace();          // background updates: a rest per chunk, a pause while the app is busy
    }
  } catch (e) {
    if (e.name !== "AbortError") e.midstream = true;   // the link works; the connection dropped: resume, don't give up
    throw e;
  } finally { await new Promise((res) => w.end(res)); }
  return n;
}

function createStore({ dir, manifest, log = () => {}, fetchImpl = globalThis.fetch, retries = 3, backoffMs = 2000 }) {
  const statePath = path.join(dir, "state.json");
  const dl = path.join(dir, ".dl");
  const byId = Object.fromEntries(manifest.assets.map((a) => [a.id, a]));

  function readState() { try { return JSON.parse(fs.readFileSync(statePath, "utf8")); } catch { return {}; } }
  function writeState(s) {
    fs.mkdirSync(dir, { recursive: true });
    const tmp = statePath + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(s, null, 1));
    renameRetrySync(tmp, statePath);
  }
  const home = (id) => path.join(dir, id);

  /**
   * installed | missing | corrupt | outdated (cheap: state + every file's size, no hashing). An installed asset may be
   * another version than the manifest's (an update swapped in, updates.js): its own file list (state) is checked.
   * outdated: older than this build's min_version for it, replaced like a missing one: a required asset on the first-run
   * screen, an optional one (videos) in the background once the UI is up (main.js fetchOptional). The old copy stays in
   * place and in use until the new one is verified and swapped in (commit); a failed download leaves it as it was.
   */
  function check(a) {
    const st = readState()[a.id];
    if (!st || !fs.existsSync(home(a.id))) return "missing";
    const files = st.files || (st.sha256 === a.sha256 ? a.files : null);
    if (!files) return "corrupt";   // an old state record of another version, without its file list: replace it
    if (a.min_version && cmpVersion(st.version || "1", a.min_version) < 0) return "outdated";
    for (const f of files) {
      try { if (fs.statSync(path.join(home(a.id), ...f.path.split("/"))).size !== f.size) return "corrupt"; }
      catch { return "corrupt"; }
    }
    return "installed";
  }

  function status() {
    return manifest.assets.map((a) => ({ id: a.id, title: a.title, required: !!a.required, size: a.size, state: check(a) }));
  }

  /** Move a filled staging folder into place: atomic rename, the old copy moved aside first. */
  async function commit(a, staging) {
    for (const f of a.files || []) {
      const st = await fsp.stat(path.join(staging, ...f.path.split("/"))).catch(() => null);
      if (!st || st.size !== f.size) throw new Error(`${a.id}: ${f.path} missing or wrong size after unpacking`);
    }
    const dst = home(a.id), old = path.join(dir, `.old-${a.id}`);
    await fsp.rm(old, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    if (fs.existsSync(dst)) await renameRetry(dst, old);
    await renameRetry(staging, dst);
    await fsp.rm(old, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    const s = readState();
    s[a.id] = { version: String(a.version || "1"), sha256: a.sha256, size: a.size, files: a.files || [],
      installed_at: new Date().toISOString() };
    writeState(s);
    fs.rmSync(path.join(dir, ".prev", a.id), { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });   // a repair supersedes any rollback copy
  }

  async function installTar(a, tar) {
    const staging = path.join(dir, ".staging", a.id);
    await fsp.rm(staging, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    await fsp.mkdir(staging, { recursive: true });
    await extractTar(tar, staging);
    await commit(a, staging);
    await fsp.rm(tar, { force: true });
  }

  async function withRetry(what, fn, signal) {
    let last;
    for (let i = 0; i < retries; i++) {
      try { return await fn(); }
      catch (e) {
        last = e;
        if (e.name === "AbortError" || (isNetworkError(e) && !e.midstream)) throw e;   // offline: say so now (Try again)
        if (e.status && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429) throw e;
        log(`assets: ${what} failed (${e.message}); retry ${i + 1}/${retries - 1}`);
        if (i < retries - 1) await sleep(backoffMs * 2 ** i, signal);
      }
    }
    throw last;
  }

  async function fromTar(a, { onProgress, signal }) {
    const part = path.join(dl, a.file + ".part");
    await withRetry(a.id, async () => {
      await downloadTo(a.url, part, { size: a.size, signal, fetchImpl,
        onBytes: (n) => onProgress && onProgress({ id: a.id, phase: "download", done: n, total: a.size }) });
      onProgress && onProgress({ id: a.id, phase: "verify", done: a.size, total: a.size });
      const got = await sha256File(part);
      if (got !== a.sha256) {
        await fsp.rm(part, { force: true });   // damaged or replaced: start over
        throw new Error(`${a.id}: sha256 mismatch`);
      }
    }, signal);
    onProgress && onProgress({ id: a.id, phase: "install", done: a.size, total: a.size });
    await installTar(a, part);
  }

  /** The asset's own files straight from their source (the ear: Hugging Face at the pinned revision). */
  async function fromFiles(a, { onProgress, signal }) {
    const fb = a.fallback;
    const base = path.join(dl, a.id);
    const total = fb.files.reduce((s, f) => s + f.size, 0);
    let before = 0;
    for (const f of fb.files) {
      const rel = safeRel(f.path);
      const part = path.join(base, ...rel.split("/")) + ".part";
      const done = path.join(base, ...rel.split("/"));
      if (fs.existsSync(done) && fs.statSync(done).size === f.size) { before += f.size; continue; }
      await withRetry(`${a.id}/${rel}`, async () => {
        await downloadTo(fb.base + rel.split("/").map(encodeURIComponent).join("/"), part, { size: f.size, signal, fetchImpl,
          onBytes: (n) => onProgress && onProgress({ id: a.id, phase: "download", done: before + n, total }) });
        if (f.sha256 && (await sha256File(part)) !== f.sha256) { await fsp.rm(part, { force: true }); throw new Error(`${rel}: sha256 mismatch`); }
      }, signal);
      await renameRetry(part, done);
      before += f.size;
    }
    onProgress && onProgress({ id: a.id, phase: "install", done: total, total });
    const staging = path.join(dir, ".staging", a.id);
    await fsp.rm(staging, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    await fsp.mkdir(path.dirname(staging), { recursive: true });
    await renameRetry(base, staging);
    await commit(a, staging);
  }

  /** A fallback that takes this asset's files out of a bigger published tar (the Steer voice: the v1 model package,
   *  models/steer-tts-edge/...): download it (resume + its own sha256), extract only the listed members, check each
   *  member's sha256, add the small inline files (licence / notice), then install as usual. */
  async function fromTarMembers(a, { onProgress, signal }) {
    const fb = a.fallback;
    const part = path.join(dl, fb.file + ".part");
    await withRetry(`${a.id} (fallback)`, async () => {
      await downloadTo(fb.url, part, { size: fb.size, signal, fetchImpl,
        onBytes: (n) => onProgress && onProgress({ id: a.id, phase: "download", done: n, total: fb.size }) });
      if (fb.sha256 && (await sha256File(part)) !== fb.sha256) { await fsp.rm(part, { force: true }); throw new Error(`${a.id}: fallback sha256 mismatch`); }
    }, signal);
    onProgress && onProgress({ id: a.id, phase: "install", done: fb.size, total: fb.size });
    const want = new Map(fb.members.map((m) => [safeRel(m.from), m]));
    const staging = path.join(dir, ".staging", a.id);
    await fsp.rm(staging, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    await fsp.mkdir(staging, { recursive: true });
    await extractTar(part, staging, (name) => (want.has(name) ? want.get(name).path : null));
    for (const m of fb.members) {
      const f = path.join(staging, ...safeRel(m.path).split("/"));
      if (!fs.existsSync(f) || (m.sha256 && (await sha256File(f)) !== m.sha256)) throw new Error(`${a.id}: ${m.path} missing or damaged in the fallback tar`);
    }
    for (const t of fb.inline || []) {
      const f = path.join(staging, ...safeRel(t.path).split("/"));
      await fsp.mkdir(path.dirname(f), { recursive: true });
      await fsp.writeFile(f, t.text, "utf8");
    }
    await commit(a, staging);
    await fsp.rm(part, { force: true });
  }

  // On-demand: anything (the backend, when the kid picks the Steer voice) asks for an optional asset by creating
  // <assets>/.want/<id>; the main process polls wanted() and downloads it at once. <assets>/.active/<id> exists while
  // an asset downloads, so the backend can show "Downloading Steer voice…".
  const flag = (kind, id) => path.join(dir, kind, id);
  function want(id) { fs.mkdirSync(path.join(dir, ".want"), { recursive: true }); fs.writeFileSync(flag(".want", id), ""); }
  function wanted() {
    try { return fs.readdirSync(path.join(dir, ".want")).filter((id) => byId[id] && check(byId[id]) !== "installed"); }
    catch { return []; }
  }

  const inflight = new Map();   // id -> its running download (the background loop and an on-demand ask share it)
  function download(a, opts = {}) {
    if (typeof a === "string") a = byId[a];
    if (!inflight.has(a.id)) inflight.set(a.id, downloadTracked(a, opts).finally(() => inflight.delete(a.id)));
    return inflight.get(a.id);
  }

  async function downloadTracked(a, opts) {
    fs.mkdirSync(path.join(dir, ".active"), { recursive: true });
    fs.writeFileSync(flag(".active", a.id), "");
    try { return await downloadOne(a, opts); }
    finally {
      fs.rmSync(flag(".active", a.id), { force: true });
      if (check(a) === "installed") fs.rmSync(flag(".want", a.id), { force: true });
    }
  }

  async function downloadOne(a, opts = {}) {
    const need = (a.size || 0) + (a.unpacked_size || a.size || 0);
    const free = freeBytes(dir);
    if (free !== null && free < need) {
      const e = new Error(`not enough disk space for ${a.title}: need ${Math.ceil(need / 1e6)} MB, ${Math.floor(free / 1e6)} MB free`);
      e.disk = true;
      throw e;
    }
    if (a.url) {
      try { return await fromTar(a, opts); }
      catch (e) {
        if (e.name === "AbortError" || isNetworkError(e) || !a.fallback) throw e;
        log(`assets: ${a.id} from its link failed (${e.message}); using the fallback source`);
      }
    }
    if (a.fallback && a.fallback.kind === "files") return fromFiles(a, opts);
    if (a.fallback && a.fallback.kind === "tar_members") return fromTarMembers(a, opts);
    throw new Error(`${a.id}: no download link yet (import the offline pack)`);
  }

  /** Download every asset of ids that is not installed (in manifest order). -> the ids done. */
  async function ensure(ids, opts = {}) {
    const done = [];
    for (const a of manifest.assets) {
      if (!ids.includes(a.id) || check(a) === "installed") continue;
      await download(a, opts);
      done.push(a.id);
    }
    return done;
  }

  /** The offline pack's own manifest (assets.manifest.json inside the zip), or null. */
  async function packManifest(zipPath, entries) {
    const e = entries.find((x) => path.posix.basename(x.name) === "assets.manifest.json");
    if (!e || e.compSize > 8 << 20) return null;
    const chunks = [];
    const src = fs.createReadStream(zipPath, { start: e.dataStart, end: e.dataStart + e.compSize - 1 });
    for await (const c of e.method === 8 ? src.pipe(zlib.createInflateRaw()) : src) chunks.push(c);
    try { const m = JSON.parse(Buffer.concat(chunks).toString("utf8")); return m && Array.isArray(m.assets) ? m : null; }
    catch { return null; }
  }

  /**
   * The offline pack: a zip holding asset tars + its manifest (matched by file name + sha256). Installs what is
   * missing, and replaces an installed asset when the pack's version is newer and fits this app (opts.appVersion):
   * so a newer pack updates an airgapped install. A pack without versions (v2 as first published) counts as "1".
   * -> ids installed.
   */
  async function importOfflinePack(zipPath, { onProgress, signal, appVersion = null } = {}) {
    const entries = await readZipEntries(zipPath);
    const inner = await packManifest(zipPath, entries);
    const innerBy = Object.fromEntries(((inner && inner.assets) || []).map((x) => [x.id, x]));
    const got = [];
    for (const base of manifest.assets) {
      const pk = innerBy[base.id];
      // the pack's entry (its version, files) when it has one; env / subdir always from this build's manifest
      const a = pk && /^[0-9a-f]{64}$/.test(String(pk.sha256)) ? { ...pk, env: base.env, subdir: base.subdir } : base;
      const e = entries.find((x) => path.posix.basename(x.name) === a.file);
      if (!e) continue;
      const st = readState()[a.id];
      const state = check(base);
      const newer = st && cmpVersion(a.version || "1", st.version || "1") > 0 && st.sha256 !== a.sha256 &&
        (!appVersion || ((!a.min_app || cmpVersion(appVersion, a.min_app) >= 0) && (!a.max_app || cmpVersion(appVersion, a.max_app) <= 0)));
      if (state === "installed" && !newer) continue;
      if (signal && signal.aborted) throw abortError();
      const part = path.join(dl, a.file + ".import");
      await fsp.mkdir(dl, { recursive: true });
      onProgress && onProgress({ id: a.id, phase: "import", done: 0, total: a.size });
      const src = fs.createReadStream(zipPath, { start: e.dataStart, end: e.dataStart + e.compSize - 1 });
      const h = crypto.createHash("sha256");
      let n = 0;
      const tap = new Transform({ transform(c, _e, cb) { h.update(c); n += c.length; onProgress && onProgress({ id: a.id, phase: "import", done: n, total: a.size }); cb(null, c); } });
      const stages = e.method === 8 ? [src, zlib.createInflateRaw(), tap] : e.method === 0 ? [src, tap] : null;
      if (!stages) throw new Error(`${a.file}: unsupported zip compression ${e.method}`);
      await pipeline(...stages, fs.createWriteStream(part), signal ? { signal } : {});
      if (h.digest("hex") !== a.sha256) { await fsp.rm(part, { force: true }); throw new Error(`${a.file} in the offline pack is damaged (sha256)`); }
      onProgress && onProgress({ id: a.id, phase: "install", done: a.size, total: a.size });
      await installTar(a, part);
      got.push(a.id);
    }
    return got;
  }

  /** Env paths for the children: { ARC_SPACE_DIR: <assets>/ear/nft2, ... } for every asset with an `env`. */
  function envPaths() {
    const out = {};
    for (const a of manifest.assets) if (a.env) out[a.env] = a.subdir ? path.join(home(a.id), a.subdir) : home(a.id);
    return out;
  }

  return { dir, manifest, check, status, download, ensure, importOfflinePack, envPaths, home, readState, writeState, want, wanted };
}

/** "1.10" vs "1.9": numeric dotted compare (updates.js has the same rule). */
function cmpVersion(a, b) {
  const p = (v) => String(v == null ? "0" : v).trim().replace(/^v/i, "").split(/[-+]/)[0].split(".").map((x) => parseInt(x, 10) || 0);
  const x = p(a), y = p(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) { const d = (x[i] || 0) - (y[i] || 0); if (d) return d > 0 ? 1 : -1; }
  return 0;
}

/** Remove every downloaded asset (the per-user assets folder: installs, .part downloads, staged updates, rollback
 * copies, the cached remote manifest). Settings -> "Reset everything" (another branch: /api/reset?level=all + userData
 * deletion) calls this with the children STOPPED (Windows file locks); the next launch is a first run again.
 * TODO(reset-everything): wire main.js's reset handler to clearAll(store.dir) once both branches are merged. */
function clearAll(dir) {
  if (!dir || !fs.existsSync(dir)) return 0;
  let n = 0;
  for (const e of fs.readdirSync(dir)) { fs.rmSync(path.join(dir, e), { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); n++; }
  return n;
}

function requiredBytes(manifest) {
  return manifest.assets.filter((a) => a.required).reduce((s, a) => s + a.size, 0);
}

module.exports = { REQUIRED_IDS, renameRetry, renameRetrySync, clearAll, loadManifest, assetsDir, createStore, extractTar, readZipEntries, downloadTo,
  isNetworkError, freeBytes, sha256File, requiredBytes, safeRel, cmpVersion };
