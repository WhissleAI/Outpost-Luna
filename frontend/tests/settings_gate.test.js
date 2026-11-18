// Settings: the destructive buttons are behind the grown-up gate's 3-second hold (src/reset.js bindHold): Reset's
// confirm view and Settings → Videos → "Hold to clear saved videos" (the ~425 MB of saved copies). A click never counts.
import test, { mock } from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const RS = await import("../src/reset.js");
const UI = await import("../src/media/video_ui.js");

function fakeButton() {
  const on = {}, cls = new Set(), fill = { style: {} }, span = { textContent: "" };
  return {
    disabled: false, isConnected: false, fill, span,
    classList: { add: c => cls.add(c), remove: c => cls.delete(c), has: c => cls.has(c) },
    addEventListener: (ev, f) => (on[ev] = on[ev] || []).push(f),
    emit(ev, extra = {}) { (on[ev] || []).forEach(f => f({ preventDefault() {}, stopPropagation() {}, ...extra })); },
    querySelector: sel => (sel === ".rs-fill" ? fill : sel === "span" ? span : null),
  };
}
const flush = () => new Promise(r => setImmediate(r));

test("bindHold: a click or a short press does nothing; 3 s held (pointer or Enter) fires once", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    let fired = 0;
    const b = fakeButton();
    RS.bindHold(b, { onFire: () => { fired++; } });
    b.emit("click"); await flush();
    assert.equal(fired, 0);
    b.emit("pointerdown"); mock.timers.tick(2900); b.emit("pointerup"); mock.timers.tick(500); await flush();
    assert.equal(fired, 0);
    assert.equal(b.fill.style.width, "0%");
    b.emit("pointerdown"); mock.timers.tick(3000); await flush();
    assert.equal(fired, 1);
    assert.equal(b.disabled, true);
    b.emit("pointerdown"); mock.timers.tick(3000); await flush();
    assert.equal(fired, 1);                       // once

    const k = fakeButton(); let kf = 0;
    RS.bindHold(k, { onFire: () => { kf++; } });
    k.emit("keydown", { key: "Enter" }); mock.timers.tick(3000); await flush();
    assert.equal(kf, 1);
    assert.equal(RS.HOLD_MS, 3000);
  } finally { mock.timers.reset(); }
});

test("bindHold: a failed action re-arms the button", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    let n = 0;
    const b = fakeButton();
    RS.bindHold(b, { onFire: () => { n++; throw new Error("down"); } });
    b.emit("pointerdown"); mock.timers.tick(3000); await flush();
    assert.equal(n, 1);
    assert.equal(b.disabled, false);
    b.emit("pointerdown"); mock.timers.tick(3000); await flush();
    assert.equal(n, 2);
  } finally { mock.timers.reset(); }
});

test("Reset's confirm view and Settings → Videos use the same hold button", () => {
  assert.match(RS.confirmHtml("all"), /class="btn rs-hold" data-reset-hold><i class="rs-fill"/);
  const html = UI.settingsSection.html();
  assert.match(html, /class="btn rs-hold" data-vid-clear><i class="rs-fill" aria-hidden="true"><\/i><span>Hold to clear saved videos<\/span>/);
  assert.match(html, /hold for 3 seconds/);
  assert.doesNotMatch(html, />Clear saved videos</);
});

test("Settings → Videos: a click never deletes; the 3-second hold does, then the count refreshes", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const calls = [];
    const fetchFn = async (u, o = {}) => { calls.push(o.method || "GET"); return { json: async () => ({ bytes: o.method ? 0 : 425e6, pinned_ready: 14, pinned_total: 14 }) }; };
    const stat = { textContent: "" }, clear = fakeButton();
    const el = { querySelector: s => (s === "[data-vid-stat]" ? stat : s === "[data-vid-clear]" ? clear : null) };
    UI.settingsSection.bind(el, { fetchFn });
    await flush();
    assert.match(stat.textContent, /14 of 14 lesson videos ready/);
    clear.emit("click"); clear.emit("pointerdown"); mock.timers.tick(1000); clear.emit("pointerup"); await flush();
    assert.ok(!calls.includes("DELETE"));
    clear.emit("pointerdown"); mock.timers.tick(3000); await flush(); await flush();
    assert.ok(calls.includes("DELETE"));
    assert.equal(clear.span.textContent, "Cleared");
  } finally { mock.timers.reset(); }
});

test("Settings → Videos copy: the v2 video pack (14 NASA videos, ~425 MB, offline), not 'after the first time online'", () => {
  const html = UI.settingsSection.html();
  assert.match(html, /14 videos, about 425 MB/);
  assert.match(html, /offline/);
  assert.doesNotMatch(html, /first time online/);
});
