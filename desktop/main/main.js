// Outpost Luna desktop: the Electron main process.
//   1. reap children a crashed run left behind, pick free loopback ports
//   2. start the model server and the backend (embedded Python, resources/app/launch.py), supervise them
//   3. splash "Warming up the models…" until both answer their health checks, then load the UI from the backend
//   4. offline by construction: the renderer may only talk to our two loopback ports; children get no API keys
//   5. quitting kills both process trees (process group on macOS / Linux, taskkill /T on Windows)
"use strict";
const { app, BrowserWindow, session, shell, dialog, systemPreferences, Menu } = require("electron");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const S = require("./supervisor");
const P = require("./permissions");
const K = require("./keys");   // [keys] the app menu + no accidental reload (docs/KEYBOARD.md §Desktop)

const RES = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..", "resources");
const USER = app.getPath("userData");                   // ~/Library/Application Support/Outpost Luna, %APPDATA%\Outpost Luna
const LOGS = path.join(USER, "logs");
const PY = S.IS_WIN ? path.join(RES, "python", "python.exe") : path.join(RES, "python", "bin", "python3");
const LAUNCH = path.join(RES, "app", "launch.py");
const LIB = { darwin: "libarctag.dylib", win32: "arctag.dll" }[process.platform] || "libarctag.so";
const MODELS = path.join(RES, "models");
const pids = new S.PidFile(path.join(USER, "children.json"));
const portsFile = path.join(USER, "ports.json");
const START_TIMEOUT_MS = 240000;

const kids = {};            // name -> { proc, port, restarts: [timestamps] }
let quitting = false, splash = null, win = null, ports = null;
const t0 = Date.now();

function log(...a) {
  const line = `[${new Date().toISOString()}] ${a.join(" ")}\n`;
  process.stdout.write(line);
  try { fs.appendFileSync(path.join(LOGS, "main.log"), line); } catch { /* logs dir not ready */ }
}

function readPorts() { try { return JSON.parse(fs.readFileSync(portsFile, "utf8")); } catch { return {}; } }

async function choosePorts() {
  // Stable ports keep the UI origin (and so its localStorage: settings, Flight School progress) the same across runs.
  const last = readPorts();
  const env = (k) => Number(process.env[k]) || 0;
  const backend = await S.pickPort([env("OUTPOST_BACKEND_PORT"), last.backend, 47310, 47311, 47312]);
  const models = await S.pickPort([env("OUTPOST_MODELS_PORT"), last.models, 47210, 47211, 47212], new Set([backend]));
  fs.writeFileSync(portsFile, JSON.stringify({ backend, models }));
  return { backend, models };
}

function envFor(name) {
  const common = { MOON_PARENT_PID: String(process.pid), HF_HOME: path.join(USER, "hf") };
  if (name === "models") {
    return S.childEnv({
      ...common,
      ARCTAG_LIB: path.join(RES, "native", LIB),
      ARCTAG_MODEL_DIR: path.join(MODELS, "arctag"),
      ARC_META_WEIGHTS: path.join(MODELS, "arc-v1.1"),
      EMBED_MODEL_DIR: path.join(MODELS, "minilm"),
      VOICE_PACK_DIR: path.join(RES, "app", "backend", "data", "voice_pack"),   // the recorded fixed lines (docs/VOICE_PACK.md)
    });
  }
  const origin = `http://127.0.0.1:${ports.backend}`;
  return S.childEnv({
    ...common,
    DATA_DIR: path.join(RES, "app", "backend", "data"),
    CACHE_DIR: path.join(USER, "cache"),
    FRONTEND_DIST: path.join(RES, "app", "frontend"),
    MODEL_SERVER_URL: `http://127.0.0.1:${ports.models}`,
    CORS_ORIGINS: origin,
    TTS_ENGINE: "os",   // the OS's own offline voices (model_server/app/tts_os.py); no Deepgram key in the app
  });
}

function startChild(name) {
  const port = ports[name];
  const out = fs.openSync(path.join(LOGS, `${name}.log`), "a");
  // POSIX: own process group, so quitting can kill the whole tree. Windows: no console window; taskkill /T on quit.
  const proc = spawn(PY, [LAUNCH, name, "--port", String(port)], S.childSpawnOptions({ cwd: path.join(RES, "app"), env: envFor(name), out }));
  fs.closeSync(out);
  const k = kids[name] = kids[name] || { restarts: [] };
  k.proc = proc; k.port = port; k.ready = false;
  pids.add({ name, pid: proc.pid, started: Date.now() });
  log(`started ${name} pid ${proc.pid} on 127.0.0.1:${port}`);
  proc.on("exit", (code, signal) => {
    pids.remove(proc.pid);
    log(`${name} exited code=${code} signal=${signal}`);
    if (quitting || k.proc !== proc) return;
    const now = Date.now();
    k.restarts = k.restarts.filter((t) => now - t < 60000);
    if (k.restarts.length >= 3) return fail(`The ${name === "models" ? "model server" : "backend"} keeps stopping.`);
    k.restarts.push(now);
    setTimeout(() => { if (!quitting) startChild(name); }, 1000);
  });
  proc.on("error", (e) => fail(`Could not start ${name}: ${e.message}`));
}

function status(msg) {
  log("status:", msg);
  if (splash && !splash.isDestroyed()) splash.webContents.executeJavaScript(`window.setStatus && setStatus(${JSON.stringify(msg)})`).catch(() => {});
}

let failed = false;
function fail(msg) {
  if (failed || quitting) return;
  failed = true;
  log("FAIL:", msg);
  dialog.showMessageBox({ type: "error", title: "Outpost Luna", message: msg,
    detail: `Logs are in ${LOGS}`, buttons: ["Open logs", "Quit"] })
    .then(({ response }) => { if (response === 0) shell.openPath(LOGS); app.quit(); });
}

async function waitHealthy() {
  const deadline = Date.now() + START_TIMEOUT_MS;
  let modelsUp = false;
  while (Date.now() < deadline && !failed && !quitting) {
    if (!modelsUp) {
      const h = await S.getJson(`http://127.0.0.1:${ports.models}/health`);
      if (h) { modelsUp = true; log(`model server healthy after ${((Date.now() - t0) / 1000).toFixed(1)} s`); status("Models ready. Opening the outpost…"); }
    }
    if (modelsUp) {
      const b = await S.getJson(`http://127.0.0.1:${ports.backend}/api/health`);
      if (b) { log(`backend healthy after ${((Date.now() - t0) / 1000).toFixed(1)} s`); return true; }
    }
    await S.sleep(300);
  }
  if (!failed && !quitting) fail("Outpost Luna took too long to start.");
  return false;
}

// Offline by construction + mic / camera for our own origin only (permissions.js; docs/GESTURES.md for the camera).
function lockDownSession(origin) {
  P.lockDownSession(session.defaultSession, origin, { log, systemPreferences });
}

function createSplash() {
  splash = new BrowserWindow({ width: 460, height: 300, frame: false, resizable: false, show: false, backgroundColor: "#05070d",
    webPreferences: { sandbox: true, contextIsolation: true } });
  splash.loadFile(path.join(__dirname, "splash.html"));
  splash.once("ready-to-show", () => splash.show());
}

function createMain(origin) {
  win = new BrowserWindow({ width: 1440, height: 900, minWidth: 960, minHeight: 640, show: false, backgroundColor: "#05070d",
    title: "Outpost Luna", webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  K.installKeys({ Menu, win, packaged: app.isPackaged, appName: "Outpost Luna" });   // [keys]
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https?:/.test(url) && !url.startsWith(origin)) shell.openExternal(url); return { action: "deny" }; });
  win.webContents.on("will-navigate", (e, url) => { if (!url.startsWith(origin)) { e.preventDefault(); if (/^https?:/.test(url)) shell.openExternal(url); } });
  win.once("ready-to-show", () => {
    win.show();
    if (splash && !splash.isDestroyed()) splash.close();
    log(`window shown after ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  });
  win.on("closed", () => { win = null; });
  win.loadURL(origin + "/");
}

async function stopAll() {
  quitting = true;
  await Promise.all(Object.values(kids).map((k) => k.proc && S.killTree(k.proc.pid)));
  pids.write([]);
  log("children stopped");
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    fs.mkdirSync(LOGS, { recursive: true });
    log(`Outpost Luna ${app.getVersion()} (${process.platform} ${process.arch}); resources ${RES}; data ${USER}`);
    createSplash();
    if (!fs.existsSync(PY)) return fail(`Embedded Python missing: ${PY}`);
    const reaped = await pids.reap(LAUNCH);
    if (reaped.length) log(`reaped stale children ${reaped.join(", ")}`);
    ports = await choosePorts();
    const origin = `http://127.0.0.1:${ports.backend}`;
    lockDownSession(origin);
    status("Warming up the models…");
    startChild("models");
    startChild("backend");
    if (await waitHealthy()) createMain(origin);
  });
  app.on("window-all-closed", () => app.quit());
  let stopped = false;
  app.on("before-quit", (e) => {
    if (stopped) return;
    e.preventDefault();
    stopAll().finally(() => { stopped = true; app.quit(); });
  });
  process.on("exit", () => { for (const k of Object.values(kids)) if (k.proc) S.killTreeSync(k.proc.pid); });
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => app.quit());
}
