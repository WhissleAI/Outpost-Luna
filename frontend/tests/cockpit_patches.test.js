// The cockpit's patch key (mission/patches.js, mission/cabin.js paintPatches): earned Flight School and Field School
// patches on the Habitat console, a card that names them, live when a patch is earned.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { normPatches, patchSig, newPatches, keyLabel, trackSummary, patchKeyHtml, patchListHtml, KEY_MAX, TRACK } from "../src/mission/patches.js";
import { patch } from "../src/assets/icons.js";
import { isField, isExplorer } from "../src/explorer.js";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const COURSE = JSON.parse(src("../../backend/data/academy/course.json"));
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// what academy/ui.js badges() hands the cabin, for a set of earned badge ids
const badges = ids => COURSE.lessons.filter(l => ids.includes(l.badge.id)).map(l => ({ id: l.badge.id, name: l.badge.name, lesson: l.id,
  track: l.ride ? "ride" : isField(l) ? "field" : isExplorer(l) ? "explorer" : "core" }));

test("every patch, Field School included, has art and a school on the card", () => {
  const all = badges(COURSE.lessons.map(l => l.badge.id));
  assert.equal(all.length, COURSE.lessons.length);
  assert.ok(all.some(b => b.track === "field"), "Field School patches reach the cockpit");
  const html = patchListHtml(all, { patch, esc });
  assert.equal((html.match(/<li class="cb-patchli/g) || []).length, all.length);
  assert.equal((html.match(/class="patch patch-\w+ is-earned"/g) || []).length, all.length, "every patch in colour");
  for (const b of all) assert.match(html, new RegExp(`<b>${b.name}</b><small>${TRACK[b.track]}</small>`));
});

test("the key: the newest three patches, the word and the count; nothing earned, no key", () => {
  assert.equal(patchKeyHtml([], { patch, esc }), "");
  const six = badges(["scout", "watcher", "sun", "radio", "storm", "observer"]);
  const html = patchKeyHtml(six, { patch, esc });
  assert.equal(KEY_MAX, 3);
  assert.equal((html.match(/<svg/g) || []).length, KEY_MAX);
  assert.match(html, /<span class="cb-patchl" aria-hidden="true">Patches <b class="cb-patchn num">6<\/b><\/span>/);
  assert.match(html, /patch-observe/, "the newest (a Field School patch) shows");
  assert.doesNotMatch(html, /patch-moon /, "the oldest is counted, not drawn");
  assert.equal(keyLabel(6), "Patches: 6 earned. Show them");
  assert.equal(trackSummary(six), "5 Flight School · 1 Field School");
});

test("live: the signature changes with the earned set and the new patch is found", () => {
  const before = badges(["scout", "sun"]), after = badges(["scout", "sun", "fieldkit"]);
  assert.notEqual(patchSig(before), patchSig(after));
  assert.equal(patchSig(before), patchSig(badges(["sun", "scout"])), "course order, not earning order");
  assert.deepEqual(newPatches(before, after).map(b => b.name), ["Field Ready"]);
  assert.deepEqual(normPatches([null, { id: "x" }, { id: "x" }]).length, 1, "bad and duplicate entries dropped");
});

test("the cabin draws the key on the Habitat console, opens the card by keyboard, and listens for outpost:patches", () => {
  const cab = src("../src/mission/cabin.js"), ui = src("../src/academy/ui.js");
  const hab = cab.slice(cab.indexOf('data-panel="habitat"'), cab.indexOf('data-panel="rover"'));
  assert.match(hab, /class="cb-plate cb-hab"[\s\S]*class="cb-sws">\$\{sw\("heaters"\)\}\$\{sw\("science"\)\}[^<]*<div class="cb-patchrow"><button type="button" class="cb-patchkey" id="cbPatchKey" hidden aria-haspopup="dialog" aria-expanded="false" aria-controls="cbPatchPop"/);
  assert.match(hab, /id="cbPatchNews" role="status" aria-live="polite"/, "a new patch is announced");
  const deck = cab.slice(cab.indexOf('<header class="cb-deck"'), cab.indexOf("</header>"));
  assert.doesNotMatch(deck, /cbPatch/, "the cockpit bar's display unit is full: the patches are not on it");
  assert.match(cab, /if \(e\.key === "Enter" \|\| e\.key === " "\) \{ e\.preventDefault\(\); e\.stopPropagation\(\); if \(!e\.repeat\) togglePatches\(true\); \}/, "Enter / Space toggle it, focus into the card");
  assert.match(cab, /id="cbPatchPop" hidden role="dialog"[^>]*aria-labelledby="cbPatchPopT"/);
  assert.match(cab, /e\.key === "Escape"\) \{ e\.preventDefault\(\); e\.stopPropagation\(\); closePatches\(true\)/, "Esc closes, focus back on the key");
  assert.match(cab, /addEventListener\("outpost:patches", onEarned\)/);
  assert.match(cab, /removeEventListener\("outpost:patches", onEarned\)/);
  assert.match(cab, /whyOff\(\); escOff\(\); patchOff\(\);/, "the listener goes with the cabin");
  assert.match(ui, /dispatchEvent\(new CustomEvent\("outpost:patches", \{ detail: \{ id: badge\.id \} \}\)\)/, "the Academy fires it when a patch is awarded");
  assert.match(ui, /badges: \(\) => \(course \? null : fetchCourse\(\)\.catch\(\(\) => \{\}\),/, "Mission can ask before Flight School was opened");
  assert.match(ui, /dispatchEvent\(new CustomEvent\("outpost:patches", \{ detail: \{\} \}\)\)/, "the course landing repaints the key");
  assert.match(cab, /paintPatches\(e && e\.detail && e\.detail\.id \? "earned" : true\)/, "only a real award is announced");
  assert.match(ui, /track: l\.ride \? "ride" : isField\(l\) \? "field" : isExplorer\(l\) \? "explorer" : "core"/);
});

test("the card keeps the 18 px HUD floor; the console key is sized like the console's own labels", () => {
  const css = src("../src/cabin.css");
  const rules = [...css.matchAll(/([^{}]+)\{([^}]*)\}/g)].filter(m => /cb-patch(pop|sum|li)/.test(m[1]) && /font-size/.test(m[2]));
  assert.ok(rules.length >= 4, `${rules.length} card rules with a size`);
  for (const [, sel, body] of rules) {
    for (const m of body.matchAll(/font-size:([^;}]+)/g)) assert.ok(/var\(--hud-min\)/.test(m[1]) || +(/(\d+)px/.exec(m[1]) || [])[1] >= 18, `${sel.trim()}: ${m[1]}`);
  }
  const swl = +/\.c3 \.c3-panel \.cb-swl\{font-size:(\d+)px\}/.exec(css)[1];
  const key = +/\.c3 \.c3-panel \.cb-patchkey\{font-size:(\d+)px/.exec(css)[1];
  assert.ok(key >= swl, `the 3D console's patch key ${key}px, its switch labels ${swl}px`);
});
