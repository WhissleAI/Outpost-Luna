// Trimmed desktop crew audio (backend/pipeline/trim_media.py): clip time <-> <audio> file time (src/cliptime.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { toClipTime, toFileTime } from "../src/cliptime.js";

const SEGS = [[2, 0, 10], [30, 10, 5], [100, 15, 20]];   // clip 2-12 -> file 0-10, 30-35 -> 10-15, 100-120 -> 15-35

test("no segs (the dev app's original audio): both times are the same", () => {
  assert.equal(toFileTime(undefined, 12.5), 12.5);
  assert.equal(toClipTime(null, 12.5), 12.5);
  assert.equal(toFileTime([], 3), 3);
});

test("inside a kept stretch the mapping is a shift and round-trips", () => {
  for (const t of [2, 7.25, 11.99, 30, 34.9, 100, 119.5]) {
    const f = toFileTime(SEGS, t);
    assert.ok(Math.abs(toClipTime(SEGS, f) - t) < 1e-9, `${t} -> ${f}`);
  }
  assert.equal(toFileTime(SEGS, 31), 11);
  assert.equal(toClipTime(SEGS, 20), 105);
});

test("outside the kept stretches: clamp to the nearest playable audio", () => {
  assert.equal(toFileTime(SEGS, 0.5), 0);      // before the first stretch
  assert.equal(toFileTime(SEGS, 20), 10);      // a dropped gap: the next stretch's start
  assert.equal(toFileTime(SEGS, 500), 35);     // past the end
});
