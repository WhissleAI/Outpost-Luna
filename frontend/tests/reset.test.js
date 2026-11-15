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

test("Start over / Reset everything clear every key the app owns, and nothing else on the page's origin", async () => {
  const ls = store({ "outpost-callsign": "Nova", "outpost-prefs": "{}", "outpost-profiles": "[]", "outpost-gestures": "{}", "outpost-gestures-spin": "{}",
    "outpost-tour-done:Nova": "1", "outpost-first-mission:Nova": "1", "outpost-missions-flown:Nova": "2", "outpost-prep-seen": "[]",
    "outpost-seen-steps": "[]", "outpost-moonbase-seen:Nova": "1", "outpost-keys": "{}", "outpost-voicebar": "{}", "outpost-a11y": "{}",
    "atm-academy": "{}", "atm-theme": "dark", "atm-mode": "mission", "atm-session-id": "x", "someone-else": "keep" });
  const ss = store({ "atm-session": "s", "keys-e2e": "keep" });
  const w = { localStorage: ls, sessionStorage: ss, indexedDB: { databases: async () => [{ name: "outpost-cache" }], deleteDatabase() {} } };
  const removed = await RS.clearAppStorage(w);
  assert.deepEqual(ls.keys(), ["someone-else"]);
  assert.deepEqual(ss.keys(), ["keys-e2e"]);
  assert.ok(removed.includes("idb:outpost-cache"));
});

test("the confirm view says exactly what each level erases and keeps; the button is a hold", () => {
  const s = RS.confirmHtml("start");
  for (const w of ["Call signs", "patches", "Missions flown", "voice, theme, sound, gestures", "voice-guide log", "Downloaded voices, crew audio, videos and models stay", "Hold to start over", "Cancel"]) assert.ok(s.includes(w), w);
  const a = RS.confirmHtml("all");
  for (const w of ["Saved NASA videos", "download again", "Hold to reset everything"]) assert.ok(a.includes(w), w);
  assert.equal(RS.HOLD_MS, 3000);
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
  assert.equal(desk.localStorage.length, 0);
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
