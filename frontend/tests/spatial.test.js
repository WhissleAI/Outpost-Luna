// Spatial (D-pad) focus, keys and gamepad: the pure parts of src/input/spatial.js, keys.js and gamepad.js
// (docs/KEYBOARD.md). Geometry, scopes, memory / restore, the key map, the help sheet and the controller mapping.
import test from "node:test";
import assert from "node:assert/strict";
import { rect, score, inBeam, pickBest, pickInRegion, topScope, keyOf, createFocusMemory, createRepeatGate, valueControl, isTextField, REPEAT_MS } from "../src/input/spatial.js";
import { keyAction, helpRows, screenName, loadKeySettings } from "../src/input/keys.js";
import { readPad, createPadReader, BTN } from "../src/input/gamepad.js";

// ---------------------------------------------------------------- geometry ----------------------------------------
// A 3×3 grid of 100×40 tiles, 20 px apart:  a b c / d e f / g h i
const grid = {};
"abcdefghi".split("").forEach((n, k) => { grid[n] = rect(20 + (k % 3) * 120, 20 + Math.floor(k / 3) * 60, 100, 40); });
const cands = names => names.map(n => ({ n, rect: grid[n] }));
const go = (from, dir, names = "abcdefghi") => { const c = cands(names.replace(from, "").split("")), k = pickBest(grid[from], c, dir); return k < 0 ? null : c[k].n; };

test("grid: each arrow goes to the neighbour, and nothing past the edge", () => {
  assert.equal(go("e", "left"), "d"); assert.equal(go("e", "right"), "f");
  assert.equal(go("e", "up"), "b"); assert.equal(go("e", "down"), "h");
  assert.equal(go("a", "left"), null); assert.equal(go("a", "up"), null);
  assert.equal(go("i", "right"), null); assert.equal(go("i", "down"), null);
});

test("the straight neighbour beats a closer diagonal; a gap row is skipped to the next aligned tile", () => {
  assert.equal(go("d", "right", "dfbh"), "f", "f is in the row; b and h are diagonal");
  assert.equal(go("b", "down", "bhdf"), "h", "past the empty e, straight down is h");
});

test("beam: overlap on the other axis", () => {
  assert.ok(inBeam(grid.d, grid.f, "right")); assert.ok(!inBeam(grid.d, grid.b, "right"));
  assert.ok(inBeam(grid.b, grid.h, "down"));
});

test("score: only what is that way counts; overlap on the other axis is preferred", () => {
  const from = rect(0, 0, 100, 40);
  assert.equal(score(from, rect(-200, 0, 100, 40), "right"), Infinity);
  assert.equal(score(from, rect(0, 0, 100, 40), "down"), Infinity, "the same spot is no direction");
  assert.ok(score(from, rect(0, 100, 100, 40), "down") < score(from, rect(300, 100, 100, 40), "down"));
});

test("regions: inside the current region first, then any region", () => {
  const from = rect(0, 0, 50, 50);
  const c = [{ rect: rect(250, 0, 50, 50), region: "other" }, { rect: rect(400, 0, 50, 50), region: "card" }];
  assert.equal(pickInRegion(from, "card", c, "right"), 1, "the card's own control, though further");
  assert.equal(pickInRegion(from, "voicebar", c, "right"), 0, "nothing in the region: the nearest anywhere");
  assert.equal(pickInRegion(from, "card", c, "left"), -1);
});

test("regions: a split region (the map's header far above its card) loses to a much nearer control", () => {
  const start = rect(900, 600, 200, 48);
  const c = [{ rect: rect(40, 20, 120, 32), region: "panel" }, { rect: rect(880, 420, 60, 60), region: "route" }];
  assert.equal(pickInRegion(start, "panel", c, "up"), 1, "the pin just above, not the header across the screen");
});

test("Moon hops: tiny place rects pick the nearest place that way (the reticle at the centre)", () => {
  const at = (x, y) => ({ rect: rect(x - 4, y - 4, 8, 8) });
  const centre = rect(496, 396, 8, 8), pts = [at(700, 400), at(560, 410), at(500, 200), at(300, 650)];
  const hop = (p, d) => pickBest(centre, p, d, { cone: 0.8 });
  assert.equal(hop(pts, "right"), 1);
  assert.equal(hop(pts, "up"), 2);
  assert.equal(hop(pts, "down"), 3, "the place just right of centre is not down");
  assert.equal(hop([at(700, 400)], "left"), -1, "no place that way: the arrow leaves the Moon");
  assert.equal(hop([at(600, 560)], "right"), -1, "60° off is outside the cone");
});

// ---------------------------------------------------------------- scopes + memory ---------------------------------
test("scopes: the first open layer, top-most first, traps focus; none open = the whole screen", () => {
  const layers = [{ id: "help", open: false }, { id: "settings", open: true }, { id: "lesson", open: true }];
  assert.equal(topScope(layers).id, "settings");
  assert.equal(topScope([{ id: "help", open: false }]), null);
  assert.equal(topScope([{ id: "panel", open: true }, { id: "seat", open: true }]).id, "panel", "an open panel beats the seat");
});

const fake = (o = {}) => ({ isConnected: true, tagName: "BUTTON", dataset: {}, className: "", ...o });
test("keyOf: an id, else an identifying data attribute, else the first class", () => {
  assert.equal(keyOf(fake({ id: "aNext" })), "#aNext");
  assert.equal(keyOf(fake({ dataset: { c: "far" } })), 'button[data-c="far"]');
  assert.equal(keyOf(fake({ dataset: { l: "moon" }, className: "pin is-sel" })), 'button[data-l="moon"]');
  assert.equal(keyOf(fake({ tagName: "INPUT", value: "strict", dataset: { p: "filter" } })), 'input[data-p="filter"][value="strict"]');
  assert.equal(keyOf(fake({ className: "is-hot cb-view" })), "button.cb-view", "state classes never identify");
});

test("memory: restores the remembered control per screen; after a re-render, its identity", () => {
  const m = createFocusMemory();
  const start = fake({ id: "aStart" }), choice = fake({ dataset: { c: "b" } });
  m.remember("academy|map", start); m.remember("academy|lesson", choice);
  assert.equal(m.recall("academy|map").el, start);
  assert.equal(m.recall("academy|lesson").el, choice);
  choice.isConnected = false;   // the lesson re-rendered
  assert.deepEqual(m.recall("academy|lesson"), { el: null, key: 'button[data-c="b"]' });
  assert.equal(m.recall("mission|brief"), null);
  m.remember("academy|map", fake({ id: "aCsEdit" }));
  assert.equal(m.recall("academy|map").key, "#aCsEdit", "the latest wins");
});

test("memory is bounded", () => {
  const m = createFocusMemory({ max: 3 });
  ["a", "b", "c", "d"].forEach(k => m.remember(k, fake({ id: k })));
  assert.equal(m.size, 3); assert.equal(m.recall("a"), null);
});

test("key repeat: a held arrow moves at most once per gap; a fresh press always moves", () => {
  let t = 0; const g = createRepeatGate(() => t);
  assert.ok(g.ok(false, 150)); t = 50; assert.equal(g.ok(true, 150), false); t = 160; assert.ok(g.ok(true, 150));
  t = 170; assert.ok(g.ok(false, 150), "not a repeat");
  assert.ok(REPEAT_MS.slow > REPEAT_MS.normal && REPEAT_MS.normal > REPEAT_MS.fast);
});

test("value controls and text fields", () => {
  const el = (tagName, type, role) => ({ tagName, type, getAttribute: () => role || null });
  assert.equal(valueControl(el("INPUT", "range")), "range");
  assert.equal(valueControl(el("INPUT", "radio")), "radio");
  assert.equal(valueControl(el("SELECT")), "select");
  assert.equal(valueControl(el("DIV", "", "slider")), "slider");
  assert.equal(valueControl(el("BUTTON", "button")), null);
  assert.ok(isTextField(el("INPUT", "text"))); assert.ok(isTextField(el("TEXTAREA")));
  assert.ok(!isTextField(el("INPUT", "checkbox"))); assert.ok(!isTextField(el("BUTTON", "button")));
});

// ---------------------------------------------------------------- keys --------------------------------------------
const K = (key, o = {}, c = {}) => keyAction({ key, ...o }, c);
test("keys: the remote map", () => {
  assert.deepEqual(K("ArrowUp"), { intent: "move", args: { dir: "up", shift: false } });
  assert.deepEqual(K("ArrowLeft", { shift: true }), { intent: "move", args: { dir: "left", shift: true } });
  assert.equal(K("Enter").intent, "select");
  assert.equal(K("Escape").intent, "back"); assert.equal(K("Backspace").intent, "back");
  assert.equal(K("m").intent, "mic"); assert.equal(K("M").intent, "mic");
  assert.equal(K("h").intent, "help"); assert.equal(K("?").intent, "help");
  assert.equal(K("/").intent, "focus_input");
  assert.deepEqual(K("3"), { intent: "pick", args: { n: 3 } });
  assert.equal(K("s").intent, "settings"); assert.equal(K("c").intent, "captions");
  assert.equal(K("v").intent, "view_next"); assert.equal(K("o").intent, "panel_open");
  assert.equal(K("y").intent, "yes"); assert.equal(K("p").intent, "prev");
  assert.equal(K("n").intent, "next"); assert.equal(K("n", {}, { confirm: true }).intent, "no");
  assert.equal(K("x"), null); assert.equal(K("Tab"), null, "Tab stays native");
});

test("keys: A–D pick only while lettered answers are up (then C is answer C, not captions)", () => {
  assert.equal(K("a"), null); assert.equal(K("b"), null);
  assert.deepEqual(K("a", {}, { lettered: true }), { intent: "pick", args: { n: 1 } });
  assert.deepEqual(K("c", {}, { lettered: true }), { intent: "pick", args: { n: 3 } });
  assert.deepEqual(K("D", {}, { lettered: true }), { intent: "pick", args: { n: 4 } });
});

test("keys: never with Ctrl / Cmd / Alt (the menu and the Alt shortcuts keep theirs)", () => {
  for (const o of [{ ctrl: true }, { meta: true }, { alt: true }]) {
    assert.equal(K("r", o), null); assert.equal(K("ArrowRight", o), null); assert.equal(K("Escape", o), null);
  }
});

test("keys: typing — letters, arrows and Backspace stay in the field; only Esc leaves", () => {
  for (const k of ["m", "n", "h", "ArrowLeft", "ArrowUp", "Backspace", "Enter", "1", "/"]) assert.equal(K(k, {}, { typing: true }), null, k);
  assert.deepEqual(K("Escape", {}, { typing: true }), { act: "leave_input" });
});

test("keys: sliders and choices adjust with Left / Right; Up / Down leave", () => {
  assert.equal(K("ArrowRight", {}, { value: "range" }), null, "native range step");
  assert.equal(K("ArrowLeft", {}, { value: "slider" }), null, "the knob's own handler");
  assert.equal(K("ArrowRight", {}, { value: "radio" }), null, "native radio");
  assert.deepEqual(K("ArrowRight", {}, { value: "select" }), { act: "select_step", d: 1 });
  for (const v of ["range", "slider", "radio", "select"]) assert.equal(K("ArrowDown", {}, { value: v }).intent, "move", v);
});

test("keys: a held letter fires once; held arrows repeat (the gate throttles them)", () => {
  assert.equal(K("Enter", { repeat: true }), null); assert.equal(K("m", { repeat: true }), null);
  assert.equal(K("ArrowDown", { repeat: true }).intent, "move");
});

test("help sheet: this screen's keys, then everywhere; the controller only when one is connected", () => {
  for (const s of ["home", "map", "lesson", "lesson_moon", "patch", "ride", "picker", "cabin_seat", "cabin_panel", "debrief", "library", "settings"]) {
    const g = helpRows(s);
    assert.ok(g.length === 2 && g[1].title === "Everywhere", s);
  }
  assert.equal(helpRows("app").length, 1);
  assert.equal(helpRows("map", { pad: true }).pop().title, "Controller");
  const all = helpRows("map").flatMap(g => g.rows.map(r => r[0])).join(" ");
  for (const k of ["Enter", "Esc", "M", "H", "S", "C", "/"]) assert.ok(all.includes(k), k);
});

test("screenName", () => {
  assert.equal(screenName({ mode: "academy", aview: "home" }), "home");
  assert.equal(screenName({ mode: "academy", aview: "map" }), "map");
  assert.equal(screenName({ mode: "academy", aview: "lesson", moon: true }), "lesson_moon");
  assert.equal(screenName({ mode: "academy", aview: "ride", ride: true }), "ride");
  assert.equal(screenName({ mode: "academy", aview: "badge" }), "patch");
  assert.equal(screenName({ mode: "mission", mission: "brief" }), "picker");
  assert.equal(screenName({ mode: "mission", cabin: true, panel: "seat" }), "cabin_seat");
  assert.equal(screenName({ mode: "mission", cabin: true, panel: "comm" }), "cabin_panel");
  assert.equal(screenName({ mode: "mission", mission: "debrief" }), "debrief");
  assert.equal(screenName({ mode: "cadet" }), "library");
  assert.equal(screenName({ mode: "cadet", settings: true }), "settings");
});

test("key settings: defaults (focus sound off), blocked storage, junk", () => {
  assert.deepEqual(loadKeySettings(null), { sound: false, repeat: "normal", lefty: false });
  assert.deepEqual(loadKeySettings({ getItem: () => { throw new Error("blocked"); } }), { sound: false, repeat: "normal", lefty: false });
  assert.deepEqual(loadKeySettings({ getItem: () => '{"sound":true,"repeat":"warp","lefty":1}' }), { sound: true, repeat: "normal", lefty: false });
});

// ---------------------------------------------------------------- gamepad -----------------------------------------
const pad = ({ pressed = [], axes = [0, 0, 0, 0] } = {}) => ({ buttons: Array.from({ length: 17 }, (_, i) => ({ pressed: pressed.includes(i), value: pressed.includes(i) ? 1 : 0 })), axes });

test("gamepad: D-pad and the left stick are directions; the right stick looks; lefty swaps the sticks", () => {
  assert.equal(readPad(pad({ pressed: [BTN.left] })).dir, "left");
  assert.equal(readPad(pad({ axes: [0, 0.9, 0, 0] })).dir, "down");
  assert.equal(readPad(pad({ axes: [0.3, 0.2, 0, 0] })).dir, null, "inside the dead zone");
  assert.deepEqual(readPad(pad({ axes: [0, 0, 0.6, -0.1] })).look, { x: 0.6, y: 0 });
  const l = readPad(pad({ axes: [0.7, 0, 0, -0.9] }), { lefty: true });
  assert.equal(l.dir, "up", "lefty: the right stick moves"); assert.equal(l.look.x, 0.7, "lefty: the left stick looks");
});

test("gamepad: a button fires once per press; a held direction repeats after a delay", () => {
  const r = createPadReader({ delay: 300, repeat: 100 }), f = p => readPad(pad(p));
  assert.deepEqual(r.step(f({ pressed: [BTN.a] }), 0), [{ intent: "select", args: {} }]);
  assert.deepEqual(r.step(f({ pressed: [BTN.a] }), 16), [], "still held: nothing");
  assert.deepEqual(r.step(f({}), 32), []);
  const names = (p, t) => r.step(f(p), t).map(a => a.intent || "look");
  assert.deepEqual(names({ pressed: [BTN.b, BTN.x] }, 40), ["back", "mic"]);
  assert.deepEqual(names({ pressed: [BTN.y, BTN.lb, BTN.rb] }, 60), ["help", "prev", "next"]);
  assert.deepEqual(names({ pressed: [BTN.right] }, 100), ["move"]);
  assert.deepEqual(names({ pressed: [BTN.right] }, 300), [], "within the first delay");
  assert.deepEqual(names({ pressed: [BTN.right] }, 401), ["move"]);
  assert.deepEqual(names({ pressed: [BTN.right] }, 450), []);
  assert.deepEqual(names({ pressed: [BTN.right] }, 502), ["move"]);
});

test("gamepad: the right stick streams look, then one recentre", () => {
  const r = createPadReader();
  assert.deepEqual(r.step(readPad(pad({ axes: [0, 0, 0.5, 0] })), 0), [{ look: { x: 0.5, y: 0 } }]);
  assert.deepEqual(r.step(readPad(pad({ axes: [0, 0, 0, 0] })), 16), [{ look: { x: 0, y: 0 }, end: true }]);
  assert.deepEqual(r.step(readPad(pad()), 32), []);
});
