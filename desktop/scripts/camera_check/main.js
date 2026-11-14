// Camera check: the desktop app's camera path in real Electron, without the Python/model bundle (docs/GESTURES.md).
// Packaged by camera_check.sh with the SAME Info.plist keys and entitlements as Outpost Luna, and the SAME session lockdown
// (permissions.js, copied from desktop/main). It loads the UI from a running backend (which serves frontend/dist exactly
// as the packaged backend does), turns gestures on the way Settings does, and writes what happened to OUT as JSON:
// permission prompt result, fps, inference ms, delegate, indicator, off-origin requests, CPU.
//   OUTPOST_ORIGIN=http://127.0.0.1:8390 OUT=/tmp/cc.json FAKE_CAMERA=1 "Outpost Luna Camera Check.app/Contents/MacOS/…"
// FAKE_CAMERA=1 uses Chromium's fake camera and skips the macOS prompt (CI / no webcam); otherwise the real camera.
"use strict";
const { app, BrowserWindow, session, systemPreferences } = require("electron");
const fs = require("fs");
const { lockDownSession } = require("./permissions");

const ORIGIN = process.env.OUTPOST_ORIGIN || "http://127.0.0.1:8390";
const OUT = process.env.OUT || "/tmp/outpost-camera-check.json";
const FAKE = process.env.FAKE_CAMERA === "1";
const SECONDS = +(process.env.SECONDS_ON || 15);
if (FAKE) app.commandLine.appendSwitch("use-fake-device-for-media-stream");

const res = { origin: ORIGIN, fake: FAKE, electron: process.versions.electron, chrome: process.versions.chrome, log: [], blocked: [] };
const log = (...a) => { const l = a.join(" "); res.log.push(l); if (a[0] === "blocked") res.blocked.push(a[1]); };
const done = (extra) => { Object.assign(res, extra); fs.writeFileSync(OUT, JSON.stringify(res, null, 2)); app.quit(); };

app.whenReady().then(async () => {
  res.cameraStatusBefore = process.platform === "darwin" ? systemPreferences.getMediaAccessStatus("camera") : "n/a";
  lockDownSession(session.defaultSession, ORIGIN, { log, systemPreferences: FAKE ? null : systemPreferences });
  const win = new BrowserWindow({ width: 1280, height: 800, title: "Outpost Luna camera check",
    webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  setTimeout(() => done({ error: "timeout" }), (SECONDS + 90) * 1000);
  await win.loadURL(ORIGIN + "/");
  const js = (s) => win.webContents.executeJavaScript(s, true);
  for (let i = 0; i < 60 && !(await js("!!(window.__outpost && window.__outpost.gestures)")); i++) await new Promise((r) => setTimeout(r, 500));
  res.offByDefault = await js("!window.__outpost.gestures.active && document.getElementById('gxIndicator').hidden");
  // Settings → Camera & gestures → on (the same call the switch makes)
  await js("window.__outpost.gestures.enable()");
  const t0 = Date.now();
  let st = null;
  while (Date.now() - t0 < 60000) { st = await js("window.__outpost.gestures.stats"); if (st.state === "on" && st.frames > 10) break; if (st.state === "denied" || st.state === "error") break; await new Promise((r) => setTimeout(r, 500)); }
  res.firstFramesMs = Date.now() - t0;
  if (st.state !== "on") return done({ state: st.state, stats: st, settingsText: await js("(document.querySelector('.gx-state')||{}).textContent || ''"), cameraStatusAfter: process.platform === "darwin" ? systemPreferences.getMediaAccessStatus("camera") : "n/a" });
  const cpu0 = app.getAppMetrics().reduce((a, m) => a + m.cpu.percentCPUUsage, 0);
  await new Promise((r) => setTimeout(r, SECONDS * 1000));
  const metrics = app.getAppMetrics();
  st = await js("window.__outpost.gestures.stats");
  const indicator = await js("(() => { const e = document.getElementById('gxIndicator'); return { visible: !e.hidden, inTopBar: !!e.closest('.topbar, .topnav'), text: e.textContent.trim() }; })()");
  const assets = await js("performance.getEntriesByType('resource').filter(e => /vision|worker/.test(e.name)).map(e => e.name.replace(location.origin, ''))");
  await js("window.__outpost.gestures.disable()");
  await new Promise((r) => setTimeout(r, 800));
  done({
    state: "on", stats: st, indicator, assets,
    cpuPercentAllProcesses: Math.round(metrics.reduce((a, m) => a + m.cpu.percentCPUUsage, 0)), cpuAtStart: Math.round(cpu0),
    processes: metrics.map((m) => ({ type: m.type, cpu: Math.round(m.cpu.percentCPUUsage), mb: Math.round((m.memory.workingSetSize || 0) / 1024) })),
    offAfterTurnOff: await js("!window.__outpost.gestures.active && !document.querySelector('.gx-video').srcObject"),
    cameraStatusAfter: process.platform === "darwin" ? systemPreferences.getMediaAccessStatus("camera") : "n/a",
  });
});
