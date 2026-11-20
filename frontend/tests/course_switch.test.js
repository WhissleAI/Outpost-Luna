// The course switcher (src/course_switch.js): hidden with one course; a short list, then one confirm.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const C = await import("../src/courses.js");
const S = await import("../src/course_switch.js");
const esc = s => s;

const MOON = { id: "moon", title: "The Moon", status: "builtin", subject: "Earth and space science", grades: "3-8", labels: { course: "Moon" } };
const ARCH = { id: "archaeology", title: "Archaeology", status: "pack", subject: "Social studies", grades: "9-12", labels: { course: "Archaeology" } };

test("hidden while only the Moon is installed", () => {
  C.courseState.courses = [MOON]; C.courseState.info = MOON; C.courseState.active = "moon";
  assert.equal(C.installed().length, 1);
  const chip = { hidden: false, textContent: "", setAttribute() {}, addEventListener() {} };
  globalThis.document = { documentElement: { dataset: {} } };
  const sw = S.installCourseSwitch({ chip, doc: {} });
  assert.equal(chip.hidden, true); assert.equal(sw.visible(), false); assert.equal(sw.open(), false);
});

test("shown with two courses; drafts never count", () => {
  C.courseState.courses = [MOON, ARCH, { id: "geo", title: "Geo", status: "draft" }];
  assert.deepEqual(C.installed().map(c => c.id), ["moon", "archaeology"]);
  const chip = { hidden: true, textContent: "", attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {} };
  S.installCourseSwitch({ chip, doc: {} });
  assert.equal(chip.hidden, false); assert.equal(chip.textContent, "Moon"); assert.equal(chip.attrs["aria-label"], "Course: Moon");
  assert.equal(chip.attrs["aria-haspopup"], "dialog");
});

test("the list marks the course being played; the confirm says patches stay", () => {
  const h = S.listHtml([MOON, ARCH], "moon", { more: true });
  assert.match(h, /data-course="moon"[^>]*\n?\s*aria-current="true"/);
  assert.match(h, /Archaeology<\/b><small>Social studies · grades 9-12/);
  assert.match(h, /Get more courses/);
  assert.doesNotMatch(S.listHtml([MOON, ARCH], "moon"), /Get more courses/);
  const c = S.confirmHtml(ARCH, MOON);
  assert.match(c, /Switch to Archaeology\?/); assert.match(c, /Your Moon patches stay\./); assert.match(c, /data-crs-yes="archaeology"/);
});

test("copy stays short and plain (docs/COPY.md)", () => {
  for (const v of Object.values(S.COPY)) {
    const t = typeof v === "function" ? v("Archaeology") : v;
    assert.ok(t.split(/\s+/).length <= 8, t);
  }
});
