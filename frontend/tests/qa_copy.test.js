// [qa] Kid-facing copy outside story.js (docs/COPY.md): no emoji or decorative glyphs in any UI string, Find-it clues
// within the 12-word supporting-line budget, no "!" hype, and no developer text in errors.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = new URL("../src/", import.meta.url).pathname;
const files = dir => readdirSync(dir).flatMap(f => { const p = join(dir, f); return statSync(p).isDirectory() ? files(p) : p.endsWith(".js") ? [p] : []; });
// emoji + the glyphs that stood in for icons (★ ⌖ ⚠ ▶ ›); assets/icons.js maps emoji to icons, so it may name them
const GLYPH = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B50}★⌖▶›]/u;

test("no emoji or stand-in glyphs in UI source strings", () => {
  const bad = [];
  for (const f of files(SRC)) {
    if (f.endsWith("icons.js") || f.endsWith("icons.template.js")) continue;
    readFileSync(f, "utf8").split("\n").forEach((line, i) => {
      if (/^\s*(\/\*\*?|\*)/.test(line)) return;   // doc comments may describe glyphs
      const code = line.replace(/\/\/.*$/, "");
      if (GLYPH.test(code)) bad.push(`${f.replace(SRC, "")}:${i + 1}: ${line.trim().slice(0, 90)}`);
    });
  }
  assert.deepEqual(bad, []);
});

test("Find it: clues are 12 words or fewer, with no '!'", () => {
  const src = readFileSync(join(SRC, "missions.js"), "utf8");
  const clues = [...src.matchAll(/clue: "([^"]+)"/g)].map(m => m[1]);
  assert.ok(clues.length >= 5);
  for (const c of clues) { assert.ok(c.split(/\s+/).length <= 12, c); assert.ok(!c.includes("!"), c); }
  assert.ok(!/Keep looking!|Found it!|done!/.test(src));
});

test("errors never show developer text to a kid", () => {
  const all = files(SRC).map(f => readFileSync(f, "utf8")).join("\n");
  for (const t of ["Is the backend running", "Voice hiccup", "local ear closed", "reach my brain"]) assert.ok(!all.includes(t), t);
});
