// Settings → Voice: two engines, the computer's voice (default) or Steer TTS (prefs.js engineChoiceHtml /
// normalizePrefs, floor.js prefStyle / packAllowed, a11y.js the Voice section). Pure: no audio, no network.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { normalizePrefs, engineChoiceHtml, moreVoicesHint } from "../src/prefs.js";
import { prefStyle, packAllowed } from "../src/floor.js";

const withPrefs = (P, f) => { globalThis.window = { __outpost: { prefs: normalizePrefs(P), defaultVoice: "zoe" } }; try { return f(); } finally { delete globalThis.window; } };
const radio = (html, v) => new RegExp(`value="${v}"[^>]*`).exec(html)[0];

test("engine pref: os by default and only os / steer; old OS-voice picks and voice_all are dropped", () => {
  assert.equal(normalizePrefs(null).engine, "os");
  assert.equal(normalizePrefs({ engine: "steer" }).engine, "steer");
  assert.equal(normalizePrefs({ engine: "loud" }).engine, "os");
  assert.equal(normalizePrefs({ steer_voice: "voice_0644" }).steer_voice, "voice_0644");
  const old = normalizePrefs({ voice: "com.apple.voice.Samantha", voice_all: true });
  assert.equal(old.voice, ""); assert.equal(old.voice_all, false);     // the OS picks its own voice now
});

test("switching engines mid-session changes the style of the next line; Steer's voice for every role", () => {
  const s1 = withPrefs({ engine: "steer", steer_voice: "voice_0644" }, () => prefStyle({ voice: "guide" }, "guide", 1));
  assert.equal(s1.tts_engine, "steer"); assert.equal(s1.steer_voice, "voice_0644"); assert.equal(s1.pack, false);
  const h = withPrefs({ engine: "steer", steer_voice: "voice_0644" }, () => prefStyle({ voice: "houston" }, "houston", 1));
  assert.equal(h.tts_engine, "steer"); assert.equal(h.steer_voice, "voice_0644");   // Houston is relayed by CAPCOM
  const s2 = withPrefs({ engine: "os" }, () => prefStyle({ voice: "guide" }, "guide", 1));
  assert.equal(s2.tts_engine, undefined); assert.equal(s2.tts_voice, undefined); assert.notEqual(s2.pack, false);
});

test("the voice pack plays only with the computer's voice", () => {
  assert.equal(packAllowed(normalizePrefs({ engine: "steer" }), "zoe"), false);
  assert.equal(packAllowed(normalizePrefs({ engine: "os" }), "zoe"), true);
  assert.equal(packAllowed(normalizePrefs({ engine: "os", pack: false }), "zoe"), false);
});

test("exactly two engine choices; the Steer option is disabled until ready", () => {
  const ready = engineChoiceHtml({ engine: "steer" }, { state: "ready" });
  assert.equal((ready.match(/name="p-engine"/g) || []).length, 2);
  assert.match(ready, /Your computer's voice/); assert.match(ready, /Steer TTS \(Whissle\)/);
  assert.doesNotMatch(radio(ready, "steer"), /disabled/); assert.match(radio(ready, "steer"), /checked/);
  // 0.1.x bundles Steer: a missing model is "not available", never a download button
  const missing = engineChoiceHtml({ engine: "os" }, { state: "missing", downloadable: false });
  assert.match(radio(missing, "steer"), /disabled/); assert.doesNotMatch(missing, /data-get-steer/);
  assert.match(missing, /Not available on this computer/);
  // the 0.3 line (first-run downloads): a Get button, then "Downloading…", the computer's voice meanwhile
  assert.match(engineChoiceHtml({ engine: "os" }, { state: "missing", downloadable: true }), /data-get-steer/);
  const dl = engineChoiceHtml({ engine: "steer" }, { state: "downloading" });
  assert.match(dl, /Downloading Steer voice…/); assert.match(radio(dl, "os"), /checked/);
});

test("Settings → Voice: no OS voice grid, no 'use this voice for everyone'; Steer's list only under Steer", () => {
  const src = fs.readFileSync(new URL("../src/a11y.js", import.meta.url), "utf8");
  assert.doesNotMatch(src, /Use this voice for everyone/);
  assert.doesNotMatch(src, /data-pb="voice_all"/);
  assert.doesNotMatch(src, /data-p="voice"/);                        // no OS voice radio list
  const sec = src.slice(src.indexOf('if (section === "voice" && PA)'), src.indexOf("function bindSteer"));
  const osBranch = sec.slice(sec.indexOf("if (!steerOn) {"), sec.indexOf("const vs = await PA.loadSteerVoices()"));
  assert.match(osBranch, /data-pb="pack"/);                          // the recorded guide voice: computer voice only
  assert.doesNotMatch(osBranch, /data-p="steer_voice"/);
  const steerBranch = sec.slice(sec.indexOf("const vs = await PA.loadSteerVoices()"));
  assert.match(steerBranch, /data-p="steer_voice"/); assert.match(steerBranch, /data-preview/);
  assert.doesNotMatch(steerBranch, /data-pb="pack"/);
});

test("the hint points parents at better OS voices", () => {
  assert.match(moreVoicesHint("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)"), /System Settings/);
  assert.match(moreVoicesHint("Mozilla/5.0 (Windows NT 10.0; Win64; x64)"), /Windows voices/);
});
