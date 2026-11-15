// The narration rule (src/narration.js, mirrors backend/app/narration.py): the voice says "millisieverts" where the
// screen shows "mSv". backend/tests/test_narration.py checks this file carries the same cases.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spokenForm } from "../src/narration.js";

const CASES = [
  ["Doctors count radiation in mSv. So what is an mSv?", "Doctors count radiation in millisieverts. So what is a millisievert?"],
  ["Correct. One mSv is about 10 chest x-rays.", "Correct. One millisievert is about 10 chest x-rays."],
  ["Radiation high: 0.42 mSv an hour.", "Radiation high: 0.42 millisieverts an hour."],
  ["Dose rate 0.12 mSv/h.", "Dose rate 0.12 millisieverts an hour."],
  ["Crew dose: 14.2 of 50 mSv.", "Crew dose: 14.2 of 50 millisieverts."],
  ["Your crew took 12.0 game-mSv.", "Your crew took 12.0 game millisieverts."],
  ["An mSv measures radiation dose.", "A millisievert measures radiation dose."],
  ["No units here.", "No units here."],
];

test("narration: the spoken form of a line (screen text unchanged)", () => {
  for (const [shown, said] of CASES) assert.equal(spokenForm(shown), said);
});
