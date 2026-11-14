// keys.js: the shell never takes the page's keys, and a packaged build can't be reloaded by accident.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { blockedInput, menuTemplate, installKeys, shellAction } = require("./keys");

const kd = (o) => ({ type: "keyDown", key: "", code: "", meta: false, control: false, shift: false, alt: false, ...o });
const roles = (t) => JSON.stringify(t).match(/"role":"(\w+)"/g).map((s) => s.slice(8, -1));

test("packaged: reload, force reload, F5 and dev tools are blocked on both platforms", () => {
  for (const platform of ["darwin", "win32"]) {
    const mod = platform === "darwin" ? { meta: true } : { control: true };
    assert.ok(blockedInput(kd({ ...mod, key: "r", code: "KeyR" }), { platform }), platform + " reload");
    assert.ok(blockedInput(kd({ ...mod, shift: true, key: "R", code: "KeyR" }), { platform }), platform + " force reload");
    assert.ok(blockedInput(kd({ key: "F5", code: "F5" }), { platform }), platform + " F5");
    assert.ok(blockedInput(kd({ key: "F12", code: "F12" }), { platform }), platform + " F12");
    assert.ok(blockedInput(kd({ ...mod, shift: true, key: "I", code: "KeyI" }), { platform }), platform + " dev tools");
  }
});

test("the page's own keys always pass: arrows, Enter, Esc, Backspace, Space, letters, Alt shortcuts, quit", () => {
  const pass = [{ key: "ArrowLeft", code: "ArrowLeft" }, { key: "Enter", code: "Enter" }, { key: "Escape", code: "Escape" }, { key: "Backspace", code: "Backspace" },
    { key: " ", code: "Space" }, { key: "m", code: "KeyM" }, { key: "r", code: "KeyR" }, { key: "/", code: "Slash" }, { key: "?", code: "Slash", shift: true },
    { key: "y", code: "KeyY", alt: true }, { key: "ArrowRight", code: "ArrowRight", alt: true }, { key: "a", code: "KeyA", alt: true }, { key: "w", code: "KeyW", alt: true },
    { key: "q", code: "KeyQ", meta: true }, { key: "c", code: "KeyC", control: true }, { key: "v", code: "KeyV", meta: true }];
  for (const platform of ["darwin", "win32"]) for (const k of pass) assert.equal(blockedInput(kd(k), { platform }), false, `${platform} ${JSON.stringify(k)}`);
});

test("dev builds keep reload and dev tools; key-up events are never blocked", () => {
  assert.equal(blockedInput(kd({ meta: true, key: "r", code: "KeyR" }), { packaged: false, platform: "darwin" }), false);
  assert.equal(blockedInput({ type: "keyUp", key: "F5", code: "F5" }, { platform: "win32" }), false);
});

test("menus: macOS keeps quit + edit, never reload or close; Windows packaged has no menu bar", () => {
  const mac = roles(menuTemplate({ packaged: true, platform: "darwin" }));
  for (const r of ["quit", "copy", "paste", "selectAll", "togglefullscreen"]) assert.ok(mac.includes(r), r);
  for (const r of ["reload", "forceReload", "toggleDevTools", "close"]) assert.ok(!mac.includes(r), r);
  assert.equal(menuTemplate({ packaged: true, platform: "win32" }), null);
  const dev = roles(menuTemplate({ packaged: false, platform: "win32" }));
  assert.ok(dev.includes("reload") && dev.includes("toggleDevTools"));
});

test("Windows packaged (no menu): Ctrl+= / Ctrl+- / Ctrl+0 zoom and F11 full screen, like the macOS View menu", () => {
  const w = { platform: "win32" };
  assert.equal(shellAction(kd({ control: true, key: "=", code: "Equal" }), w), "in");
  assert.equal(shellAction(kd({ control: true, shift: true, key: "+", code: "Equal" }), w), "in");
  assert.equal(shellAction(kd({ control: true, key: "-", code: "Minus" }), w), "out");
  assert.equal(shellAction(kd({ control: true, key: "0", code: "Digit0" }), w), "reset");
  assert.equal(shellAction(kd({ key: "F11", code: "F11" }), w), "fullscreen");
  // never the page's keys, never macOS (its menu does it), never a dev build (its View menu does it)
  for (const k of [{ key: "=", code: "Equal" }, { key: "0", code: "Digit0" }, { key: "y", code: "KeyY", alt: true }, { key: "c", code: "KeyC", control: true }])
    assert.equal(shellAction(kd(k), w), null, JSON.stringify(k));
  assert.equal(shellAction(kd({ meta: true, key: "=", code: "Equal" }), { platform: "darwin" }), null);
  assert.equal(shellAction(kd({ control: true, key: "=", code: "Equal" }), { platform: "win32", packaged: false }), null);
  assert.equal(shellAction({ type: "keyUp", key: "F11", code: "F11" }, w), null);
});

test("installKeys on Windows: no menu bar, blocked keys stop, Ctrl+= zooms the window", () => {
  let handler = null, menu = "unset", zoom = 0, full = false, hidden = false;
  const win = { webContents: { on: (ev, h) => { if (ev === "before-input-event") handler = h; }, getZoomLevel: () => zoom, setZoomLevel: (z) => { zoom = z; } },
    setMenuBarVisibility: (v) => { hidden = !v; }, isFullScreen: () => full, setFullScreen: (v) => { full = v; } };
  installKeys({ Menu: { setApplicationMenu: (m) => { menu = m; }, buildFromTemplate: (t) => t }, win, packaged: true, platform: "win32" });
  assert.equal(menu, null); assert.ok(hidden);
  const press = (o) => { let stopped = false; handler({ preventDefault: () => { stopped = true; } }, kd(o)); return stopped; };
  assert.ok(press({ key: "F5", code: "F5" }), "reload blocked");
  assert.ok(press({ control: true, key: "=", code: "Equal" })); assert.equal(zoom, 0.5);
  assert.ok(press({ control: true, key: "0", code: "Digit0" })); assert.equal(zoom, 0);
  assert.ok(press({ key: "F11", code: "F11" })); assert.ok(full);
  assert.equal(press({ key: "ArrowLeft", code: "ArrowLeft", alt: true }), false, "the page's Alt shortcuts pass");
});
