// Settings -> App version -> "Check for updates" (docs/DESKTOP.md "App updates"). No Electron import: main.js passes
// fetch / platform / the app version in, and appupdate.test.js drives it with fakes.
//
// The app promises no network after setup, so this is a MANUAL check by default: the page asks (it navigates to
// /__outpost/update?do=check, main.js stops that), the main process asks GitHub for the latest release (the page is
// locked to its own origin and could not), compares it with app.getVersion() and hands the result back through
// window.__lunaUpdate. "Download" opens the installer for this platform in the system browser; only https URLs on
// github.com/WhissleAI/Outpost-Luna or whissleai.github.io are ever opened. Nothing is installed by the app.
//
// Opt-in: Settings -> "Check for updates automatically" (prefs.update_check, off by default). When on, a launch checks
// at most once per day (the last attempt is kept in <userData>/update-check.json) and stays silent unless a newer
// release exists.
"use strict";
const fs = require("fs");
const path = require("path");
const { cmpVersion } = require("./assets");

const REPO = "WhissleAI/Outpost-Luna";
const LATEST_URL = `https://api.github.com/repos/${REPO}/releases/latest`;
const RELEASES_URL = `https://github.com/${REPO}/releases/latest`;
const SITE_URL = "https://whissleai.github.io/Outpost-Luna/";
const UPDATE_PATH = "/__outpost/update";
const DAY_MS = 24 * 3600 * 1000;
const TIMEOUT_MS = 8000;

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

/** A GitHub release object -> {version, tag, url, notes, assets: [{name, url}]}, or null (draft, prerelease, junk). */
function parseRelease(r) {
  if (!r || typeof r !== "object" || r.draft || r.prerelease) return null;
  const tag = String(r.tag_name || "");
  const version = tag.replace(/^v/i, "");
  if (!/^\d+\.\d+\.\d+$/.test(version)) return null;
  const url = openAllowed(r.html_url) ? r.html_url : `https://github.com/${REPO}/releases/tag/${encodeURIComponent(tag)}`;
  const assets = (Array.isArray(r.assets) ? r.assets : [])
    .filter((a) => a && typeof a.name === "string" && openAllowed(a.browser_download_url) && (a.state == null || a.state === "uploaded"))
    .map((a) => ({ name: a.name, url: a.browser_download_url }));
  return { version, tag, url, notes: summarize(r.body), assets };
}

/** The installer for `platform` in a parsed release, or null (not uploaded yet, or no installer for this OS). */
function pickAsset(rel, platform) {
  const want = ASSETS[platform];
  if (!rel || !want) return null;
  for (const n of want.names) { const a = rel.assets.find((x) => x.name === n); if (a) return a; }
  return rel.assets.find((x) => want.re.test(x.name)) || null;
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
  return { ...base, state: "available", latest: rel.version, notes: rel.notes, release: rel.url,
    download: a ? a.url : null, asset: a ? a.name : null, others: a ? [] : otherPlatforms(rel, platform) };
}

/** What "Download" / "Release page" / the site opens for the last result, already allow-listed; else null. */
function targetUrl(last, what) {
  const u = what === "site" ? SITE_URL : what === "release" ? (last && last.release) || RELEASES_URL
    : what === "download" ? last && last.download : null;
  return u && openAllowed(u) ? u : null;
}

/** /__outpost/update?do=check|open&what=download|release|site on our origin -> {do, what}, else null. */
function parseUpdateUrl(url, origin) {
  let u;
  try { u = new URL(url); } catch { return null; }
  if (u.origin !== origin || u.pathname !== UPDATE_PATH) return null;
  const act = u.searchParams.get("do");
  if (act === "check") return { do: "check" };
  if (act === "open") {
    const what = u.searchParams.get("what");
    return ["download", "release", "site"].includes(what) ? { do: "open", what } : null;
  }
  return null;
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

module.exports = { REPO, LATEST_URL, RELEASES_URL, SITE_URL, UPDATE_PATH, DAY_MS, ASSETS, cmpVersion, openAllowed, summarize,
  parseRelease, pickAsset, otherPlatforms, fetchLatest, check, targetUrl, parseUpdateUrl, createAutoGate, platformLabel };
