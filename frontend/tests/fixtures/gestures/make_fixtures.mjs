// Writes the gesture landmark fixtures (JSON, the same shape a recording has) from synth.mjs.
//   node tests/fixtures/gestures/make_fixtures.mjs
// A real recording can sit next to them: {name, expect, note?, frames: [{t, aspect, hands, faces}]}. The unit tests run
// every *.json here; the Playwright test injects them into the running app.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { sequences } from "./synth.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const KEEP = ["palm_hold", "thumbs_up", "thumbs_down", "swipe_left", "swipe_right", "swipe_left_return", "point_dwell", "grab_drag",
  "lean_in_back", "brief_palm", "moving_palm", "background_person", "slow_drift",
  "fist_spin_left", "fist_spin_right", "fist_spin_up", "fist_spin_down", "fist_spin_up_left", "fist_spin_up_right", "fist_spin_down_left", "fist_spin_down_right",
  ...["left", "right", "up", "down", "up_left", "up_right", "down_left", "down_right"].map(d => "fist_spin_roll_" + d),
  "pinch_slide_up", "pinch_slide_down", "pinch_hold"];
const r4 = v => Math.round(v * 1e4) / 1e4;
const all = sequences();
for (const name of KEEP) {
  const s = all[name];
  const frames = s.frames.map(f => ({
    t: f.t, aspect: +f.aspect.toFixed(4),
    hands: f.hands.map(h => ({ side: h.side, score: h.score, lm: h.lm.map(p => p.map(r4)) })),
    faces: f.faces.map(fc => ({ score: fc.score, box: Object.fromEntries(Object.entries(fc.box).map(([k, v]) => [k, r4(v)])), kp: fc.kp.map(p => p.map(r4)) })),
  }));
  fs.writeFileSync(path.join(HERE, name + ".json"), JSON.stringify({ name, source: "synthetic (synth.mjs)", expect: s.expect, note: s.note || "", ...(s.dir ? { dir: s.dir } : {}), frames }) + "\n");
}
console.log(`wrote ${KEEP.length} fixtures to ${HERE}`);
