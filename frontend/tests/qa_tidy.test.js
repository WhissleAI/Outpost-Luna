// QA tidy (docs/QA.md): QA-61 the picker pins redraw only when the picture changes, QA-62 44px hit areas,
// QA-63 the crew audio's failure line, QA-65 the debrief takeaway for a lesson that came back, QA-66 a finished mission.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pinLayout, PIN_ROW } from "../src/mission/pin_layout.js";
import { CALLBACKS, callbackTakeaway } from "../src/story.js";

const src = p => readFileSync(new URL(`../src/${p}`, import.meta.url), "utf8");
const P = [{ id: "a", x: 500, y: 300 }, { id: "b", x: 520, y: 340 }, { id: "c", x: 480, y: 360 }];

test("QA-61: the pin layout's key is stable for a still globe and sub-pixel jitter", () => {
  const k = pinLayout(P, 900, "a").key;
  assert.equal(pinLayout(P.map(o => ({ ...o })), 900, "a").key, k);
  assert.equal(pinLayout(P.map(o => ({ ...o, x: o.x + 0.02 })), 900, "a").key, k);
});

test("QA-61: the key changes when the camera moves, the layer resizes or the pick changes", () => {
  const k = pinLayout(P, 900, "a").key;
  assert.notEqual(pinLayout(P.map(o => ({ ...o, x: o.x + 3 })), 900, "a").key, k);
  assert.notEqual(pinLayout(P, 400, "a").key, k);
  assert.notEqual(pinLayout(P, 900, "b").key, k);
  assert.notEqual(pinLayout(P.slice(1), 900, "a").key, k);   // a site turned away
});

test("QA-61: labels sit in one column left of the cluster, top to bottom, one row each", () => {
  const L = pinLayout(P, 900, "b");
  assert.deepEqual(L.rows.map(r => r.id), ["a", "b", "c"]);
  assert.ok(L.rows.every(r => r.lab[0] === L.rows[0].lab[0] && r.lab[0] < 480));
  L.rows.slice(1).forEach((r, i) => assert.equal(r.lab[1] - L.rows[i].lab[1], PIN_ROW));
  assert.equal((L.lines.match(/<path /g) || []).length, 3);
  assert.equal((L.lines.match(/class="is-sel"/g) || []).length, 1);
  assert.deepEqual(pinLayout([], 900, "a").rows, []);
});

test("QA-61: the picker loop touches the DOM only on a new key (no per-frame querySelector)", () => {
  const ui = src("mission/ui.js"), body = ui.slice(ui.indexOf("const tick = () => {"), ui.indexOf("tick();", ui.indexOf("const tick = () => {")));
  assert.match(body, /if \(L\.key !== lastKey\)/);
  assert.doesNotMatch(body, /querySelector/);
});

test("QA-62: a 44px row pitch for the pin labels, and hit areas on the small controls", () => {
  assert.ok(PIN_ROW >= 44);
  const css = src("styles.css") + src("mission/mission.css");
  for (const sel of [".hud button::after", ".ghost::after", ".np-stop::after", ".mx-x::after", ".mx-pin::after", ".modes button::after"])
    assert.ok(css.includes(sel + "{"), `${sel} gives the control a 44px hit area`);
});

test("QA-63: the crew audio's failure says so plainly and offers a retry", () => {
  const p = src("player.js");
  assert.match(p, /line: "Couldn't load the crew audio\."/);
  assert.match(p, /retry: "Try again"/);
  assert.match(p, /catch \(e\) \{ if \(my === seq\) failed\(raw\); return false; \}/);
  assert.match(src("api.js"), /clipCache\.delete\(id\)/, "a failed fetch isn't cached, so Try again really retries");
});

test("QA-65: every lesson that comes back has a whole-sentence takeaway, not the radio line", () => {
  for (const k of Object.keys(CALLBACKS)) {
    const t = callbackTakeaway(k), first = CALLBACKS[k].text.split(/(?<=[.!?])\s/)[0];
    assert.ok(t && t !== first, k);
    assert.ok(t.split(/\s+/).length >= 8 && t.split(/\s+/).length <= 20, `${k}: ${t}`);
    assert.match(t, /^[A-Z].*\.$/);
    assert.equal((t.match(/[.!?](\s|$)/g) || []).length, 1, `${k}: one sentence`);
  }
  assert.doesNotMatch(callbackTakeaway("low_power"), /^Battery's low\.$/);
  assert.equal(callbackTakeaway("nope"), null);
});

test("QA-66: coming back to a running mission takes the server's state first; a finished one opens its debrief", () => {
  const ui = src("mission/ui.js"), at = ui.indexOf("async function enter()"), body = ui.slice(at, ui.indexOf("hub();", at));
  assert.match(body, /await freshState\(state\.id\)/);
  assert.ok(body.indexOf("showDebrief()") > body.indexOf("freshState") && body.indexOf("showDebrief()") < body.indexOf("showHud()"));
});
