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
//  10. app updates (appupdate.js, docs/DESKTOP.md "App updates"): Settings -> App version -> "Check for updates" asks
//      GitHub for the latest release (manual; or once a day on launch when the user opted in) and "Download" fetches the
//      installer into the Downloads folder itself (no browser needed), checks its size + sha256 and opens it (macOS
//      mounts the dmg; a Windows .exe is only shown in its folder). Nothing is installed by the app.
//      Every web link (openOutside) is awaited: when the system browser does not open, the page shows the link to copy.
//  11. School network mode (netpolicy.js, docs/SCHOOL_IT.md): an IT admin's machine policy or a grown-up's switch stops
//      every outbound connection except to an allow list (none by default): the page's (session.webRequest), the
//      shell's own downloads (globalThis.fetch is gated) and both servers' (LUNA_NET_POLICY -> app/netgate.py).
//      Hardening in one place (hardening.js): every window's webPreferences, the page's CSP, navigation and links.
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
const PT = require("./playtest");   // Settings -> For grown-ups -> "Export playtest" (docs/DIRECTOR_LOOP.md §1b)
const AU = require("./appupdate"); // Settings -> "Check for updates" (GitHub releases; manual unless opted in)
const NP = require("./netpolicy");  // School network mode: the policy and the gated fetch (docs/SCHOOL_IT.md)
const H = require("./hardening");   // webPreferences, CSP, navigation and link allow-lists, Chromium features off

// Tests and demos run against their own data folder, never the owner's real "Outpost Luna" one.
if (process.env.OUTPOST_USER_DATA) app.setPath("userData", process.env.OUTPOST_USER_DATA);
const RES = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..", "resources");
const USER = app.getPath("userData");                   // ~/Library/Application Support/Outpost Luna, %APPDATA%\Outpost Luna
const LOGS = path.join(USER, "logs");
// School network mode (netpolicy.js): the machine policy is read once (an IT admin changes it, then the app restarts);
// the grown-up's switch (<userData>/network.json, written by the backend) is re-read when it changes.
const MACHINE_POLICY = NP.readMachine({ execPath: process.execPath });
const USER_NET_FILE = path.join(USER, NP.USER_NAME);
let netPol = NP.effective(MACHINE_POLICY, NP.readUser(USER_NET_FILE));
globalThis.fetch = NP.gateFetch(globalThis.fetch, () => netPol, (...a) => log(...a));   // every shell download goes through it
// Chromium never looks for other devices on the network (Cast / DIAL discovery uses mDNS and SSDP)
app.commandLine.appendSwitch("disable-features", H.CHROMIUM_OFF.join(","));
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
    LUNA_LOG_DIR: LOGS, LUNA_DATA_DIR: USER,   // [#92] <svc>.jsonl logs + metrics/daily-<svc>.json (app/diag.py)
    ORT_DISABLE_TELEMETRY: "1",     // ONNX Runtime's built-in Microsoft telemetry: off (no network after setup)
    LUNA_NET_POLICY: JSON.stringify(MACHINE_POLICY) };   // School network mode: the machine policy (app/netgate.py)
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
    NASA_VIEWS_DIR: a.NASA_VIEWS_DIR,     // 0.4 real NASA views: star map, 3D models, Moon rocks, images (optional asset)
    MOON_VIEWS_DIR: a.MOON_VIEWS_DIR,     // open Moon data: Apollo surface photos, USGS rock ages, Columbia 3D, sample facts (optional asset)
    VOICE_PACK_DIR: a.VOICE_PACK_DIR,
    // Settings -> About / Storage: GET /api/assets reads the summary, POST /api/assets/check asks for a check
    ASSETS_STATE_FILE: path.join(store.dir, "summary.json"),
    ASSETS_CHECK_FILE: path.join(store.dir, "check-request"),
    ASSETS_DIR: store.dir,                // the backend asks for an optional asset (.want/<id>) and shows its state
    ASSETS_MANIFEST: MANIFEST,            // [courses] the catalog the backend lists course packs from (and checks built-ins against)
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
  P.lockDownSession(session.defaultSession, origin, { log, systemPreferences, referer: process.env.OUTPOST_YT_REFERER === "1",
    policy: () => netPol, csp: H.csp(origin) });
  session.defaultSession.setSpellCheckerEnabled(false);   // Windows would download dictionaries from Google
}
/** The grown-up's switch changed (the backend wrote network.json): the page and the shell follow at once. */
function watchNetPolicy() {
  fs.watchFile(USER_NET_FILE, { interval: 1000 }, () => {
    const was = netPol.school_network;
    netPol = NP.effective(MACHINE_POLICY, NP.readUser(USER_NET_FILE));
    if (was !== netPol.school_network) { log(`school network: ${netPol.school_network ? "on" : "off"} (${netPol.source})`); jlog.event("school_network", { on: netPol.school_network, source: netPol.source }); }
  });
}
/**
 * The system browser, awaited (appupdate.openWithFallback). A Mac whose default browser app is gone rejects
 * (LaunchServices -10810, "The application can't be opened"): that is logged and the page is told, so it shows the
 * link with a Copy button (window.__lunaLink, frontend/src/link_fallback_ui.js; the update row for its own links).
 * Test runs only: OUTPOST_TEST_OPEN_FAIL=1 makes every open fail that way.
 */
function openOutside(url, where, onFail) {
  return AU.openWithFallback(url, {
    open: (u) => (TESTING && process.env.OUTPOST_TEST_OPEN_FAIL === "1" ? Promise.reject(new Error("test: no browser (-10810)")) : shell.openExternal(u)),
    log: (...a) => log(`[${where}]`, ...a),
    onFail: (u) => {
      jlog.event("open_external_failed", { where });
      if (onFail) onFail(u);
      else if (win && !win.isDestroyed()) win.webContents.executeJavaScript(`window.__lunaLink && window.__lunaLink(${JSON.stringify({ url: u })})`).catch(() => {});
    },
  });
}
/** A web link the page asked for: allow-listed (hardening.linkAllowed) and not switched off by the policy. */
function openLink(url, kind) {
  if (!netPol.open_links) { log("link not opened (policy: open_links off)", url.slice(0, 120)); return; }
  if (kind === "youtube") gate(win, url).then((ok) => { if (ok) return openOutside(url, "youtube"); });   // [media] grown-up gate
  else if (kind === "external") openOutside(url, "link");
  else log("link refused (not on the list)", url.slice(0, 120));
}
const gate = G.createGate({ makeWindow: (o) => new BrowserWindow(o), file: path.join(__dirname, "gate.html"), log });

function createSplash() {
  splash = new BrowserWindow({ width: 460, height: 300, frame: false, resizable: false, show: false, backgroundColor: "#05070d",
    webPreferences: { ...H.WEB_PREFS } });
  splash.webContents.on("will-navigate", (e) => e.preventDefault());
  splash.loadFile(path.join(__dirname, "splash.html"));
  splash.once("ready-to-show", () => reveal(splash));
}

function createMain(origin) {
  win = new BrowserWindow({ width: 1440, height: 900, minWidth: 960, minHeight: 640, show: false, backgroundColor: "#05070d",
    title: "Outpost Luna", webPreferences: { ...H.WEB_PREFS } });
  K.installKeys({ Menu, win, packaged: app.isPackaged, appName: "Outpost Luna" });   // [keys]
  win.webContents.setWindowOpenHandler(({ url }) => {   // no new windows, ever: a link opens in the system browser, or not
    const kind = H.navigation(url, origin, G.classifyOpen);
    if (kind !== "ours") openLink(url, kind);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (e, url) => {
    // Settings → Reset: the page asked the backend (which returned a one-time token), now the shell does its part
    const r = R.parseResetUrl(url, origin);
    if (r) { e.preventDefault(); resetApp(r, origin); return; }
    // Settings → Help & diagnostics → "Save a diagnostics file…" (#92): the user picks where; nothing is uploaded
    if (D.isDiagUrl(url, origin)) { e.preventDefault(); saveDiagnostics(origin, /[?&]names=1\b/.test(url)); return; }
    // Settings → For grown-ups → "Export playtest": the grown-up picks where; nothing is uploaded
    if (PT.isExportUrl(url, origin)) { e.preventDefault(); exportPlaytest(origin); return; }
    // Settings → App version → "Check for updates" / "Download": the shell asks GitHub and downloads the installer
    const up = AU.parseUpdateUrl(url, origin);
    if (up) {
      e.preventDefault();
      if (up.do === "check") checkAppUpdate("Settings");
      else if (up.what === "download") downloadAppUpdate();
      else if (up.what === "folder") showDownloaded();
      else openUpdateTarget(up.what);
      return;
    }
    const kind = H.navigation(url, origin, G.classifyOpen);
    if (kind !== "ours") { e.preventDefault(); openLink(url, kind); }
  });
  win.once("ready-to-show", () => {
    reveal(win);
    if (splash && !splash.isDestroyed()) splash.close();
    log(`window ${HEADLESS ? "ready (headless)" : "shown"} after ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  });
  win.on("closed", () => { win = null; });
  win.webContents.on("did-finish-load", pushEngine);   // a reload gets the engine state again
  win.webContents.on("did-finish-load", helloAppUpdate);   // the version for Settings; the opt-in daily check
  win.webContents.on("did-finish-load", helloAssets);      // the opt-in daily check for new models and media
  win.loadURL(origin + "/");
}

// ---- Settings → App version → "Check for updates" (appupdate.js) ----------------------------------------------------
// Test runs only (unpackaged, like OUTPOST_DIAG_SAVE_PATH): OUTPOST_TEST_APP_VERSION pretends to be another version;
// OUTPOST_TEST_OPEN_LOG appends the URL "Release page" / "Open the site" would open (and "openPath <file>" for a finished
// download, "showItemInFolder <file>" for "Show in folder") to that file instead of opening anything; OUTPOST_TEST_DOWNLOAD_DIR saves the installer there, not Downloads.
const TESTING = !app.isPackaged;
const UPDATE_VERSION = (TESTING && process.env.OUTPOST_TEST_APP_VERSION) || APP_VERSION;
const autoGate = AU.createAutoGate({ file: path.join(USER, "update-check.json") });
let appUpdate = null, appUpdateBusy = false;
let dl = null;              // the installer download: {state: "downloading"|"done"|"failed", got, total, name, reason, version}
let dlFile = null;          // where the last finished download landed (for "Show in folder")
function pushUpdate(s) {
  if (!win || win.isDestroyed()) return Promise.resolve(null);
  if (dl && s && s.state === "available" && s.latest === dl.version) s = { ...s, dl };   // a check mid-download keeps its bar
  return win.webContents.executeJavaScript(`window.__lunaUpdate ? window.__lunaUpdate(${JSON.stringify(s)}) : null`).catch(() => null);
}
/** The page loaded: tell it the version; it answers whether the user opted in to the daily check. */
async function helloAppUpdate() {
  const r = await pushUpdate(appUpdate && appUpdate.state === "available" ? appUpdate : { state: "idle", current: UPDATE_VERSION });
  if (r && r.auto === true && !appUpdate && autoGate.due()) {
    autoGate.mark();   // the attempt counts: at most one request a day, online or not
    setTimeout(() => checkAppUpdate("auto"), 5000);
  }
}
async function checkAppUpdate(why) {
  if (appUpdateBusy) return;
  appUpdateBusy = true;
  const auto = why === "auto";
  try {
    if (!auto) pushUpdate({ state: "checking", current: UPDATE_VERSION });
    const r = await AU.check({ appVersion: UPDATE_VERSION, platform: process.platform });
    appUpdate = r;
    log(`app update check (${why}): ${r.state}${r.latest ? " " + r.latest : ""}${r.reason ? " (" + r.reason + ": " + r.detail + ")" : ""}`);
    jlog.event("app_update_check", { why, state: r.state, latest: r.latest || null, reason: r.reason || null });
    if (!auto || r.state === "available") pushUpdate({ ...r, auto });   // the opt-in check is silent unless there is one
  } finally { appUpdateBusy = false; }
}
function openUpdateTarget(what) {
  const url = AU.targetUrl(appUpdate, what);
  if (!url) { log(`app update: open ${what} refused (nothing allow-listed to open)`); return; }
  log(`app update: opening ${what} ${url}`);
  if (TESTING && process.env.OUTPOST_TEST_OPEN_LOG && process.env.OUTPOST_TEST_OPEN_FAIL !== "1") { fs.appendFileSync(process.env.OUTPOST_TEST_OPEN_LOG, url + "\n"); return; }
  // no browser: the row shows the link with a Copy button
  openOutside(url, "app update", (u) => pushUpdate({ ...(appUpdate || { state: "idle", current: UPDATE_VERSION }), link_failed: u }));
}
/**
 * "Download": the main process fetches the installer itself (appupdate.downloadInstaller), never a browser. Into the
 * Downloads folder under a fresh name, size + sha256 checked against the release; progress, done or failed go to the
 * page. Then macOS opens the dmg (mounts it) and shows it in Finder; Windows only shows the .exe in its folder.
 */
async function downloadAppUpdate() {
  if (!appUpdate || appUpdate.state !== "available" || !appUpdate.download) { log("app update: download refused (no installer found)"); return; }
  if (dl && dl.state === "downloading") return;
  const rel = appUpdate;
  const dir = (TESTING && process.env.OUTPOST_TEST_DOWNLOAD_DIR) || app.getPath("downloads");
  dl = { state: "downloading", got: 0, total: rel.size || null, name: rel.asset, version: rel.latest };
  pushUpdate(rel);
  // test runs only: OUTPOST_TEST_DOWNLOAD_BREAK=size (the release's size is off by one: refused before any byte is
  // written) | sha (a wrong sha256: the whole file arrives, then fails the check and its .part is removed)
  const brk = TESTING && process.env.OUTPOST_TEST_DOWNLOAD_BREAK;
  const last = brk === "size" ? { ...rel, size: (rel.size || 0) + 1 } : brk === "sha" ? { ...rel, sha_url: null, digest: "0".repeat(64) } : rel;
  log(`app update: downloading ${rel.asset} ${rel.latest} (${last.size || "?"} bytes, ${last.sha_url ? "sha256 file" : last.digest ? "digest" : "size only"})${brk ? ` [test: broken ${brk}]` : ""}`);
  let lastPush = 0;
  const realFetch = globalThis.fetch.__real || globalThis.fetch;   // getAsset checks the policy hop by hop itself
  try {
    const r = await AU.downloadInstaller({ last, dir, fetchImpl: realFetch, appVersion: UPDATE_VERSION,
      hostOk: (h) => NP.hostAllowed(h, netPol),
      onProgress: (got, total) => {
        dl = { ...dl, got, total };
        const t = Date.now();
        if (t - lastPush > 250) { lastPush = t; pushUpdate(appUpdate && appUpdate.latest === rel.latest ? appUpdate : rel); }
      } });
    dlFile = r.file;
    dl = { state: "done", got: r.bytes, total: r.bytes, name: path.basename(r.file), version: rel.latest, verified: r.verified };
    log(`app update: downloaded ${r.bytes} bytes to ${r.file} (${r.verified} checked)`);
    jlog.event("app_update_download", { ok: true, latest: rel.latest, bytes: r.bytes, verified: r.verified });
    pushUpdate(appUpdate && appUpdate.latest === rel.latest ? appUpdate : rel);
    if (TESTING && process.env.OUTPOST_TEST_OPEN_LOG) { fs.appendFileSync(process.env.OUTPOST_TEST_OPEN_LOG, `openPath ${r.file}\n`); return; }
    if (process.platform === "darwin") {
      const err = await shell.openPath(r.file);   // mounts the dmg: the drag-to-Applications window, no browser
      if (err) log(`app update: could not open the dmg: ${err}`);
    }
    shell.showItemInFolder(r.file);   // Windows: only this; the installer is never run by the app
  } catch (e) {
    dl = { state: "failed", reason: e.kind || "error", name: rel.asset, version: rel.latest };
    log(`app update: download failed (${dl.reason}): ${e.message}`);
    jlog.event("app_update_download", { ok: false, latest: rel.latest, reason: dl.reason });
    pushUpdate(appUpdate && appUpdate.latest === rel.latest ? appUpdate : rel);
  }
}
function showDownloaded() {
  if (TESTING && process.env.OUTPOST_TEST_OPEN_LOG) { fs.appendFileSync(process.env.OUTPOST_TEST_OPEN_LOG, `showItemInFolder ${dlFile || "downloads"}\n`); return; }
  if (dlFile && fs.existsSync(dlFile)) shell.showItemInFolder(dlFile);
  else shell.openPath(app.getPath("downloads")).then((err) => { if (err) log(`app update: could not open Downloads: ${err}`); });
}

// ---- Settings → Help & diagnostics (#92, diag.js) -------------------------------------------------------------------
let diagBusy = false;
function diagState(state) {
  if (win && !win.isDestroyed()) win.webContents.executeJavaScript(`window.__lunaDiag && window.__lunaDiag(${JSON.stringify({ state })})`).catch(() => {});
}
async function saveDiagnostics(origin, names = false) {
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
    if (names) shell.learning_aliases = true;   // a grown-up ticked "Include learned names" (docs/ON_DEVICE_LEARNING.md)
    const bytes = await D.saveBundle({ backend: origin, token: TOKEN, shell, file });
    log(`diagnostics: saved a ${Math.round(bytes / 1024)} KB file`);
    jlog.event("diagnostics_saved", { bytes });
    diagState("saved");
  } catch (e) {
    log("diagnostics: not saved:", e.message);
    diagState("error");
  } finally { diagBusy = false; }
}

// ---- Settings → For grown-ups → Playtest session → "Export playtest" (playtest.js) ----------------------------------
let ptBusy = false;
function ptState(state) {
  if (win && !win.isDestroyed()) win.webContents.executeJavaScript(`window.__lunaPlaytest && window.__lunaPlaytest(${JSON.stringify({ state })})`).catch(() => {});
}
async function exportPlaytest(origin) {
  if (ptBusy || !win) return;
  ptBusy = true;
  try {
    // OUTPOST_PLAYTEST_SAVE_PATH: test runs only (like OUTPOST_DIAG_SAVE_PATH): no dialog, this file
    let file = (TESTING && process.env.OUTPOST_PLAYTEST_SAVE_PATH) || "";
    if (!file) {
      const r = await dialog.showSaveDialog(win, { title: "Export playtest",
        defaultPath: path.join(app.getPath("downloads"), PT.defaultName()), filters: [{ name: "Zip", extensions: ["zip"] }] });
      if (r.canceled || !r.filePath) { ptState("cancelled"); return; }
      file = r.filePath;
    }
    ptState("saving");
    const bytes = await PT.saveExport({ backend: origin, token: TOKEN, appVersion: APP_VERSION, file });
    log(`playtest: exported a ${Math.round(bytes / 1024)} KB file`);
    jlog.event("playtest_exported", { bytes });
    ptState("saved");
  } catch (e) {
    log("playtest: not exported:", e.message);
    ptState("error");
  } finally { ptBusy = false; }
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
const SCHOOL_MSG = "School network mode is on, so nothing downloads. Import the offline pack from a USB stick.";
let firstrun = null, frAbort = null, frState = {}, frWaiters = [], frBusy = false;
const progress = {};        // id -> bytes done (for the screen)

function frSend(extra = {}) {
  frState = { ...frState, ...extra,
    assets: store.status().filter((x) => x.required).map((x) => ({ ...x, done: progress[x.id] || 0 })) };
  if (firstrun && !firstrun.isDestroyed()) firstrun.webContents.send("firstrun:state", frState);
}

function requiredReady() { return store.status().filter((x) => x.required).every((x) => x.state === "installed"); }

function createFirstRun() {
  firstrun = new BrowserWindow({ width: 560, height: 540, frame: false, resizable: false, show: false, backgroundColor: "#05070d",
    webPreferences: { ...H.WEB_PREFS, preload: path.join(__dirname, "firstrun-preload.js") } });
  firstrun.webContents.on("will-navigate", (e) => e.preventDefault());
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
        message: e.school ? SCHOOL_MSG : AS.isNetworkError(e) ? OFFLINE_MSG : e.disk ? e.message : `The download stopped (${e.message}). Try again, or import the offline pack.` });
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
    const gone = store.removals()[0];   // a grown-up removed a course pack (Settings → Storage; docs/COURSES.md §4.2)
    if (gone) {
      wantBusy = true;
      try { await store.remove(gone); log(`assets: ${gone} removed (asked for)`); }
      catch (e) { log(`assets: ${gone} not removed yet (${e.message})`); }
      finally { wantBusy = false; }
      return;
    }
    const id = store.wanted()[0];
    if (!id) return;
    wantBusy = true;
    try { await store.download(id); log(`assets: ${id} installed (asked for)`); }
    catch (e) {
      log(`assets: ${id} not downloaded (${e.message})`);
      // a course pack: said plainly in Settings → Storage (backend/app/course_packs.py reads it) and the ask is dropped,
      // so a blocked or offline download doesn't retry every 2 s (the Steer voice keeps its old behaviour)
      if (store.removable(id)) {
        store.failed(id, e.school ? SCHOOL_MSG : AS.isNetworkError(e) ? OFFLINE_MSG : e.disk ? e.message : "The download stopped. Try again.");
        try { require("fs").rmSync(require("path").join(store.dir, ".want", id), { force: true }); } catch { /* */ }
      }
    }
    finally { wantBusy = false; }
  }, 2000);
}

/** After the UI is up: the optional assets (crew audio, videos), quietly; a failure waits for the next launch. An
 *  `on_demand` asset (the Steer voice) is never fetched here: only when the kid picks it in Settings (watchWanted). */
async function fetchOptional() {
  if (netPol.school_network) { log("assets: optional downloads skipped (school network mode)"); return; }
  const todo = U.setupNeeds(store.status(), store.manifest).optional;   // empty once setup is done: no request at all
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

// The check for NEW models and media is opt-in (the app promises no network after setup): Settings -> Storage & updates
// -> "Check for new models and media automatically" (prefs.assets_check, off by default). The page answers
// window.__lunaAssets() when it loads; when on, a launch checks at most once a day (the last attempt is kept in
// <userData>/asset-check.json). The button ("Check for new models and media") always works (watchCheckRequests).
const assetGate = AU.createAutoGate({ file: path.join(USER, "asset-check.json") });
let assetAutoScheduled = false;
async function helloAssets() {
  if (assetAutoScheduled || !win || win.isDestroyed()) return;
  const r = await win.webContents.executeJavaScript("window.__lunaAssets ? window.__lunaAssets() : null").catch(() => null);
  if (assetAutoScheduled || netPol.school_network || !U.autoCheckDue(r, assetGate)) return;
  assetAutoScheduled = true;   // one per launch, even if the page reloads
  assetGate.mark();            // the attempt counts: at most one request a day, online or not
  setTimeout(() => runUpdates("auto"), U.AUTO_CHECK_DELAY_MS);   // non-blocking, after the UI is up
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
  // Every web contents, now and later: no <webview>, no new windows unless a handler set later says otherwise (the main
  // window's sends links to the system browser and still denies the window)
  app.on("web-contents-created", (_e, wc) => {
    wc.on("will-attach-webview", (e) => { e.preventDefault(); log("webview refused"); });
    wc.setWindowOpenHandler(() => ({ action: "deny" }));
  });
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    if (HEADLESS && app.dock) app.dock.hide();
    fs.mkdirSync(LOGS, { recursive: true });
    for (const n of ["main", "backend", "models"]) D.rotateText(path.join(LOGS, `${n}.log`));   // [#92] capped: 5 MB + one old
    const { previous } = tracker.begin();   // [#92] a session = one launch; the last one unfinished = not crash-free
    jlog.event("launch", { version: APP_VERSION, platform: process.platform, arch: process.arch, previous_session: previous });
    log(`Outpost Luna ${app.getVersion()} (${process.platform} ${process.arch}); resources ${RES}; data ${USER}`);
    if (netPol.school_network) log(`school network: on (${netPol.source}${MACHINE_POLICY.source ? ": " + MACHINE_POLICY.source : ""}); allowed: ${netPol.allow_hosts.join(", ") || "nothing"}`);
    watchNetPolicy();
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
      // no launch-time check for new models and media: opt-in only (helloAssets), or the Settings button
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
