// [audit2] docs/AUDIT_2.md: "what do I do?" never says the same thing twice; the new copy keeps the budgets.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { helpLine, doLine } from "../src/academy/guide.js";
import { CALLSIGN_COPY, SCHOOL } from "../src/story.js";

const course = JSON.parse(fs.readFileSync(new URL("../../backend/data/academy/course.json", import.meta.url)));
const words = t => String(t).split(/\s+/).filter(Boolean).length;

test("help: a hint that repeats the do-line is said once", () => {
  assert.equal(helpLine("Guess first. Any guess is fine", "Guess first. Then we'll see."), "Guess first. Then we'll see.");
  assert.equal(helpLine("Drag the Moon to turn it, or tap a side", "Tap Far, or drag the Moon around."), "Tap Far, or drag the Moon around.");
  assert.equal(helpLine("Tap it on the Moon, or say its name", "It's the dark patch right of the middle."),
    "Tap it on the Moon, or say its name. It's the dark patch right of the middle.");
  assert.equal(helpLine("Tap an answer, or say it", ""), "Tap an answer, or say it");
});

test("help: every course step's spoken help is 20 words or fewer and never repeats a sentence", () => {
  for (const L of course.lessons) for (const st of L.steps) {
    const line = helpLine(doLine(st), st.hint);
    assert.ok(words(line) <= 24, `${L.id}: ${line}`);
    const sents = line.split(/(?<=[.!?])\s+/).map(s => s.toLowerCase());
    assert.equal(new Set(sents).size, sents.length, `${L.id}: ${line}`);
  }
});

test("every CSS file keeps its @imports first (a rule before them drops them: the fonts never loaded)", () => {
  const files = [];
  const walk = d => fs.readdirSync(d, { withFileTypes: true }).forEach(e => { const p = d + "/" + e.name; if (e.isDirectory()) walk(p); else if (p.endsWith(".css")) files.push(p); });
  walk(new URL("../src", import.meta.url).pathname);
  assert.ok(files.length > 5);
  for (const f of files) {
    const css = fs.readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    const firstImport = css.search(/@import\b/);
    if (firstImport < 0) continue;
    const before = css.slice(0, firstImport).replace(/@charset[^;]*;/, "").trim();
    assert.equal(before, "", `${f}: something comes before its first @import`);
    const lastImport = css.lastIndexOf("@import");
    const between = css.slice(firstImport, lastImport).replace(/@import[^;]*;/g, "").trim();
    assert.equal(between, "", `${f}: a rule sits between its @imports`);
  }
});

test("new copy keeps the budgets", () => {
  for (const t of [CALLSIGN_COPY.empty, CALLSIGN_COPY.typed, CALLSIGN_COPY.saved("Nova"), SCHOOL.answerFirst, SCHOOL.progressLine(3, 6, "Power from the Sun"),
    SCHOOL.mapHelp("Continue", "Power from the Sun")]) assert.ok(words(t) <= 12, t);
});
