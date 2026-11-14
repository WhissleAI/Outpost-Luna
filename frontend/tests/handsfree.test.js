// Hands-free: the client side of the echo / filler gate (mirrors backend/app/turn_router.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { isFiller, shouldBargeIn } from "../src/floor.js";

test("isFiller: hums, fillers and non-lexical turns", () => {
  for (const t of ["Oh.", "Mm-mm.", "um", "hmm", "Uh-huh.", "Mm.", "Ah!", "uh, um", "ooh", ""]) assert.equal(isFiller(t), true, t);
  for (const t of ["next", "yes", "no", "stop", "go back", "shields to 40"]) assert.equal(isFiller(t), false, t);
});

test("shouldBargeIn: filler never barges in; two words only for a control word or a clearly directed turn", () => {
  const refs = ["The storm is over. All clear, Commander!"];
  assert.equal(shouldBargeIn({ started: true, text: "mm mm", refs }), false);
  assert.equal(shouldBargeIn({ started: true, text: "oh wow", refs }), false);
  assert.equal(shouldBargeIn({ started: true, text: "go back", refs }), true);
  assert.equal(shouldBargeIn({ started: true, text: "the rover", refs }), false);
  assert.equal(shouldBargeIn({ started: true, text: "the rover", refs, dd: 0.9 }), true);
  assert.equal(shouldBargeIn({ started: true, text: "all clear commander", refs }), false);   // echo
});
