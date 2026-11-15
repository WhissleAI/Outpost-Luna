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

/** Extract a ustar archive (regular files + directories; anything else is skipped) into dest. -> [{path, size}] */
async function extractTar(tarPath, dest) {
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
      if (type === "0" || type === "\0") {
        const rel = safeRel(full);
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
      } else if (type === "5") {
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
async function downloadTo(url, part, { size, signal, onBytes, fetchImpl = globalThis.fetch } = {}) {
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
    fs.renameSync(tmp, statePath);
  }
  const home = (id) => path.join(dir, id);

  /** installed | missing | corrupt (cheap: state + every file's size, no hashing). */
  function check(a) {
    const st = readState()[a.id];
    if (!st || !fs.existsSync(home(a.id))) return "missing";
    if (st.sha256 !== a.sha256) return "corrupt";   // a different version: replace it
    for (const f of a.files || []) {
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
    await fsp.rm(old, { recursive: true, force: true });
    if (fs.existsSync(dst)) await fsp.rename(dst, old);
    await fsp.rename(staging, dst);
    await fsp.rm(old, { recursive: true, force: true });
    const s = readState();
    s[a.id] = { sha256: a.sha256, size: a.size, installed_at: new Date().toISOString() };
    writeState(s);
  }

  async function installTar(a, tar) {
    const staging = path.join(dir, ".staging", a.id);
    await fsp.rm(staging, { recursive: true, force: true });
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
      await fsp.rename(part, done);
      before += f.size;
    }
    onProgress && onProgress({ id: a.id, phase: "install", done: total, total });
    const staging = path.join(dir, ".staging", a.id);
    await fsp.rm(staging, { recursive: true, force: true });
    await fsp.mkdir(path.dirname(staging), { recursive: true });
    await fsp.rename(base, staging);
    await commit(a, staging);
  }

  async function download(a, opts = {}) {
    if (typeof a === "string") a = byId[a];
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

  /** The offline pack: a zip holding the asset tars (matched by file name + sha256). -> ids installed. */
  async function importOfflinePack(zipPath, { onProgress, signal } = {}) {
    const entries = await readZipEntries(zipPath);
    const got = [];
    for (const a of manifest.assets) {
      const e = entries.find((x) => path.posix.basename(x.name) === a.file);
      if (!e || check(a) === "installed") continue;
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

  return { dir, manifest, check, status, download, ensure, importOfflinePack, envPaths, home, readState };
}

function requiredBytes(manifest) {
  return manifest.assets.filter((a) => a.required).reduce((s, a) => s + a.size, 0);
}

module.exports = { REQUIRED_IDS, loadManifest, assetsDir, createStore, extractTar, readZipEntries, downloadTo,
  isNetworkError, freeBytes, sha256File, requiredBytes, safeRel };
