// node --test tests/  — 0.4 cabin follow-up (a reviewer's notes on the PR #145 screenshots): the consoles read flat from
// the seat, a storm keeps every console readable, the real Sun is recognisable (gold, the whole disc, the flare region,
// never a dark first frame), the Site view frames the outpost, and ux_audit2.py holds "Reset my patches".
// No DOM, no WebGL: three.js maths, the pure Sun toning, and source checks for the wiring.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as THREE from "three";
import { consoleSkew, MAX_SKEW, RIDE_LAYOUT } from "../src/mission/cockpit3d.js";
import { SITE_FRAME } from "../src/mission/terrain.js";
import * as C from "../src/mission/cabin_views.js";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const lum = ([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;

test("every console's text leans no more than MAX_SKEW (8°) from the seat, missions and the check ride", () => {
  assert.equal(MAX_SKEW, 8);
  for (const [w, h] of [[1440, 900], [1280, 720], [1024, 640], [1920, 1080], [970, 900]]) {
    for (const [name, layout] of [["mission", null], ["ride", RIDE_LAYOUT]]) {
      const sk = consoleSkew(layout, { w, h });
      assert.deepEqual(Object.keys(sk).sort(), ["comm", "displays", "habitat", "pedestal", "radiation", "rover"]);
      for (const [id, deg] of Object.entries(sk)) assert.ok(deg <= MAX_SKEW, `${name} ${w}x${h} ${id}: ${deg}°`);
    }
  }
  // the old angles (rover / comm yawed 0.6 and pitched 0.62, the pedestal laid back 1.0) are what the reviewer saw
  const old = consoleSkew({ rover: { pos: [-1.12, 0.62, -1.02], rot: [-0.62, 0.6, 0], w: 0.8, px: 560, pxh: 300 } });
  assert.ok(old.rover > 12, `the old Rover console leaned ${old.rover}°`);
});

test("the live seat view reports the same lean (tools/mission_ui.py reads c3.skew)", () => {
  const c3 = src("../src/mission/cockpit3d.js"), ui = src("../tools/mission_ui.py");
  assert.match(c3, /get skew\(\)/);
  assert.match(ui, /__c3\.skew/);
  assert.match(ui, /MAX_SKEW = 8/);
});

test("a storm dims the room, not the consoles: the shade sits under the consoles' faces; red alert light in the room", () => {
  const css = src("../src/cabin.css"), cab = src("../src/mission/cabin.js"), c3 = src("../src/mission/cockpit3d.js");
  assert.match(css, /\.m-cabin \.cb\.is-3d::before\{display:none\}/, "no full-screen shade over the 3D consoles");
  assert.match(css, /\.m-cabin \.cb\.is-3d \.c3>\.c3-css\{z-index:1\}/, "the consoles' DOM faces above the room's shade");
  assert.match(css, /\.m-cabin \.cb\.is-3d\.is-storm \.c3::after\{/);
  assert.match(css, /\.m-cabin \.cb\.is-3d\.is-takeover>:is\(\.cb-deck,\.cb-viewbar\)\{opacity:1\}/, "the cockpit bar stays readable");
  assert.match(cab, /cabS\.classList\.toggle\("is-storm", !!storm\)/);
  assert.match(cab, /c3\.alert\(!!storm\)/);
  assert.match(c3, /function setAlert\(on\)/);
});

test("the Sun's gold ramp runs dark to white-hot, and brightens with the value", () => {
  assert.deepEqual(C.sunTone(0), [0, 0, 0]);
  assert.deepEqual(C.sunTone(1), [255, 255, 236]);
  let prev = -1;
  for (let v = 0; v <= 1.0001; v += 0.05) { const L = lum(C.sunTone(v)); assert.ok(L >= prev, `monotonic at ${v.toFixed(2)}`); prev = L; }
  const mid = C.sunTone(0.6); assert.ok(mid[0] > mid[2] + 100, "gold, not teal");
  assert.deepEqual(C.sunTone(-3), [0, 0, 0]); assert.deepEqual(C.sunTone(9), [255, 255, 236]);
});

test("the contrast stretch ignores the black sky and spans the lit disc", () => {
  const hist = new Array(256).fill(0);
  hist[0] = 50000;                                   // the sky
  for (let v = 20; v <= 120; v++) hist[v] = 100;     // a dim disc, like AIA 131
  const [lo, hi] = C.stretchBounds(hist);
  assert.ok(lo >= 20 && lo <= 22, `lo ${lo}`); assert.ok(hi >= 118 && hi <= 120, `hi ${hi}`);
  assert.deepEqual(C.stretchBounds(new Array(256).fill(0)), [0, 255], "an empty frame");
});

test("toneSun turns a dim teal frame into a bright gold one", () => {
  // a 'frame': half sky, half dim teal disc (AIA 131 at its usual exposure), one hot pixel (the active region)
  const n = 4000, px = new Uint8ClampedArray(n * 4);
  for (let i = 0; i < n; i++) { const disc = i >= n / 2, v = 40 + (i % 80); px.set(disc ? [10, v, v, 255] : [0, 0, 0, 255], i * 4); }
  px.set([200, 255, 255, 255], (n - 1) * 4);
  const k = n - 80 + 40;   // a disc pixel at the disc's median brightness
  const before = lum([px[k * 4], px[k * 4 + 1], px[k * 4 + 2]]);
  C.toneSun(px);
  const after = lum([px[k * 4], px[k * 4 + 1], px[k * 4 + 2]]);
  assert.ok(after > before * 1.4, `disc brighter: ${before.toFixed(0)} -> ${after.toFixed(0)}`);
  assert.ok(px[k * 4] > px[k * 4 + 2], "warm");
  assert.deepEqual([...px.slice(0, 3)], [0, 0, 0], "the sky stays black");
  assert.ok(lum([px[(n - 1) * 4], px[(n - 1) * 4 + 1], px[(n - 1) * 4 + 2]]) > 240, "the active region white-hot");
});

test("the loop starts on the flare frame (never the dark first frame of the day) and the flare ring is on the disc", () => {
  const frames = ["00:05", "13:35", "16:25", "16:35", "16:55", "17:05", "23:56"].map(t => ({ url: t, time: `2024-05-14T${t}:00Z` }));
  const o = C.playOrder(frames);
  assert.equal(o[0].url, "16:55"); assert.equal(o.length, frames.length); assert.equal(o[o.length - 1].url, "16:35");
  assert.deepEqual(C.playOrder([]), []);
  const [x, y] = C.flareOnCanvas();
  assert.ok(x > 0.8 && x < 0.97 && y > 0.55 && y < 0.7, `AR 13664 at the west limb, inside the crop: ${x.toFixed(2)}, ${y.toFixed(2)}`);
  const r = Math.hypot(x - 0.5, y - 0.5); assert.ok(r < 0.5, "inside the round crop");
  const cab = src("../src/mission/cabin.js"), cv = src("../src/mission/cabin_views.js");
  assert.match(cab, /const sv = realSun\(\); if \(sv\) preloadSun\(sv\.frames\);/, "frames warmed as soon as the pack is in");
  assert.match(cab, /class="cb-sun-ring"/); assert.match(cab, /X8\.7 flare/);
  assert.match(cv, /show\(still\)/, "the first frame drawn is the flare frame");
  assert.match(cv, /if \(!alive \|\| !c \|\| !g\) return false;/, "a frame that isn't ready is skipped, the last one stays up");
  assert.equal(C.SUN_CREDIT, "The actual Sun, 14 May 2024"); assert.equal(C.SUN_SOURCE, "NASA/SDO");
});

test("the Sun is bigger on the Radiation console and the storm strip, with a warm glow until it is drawn", () => {
  const css = src("../src/cabin.css");
  assert.match(css, /\.cb-sun-disc\{position:relative;display:block;width:150px;height:150px;/);
  assert.match(css, /\.cb-al-sun\{flex:none;width:64px;height:64px;/);
  assert.match(css, /\.cb-al-sun\{[^}]*background:radial-gradient\(circle,#ffcf6a/);
  assert.doesNotMatch(css, /\.cb-sunmon img|\.cb-al-sun img/, "no more <img> swaps (they showed black while a frame decoded)");
});

/** Project world points through the Site camera at drift angle `da`; -> [ndcX, ndcY] for each. */
function siteShot(da, pts, aspect = 1.6) {
  const F = SITE_FRAME, a = F.base + da;
  const cam = new THREE.PerspectiveCamera(F.fov, aspect, 0.3, 1e5);
  cam.position.set(F.cx + Math.sin(a) * F.r, F.up, F.cz - Math.cos(a) * F.r); cam.lookAt(F.cx, F.lookUp, F.cz); cam.updateMatrixWorld(true);
  return pts.map(p => { const v = new THREE.Vector3(...p).project(cam); return [v.x, v.y]; });
}

test("the Site view frames the outpost: the habitat, the rover park and the array's panels in view, the habitat big enough to read", () => {
  // flat ground at y = 0 (the camera height is above the pad), over the first ~2 minutes of drift (0.012 rad/s)
  for (const da of [0, 0.3, 0.6, 0.9, 1.4]) {
    const [hab, habTop, park, wing] = siteShot(da, [[0, 0, 2.5], [0, 6, 2.5], [14, 0, 9], [34, 13, 18]]);
    for (const [n, p] of [["habitat", hab], ["rover park", park], ["array wing", wing]]) assert.ok(Math.abs(p[0]) < 0.98 && Math.abs(p[1]) < 0.98, `${n} in view at +${da} rad: ${p.map(v => v.toFixed(2))}`);
    // the window's lower edge is behind the Displays console: keep the habitat in the upper ~75% of the frame
    assert.ok(hab[1] > -0.5, `habitat clear of the consoles at +${da} rad: ${hab[1].toFixed(2)}`);
    assert.ok((habTop[1] - hab[1]) / 2 > 0.07, `the habitat stands ≥ 7% of the frame tall at +${da} rad: ${((habTop[1] - hab[1]) / 2).toFixed(3)}`);
  }
  assert.ok(SITE_FRAME.r <= 56, "close enough to read (the old pose was 64 m out, aimed 18 m past the outpost)");
});

test("ux_audit2.py holds Reset my patches for 3 s (a click never clears it)", () => {
  const a = src("../tools/ux_audit2.py");
  assert.doesNotMatch(a, /Reset my patches \(twice\)/);
  assert.match(a, /hold\(pg, "\[data-prof-reset\]", 3400\)/);
  assert.match(a, /def hold\(pg, sel, ms\):[\s\S]*pg\.mouse\.down\(\)[\s\S]*pg\.wait_for_timeout\(ms\)[\s\S]*pg\.mouse\.up\(\)/);
});
