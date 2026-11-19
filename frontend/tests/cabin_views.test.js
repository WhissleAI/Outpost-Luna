// node --test tests/  — 0.4 part 2, the cabin redesign: the real NASA views in the cabin (mission/cabin_views.js), the
// folded header and one cockpit bar, the 18 px HUD floor, the top-down picker, dark first run, the 3-second holds.
// No DOM, no WebGL: the pure parts, plus source checks for the wiring.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as C from "../src/mission/cabin_views.js";
import { normalizePrefs, PREF_DEFAULTS } from "../src/prefs.js";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const icon = n => `<i data-icon="${n}"></i>`;

test("earthBelow: nothing while Earth is up; the rise day from the sim's next comm window", () => {
  assert.equal(C.earthBelow({ earth_visible: true, earth_elev_deg: 2 }, 10), null);
  const a = C.earthBelow({ earth_visible: false, earth_elev_deg: -2.1, next_comm_window_h: 110 }, 12);
  assert.equal(a.day, 6); assert.equal(a.line, "Earth rises Day 6.");
  assert.equal(a.photo, "earthrise"); assert.equal(a.arrow, "up");
  // later today
  assert.equal(C.earthBelow({ earth_visible: false, next_comm_window_h: 3 }, 30).line, "Earth rises later today.");
  // never again this mission: Earthset, no day
  const n = C.earthBelow({ earth_visible: false, earth_elev_deg: -4, next_comm_window_h: null }, 200);
  assert.equal(n.day, null); assert.equal(n.photo, "earthset"); assert.match(n.line, /won't rise again/);
  assert.equal(C.earthBelow({ earth_visible: false, next_comm_window_h: 300 }, 0).day, null, "past day 10 is never");
});

test("earthBelow: the trend from the last elevation seen (rising / setting) picks the arrow and the photo", () => {
  const env = { earth_visible: false, earth_elev_deg: -2.1, next_comm_window_h: 90 };
  const set = C.earthBelow(env, 0, -1.8);
  assert.equal(set.trend, "setting"); assert.equal(set.arrow, "down"); assert.equal(set.photo, "earthrise", "it rises again on day 4");
  const rise = C.earthBelow(env, 0, -2.4);
  assert.equal(rise.trend, "rising"); assert.equal(rise.arrow, "up"); assert.equal(rise.photo, "earthrise");
  assert.equal(C.elevLine(rise), "2.1° below the horizon · rising");
  assert.equal(C.elevLine({ el: null }), "");
});

test("the Earth inset: the real photo with its credit when the pack is in; today's note without it", () => {
  const info = C.earthBelow({ earth_visible: false, earth_elev_deg: -2, next_comm_window_h: 50 }, 0);
  const photo = { url: "/api/views/file/images/earthrise.jpg", title: "Earthrise", credit: "NASA" };
  const html = C.earthInsetHtml(info, photo, icon);
  assert.match(html, /<img class="cb-ei-img is-earthrise" src="\/api\/views\/file\/images\/earthrise\.jpg" alt="Earthrise"/);
  assert.match(html, /Earth rises Day 3\./); assert.match(html, /Earthrise · NASA/); assert.match(html, /trend-up/);
  const plain = C.earthInsetHtml(info, null, icon);
  assert.doesNotMatch(plain, /<img/); assert.match(plain, /Earth is below the horizon\.<\/b> It rises Day 3\./);
  const bad = C.earthInsetHtml(info, { url: "x\" onerror=\"y", title: "<script>" }, icon);
  assert.doesNotMatch(bad, /onerror="y|<script>/, "escaped"); assert.match(bad, /&lt;script&gt;/);
});

test("the SDO loop holds the flare frame (16:51 UTC) under Less motion; frame times read as UTC clock times", () => {
  const frames = ["00:05", "13:35", "16:25", "16:35", "16:55", "17:05", "23:56"].map(t => ({ url: t, time: `2024-05-14T${t}:00Z` }));
  assert.equal(C.stillFrame(frames).url, "16:55");
  assert.equal(C.stillFrame([]), null);
  assert.equal(C.stillFrame([{ url: "a" }, { url: "b" }, { url: "c" }]).url, "b");
  assert.equal(C.frameTime("2024-05-14T16:55:46Z"), "16:55 UTC");
  assert.equal(C.frameTime(""), "");
  assert.equal(C.SUN_CREDIT, "The actual Sun, 14 May 2024");
  assert.match(C.SUN_SOURCE, /NASA\/SDO/);
});

test("the cabin wires the real views only through cabin_views.js (optional pack; today's visuals without it)", () => {
  const cab = src("../src/mission/cabin.js");
  assert.match(cab, /from "\.\/cabin_views\.js"/);
  assert.doesNotMatch(cab, /media\/nasa_views/);
  assert.match(cab, /const sunV = \(stm \|\| wn\) && a\.icon === "storm" \? realSun\(\) : null/, "the storm strip shows the Sun only when the pack has it");
  assert.match(cab, /id="cbSunMon" hidden/, "the Radiation console's Sun monitor starts hidden");
  assert.match(cab, /if \(key === alertKey\) return;/, "the strip is not rebuilt every tick (the loop keeps running)");
  for (const f of ["cabin.css", "mission/cockpit.js", "mission/cockpit3d.js"]) assert.doesNotMatch(src("../src/" + f), /nasa_views|views_wire/, f);
  const ter = src("../src/mission/terrain.js");
  assert.match(ter, /const m = viewModel\("hdu"\); if \(!m \|\| hdu\) return;/, "the HDU only when the pack has it");
  assert.match(ter, /hab\.userData\.modules\.visible = false/);
  assert.doesNotMatch(ter, /emissive: 0x000000/);
});

test("one cockpit bar: the header folds in, the clock state and Days / Science / Ice live in one display unit", () => {
  const cab = src("../src/mission/cabin.js"), css = src("../src/cabin.css");
  assert.match(cab, /export function foldHeader\(root, o = \{\}\)/);
  assert.match(cab, /document\.body\.dataset\.cockpit = "1"/);
  assert.match(cab, /const foldOff = foldHeader\(root, o\);/);
  assert.match(cab, /dispose\(\) \{ clearInterval\(offT\); foldOff\(\);/, "the header comes back when the cabin goes");
  const deck = cab.slice(cab.indexOf('<header class="cb-deck"'), cab.indexOf("</header>"));
  assert.match(deck, /class="cb-dsp"[\s\S]*id="cbClock"[\s\S]*id="cbState"[\s\S]*id="cbSky"[\s\S]*id="cbProg"/);
  assert.match(deck, /id="cbPlay"[\s\S]*id="cbSkip"[\s\S]*id="cbMenuBtn"/);
  assert.match(css, /body\[data-cockpit="1"\] \.topbar\{position:fixed;/);
  assert.match(css, /padding:6px calc\(var\(--cp-r, 0px\) \+ 12px\) 6px calc\(var\(--cp-l, 0px\) \+ 12px\)/);
});

test("the HUD floor: every 0.4 HUD size is at least 18 px", () => {
  const css = src("../src/cabin.css"), part = css.slice(css.indexOf("[0.4] the cabin redesign"));
  assert.match(part, /--hud-min:18px/);
  const hud = /cb-now|cb-deck|cb-dsp|cb-tbtn|cb-view|cb-alert|cb-al-|cb-rover|cb-earthnote|cb-ei-t|cb-state|cb-prog|cb-logbtn|cb-sky/;
  const rules = [...part.matchAll(/([^{}]+)\{([^}]*)\}/g)].filter(m => hud.test(m[1]) && /font-size/.test(m[2]));
  assert.ok(rules.length >= 12, `${rules.length} HUD rules with a size`);
  for (const [, sel, body] of rules) {
    const px = [...body.matchAll(/font-size:(\d+)px/g)].map(m => +m[1]);
    for (const v of px) assert.ok(v >= 18 || /\.cb-ei-c|tv-/.test(sel), `${sel.trim()}: ${v}px`);
    assert.doesNotMatch(body, /font-size:var\(--text-(xs|sm|md)\)/, sel.trim());
  }
});

test("no ceiling light strip in the 3D cabin (it showed as a white line under the top bar)", () => {
  const c3 = src("../src/mission/cockpit3d.js");
  assert.doesNotMatch(c3, /const strip = new THREE\.Mesh/);
});

test("the Mission picker looks straight down on the pole ({clamp: false}, docs/MEDIA.md)", () => {
  const ui = src("../src/mission/ui.js"), g = src("../src/globe.js");
  assert.match(ui, /globe\.mission\.setSite\(\{ \.\.\.site, short: site\.name\.split\(" \("\)\[0\] \}, \{ dist: 2\.0, clamp: false \}\)/);
  assert.match(ui, /globe\.flyTo\(PICK_VIEW\.lat, PICK_VIEW\.lon, window\.__pickDist \|\| PICK_VIEW\.dist, \{ clamp: false \}\)/);
  assert.match(g, /flyTo\(site\.lat, site\.lon, dist, clamp === false \? \{ clamp: false \} : undefined\)/);
  assert.match(g, /function setViewport\(frac, xFrac = 0\)/);
});

test("first run is dark; a saved choice (Light, System) stays", () => {
  assert.equal(PREF_DEFAULTS.theme, "dark");
  assert.equal(normalizePrefs({ theme: "system" }).theme, "system");
  assert.equal(normalizePrefs({ theme: "light" }).theme, "light");
  const html = src("../public/theme-boot.js");   // a file, not inline: the desktop CSP allows no inline script
  assert.match(src("../index.html"), /<script src="\/theme-boot\.js"><\/script>/);
  assert.match(html, /p\.theme==="system"\|\|p\.theme==="light"/);
  assert.match(html, /:"dark";if\(t\)document\.documentElement\.dataset\.theme=t/);
});

test("Save a diagnostics file… and Reset my patches are behind the shared 3-second hold", () => {
  const a11y = src("../src/a11y.js"), dg = src("../src/diagnostics_ui.js");
  assert.match(a11y, /holdButtonHtml\(GROWNUPS\.patches, "data-prof-reset"\)/);   // [0.4.1] in For grown-ups
  assert.match(a11y, /patches: "Reset my patches"/);
  assert.match(a11y, /bindHold\(pr, \{ onFire: \(\) => PA\.resetProgress\(\) \}\)/);
  assert.doesNotMatch(a11y, /Tap again to clear this cadet's patches/);
  assert.match(dg, /holdButtonHtml\(COPY\.save, "data-dg-save"\)/);
  assert.match(dg, /h = bindHold\(btn, \{ holdMs, onFire: \(\) => save\(/);
  assert.doesNotMatch(dg, /btn\.onclick = \(\) => save/);
});
