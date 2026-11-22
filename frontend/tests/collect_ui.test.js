// Settings → For grown-ups → Help improve Outpost Luna (src/collect_ui.js, docs/ADULT_SESSIONS.md): an adult's opt-in,
// off by default, only inside the grown-up gate; the consent screen; audio as its own switch; export and delete.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const C = await import("../src/collect_ui.js");
const A = await import("../src/a11y.js");
const words = s => String(s).trim().split(/\s+/).length;

test("registered only in For grown-ups (behind the hold), after the playtest", () => {
  const sec = window.__outpost.settingsSections.find(x => x.id === "collect");
  assert.equal(sec.title, "Help improve Outpost Luna");
  assert.equal(sec.grownup, true, "drawn inside For grown-ups, never in the kids' sidebar");
  assert.equal(sec.after, "playtest");
  assert.ok(A.GROWNUPS.inside.includes("Help improve Outpost Luna"), "the locked gate lists it");
});

test("the locked gate shows the list only: no switch a kid can press", () => {
  const sec = window.__outpost.settingsSections.find(x => x.id === "collect");
  const parts = [{ id: sec.id, title: sec.title, html: sec.html() }];
  const locked = A.grownupsHtml({ open: false, parts });
  assert.ok(!locked.includes("data-col-start") && !locked.includes("data-col-zone"));
  assert.match(locked, /data-gu-open/);
  const pin = A.grownupsHtml({ open: false, pin: true, parts });
  assert.ok(!pin.includes("data-col-zone"), "the teacher PIN step hides it too");
  assert.match(A.grownupsHtml({ open: true, parts }), /data-col-zone/);
});

test("off by default; on only for the profile that turned it on", () => {
  const off = C.viewHtml({ st: null });
  assert.match(off, /Off\. Nothing extra is kept\./);
  assert.match(off, /data-col-start/);
  assert.ok(!off.includes("data-col-audio"), "no audio switch before it is on");
  assert.match(off, /Nothing is sent/);
  const st = { on: true, audio: false, profile: "p2", turns: 3, clips: 0 };
  assert.match(C.viewHtml({ st, pid: "p2" }), /On for this profile\. 3 turns kept\./);
  assert.match(C.viewHtml({ st, pid: "p2" }), /data-col-audio(?![^>]*checked)/, "audio is its own switch, off");
  assert.match(C.viewHtml({ st, pid: "p1" }), /Off\./, "another cadet's profile: not collecting here");
  assert.equal(C.onHere(st, "p2"), true);
  assert.equal(C.onHere(st, "p1"), false);
  assert.match(C.viewHtml({ st: { ...st, audio: true, clips: 2 }, pid: "p2" }), /data-col-audio checked/);
});

test("the consent screen: Turn on stays disabled until the adult agrees", () => {
  const h = C.viewHtml({ view: "consent" });
  assert.match(h, /data-col-agree/);
  assert.match(h, /<button[^>]*data-col-go disabled/);
  assert.match(h, /I'm an adult, and I agree\./);
  for (const t of C.COPY.consent) assert.ok(h.includes(t.replace(/'/g, "'")), t);
  assert.ok(C.COPY.consent.some(t => /Audio clips only if you turn them on/.test(t)));
  assert.ok(C.COPY.consent.some(t => /Nothing is sent/.test(t)));
});

test("export and a held delete appear once turns are kept", () => {
  const h = C.viewHtml({ st: { on: false, turns: 5, clips: 1 }, pid: "p1" });
  assert.match(h, /data-col-export/);
  assert.match(h, /data-col-delete/);
  assert.match(h, /rs-hold/, "delete is a 3-second hold, never a click");
  assert.ok(!C.viewHtml({ st: { on: true, profile: "p1", turns: 0 } , pid: "p1"}).includes("data-col-export"));
});

test("bind: Turn on posts consent + adult + this profile; Turn off posts off; never anything else", async () => {
  const calls = [];
  let st = { on: false, audio: false, profile: null, turns: 0, clips: 0 };
  const fetchFn = async (url, opt = {}) => {
    calls.push({ url, opt });
    if (url === "/api/collect" && opt.method === "POST") {
      const b = JSON.parse(opt.body);
      assert.equal(opt.headers["X-Outpost-Reset"], "1");
      st = b.on ? { ...st, on: true, audio: !!b.audio, profile: b.profile } : { ...st, on: false, audio: false };
      return { ok: true, json: async () => st };
    }
    return { ok: true, json: async () => st };
  };
  const els = {};
  const mk = (attrs = {}) => ({ ...attrs, focus() {}, set onclick(f) { this._c = f; }, get onclick() { return this._c; }, set onchange(f) { this._ch = f; }, get onchange() { return this._ch; } });
  const zone = {
    set innerHTML(h) { this._h = h; for (const k of Object.keys(els)) delete els[k];
      for (const m of h.matchAll(/data-(col-[a-z]+)/g)) els[m[1]] = mk({ checked: false, disabled: /data-col-go disabled/.test(h) && m[1] === "col-go" }); },
    get innerHTML() { return this._h; },
    querySelector: s => els[(s.match(/data-(col-[a-z]+)/) || [])[1]] || null,
  };
  const el = { querySelector: s => (s === "[data-col-zone]" ? zone : null) };
  const sec = window.__outpost.settingsSections.find(x => x.id === "collect");
  sec.bind(el, { fetchFn });
  await new Promise(r => setTimeout(r, 0));
  assert.ok(els["col-start"]);
  els["col-start"].onclick();
  assert.ok(els["col-agree"] && els["col-go"].disabled);
  els["col-go"].onclick();                                       // not agreed: nothing posted
  assert.equal(calls.filter(c => c.opt.method === "POST").length, 0);
  els["col-agree"].checked = true;
  els["col-go"].onclick();
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  const on = calls.find(c => c.opt.method === "POST");
  assert.deepEqual(JSON.parse(on.opt.body), { on: true, audio: false, consent: true, adult: true, profile: "p1" });
  assert.ok(els["col-stop"], "now on: Turn off");
  els["col-stop"].onclick();
  await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
  assert.deepEqual(JSON.parse(calls.filter(c => c.opt.method === "POST").pop().opt.body), { on: false });
  assert.ok(calls.every(c => c.url.startsWith("/api/collect")), "only this app's own backend");
});

test("export: the desktop hands over to the shell; the browser downloads; a failure says so", async () => {
  const w = { navigator: { userAgent: "Mozilla/5.0 Electron/44.10.0" }, location: { href: "/" } };
  const states = [];
  assert.equal(await C.exportZip({ w, fetchFn: async () => assert.fail("no fetch on desktop"), onState: s => states.push(s) }), "desktop");
  assert.equal(w.location.href, "/__outpost/collect-export");
  w.__lunaCollect({ state: "saved" });
  assert.deepEqual(states, ["saved"]);
  const s2 = [];
  assert.equal(await C.exportZip({ w: { navigator: { userAgent: "Chrome" } }, fetchFn: async () => ({ ok: false, status: 500 }), onState: s => s2.push(s) }), "error");
  assert.deepEqual(s2, ["saving", "error"]);
});

test("copy: short, plain, no model or vendor names", () => {
  const C2 = C.COPY;
  for (const t of [C2.off, C2.on, C2.what, C2.where, C2.share, C2.agree, C2.audio, C2.audioHelp, ...C2.consent]) assert.ok(words(t) <= 14, t);
  for (const t of [C2.start, C2.stop, C2.go, C2.cancel, C2.export, C2.tag]) assert.ok(words(t) <= 3, t);
  const all = JSON.stringify(C2);
  for (const bad of [/\bAI\b/, /LLM/i, /Claude/i, /GPT/i, /Gemini/i, /model/i, /upload/i]) assert.ok(!bad.test(all), String(bad));
});
