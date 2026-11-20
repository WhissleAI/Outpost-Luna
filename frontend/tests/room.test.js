// Room state (src/room.js): the automatic calm / busy / loud estimator and its hysteresis (docs/HANDSFREE.md).
import test from "node:test";
import assert from "node:assert/strict";
import { createRoom, effectiveFilter, ROOM_LINES, ROOM_TUNING } from "../src/room.js";
import { runAll } from "../tools/room_harness.mjs";

function clocked(tuning) {
  let t = 0;
  const changes = [];
  const room = createRoom({ now: () => t, tuning, onChange: (s, p) => changes.push({ t, from: p.state, to: s.state, mode: s.mode }) });
  const run = (sec, rms, o) => { const end = t + sec * 1000; for (; t < end; t += 80) room.frame(typeof rms === "function" ? rms(t) : rms, o); };
  const at = ms => { t = ms; };
  return { room, run, changes, get t() { return t; }, at, advance: ms => { t += ms; room.tick(); } };
}

test("a quiet room stays calm and open, with no line", () => {
  const c = clocked();
  c.run(120, 0.0012);
  assert.equal(c.room.state, "calm"); assert.equal(c.room.mode, "open"); assert.equal(c.changes.length, 0);
  assert.equal(c.room.snapshot().line, "");
});

test("a raised floor enters busy only after it holds, and leaves only below the lower exit level", () => {
  const c = clocked();
  c.run(3, 0.0012);
  c.run(2, 0.02);                                   // too short to hold
  assert.equal(c.room.state, "calm");
  c.run(15, 0.02);
  assert.equal(c.room.state, "busy");
  assert.equal(c.room.mode, "open", "busy from the floor alone: stricter filter, nothing shown");
  c.run(30, 0.012);                                 // between the exit (0.009) and enter (0.016) levels: stays busy
  assert.equal(c.room.state, "busy");
  c.run(30, 0.004);
  assert.equal(c.room.state, "calm");
});

test("busy holds at least its dwell even when the room goes quiet at once", () => {
  const c = clocked({ DWELL: { busy: 20000 } });
  c.run(12, 0.02);
  const enteredAt = c.changes.find(x => x.to === "busy").t;
  c.run(40, 0.0012);
  const left = c.changes.find(x => x.from === "busy" && x.to === "calm");
  assert.ok(left && left.t - enteredAt >= 20000);
});

test("our own audio is not the room: frames while we play never raise the floor", () => {
  const c = clocked();
  c.run(60, 0.06, { playing: true });
  c.run(5, 0.0012);
  assert.equal(c.room.state, "calm");
});

test("a short loud burst (a cheer, a slam) never switches", () => {
  const c = clocked();
  c.run(20, 0.0012); c.run(1.5, 0.3); c.run(30, 0.0012);
  assert.equal(c.changes.length, 0);
});

test("chatter turns make the room busy, and enough of them ask for hold to talk", () => {
  const c = clocked();
  c.run(5, 0.0012);
  for (let i = 0; i < 3; i++) { c.room.turn({ text: "chat " + i, outcome: "ignore", reason: "not_directed", dd: 0.2 }); c.run(3, 0.0012); }
  assert.equal(c.room.state, "busy"); assert.equal(c.room.mode, "open");
  c.room.turn({ text: "chat 4", outcome: "ignore", reason: "crew_talk", dd: 0.6 });
  assert.equal(c.room.mode, "hold");
  assert.equal(c.room.snapshot().line, ROOM_LINES.hold);
  assert.equal(c.room.snapshot().holdToTalk, true);
});

test("a kid's own directed turns are not chatter; one stray remark is not a busy room", () => {
  const c = clocked();
  c.run(5, 0.0012);
  for (let i = 0; i < 6; i++) { c.room.turn({ text: "go to the map " + i, outcome: "navigate", dd: 0.9 }); c.run(4, 0.0012); }
  c.room.turn({ text: "dinner is ready", outcome: "ignore", reason: "not_directed", dd: 0.2 });
  c.run(5, 0.0012);
  assert.equal(c.room.state, "calm");
});

test("explicit turns (Space, typed) never count as room talk", () => {
  const c = clocked();
  for (let i = 0; i < 6; i++) c.room.turn({ text: "x" + i, outcome: "ignore", reason: "not_directed", dd: 0.1, ptt: true });
  for (let i = 0; i < 6; i++) c.room.turn({ text: "y" + i, outcome: "ignore", typed: true });
  assert.equal(c.room.state, "calm");
});

test("voice that keeps failing offers typing, then switches to typing", () => {
  const c = clocked();
  c.run(5, 0.0012);
  for (let i = 0; i < 3; i++) { c.room.turn({ text: "fail " + i, outcome: "ignore", notice: true, dd: 0.8 }); c.run(4, 0.0012); }
  assert.equal(c.room.state, "loud"); assert.equal(c.room.mode, "offer");
  assert.equal(c.room.snapshot().line, ROOM_LINES.offer);
  c.room.turn({ text: "fail again", outcome: "ignore", notice: true, dd: 0.8 });
  assert.equal(c.room.mode, "type"); assert.equal(c.room.snapshot().typing, true);
});

test("the offer becomes typing after OFFER_MS of a loud room", () => {
  const c = clocked();
  c.run(10, 0.08);
  assert.equal(c.room.mode, "offer");
  c.run(ROOM_TUNING.OFFER_MS / 1000 + 1, 0.08);
  assert.equal(c.room.mode, "type");
});

test("a repeated turn after an ignore and very low confidence are failures", () => {
  const c = clocked();
  c.room.turn({ text: "show me the rover", outcome: "ignore", reason: "too_short", dd: 0.8 });
  c.room.turn({ text: "Show me the rover!", outcome: "ignore", reason: "too_short", dd: 0.8 });
  c.room.turn({ text: "show me the rover", outcome: "ignore", reason: "too_short", dd: 0.8 });
  assert.equal(c.room.state, "calm");
  c.room.turn({ text: "zzz", outcome: "answer", dd: 0.8, uconf: 0.2 });
  assert.equal(c.room.state, "loud");
});

test("held barge-ins for room talk count as chatter; echo and low energy do not", () => {
  const c = clocked();
  ["echo", "low_energy", "filler", "echo"].forEach(r => c.room.held(r));
  assert.equal(c.room.state, "calm");
  ["not_directed", "not_rated", "not_directed"].forEach(r => c.room.held(r));
  assert.equal(c.room.state, "busy");
});

test("calm again returns to open voice silently, from hold and from typing", () => {
  const c = clocked();
  c.run(10, 0.08); c.run(25, 0.08);
  assert.equal(c.room.mode, "type");
  c.run(60, 0.0012);
  assert.equal(c.room.state, "calm"); assert.equal(c.room.mode, "open"); assert.equal(c.room.snapshot().line, "");
});

test("coming down from loud to a still-busy room keeps hold to talk", () => {
  const c = clocked();
  c.run(10, 0.08);
  assert.equal(c.room.state, "loud");
  c.run(40, 0.02);
  assert.equal(c.room.state, "busy"); assert.equal(c.room.mode, "hold");
});

test("effectiveFilter: one level stricter in a busy or loud room, never looser than the kid's choice", () => {
  assert.equal(effectiveFilter("relaxed", "calm"), "relaxed");
  assert.equal(effectiveFilter("relaxed", "busy"), "normal");
  assert.equal(effectiveFilter("normal", "busy"), "strict");
  assert.equal(effectiveFilter("strict", "loud"), "strict");
  assert.equal(effectiveFilter("bogus", "calm"), "normal");
});

test("force pins a state for screenshots and tests; force(null) goes back to automatic", () => {
  const c = clocked();
  c.room.force("busy");
  assert.equal(c.room.state, "busy"); assert.equal(c.room.mode, "hold");
  c.room.force("loud", "type");
  assert.equal(c.room.mode, "type");
  c.room.force(null);
  c.run(30, 0.0012);
  assert.equal(c.room.state, "calm"); assert.equal(c.room.mode, "open");
});

test("voice bar lines stay inside the copy budget (12 words or fewer, no emoji)", () => {
  Object.values(ROOM_LINES).filter(Boolean).forEach(l => {
    assert.ok(l.split(/\s+/).length <= 12, l);
    assert.ok(!/[\u{1F300}-\u{1FAFF}]/u.test(l), l);
  });
});

test("harness: every synthetic / recorded scenario meets its expectation, no flapping, calm rooms never switch", () => {
  const rows = runAll();
  for (const r of rows) assert.deepEqual(r.problems, [], r.name);
  rows.filter(r => r.name.startsWith("quiet")).forEach(r => assert.equal(r.switches, 0, r.name));
  rows.forEach(r => assert.equal(r.flaps, 0, r.name));
});
