// The icon + patch set: every name the UI asks for exists, a patch per lesson, SVGs are well-formed and offline.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { icon, patch, iconNames, patchIds, hasIcon, patchId, ICONS, ALIASES, EMOJI, PATCHES } from "../src/assets/icons.js";

const FE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(FE, "src");
const COURSE = JSON.parse(fs.readFileSync(path.join(FE, "..", "backend", "data", "academy", "course.json"), "utf8"));

const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e =>
  e.isDirectory() ? (e.name === "assets" || e.name === "node_modules" ? [] : walk(path.join(d, e.name))) : [path.join(d, e.name)]);
const uiFiles = [...walk(SRC).filter(f => /\.(js|css|html)$/.test(f)), path.join(FE, "index.html")];

// Pictographs and the UI-chrome symbols this set replaces (not typography such as · → ≥ − —).
const GLYPH = /\p{Extended_Pictographic}|[▶▸▲▼◌↗⌖✓★]/gu;

// What the brief asks the set to cover, by semantic name.
const REQUIRED = ["mic", "speaker", "play", "pause", "back", "next", "close", "settings", "access", "library", "mission",
  "academy", "theme", "info", "check", "warning", "alert", "radio", "houston", "rover", "shield", "sun", "earth", "power",
  "air", "water", "ice", "heater", "science", "shelter", "storm", "camera", "view", "orbit", "site", "captions", "speed",
  "astronaut", "star", "call", "comms", "greenhouse", "explore", "radiation", "rocket", "moon", "retry"];

test("icons: the brief's names and every alias resolve", () => {
  for (const n of REQUIRED) assert.ok(hasIcon(n), `missing icon "${n}"`);
  for (const [a, t] of Object.entries(ALIASES)) assert.ok(ICONS[t], `alias ${a} → missing ${t}`);
  assert.ok(iconNames().length >= REQUIRED.length);
});

test("icons: every icon()/patch() name used in the UI exists", () => {
  const used = [], usedP = [];
  for (const f of uiFiles) {
    const s = fs.readFileSync(f, "utf8");
    for (const m of s.matchAll(/\bicon\(\s*["'`]([\w-]+)["'`]/g)) used.push([m[1], f]);
    for (const m of s.matchAll(/\bpatch\(\s*["'`]([\w-]+)["'`]/g)) usedP.push([m[1], f]);
    for (const m of s.matchAll(/data-icon="([\w-]+)"/g)) used.push([m[1], f]);
  }
  for (const [n, f] of used) assert.ok(hasIcon(n), `${path.relative(FE, f)} uses unknown icon "${n}"`);
  for (const [n, f] of usedP) assert.ok(patchId(n), `${path.relative(FE, f)} uses unknown patch "${n}"`);
});

test("icons: every emoji / symbol still in the UI has a replacement icon", () => {
  for (const [ch, n] of Object.entries(EMOJI)) assert.ok(ICONS[n], `EMOJI ${ch} → missing ${n}`);
  const missing = new Set();
  for (const f of uiFiles) {
    const s = fs.readFileSync(f, "utf8").replace(/‍\p{Extended_Pictographic}/gu, "").replace(/️/g, "");
    for (const m of s.matchAll(GLYPH)) if (!EMOJI[m[0]]) missing.add(`${m[0]} (${path.relative(FE, f)})`);
  }
  assert.deepEqual([...missing], [], "glyphs without an icon mapping");
});

test("patches: one per lesson (by lesson id and badge id), plus mission patches", () => {
  for (const l of COURSE.lessons) {
    assert.ok(PATCHES[l.id], `no patch for lesson ${l.id}`);
    assert.equal(patchId(l.badge.id), l.id, `badge ${l.badge.id} → ${l.id}`);
    assert.equal(PATCHES[l.id].name, l.badge.name, `patch name for ${l.id}`);
  }
  assert.equal(patchId(COURSE.pass_badge), "checkride");
  assert.ok(PATCHES.storm_survivor && PATCHES.outpost_luna);
  for (const id of patchIds()) {
    assert.ok(fs.existsSync(path.join(SRC, "assets", "patches", `${id}.svg`)), `${id}.svg`);
    assert.ok(fs.existsSync(path.join(SRC, "assets", "patches", `${id}-locked.svg`)), `${id}-locked.svg`);
    assert.notEqual(patch(id, { earned: true }), patch(id, { earned: false }));
  }
});

// A small well-formedness check: balanced tags, known SVG elements, quoted attributes, nothing external.
const ELEMENTS = new Set(["svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "title"]);
function checkSvg(s, where) {
  assert.match(s, /^(<!--[\s\S]*?-->\s*)?<svg\b/, `${where}: starts with <svg>`);
  assert.doesNotMatch(s, /\b(?:href|xlink:href|src)\s*=|url\(|@import|<script|<image|<foreignObject|<style|\bon\w+=/i, `${where}: external ref / script`);
  assert.doesNotMatch(s.replace(/xmlns="http:\/\/www\.w3\.org\/2000\/svg"/g, ""), /https?:/, `${where}: URL`);
  assert.doesNotMatch(s, /\bid=/, `${where}: ids collide when inlined many times`);
  const stack = [];
  const body = s.replace(/<!--[\s\S]*?-->/g, "");
  for (const m of body.matchAll(/<(\/?)([a-zA-Z][\w:-]*)((?:\s+[\w:-]+="[^"<]*")*)\s*(\/?)>/g)) {
    const [, close, name, , self] = m;
    assert.ok(ELEMENTS.has(name), `${where}: unexpected <${name}>`);
    if (close) assert.equal(stack.pop(), name, `${where}: </${name}> unbalanced`);
    else if (!self) stack.push(name);
  }
  assert.deepEqual(stack, [], `${where}: unclosed tags`);
  const tags = (body.match(/</g) || []).length, parsed = [...body.matchAll(/<(\/?)([a-zA-Z][\w:-]*)((?:\s+[\w:-]+="[^"<]*")*)\s*(\/?)>/g)].length;
  assert.equal(tags, parsed, `${where}: a tag that is not well-formed`);
}

test("svg: every icon and patch file and every generated string is well-formed and offline", () => {
  for (const dir of ["icons", "patches"]) {
    for (const fn of fs.readdirSync(path.join(SRC, "assets", dir)).filter(n => n.endsWith(".svg")))
      checkSvg(fs.readFileSync(path.join(SRC, "assets", dir, fn), "utf8").trim(), `${dir}/${fn}`);
  }
  for (const n of iconNames()) { checkSvg(icon(n), n); checkSvg(icon(n, { title: "A <b> & \"c\"", size: "1.25em" }), n + " titled"); }
  for (const id of patchIds()) for (const earned of [true, false]) checkSvg(patch(id, { earned, size: 40, title: true }), id);
});

test("icon(): aria-hidden unless titled; currentColor; size; unknown → empty", () => {
  const h = icon("mic");
  assert.match(h, /aria-hidden="true"/); assert.doesNotMatch(h, /<title>/);
  assert.match(h, /stroke="currentColor"/); assert.match(h, /width="24" height="24"/);
  const t = icon("close", { title: "Close <now>", size: 20 });
  assert.match(t, /role="img" aria-label="Close &lt;now&gt;"/); assert.match(t, /<title>Close &lt;now&gt;<\/title>/);
  assert.match(t, /width="20"/); assert.doesNotMatch(t, /aria-hidden/);
  assert.equal(icon("dose"), icon("radiation"));
  const warn = console.warn; console.warn = () => {};
  try { assert.equal(icon("nope"), ""); assert.equal(patch("nope"), ""); } finally { console.warn = warn; }
});

test("patch(): earned uses the fixed palette; locked is a grey outline that follows the theme", () => {
  const e = patch("moon", { size: 40 }), l = patch("scout", { earned: false, title: true });
  assert.match(e, /is-earned/); assert.match(e, /aria-hidden="true"/); assert.match(e, /width="40"/);
  assert.match(l, /is-locked/); assert.match(l, /aria-label="Moon Scout patch, not yet earned"/);
  assert.match(l, /var\(--color-text-3/); assert.match(l, /stroke-dasharray/);
  assert.doesNotMatch(l.replace(/#7D8796/g, ""), /#[0-9A-Fa-f]{6}/, "locked draws in currentColor only");
});

test("build: icons.js and patch files are in sync with their sources", () => {
  execFileSync(process.execPath, [path.join(SRC, "assets", "build-art.mjs"), "--check"], { stdio: "pipe" });
});
