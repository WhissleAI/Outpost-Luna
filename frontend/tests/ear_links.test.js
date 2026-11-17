// The ear's linked names in the kid's words (highlight.js linkSegments / LINK_SURE_P; docs/SPEECH_SIGNALS_AUDIT.md).
import test from "node:test";
import assert from "node:assert/strict";
import { linkSegments, LINK_SURE_P } from "../src/highlight.js";

test("a sure link is marked, the rest is plain text", () => {
  const s = linkSegments("Fly to Sea of Rains now", [{ entity: "Sea of Rains", state: "linked", p: 1.0 }]);
  assert.deepEqual(s, [{ text: "Fly to " }, { text: "Sea of Rains", link: { entity: "Sea of Rains", sure: true } }, { text: " now" }]);
});

test("a low-p link is marked unsure (the director asks); abstain / not_in_list are never marked", () => {
  const s = linkSegments("How big is Orion", [{ entity: "Orion", state: "linked", p: 0.9 },
    { entity: null, heard: "big", state: "not_in_list", p: 1 }, { entity: "Tycho", state: "abstain", p: 0.5 }]);
  assert.equal(s.length, 2);
  assert.deepEqual(s[1].link, { entity: "Orion", sure: false });
  assert.ok(LINK_SURE_P > 0.9);
});

test("no names, or an entity not spelled in the text: one plain segment", () => {
  assert.deepEqual(linkSegments("hello there", []), [{ text: "hello there" }]);
  assert.deepEqual(linkSegments("hello there", [{ entity: "Tycho", state: "linked", p: 1 }]), [{ text: "hello there" }]);
  assert.deepEqual(linkSegments("", null), []);
});

test("whole words only, longest entity first", () => {
  const s = linkSegments("Apollo 11 Lunar Module Eagle landed", [{ entity: "Eagle", state: "linked", p: 1 },
    { entity: "Apollo 11 Lunar Module Eagle", state: "linked", p: 1 }]);
  assert.equal(s[0].link.entity, "Apollo 11 Lunar Module Eagle");
});
