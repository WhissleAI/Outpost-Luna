// Outpost Luna desktop: the Electron main process.
//   1. reap children a crashed run left behind, pick free loopback ports
//   2. start the model server and the backend (embedded Python, resources/app/launch.py), supervise them
//   3. splash "Warming up the models…" until both answer their health checks, then load the UI from the backend
//   4. offline by construction: the renderer may only talk to our two loopback ports; children get no API keys
//   5. quitting kills both process trees (process group on macOS / Linux, taskkill /T on Windows)
//   0. first run (assets.js, docs/DESKTOP.md "First run: assets"): the models, the voice pack, the crew audio and the
//      NASA videos are not in the installer. The REQUIRED ones (ear, tagger, embedder, voice) are downloaded (or imported
//      from the offline pack) on a first-run screen before the children start; the optional ones follow in the
//      background once the UI is up. Every launch re-checks the installed files' sizes and repairs what is damaged.
//   6. asset updates without an app build (updates.js, docs/DESKTOP.md "Asset updates"): updates staged by an earlier
//      run are swapped in before the children start and confirmed (or rolled back) by the model server's health;
//      once the UI is up the remote manifest is checked and changed assets are staged in the background.
//   7. local access (docs/SECURITY.md, #84 / #88): a per-launch token (engine.js) goes to both children (LUNA_TOKEN) and
//      to the page as an HttpOnly SameSite=Strict cookie on our origin; both children refuse any other Origin and any
//      WebSocket / state-changing call without it. engine.json (0600, userData) tells other local clients where we are.
//   8. supervision (#87): a crashed child restarts with exponential back-off (engine.js RestartPolicy) and the app gives
//      up with a clear message after 5 fast crashes; a child that stops answering its health check is killed and
//      restarted; the page shows "Ear restarting…" (frontend/src/engine.js) while typing keeps working.
//   9. local diagnostics (#92, diag.js, docs/DIAGNOSTICS.md): JSON-lines logs (logs/main.jsonl; the children write
//      backend.jsonl / models.jsonl), crash-free sessions in metrics/, and Settings -> Help & diagnostics -> "Save a
//      diagnostics file…" (a zip the user saves where they choose; nothing is uploaded).
"use strict";
const { app, BrowserWindow, session, shell, dialog, systemPreferences, Menu, ipcMain } = require("electron");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const S = require("./supervisor");
const P = require("./permissions");
const K = require("./keys");   // [keys] the app menu + no accidental reload (docs/KEYBOARD.md §Desktop)
const R = require("./reset");   // Settings → Reset Outpost Luna (docs/RESET.md)
const G = require("./gate");   // [media] links out of a NASA video open behind the grown-up gate (docs/MEDIA.md)
const AS = require("./assets"); // first-run assets
const U = require("./updates"); // asset updates (remote manifest, staged swap, rollback)
const E = require("./engine");  // per-launch token, engine.json, restart back-off, hang watch (docs/SECURITY.md)
const D = require("./diag");    // structured logs, crash-free sessions, the diagnostics file (docs/DIAGNOSTICS.md)

// Tests and demos run against their own data folder, never the owner's real "Outpost Luna" one.
if (process.env.OUTPOST_USER_DATA) app.setPath("userData", process.env.OUTPOST_USER_DATA);
const RES = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..", "resources");
const USER = app.getPath("userData");                   // ~/Library/Application Support/Outpost Luna, %APPDATA%\Outpost Luna
const LOGS = path.join(USER, "logs");
const PY = S.IS_WIN ? path.join(RES, "python", "python.exe") : path.join(RES, "python", "bin", "python3");
const LAUNCH = path.join(RES, "app", "launch.py");
const LIB = { darwin: "libarctag.dylib", win32: "arctag.dll" }[process.platform] || "libarctag.so";
const ARC_LIB = { darwin: "libarc.dylib", win32: "arc.dll" }[process.platform] || "libarc.so";   // libarc (the ear)
const MANIFEST = app.isPackaged ? path.join(RES, "assets.manifest.json") : path.join(__dirname, "..", "assets.manifest.json");
let store = null;           // assets.createStore(...), set in whenReady
let updater = null;         // updates.createUpdater(...), set in whenReady
const APP_VERSION = app.getVersion();
const pids = new S.PidFile(path.join(USER, "children.json"));
const portsFile = path.join(USER, "ports.json");
const START_TIMEOUT_MS = 240000;
const HEALTH_EVERY_MS = 5000;   // after launch: both children's health checks (a hung child is killed and restarted)
const TOKEN = E.newToken();     // per launch; never written anywhere but engine.json (0600)
const AUTH = { "X-Luna-Token": TOKEN };
const ENGINE_FILE = E.discoveryFile(USER);
const LABEL = { models: "model server", backend: "backend" };
let engine = { ear: "starting", backend: "starting" };   // what the page shows (frontend/src/engine.js)
const jlog = D.createJsonLog({ dir: LOGS, svc: "main", token: TOKEN });   // [#92] logs/main.jsonl, scrubbed + rotated
const tracker = D.createTracker({ dir: path.join(USER, "metrics"), version: APP_VERSION });   // [#92] crash-free sessions

// Silent runs (tests, demos next to someone): OUTPOST_MUTE_AUDIO=1 mutes every page, like --mute-audio.
if (process.env.OUTPOST_MUTE_AUDIO === "1") app.commandLine.appendSwitch("mute-audio");
// Test runs next to someone working: OUTPOST_HEADLESS=1 never shows a window and (macOS) keeps the app out of the Dock,
// so it never takes focus. The page still loads and runs (drive it over --remote-debugging-port).
const HEADLESS = process.env.OUTPOST_HEADLESS === "1";
const reveal = (w) => { if (!HEADLESS) w.show(); };

const kids = {};            // name -> { proc, port, restarts: [timestamps] }
let quitting = false, splash = null, win = null, ports = null;
const t0 = Date.now();

function log(...a) {
  const line = `[${new Date().toISOString()}] ${a.join(" ")}\n`;
  process.stdout.write(line);
  try { fs.appendFileSync(path.join(LOGS, "main.log"), line); } catch { /* logs dir not ready */ }
  jlog.event("log", { msg: a.join(" ") });   // the same line, structured and scrubbed (paths -> ~, no token)
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
  const common = { MOON_PARENT_PID: String(process.pid), HF_HOME: path.join(USER, "hf"), LUNA_TOKEN: TOKEN,
    LUNA_LOG_DIR: LOGS, LUNA_DATA_DIR: USER };   // [#92] <svc>.jsonl logs + metrics/daily-<svc>.json (app/diag.py)
  if (name === "models") {
    const a = store.envPaths();   // the installed assets (assets.js): <userData>/assets/<id>
    return S.childEnv({
      ...common,
      ARCTAG_LIB: path.join(RES, "native", LIB),
      ARC_LIB: path.join(RES, "native", ARC_LIB),
      ARC_SPACE_DIR: a.ARC_SPACE_DIR,          // Arc Transcriber Space nft2/ (the ear)
      ARCTAG_MODEL_DIR: a.ARCTAG_MODEL_DIR,
      EMBED_MODEL_DIR: a.EMBED_MODEL_DIR,
      VOICE_PACK_DIR: a.VOICE_PACK_DIR,        // the recorded fixed lines (docs/VOICE_PACK.md)
      STEER_TTS_MODEL: a.STEER_TTS_MODEL,      // Steer TTS Edge, the optional engine (loaded once its asset is in)
    });
  }
  const a = store.envPaths();
  const vids = store.manifest.assets.find((x) => x.id === "videos");
  const origin = `http://127.0.0.1:${ports.backend}`;
  return S.childEnv({
    ...common,
    DATA_DIR: path.join(RES, "app", "backend", "data"),
    CACHE_DIR: path.join(USER, "cache"),
    FRONTEND_DIST: path.join(RES, "app", "frontend"),
    MODEL_SERVER_URL: `http://127.0.0.1:${ports.models}`,
    CORS_ORIGINS: origin,
    TTS_ENGINE: "os",   // the OS's own offline voices (model_server/app/tts_os.py); no Deepgram key in the app
    MEDIA_AUDIO_DIR: a.MEDIA_AUDIO_DIR,   // crew audio (optional asset; served once it is installed)
    VIDEO_PACK_DIR: a.VIDEO_PACK_DIR,     // the pinned NASA videos (optional asset; copied into the video cache)
    SITE_LAYERS_DIR: a.SITE_LAYERS_DIR,   // the site navigator's polar map layers (optional asset, docs/SITE_NAVIGATOR.md)
    VOICE_PACK_DIR: a.VOICE_PACK_DIR,
    // Settings -> About / Storage: GET /api/assets reads the summary, POST /api/assets/check asks for a check
    ASSETS_STATE_FILE: path.join(store.dir, "summary.json"),
    ASSETS_CHECK_FILE: path.join(store.dir, "check-request"),
    ASSETS_DIR: store.dir,                // the backend asks for an optional asset (.want/<id>) and shows its state
    // the pinned videos come from the asset pack: no second download of the same files from nasa.gov
    ...(vids && vids.url ? { VIDEO_PREFETCH: "0" } : {}),
  });
}

function startChild(name) {
  const port = ports[name];
  const out = fs.openSync(path.join(LOGS, `${name}.log`), "a");
  // POSIX: own process group, so quitting can kill the whole tree. Windows: no console window; taskkill /T on quit.
  const proc = spawn(PY, [LAUNCH, name, "--port", String(port)], S.childSpawnOptions({ cwd: path.join(RES, "app"), env: envFor(name), out }));
  fs.closeSync(out);
  const k = kids[name] = kids[name] || { policy: new E.RestartPolicy(), hang: new E.HangWatch() };
  k.proc = proc; k.port = port; k.ready = false; k.restarting = false; k.startedAt = Date.now(); k.hang.ok();
  pids.add({ name, pid: proc.pid, started: Date.now() });
  log(`started ${name} pid ${proc.pid} on 127.0.0.1:${port}`);
  jlog.event("child_start", { child: name, pid: proc.pid, port });
  proc.on("exit", (code, signal) => {
    pids.remove(proc.pid);
    log(`${name} exited code=${code} signal=${signal}`);
    if (quitting || k.proc !== proc) return;
    jlog.error("child_exit", { child: name, code, signal, up_s: Math.round((Date.now() - k.startedAt) / 1000) });
    tracker.restart(name);   // [#92] this session is no longer crash-free
    k.ready = false;
    if (name === "models" && updater && updater.trials().length) {   // a fresh update may be what killed it
      const back = updater.rollbackTrials(`the model server stopped (code ${code})`);
      if (back.length) writeSummary();
    }
    const r = k.policy.crashed();
    if (r.action === "giveup") return gaveUp(name, r.failures);
    log(`${name}: restart ${r.attempt} in ${r.delayMs} ms`);
    k.restarting = true;
    setEngine(name, "restarting");
    setTimeout(() => { if (!quitting && k.proc === proc) startChild(name); }, r.delayMs);
  });
  proc.on("error", (e) => fail(`Could not start ${name}: ${e.message}`));
}

/** A child crashed `failures` times in a row without running healthy in between: stop trying. The backend serves the
 *  page itself, so without it the app cannot go on; without the model server the page still works by typing. */
function gaveUp(name, failures) {
  log(`${name}: gave up after ${failures} restarts`);
  jlog.error("child_gave_up", { child: name, failures });
  tracker.event(`gave_up{child=${name}}`);
  if (name === "backend" || !win) return fail(`The ${LABEL[name]} keeps stopping.`);
  setEngine(name, "down");
}

function setEngine(name, state) {
  const key = name === "models" ? "ear" : "backend";
  if (engine[key] === state) return;
  engine = { ...engine, [key]: state };
  log(`engine: ${key} ${state}`);
  pushEngine();
}

/** The page's status line (frontend/src/engine.js): "Ear restarting…", or "Voice is off" after giving up. */
function pushEngine() {
  if (win && !win.isDestroyed()) {
    win.webContents.executeJavaScript(`window.__lunaEngine && window.__lunaEngine(${JSON.stringify(engine)})`).catch(() => {});
  }
}

/** After launch: every HEALTH_EVERY_MS ask both children. A restarted child turns ready again here; a running child
 *  that misses 4 checks in a row (20 s+), or one that never gets ready within START_TIMEOUT_MS, is killed: its exit
 *  handler restarts it with the back-off. */
function watchHealth() {
  let busy = false;
  setInterval(async () => {
    if (busy || quitting) return;
    busy = true;
    try {
      for (const name of ["models", "backend"]) {
        const k = kids[name];
        if (!k || !k.proc || k.restarting) continue;
        const proc = k.proc;
        const h = await S.getJson(`http://127.0.0.1:${k.port}${name === "models" ? "/health" : "/api/health"}`, 3000, AUTH);
        if (quitting || k.proc !== proc) continue;
        if (h) {
          k.hang.ok();
          k.policy.healthy();
          if (!k.ready) { k.ready = true; log(`${name} healthy after a restart`); setEngine(name, "ok"); }
          continue;
        }
        const hung = k.ready ? k.hang.miss() : Date.now() - k.startedAt > START_TIMEOUT_MS;
        if (hung) {
          log(`${name} stopped answering its health check; restarting it`);
          jlog.error("child_hung", { child: name });
          tracker.event(`health_kills{child=${name}}`);
          k.ready = false;
          setEngine(name, "restarting");
          S.killTree(proc.pid);   // the exit handler restarts it
        }
      }
    } finally { busy = false; }
  }, HEALTH_EVERY_MS);
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
      const h = await S.getJson(`http://127.0.0.1:${ports.models}/health`, 2000, AUTH);
      if (h) { modelsUp = true; log(`model server healthy after ${((Date.now() - t0) / 1000).toFixed(1)} s`); status("Models ready. Opening the outpost…"); }
    }
    if (modelsUp) {
      const b = await S.getJson(`http://127.0.0.1:${ports.backend}/api/health`, 2000, AUTH);
      if (b) {
        log(`backend healthy after ${((Date.now() - t0) / 1000).toFixed(1)} s`);
        for (const k of Object.values(kids)) { k.ready = true; k.policy.healthy(); }
        engine = { ear: "ok", backend: "ok" };
        return true;
      }
    }
    await S.sleep(300);
  }
  if (!failed && !quitting) fail("Outpost Luna took too long to start.");
  return false;
}

// Offline by construction + mic / camera for our own origin only (permissions.js; docs/GESTURES.md for the camera).
// The one way out: a NASA video's YouTube embed (permissions.allowYouTube). It plays from the loopback origin as it is
// (measured in Electron 44: no error 153), so no Referer is set; OUTPOST_YT_REFERER=1 turns that fallback on.
function lockDownSession(origin) {
  P.lockDownSession(session.defaultSession, origin, { log, systemPreferences, referer: process.env.OUTPOST_YT_REFERER === "1" });
}
const gate = G.createGate({ makeWindow: (o) => new BrowserWindow(o), file: path.join(__dirname, "gate.html"), log });

function createSplash() {
  splash = new BrowserWindow({ width: 460, height: 300, frame: false, resizable: false, show: false, backgroundColor: "#05070d",
    webPreferences: { sandbox: true, contextIsolation: true } });
  splash.loadFile(path.join(__dirname, "splash.html"));
  splash.once("ready-to-show", () => reveal(splash));
}

function createMain(origin) {
  win = new BrowserWindow({ width: 1440, height: 900, minWidth: 960, minHeight: 640, show: false, backgroundColor: "#05070d",
    title: "Outpost Luna", webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  K.installKeys({ Menu, win, packaged: app.isPackaged, appName: "Outpost Luna" });   // [keys]
  win.webContents.setWindowOpenHandler(({ url }) => {
    const kind = G.classifyOpen(url, origin);
    if (kind === "youtube") gate(win, url).then((ok) => { if (ok) shell.openExternal(url); });   // [media] grown-up gate
    else if (kind === "external") shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    // Settings → Reset: the page asked the backend (which returned a one-time token), now the shell does its part
    const r = R.parseResetUrl(url, origin);
    if (r) { e.preventDefault(); resetApp(r, origin); return; }
    // Settings → Help & diagnostics → "Save a diagnostics file…" (#92): the user picks where; nothing is uploaded
    if (D.isDiagUrl(url, origin)) { e.preventDefault(); saveDiagnostics(origin); return; }
    if (!url.startsWith(origin)) { e.preventDefault(); if (/^https?:/.test(url)) shell.openExternal(url); }
  });
  win.once("ready-to-show", () => {
    reveal(win);
    if (splash && !splash.isDestroyed()) splash.close();
    log(`window ${HEADLESS ? "ready (headless)" : "shown"} after ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  });
  win.on("closed", () => { win = null; });
  win.webContents.on("did-finish-load", pushEngine);   // a reload gets the engine state again
  win.loadURL(origin + "/");
}

// ---- Settings → Help & diagnostics (#92, diag.js) -------------------------------------------------------------------
let diagBusy = false;
function diagState(state) {
  if (win && !win.isDestroyed()) win.webContents.executeJavaScript(`window.__lunaDiag && window.__lunaDiag(${JSON.stringify({ state })})`).catch(() => {});
}
async function saveDiagnostics(origin) {
  if (diagBusy || !win) return;
  diagBusy = true;
  try {
    // OUTPOST_DIAG_SAVE_PATH: test runs only (like OUTPOST_USER_DATA): no dialog, this file
    let file = process.env.OUTPOST_DIAG_SAVE_PATH || "";
    if (!file) {
      const r = await dialog.showSaveDialog(win, { title: "Save a diagnostics file",
        defaultPath: path.join(app.getPath("downloads"), D.defaultName()), filters: [{ name: "Zip", extensions: ["zip"] }] });
      if (r.canceled || !r.filePath) { diagState("cancelled"); return; }
      file = r.filePath;
    }
    diagState("saving");
    const shell = D.shellInfo({ appVersion: APP_VERSION, packaged: app.isPackaged, engine: E.readDiscovery(ENGINE_FILE),
      tracker, appMetrics: app.getAppMetrics() });
    const bytes = await D.saveBundle({ backend: origin, token: TOKEN, shell, file });
    log(`diagnostics: saved a ${Math.round(bytes / 1024)} KB file`);
    jlog.event("diagnostics_saved", { bytes });
    diagState("saved");
  } catch (e) {
    log("diagnostics: not saved:", e.message);
    diagState("error");
  } finally { diagBusy = false; }
}

let resetting = false;
function resetApp(r, origin) {
  if (resetting) return;
  resetting = true;
  R.performReset(r, {
    session: session.defaultSession, fs, userData: USER, log,
    confirm: async (token) => { const j = await S.getJson(`${origin}/api/reset/confirm?token=${encodeURIComponent(token)}`, 2000, AUTH); return j && j.level; },
    stopChildren: stopAll,
    clearAssets: () => AS.clearAll(store.dir),   // "Reset everything": the first-run downloads go; the next launch fetches them
    relaunch: () => app.relaunch(), exit: (c) => app.exit(c),
  }).then((o) => { if (!o.done) resetting = false; }, (e) => { log("reset failed:", e.message); app.relaunch(); app.exit(0); });
}

// ---- first run: assets (assets.js) ---------------------------------------------------------------------------------
const OFFLINE_MSG = "You're offline. Connect to the internet, or import the offline pack from a USB stick.";
let firstrun = null, frAbort = null, frState = {}, frWaiters = [], frBusy = false;
const progress = {};        // id -> bytes done (for the screen)

function frSend(extra = {}) {
  frState = { ...frState, ...extra,
    assets: store.status().filter((x) => x.required).map((x) => ({ ...x, done: progress[x.id] || 0 })) };
  if (firstrun && !firstrun.isDestroyed()) firstrun.webContents.send("firstrun:state", frState);
}

function requiredReady() { return store.status().filter((x) => x.required).every((x) => x.state === "installed"); }

function createFirstRun() {
  firstrun = new BrowserWindow({ width: 560, height: 470, frame: false, resizable: false, show: false, backgroundColor: "#05070d",
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false, preload: path.join(__dirname, "firstrun-preload.js") } });
  firstrun.loadFile(path.join(__dirname, "firstrun.html"));
  firstrun.webContents.on("did-finish-load", () => frSend());
  firstrun.once("ready-to-show", () => reveal(firstrun));
  firstrun.on("closed", () => { firstrun = null; if (!requiredReady() && !quitting) app.quit(); });
}

/** Download the missing required assets with the screen's progress; resolves when all are in, or sets a problem. */
async function fetchRequired() {
  if (frBusy) return;
  frBusy = true;
  frAbort = new AbortController();
  const need = store.status().filter((x) => x.required && x.state !== "installed");
  const mb = Math.round(need.reduce((s, x) => s + x.size, 0) / 1e6);
  frSend({ busy: true, problem: false, title: "Getting Outpost Luna ready", message: `Downloading the Moon (${mb} MB)…` });
  try {
    await store.ensure(AS.REQUIRED_IDS, { signal: frAbort.signal,
      onProgress: (p) => { progress[p.id] = p.done; if (p.phase !== "download" || Math.random() < 0.1) frSend(); } });
    frSend({ busy: false, message: "Ready." });
  } catch (e) {
    if (e.name !== "AbortError") {
      log("assets: first run failed:", e.message);
      frSend({ busy: false, problem: true, title: "Outpost Luna isn't ready yet",
        message: AS.isNetworkError(e) ? OFFLINE_MSG : e.disk ? e.message : `The download stopped (${e.message}). Try again, or import the offline pack.` });
    }
  } finally { frBusy = false; }
  if (requiredReady()) { const w = frWaiters; frWaiters = []; w.forEach((r) => r()); }
}

async function importPack() {
  if (frBusy) return;
  const r = await dialog.showOpenDialog(firstrun, { title: "Import the Outpost Luna offline pack", properties: ["openFile"],
    filters: [{ name: "Offline pack", extensions: ["zip"] }] });
  if (r.canceled || !r.filePaths[0]) return;
  frBusy = true;
  frSend({ busy: true, problem: false, message: "Importing the offline pack…" });
  try {
    const got = await store.importOfflinePack(r.filePaths[0], { appVersion: APP_VERSION, onProgress: (p) => { progress[p.id] = p.done; if (Math.random() < 0.05) frSend(); } });
    log(`assets: imported ${got.join(", ") || "nothing new"} from ${r.filePaths[0]}`);
    frSend({ busy: false, message: requiredReady() ? "Ready." : "That pack did not have everything. Try again online, or another pack." , problem: !requiredReady() });
  } catch (e) {
    log("assets: import failed:", e.message);
    frSend({ busy: false, problem: true, message: `Could not import that file: ${e.message}` });
  } finally { frBusy = false; }
  if (requiredReady()) { const w = frWaiters; frWaiters = []; w.forEach((x) => x()); }
}

ipcMain.on("firstrun:retry", () => fetchRequired());
ipcMain.on("firstrun:import", () => importPack());
ipcMain.on("firstrun:later", () => {   // keeps every .part: the next launch resumes
  if (frAbort) frAbort.abort();
  log("assets: continue later");
  app.quit();
});

/** Resolves once the required assets are installed (at once when they already are: the usual launch). */
function requiredAssets() {
  const st = store.status();
  const bad = st.filter((x) => x.state === "corrupt");
  if (bad.length) log(`assets: repairing ${bad.map((x) => x.id).join(", ")} (size check failed)`);
  if (requiredReady()) return Promise.resolve();
  log(`assets: first run, missing ${st.filter((x) => x.required && x.state !== "installed").map((x) => x.id).join(", ")}`);
  createFirstRun();           // before the splash closes: closing the last window would quit the app
  if (splash && !splash.isDestroyed()) splash.close();
  const p = new Promise((res) => frWaiters.push(res));
  fetchRequired();
  return p.then(() => {
    createSplash();
    const fr = firstrun; firstrun = null;
    if (fr && !fr.isDestroyed()) fr.destroy();
  });
}

/** On demand: an optional asset the backend asked for (<assets>/.want/<id>: the kid picked the Steer voice) downloads
 *  at once instead of waiting its turn. Polled every 2 s; one at a time. */
let wantBusy = false;
function watchWanted() {
  setInterval(async () => {
    if (wantBusy || quitting) return;
    const id = store.wanted()[0];
    if (!id) return;
    wantBusy = true;
    try { await store.download(id); log(`assets: ${id} installed (asked for)`); }
    catch (e) { log(`assets: ${id} not downloaded (${e.message})`); }
    finally { wantBusy = false; }
  }, 2000);
}

/** After the UI is up: the optional assets (crew audio, videos), quietly; a failure waits for the next launch. An
 *  `on_demand` asset (the Steer voice) is never fetched here: only when the kid picks it in Settings (watchWanted). */
async function fetchOptional() {
  const onDemand = new Set(store.manifest.assets.filter((x) => x.on_demand).map((x) => x.id));
  const todo = store.status().filter((x) => !x.required && !onDemand.has(x.id) && x.state !== "installed").map((x) => x.id);
  for (const id of todo) {
    if (quitting) return;
    try { await store.ensure([id]); log(`assets: ${id} installed`); }
    catch (e) { log(`assets: ${id} not downloaded (${e.message}); next launch tries again`); }
  }
}

// ---- asset updates (updates.js) -------------------------------------------------------------------------------------
function writeSummary() {
  if (!updater) return;
  try {
    const f = path.join(store.dir, "summary.json");
    fs.writeFileSync(f + ".tmp", JSON.stringify(updater.summary()));
    fs.renameSync(f + ".tmp", f);
  } catch (e) { log("assets: summary not written:", e.message); }
}

/** The backend says a mission or a video is on: background downloads wait (like the video prefetch). */
async function backendBusy() {
  if (!ports) return false;
  const b = await S.getJson(`http://127.0.0.1:${ports.backend}/api/assets/busy`, 2000, AUTH);
  return !!(b && b.busy);
}

let updating = false;
async function runUpdates(why) {
  if (updating || quitting) return;
  updating = true;
  log(`assets: update check (${why})`);
  const tick = setInterval(writeSummary, 3000);
  try { await updater.run(); } finally { clearInterval(tick); updating = false; writeSummary(); }
}

/** Children healthy: keep the updates that loaded, roll back the ones that did not (then restart the model server). */
async function confirmUpdates() {
  if (!updater.trials().length) return;
  const h = (await S.getJson(`http://127.0.0.1:${ports.models}/health`, 2000, AUTH)) || {};
  const bad = updater.failing(h);
  if (bad.length) {
    // Stop both children BEFORE the rollback renames: Windows keeps open / memory-mapped files (the ear's weights, the
    // voice clips, the crew audio) locked, so a folder in use cannot be moved. Then start them on the previous copies.
    log(`assets: ${bad.join(", ")} failed the load check; stopping the children to roll back`);
    for (const name of ["models", "backend"]) {
      const k = kids[name];
      if (k && k.proc) { const p = k.proc; k.proc = null; await S.killTree(p.pid); }
    }
  }
  const r = updater.confirm(h);
  writeSummary();
  if (bad.length) {
    log(`assets: restarting on the previous ${r.rolled.join(", ") || "(none)"}`);
    startChild("models");
    startChild("backend");
  }
}

function watchCheckRequests() {
  const f = path.join(store.dir, "check-request");
  fs.watchFile(f, { interval: 2000 }, (cur, prev) => { if (cur.mtimeMs && cur.mtimeMs !== prev.mtimeMs) runUpdates("Settings"); });
}

async function stopAll() {
  if (!quitting) { const free = tracker.end(failed); jlog.event("session_end", { crash_free: free, up_s: Math.round((Date.now() - t0) / 1000) }); }
  quitting = true;
  await Promise.all(Object.values(kids).map((k) => k.proc && S.killTree(k.proc.pid)));
  pids.write([]);
  E.removeDiscovery(ENGINE_FILE);
  log("children stopped");
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    if (HEADLESS && app.dock) app.dock.hide();
    fs.mkdirSync(LOGS, { recursive: true });
    for (const n of ["main", "backend", "models"]) D.rotateText(path.join(LOGS, `${n}.log`));   // [#92] capped: 5 MB + one old
    const { previous } = tracker.begin();   // [#92] a session = one launch; the last one unfinished = not crash-free
    jlog.event("launch", { version: APP_VERSION, platform: process.platform, arch: process.arch, previous_session: previous });
    log(`Outpost Luna ${app.getVersion()} (${process.platform} ${process.arch}); resources ${RES}; data ${USER}`);
    createSplash();
    if (!fs.existsSync(PY)) return fail(`Embedded Python missing: ${PY}`);
    try {
      const bundled = AS.loadManifest(MANIFEST), dir = AS.assetsDir(USER);
      let remote = null;   // the last remote manifest a check cached: newer compatible entries win (updates.js)
      try { remote = JSON.parse(fs.readFileSync(path.join(dir, "remote-manifest.json"), "utf8")); } catch { /* none */ }
      store = AS.createStore({ dir, manifest: U.effectiveManifest(bundled, remote, APP_VERSION), log });
      updater = U.createUpdater({ store, bundled, appVersion: APP_VERSION, log, busy: backendBusy,
        remoteUrl: process.env.OUTPOST_ASSETS_MANIFEST_URL || U.REMOTE_URL });
      updater.applyPending();   // what an earlier run staged: swapped in now, before anything has the files open
    } catch (e) { return fail(`Asset list missing or damaged: ${e.message}`); }
    await requiredAssets();
    writeSummary();
    const reaped = await pids.reap(LAUNCH);
    if (reaped.length) log(`reaped stale children ${reaped.join(", ")}`);
    ports = await choosePorts();
    const origin = `http://127.0.0.1:${ports.backend}`;
    lockDownSession(origin);
    status("Warming up the models…");
    startChild("models");
    startChild("backend");
    if (await waitHealthy()) {
      // [#84] the page's token: a cookie on our origin only (HttpOnly: page scripts never see it; SameSite=Strict: no
      // other site's request carries it). Sent with every fetch and WebSocket from the page.
      await session.defaultSession.cookies.set({ url: origin, name: "luna_token", value: TOKEN, httpOnly: true, sameSite: "strict" });
      // [#88] engine.json: where the engine is and its token, for other local clients (docs/SECURITY.md)
      try {
        E.writeDiscovery(ENGINE_FILE, E.discoveryRecord({ backendPort: ports.backend, modelsPort: ports.models, token: TOKEN, version: APP_VERSION }));
      } catch (e) { log("engine.json not written:", e.message); }
      createMain(origin);
      watchHealth();
      await confirmUpdates();
      setTimeout(fetchOptional, 20000);
      setTimeout(() => runUpdates("launch"), 30000);   // non-blocking, after the UI is up; offline: nothing changes
      watchCheckRequests();
      watchWanted();
    }
  });
  app.on("window-all-closed", () => app.quit());
  let stopped = false;
  app.on("before-quit", (e) => {
    if (stopped) return;
    e.preventDefault();
    stopAll().finally(() => { stopped = true; app.quit(); });
  });
  process.on("exit", () => { for (const k of Object.values(kids)) if (k.proc) S.killTreeSync(k.proc.pid); E.removeDiscovery(ENGINE_FILE); });
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) process.on(sig, () => app.quit());
}
