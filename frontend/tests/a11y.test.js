// Pure helpers of the a11y modules: settings persistence, commands, caption timing, highlighting, vocab.
import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULTS, normalize, loadSettings, saveSettings, stepSpeed, parseCommand, findControl } from "../src/a11y.js";
import { parseWords, estimateWords, wordAt, wrapLines, syllables, wordAtChar } from "../src/caption.js";
import { buildMatcher, tokenize } from "../src/highlight.js";
import { ttsUrlFor } from "../src/floor.js";
import { syllabify } from "../src/academy/vocab.js";

const mem = () => { const m = new Map(); return { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), m }; };

test("settings: defaults, clamp, snap, round-trip, broken storage", () => {
  assert.deepEqual(loadSettings(mem()), DEFAULTS);
  const s = mem();
  const v = saveSettings(s, { speed: 1.4, textScale: 9, contrast: true, junk: 1, captionChars: 5 });
  assert.equal(v.speed, 1.5); assert.equal(v.textScale, 1.5); assert.equal(v.contrast, true); assert.equal(v.captionChars, 24);
  assert.ok(!("junk" in v));
  assert.deepEqual(loadSettings(s), v);
  assert.deepEqual(loadSettings({ getItem: () => "{bad json" }), DEFAULTS);
  assert.deepEqual(loadSettings({ getItem: () => { throw new Error("blocked"); } }), DEFAULTS);
  assert.doesNotThrow(() => saveSettings({ setItem: () => { throw new Error("quota"); } }, { speed: 1 }));
  assert.equal(normalize({ contrast: "yes" }).contrast, false);    // only real booleans
});

test("speed ladder", () => {
  assert.equal(stepSpeed(1, 1), 1.25); assert.equal(stepSpeed(1.5, 1), 1.5); assert.equal(stepSpeed(0.75, -1), 0.75);
  assert.equal(ttsUrlFor("/api/tts", "Hi.", "guide", null, 0, 1, "", 1.5), "/api/tts?voice=guide&text=Hi.&speed=1.5");
  assert.ok(!ttsUrlFor("/api/tts", "Hi.", "guide", null, 0, 1, "", 1).includes("speed"));
});

test("voice commands", () => {
  assert.deepEqual(parseCommand("Where am I?"), { cmd: "where" });
  assert.deepEqual(parseCommand("what can I do"), { cmd: "options" });
  assert.deepEqual(parseCommand("slower"), { cmd: "speed", arg: -1 });
  assert.deepEqual(parseCommand("press the next button"), { cmd: "press", arg: "next" });
  assert.deepEqual(parseCommand("option two"), { cmd: "nth", arg: 2 });
  assert.equal(parseCommand("regolith"), null);                 // a lesson answer is not a command
  assert.equal(parseCommand("albedo is how bright a surface is"), null);
  const b = l => ({ textContent: l, getAttribute: () => null });
  const cs = [b("Next"), b("Hear it again"), b("‹ Course")];
  assert.equal(findControl("next", cs), cs[0]); assert.equal(findControl("hear it", cs), cs[1]); assert.equal(findControl("course", cs), cs[2]);
  assert.equal(findControl("zz", cs), null);
});

test("caption timing", () => {
  assert.deepEqual(parseWords("0-320,320-1000"), [[0, 0.32], [0.32, 1]]);
  assert.deepEqual(parseWords("<x>"), []); assert.deepEqual(parseWords(""), []);
  const est = estimateWords(["Hi,", "regolith", "is", "dust."], 2);
  assert.equal(est.length, 4); assert.ok(est[1][1] - est[1][0] > est[2][1] - est[2][0]);   // longer word, longer slot
  assert.ok(Math.abs(est[3][1] - 1.95) < 1e-9);
  assert.equal(wordAt([[0, .3], [.3, .6], [.6, 1]], 0.45), 1); assert.equal(wordAt([[.1, .3]], 0), -1);
  assert.deepEqual(wrapLines(["aaaa", "bbbb", "cccc"], 9), [[0, 1], [2]]);
  assert.equal(syllables("regolith"), 3); assert.equal(syllables("Moon"), 1);
  assert.equal(wordAtChar(["Copy", "that", "cadet"], 6), 1);
});

test("highlight tokenize: terms, places, resources, numbers with units", () => {
  const m = buildMatcher({ terms: { albedo: "albedo", "impact flash": "impact flash" }, places: { "Shackleton crater": "shackleton", Shackleton: "shackleton" } });
  const parts = tokenize("Albedo near Shackleton crater: power at 40 percent for 6 days in 2026, one impact flash.", m).filter(p => p.kind);
  assert.deepEqual(parts.map(p => [p.text, p.kind]), [["Albedo", "term"], ["Shackleton crater", "place"], ["power", "resource"],
    ["40 percent", "number"], ["6 days", "number"], ["impact flash", "term"]]);
  assert.equal(tokenize("plain text", m).length, 1);
  assert.equal(tokenize("Albedo", m).map(p => p.text).join(""), "Albedo");
});

test("syllabify", () => {
  assert.equal(syllabify("regolith"), "re·go·lith");
  assert.equal(syllabify("Moon"), "Moon");
});
