// [campaign] Missions 2+ on the hub (src/mission/campaign.js, docs/GAMEPLAY.md §16): unlocked in order, the next one up,
// goals on the progress strip, the debrief checklist, the briefing cards.
import test from "node:test";
import assert from "node:assert/strict";

const CM = await import("../src/mission/campaign.js");
const { CAMPAIGN } = await import("../src/story.js");
const words = s => String(s).trim().split(/\s+/).filter(Boolean).length;
const mem = () => { const m = new Map(); return { getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) }; };
const LIST = [1, 2, 3, 4, 5, 6].map(n => ({ n, id: `m${n}`, title: `T${n}`, site: n > 1 ? `s${n}` : null, line: "x", danger: "d", goals: ["A", "B"] }));

test("missions open in order: Mission 1, then one more per win, never skipping", () => {
  assert.equal(CM.unlockedCount(LIST, []), 1);
  assert.equal(CM.unlockedCount(LIST, ["m1"]), 2);
  assert.equal(CM.unlockedCount(LIST, ["m1", "m3"]), 2, "a win out of order opens nothing past the gap");
  assert.equal(CM.unlockedCount(LIST, ["m1", "m2", "m3", "m4", "m5", "m6"]), 6);
  assert.equal(CM.unlockedCount(CM.FALLBACK, []), 1);
});

test("the hub offers the next mission up; after the last, the last", () => {
  assert.equal(CM.nextUp(LIST, []).id, "m1");
  assert.equal(CM.nextUp(LIST, ["m1"]).id, "m2");
  assert.equal(CM.nextUp(LIST, ["m1", "m2", "m3", "m4", "m5", "m6"]).id, "m6");
});

test("wins are kept per call sign, once each", () => {
  const s = mem();
  assert.deepEqual(CM.markWon("m1", "Nova", s), ["m1"]);
  assert.deepEqual(CM.markWon("m1", "Nova", s), ["m1"]);
  assert.deepEqual(CM.wonIds("Comet", s), []);
  assert.deepEqual(CM.wonIds("Nova", { getItem: () => "{bad" }), []);
});

test("goals on the progress strip: counts as n/goal, keep goals as OK / Missed", () => {
  assert.deepEqual(CM.goalBit({ id: "relay_calls", label: "Call Houston 3 times", short: "Houston calls", goal: 3, got: 2, met: false, kind: "count" }),
    { name: "Houston calls", val: 2, of: 3, p: 2 / 3, met: false, title: "Call Houston 3 times: 2 of 3" });
  const k = CM.goalBit({ id: "warm", label: "Never let the battery run empty", short: "Battery never empty", goal: 0, got: 0, met: true, kind: "keep" });
  assert.equal(k.val, CAMPAIGN.keepOk); assert.equal(k.p, 1); assert.equal(k.of, "");
  assert.equal(CM.goalBit({ kind: "keep", met: false, short: "x", label: "y" }).val, CAMPAIGN.keepMissed);
});

test("debrief checklist and briefing cards come from the mission", () => {
  assert.deepEqual(CM.goalChecks([{ label: "Rover home by day 3", met: true }, { label: "Bring ice home", met: false }]),
    [{ ok: true, text: "Rover home by day 3" }, { ok: false, text: "Bring ice home" }]);
  const cards = CM.briefCards({ goals: ["Rover home by day 3", "Bring ice home"], danger: "No rover until you rescue it." });
  assert.deepEqual(cards.map(c => c.k), ["goal", "danger", "bonus"]);
  assert.equal(cards[0].text, "Rover home by day 3");
  assert.equal(CM.isCampaign({ n: 1 }), false); assert.equal(CM.isCampaign({ n: 2 }), true);
});

test("campaign copy keeps the budgets", () => {
  assert.ok(words(CAMPAIGN.say("Sky Otter", 4, "Rover rescue", "de Gerlache Crater Rim")) <= 20);
  assert.ok(words(CAMPAIGN.locked(6)) <= 12);
  assert.ok(words(CAMPAIGN.unlocked(3, "Storm season")) <= 12);
  for (const k of ["goalsBoth", "goalsOne", "goalsNone"]) assert.ok(words(CAMPAIGN[k]) <= 12);
});

test("debrief: a campaign mission's checklist is the crew and its two goals; Mission 1 keeps ice and science", async () => {
  const { debriefStory } = await import("../src/mission/objective.js");
  const goals = [{ id: "rescue", label: "Rover home by day 3", met: true }, { id: "ice", label: "Bring ice home", met: false }];
  const st = { site: { name: "de Gerlache Crater Rim" }, mission_time_h: 240, resources: { dose_limit_msv: 50, dose_msv: 12 } };
  const d = { outcome: "survived", campaign: { n: 4 }, objectives: { goals, science: { met: false }, ice: { met: false } }, try: "Send the rover for ice when no storm is due.", timeline: [] };
  const s = debriefStory(d, st);
  assert.deepEqual(s.checks.map(c => [c.ok, c.text]).slice(1), [[true, "Rover home by day 3"], [false, "Bring ice home"]]);
  assert.equal(s.beats[2], CAMPAIGN.goalsOne);
  const m1 = debriefStory({ ...d, campaign: { n: 1 } }, st);
  assert.equal(m1.checks.length, 3);
  assert.notEqual(m1.checks[1].text, "Rover home by day 3");
});
