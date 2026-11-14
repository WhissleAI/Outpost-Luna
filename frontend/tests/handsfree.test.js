// Hands-free: the client side of the echo / filler gate (mirrors backend/app/turn_router.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { isFiller, normWords, shouldBargeIn, takesOffer, turnIsEcho } from "../src/floor.js";

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

// Mirrors backend/tests/test_handsfree_loop.py test_the_offers_answer_right_after_its_echo_navigates: our offer plays,
// the mic hears it back (echo), then the kid's reply arrives right after the line ended, inside the echo tail (`refs`
// still holds the line, nothing is on air). The reply is the kid; the same word while a line is on air is its echo.
test("turnIsEcho: the kid's answer to an offer right after its echo is not an echo", () => {
  const cases = [
    [{ screen: "patch", offer: "next_lesson" }, "Ready for the next lesson?", ["next", "yes", "next lesson", "okay next"]],
    [{ screen: "patch", offer: "next_lesson" }, "Next up: Lessons from Apollo. Say next when you're ready.", ["next"]],
    [{ screen: "patch", offer: "mission" }, "Ready to take command?", ["take command", "yes"]],
    [{ screen: "brief", offer: "take_command" }, "Malapert. Good choice. Say take command when you're ready.", ["take command"]],
    [{ screen: "debrief", offer: "fly_again" }, "Mission paused. Fly again?", ["fly again", "yeah"]],
  ];
  for (const [frame, line, words] of cases) {
    const refs = [line];
    assert.equal(turnIsEcho({ text: line, frame, onAir: true, refs }), true, `echo of ${line}`);
    for (const w of words) {
      assert.equal(turnIsEcho({ text: w, frame, onAir: false, refs }), false, `${w} after ${line}`);
      if (normWords(w).every(x => normWords(line).includes(x))) {
        assert.equal(turnIsEcho({ text: w, frame, onAir: true, refs }), true, `${w} while ${line} is on air`);
      }
    }
  }
});

test("turnIsEcho: a step answer the prompt itself says, right after the prompt's echo, is the kid", () => {
  const frame = { screen: "lesson", step_type: "choice", step_options: ["I heard you", "Write it down", "Say it again"] };
  const refs = ['Radio is noisy, so crews keep it short. Copy means I heard you. What does "copy" mean on the radio?'];
  assert.equal(turnIsEcho({ text: refs[0], frame, onAir: true, refs }), true);
  assert.equal(turnIsEcho({ text: "I heard you", frame, onAir: true, refs }), true);
  assert.equal(turnIsEcho({ text: "I heard you", frame, onAir: false, refs }), false);
  const ride = { screen: "ride", step_type: "tap" };
  const p = ["Solar panels need sunlight. Tap the line where day meets night."];
  assert.equal(turnIsEcho({ text: "the terminator, where day meets night", frame: ride, onAir: false, refs: p }), false);
});

test("turnIsEcho: everything else keeps the old echo rules (tail and older lines)", () => {
  const refs = ["Copy, commander. Shields now get 40 percent of the power."];
  // no offer pending, or a word that does not take it: the tail still counts
  assert.equal(turnIsEcho({ text: "shields now get 40 percent", frame: { screen: "cabin" }, onAir: false, refs }), true);
  assert.equal(turnIsEcho({ text: "next", frame: { screen: "map" }, onAir: false, refs: ["Say next when you're ready."] }), true);
  assert.equal(turnIsEcho({ text: "no", frame: { screen: "patch", offer: "next_lesson" }, onAir: false, refs: ["No rush. Ready?"] }), true);
  // an older line: near-verbatim repeats only
  const old = ["I don't know that one yet. Try: show me the giant bullseye."];
  assert.equal(turnIsEcho({ text: "show me the giant bullseye", frame: { screen: "library" }, onAir: false, refs: [], oldRefs: old }), true);
  assert.equal(turnIsEcho({ text: "show me the moon", frame: { screen: "library" }, onAir: false, refs: [], oldRefs: old }), false);
});

test("takesOffer: yes / next / start take any offer; the rest only their own", () => {
  assert.equal(takesOffer("Yes!", "next_lesson"), true);
  assert.equal(takesOffer("let's go", "fly_again"), true);
  assert.equal(takesOffer("take command", "take_command"), true);
  assert.equal(takesOffer("take command", "fly_again"), false);
  assert.equal(takesOffer("fly again", "fly_again"), true);
  assert.equal(takesOffer("no thanks", "next_lesson"), false);
  assert.equal(takesOffer("next", null), false);
});
