// The grown-up gate (docs/MEDIA.md): a link out of a NASA video (the YouTube logo, "Watch on YouTube", the title)
// opens in the system browser only after a grown-up holds a button for 3 seconds (gate.html). Everything else that
// leaves the app keeps the old rule (main.js: http(s) links open in the browser). No Electron import: tested with fakes.
"use strict";

/** "youtube": needs the gate; "external": another web link (opens as before); "ours": our own page; null: never. */
function classifyOpen(url, origin) {
  let u; try { u = new URL(url); } catch { return null; }
  if (u.origin === origin) return "ours";
  if (u.protocol !== "https:" && u.protocol !== "http:") return null;
  const h = u.hostname;
  if (h === "youtu.be" || h === "youtube.com" || h.endsWith(".youtube.com") || h === "www.youtube-nocookie.com" || h.endsWith(".google.com")) return "youtube";
  return "external";
}

/**
 * Show the gate over `parent`; resolve true only on the 3-second hold. One gate at a time (a second link while it is
 * up resolves false). makeWindow(opts) → a BrowserWindow-like {loadFile, on, once, close, isDestroyed, webContents}.
 */
function createGate({ makeWindow, file, log = () => {} }) {
  let open = null;
  return function gate(parent, url) {
    if (open) return Promise.resolve(false);
    return (open = new Promise((resolve) => {
      const w = makeWindow({ parent, modal: true, width: 520, height: 300, resizable: false, minimizable: false, maximizable: false,
        fullscreenable: false, title: "Ask a grown-up", backgroundColor: "#05070d", show: false,
        webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
      let done = false;
      const finish = (ok) => { if (done) return; done = true; open = null; log("grown-up gate", ok ? "opened" : "declined", url.slice(0, 120)); if (!w.isDestroyed()) w.close(); resolve(ok); };
      w.webContents.on("page-title-updated", (_e, title) => { if (title === "go") finish(true); else if (title === "no") finish(false); });
      w.webContents.on("will-navigate", (e) => e.preventDefault());
      w.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
      w.on("closed", () => finish(false));
      w.once("ready-to-show", () => w.show());
      w.loadFile(file);
    }));
  };
}

module.exports = { classifyOpen, createGate };
