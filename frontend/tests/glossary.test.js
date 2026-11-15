// Space-word chips (owner bug, 0.1.2: "these buttons like lava with i sometimes are not really clickable, shows
// nothing"). Every word our text can mark as a space word has a kid definition, and every chip carries what its click
// needs. The click itself is checked in a browser by tests/e2e/flows_e2e.py (glossary section).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildMatcher, tokenize } from "../src/highlight.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const DATA = path.join(ROOT, "backend", "data");
const G = JSON.parse(fs.readFileSync(path.join(DATA, "glossary.json"), "utf8")).terms;
// the client builds its matcher exactly like this from GET /api/glossary (highlight.js load())
const terms = {};
for (const [term, v] of Object.entries(G)) for (const f of v.forms || [term]) terms[f] = term;
const m = buildMatcher({ terms });

/** Every string in a JSON file (the course, places, facts, the guide's fixed lines and answer templates). */
function strings(file) {
  const out = [], walk = x => { if (typeof x === "string") out.push(x); else if (x && typeof x === "object") Object.values(x).forEach(walk); };
  walk(JSON.parse(fs.readFileSync(path.join(DATA, file), "utf8")));
  return out.filter(s => s.split(/\s+/).length >= 3);
}
const SOURCES = ["academy/course.json", "places.json", "facts.json", "learning/concepts.json", "voice_pack/lines.json"].filter(f => fs.existsSync(path.join(DATA, f)));

test("every space word the app's text can mark has a kid definition (<= 20 words)", () => {
  const seen = new Map();
  for (const f of SOURCES) for (const s of strings(f)) for (const p of tokenize(s, m)) {
    if (p.kind !== "term") continue;
    const e = G[p.ref];
    assert.ok(e, `${f}: "${p.text}" is marked but has no glossary entry`);
    assert.ok(e.explain && e.explain.split(/\s+/).length <= 20, `${p.ref}: a short definition`);
    seen.set(p.ref, (seen.get(p.ref) || 0) + 1);
  }
  assert.ok(seen.size >= 15, `the course and our lines use many space words (${seen.size})`);
  assert.ok(seen.has("lava"), "lava (the owner's card) is a linked word");
});

test("the words our lines use most all have entries (and a NASA source when no crew clip says them)", () => {
  const need = ["lava", "mare", "crater", "regolith", "highlands", "terminator", "far side", "near side", "ejecta", "rille",
    "basin", "impact", "orbit", "phase", "eclipse", "solar storm", "millisievert", "shelter", "rover", "permanently shadowed region", "ice"];
  for (const t of need) assert.ok(G[t] && G[t].explain, t);
  assert.ok(G.mare.forms.includes("dark plain"), "dark plain → mare");
  for (const [t, v] of Object.entries(G)) if (v.source) assert.match(v.source.url, /^https:\/\/(www|science)\.nasa\.gov\//, t);
});

test("a resource word that is also a space word opens its meaning (not a dead double underline)", () => {
  const parts = tokenize("Send the rover for ice before the solar storm.", m).filter(p => p.kind);
  assert.deepEqual(parts.map(p => [p.text, p.kind]), [["rover", "term"], ["ice", "term"], ["solar storm", "term"]]);
});

test("a chip carries data-kind and data-ref (they were inside a comment: every chip was dead)", () => {
  const src = fs.readFileSync(path.join(ROOT, "frontend", "src", "highlight.js"), "utf8");
  const code = src.split("\n").map(l => l.replace(/\/\/.*$/, "")).join("\n");   // comments out
  const chips = code.slice(code.indexOf("function chips("), code.indexOf("function markCaption("));
  assert.match(chips, /b\.dataset\.kind\s*=\s*p\.kind/);
  assert.match(chips, /b\.dataset\.ref\s*=\s*p\.ref/);
});
