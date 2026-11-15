// Settings → Voice: the optional Steer TTS engine (prefs.js engineChoiceHtml / normalizePrefs, floor.js prefStyle /
// packAllowed). Pure: no audio, no network.
import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizePrefs, engineChoiceHtml } from "../src/prefs.js";
import { prefStyle, packAllowed } from "../src/floor.js";

const withPrefs = (P, f) => { globalThis.window = { __outpost: { prefs: normalizePrefs(P), defaultVoice: "zoe" } }; try { return f(); } finally { delete globalThis.window; } };

test("steer: the engine pref is os by default and only os / steer", () => {
  assert.equal(normalizePrefs(null).engine, "os");
  assert.equal(normalizePrefs({ engine: "steer" }).engine, "steer");
  assert.equal(normalizePrefs({ engine: "loud" }).engine, "os");
  assert.equal(normalizePrefs({ steer_voice: "voice_0644" }).steer_voice, "voice_0644");
});

test("steer: switching engines mid-session changes the style of the next line", () => {
  const s1 = withPrefs({ engine: "steer", steer_voice: "voice_0644" }, () => prefStyle({ voice: "guide" }, "guide", 1));
  assert.equal(s1.tts_engine, "steer"); assert.equal(s1.steer_voice, "voice_0644"); assert.equal(s1.pack, false);
  const h = withPrefs({ engine: "steer", steer_voice: "voice_0644" }, () => prefStyle({ voice: "houston" }, "houston", 1));
  assert.equal(h.tts_engine, "steer"); assert.equal(h.steer_voice, undefined);   // Houston keeps its own Steer voice
  const s2 = withPrefs({ engine: "os" }, () => prefStyle({ voice: "guide" }, "guide", 1));
  assert.equal(s2.tts_engine, undefined); assert.notEqual(s2.pack, false);
});

test("steer: the voice pack plays only with the system voice", () => {
  assert.equal(packAllowed(normalizePrefs({ engine: "steer" }), "zoe"), false);
  assert.equal(packAllowed(normalizePrefs({ engine: "os" }), "zoe"), true);
});

test("steer: the switch is disabled until the Steer voice is ready", () => {
  const radio = (html, v) => new RegExp(`value="${v}"[^>]*`).exec(html)[0];
  const missing = engineChoiceHtml({ engine: "os" }, { state: "missing" });
  assert.match(radio(missing, "steer"), /disabled/); assert.match(missing, /data-get-steer/);
  const dl = engineChoiceHtml({ engine: "steer" }, { state: "downloading" });
  assert.match(dl, /Downloading Steer voice…/); assert.match(radio(dl, "os"), /checked/);   // the system voice speaks meanwhile
  const ready = engineChoiceHtml({ engine: "steer" }, { state: "ready" });
  assert.doesNotMatch(radio(ready, "steer"), /disabled/); assert.match(radio(ready, "steer"), /checked/);
});
