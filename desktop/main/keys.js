// The app menu and the keys the shell keeps from the page (docs/KEYBOARD.md §Desktop).
//
// The page is driven like a TV app with plain keys (arrows, Enter, Esc, letters) and a few Alt shortcuts (Alt+←/→, Y, N,
// ., A, W, P). The shell must not take any of them, and in a packaged build nothing a kid can press by accident may wipe
// the session: no reload (Cmd/Ctrl+R, Shift+Cmd/Ctrl+R, F5), no dev tools, no "close window" (the app quits when its
// only window closes). Quitting stays where people expect it: Cmd+Q on macOS, Alt+F4 / the window's close box on Windows.
//
// macOS keeps a small menu (Edit is needed for copy / paste in the text box). Windows and Linux get no menu bar in a
// packaged build, so Alt never opens a menu and Alt+letter mnemonics can't swallow the page's Alt shortcuts.
"use strict";

/** True when a before-input-event must not reach the page or the default menu (a reload, the dev tools). */
function blockedInput(input, { packaged = true, platform = process.platform } = {}) {
  if (!packaged || !input || input.type !== "keyDown") return false;
  const k = String(input.key || ""), code = String(input.code || ""), mod = platform === "darwin" ? input.meta : input.control;
  if (k === "F5" || code === "F5") return true;                                   // reload (Windows / Linux muscle memory)
  if (mod && (code === "KeyR" || k.toLowerCase() === "r")) return true;            // Cmd/Ctrl+R, Shift+Cmd/Ctrl+R
  if (k === "F12" || code === "F12") return true;                                 // dev tools
  if (mod && input.shift && (code === "KeyI" || code === "KeyJ" || code === "KeyC")) return true;   // dev tools / console / inspect
  if (platform === "darwin" && input.meta && input.alt && (code === "KeyI" || code === "KeyJ")) return true;
  if (k === "BrowserBack" || k === "BrowserForward") return true;                 // mouse / keyboard back buttons: the page owns back
  return false;
}

/** The application menu template (Menu.buildFromTemplate). null = no menu (Windows / Linux, packaged). */
function menuTemplate({ packaged = true, platform = process.platform, appName = "Outpost Luna" } = {}) {
  const dev = packaged ? [] : [{ type: "separator" }, { role: "reload" }, { role: "forceReload" }, { role: "toggleDevTools" }];
  const view = { label: "View", submenu: [{ role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { type: "separator" }, { role: "togglefullscreen" }, ...dev] };
  if (platform !== "darwin") return packaged ? null : [view];
  return [
    { label: appName, submenu: [{ role: "about" }, { type: "separator" }, { role: "hide" }, { role: "hideOthers" }, { role: "unhide" }, { type: "separator" }, { role: "quit" }] },
    { label: "Edit", submenu: [{ role: "undo" }, { role: "redo" }, { type: "separator" }, { role: "cut" }, { role: "copy" }, { role: "paste" }, { role: "selectAll" }] },
    view,
    { label: "Window", submenu: [{ role: "minimize" }, { role: "zoom" }] },   // no "close": Cmd+W would quit the only window
  ];
}

/** Wire both into a window: the menu (app-wide) and the input filter (this window). */
function installKeys({ Menu, win, packaged, platform = process.platform, appName }) {
  const t = menuTemplate({ packaged, platform, appName });
  Menu.setApplicationMenu(t ? Menu.buildFromTemplate(t) : null);
  if (win && win.webContents) win.webContents.on("before-input-event", (e, input) => { if (blockedInput(input, { packaged, platform })) e.preventDefault(); });
  if (win && !t && win.setMenuBarVisibility) win.setMenuBarVisibility(false);
}

module.exports = { blockedInput, menuTemplate, installKeys };
