// [0.4.1] Lesson resume (academy/client.js), numbered / locked map pins and the locked Field School track
// (academy/pins.js), and the cockpit that is always dark (tokens.css).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

globalThis.window = globalThis.window || {};
const C = await import("../src/academy/client.js");
const P = await import("../src/academy/pins.js");
const { FIELD } = await import("../src/story.js");
const { coreLessons, fieldLessons, unlocked } = await import("../src/explorer.js");

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const COURSE = JSON.parse(src("../../backend/data/academy/course.json"));
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const L = id => COURSE.lessons.find(l => l.id === id);

test("resume: the step shown is saved per lesson, with the progress; step 0 is not worth saving", () => {
  const blank = { badges: [], qualified: false };
  let p = C.saveStep(blank, L("phases"), 2);
  assert.deepEqual(p.steps, { phases: { i: 2, n: L("phases").steps.length } });
  assert.equal(p.current, "phases");
  assert.deepEqual(p.badges, []);
  assert.equal(C.resumeStep(p, L("phases")), 2);
  assert.equal(C.resumeStep(p, L("moon")), 0, "another lesson starts at the top");
  p = C.saveStep(p, L("moon"), 1);
  assert.equal(p.current, "moon");
  assert.equal(C.resumeStep(p, L("phases")), 2, "every lesson keeps its own step");
  const back = C.saveStep(p, L("moon"), 0);
  assert.equal(back.steps.moon, undefined);
  assert.equal(back.current, null);
});

test("resume: cleared on completion; the app reopens the half-done lesson at its step", () => {
  let p = C.saveStep({ badges: ["scout"], qualified: false }, L("phases"), 3);
  assert.deepEqual(C.resumeTarget(p, COURSE.lessons), { lesson: L("phases"), step: 3 });
  p = C.clearStep(p, "phases");
  assert.equal(C.resumeStep(p, L("phases")), 0);
  assert.equal(C.resumeTarget(p, COURSE.lessons), null);
  assert.deepEqual(p.badges, ["scout"], "the patches stay");
});

test("resume: safe if the course changed (another step count, a step gone, a lesson gone, junk)", () => {
  const l = L("phases"), n = l.steps.length;
  const p = { badges: [], steps: { phases: { i: 2, n } }, current: "phases" };
  assert.equal(C.resumeStep(p, { ...l, steps: l.steps.slice(0, n - 1) }), 0, "a step removed: from the top");
  assert.equal(C.resumeStep(p, { ...l, steps: [...l.steps, l.steps[0]] }), 0, "a step added: from the top");
  assert.equal(C.resumeStep({ steps: { phases: { i: n, n } } }, l), 0, "past the end");
  assert.equal(C.resumeStep({ steps: { phases: { i: "2", n } } }, l), 0);
  assert.equal(C.resumeStep({ steps: { phases: null } }, l), 0);
  assert.equal(C.resumeStep({}, l), 0);
  assert.equal(C.resumeTarget({ steps: { gone: { i: 1, n: 3 } }, current: "gone" }, COURSE.lessons), null, "a lesson gone");
  assert.equal(C.resumeTarget({ steps: { checkride: { i: 1, n: L("checkride").steps.length } }, current: "checkride" }, COURSE.lessons), null, "never the check ride");
});

test("resume: the lesson UI saves the step it renders, opens at it, and forgets it when the lesson is done", () => {
  const ui = src("../src/academy/ui.js");
  assert.match(ui, /stepKey = L\.id \+ ":" \+ i; stepAt = now\(\); rememberStep\(\);/);
  assert.match(ui, /i = L\.ride \? 0 : resumeStep\(prog, L\); misses = 0; waitingNext = false; feedback = null;/, "a new lesson starts clean");
  assert.match(ui, /if \(L\) prog = clearStep\(prog, L\.id\);/);
  assert.match(ui, /if \(i \+ 1 >= L\.steps\.length\) \{ forgetStep\(L\.id\); showMap\(\); return; \}/);
  assert.match(ui, /const t = callSign\.get\(\) \? resumeTarget\(prog, lessons\(\)\) : null;\s*if \(t && open\(t\.lesson\)\) \{ openLesson\(t\.lesson\.id\); return; \}/);
  assert.match(ui, /L\.steps\[i\]\.prompt\] : \[/, "a resumed lesson asks that step's question");
});

test("pins: every core pin shows its number; a locked pin shows a lock", () => {
  const core = coreLessons(COURSE.lessons);
  assert.ok(core.length >= 6);
  core.forEach((l, k) => {
    const h = P.pinInnerHtml({ patchHtml: "<svg/>", no: String(k + 1), locked: false, title: l.title, esc, lockIcon: "<i>lock</i>" });
    assert.match(h, new RegExp(`<span class="pin-no" aria-hidden="true">${k + 1}</span>`));
    assert.doesNotMatch(h, /pin-lock/);
  });
  const field = fieldLessons(COURSE.lessons)[0];
  const h = P.pinInnerHtml({ patchHtml: "<svg/>", no: "", locked: !unlocked(field, 0, false), title: field.title, esc, lockIcon: "<i>lock</i>" });
  assert.match(h, /<span class="pin-lock" aria-hidden="true"><i>lock<\/i><\/span>/);
  assert.doesNotMatch(h, /pin-no/);
  const ui = src("../src/academy/ui.js");
  assert.match(ui, /const no = l\.ride \|\| isBonus\(l\) \? "" : String\(lessonNo\(l\)\.n\);/);
  assert.match(ui, /pinInnerHtml\(\{ patchHtml: patch\(l\.id, [^)]*\), no, locked: !open\(l\),/);
  assert.match(src("../src/school.css"), /\.pin-no,\.pin-lock\{/);
});

test("Field School: a visible locked track before the check ride, gone once qualified; unlock logic unchanged", () => {
  const fl = fieldLessons(COURSE.lessons);
  const h = P.fieldTrackHtml({ qualified: false, fieldLessons: fl, copy: FIELD, esc, lockIcon: "<i>lock</i>" });
  assert.match(h, /id="aFieldTrack"/);
  assert.ok(h.includes("Field School") && h.includes("Opens after your check ride") && h.includes(`${fl.length} geology lessons`));
  assert.match(h, new RegExp(`data-l="${fl[0].id}"`));
  assert.equal(P.fieldTrackHtml({ qualified: true, fieldLessons: fl, copy: FIELD, esc }), "");
  assert.equal(P.fieldTrackHtml({ qualified: false, fieldLessons: [], copy: FIELD, esc }), "");
  for (const l of fl) { assert.equal(unlocked(l, 9, false), false); assert.equal(unlocked(l, 0, true), true); }
  assert.match(src("../src/academy/ui.js"), /const lockedText = l => \(isField\(l\) \? FIELD\.lockedTrack : EXPLORER\.locked\(lockedWhen\(l\)\)\);/);
});

test("theme: dark stays the default; the cockpit (Mission cabin, check-ride cockpit, its folded header) is always dark", async () => {
  const { PREF_DEFAULTS } = await import("../src/prefs.js");
  assert.equal(PREF_DEFAULTS.theme, "dark");
  const t = src("../src/tokens.css");
  const m = t.match(/:root\[data-theme="dark"\],\s*body\[data-cabin="1"\],\s*\.m-cabin,\s*body\[data-cockpit="1"\] \.topbar \{([^}]*)\}/);
  assert.ok(m, "the dark tokens also sit on the cockpit's own elements");
  for (const k of ["--color-bg: #0B0D12", "--color-surface: #141821", "--color-text: #F3F5F8", "color-scheme: dark"]) assert.ok(m[1].includes(k), k);
  assert.match(t, /:root\[data-contrast="high"\],\s*:root\[data-contrast="high"\] :is\(body\[data-cabin="1"\], \.m-cabin, body\[data-cockpit="1"\] \.topbar\) \{/, "high contrast still wins in the cockpit");
  // both cockpits carry .m-cabin; the Mission cabin sets body[data-cabin]
  assert.match(src("../src/academy/ui.js"), /host\.className = "m-cabin a-ridecabin"/);
  assert.match(src("../src/mission/ui.js"), /document\.body\.dataset\.cabin = "1"/);
});
