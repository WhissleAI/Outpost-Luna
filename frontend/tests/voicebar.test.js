// The floating voice bar's command parser (frontend/src/voicebar.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseBarCommand, ANCHORS } from "../src/voicebar.js";

test("voice bar: move commands map to one of six anchors", () => {
  assert.deepEqual(parseBarCommand("move the voice bar to the top"), { cmd: "move", anchor: "tc" });
  assert.deepEqual(parseBarCommand("Move the voice bar to the top right."), { cmd: "move", anchor: "tr" });
  assert.deepEqual(parseBarCommand("move the voice bar to the bottom left"), { cmd: "move", anchor: "bl" });
  assert.deepEqual(parseBarCommand("put the voice bar on the left".replace(" on", " to")), { cmd: "move", anchor: "bl" });
  assert.deepEqual(parseBarCommand("move the voice bar to the right", "tc"), { cmd: "move", anchor: "tr" });   // keeps its row
  assert.deepEqual(parseBarCommand("move the voicebar up"), { cmd: "move", anchor: "tc" });
  for (const a of ["tl", "tc", "tr", "bl", "bc", "br"]) assert.ok(ANCHORS.includes(a));
});

test("voice bar: reset, and nothing else is a bar command", () => {
  assert.deepEqual(parseBarCommand("reset the voice bar"), { cmd: "reset" });
  assert.deepEqual(parseBarCommand("reset voice bar position"), { cmd: "reset" });
  for (const t of ["move the rover to the top", "shields to 40", "top", "what is a voice", ""]) assert.equal(parseBarCommand(t), null, t);
});
