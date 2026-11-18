// Settings → Reset Outpost Luna (src/reset.js, docs/RESET.md): which browser keys each level clears, the copy that
// says exactly what goes, the hold (never a click), and that voice only opens the confirm view.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const RS = await import("../src/reset.js");
const { parseCommand } = await import("../src/a11y.js");

function store(o) {
  const m = new Map(Object.entries(o));
  return { get length() { return m.size; }, key: i => [...m.keys()][i], getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)),
    removeItem: k => m.delete(k), keys: () => [...m.keys()] };
}

const ALL = () => ({ "outpost-callsign": "Nova", "outpost-prefs": "{}", "outpost-gestures": "{}", "outpost-gestures-spin": "{}",
  "outpost-profiles": JSON.stringify({ active: "p1", list: [{ id: "p1", data: null }, { id: "p2", data: { "outpost-callsign": "Vega", "atm-academy": "{\"badges\":[\"b1\"]}", "outpost-prefs": "{}", "atm-theme": "light" } }] }),
  "outpost-tour-done:Nova": "1", "outpost-first-mission:Nova": "1", "outpost-missions-flown:Nova": "2", "outpost-prep-seen": "[]",
  "outpost-seen-steps": "[]", "outpost-moonbase-seen:Nova": "1", "outpost-keys": "{}", "outpost-voicebar": "{}", "outpost-a11y": "{}",
  "atm-academy": "{\"badges\":[\"moon\"]}", "atm-theme": "dark", "atm-mode": "mission", "atm-session-id": "x", "someone-else": "keep" });

test("[0.4.1] Start over / Reset everything keep Flight School progress, call signs and missions flown; the rest goes", async () => {
  const ls = store(ALL());
  const ss = store({ "atm-session": "s", "keys-e2e": "keep" });
  const w = { localStorage: ls, sessionStorage: ss, indexedDB: { databases: async () => [{ name: "outpost-cache" }], deleteDatabase() {} } };
  const removed = await RS.clearAppStorage(w);
  assert.deepEqual(ls.keys().sort(), ["atm-academy", "outpost-callsign", "outpost-missions-flown:Nova", "outpost-profiles", "someone-else"]);
  assert.equal(ls.getItem("atm-academy"), '{"badges":["moon"]}');
  assert.equal(ls.getItem("outpost-callsign"), "Nova");
  // the other cadets stay, trimmed to their progress (their settings go like everyone's)
  const prof = JSON.parse(ls.getItem("outpost-profiles"));
  assert.deepEqual(prof.list.map(p => p.id), ["p1", "p2"]);
  assert.deepEqual(Object.keys(prof.list[1].data).sort(), ["atm-academy", "outpost-callsign"]);
  assert.deepEqual(ss.keys(), ["keys-e2e"]);
  assert.ok(removed.includes("idb:outpost-cache") && removed.includes("outpost-prefs") && removed.includes("atm-theme"));
});

test("[0.4.1] Erase progress too: every key the app owns goes, and nothing else on the page's origin", async () => {
  const ls = store(ALL());
  const ss = store({ "atm-session": "s", "keys-e2e": "keep" });
  const w = { localStorage: ls, sessionStorage: ss, indexedDB: { databases: async () => [], deleteDatabase() {} } };
  await RS.clearAppStorage(w, { erase: true });
  assert.deepEqual(ls.keys(), ["someone-else"]);
  assert.deepEqual(ss.keys(), ["keys-e2e"]);
});

test("the confirm view says exactly what each level erases and keeps; both buttons are holds", () => {
  const s = RS.confirmHtml("start");
  for (const w of ["voice, theme, sound, gestures", "voice-guide log", "Lessons, patches and call signs stay", "downloaded voices, crew audio, videos and models",
    "Hold to start over", "Hold to erase progress too", "call sign, patches and lesson progress", "Cancel"]) assert.ok(s.includes(w), w);
  assert.ok(s.includes("data-reset-hold") && s.includes("data-reset-erase"));
  const a = RS.confirmHtml("all");
  for (const w of ["Saved NASA videos", "download again", "Hold to reset everything", "Lessons, patches and call signs stay", "Hold to erase progress too"]) assert.ok(a.includes(w), w);
  assert.ok(/Progress and downloads stay/.test(RS.zoneHtml()));
  assert.equal(RS.HOLD_MS, 3000);
});

test("bindConfirm: the level's hold keeps progress; the separate 'Erase progress too' hold erases it; one fires, the other is off", async () => {
  const { mock } = await import("node:test");
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const mkBtn = () => { const on = {}; return { disabled: false, isConnected: false, classList: { add() {}, remove() {} }, style: {},
      addEventListener: (ev, f) => (on[ev] = on[ev] || []).push(f), emit: ev => (on[ev] || []).forEach(f => f({ preventDefault() {}, stopPropagation() {} })),
      querySelector: () => ({ style: {} }), focus() {} }; };
    const run = async which => {
      const btns = { "[data-reset-hold]": mkBtn(), "[data-reset-erase]": mkBtn(), "[data-reset-cancel]": mkBtn(), ".rs-status": { textContent: "" } };
      const box = { dataset: { level: "start" }, querySelector: q => btns[q], addEventListener() {} };
      const calls = [];
      RS.bindConfirm({ querySelector: () => box }, { doReset: (lv, o) => { calls.push([lv, o.erase]); return new Promise(() => {}); } });
      btns[which].emit("click"); await new Promise(r => setImmediate(r));
      assert.equal(calls.length, 0, "a click never resets");
      btns[which].emit("pointerdown"); mock.timers.tick(3000); await new Promise(r => setImmediate(r));
      return { calls, btns };
    };
    const keep = await run("[data-reset-hold]");
    assert.deepEqual(keep.calls, [["start", false]]);
    assert.equal(keep.btns["[data-reset-erase]"].disabled, true);
    const erase = await run("[data-reset-erase]");
    assert.deepEqual(erase.calls, [["start", true]]);
    assert.equal(erase.btns["[data-reset-hold]"].disabled, true);
  } finally { mock.timers.reset(); }
});

test("runReset: backend first (with the reset header), then the page's storage; desktop hands over to the shell", async () => {
  const calls = [];
  const fetchFn = async (u, o) => { calls.push([u, o.method, o.headers["X-Outpost-Reset"]]); return { ok: true, json: async () => ({ token: "T1" }) }; };
  const mk = ua => ({ localStorage: store({ "outpost-callsign": "N" }), sessionStorage: store({}), navigator: { userAgent: ua },
    location: { href: "", replace(u) { this.replaced = u; } } });
  const desk = mk("Mozilla/5.0 Electron/44.10.0");
  await RS.runReset("all", { fetchFn, w: desk });
  assert.deepEqual(calls[0], ["/api/reset?level=all", "POST", "1"]);
  assert.equal(desk.location.href, "/__outpost/reset?level=all&token=T1");
  assert.equal(desk.localStorage.getItem("outpost-callsign"), "N", "the call sign stays");
  const desk2 = mk("Mozilla/5.0 Electron/44.10.0");
  await RS.runReset("all", { fetchFn, w: desk2, erase: true });
  assert.equal(desk2.location.href, "/__outpost/reset?level=all&token=T1&erase=1");
  assert.equal(desk2.localStorage.length, 0);
  const web = mk("Mozilla/5.0 Chrome/140");
  await RS.runReset("start", { fetchFn, w: web });
  assert.equal(web.location.replaced, "/");
});

test("voice only opens the confirm view (no command resets by itself)", () => {
  assert.deepEqual(parseCommand("reset"), { cmd: "reset", arg: "start" });
  assert.deepEqual(parseCommand("reset the app"), { cmd: "reset", arg: "start" });
  assert.deepEqual(parseCommand("reset everything"), { cmd: "reset", arg: "all" });
  assert.notEqual((parseCommand("reset the voice bar") || {}).cmd, "reset");
});
