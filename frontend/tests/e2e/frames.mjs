// Synthetic landmark frames for the e2e tests (Python can't import the JS synth): prints JSON frames to stdout.
//   node tests/e2e/frames.mjs hold <pose> <ms> [cx cy]       a pose held still (light jitter)
//   node tests/e2e/frames.mjs point <u> <v> <ms>              an index held so the cursor sits at screen (u, v) in 0..1
import { hand, seq } from "../fixtures/gestures/synth.mjs";
import { DEFAULTS } from "../../src/gesture/tuning.js";

let s = 11; const rand = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
const [cmd, ...a] = process.argv.slice(2);
let frames = [];
if (cmd === "hold") {
  const [pose, ms, cx = 0.5, cy = 0.7] = [a[0], +a[1], +(a[2] ?? 0.5), +(a[3] ?? 0.7)];
  frames = seq(ms, () => ({ hands: [hand(pose, { cx, cy, noise: 0.002, rand })] }));
} else if (cmd === "point") {
  const [u, v, ms] = a.map(Number), [x0, y0, x1, y1] = DEFAULTS.pointBox;
  const ref = hand("point", { cx: 0.5, cy: 0.7 }).lm[8];
  const tx = x0 + u * (x1 - x0), ty = y0 + v * (y1 - y0);
  const cx = 0.5 + (tx - ref[0]), cy = 0.7 + (ty - ref[1]);
  frames = seq(ms, () => ({ hands: [hand("point", { cx, cy, noise: 0.0008, rand })] }));
}
process.stdout.write(JSON.stringify(frames));
