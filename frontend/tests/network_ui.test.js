// Settings → For grown-ups → School network (src/network_ui.js, docs/SCHOOL_IT.md): the switch, what's off, the
// locked state, and the words other screens use while it is on.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const N = await import("../src/network_ui.js");
const C = await import("../src/media/commands.js");
const AU = await import("../src/app_update_ui.js");
const { engineChoiceHtml } = await import("../src/prefs.js");
const { GROWNUPS } = await import("../src/a11y.js");
const words = s => s.trim().split(/\s+/).length;
const text = h => h.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

test("registered in For grown-ups, after Help & diagnostics, and listed on the gate", () => {
  const sec = window.__outpost.settingsSections.find(x => x.id === "network");
  assert.equal(sec.title, "School network");
  assert.equal(sec.grownup, true);
  assert.equal(sec.after, "diagnostics");
  assert.ok(GROWNUPS.inside.includes("School network"));
  assert.match(GROWNUPS.gate, /school network/);
});

test("off: one switch, unchecked, nothing listed as off", () => {
  const h = N.innerHtml({ school_network: false, locked: false, off: [], allow_hosts: [] });
  assert.match(h, /data-nw-sw (?!checked)/);
  assert.doesNotMatch(h, /Off while it's on/);
  assert.doesNotMatch(h, /disabled/);
});

test("on: says plainly what is off; an admin's allow list is shown", () => {
  const h = N.innerHtml({ school_network: true, locked: false, off: ["videos", "downloads", "updates"], allow_hosts: ["nasa.gov"] });
  assert.match(h, /data-nw-sw checked/);
  const t = text(h);
  for (const k of ["videos", "downloads", "updates"]) assert.ok(t.includes(N.COPY.off[k]), k);
  assert.match(t, /Your IT admin allows: nasa\.gov/);
});

test("locked by the IT admin: on, the switch cannot turn it off, and it says who", () => {
  const h = N.innerHtml({ school_network: true, locked: true, off: ["videos"], allow_hosts: [] });
  assert.match(h, /data-nw-sw checked\s+disabled/);
  assert.match(text(h), /Turned on by this computer's IT admin/);
});

test("copy: the app's budgets (supporting line 12 words or fewer), no age words", () => {
  for (const s of [N.COPY.line, N.COPY.swHelp, N.COPY.locked, ...Object.values(N.COPY.off), N.SCHOOL.line, C.SCHOOL_LINE])
    assert.ok(words(s) <= 12, s);
  assert.ok(words(N.COPY.title) <= 6);
  for (const s of Object.values(N.COPY).flatMap(v => (typeof v === "string" ? [v] : Object.values(v))))
    assert.doesNotMatch(s, /\b(kid|kids|child|children|parent|year[- ]old)\b/i, s);
});

test("the switch posts to /api/network and keeps the answer for the other screens", async () => {
  const o = {};
  const calls = [];
  const fake = async (url, init) => { calls.push([url, init && init.method, init && init.body]); return { ok: true, json: async () => ({ school_network: true, off: ["updates"] }) }; };
  const s = await N.set(true, fake, o);
  assert.equal(s.school_network, true);
  assert.deepEqual(calls[0], ["/api/network", "POST", JSON.stringify({ school_network: true })]);
  assert.equal(N.schoolOn(o), true);
  await assert.rejects(N.set(false, async () => ({ ok: false, status: 409 }), o));
});

test("while it is on, the other screens say 'school network', not 'connect'", () => {
  assert.equal(C.needsNet(true), "Off on the school network");
  assert.equal(C.needsNet(false), C.NEEDS_NET);
  assert.match(C.offlineLine(true), /school network.*Saved videos still play/);
  assert.equal(C.offlineLine(false), C.OFFLINE_LINE);
  assert.deepEqual(AU.view({ state: "error", reason: "school" }), { line: "Update checks are off on the school network.", notes: "", action: null });
  window.__outpost.network = { school_network: true };
  const h = engineChoiceHtml({ engine: "os" }, { state: "missing", downloadable: true });
  assert.doesNotMatch(h, /data-get-steer/, "no download button that could only fail");
  assert.match(h, /Off on the school network/);
  window.__outpost.network = { school_network: false };
  assert.match(engineChoiceHtml({ engine: "os" }, { state: "missing", downloadable: true }), /data-get-steer/);
});

test("voice opens School network (behind the grown-up hold), and never switches it", async () => {
  const { parseCommand } = await import("../src/a11y.js");
  for (const t of ["school network", "open school network", "school mode", "school network settings"])
    assert.deepEqual(parseCommand(t), { cmd: "network" }, t);
  assert.notDeepEqual(parseCommand("turn off school network"), { cmd: "network" });
  for (const s of [GROWNUPS.sayNetLocked, GROWNUPS.sayNetOpen]) assert.ok(words(s) <= 20, s);
});
