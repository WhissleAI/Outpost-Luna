// Academy API client + on-device progress (localStorage, no names: a kids' app). See backend/app/academy/routes.py.
import { activeCourse, courseView, mergeView, readStore, writeStore, ACADEMY_KEY } from "../courses.js";
async function j(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) { const e = new Error(url + " " + r.status); e.status = r.status; throw e; }
  return r.json();
}
const post = (url, body) => j(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

export const academyApi = {
  course: () => j("/api/academy/course"),
  /** {lesson_id, step, input:{text?|tap?|choice?}, misses, ride_id?} → {status, say, next_step?, badge?, hint?, state?, decisions} */
  attempt: body => post("/api/academy/attempt", body),
  ride: () => post("/api/academy/ride"),
  /** The kid asked for help: {lesson_id, step, rung (1 highlight, 2 label, 3 show), got?} → the ladder's next rung,
   *  no miss counted: {status: "help", rung, say, focus?, label?, eliminate?, cue?, answer?, phrase?, line_lon?, show?} */
  hint: body => post("/api/academy/hint", body),
};

// Progress is stored per course under course-prefixed ids (courses.js: "atm-academy" v2, a v1 save migrates once and
// is kept as "atm-academy.v1"). The lesson UI sees the active course's progress with bare ids, as it always has.
const blank = () => ({ badges: [], qualified: false });

export const progress = {
  load() {
    try { return { ...blank(), ...courseView(readStore(), activeCourse()) }; }
    catch (e) { return blank(); }
  },
  save(p) { try { writeStore(mergeView(readStore(), activeCourse(), p)); } catch (e) { /* private mode: progress lasts this visit */ } },
  reset() { try { localStorage.removeItem(ACADEMY_KEY); } catch (e) { /* none */ } },
};

// [0.4.1] Lesson resume: reopening the app goes back to a half-done lesson at its step. Stored with the progress
// (`atm-academy`, so per cadet and kept by Reset): steps = {lessonId: {i, n}} (the step shown, and how many steps the
// lesson had), current = the lesson last open. Cleared when the lesson is finished. A course that changed under it
// (another step count, a lesson gone) starts that lesson from the top. Pure: these return a new progress object.

/** Remember that lesson `l` is open at step i. Step 0 is not worth remembering (it starts there anyway). */
export function saveStep(p, l, i) {
  const steps = { ...(p.steps || {}) };
  if (i > 0 && i < l.steps.length) steps[l.id] = { i, n: l.steps.length }; else delete steps[l.id];
  return { ...p, steps, current: i > 0 ? l.id : (p.current === l.id ? null : p.current || null) };
}
/** The lesson is done (or left for good): forget its step. */
export function clearStep(p, id) {
  const steps = { ...(p.steps || {}) }; delete steps[id];
  return { ...p, steps, current: p.current === id ? null : p.current || null };
}
/** Where lesson `l` picks up: the saved step when it still fits the lesson, else 0. */
export function resumeStep(p, l) {
  const s = l && p && p.steps && p.steps[l.id];
  if (!s || !Number.isInteger(s.i) || s.n !== l.steps.length || s.i <= 0 || s.i >= l.steps.length) return 0;
  return s.i;
}
/** The half-done lesson to reopen at launch: {lesson, step} or null (none, gone from the course, or back at step 0). */
export function resumeTarget(p, lessons) {
  const l = p && p.current && (lessons || []).find(x => x.id === p.current);
  if (!l || l.ride) return null;
  const step = resumeStep(p, l);
  return step ? { lesson: l, step } : null;
}
