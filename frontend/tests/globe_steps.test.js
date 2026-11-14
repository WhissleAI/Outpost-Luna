// Flight School globe steps (src/academy/globe_steps.js): every new step type registers, runs its globe directive,
// and sends the input shape the server grades (docs/LEARNING_DESIGN.md §9.2).
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const m = await import("../src/academy/globe_steps.js");
const R = window.__outpost.stepRenderers;

function fakeGlobe(calls) {
  return { flyTo: (...a) => calls.push(["fly", ...a]), poleView: (...a) => calls.push(["pole", ...a]),
    setSunDir: (...a) => calls.push(["sun", ...a]), centerLatLon: () => ({ lat: 0, lon: 170 }) };
}
const ctx = (type, acc, g, sent, calls) => ({ step: { globe: g }, acc: { type, ...acc }, answer: x => sent.push(x),
  globe: fakeGlobe(calls) });

test("every globe step type is registered", () => {
  for (const t of m.GLOBE_STEP_TYPES) assert.equal(typeof R[t], "function", t);
});

test("route sends the taps once every stop is tapped", () => {
  const sent = [], calls = [];
  const r = R.route(ctx("route", { stops: ["orientale", "ohm"] }, { do: "route" }, sent, calls));
  r.bind({ querySelector: () => null });
  r.onTap({ lat: 1, lon: 2 });
  assert.equal(sent.length, 0);
  r.onTap({ lat: 3, lon: 4 });
  assert.deepEqual(sent, [{ taps: [{ lat: 1, lon: 2 }, { lat: 3, lon: 4 }] }]);
  assert.deepEqual(calls[0], ["pole", "south", 2.4]);
});

test("terminator lights the Moon from the step's Sun and grades a tap", () => {
  const sent = [], calls = [];
  const r = R.terminator(ctx("terminator", { sun_lon: 90 }, { do: "sun", sun_lon: 90 }, sent, calls));
  r.bind({});
  r.onTap({ lat: 0, lon: 1 });
  assert.deepEqual(sent, [{ tap: { lat: 0, lon: 1 } }]);
  assert.ok(calls.some(c => c[0] === "sun" && c[2] === 90));
});

test("options are numbered buttons with no answer key", () => {
  const html = m.optionsHtml([{ id: "a", label: "Yes" }, { id: "b", label: "No" }]);
  assert.match(html, /data-c="a".*>1<.*Yes/s);
  assert.doesNotMatch(html, /answer/);
});
