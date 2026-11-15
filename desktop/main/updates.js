// Asset updates without an app build (docs/DESKTOP.md "Asset updates"). No Electron imports: unit-tested with node --test.
//
// The manifest is published from git (site/assets/manifest.json -> scripts/publish_site.sh -> GitHub Pages at
// REMOTE_URL); the app bundles a copy (desktop/assets.manifest.json) as the first-run source and the offline fallback.
//
//   1. launch: applyPending() swaps in what an earlier run staged (atomic renames, BEFORE the children start), keeping
//      the old copy in .prev/<id> and marking the asset "trial"
//   2. children healthy: confirm(health) keeps a trial asset whose load check passed (and drops .prev), or rolls it
//      back (.prev -> <id>, the new sha remembered as rejected, logged); a model server that dies with a trial asset
//      in place rolls back too (rollbackTrials)
//   3. after the UI is up, online: check() fetches the remote manifest (short timeout), validates it and caches it;
//      stageAll() downloads every changed + compatible installed asset in the background (resumable, paced, paused
//      while busy() says a mission or a video is on), verifies its sha256 and unpacks it into .pending/<id>:
//      it is swapped in on the NEXT launch
// Offline: nothing changes. A manifest that fails to parse or validate (https only, allow-listed hosts, sha256 on
// every entry) is ignored as a whole. Signing the manifest (minisign) is future hardening.
//
// Manifest (schema 2): { schema, version, published_at, assets: [entry] }
//   entry: id, title, version, file, url (https, allow-listed; null = not uploaded yet), sha256, size, required,
//          min_app / max_app (the app versions it works with, inclusive; null = no bound), requires ([{id,
//          min_version}]: other assets it needs), min_version (in the BUNDLED manifest: the oldest installed version
//          this app build accepts; older is replaced in the foreground), licence, files [{path, size}], env, subdir,
//          fallback ({kind: "files", base, files: [{path, size, sha256}]} or {kind: "tar_members", url, sha256, size,
//          members: [{from, path, size, sha256}], inline: [{path, text}]}, optional)
"use strict";
const fs = require("fs");
const fsp = require("fs/promises");
const path = require("path");
const AS = require("./assets");

const REMOTE_URL = "https://whissleai.github.io/Outpost-Luna/assets/manifest.json";
const ALLOW_HOSTS = ["dropbox.com", "dropboxusercontent.com", "huggingface.co", "github.com", "github.io",
  "githubusercontent.com"];
const SHA_RE = /^[0-9a-f]{64}$/;
const ID_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;

/** "1.10.2" vs "1.9" (numeric parts; a leading "v" and any "-pre"/"+build" suffix ignored). -1 | 0 | 1 */
const cmpVersion = AS.cmpVersion;

function hostAllowed(url, allow = ALLOW_HOSTS) {
  let u;
  try { u = new URL(url); } catch { return false; }
  if (u.protocol !== "https:") return false;
  const h = u.hostname.toLowerCase();
  return allow.some((d) => h === d || h.endsWith("." + d));
}

/** -> [] when the manifest is usable, else the reasons. Every url must be https on an allow-listed host. */
function validateManifest(m, { allow = ALLOW_HOSTS } = {}) {
  const err = [];
  if (!m || typeof m !== "object" || !Array.isArray(m.assets)) return ["not a manifest (no assets list)"];
  const seen = new Set();
  for (const a of m.assets) {
    const id = a && a.id;
    if (!a || typeof a !== "object" || !ID_RE.test(String(id))) { err.push(`bad id ${JSON.stringify(id)}`); continue; }
    if (seen.has(id)) err.push(`${id}: listed twice`);
    seen.add(id);
    if (!SHA_RE.test(String(a.sha256))) err.push(`${id}: sha256 missing or malformed`);
    if (!(Number.isFinite(a.size) && a.size > 0)) err.push(`${id}: size missing`);
    if (typeof a.file !== "string" || !/^[\w.-]+$/.test(a.file)) err.push(`${id}: bad file name`);
    if (a.url != null && !hostAllowed(a.url, allow)) err.push(`${id}: url not https on an allowed host`);
    if (a.fallback) {
      // kind "files": a base URL + per-file sha256; kind "tar_members": one https tar (sha256) whose listed members are taken
      if (!hostAllowed(a.fallback.base || a.fallback.url, allow)) err.push(`${id}: fallback not https on an allowed host`);
      if (a.fallback.kind === "tar_members" && !SHA_RE.test(a.fallback.sha256 || "")) err.push(`${id}: fallback tar sha256`);
      for (const f of a.fallback.files || []) if (f.sha256 && !SHA_RE.test(f.sha256)) err.push(`${id}: fallback file sha256`);
    }
    for (const f of a.files || []) {
      try { AS.safeRel(f.path); } catch { err.push(`${id}: unsafe file path ${f.path}`); }
    }
    if (a.requires != null && !Array.isArray(a.requires)) err.push(`${id}: requires must be a list`);
  }
  if (m.assets.length === 0) err.push("no assets");
  return err;
}

/** The entry fits this app build (min_app <= app <= max_app). */
function appCompatible(a, appVersion) {
  if (a.min_app && cmpVersion(appVersion, a.min_app) < 0) return false;
  if (a.max_app && cmpVersion(appVersion, a.max_app) > 0) return false;
  return true;
}

/** Its `requires` are met by `versions` ({id: installed or planned version}). */
function requiresMet(a, versions) {
  return (a.requires || []).every((r) => r && versions[r.id] != null && cmpVersion(versions[r.id], r.min_version || "0") >= 0);
}

/**
 * The manifest the app runs with: the bundled one, with each entry replaced by the cached remote's when that one is
 * compatible and not older. env / subdir always come from the bundled entry (a remote manifest never moves paths).
 */
function effectiveManifest(bundled, cached, appVersion) {
  if (!cached || validateManifest(cached).length) return bundled;
  const remote = Object.fromEntries(cached.assets.map((a) => [a.id, a]));
  const assets = bundled.assets.map((b) => {
    const r = remote[b.id];
    if (!r || !appCompatible(r, appVersion) || cmpVersion(r.version || "1", b.version || "1") < 0) return b;
    return { ...r, env: b.env, subdir: b.subdir, min_version: b.min_version, required: b.required };
  });
  return { ...bundled, assets };
}

async function fetchManifest(url, { fetchImpl = globalThis.fetch, timeoutMs = 8000 } = {}) {
  if (!hostAllowed(url)) throw new Error(`manifest url refused: ${url}`);
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const r = await fetchImpl(url, { signal: ac.signal, headers: { "User-Agent": "OutpostLuna-desktop (asset updates)", "Cache-Control": "no-cache" } });
    if (r.status !== 200) { const e = new Error(`manifest HTTP ${r.status}`); e.status = r.status; throw e; }
    const text = await r.text();
    if (text.length > 4 << 20) throw new Error("manifest too large");
    return JSON.parse(text);
  } catch (e) {
    if (e.name === "AbortError") { const x = new Error("manifest fetch timed out"); x.offline = true; throw x; }
    throw e;
  } finally { clearTimeout(t); }
}

/** The health check that proves an asset loaded (model server /health; backend for the media). */
function healthOk(id, health) {
  const m = (health && health.models) || {};
  switch (id) {
    case "ear": return !!(m.arc_ear && m.arc_ear.available);
    case "tagger": return !!(m.arc_tagger && m.arc_tagger.loaded);
    case "embedder": return !!(m.embedder && m.embedder.loaded);
    case "voice": return !!(m.voice_pack && m.voice_pack.clips > 0);
    default: return true;     // media assets: the file sizes were checked when they were swapped in
  }
}

function createUpdater({ store, bundled, appVersion, remoteUrl = REMOTE_URL, log = () => {}, fetchImpl = globalThis.fetch,
  busy = async () => false, timeoutMs = 8000, paceMs = 5 }) {
  const dir = store.dir;
  const pendDir = path.join(dir, ".pending"), prevDir = path.join(dir, ".prev"), dl = path.join(dir, ".dl");
  const cacheFile = path.join(dir, "remote-manifest.json");
  const status = { state: "idle", checked_at: null, manifest_version: null, ready: [], downloading: null, error: null,
    available: [] };

  const readState = () => store.readState();
  const writeState = (s) => store.writeState(s);

  function cached() {
    try { const m = JSON.parse(fs.readFileSync(cacheFile, "utf8")); return validateManifest(m).length ? null : m; }
    catch { return null; }
  }

  function pendingIds() {
    try { return fs.readdirSync(pendDir).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)); } catch { return []; }
  }

  /** What the remote manifest would change: installed assets whose version or sha differ, compatible, not rejected. */
  function plan(remote) {
    const st = readState();
    const rejected = st._rejected || {};
    const versions = Object.fromEntries(Object.entries(st).filter(([k]) => !k.startsWith("_")).map(([k, v]) => [k, v.version || "1"]));
    const out = [];
    for (const r of remote.assets) {
      const cur = st[r.id];
      if (!cur || !store.manifest.assets.some((b) => b.id === r.id)) continue;    // not installed, or unknown to this build
      if (cur.sha256 === r.sha256) continue;
      if (!r.url) continue;                                                      // not uploaded yet
      if ((rejected[r.id] || []).includes(r.sha256)) continue;                   // rolled back once: never again
      if (!appCompatible(r, appVersion)) { log(`assets: update ${r.id} v${r.version} needs app ${r.min_app || "*"}..${r.max_app || "*"}; this is ${appVersion}`); continue; }
      if (cmpVersion(r.version || "1", cur.version || "1") < 0) continue;       // never downgrade
      const pend = path.join(pendDir, r.id + ".json");
      try { if (JSON.parse(fs.readFileSync(pend, "utf8")).sha256 === r.sha256) continue; } catch { /* none */ }
      out.push(r);
    }
    const planned = { ...versions, ...Object.fromEntries(out.map((r) => [r.id, r.version || "1"])) };
    return out.filter((r) => requiresMet(r, planned) || (log(`assets: update ${r.id} waits for ${JSON.stringify(r.requires)}`), false));
  }

  /** Fetch + validate + cache the remote manifest. -> {manifest, updates} or null (offline / refused). */
  async function check() {
    status.state = "checking"; status.error = null;
    let m;
    try { m = await fetchManifest(remoteUrl, { fetchImpl, timeoutMs }); }
    catch (e) {
      status.state = AS.isNetworkError(e) || e.offline ? "offline" : "error";
      status.error = e.message;
      log(`assets: update check: ${status.state} (${e.message})`);
      return null;
    }
    const errs = validateManifest(m);
    if (errs.length) {
      status.state = "error"; status.error = "remote manifest refused";
      log(`assets: remote manifest refused: ${errs.slice(0, 5).join("; ")}`);
      return null;
    }
    await fsp.mkdir(dir, { recursive: true });
    await fsp.writeFile(cacheFile + ".tmp", JSON.stringify(m));
    await fsp.rename(cacheFile + ".tmp", cacheFile);
    const updates = plan(m);
    status.checked_at = new Date().toISOString();
    status.manifest_version = m.version || null;
    status.available = updates.map((r) => r.id);
    status.ready = pendingIds();
    status.state = updates.length ? "available" : status.ready.length ? "ready" : "up_to_date";
    log(`assets: remote manifest ${m.version || "?"}: ${updates.length ? "updates for " + status.available.join(", ") : "nothing new"}`);
    return { manifest: m, updates };
  }

  /** Low priority: a short rest per chunk, a full pause while busy() (a mission runs, a video plays). */
  const pace = (signal) => async () => {
    if (paceMs) await new Promise((r) => setTimeout(r, paceMs));
    while (await busy()) {
      if (signal && signal.aborted) return;
      status.state = "paused";
      await new Promise((r) => setTimeout(r, 2000));
    }
    if (status.state === "paused") status.state = "downloading";
  };

  /** Download, verify and unpack one update into .pending/<id> (swapped in on the next launch). */
  async function stage(r, { signal } = {}) {
    status.state = "downloading"; status.downloading = r.id;
    const part = path.join(dl, r.file + ".update.part");
    await AS.downloadTo(r.url, part, { size: r.size, signal, fetchImpl, pace: pace(signal) });
    const got = await AS.sha256File(part);
    if (got !== r.sha256) {
      await fsp.rm(part, { force: true });
      throw new Error(`${r.id}: update sha256 mismatch (refused)`);
    }
    const tmp = path.join(pendDir, r.id + ".unpack");
    await fsp.rm(tmp, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    await fsp.mkdir(tmp, { recursive: true });
    await AS.extractTar(part, tmp);
    for (const f of r.files || []) {
      const s = await fsp.stat(path.join(tmp, ...f.path.split("/"))).catch(() => null);
      if (!s || s.size !== f.size) throw new Error(`${r.id}: ${f.path} missing or wrong size in the update`);
    }
    const dst = path.join(pendDir, r.id);
    await fsp.rm(dst, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    await fsp.rename(tmp, dst);
    await fsp.writeFile(path.join(pendDir, r.id + ".json"), JSON.stringify(r));
    await fsp.rm(part, { force: true });
    status.downloading = null;
    log(`assets: update ${r.id} v${r.version || "?"} staged (${Math.round(r.size / 1e6)} MB); swapped in on the next launch`);
  }

  /** check() then stage() every update, one at a time. Never throws. */
  async function run({ signal } = {}) {
    try {
      const c = await check();
      if (!c) return status;
      for (const r of c.updates) {
        if (signal && signal.aborted) break;
        try { await stage(r, { signal }); }
        catch (e) { status.error = e.message; log(`assets: update ${r.id} not staged (${e.message})`); }
      }
      status.ready = pendingIds();
      status.downloading = null;
      status.state = status.ready.length ? "ready" : status.error ? "error" : "up_to_date";
    } catch (e) { status.state = "error"; status.error = e.message; log(`assets: update run failed (${e.message})`); }
    return status;
  }

  /** Launch, before the children start: swap every staged update in; the old copy stays in .prev/<id>. -> ids */
  function applyPending() {
    const done = [];
    for (const id of pendingIds()) {
      const metaPath = path.join(pendDir, id + ".json"), src = path.join(pendDir, id);
      try {
        const r = JSON.parse(fs.readFileSync(metaPath, "utf8"));
        if (!fs.existsSync(src) || !appCompatible(r, appVersion)) throw new Error("not applicable");
        const home = store.home(id), prev = path.join(prevDir, id);
        fs.mkdirSync(prevDir, { recursive: true });
        fs.rmSync(prev, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
        if (fs.existsSync(home)) AS.renameRetrySync(home, prev);
        AS.renameRetrySync(src, home);
        const s = readState();
        s[id] = { version: r.version || "1", sha256: r.sha256, size: r.size, files: r.files || [],
          installed_at: new Date().toISOString(), trial: true, prev: s[id] || null };
        writeState(s);
        fs.rmSync(metaPath, { force: true });
        done.push(id);
        log(`assets: swapped in ${id} v${r.version || "?"} (previous kept for rollback)`);
      } catch (e) {
        log(`assets: staged ${id} dropped (${e.message})`);
        fs.rmSync(src, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
        fs.rmSync(metaPath, { force: true });
      }
    }
    return done;
  }

  function trials() { return Object.entries(readState()).filter(([k, v]) => !k.startsWith("_") && v && v.trial).map(([k]) => k); }

  function rollback(id, reason) {
    const s = readState();
    const cur = s[id], prev = path.join(prevDir, id), home = store.home(id);
    if (!cur || !cur.trial) return false;
    if (!fs.existsSync(prev) || !cur.prev) {
      log(`assets: ROLLBACK of ${id} impossible (no previous copy): ${reason}; it will be repaired`);
      delete s[id];
      writeState(s);
      return false;
    }
    const bad = path.join(dir, `.failed-${id}`);
    fs.rmSync(bad, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    if (fs.existsSync(home)) AS.renameRetrySync(home, bad);
    AS.renameRetrySync(prev, home);
    fs.rmSync(bad, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    s._rejected = s._rejected || {};
    s._rejected[id] = [...new Set([...(s._rejected[id] || []), cur.sha256])];
    s[id] = cur.prev;
    writeState(s);
    log(`assets: ROLLBACK ${id} v${cur.version} -> v${(cur.prev && cur.prev.version) || "?"} (${reason})`);
    return true;
  }

  /** The children are up: keep each trial asset whose load check passed, roll back the others. -> {kept, rolled} */
  /** The trial assets that failed their load check (nothing changes): main.js stops the children first (Windows keeps
   * open / memory-mapped files locked, so a folder in use cannot be renamed), then calls confirm(). */
  function failing(health) { return trials().filter((id) => !healthOk(id, health)); }

  function confirm(health) {
    const kept = [], rolled = [];
    for (const id of trials()) {
      if (healthOk(id, health)) {
        const s = readState();
        delete s[id].trial; delete s[id].prev;
        writeState(s);
        fs.rmSync(path.join(prevDir, id), { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
        kept.push(id);
        log(`assets: update ${id} v${s[id].version} confirmed`);
      } else if (rollback(id, "failed its load check")) rolled.push(id);
    }
    return { kept, rolled };
  }

  /** The model server died with trial assets in place: roll them all back. -> ids */
  function rollbackTrials(reason) { return trials().filter((id) => rollback(id, reason)); }

  /** For Settings -> About / Storage (written to ASSETS_STATE_FILE for the backend's GET /api/assets). */
  function summary() {
    const st = readState();
    const installed = store.manifest.assets.map((a) => {
      const s = st[a.id];
      let bytes = 0;
      for (const f of (s && s.files) || []) bytes += f.size;
      return { id: a.id, title: a.title, required: !!a.required, version: s ? s.version || "1" : null,
        installed: !!s, bytes: s ? bytes || s.size || 0 : 0, update_ready: pendingIds().includes(a.id) };
    });
    return { managed: true, app_version: appVersion, remote: remoteUrl, installed,
      total_bytes: installed.reduce((n, x) => n + x.bytes, 0),
      update: { ...status, ready: pendingIds() } };
  }

  return { check, plan, stage, run, applyPending, confirm, failing, rollback, rollbackTrials, trials, summary, cached, status,
    pendingIds, cacheFile };
}

module.exports = { REMOTE_URL, ALLOW_HOSTS, cmpVersion, hostAllowed, validateManifest, appCompatible, requiresMet,
  effectiveManifest, fetchManifest, healthOk, createUpdater };
