// A course switch starts getting what the new course still needs (backend: app/video.py kick, app/course_packs.py
// ensure_active). The chip shows a calm progress line, Course storage says how far, and a video on its way says
// "Getting ready…" instead of streaming. The Moon: nothing changes.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const C = await import("../src/courses.js");
const S = await import("../src/course_switch.js");

const MOON = { id: "moon", title: "The Moon", status: "builtin", labels: { course: "Moon" } };
const ARCH = { id: "archaeology", title: "Archaeology", status: "pack", labels: { course: "Archaeology" } };
const vids = (o = {}) => ({ course: "archaeology", total: 5, ready: 2, progress: 0.4, state: "downloading", ...o });

test("progressView: videos, a pack update, and nothing", () => {
  assert.deepEqual(C.progressView(null), { busy: false, pct: null, label: "", what: "" });
  assert.equal(C.progressView({ busy: false, videos: vids({ state: "done" }) }).busy, false);
  assert.deepEqual(C.progressView({ busy: true, pack: { state: "installed" }, videos: vids() }),
    { busy: true, pct: 40, label: "Getting its videos… 40%", what: "videos" });
  assert.equal(C.progressView({ busy: true, videos: vids({ progress: null }) }).label, "Getting its videos…");
  const pk = C.progressView({ busy: true, pack: { state: "installed", updating: true, progress: 0.25 }, videos: vids() });
  assert.equal(pk.what, "pack"); assert.equal(pk.pct, 25); assert.match(pk.label, /new course files… 25%/);
  assert.equal(C.progressView({ busy: true, videos: vids({ progress: 1.7 }) }).pct, 100, "clamped");
});

test("chipProgress keeps the course name and adds the progress to the label", () => {
  assert.deepEqual(S.chipProgress(null, "Archaeology"), { show: false, pct: null, label: "Course: Archaeology" });
  assert.deepEqual(S.chipProgress({ busy: true, videos: vids() }, "Archaeology"),
    { show: true, pct: 40, label: "Course: Archaeology. Getting its videos… 40%" });
});

function fakeChip() {
  const attrs = {}, props = {};
  return { hidden: true, textContent: "", title: "", dataset: {}, attrs, props,
    style: { setProperty: (k, v) => { props[k] = v; }, removeProperty: k => { delete props[k]; } },
    setAttribute: (k, v) => { attrs[k] = v; }, addEventListener() {} };
}
const answer = body => async url => { answer.urls.push(url); return { ok: true, json: async () => (typeof body === "function" ? body() : body) }; };
answer.urls = [];

test("the chip shows the download, polls while busy, then goes quiet", async () => {
  C.courseState.courses = [MOON, ARCH]; C.courseState.info = ARCH; C.courseState.active = "archaeology";
  globalThis.document = { documentElement: { dataset: {} } };
  let step = 0;
  const replies = [{ busy: true, videos: vids() }, { busy: true, videos: vids({ ready: 4, progress: 0.8 }) }, { busy: false, videos: vids({ ready: 5, progress: 1, state: "done" }) }];
  answer.urls = [];
  const chip = fakeChip();
  const sw = S.installCourseSwitch({ chip, doc: {}, fetchFn: answer(() => replies[Math.min(step++, 2)]), pollMs: 5 });
  await new Promise(r => setTimeout(r, 0));
  await new Promise(r => setTimeout(r, 0));
  assert.equal(chip.textContent, "Archaeology", "the name never changes");
  assert.equal(chip.dataset.dl, "40"); assert.equal(chip.props["--crs-dl"], "40%");
  assert.equal(chip.attrs["aria-label"], "Course: Archaeology. Getting its videos… 40%");
  assert.equal(chip.title, "Course: Archaeology. Getting its videos… 40%");
  await new Promise(r => setTimeout(r, 40));
  assert.ok(!("dl" in chip.dataset), "done: the line goes"); assert.equal(chip.title, "");
  assert.equal(chip.attrs["aria-label"], "Course: Archaeology");
  const n = answer.urls.length;
  assert.ok(n >= 3 && answer.urls.every(u => u === "/api/courses/active/progress"));
  await new Promise(r => setTimeout(r, 30));
  assert.equal(answer.urls.length, n, "quiet once nothing is on its way");
  sw.stop();
});

test("the Moon never asks (unchanged)", async () => {
  C.courseState.courses = [MOON, ARCH]; C.courseState.info = MOON; C.courseState.active = "moon";
  globalThis.document = { documentElement: { dataset: {} } };
  answer.urls = [];
  const chip = fakeChip();
  S.installCourseSwitch({ chip, doc: {}, fetchFn: answer({ busy: true, videos: vids() }), pollMs: 5 });
  await new Promise(r => setTimeout(r, 20));
  assert.equal(answer.urls.length, 0); assert.ok(!("dl" in chip.dataset));
  assert.equal(chip.attrs["aria-label"], "Course: Moon");
});

test("videos waiting offline: asked twice more, slowly, then stop; school / off: never again", async () => {
  C.courseState.courses = [MOON, ARCH]; C.courseState.info = ARCH; C.courseState.active = "archaeology";
  globalThis.document = { documentElement: { dataset: {} } };
  answer.urls = [];
  S.installCourseSwitch({ chip: fakeChip(), doc: {}, fetchFn: answer({ busy: false, videos: vids({ state: "waiting", reason: "offline" }) }), pollMs: 1 });
  await new Promise(r => setTimeout(r, 60));
  assert.equal(answer.urls.length, 3);
  answer.urls = [];
  S.installCourseSwitch({ chip: fakeChip(), doc: {}, fetchFn: answer({ busy: false, videos: vids({ state: "waiting", reason: "school" }) }), pollMs: 1 });
  await new Promise(r => setTimeout(r, 30));
  assert.equal(answer.urls.length, 1);
});

test("an older backend (no progress route): the chip is as it was", async () => {
  C.courseState.courses = [MOON, ARCH]; C.courseState.info = ARCH; C.courseState.active = "archaeology";
  globalThis.document = { documentElement: { dataset: {} } };
  const chip = fakeChip();
  S.installCourseSwitch({ chip, doc: {}, fetchFn: async () => ({ ok: false, json: async () => ({}) }), pollMs: 1 });
  await new Promise(r => setTimeout(r, 10));
  assert.ok(!("dl" in chip.dataset)); assert.equal(chip.attrs["aria-label"], "Course: Archaeology");
});

test("Course storage: the playing course's videos and its update, said calmly with a bar", async () => {
  const U = await import("../src/course_store_ui.js");
  C.courseState.active = "archaeology";
  const base = { id: "archaeology", title: "Course: Archaeology", size: 4608000, version: "2", state: "installed", active: true };
  let d = U.dlNote({ ...base, videos: vids() });
  assert.deepEqual(d, { note: "Getting its videos… 2 of 5 (40%)", bar: 40, busy: true });
  d = U.dlNote({ ...base, updating: true, progress: 0.5, videos: vids() });
  assert.equal(d.note, "Getting the new course files… 50%"); assert.equal(d.bar, 50);
  assert.equal(U.dlNote({ ...base, videos: vids({ state: "waiting", reason: "offline" }) }).note, "3 videos still to get. They download when you're online.");
  assert.equal(U.dlNote({ ...base, videos: vids({ state: "waiting", reason: "school", ready: 4 }) }).note, "1 video is off on the school network.");
  assert.equal(U.dlNote({ ...base, videos: vids({ state: "waiting", reason: "off" }) }).note, "3 videos play from the internet.");
  assert.equal(U.dlNote({ ...base, videos: vids({ state: "done", ready: 5 }) }).note, "All 5 videos saved.");
  assert.equal(U.dlNote({ ...base, videos: { state: "none", total: 0 } }).note, "");
  assert.equal(U.dlNote({ ...base, state: "missing" }).note, "");
  const html = U.listHtml({ packs: [{ ...base, videos: vids() }] });
  assert.match(html, /role="progressbar"[^>]*aria-valuenow="40"/);
  assert.match(html, /Getting its videos… 2 of 5 \(40%\)/);
  const row = U.rowOf({ ...base, videos: vids() });
  assert.deepEqual(row.actions.map(a => a.act), ["remove"], "playing: Remove only, as before");
  assert.equal(U.busy({ packs: [{ ...base, videos: vids() }] }), true);
  assert.equal(U.busy({ packs: [{ ...base, videos: vids({ state: "done", ready: 5 }) }] }), false);
  assert.equal(U.busy({ packs: [{ ...base, state: "downloading" }] }), true);
});

test("video: a course video on its way is 'downloading' (Getting ready…), never mapped to offline", async () => {
  const V = await import("../src/media/commands.js");
  assert.equal(V.DOWNLOADING, "Getting ready…");
  assert.match(V.DOWNLOADING_LINE, /still downloading/);
  const real = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ status: "downloading" }) });
    const M = await import("../src/media/video.js");
    assert.equal(await M.isAvailable("arch_lidar_space"), "downloading");
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ status: "weird" }) });
    assert.equal(await M.isAvailable("x"), "offline");
  } finally { globalThis.fetch = real; }
});
