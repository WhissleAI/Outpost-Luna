// Settings -> App version -> "Check for updates" (docs/DESKTOP.md "App updates"). No Electron import: main.js passes
// fetch / platform / the app version in, and appupdate.test.js drives it with fakes.
//
// The app promises no network after setup, so this is a MANUAL check by default: the page asks (it navigates to
// /__outpost/update?do=check, main.js stops that), the main process asks GitHub for the latest release (the page is
// locked to its own origin and could not), compares it with app.getVersion() and hands the result back through
// window.__lunaUpdate. "Download" does NOT need a web browser (a Mac whose default browser is gone just says "The
// application can't be opened" and nothing happens): the main process downloads the installer itself
// (downloadInstaller) into the Downloads folder, checks its size and sha256, reports progress through
// window.__lunaUpdate, then opens it (macOS mounts the dmg) and shows it in the folder. A Windows .exe is only shown in
// its folder, never run. Only https URLs on github.com/WhissleAI/Outpost-Luna (and GitHub's release-asset redirect
// hosts, for this download only) are fetched. Nothing is installed by the app.
// "Release page" / "Open the site" still open the system browser (openWithFallback): when it does not open, the page
// is told and shows the link with a Copy button.
//
// Opt-in: Settings -> "Check for updates automatically" (prefs.update_check, off by default). When on, a launch checks
// at most once per day (the last attempt is kept in <userData>/update-check.json) and stays silent unless a newer
// release exists.
"use strict";
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { once } = require("events");
const { cmpVersion } = require("./assets");

const REPO = "WhissleAI/Outpost-Luna";
const LATEST_URL = `https://api.github.com/repos/${REPO}/releases/latest`;
const RELEASES_URL = `https://github.com/${REPO}/releases/latest`;
const SITE_URL = "https://whissleai.github.io/Outpost-Luna/";
const UPDATE_PATH = "/__outpost/update";
const DAY_MS = 24 * 3600 * 1000;
const TIMEOUT_MS = 8000;
const CONNECT_MS = 20000;      // the installer download: no answer for this long -> offline
const STALL_MS = 60000;        // ... and no bytes for this long once it started
/** Where github.com sends a release-asset download. Fetched only for the installer download, never opened. */
const ASSET_HOSTS = ["objects.githubusercontent.com", "release-assets.githubusercontent.com", "github-releases.githubusercontent.com"];

/** The installer each platform downloads: the stable name first, then the versioned one a release may carry instead. */
const ASSETS = {
  darwin: { label: "Mac", names: ["Outpost-Luna-mac-arm64.dmg"], re: /^Outpost-Luna-\d+\.\d+\.\d+-arm64\.dmg$/ },
  win32: { label: "Windows", names: ["Outpost-Luna-win-x64.exe"], re: /^Outpost[-.]Luna[-.](Setup[-.])?\d+\.\d+\.\d+(-x64)?\.exe$/ },
};
const platformLabel = (p) => (ASSETS[p] && ASSETS[p].label) || "this computer";

/** Only these may be handed to shell.openExternal: https, our repo on github.com, or our site. */
function openAllowed(url) {
  let u;
  try { u = new URL(url); } catch { return false; }
  if (u.protocol !== "https:" || u.username || u.password || u.port) return false;
  const h = u.hostname.toLowerCase();
  if (h === "whissleai.github.io") return u.pathname === "/Outpost-Luna" || u.pathname.startsWith("/Outpost-Luna/");
  if (h === "github.com") return u.pathname.toLowerCase().startsWith(`/${REPO.toLowerCase()}/`);
  return false;
}

/** One of GitHub's release-asset redirect hosts, https, nothing odd in it. */
function assetHostAllowed(url) {
  let u;
  try { u = new URL(url); } catch { return false; }
  return u.protocol === "https:" && !u.username && !u.password && !u.port && ASSET_HOSTS.includes(u.hostname.toLowerCase());
}

/** Release notes -> a short plain-text summary: the "What's new" bullets when there are some, else the first lines. */
function summarize(body, { lines = 3, max = 320 } = {}) {
  const plain = (s) => s.replace(/!\[[^\]]*\]\([^)]*\)/g, "").replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[*_`>#]+/g, "").replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
  const all = String(body || "").split(/\r?\n/);
  const at = all.findIndex((l) => /^#{1,6}\s*what'?s new/i.test(l.trim()));
  let pick;
  if (at >= 0) {
    pick = [];
    for (const l of all.slice(at + 1)) {
      if (/^#{1,6}\s/.test(l.trim())) break;
      if (/^\s*[-*+]\s+/.test(l)) pick.push(plain(l.replace(/^\s*[-*+]\s+/, "")));
    }
  }
  if (!pick || !pick.length) pick = all.filter((l) => l.trim() && !/^#{1,6}\s/.test(l.trim())).map(plain);
  const out = pick.filter(Boolean).slice(0, lines);
  let text = out.join("\n");
  if (text.length > max) text = text.slice(0, max - 1).replace(/\s+\S*$/, "") + "…";
  return text;
}

/** A GitHub release object -> {version, tag, url, notes, assets: [{name, url, size, digest}]}, or null (draft, prerelease, junk). */
function parseRelease(r) {
  if (!r || typeof r !== "object" || r.draft || r.prerelease) return null;
  const tag = String(r.tag_name || "");
  const version = tag.replace(/^v/i, "");
  if (!/^\d+\.\d+\.\d+$/.test(version)) return null;
  const url = openAllowed(r.html_url) ? r.html_url : `https://github.com/${REPO}/releases/tag/${encodeURIComponent(tag)}`;
  const assets = (Array.isArray(r.assets) ? r.assets : [])
    .filter((a) => a && typeof a.name === "string" && openAllowed(a.browser_download_url) && (a.state == null || a.state === "uploaded"))
    .map((a) => ({ name: a.name, url: a.browser_download_url, size: Number.isSafeInteger(a.size) && a.size > 0 ? a.size : null,
      digest: typeof a.digest === "string" && /^sha256:[0-9a-f]{64}$/i.test(a.digest) ? a.digest.slice(7).toLowerCase() : null }));
  return { version, tag, url, notes: summarize(r.body), assets };
}

/** The installer for `platform` in a parsed release, or null (not uploaded yet, or no installer for this OS). */
function pickAsset(rel, platform) {
  const want = ASSETS[platform];
  if (!rel || !want) return null;
  for (const n of want.names) { const a = rel.assets.find((x) => x.name === n); if (a) return a; }
  return rel.assets.find((x) => want.re.test(x.name)) || null;
}

const isInstaller = (name, platform) => !!ASSETS[platform] && (ASSETS[platform].names.includes(name) || ASSETS[platform].re.test(name));
/**
 * The .sha256 file for the installer `a`: "<name>.sha256", else the one beside a same-sized installer for this platform
 * (releases carry Outpost-Luna-<ver>-arm64.dmg.sha256 only; Outpost-Luna-mac-arm64.dmg is a copy of that dmg). Or null.
 */
function pickSha(rel, a, platform) {
  if (!rel || !a) return null;
  const own = rel.assets.find((x) => x.name === a.name + ".sha256");
  if (own) return own;
  return rel.assets.find((x) => {
    if (!x.name.endsWith(".sha256")) return false;
    const base = rel.assets.find((y) => y.name === x.name.slice(0, -7));
    return base && isInstaller(base.name, platform) && base.size && base.size === a.size && (!a.digest || !base.digest || a.digest === base.digest);
  }) || null;
}
/** The first 64-hex word of a .sha256 file ("<hex>  <name>"), lower case; else null. */
function parseShaFile(text) {
  const m = /(?:^|[^0-9a-f])([0-9a-f]{64})(?![0-9a-f])/i.exec(String(text || ""));
  return m ? m[1].toLowerCase() : null;
}

/** The other platforms the release has an installer for ("Mac"), for "0.3.9 is out for Mac; …". */
function otherPlatforms(rel, platform) {
  return Object.keys(ASSETS).filter((p) => p !== platform && pickAsset(rel, p)).map((p) => ASSETS[p].label);
}

function errKind(e) {
  if (!e) return "error";
  if (e.kind) return e.kind;
  if (e.name === "AbortError" || e.name === "TimeoutError") return "offline";
  const c = (e.cause && e.cause.code) || e.code || "";
  if (/ENOTFOUND|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EAI_AGAIN|ENETUNREACH|EHOSTUNREACH|UND_ERR/.test(c)) return "offline";
  if (e instanceof TypeError && /fetch failed|network/i.test(e.message)) return "offline";
  return "error";
}

/** GET the latest release. Throws {kind: "offline" | "rate_limited" | "error"}. */
async function fetchLatest({ fetchImpl = globalThis.fetch, appVersion = "0", timeoutMs = TIMEOUT_MS, url = LATEST_URL } = {}) {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const r = await fetchImpl(url, { signal: ac.signal, redirect: "follow",
      headers: { "User-Agent": `Outpost-Luna/${appVersion}`, Accept: "application/vnd.github+json" } });
    if (r.status === 403 || r.status === 429) throw Object.assign(new Error(`GitHub said ${r.status} (rate limit)`), { kind: "rate_limited" });
    if (r.status === 404) throw Object.assign(new Error("no published release"), { kind: "error" });
    if (r.status !== 200) throw Object.assign(new Error(`GitHub said ${r.status}`), { kind: "error" });
    const text = await r.text();
    if (text.length > 2 << 20) throw Object.assign(new Error("release too large"), { kind: "error" });
    return JSON.parse(text);
  } catch (e) {
    if (e.kind) throw e;
    throw Object.assign(new Error(e.message || String(e)), { kind: errKind(e) });
  } finally { clearTimeout(t); }
}

/**
 * One check. Never throws. -> {state, current, latest, notes, download, release, platform, others, checked_at, reason}
 *   state "up_to_date" | "available" (download: the installer URL, or null when this OS's is not uploaded yet;
 *   others: the platforms it is out for) | "error" (reason: "offline" | "rate_limited" | "error")
 */
async function check({ appVersion, platform = process.platform, fetchImpl = globalThis.fetch, timeoutMs = TIMEOUT_MS,
  url = LATEST_URL, now = Date.now } = {}) {
  const base = { current: appVersion, platform: platformLabel(platform), site: SITE_URL, checked_at: new Date(now()).toISOString() };
  let raw;
  try { raw = await fetchLatest({ fetchImpl, appVersion, timeoutMs, url }); }
  catch (e) { return { ...base, state: "error", reason: e.kind || "error", detail: e.message }; }
  const rel = parseRelease(raw);
  if (!rel || cmpVersion(rel.version, appVersion) <= 0) return { ...base, state: "up_to_date", latest: rel ? rel.version : null };
  const a = pickAsset(rel, platform);
  const sha = pickSha(rel, a, platform);
  return { ...base, state: "available", latest: rel.version, notes: rel.notes, release: rel.url,
    download: a ? a.url : null, asset: a ? a.name : null, size: a ? a.size : null, digest: a ? a.digest : null,
    sha_url: sha ? sha.url : null, others: a ? [] : otherPlatforms(rel, platform) };
}

/** What "Download" / "Release page" / the site opens for the last result, already allow-listed; else null. */
function targetUrl(last, what) {
  const u = what === "site" ? SITE_URL : what === "release" ? (last && last.release) || RELEASES_URL
    : what === "download" ? last && last.download : null;
  return u && openAllowed(u) ? u : null;
}

/** /__outpost/update?do=check|open&what=download|release|site|folder on our origin -> {do, what}, else null. */
function parseUpdateUrl(url, origin) {
  let u;
  try { u = new URL(url); } catch { return null; }
  if (u.origin !== origin || u.pathname !== UPDATE_PATH) return null;
  const act = u.searchParams.get("do");
  if (act === "check") return { do: "check" };
  if (act === "open") {
    const what = u.searchParams.get("what");
    return ["download", "release", "site", "folder"].includes(what) ? { do: "open", what } : null;
  }
  return null;
}

// ---- "Download": the main process fetches the installer itself (no browser) --------------------------------------

const fail = (kind, msg) => Object.assign(new Error(msg), { kind });

/** "name.dmg", then "name (1).dmg", "name (2).dmg", …: the first that does not exist. Never overwrites. */
function uniquePath(dir, name, exists = fs.existsSync) {
  const ext = path.extname(name), stem = name.slice(0, name.length - ext.length);
  for (let i = 0; i < 1000; i++) {
    const p = path.join(dir, i ? `${stem} (${i})${ext}` : name);
    if (!exists(p)) return p;
  }
  throw fail("disk", "no free name in the folder");
}

/**
 * GET url, following redirects one hop at a time. The first hop must be on our repo (openAllowed) and allowed by the
 * net policy (hostOk); later hops may also be GitHub's release-asset hosts (ASSET_HOSTS): the policy allowed github.com,
 * and this is where github.com keeps the bytes. Anything else is refused before it is requested.
 */
async function getAsset(url, { fetchImpl, hostOk = () => true, signal, headers }) {
  for (let hop = 0; hop < 6; hop++) {
    const host = new URL(url).hostname.toLowerCase();
    const listed = openAllowed(url) || (hop > 0 && assetHostAllowed(url));
    if (!listed) throw fail("error", `refused to fetch ${host}`);
    if (!hostOk(host) && !(hop > 0 && assetHostAllowed(url))) throw fail("school", `School network mode: ${host} is not on the allow list`);
    const r = await fetchImpl(url, { headers, signal, redirect: "manual" });
    const loc = r.status >= 300 && r.status < 400 && r.headers && r.headers.get && r.headers.get("location");
    if (!loc) return r;
    if (r.body && r.body.cancel) r.body.cancel().catch(() => {});
    url = new URL(loc, url).toString();
  }
  throw fail("error", "too many redirects");
}

function dlKind(e) {
  if (e && e.kind) return e.kind;
  const c = (e && ((e.cause && e.cause.code) || e.code)) || "";
  if (/ENOSPC|EACCES|EPERM|EROFS|EDQUOT|EISDIR|ENOTDIR/.test(c)) return "disk";
  return errKind(e);
}

/**
 * Download the installer the last check found into `dir` (the Downloads folder). -> {file, bytes, sha256, verified}
 * verified: "sha256" (the release's .sha256 file, or GitHub's digest) | "size" (only the size was known).
 * Throws {kind: "offline" | "school" | "check" (wrong size / sha256) | "disk" | "error"}; nothing is left behind then.
 * onProgress(got, total) after each chunk. The file lands under a new name when one with its name is there already.
 */
async function downloadInstaller({ last, dir, fetchImpl = globalThis.fetch, hostOk, onProgress = () => {}, appVersion = "0",
  connectMs = CONNECT_MS, stallMs = STALL_MS, signal: outer } = {}) {
  const url = targetUrl(last, "download");
  if (!url || !last.asset) throw fail("error", "no installer to download");
  const name = path.basename(String(last.asset));
  if (!name || name.startsWith(".") || !/\.(dmg|exe)$/i.test(name)) throw fail("error", `odd installer name ${name}`);
  const headers = { "User-Agent": `Outpost-Luna/${appVersion}` };
  const ac = new AbortController();
  let timer = null, why = null;
  const arm = (ms, what) => { clearTimeout(timer); timer = setTimeout(() => { why = what; ac.abort(); }, ms); };
  if (outer) outer.addEventListener("abort", () => { why = "cancelled"; ac.abort(); }, { once: true });
  const part = path.join(dir, `.${name}.${crypto.randomBytes(4).toString("hex")}.part`);
  let w = null;
  try {
    let want = null;
    if (last.sha_url) {
      arm(connectMs, "connect");
      const r = await getAsset(last.sha_url, { fetchImpl, hostOk, signal: ac.signal, headers });
      if (r.status !== 200) throw fail("error", `checksum file: HTTP ${r.status}`);
      const text = await r.text();
      want = parseShaFile(text.slice(0, 4096));
      if (!want) throw fail("check", "checksum file has no sha256");
    } else if (last.digest) want = last.digest;
    arm(connectMs, "connect");
    const r = await getAsset(url, { fetchImpl, hostOk, signal: ac.signal, headers });
    if (r.status !== 200) throw fail("error", `HTTP ${r.status}`);
    const len = Number(r.headers && r.headers.get && r.headers.get("content-length"));
    const size = last.size || (Number.isSafeInteger(len) && len > 0 ? len : null);
    if (last.size && Number.isSafeInteger(len) && len > 0 && len !== last.size) throw fail("check", `size ${len}, the release says ${last.size}`);
    fs.mkdirSync(dir, { recursive: true });
    w = fs.createWriteStream(part, { flags: "wx" });
    await once(w, "open");
    const h = crypto.createHash("sha256");
    let got = 0;
    arm(stallMs, "stall");
    for await (const chunk of r.body) {
      arm(stallMs, "stall");
      h.update(chunk);
      got += chunk.length;
      if (size && got > size) throw fail("check", `more than the ${size} bytes the release says`);
      if (!w.write(chunk)) await once(w, "drain");   // rejects on a write error, and leaves no listener behind
      onProgress(got, size);
    }
    clearTimeout(timer);
    await new Promise((res, rej) => w.end((e) => (e ? rej(e) : res())));
    w = null;
    if (size && got !== size) throw fail("check", `got ${got} bytes, the release says ${size}`);
    const sha256 = h.digest("hex");
    if (want && sha256 !== want) throw fail("check", "sha256 does not match the release");
    let file = null;
    for (let i = 0; i < 20 && !file; i++) {
      const p = uniquePath(dir, name);
      try { fs.linkSync(part, p); file = p; }
      catch (e) {
        if (e.code === "EEXIST") continue;   // appeared just now: the next name
        if (fs.existsSync(p)) continue;
        fs.renameSync(part, p); file = p;     // a folder that cannot hard-link (some network / FAT drives)
      }
    }
    if (!file) throw fail("disk", "no free name in the folder");
    fs.rmSync(part, { force: true });
    return { file, bytes: got, sha256, verified: want ? "sha256" : "size" };
  } catch (e) {
    ac.abort();   // drops the connection of a download that stopped half way
    if (w) { w.destroy(); }
    try { fs.rmSync(part, { force: true }); } catch { /* best effort */ }
    if (why === "connect" || why === "stall") throw fail("offline", why === "stall" ? "the download stalled" : "no answer");
    if (why === "cancelled") throw fail("cancelled", "cancelled");
    throw Object.assign(new Error((e && e.message) || String(e)), { kind: dlKind(e) });
  } finally { clearTimeout(timer); }
}

/**
 * shell.openExternal, awaited. It rejects when the system cannot open the link (macOS -10810: the default browser app
 * is gone); then the failure is logged and onFail(url) tells the page, which shows the link with a Copy button.
 * -> true (opened) | false.
 */
async function openWithFallback(url, { open, log = () => {}, onFail = () => {} }) {
  try { await open(url); return true; }
  catch (e) {
    log(`web browser did not open: ${(e && e.message) || e}`, String(url).slice(0, 160));
    try { onFail(url, e); } catch { /* the page is gone */ }
    return false;
  }
}

/** The opt-in launch check: at most once per DAY_MS (the last ATTEMPT counts, offline or not). */
function createAutoGate({ file, now = Date.now }) {
  const read = () => { try { return JSON.parse(fs.readFileSync(file, "utf8")) || {}; } catch { return {}; } };
  return {
    due() {
      const last = Date.parse(read().last_auto_check_at || "");
      return !Number.isFinite(last) || now() - last >= DAY_MS || last > now() + DAY_MS;   // a clock moved back: allow
    },
    mark() {
      try {
        fs.mkdirSync(path.dirname(file), { recursive: true });
        fs.writeFileSync(file + ".tmp", JSON.stringify({ ...read(), last_auto_check_at: new Date(now()).toISOString() }));
        fs.renameSync(file + ".tmp", file);
      } catch { /* the next launch checks again: still at most one request per launch */ }
    },
    last: () => read().last_auto_check_at || null,
  };
}

module.exports = { REPO, LATEST_URL, RELEASES_URL, SITE_URL, UPDATE_PATH, DAY_MS, ASSETS, ASSET_HOSTS, cmpVersion, openAllowed,
  assetHostAllowed, summarize, parseRelease, pickAsset, pickSha, parseShaFile, otherPlatforms, fetchLatest, check, targetUrl,
  parseUpdateUrl, createAutoGate, platformLabel, uniquePath, getAsset, downloadInstaller, openWithFallback };
