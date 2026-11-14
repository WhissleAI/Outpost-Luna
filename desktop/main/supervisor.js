// Process supervision for the two Python children (backend, model server). No Electron imports: unit-tested with node --test.
//   pickPort       a free loopback port: the preferred one when free, else one the OS picks
//   PidFile        children's pids on disk, so the next start can reap what a crash left behind
//   killTree       SIGTERM the process group (POSIX) / taskkill /T /F (Windows), then SIGKILL after a grace period
//   childEnv       a clean environment: an allow-list from the parent, never its API keys
"use strict";
const fs = require("fs");
const net = require("net");
const http = require("http");
const path = require("path");
const { execFileSync } = require("child_process");

const IS_WIN = process.platform === "win32";

function portFree(port) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once("error", () => resolve(false));
    s.listen({ port, host: "127.0.0.1", exclusive: true }, () => s.close(() => resolve(true)));
  });
}

function ephemeralPort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once("error", reject);
    s.listen({ port: 0, host: "127.0.0.1" }, () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

/** First free port of `preferred` (in order), else an OS-chosen one. `avoid` excludes ports already handed out. */
async function pickPort(preferred = [], avoid = new Set()) {
  for (const p of preferred) if (p && !avoid.has(p) && (await portFree(p))) return p;
  for (let i = 0; i < 20; i++) { const p = await ephemeralPort(); if (!avoid.has(p)) return p; }
  throw new Error("no free loopback port");
}

/** Command line of a live pid, or null when it is gone. `platform` / `exec` are for the tests. */
function commandOf(pid, { platform = process.platform, exec = execFileSync } = {}) {
  try {
    if (platform === "win32") {
      // The full command line (CIM), so a reused pid that is now someone else's python.exe is never taken for ours.
      try {
        const cl = String(exec("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command",
          `(Get-CimInstance Win32_Process -Filter 'ProcessId=${Number(pid)}').CommandLine`],
          { encoding: "utf8", windowsHide: true, stdio: ["ignore", "pipe", "ignore"], timeout: 8000 })).trim();
        if (cl) return cl;
      } catch { /* no PowerShell / CIM: tasklist below */ }
      const out = String(exec("tasklist", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"], { encoding: "utf8", windowsHide: true }));
      return out.includes(`"${pid}"`) ? out.trim() : null;
    }
    return String(exec("ps", ["-o", "command=", "-p", String(pid)], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] })).trim() || null;
  } catch { return null; }
}

/** Is this command line one of our children (does it name our launcher)? Windows paths are case-insensitive. Without
 * CIM, Windows only has tasklist's image name: a python.exe at that pid is taken for ours. */
function isOurChild(cmd, marker, platform = process.platform) {
  if (!cmd) return false;
  const win = platform === "win32";
  if (win ? cmd.toLowerCase().includes(String(marker).toLowerCase()) : cmd.includes(marker)) return true;
  return win && /^"python3?\.exe","/i.test(cmd);
}

/** taskkill arguments for a whole tree (Windows has no process groups: /T walks the children). */
function taskkillArgs(pid) { return ["/PID", String(pid), "/T", "/F"]; }

/** spawn() options for a Python child. POSIX: its own process group (detached), so killTree can signal the group.
 * Windows: not detached (a detached console program gets its own console window), no window (windowsHide); taskkill /T
 * finds the tree. */
function childSpawnOptions({ cwd, env, out, platform = process.platform }) {
  return { cwd, env, stdio: ["ignore", out, out], detached: platform !== "win32", windowsHide: true };
}

function alive(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === "EPERM"; }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Kill a child and everything under it. POSIX children are spawned detached (own process group): signal the group. */
async function killTree(pid, graceMs = 4000) {
  if (!pid || !alive(pid)) return;
  if (IS_WIN) {
    try { execFileSync("taskkill", taskkillArgs(pid), { windowsHide: true, stdio: "ignore" }); } catch { /* gone */ }
    return;
  }
  const sig = (s) => { try { process.kill(-pid, s); } catch { try { process.kill(pid, s); } catch { /* gone */ } } };
  sig("SIGTERM");
  const t = Date.now();
  while (alive(pid) && Date.now() - t < graceMs) await sleep(100);
  if (alive(pid)) sig("SIGKILL");
}

/** Synchronous best effort, for process 'exit' handlers (no awaits possible there). */
function killTreeSync(pid) {
  if (!pid) return;
  if (IS_WIN) { try { execFileSync("taskkill", taskkillArgs(pid), { windowsHide: true, stdio: "ignore" }); } catch { /* gone */ } return; }
  try { process.kill(-pid, "SIGKILL"); } catch { try { process.kill(pid, "SIGKILL"); } catch { /* gone */ } }
}

class PidFile {
  constructor(file) { this.file = file; }
  read() { try { return JSON.parse(fs.readFileSync(this.file, "utf8")); } catch { return []; } }
  write(list) { fs.mkdirSync(path.dirname(this.file), { recursive: true }); fs.writeFileSync(this.file, JSON.stringify(list, null, 1)); }
  add(rec) { this.write([...this.read().filter((r) => r.pid !== rec.pid), rec]); }
  remove(pid) { this.write(this.read().filter((r) => r.pid !== pid)); }
  /** Kill children a previous run left behind. Only pids whose command line still names our launcher (pid reuse). */
  async reap(marker) {
    const killed = [];
    for (const r of this.read()) {
      const cmd = commandOf(r.pid);
      if (isOurChild(cmd, marker)) { await killTree(r.pid, 1500); killed.push(r.pid); }
    }
    this.write([]);
    return killed;
  }
}

/** GET url -> parsed JSON on 200, else null. */
function getJson(url, timeoutMs = 2000) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (c) => { body += c; });
      res.on("end", () => { if (res.statusCode !== 200) return resolve(null); try { resolve(JSON.parse(body)); } catch { resolve(null); } });
    });
    req.on("timeout", () => req.destroy());
    req.on("error", () => resolve(null));
  });
}

// Inherited from the parent environment, nothing else (so no DEEPGRAM_API_KEY etc. from a developer shell).
const ENV_ALLOW = ["PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "LC_CTYPE",
  "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
  "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE"];

function childEnv(extra, parent = process.env) {
  const env = {};
  for (const k of ENV_ALLOW) if (parent[k] !== undefined) env[k] = parent[k];
  return {
    ...env,
    PYTHONNOUSERSITE: "1", PYTHONDONTWRITEBYTECODE: "1", PYTHONUNBUFFERED: "1", PYTHONUTF8: "1",
    HF_HUB_OFFLINE: "1", TRANSFORMERS_OFFLINE: "1", HF_HUB_DISABLE_TELEMETRY: "1", DO_NOT_TRACK: "1",
    TOKENIZERS_PARALLELISM: "false",
    DEEPGRAM_API_KEY: "", NASA_API_KEY: "",
    ...extra,
  };
}

module.exports = { pickPort, portFree, killTree, killTreeSync, PidFile, getJson, childEnv, commandOf, isOurChild, taskkillArgs,
  childSpawnOptions, alive, sleep, IS_WIN };
