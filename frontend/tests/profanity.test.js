// [P0] Kid text shown anywhere (voice bar, captions, transcript, the card's "you asked") is masked offline.
import { test } from "node:test";
import assert from "node:assert/strict";
import { maskProfanity, hasProfanity, isProfane, maskAll } from "../src/profanity.js";

test("the owner's room: 'Shit. Shit.' is masked, first letter kept", () => {
  assert.equal(maskProfanity("Shit. Shit."), "S***. S***.");
  assert.equal(maskProfanity("shit shit oh"), "s*** s*** oh");
});

test("stems inside words and common forms are caught", () => {
  for (const w of ["fuck", "fucking", "motherfucker", "bullshit", "dipshit", "bitches", "asshole", "damn", "wtf", "Pissed"]) assert.ok(isProfane(w), w);
  assert.equal(maskProfanity("what the fuck is that"), "what the f*** is that");
});

test("Moon and cockpit words are left alone (Hell is a real crater; cockpit, class, pass, Uranus...)", () => {
  for (const t of ["Hell crater", "the cockpit", "class", "pass the shields", "assess", "Scunthorpe", "Shackleton", "Dickens"]) {
    assert.equal(maskProfanity(t), t, t);
    assert.equal(hasProfanity(t), false, t);
  }
});

test("maskAll hides every word of a flagged turn; empty input is safe", () => {
  assert.equal(maskAll("you are stupid"), "y*** a*** s***");
  assert.equal(maskProfanity(""), "");
  assert.equal(maskProfanity(null), "");
});
