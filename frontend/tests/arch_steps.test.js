// Archaeology steps (docs/COURSES.md §3.2): layers, rings, hillshade, decide. The renderers send what the server grades
// (backend/app/academy/arch_steps.py), every control is a button / slider (keys and controller reach it), nothing is
// inline script (CSP), and the dev harness never changes the Moon.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = globalThis.window || {};
const A = await import("../src/academy/arch_steps.js");
const { DO, INTRO } = await import("../src/academy/guide.js");
const { anyPatch, registerClassLessons } = await import("../src/academy/class_patch.js");
const R = window.__outpost.stepRenderers;

const LAYERS = { type: "layers", layers: [{ id: "topsoil", label: "Topsoil", h: 1 }, { id: "collapse", label: "Roof fall", h: 1.4 },
  { id: "ash", label: "Ash", h: 0.6, finds: "charcoal" }, { id: "floor", label: "Floor", h: 0.6, finds: "sherd" }, { id: "rock", label: "Sandstone", h: 1 }],
  pit: { id: "pit", label: "Pit", from: "topsoil", to: "ash" } };
const RINGS = { type: "rings", master: { from: 1200, to: 1290, w: Array.from({ length: 91 }, (_, k) => 0.5 + (k % 7) / 5) },
  beam: { n: 50, w: Array.from({ length: 50 }, (_, k) => 0.5 + ((k + 26) % 7) / 5) }, start: 1250, tol: 1,
  source: { title: "NOAA", url: "https://www.ncei.noaa.gov/" } };
const HILL = { type: "hillshade", need: 2, image: { low_url: "/a.jpg", high_url: "/b.jpg", w: 1400, h: 1000, width_m: 900, alt: "Lidar", credit: "USGS", source: { title: "USGS", url: "https://www.usgs.gov/" } },
  targets: [{ id: "house", label: "Far View House", x: 0.3, y: 0.4, r: 0.05 }, { id: "lake", label: "Mummy Lake", x: 0.7, y: 0.6, r: 0.06 }] };
const DECIDE = { type: "decide", options: [{ id: "leave", label: "Photograph it and leave it" }, { id: "take", label: "Take it home" }] };

/** A tiny element stand-in: buttons with dataset and onclick, plus the named boxes. */
function fakeEl(html) {
  const btns = [...html.matchAll(/<button[^>]*>/g)].map(([tag]) => {
    const at = k => (tag.match(new RegExp(`${k}="([^"]*)"`)) || [])[1];
    return { cls: at("class") || "", disabled: / disabled/.test(tag), dataset: { ...(at("data-c") != null ? { c: at("data-c") } : {}), ...(at("data-move") != null ? { move: at("data-move") } : {}) }, onclick: null, set textContent(v) { this.text = v; } };
  });
  const has = cls => b => b.cls.split(" ").includes(cls);
  return { btns, querySelector: () => null, querySelectorAll: sel => btns.filter(b => sel.split(",").some(s => has(s.trim().split(".").pop())(b))) };
}
const ctxOf = (acc, extra = {}) => { const sent = []; return { sent, ctx: { step: { accept: acc }, acc, answer: i => sent.push(i), esc: s => s, state: {}, locked: false, guide: {}, ...extra } }; };

test("the build-up types ride the Field steps' `got` loop; every type has a do-line and an intro", () => {
  const ui = readFileSync(new URL("../src/academy/ui.js", import.meta.url), "utf8");
  assert.match(ui, /const FIELD_STEP_TYPES = \[\.\.\.MOON_FIELD_TYPES, \.\.\.ARCH_BUILDUP_TYPES(, \.\.\.SPEECH_STEP_TYPES)?\]/);   // + speech steps (docs/SPEECH_LEARNING.md)
  assert.deepEqual(A.ARCH_BUILDUP_TYPES, ["layers", "hillshade"]);
  for (const t of A.ARCH_STEP_TYPES) {
    assert.ok(R[t], t);
    assert.ok(DO[t] && DO[t].split(/\s+/).length <= 10, t);
    assert.ok(INTRO[t] && INTRO[t].startsWith("New:"), t);
  }
});

test("layers: the trench draws every layer top to bottom and the pit cuts from below `from` into `to`", () => {
  const L = A.trenchLayout(LAYERS, { width: 320, height: 168 });
  assert.deepEqual(L.rows.map(r => r.letter), ["A", "B", "C", "D", "E"]);
  assert.ok(Math.abs(L.rows.at(-1).y + L.rows.at(-1).h - 168) < 0.01);
  const top = L.rows[0], ash = L.rows[2];
  assert.ok(Math.abs(L.pit.top - (top.y + top.h)) < 0.01 && L.pit.bottom > ash.y && L.pit.bottom < ash.y + ash.h);
});

test("layers: jumbled chips (the pit among them), a tap sends the id, placed chips are disabled", () => {
  assert.deepEqual(A.layerChips(LAYERS).map(c => c.id), ["ash", "floor", "pit", "collapse", "rock", "topsoil"]);
  const { ctx, sent } = ctxOf(LAYERS, { state: { got: ["rock"] } });
  const r = R.layers(ctx), el = fakeEl(r.html);
  r.bind(el);
  assert.ok(el.btns.find(b => b.dataset.c === "rock").disabled);
  el.btns.find(b => b.dataset.c === "floor").onclick();
  assert.deepEqual(sent, [{ choice: "floor" }]);
  assert.match(r.html, /role="img" aria-label="Trench wall, top to bottom: A Topsoil/);
});

test("rings: the beam stays on the strip; the slider buttons move it and Lock in sends the year", () => {
  assert.equal(A.clampOuter(RINGS, 1100), 1249);   // 1200 + 50 - 1
  assert.equal(A.clampOuter(RINGS, 1400), 1290);
  const { ctx } = ctxOf(RINGS);
  const r = R.rings(ctx);
  assert.equal(ctx.state.outer, 1250);
  assert.match(r.html, /role="slider" tabindex="0"/);
  assert.match(r.html, /aria-valuenow="1250"/);
  assert.match(r.html, /data-c="1250">Lock in 1250</);
  assert.equal(A.bars([1, 2.2, 0], { step: 6, height: 56 })[1].h, 56);
  assert.equal(A.bars([0], { height: 56 })[0].h, 2);   // a missing ring still shows
});

test("hillshade: a tap is sent as image fractions; the keyboard crosshair stops at the edge", () => {
  assert.deepEqual(A.tapFraction({ left: 100, top: 50, width: 400, height: 200 }, 300, 100), { x: 0.5, y: 0.25 });
  assert.deepEqual(A.tapFraction({ left: 0, top: 0, width: 100, height: 100 }, -5, 120), { x: 0, y: 1 });
  assert.deepEqual(A.moveCross({ x: 0.5, y: 0.5 }, "ArrowRight"), { x: 0.525, y: 0.5 });
  assert.equal(A.moveCross({ x: 0.99, y: 0.5 }, "ArrowRight"), null);
  assert.equal(A.moveCross({ x: 0.5, y: 0.5 }, "Enter"), null);
  const { ctx } = ctxOf(HILL, { state: { got: ["house"] }, guide: { focus: ["lake"] } });
  const html = R.hillshade(ctx).html;
  assert.match(html, /1 of 2 found/);
  assert.match(html, /class="ar-tag"[^>]*>Far View House</);
  assert.match(html, /class="ar-glow"/);        // rung 2: the next one glows
  assert.match(html, /tabindex="0" role="application"/);
  assert.match(html, /aria-pressed="true">.*Low sun/s);
  assert.doesNotMatch(html, /\blat\b|\blon\b|latitude|longitude/);         // image fractions only (park-level rule)
});

test("decide: numbered options send their id; the law card shows on the locked step", () => {
  const { ctx, sent } = ctxOf(DECIDE);
  const r = R.decide(ctx), el = fakeEl(r.html);
  r.bind(el);
  el.btns[1].onclick();
  assert.deepEqual(sent, [{ choice: "take" }]);
  assert.doesNotMatch(r.html, /ar-law/);
  const locked = R.decide({ ...ctx, locked: true, state: { law: { title: "ARPA (1979)", text: "Permit needed.", source: { title: "NPS", url: "https://www.nps.gov/" } } } }).html;
  assert.match(locked, /<b>ARPA \(1979\)<\/b>/);
});

test("no inline handlers or scripts in any renderer (the app's CSP)", () => {
  const all = [R.layers(ctxOf(LAYERS).ctx).html, R.rings(ctxOf(RINGS).ctx).html, R.hillshade(ctxOf(HILL).ctx).html, R.decide(ctxOf(DECIDE).ctx).html].join("");
  assert.doesNotMatch(all, /\son[a-z]+=|<script/i);
  const src = readFileSync(new URL("../src/academy/arch_steps.js", import.meta.url), "utf8");
  assert.doesNotMatch(src, /eval\(|new Function/);
});

test("course lessons draw a round letter patch; Moon ids keep their drawn art", () => {
  registerClassLessons([{ id: "archaeology:dating", title: "Dating the past", badge: { id: "archaeology:ring_counter", name: "Ring Counter", glyph: "R" } }]);
  assert.match(anyPatch("archaeology:dating"), /patch-class/);
  assert.match(anyPatch("archaeology:ring_counter"), />R</);
  assert.doesNotMatch(anyPatch("scout"), /patch-class/);
  registerClassLessons([]);
});
