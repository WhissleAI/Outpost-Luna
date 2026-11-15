// NASA Moon Learning & Media Plan v1 (frontend): the video shim never blocks, the debrief's Learn more mapping, the
// Mission prep / video / Moon Base copy budgets, and story.js kept in sync with the course (tracks, blurbs, lesson
// numbers). The backend twin is backend/tests/test_learning_v1.py.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as S from "../src/story.js";
import { videoState, playVideo, playable, _setVideoModule } from "../src/video_shim.js";
import { pickLearnMore, LEARN_MORE_OUTCOMES } from "../src/learn_more.js";
import { missionsFlown, markMissionFlown, unlocked, newlyUnlocked, coreLessons, isExplorer } from "../src/explorer.js";

const COURSE = JSON.parse(readFileSync(new URL("../../backend/data/academy/course.json", import.meta.url), "utf8"));
const CONTENT = readFileSync(new URL("../../backend/app/academy/content.py", import.meta.url), "utf8");
const VIDEO_IDS = new Set([...CONTENT.match(/VIDEO_MEDIA = \{([\s\S]*?)\n\}/)[1].matchAll(/"(\w+)"/g)].map(m => m[1]).filter(x => x !== "cached" && x !== "online"));
const ONLINE = new Set([...CONTENT.match(/"online": \(([\s\S]*?)\)/)[1].matchAll(/"(\w+)"/g)].map(m => m[1]));
const words = s => String(s).trim().split(/\s+/).filter(Boolean).length;
const lessons = COURSE.lessons.filter(l => !l.ride);
const core = coreLessons(COURSE.lessons);

test("video shim: no player yet → 'missing', and playVideo resolves {watched: false} (never throws)", async () => {
  _setVideoModule(undefined);           // the real lookup: in Node there is no import.meta.glob, so no player
  assert.equal(await videoState("psr"), "missing");
  assert.deepEqual(await playVideo("psr"), { watched: false, seconds: 0, missing: true });
  assert.equal(playable("missing"), false);
});

test("video shim: a player passes through; a broken one is caught", async () => {
  const calls = [];
  _setVideoModule({ isAvailable: id => (id === "psr" ? "cached" : "offline"), openVideo: async (id, o) => { calls.push([id, o]); return { watched: true, seconds: 117 }; } });
  assert.equal(await videoState("psr"), "cached");
  assert.equal(await videoState("meet_crew"), "offline");
  assert.deepEqual(await playVideo("psr", { context: "x" }), { watched: true, seconds: 117 });
  assert.deepEqual(calls, [["psr", { context: "x" }]]);
  _setVideoModule({ isAvailable: () => { throw new Error("boom"); }, openVideo: async () => { throw new Error("boom"); } });
  assert.equal(await videoState("psr"), "offline");
  assert.equal((await playVideo("psr")).watched, false);
  _setVideoModule({ openVideo: async () => null });   // a player without the probe: try it
  assert.equal(await videoState("psr"), "online");
  _setVideoModule(null);
  assert.equal(await videoState("psr"), "missing");
  _setVideoModule(undefined);
});

test("debrief Learn more: one video per outcome, the online pick only online, else a fact card", async () => {
  const all = st => () => st;
  assert.deepEqual(await pickLearnMore("dose_limit", all("online")), { kind: "video", media: "solar_eruptions", line: S.LEARN_MORE.dose_limit.line });
  assert.deepEqual(await pickLearnMore("dose_limit", id => (id === "moon_weather" ? "cached" : "offline")),
    { kind: "video", media: "moon_weather", line: S.LEARN_MORE.dose_limit.line });
  assert.deepEqual(await pickLearnMore("power_out", all("online")), { kind: "fact", text: S.LEARN_MORE.power_out.fact });
  assert.deepEqual(await pickLearnMore("life_support_out", all("cached")), { kind: "video", media: "water_extraction", line: S.LEARN_MORE.life_support_out.line });
  assert.deepEqual(await pickLearnMore("survived", all("online")), { kind: "video", media: "meet_crew", line: S.LEARN_MORE.survived.line });
  assert.deepEqual(await pickLearnMore("success", all("online")), await pickLearnMore("survived", all("online")));
  for (const o of LEARN_MORE_OUTCOMES) {   // offline or no player: always a fact, never a dead button
    assert.deepEqual(await pickLearnMore(o, all("offline")), { kind: "fact", text: S.LEARN_MORE[o].fact });
    assert.deepEqual(await pickLearnMore(o, all("missing")), { kind: "fact", text: S.LEARN_MORE[o].fact });
    assert.deepEqual(await pickLearnMore(o, () => { throw new Error("x"); }), { kind: "fact", text: S.LEARN_MORE[o].fact });
  }
  assert.equal(await pickLearnMore("in_progress", all("online")), null);
});

test("Learn more names only known NASA videos; the online-only pick is a YouTube one", () => {
  for (const o of LEARN_MORE_OUTCOMES) {
    const e = S.LEARN_MORE[o];
    if (e.media) assert.ok(VIDEO_IDS.has(e.media), e.media);
    if (e.online) assert.ok(ONLINE.has(e.online), e.online);
    assert.ok(words(e.fact) <= 20 && words(e.line) <= 12, o);
  }
  for (const id of Object.keys(S.VIDEO_LENGTH)) assert.ok(VIDEO_IDS.has(id), id);
  for (const id of VIDEO_IDS) assert.ok(S.VIDEO_LENGTH[id], `no length for ${id}`);
  assert.equal(S.VIDEO.watch("hammer_feather"), "Watch (1 min)");
});

test("course video steps name known videos and keep the contract shape", () => {
  const vs = COURSE.lessons.flatMap(l => l.steps.filter(s => s.type === "video").map(s => [l.id, s]));
  assert.equal(vs.length, 7);
  for (const [lid, s] of vs) {
    assert.ok(VIDEO_IDS.has(s.media), `${lid}: ${s.media}`);
    assert.ok(s.say && s.reveal && s.prompt === s.say && s.accept.type === "video", lid);
    assert.ok(words(s.say) <= 20 && words(s.reveal) <= 20, lid);
  }
});

test("Mission prep: six tasks, 3 spoken steps or fewer, never speaking 'done'; copy budgets", () => {
  const preps = COURSE.lessons.filter(l => l.prep).map(l => l.prep);
  assert.equal(preps.length, 6);
  for (const p of preps) {
    assert.ok(p.steps.length >= 1 && p.steps.length <= 3, p.id);
    assert.ok(p.steps.every(t => words(t) <= 20), p.id);
    assert.match(p.steps[p.steps.length - 1], /Tell me when it's ready\.$/);
    assert.ok(p.steps.every(t => !/\bdone\b/i.test(t)), `${p.id} speaks the trigger word`);
    assert.ok(words(p.title) <= 6 && p.source && /^https:\/\//.test(p.source.url), p.id);
  }
  for (const k of ["intro", "grownUpSay", "doneSay", "skipSay", "ask"]) { assert.ok(words(S.PREP[k]) <= 20, k); assert.doesNotMatch(S.PREP[k], /\bdone\b/i, k); }
  for (const k of ["done", "skip", "open", "eyebrow"]) assert.ok(words(S.PREP[k]) <= 3, k);
  assert.ok(words(S.PREP.how) <= 12 && words(S.PREP.grownUp) <= 4);
  assert.ok(words(S.PREP.intro + " " + S.PREP.grownUpSay) <= 20);
});

test("first-mission Moon Base line and the pretend-base credit", () => {
  assert.equal(S.MOON_BASE.line, "NASA plans a real base near here. Ours is pretend. Let's run it.");
  assert.ok(words(S.MOON_BASE.title) <= 6 && words(S.MOON_BASE.watch) <= 3 && words(S.MOON_BASE.help) <= 4);
  assert.equal(S.PRETEND_BASE, "Outpost Luna is a pretend outpost for learning. NASA's real Moon Base plans: nasa.gov/moon-base.");
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  assert.match(html, /Outpost Luna is a pretend outpost for learning\. NASA's real Moon Base plans: <a href="https:\/\/www\.nasa\.gov\/moon-base\/"/);
  assert.match(html, /lroc\.im-ldi\.com/); assert.doesNotMatch(html, /lroc\.asu\.edu/);
  assert.match(html, /NASA\/GSFC\/Arizona State University/); assert.match(html, /NASA's Scientific Visualization Studio/);
  for (const t of [S.VIDEO.offline, S.VIDEO.missing]) assert.ok(words(t) <= 12, t);
});

test("story.js follows the course: tracks, blurbs, beats and lesson numbers (no stale or missing lessons)", () => {
  const ids = COURSE.lessons.map(l => l.id);
  assert.deepEqual(S.TRACKS.flatMap(t => t.lessons).sort(), [...ids].sort());
  assert.deepEqual(Object.keys(S.LESSON_BLURB).sort(), [...ids].sort());
  assert.deepEqual(Object.keys(S.LESSON_STORY).sort(), [...ids].sort());
  for (const c of Object.values(S.CALLBACKS)) assert.equal(core.findIndex(l => l.id === c.lesson) + 1, c.n, c.lesson);
  assert.deepEqual(core.map(l => l.id), ["moon", "phases", "power", "comms", "radiation", "life"]);
  assert.deepEqual(S.TRACKS.find(t => t.id === "explorer").lessons, COURSE.lessons.filter(isExplorer).map(l => l.id));
  assert.equal(S.TRANSITION.patchProgress(8, 9), "8 of 9 patches. One lesson to go.");
});

test("explorer lessons: locked until missions are flown; counted once per mission; core numbering", () => {
  const store = new Map(), st = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)) };
  const grav = COURSE.lessons.find(l => l.id === "gravity"), hist = COURSE.lessons.find(l => l.id === "history");
  assert.ok(isExplorer(grav) && grav.unlock_after_missions === 1 && hist.unlock_after_missions === 2);
  assert.equal(missionsFlown("Nova", st), 0);
  assert.ok(!unlocked(grav, 0) && unlocked(COURSE.lessons[0], 0));
  assert.equal(markMissionFlown("m1", "Nova", st), 1);
  assert.equal(markMissionFlown("m1", "Nova", st), 1);          // the same debrief shown twice counts once
  assert.equal(missionsFlown("Comet", st), 0);                  // per call sign
  assert.ok(unlocked(grav, 1) && !unlocked(hist, 1));
  assert.deepEqual(newlyUnlocked(COURSE.lessons, 1).map(l => l.id), ["gravity"]);
  assert.deepEqual(newlyUnlocked(COURSE.lessons, 2).map(l => l.id), ["history"]);
  assert.deepEqual(newlyUnlocked(COURSE.lessons, 3), []);
  assert.equal(core.length, 6);                                 // "Lesson n of 6"; patches count all 9
  assert.equal(S.EXPLORER.locked(1), "Unlocks after your first mission");
  assert.ok(words(S.EXPLORER.lockedSay) <= 20 && words(S.EXPLORER.locked(2)) <= 12);
});
