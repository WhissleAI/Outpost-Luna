// Outpost Luna desktop: Settings → Reset Outpost Luna (docs/RESET.md). No Electron import: main.js passes the
// session, fs and the app hooks in, and reset.test.js drives it with fakes on both platforms.
//
// The page asks the backend first (POST /api/reset: it empties its own per-user state and returns a one-time token),
// then navigates to <origin>/__outpost/reset?level=start|all&token=…. main.js stops that navigation and calls
// performReset. It confirms the token with the backend, stops the backend and model server (on Windows an open model
// file or cache file can't be deleted while a child holds it), clears Chromium's storage for the app, deletes the
// per-user folders the level owns, logs it, and relaunches.
//
// What lives in userData (app.getPath("userData"): ~/Library/Application Support/Outpost Luna on macOS,
// %APPDATA%\Outpost Luna on Windows; Electron keeps everything there, nothing under %LOCALAPPDATA%):
//   logs/            KEPT always (the reset itself is logged there)
//   ports.json       KEPT (stable ports keep the page origin the same)
//   children.json    KEPT (the supervisor's pid file)
//   cache/           the backend's CACHE_DIR: tts/ turnlog/ (start); video/ vectors/ (all)
//   hf/              HF_HOME (all)
//   Local Storage, IndexedDB, Session Storage, …   Chromium's: cleared through session.clearStorageData
"use strict";
const path = require("path");

const RESET_PATH = "/__outpost/reset";
const LEVELS = ["start", "all"];
const KEEP = ["logs", "ports.json", "children.json"];
// Chromium storage the page owns (localStorage: progress, call sign, prefs; IndexedDB, caches): both levels
const STORAGES = ["localstorage", "indexdb", "cachestorage", "serviceworkers", "websql", "cookies", "filesystem", "shadercache"];

/** The per-user folders a level deletes, joined with the platform's own path rules (never a hard-coded root). */
function plan(level, userData, platform = process.platform) {
  if (!LEVELS.includes(level)) throw new Error(`reset level: ${level}`);
  const P = platform === "win32" ? path.win32 : path.posix;
  const start = [P.join(userData, "cache", "tts"), P.join(userData, "cache", "turnlog")];
  const all = [P.join(userData, "cache"), P.join(userData, "hf"), ...downloadedAssetDirs(userData, platform)];
  const del = level === "all" ? all : start;
  for (const d of del) {
    const rel = P.relative(userData, d);
    if (!rel || rel.startsWith("..") || P.isAbsolute(rel) || KEEP.includes(rel.split(P.sep)[0])) throw new Error(`refusing to delete ${d}`);
  }
  return { storages: STORAGES, delete: del, keep: KEEP.map((k) => P.join(userData, k)) };
}

/** TODO(feat/arc-space first-run download): the per-user folders the first-run download fills (models, the voice pack,
 *  crew audio). "Reset everything" deletes them so the next launch downloads them again. Today every asset is bundled
 *  read-only in the app, so there are none. */
function downloadedAssetDirs(userData, platform = process.platform) { void userData; void platform; return []; }

/** "<origin>/__outpost/reset?level=…&token=…" → {level, token}, or null for any other URL. */
function parseResetUrl(url, origin) {
  let u; try { u = new URL(url); } catch { return null; }
  if (u.origin !== origin || u.pathname !== RESET_PATH) return null;
  const level = u.searchParams.get("level"), token = u.searchParams.get("token") || "";
  return LEVELS.includes(level) && token ? { level, token } : null;
}

/**
 * Do it. deps: { session (Electron session: clearStorageData, clearCache), fs (rmSync), userData, platform,
 * confirm(token) → Promise<level|null> (asks the backend), stopChildren() → Promise, relaunch(), exit(code), log }.
 * Resolves the summary; never deletes anything unless the backend confirmed the same level.
 */
async function performReset({ level, token }, deps) {
  const { session, fs, userData, platform = process.platform, confirm, stopChildren, relaunch, exit, log = () => {} } = deps;
  const ok = await confirm(token);
  if (ok !== level) { log("reset refused: not confirmed by the backend"); return { done: false }; }
  const p = plan(level, userData, platform);
  log(`reset ${level}: stopping the backend and the model server`);
  await stopChildren();                       // Windows: nothing may hold a file we delete
  await session.clearStorageData({ storages: p.storages });
  if (session.clearCache) await session.clearCache();
  const deleted = [], failed = [];
  for (const d of p.delete) {
    try { fs.rmSync(d, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); deleted.push(d); }
    catch (e) { failed.push(`${d}: ${e.code || e.message}`); }
  }
  log(`reset ${level}: cleared browser storage; deleted ${deleted.length ? deleted.join(", ") : "nothing"}${failed.length ? `; could not delete ${failed.join(", ")}` : ""}; relaunching`);
  relaunch();
  exit(0);
  return { done: true, deleted, failed };
}

module.exports = { plan, parseResetUrl, performReset, downloadedAssetDirs, RESET_PATH, LEVELS, KEEP, STORAGES };
