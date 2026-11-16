// Outpost Luna desktop: local diagnostics (issue #92, docs/DIAGNOSTICS.md). No Electron import: main.js passes the app
// hooks in, and diag.test.js drives it with temp folders.
//
//   JSON-lines log   <userData>/logs/main.jsonl: {"ts","level","svc":"main","event",...fields}, every field scrubbed
//                    (the same rules as the Python servers' app/diag.py), rotated at 5 MB, 5 files. main.log (the
//                    human-readable lines) stays as it was; it is capped at launch (rotateText) like the children's.
//   Sessions         a session is one app launch. <userData>/metrics/session.json marks the running one; a launch that
//                    finds it unfinished counts the previous session as NOT crash-free (the app crashed or was killed),
//                    and so does a session in which a child crashed and was restarted. A clean quit with no restart
//                    is crash-free. Counted per day in <userData>/metrics/daily-main.json (last 30 days).
//   The bundle       Settings -> Help & diagnostics -> "Save a diagnostics file…": the page navigates to
//                    /__outpost/diagnostics; main.js stops that, asks the user where to save (a save dialog), gets the
//                    zip from the backend (POST /api/diagnostics/bundle with what only the shell knows: app, OS,
//                    hardware, engine.json minus the token, these session counts) and writes it there. Nothing is ever
//                    uploaded.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");

const LOG_MAX_BYTES = 5 * 1024 * 1024;
const LOG_KEEP = 5;
const KEEP_DAYS = 30;
const MAX_STR = 300;
const SCRUBBED = "[scrubbed]";
const DIAG_PATH = "/__outpost/diagnostics";

// ---- scrub: the same rules as app/diag.py (diag.test.js checks the key lists match) ----
const SENSITIVE_KEYS = new Set([
  "text", "transcript", "words", "word", "spoken", "heard", "entity", "names", "name", "utterance", "utts", "said",
  "say", "readback", "question", "answer", "query", "q", "prompt", "message", "callsign", "call_sign", "audio",
  "pcm", "wav", "samples", "token", "luna_token", "x-luna-token", "authorization", "cookie", "set-cookie",
  "password", "secret", "api_key"]);
const SENSITIVE_SUFFIXES = ["token", "secret", "password", "_key", "cookie", "_text", "_words"];
const SECRET_AFTER = /(bearer\s+|luna_token=|x-luna-token["']?\s*[:=]\s*["']?|token["']?\s*[:=]\s*["']?)[A-Za-z0-9._~+/=-]{6,}/gi;
const LONG_RUN = /[A-Za-z0-9_-]{32,}/g;

function sensitiveKey(k) {
  const s = String(k).toLowerCase();
  return SENSITIVE_KEYS.has(s) || SENSITIVE_SUFFIXES.some((x) => s.endsWith(x));
}

function scrubStr(s, { token = "", home = os.homedir(), limit = MAX_STR } = {}) {
  s = String(s);
  if (token) s = s.split(token).join(SCRUBBED);
  s = s.replace(SECRET_AFTER, (_m, a) => a + SCRUBBED);
  s = s.replace(LONG_RUN, (m) => (/^[0-9a-fA-F]+$/.test(m) ? m : SCRUBBED));
  if (home && home.length > 1) s = s.split(home).join("~");
  if (limit && s.length > limit) s = s.slice(0, limit) + "…";
  return s;
}

function scrub(v, opts = {}, depth = 0) {
  if (depth > 12) return SCRUBBED;
  if (v === null || v === undefined || typeof v === "boolean") return v ?? null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string") return scrubStr(v, opts);
  if (Buffer.isBuffer(v) || v instanceof Uint8Array || v instanceof ArrayBuffer) return "[bytes]";
  if (Array.isArray(v)) return v.slice(0, 200).map((x) => scrub(x, opts, depth + 1));
  if (typeof v === "object") {
    const out = {};
    for (const [k, x] of Object.entries(v)) {
      const empty = x === null || x === undefined || x === "" || (Array.isArray(x) && !x.length);
      out[k] = sensitiveKey(k) && !empty ? SCRUBBED : scrub(x, opts, depth + 1);
    }
    return out;
  }
  return scrubStr(String(v), opts);
}

// ---- the JSON-lines log ----
function rotate(file, keep) {
  for (let i = keep - 1; i >= 1; i--) {
    const src = i > 1 ? `${file}.${i - 1}` : file;
    try { if (fs.existsSync(src)) fs.renameSync(src, `${file}.${i}`); } catch { /* a file in use (Windows): next time */ }
  }
  if (keep === 1) { try { fs.unlinkSync(file); } catch { /* */ } }
}

function createJsonLog({ dir, svc = "main", maxBytes = LOG_MAX_BYTES, keep = LOG_KEEP, token = "" }) {
  const file = path.join(dir, `${svc}.jsonl`);
  function event(name, fields = {}, level = "info") {
    const rec = { ts: new Date().toISOString(), level, svc, event: String(name).slice(0, 80) };
    for (const [k, v] of Object.entries(scrub(fields, { token }))) if (!(k in rec)) rec[k] = v;
    const line = JSON.stringify(rec) + "\n";
    try {
      fs.mkdirSync(dir, { recursive: true });
      let size = 0;
      try { size = fs.statSync(file).size; } catch { /* new */ }
      if (size && size + Buffer.byteLength(line) > maxBytes) rotate(file, Math.max(1, keep));
      fs.appendFileSync(file, line);
    } catch { /* logging never breaks the app */ }
    return rec;
  }
  const files = () => [file, ...Array.from({ length: keep - 1 }, (_, i) => `${file}.${i + 1}`)].filter((f) => fs.existsSync(f));
  return { event, error: (n, f) => event(n, f, "error"), warning: (n, f) => event(n, f, "warning"), files, file };
}

/** A human-readable log (main.log, backend.log, models.log) over maxBytes at launch: moved to <name>.1 (one kept). */
function rotateText(file, maxBytes = LOG_MAX_BYTES) {
  try {
    if (fs.statSync(file).size > maxBytes) { fs.rmSync(`${file}.1`, { force: true }); fs.renameSync(file, `${file}.1`); return true; }
  } catch { /* missing */ }
  return false;
}

// ---- sessions + the daily summary ----
const day = (t) => { const d = new Date(t); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

function readJson(f) { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return null; } }
function writeJson(f, v) {
  try {
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f + ".tmp", JSON.stringify(v));
    fs.renameSync(f + ".tmp", f);
    return true;
  } catch { return false; }
}

/** counters into `when`'s bucket of daily-main.json; days past KEEP_DAYS dropped (the format of app/diag.py). */
function addDaily(file, counters, when = Date.now(), keepDays = KEEP_DAYS) {
  let doc = readJson(file);
  if (!doc || typeof doc.days !== "object" || !doc.days) doc = { format: 1, svc: "main", days: {} };
  const b = doc.days[day(when)] = doc.days[day(when)] || { counters: {} };
  b.counters = b.counters || {};
  for (const [k, v] of Object.entries(counters)) b.counters[k] = (b.counters[k] || 0) + v;
  const days = Object.keys(doc.days).sort();
  for (const d of days.slice(0, Math.max(0, days.length - keepDays))) delete doc.days[d];
  doc.updated_at = new Date().toISOString();
  writeJson(file, doc);
  return doc;
}

function createTracker({ dir, version = "", pid = process.pid, now = () => Date.now() }) {
  const sessionFile = path.join(dir, "session.json"), dailyFile = path.join(dir, "daily-main.json");
  const counters = {};
  let cur = null;
  const count = (k, n = 1, when) => { counters[k] = (counters[k] || 0) + n; addDaily(dailyFile, { [k]: n }, when); };
  return {
    sessionFile, dailyFile,
    /** At launch: settle the previous session (unfinished = not crash-free), start this one. */
    begin() {
      const prev = readJson(sessionFile);
      let previous = null;
      if (prev && prev.started) {
        previous = prev.ended ? "clean" : "crashed";
        if (!prev.ended) { count("sessions_not_crash_free", 1, prev.started); count("sessions_ended_by_crash", 1, prev.started); }
      }
      cur = { started: now(), pid, version, restarts: {}, ended: false };
      writeJson(sessionFile, cur);
      count("sessions");
      return { previous };
    },
    /** A child crashed (or was killed for a hung health check) and is being restarted: this session is not crash-free. */
    restart(child) {
      count(`restarts{child=${child}}`);
      if (cur) { cur.restarts[child] = (cur.restarts[child] || 0) + 1; writeJson(sessionFile, cur); }
    },
    event(name) { count(name); },
    /** A quit (or a Settings reset): crash-free unless a child restarted or the app failed (`failed`: its error box). */
    end(failed = false) {
      if (!cur || cur.ended) return null;
      const free = !failed && !Object.values(cur.restarts).some((n) => n > 0);
      count(free ? "sessions_crash_free" : "sessions_not_crash_free", 1, cur.started);
      cur = { ...cur, ended: now(), crash_free: free };
      writeJson(sessionFile, cur);
      return free;
    },
    snapshot() {
      const doc = readJson(dailyFile) || { days: {} };
      let free = 0, notFree = 0;
      for (const b of Object.values(doc.days || {})) { free += (b.counters || {}).sessions_crash_free || 0; notFree += (b.counters || {}).sessions_not_crash_free || 0; }
      return { svc: "main", pid, version, session: cur && { started_at: new Date(cur.started).toISOString(), restarts: cur.restarts },
        counters: { ...counters }, crash_free_sessions_30d: { crash_free: free, not_crash_free: notFree,
          rate: free + notFree ? Math.round((free / (free + notFree)) * 1000) / 1000 : null } };
    },
  };
}

// ---- the bundle ----
const isDiagUrl = (url, origin) => { try { const u = new URL(url); return u.origin === origin && u.pathname === DIAG_PATH; } catch { return false; } };
const defaultName = (t = Date.now()) => `outpost-luna-diagnostics-${day(t)}.zip`;

/** What only the shell knows, for the bundle: app, OS, hardware, engine.json minus its token, the session counts and
 *  each Electron process's memory. No host name, no user name. */
function shellInfo({ appVersion, packaged, versions = process.versions, osm = os, engine = null, tracker = null, appMetrics = [] }) {
  const cpus = osm.cpus() || [];
  const eng = engine ? Object.fromEntries(Object.entries(engine).filter(([k]) => !sensitiveKey(k))) : null;
  return {
    app: { version: appVersion, packaged: !!packaged, electron: versions.electron, chrome: versions.chrome, node: versions.node },
    os: { platform: osm.platform(), release: osm.release(), arch: osm.arch(), type: osm.type(),
      version: typeof osm.version === "function" ? osm.version() : undefined },
    hardware: { cpu: cpus[0] && cpus[0].model, cores: cpus.length, memory_gb: Math.round((osm.totalmem() / 2 ** 30) * 10) / 10,
      free_memory_gb: Math.round((osm.freemem() / 2 ** 30) * 10) / 10 },
    engine: eng,
    main_metrics: { ...(tracker ? tracker.snapshot() : {}),
      memory_mb: (appMetrics || []).map((m) => ({ type: m.type, pid: m.pid, rss_mb: m.memory ? Math.round(m.memory.workingSetSize / 1024) : null })) },
  };
}

/** POST the shell's part to the backend, write the zip it returns to `file`. Returns the bytes written. */
async function saveBundle({ backend, token, shell, file, fetchFn = fetch }) {
  const r = await fetchFn(`${backend}/api/diagnostics/bundle`, { method: "POST",
    headers: { "Content-Type": "application/json", "X-Luna-Token": token }, body: JSON.stringify(shell) });
  if (!r.ok) throw new Error(`the backend answered ${r.status}`);
  const buf = Buffer.from(await r.arrayBuffer());
  if (buf.length < 22 || buf.readUInt32LE(0) !== 0x04034b50) throw new Error("the backend did not send a zip");
  fs.writeFileSync(file + ".part", buf);
  fs.renameSync(file + ".part", file);
  return buf.length;
}

module.exports = { scrub, scrubStr, sensitiveKey, SENSITIVE_KEYS, SENSITIVE_SUFFIXES, createJsonLog, rotateText, createTracker,
  addDaily, isDiagUrl, defaultName, shellInfo, saveBundle, DIAG_PATH, LOG_MAX_BYTES, LOG_KEEP, KEEP_DAYS, day };
