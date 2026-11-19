// [ipad] A shell with no local ear (the iPad app, docs/IPAD.md) sets window.__lunaEngineBoot = {ear: "none"} before the
// page loads: the voice bar is "Voice off · type" from the first frame, nothing says "Starting voice…", and the ear's
// WebSocket is never opened. (Own file: engine.js reads the boot state once, at import.)
import { test } from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis;
globalThis.__lunaEngineBoot = { ear: "none" };
const E = await import("../src/engine.js");

test("boot state 'none': no ear, the bar's 'voice off' class, the typing hint", () => {
  assert.equal(E.engineState().ear, "none");
  assert.equal(E.noEar(), true);
  assert.deepEqual(E.askbarClasses(), { "is-ear-restarting": false, "is-ear-down": true });
  assert.equal(E.earNote(), E.NO_EAR_NOTE);
  assert.ok(E.NO_EAR_NOTE.split(/\s+/).length <= 12, "docs/COPY.md: 12 words or fewer");
});

test("boot state 'none': never warming, never the restart fix line, whatever /api/health says", () => {
  const unreachable = { model_server: { ok: false, error: "model server unreachable" }, voice: { ear: "arc" } };
  assert.equal(E.warmState(unreachable, 0), "ready");
  assert.equal(E.warmState(unreachable, 10 * 60 * 1000), "ready");
});

test("the other states are unchanged by the new one", () => {
  const ok = { ear: "ok", backend: "ok" };
  assert.equal(E.noEar(ok), false);
  assert.deepEqual(E.askbarClasses({ ear: "down" }), { "is-ear-restarting": false, "is-ear-down": true });
  assert.equal(E.earNote({ ear: "down" }), "Voice is off. Type to ask.");
  assert.equal(E.warmState({ model_server: { ok: false } }, 0, ok), "warming");
});
