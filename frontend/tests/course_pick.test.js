// The first-run course pick (src/course_pick.js, docs/COURSES.md §4.10): the options, who gets the pick, voice, the
// download through the backend + desktop flow, and every failure path (offline, School network mode, a failed or stuck
// download) landing on the Moon.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const P = await import("../src/course_pick.js");

const MOON = { id: "moon", title: "The Moon", program: "Junior Astronaut Academy", grades: "3-8", status: "builtin" };
const pack = (o = {}) => ({ id: "archaeology", title: "Course: Archaeology", program: "Field Archaeology: the Mesa Verde region",
  grades: "9-12", size: 4608000, state: "missing", blocked: false, ...o });
const listing = (o = {}, p = {}) => ({ downloadable: true, managed: true, packs: [pack(p)], ...o });
const mem = (init = {}) => { const m = new Map(Object.entries(init)); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: k => m.delete(k), m }; };
const res = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

test("options: the Moon first (built in, starts now), then each catalog course with its line, grades and size", () => {
  const o = P.options(listing(), [MOON]);
  assert.deepEqual(o.map(x => x.id), ["moon", "archaeology"]);
  assert.equal(o[0].title, "The Moon"); assert.equal(o[0].line, "Junior Astronaut Academy");
  assert.equal(o[0].meta, "grades 3-8 · Built in · starts now");
  assert.equal(o[1].title, "Archaeology"); assert.equal(o[1].line, "Field Archaeology: the Mesa Verde region");
  assert.equal(o[1].meta, "grades 9-12 · 4.6 MB"); assert.equal(o[1].installed, false);
  assert.equal(P.options(listing({}, { state: "installed" }), [MOON])[1].meta, "grades 9-12 · On this computer");
});

test("options: nothing can download here (the iPad shell) -> only installed courses are offered", () => {
  assert.deepEqual(P.options(listing({ downloadable: false, managed: false }), [MOON]).map(x => x.id), ["moon"]);
  assert.deepEqual(P.options(listing({ downloadable: false, managed: false }, { state: "installed" }), [MOON]).map(x => x.id), ["moon", "archaeology"]);
  // a course installed from the offline pack but not in this catalog is offered too
  const geo = { id: "geo", title: "Geology", status: "pack", grades: "6-8", labels: { course: "Geology" } };
  assert.deepEqual(P.options({ packs: [] }, [MOON, geo, { id: "x1", status: "draft" }]).map(x => x.id), ["moon", "geo"]);
});

test("who gets the pick: no course stored and more than the Moon to offer; a stored choice (even the Moon) is final", () => {
  const o = P.options(listing(), [MOON]);
  assert.equal(P.shouldOffer(o, mem()), true);
  assert.equal(P.shouldOffer(o, mem({ "outpost-course": "moon" })), false);
  assert.equal(P.shouldOffer(o, mem({ "outpost-course": "archaeology" })), false);
  assert.equal(P.shouldOffer(o.slice(0, 1), mem()), false);         // the Moon alone: straight to the welcome
  assert.equal(P.shouldOffer(o, null), true);
  const s = mem(); P.remember("moon", s); assert.equal(s.getItem("outpost-course"), "moon");
  P.remember("../x", s); assert.equal(s.getItem("outpost-course"), "moon");
});

test("voice: the course names, with or without 'the'; skip words are the Moon; anything else is not a pick", () => {
  const o = P.options(listing(), [MOON]);
  for (const [t, id] of [["the moon", "moon"], ["Moon", "moon"], ["archaeology", "archaeology"], ["Archaeology please", "archaeology"],
    ["I want archaeology", "archaeology"], ["the archaeology one", "archaeology"], ["skip", "moon"], ["not now", "moon"], ["pick for me", "moon"]]) {
    assert.equal(P.matchPick(t, o), id, t);
  }
  assert.equal(P.matchPick("what is a kiva", o), null);
  assert.equal(P.matchPick("", o), null);
  assert.deepEqual(P.spokenNames(o), ["The Moon", "Moon", "Archaeology"]);
});

test("failure reasons are read plainly", () => {
  assert.equal(P.whyOf("School network mode is on, so nothing downloads."), "school");
  assert.equal(P.whyOf("You're offline. Connect to the internet, or import the offline pack from a USB stick."), "offline");
  assert.equal(P.whyOf("The download stopped. Try again."), "failed");
  assert.equal(P.failLine("offline", "Archaeology"), "You're offline, so Archaeology can't download. Starting on the Moon.");
  assert.equal(P.failLine("school", "Archaeology"), "School network mode is on, so Archaeology can't download here. Starting on the Moon.");
  assert.equal(P.failLine("failed", "Archaeology"), "Archaeology didn't download. Starting on the Moon.");
  assert.equal(P.failLine("timeout", "Archaeology"), "Archaeology is taking too long. Starting on the Moon.");
  assert.match(P.failHtml("offline", "Archaeology"), /For grown-ups → Course storage/);
});

/** A fake backend: GET /api/courses/packs returns the next listing in `lists`; POST …/get returns `got`. */
function backend({ lists, got = res(200, { state: "queued" }) }) {
  const calls = [];
  let i = 0;
  const fetchFn = async (url, o = {}) => {
    calls.push(`${o.method || "GET"} ${url}`);
    if (url === "/api/courses/packs") return res(200, lists[Math.min(i++, lists.length - 1)]);
    if (url.endsWith("/get")) return typeof got === "function" ? got() : got;
    return res(404, {});
  };
  return { fetchFn, calls };
}
const fast = { sleep: async () => {}, pollMs: 0 };

test("download: the backend + desktop flow (queued -> downloading with progress -> installed)", async () => {
  const b = backend({ lists: [listing(), listing({}, { state: "queued" }), listing({}, { state: "downloading", progress: 0.4 }), listing({}, { state: "installed" })] });
  const seen = [];
  const r = await P.getCourse("archaeology", { fetchFn: b.fetchFn, onState: s => seen.push(s), online: () => true, ...fast });
  assert.deepEqual(r, { ok: true });
  assert.ok(b.calls.includes("POST /api/courses/packs/archaeology/get"));
  assert.deepEqual(seen.map(s => s.state), ["queued", "queued", "downloading", "installed"]);
  assert.equal(seen[2].progress, 0.4);
});

test("download: the local-file fallback installs at once; an installed course needs no download", async () => {
  let b = backend({ lists: [listing()], got: res(200, { state: "installed" }) });
  assert.deepEqual(await P.getCourse("archaeology", { fetchFn: b.fetchFn, online: () => true, ...fast }), { ok: true });
  b = backend({ lists: [listing({}, { state: "installed" })] });
  assert.deepEqual(await P.getCourse("archaeology", { fetchFn: b.fetchFn, ...fast }), { ok: true });
  assert.ok(!b.calls.some(c => c.startsWith("POST")));
  assert.deepEqual(await P.getCourse("moon", {}), { ok: true });
});

test("offline: said at once, nothing is asked of the desktop", async () => {
  const b = backend({ lists: [listing()] });
  const r = await P.getCourse("archaeology", { fetchFn: b.fetchFn, online: () => false, ...fast });
  assert.equal(r.why, "offline"); assert.ok(!b.calls.some(c => c.startsWith("POST")));
  // the desktop found out (assets.js wrote .failed with its offline line)
  const b2 = backend({ lists: [listing(), listing({}, { state: "failed", reason: "You're offline. Connect to the internet, or import the offline pack from a USB stick." })] });
  assert.equal((await P.getCourse("archaeology", { fetchFn: b2.fetchFn, online: () => true, ...fast })).why, "offline");
});

test("School network mode: a blocked course never asks; a 403 from the backend says school too", async () => {
  const b = backend({ lists: [listing({}, { blocked: true })] });
  assert.equal((await P.getCourse("archaeology", { fetchFn: b.fetchFn, online: () => true, ...fast })).why, "school");
  assert.ok(!b.calls.some(c => c.startsWith("POST")));
  const b2 = backend({ lists: [listing()], got: res(403, { detail: "School network mode is on, so this course can't download here." }) });
  assert.equal((await P.getCourse("archaeology", { fetchFn: b2.fetchFn, online: () => true, ...fast })).why, "school");
});

test("a failed download, a missing source, a dropped ask, a timeout, a dead backend: all land on the Moon", async () => {
  const run = async (b, o = {}) => (await P.getCourse("archaeology", { fetchFn: b.fetchFn, online: () => true, ...fast, ...o })).why;
  assert.equal(await run(backend({ lists: [listing(), listing({}, { state: "failed", reason: "The download stopped. Try again." })] })), "failed");
  assert.equal(await run(backend({ lists: [listing()], got: res(404, { detail: "This course isn't ready to download yet." }) })), "failed");
  assert.equal(await run(backend({ lists: [listing()], got: res(422, { detail: "The course file is damaged (sha256). Download it again." }) })), "failed");
  assert.equal(await run(backend({ lists: [listing(), listing({}, { state: "missing" })] })), "failed");
  let t = 0;
  assert.equal(await run(backend({ lists: [listing(), listing({}, { state: "downloading" })] }), { now: () => (t += 1000), timeoutMs: 5000 }), "timeout");
  assert.equal(await run({ fetchFn: async () => { throw new Error("down"); } }), "failed");
  assert.equal(await run(backend({ lists: [{ packs: [] }] })), "failed");   // not in the catalog
});

// ---------------------------------------------------------------- the controller, on a tiny fake DOM
function fakePanel() {
  const els = new Map();
  const panel = {
    _html: "", ownerDocument: { activeElement: null },
    set innerHTML(h) {
      this._html = h; els.clear();
      for (const m of h.matchAll(/<button[^>]*?(?:id="([^"]+)"|data-crs="([^"]+)")[^>]*>/g)) {
        const key = m[1] ? `#${m[1]}` : `opt:${m[2]}`;
        const el = { dataset: m[2] ? { crs: m[2] } : {}, onclick: null, focus() { panel.ownerDocument.activeElement = this; }, click() { return this.onclick && this.onclick(); } };
        els.set(key, el);
      }
    },
    get innerHTML() { return this._html; },
    querySelector(sel) {
      if (sel === ".a-crs-opt.is-default") return els.get("opt:moon") || null;
      if (sel.startsWith("#")) return els.get(sel) || null;
      if (sel === ".crp-bar" || sel === ".crp-state") return null;
      return null;
    },
    querySelectorAll(sel) { return sel === ".a-crs-opt" ? [...els.entries()].filter(([k]) => k.startsWith("opt:")).map(([, v]) => v) : []; },
    el: k => els.get(k),
  };
  return panel;
}
const tick = () => new Promise(r => setTimeout(r, 0));

test("controller: the Moon (or Skip) stores the choice and starts the welcome, no reload", async () => {
  const opts = P.options(listing(), [MOON]);
  for (const how of ["click", "skip", "voice"]) {
    const panel = fakePanel(), storage = mem(), done = [], said = [];
    const c = P.mountPick(panel, { opts, storage, session: mem(), say: t => said.push(t), onDone: id => done.push(id), set: async () => { throw new Error("no switch for the Moon"); } });
    assert.match(panel.innerHTML, /Pick your course/); assert.equal(said[0], P.COPY.say);
    assert.equal(panel.ownerDocument.activeElement, panel.el("opt:moon"));   // the default has focus (Enter / A starts it)
    if (how === "click") panel.el("opt:moon").click();
    if (how === "skip") panel.el("#aCrpSkip").click();
    if (how === "voice") c.handleText("skip");
    await tick();
    assert.deepEqual(done, ["moon"], how); assert.equal(storage.getItem("outpost-course"), "moon");
  }
});

test("controller: a pack course downloads, then switches (setCourse) with the welcome one-shot set", async () => {
  const opts = P.options(listing(), [MOON]);
  const panel = fakePanel(), storage = mem(), session = mem(), switched = [], done = [];
  const c = P.mountPick(panel, { opts, storage, session, onDone: id => done.push(id),
    get: async (id, d) => { d.onState({ state: "downloading", progress: 0.5 }); return { ok: true }; },
    set: async id => { switched.push(id); return true; } });
  c.handleText("archaeology");
  await tick(); await tick();
  assert.deepEqual(switched, ["archaeology"]); assert.deepEqual(done, []);
  assert.equal(session.getItem(P.WELCOME_KEY), "1");
});

for (const why of ["offline", "school", "failed", "timeout"]) {
  test(`controller: ${why} -> said plainly, "get it later", then the Moon`, async () => {
    const opts = P.options(listing(), [MOON]);
    const panel = fakePanel(), storage = mem(), session = mem(), said = [], done = [], switched = [];
    const c = P.mountPick(panel, { opts, storage, session, say: t => said.push(t), onDone: id => done.push(id),
      get: async () => ({ ok: false, why }), set: async id => { switched.push(id); return true; } });
    panel.el("opt:archaeology").click();
    await tick(); await tick();
    assert.equal(c.view, "fail");
    assert.match(panel.innerHTML, new RegExp(P.failLine(why, "Archaeology").replace(/\./g, "\\.").replace(/'/g, ".{1,5}")));
    assert.match(panel.innerHTML, /You can get it later in For grown-ups → Course storage\./);
    assert.deepEqual(said.at(-1), [P.failLine(why, "Archaeology"), P.COPY.later]);
    assert.equal(panel.ownerDocument.activeElement, panel.el("#aCrpMoon"));
    c.handleText("okay");
    assert.deepEqual(done, ["moon"]); assert.deepEqual(switched, []);
    assert.equal(storage.getItem("outpost-course"), "moon"); assert.equal(session.getItem(P.WELCOME_KEY), null);
  });
}

test("controller: 'Start on the Moon instead' during a download stops waiting and starts the Moon", async () => {
  const opts = P.options(listing(), [MOON]);
  const panel = fakePanel(), storage = mem(), done = [];
  let release;
  P.mountPick(panel, { opts, storage, session: mem(), onDone: id => done.push(id),
    get: (id, d) => new Promise(r => { release = () => r({ ok: d.cancelled() ? false : true, why: "cancelled" }); }), set: async () => true });
  panel.el("opt:archaeology").click();
  await tick();
  panel.el("#aCrpCancel").click();
  assert.deepEqual(done, ["moon"]);
  release(); await tick();
  assert.deepEqual(done, ["moon"]);                                // never switches after the kid chose the Moon
});

test("controller: a switch the backend refuses lands on the failure view", async () => {
  const opts = P.options(listing({}, { state: "installed" }), [MOON]);
  const panel = fakePanel(), session = mem();
  const c = P.mountPick(panel, { opts, storage: mem(), session, get: async () => ({ ok: true }), set: async () => false });
  panel.el("opt:archaeology").click();
  await tick(); await tick();
  assert.equal(c.view, "fail"); assert.equal(session.getItem(P.WELCOME_KEY), null);
});

test("controller: router intents (yes / next start the focused course; no / back is the Moon) and help", async () => {
  const opts = P.options(listing(), [MOON]);
  let panel = fakePanel(), done = [];
  let c = P.mountPick(panel, { opts, storage: mem(), session: mem(), onDone: id => done.push(id) });
  assert.match(c.help(), /^Say The Moon, or Archaeology\. Or say skip\.$/);
  assert.equal(c.nav("next"), true); await tick();
  assert.deepEqual(done, ["moon"]);
  panel = fakePanel(); done = [];
  c = P.mountPick(panel, { opts, storage: mem(), session: mem(), onDone: id => done.push(id) });
  c.nav("back"); assert.deepEqual(done, ["moon"]);
  assert.equal(c.nav("library"), false);
});

test("copy stays short and plain (docs/COPY.md)", () => {
  for (const [k, v] of Object.entries(P.COPY)) {
    const t = typeof v === "function" ? v("Archaeology") : v;
    assert.ok(t.split(/\s+/).length <= 14, `${k}: ${t}`);
  }
});
