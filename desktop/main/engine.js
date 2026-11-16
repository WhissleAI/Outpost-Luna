// The local engine's access and supervision (issues #84, #87, #88; docs/SECURITY.md). No Electron imports: unit-tested
// with node --test (engine.test.js).
//   newToken          the per-launch secret both Python children require (LUNA_TOKEN; app/local_guard.py)
//   discovery file    engine.json in the per-user app data folder, 0600: how another local client finds the engine
//   RestartPolicy     restart a crashed child with exponential back-off; give up after N fast failures
//   HangWatch         a child that is alive but stops answering its health check N times in a row is hung
"use strict";
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const DISCOVERY = "engine.json";
const DISCOVERY_FORMAT = 1;

/** 32 random bytes, URL-safe base64 (43 chars). A new one every launch: nothing persists it but engine.json. */
function newToken() { return crypto.randomBytes(32).toString("base64url"); }

/** <userData>/engine.json: macOS ~/Library/Application Support/Outpost Luna, Windows %APPDATA%\Outpost Luna. */
function discoveryFile(userData) { return path.join(userData, DISCOVERY); }

/** The discovery record (docs/SECURITY.md "engine.json"). */
function discoveryRecord({ backendPort, modelsPort, token, pid = process.pid, version, startedAt = Date.now() }) {
  return {
    format: DISCOVERY_FORMAT,
    backend: `http://127.0.0.1:${backendPort}`,
    model_server: `http://127.0.0.1:${modelsPort}`,
    token,
    pid,
    version,
    started_at: new Date(startedAt).toISOString(),
  };
}

/** Write atomically, readable by this user only (0600 on POSIX; on Windows the per-user %APPDATA% ACL does that job,
 *  and chmod only toggles read-only there, so it is skipped). */
function writeDiscovery(file, rec, { platform = process.platform } = {}) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  try { fs.unlinkSync(tmp); } catch { /* none */ }
  fs.writeFileSync(tmp, JSON.stringify(rec, null, 1) + "\n", { mode: 0o600, flag: "wx" });
  if (platform !== "win32") fs.chmodSync(tmp, 0o600);
  fs.renameSync(tmp, file);
  if (platform !== "win32") fs.chmodSync(file, 0o600);
}

function readDiscovery(file) { try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return null; } }

/** Remove engine.json, but only our own (a second instance must not delete the first one's). */
function removeDiscovery(file, pid = process.pid) {
  const rec = readDiscovery(file);
  if (rec && rec.pid !== pid) return false;
  try { fs.unlinkSync(file); return true; } catch { return false; }
}

/**
 * Restart policy for one child. Each crash waits base * 2^n (capped), n = crashes since the child last ran healthy
 * for `stableMs`. After `maxRestarts` such crashes in a row it gives up (the caller tells the user).
 *   const p = new RestartPolicy(); p.healthy(now); ... p.crashed(now) -> {action: "restart", delayMs} | {action: "giveup"}
 */
class RestartPolicy {
  constructor({ baseMs = 1000, capMs = 30000, maxRestarts = 5, stableMs = 60000 } = {}) {
    Object.assign(this, { baseMs, capMs, maxRestarts, stableMs });
    this.failures = 0;
    this.healthySince = null;
  }
  healthy(now = Date.now()) { if (this.healthySince == null) this.healthySince = now; }
  crashed(now = Date.now()) {
    if (this.healthySince != null && now - this.healthySince >= this.stableMs) this.failures = 0;
    this.healthySince = null;
    if (this.failures >= this.maxRestarts) return { action: "giveup", failures: this.failures };
    const delayMs = Math.min(this.capMs, this.baseMs * 2 ** this.failures);
    this.failures += 1;
    return { action: "restart", delayMs, attempt: this.failures };
  }
}

/** Counts failed health checks in a row; `miss()` returns true once there are `strikes` of them (the child is hung). */
class HangWatch {
  constructor({ strikes = 4 } = {}) { this.strikes = strikes; this.misses = 0; }
  ok() { this.misses = 0; }
  miss() { this.misses += 1; return this.misses >= this.strikes; }
}

module.exports = { newToken, discoveryFile, discoveryRecord, writeDiscovery, readDiscovery, removeDiscovery, RestartPolicy,
  HangWatch, DISCOVERY, DISCOVERY_FORMAT };
