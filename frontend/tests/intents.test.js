// The input bus (src/input/intents.js): priority, consumption, wildcard, async handlers, the intent-only log.
import test from "node:test";
import assert from "node:assert/strict";
import { createIntentBus, INTENTS, CONTINUOUS } from "../src/input/intents.js";
import { ROUTER_INTENTS } from "../src/input/defaults.js";

test("a screen handler (priority 10) beats the shell default (0); returning true consumes", async () => {
  const bus = createIntentBus(), got = [];
  bus.onIntent("next", () => { got.push("shell"); return true; });
  bus.onIntent("next", () => { got.push("screen"); return true; }, { priority: 10 });
  assert.equal(await bus.emitIntent("next", {}, "gesture"), true);
  assert.deepEqual(got, ["screen"]);
});

test("false passes the intent on; the wildcard sees everything; unsubscribe works", async () => {
  const bus = createIntentBus(), got = [];
  const off = bus.onIntent("next", () => { got.push("screen-pass"); return false; }, { priority: 10 });
  bus.onIntent("*", (a, ev) => { got.push("wild:" + ev.name + ":" + ev.source); return true; }, { priority: -10 });
  assert.equal(await bus.emitIntent("next", { arg: 1 }, "voice"), true);
  off();
  await bus.emitIntent("next", {}, "keyboard");
  assert.deepEqual(got, ["screen-pass", "wild:next:voice", "wild:next:keyboard"]);
});

test("async handlers: a promise of true consumes, of false falls through", async () => {
  const bus = createIntentBus(), got = [];
  bus.onIntent("yes", async () => { got.push("a"); return false; }, { priority: 5 });
  bus.onIntent("yes", async () => { got.push("b"); return true; }, { priority: 1 });
  bus.onIntent("yes", () => { got.push("c"); return true; });
  assert.equal(await bus.emitIntent("yes", {}, "gesture"), true);
  assert.deepEqual(got, ["a", "b"]);
});

test("no handler → false; a throwing handler is skipped, not fatal", async () => {
  const bus = createIntentBus();
  assert.equal(await bus.emitIntent("prev", {}, "gesture"), false);
  const err = console.error; console.error = () => {};
  bus.onIntent("stop", () => { throw new Error("boom"); }, { priority: 5 });
  bus.onIntent("stop", () => true);
  assert.equal(await bus.emitIntent("stop", {}, "gesture"), true);
  console.error = err;
});

test("the log keeps discrete intents only (no frame-rate ones), capped", async () => {
  const bus = createIntentBus({ logSize: 3 });
  await bus.emitIntent("point", { x: 1, y: 2 }, "gesture");
  for (const n of ["stop", "yes", "next", "prev"]) await bus.emitIntent(n, {}, "gesture");
  const log = bus.recent();
  assert.deepEqual(log.map(e => e.name), ["yes", "next", "prev"]);
  assert.ok(log.every(e => e.source === "gesture" && typeof e.t === "number"));
  assert.ok(!JSON.stringify(log).includes("lm"), "no landmarks in the log");
});

test("the vocabulary covers the router's nav intents and the gesture intents", () => {
  for (const n of ["next", "back", "accept_offer", "decline_offer", "panel_back", "panel_comm", "view_orbit", "a11y"]) assert.ok(n in INTENTS, n);
  for (const n of ["stop", "yes", "no", "prev", "point", "select", "rotate", "look", "panel_open", "zoom", "call_houston"]) assert.ok(n in INTENTS, n);
  for (const n of CONTINUOUS) assert.ok(n in INTENTS, n);
  for (const n of ["stop", "yes", "no", "prev", "select", "point"]) assert.ok(!ROUTER_INTENTS.has(n), `${n} is not a shell nav intent`);
});
