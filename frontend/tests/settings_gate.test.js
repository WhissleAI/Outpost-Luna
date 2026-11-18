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

// [0.4.1] Settings → For grown-ups: Reset, Clear saved videos, Save diagnostics, What the app has learned and Reset my
// patches sit in one section behind the 3-second hold; the kids' settings (voice, speed, theme, captions) stay open.
test("For grown-ups: locked, it shows only the gate's hold and what is inside; open, every grown-up part", async () => {
  const A = await import("../src/a11y.js");
  const locked = A.grownupsHtml({ open: false, parts: [{ id: "reset", title: "Reset", html: "<button data-reset-open>" }] });
  assert.ok(locked.includes("data-gu-open") && locked.includes("rs-hold") && locked.includes(A.GROWNUPS.hold));
  assert.ok(!locked.includes("data-reset-open"), "nothing inside is reachable before the hold");
  for (const t of ["Reset the app", "Clear saved videos", "Save diagnostics", "What the app has learned", "Reset my patches"]) assert.ok(locked.includes(t), t);
  const open = A.grownupsHtml({ open: true, parts: [{ id: "reset", title: "Reset", html: "<b>R</b>" }, { id: "videos", title: "Videos", html: "<b>V</b>" }] });
  assert.ok(!open.includes("data-gu-open"));
  assert.match(open, /data-gu="reset"[\s\S]*data-gu="videos"/);
});

test("For grown-ups: the videos, diagnostics and learning sections are grown-up parts; the kids' sections are not", async () => {
  const fs = await import("node:fs");
  const src = f => fs.readFileSync(new URL(f, import.meta.url), "utf8");
  assert.equal(UI.settingsSection.grownup, true);
  assert.match(src("../src/diagnostics_ui.js"), /id: "diagnostics"[^\n]*grownup: true/);
  assert.match(src("../src/learning_ui.js"), /id: "learning"[^\n]*grownup: true/);
  const a11y = src("../src/a11y.js");
  // the sidebar: kids' sections first, For grown-ups last; Reset is no longer a section of its own
  assert.match(a11y, /\["voice", "Voice"\][\s\S]*\["read", "Reading & captions"\], \["display", "Display"\][\s\S]*\["grownups", GROWNUPS\.title\]\]/);
  assert.doesNotMatch(a11y, /\["reset", "Reset"\]/);
  // the gate is the shared hold, and closing Settings locks it again
  assert.match(a11y, /bindHold\(gate, \{ onFire: \(\) => \{ guOpen = true;/);
  assert.match(a11y, /panel\.hidden = true; scrim\.hidden = true; resetArmed = false; guOpen = false;/);
  // voice "reset" opens For grown-ups, never past the gate
  assert.match(a11y, /case "reset": section = "grownups";/);
});

test("[0.4.1] bindHold: a held Enter on the focused button is not cancelled by the controller poll (only a pad hold is)", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  const saved = { raf: globalThis.requestAnimationFrame, doc: globalThis.document, nav: Object.getOwnPropertyDescriptor(globalThis, "navigator") };
  const frames = [];
  globalThis.requestAnimationFrame = f => { frames.push(f); return frames.length; };
  globalThis.cancelAnimationFrame = () => {};
  try {
    const b = fakeButton(); b.isConnected = true;
    globalThis.document = { activeElement: b };
    Object.defineProperty(globalThis, "navigator", { value: { getGamepads: () => [] }, configurable: true });
    let fired = 0;
    RS.bindHold(b, { onFire: () => { fired++; } });
    const runFrames = () => { const fs = frames.splice(0); fs.forEach(f => f()); };
    b.emit("keydown", { key: "Enter" });
    for (let k = 0; k < 5; k++) runFrames();      // the poll runs every frame with no pad button down
    mock.timers.tick(3000); await flush();
    assert.equal(fired, 1, "the keyboard hold lasted its 3 s");
  } finally {
    mock.timers.reset();
    globalThis.requestAnimationFrame = saved.raf; globalThis.document = saved.doc;
    if (saved.nav) Object.defineProperty(globalThis, "navigator", saved.nav);
  }
});
