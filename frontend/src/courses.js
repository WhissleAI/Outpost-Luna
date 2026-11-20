// Courses on the client (docs/COURSES.md §4). The Moon is course #1; the backend owns the registry (GET /api/courses,
// app/courses.py) and the client owns which course each cadet plays.
//
// - The active course is per call sign: "outpost-course" is a profile key (prefs.js PROFILE_KEYS), so it moves with
//   the cadet's profile. Default "moon". At launch syncCourse() tells the backend (POST /api/courses/active) so the
//   lessons, places, names list and keyterms it serves are this cadet's course. A course that is not installed any
//   more (a pack removed) falls back to the Moon.
// - Ids are course-prefixed: "<course>:<id>" (moon:phases, moon:scout). The progress store ("atm-academy") keeps
//   every course's patches, the qualified flag and the half-done lesson under prefixed ids (v2). A v1 save (bare ids,
//   from before courses) migrates losslessly: every bare id is the Moon's, and the original is kept untouched under
//   "atm-academy.v1" (a progress key: only "erase progress too" removes it). The lesson UI sees the ids its lessons use
//   (bare on the Moon, prefixed elsewhere, as the backend serves them): courseView() / mergeView() translate.
// - Switching: setCourse() stores the choice, tells the backend, fires `outpost:course-changed`, then the app
//   reloads (as a profile switch does) so every module, the globe included, starts clean on the new course.
// Pure helpers first (tests/courses.test.js), then the small client.

export const COURSE_KEY = "outpost-course";
export const DEFAULT_COURSE = "moon";
export const ACADEMY_KEY = "atm-academy";
export const ACADEMY_BACKUP = "atm-academy.v1";
export const STORE_V = 2;
const CID = /^[a-z][a-z0-9-]{1,23}$/;
export const validCourse = c => typeof c === "string" && CID.test(c);

// ---------------------------------------------------------------- ids (pure)
/** "<course>:<id>" */
export const qid = (course, id) => { const c = validCourse(course) ? course : DEFAULT_COURSE, s = String(id ?? "");
  return s.startsWith(c + ":") ? s : `${c}:${s}`; };   // idempotent: an id already in the course stays as it is
/** "<course>:<id>" → {course, id}. A bare id (a v1 save, a class lesson) is the Moon's. */
export function splitQid(q) {
  const s = String(q ?? ""), i = s.indexOf(":");
  if (i > 0 && validCourse(s.slice(0, i))) return { course: s.slice(0, i), id: s.slice(i + 1) };
  return { course: DEFAULT_COURSE, id: s };
}
const inCourse = (q, course) => splitQid(q).course === course;

// ---------------------------------------------------------------- the progress store (pure)
const blankStore = () => ({ v: STORE_V, badges: [], qualified: [], steps: {}, current: {} });
const strs = a => (Array.isArray(a) ? a.filter(x => typeof x === "string" && x) : []);
const stepOk = s => s && Number.isInteger(s.i) && Number.isInteger(s.n);

/** Any saved value (v1, v2, junk) → a clean v2 store. v1: every bare id is the Moon's; unknown top-level fields are
 *  kept as they were (lossless). Pure: never touches storage. */
export function migrateAcademy(raw) {
  const p = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : null;
  if (!p) return blankStore();
  const out = { ...p, ...blankStore() };
  if (p.v === STORE_V) {
    out.badges = [...new Set(strs(p.badges).map(b => qid(splitQid(b).course, splitQid(b).id)))];
    out.qualified = [...new Set(strs(p.qualified).filter(validCourse))];
    for (const [k, s] of Object.entries(p.steps && typeof p.steps === "object" ? p.steps : {})) if (stepOk(s)) out.steps[qid(splitQid(k).course, splitQid(k).id)] = { i: s.i, n: s.n };
    for (const [c, q] of Object.entries(p.current && typeof p.current === "object" ? p.current : {})) if (validCourse(c) && typeof q === "string" && inCourse(q, c)) out.current[c] = q;
    return out;
  }
  // v1 (before courses): {badges: [bare], qualified: bool, steps: {bare: {i, n}}, current: bare | null}
  out.badges = [...new Set(strs(p.badges).map(b => qid(DEFAULT_COURSE, b)))];
  out.qualified = p.qualified ? [DEFAULT_COURSE] : [];
  for (const [k, s] of Object.entries(p.steps && typeof p.steps === "object" ? p.steps : {})) if (stepOk(s)) out.steps[qid(DEFAULT_COURSE, k)] = { i: s.i, n: s.n };
  if (typeof p.current === "string" && p.current) out.current[DEFAULT_COURSE] = qid(DEFAULT_COURSE, p.current);
  return out;
}

/** One course's progress in the shape the lesson UI has always used: {badges: [bare], qualified, steps: {bare}, current}. */
export function courseView(store, course = DEFAULT_COURSE) {
  const s = store && store.v === STORE_V ? store : migrateAcademy(store);
  // the ids the course's lessons use: bare on the Moon (as always), "<course>:<id>" elsewhere (the backend serves another
  // course's lessons prefixed, app/academy/content.py prefixed())
  const bare = q => (course === DEFAULT_COURSE ? splitQid(q).id : q);
  const steps = {};
  for (const [k, v] of Object.entries(s.steps)) if (inCourse(k, course)) steps[bare(k)] = { ...v };
  return { badges: s.badges.filter(b => inCourse(b, course)).map(bare), qualified: s.qualified.includes(course),
    steps, current: s.current[course] ? bare(s.current[course]) : null };
}

/** Write one course's view back into the store (other courses untouched). Pure: returns a new store. */
export function mergeView(store, course, view) {
  const s = store && store.v === STORE_V ? store : migrateAcademy(store);
  const v = view || {};
  const out = { ...s, badges: s.badges.filter(b => !inCourse(b, course)), qualified: s.qualified.filter(c => c !== course),
    steps: Object.fromEntries(Object.entries(s.steps).filter(([k]) => !inCourse(k, course))), current: { ...s.current } };
  out.badges.push(...[...new Set(strs(v.badges))].map(b => qid(course, b)));
  if (v.qualified) out.qualified.push(course);
  for (const [k, st] of Object.entries(v.steps && typeof v.steps === "object" ? v.steps : {})) if (stepOk(st)) out.steps[qid(course, k)] = { i: st.i, n: st.n };
  if (typeof v.current === "string" && v.current) out.current[course] = qid(course, v.current); else delete out.current[course];
  return out;
}

/** A raw saved string (any version) → one course's view. For readers of other cadets' snapshots (prefs, Progress). */
export function viewOfRaw(raw, course = DEFAULT_COURSE) {
  let p = null; try { p = typeof raw === "string" ? JSON.parse(raw || "null") : raw; } catch (e) { p = null; }
  return courseView(migrateAcademy(p), course);
}

// ---------------------------------------------------------------- storage (try/catch: private mode lasts a visit)
const ls = () => { try { return typeof localStorage !== "undefined" ? localStorage : null; } catch (e) { return null; } };
const sget = (st, k) => { try { return st ? st.getItem(k) : null; } catch (e) { return null; } };
const sset = (st, k, v) => { try { if (st) (v == null ? st.removeItem(k) : st.setItem(k, v)); } catch (e) { /* full / blocked */ } };

/** The cadet's course (the stored choice, else the Moon). */
export function activeCourse(storage = ls()) {
  const c = sget(storage, COURSE_KEY);
  return validCourse(c) ? c : DEFAULT_COURSE;
}

/** The v2 store, migrating a v1 save in place once (the original kept under ACADEMY_BACKUP). */
export function readStore(storage = ls()) {
  const raw = sget(storage, ACADEMY_KEY);
  let p = null; try { p = JSON.parse(raw || "null"); } catch (e) { p = null; }
  if (raw && p && p.v !== STORE_V) {
    if (sget(storage, ACADEMY_BACKUP) == null) sset(storage, ACADEMY_BACKUP, raw);
    const s = migrateAcademy(p);
    sset(storage, ACADEMY_KEY, JSON.stringify(s));
    return s;
  }
  return migrateAcademy(p);
}
export const writeStore = (s, storage = ls()) => sset(storage, ACADEMY_KEY, JSON.stringify(migrateAcademy(s)));

// ---------------------------------------------------------------- the registry and switching
const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || {}) : {};
const MOON_INFO = Object.freeze({ id: "moon", title: "The Moon", status: "builtin", removable: false,
  globe: { body: "moon", name: "Moon", km: 1737.4 }, labels: { course: "Moon", school: "Flight School", lessons: "Lessons", patches: "NASA patches", patch: "patch" },
  standards: [], big_ideas: {} });

/** {active, courses, info} once synced; the Moon alone before (or with an older backend). */
export const courseState = { active: DEFAULT_COURSE, courses: [MOON_INFO], info: MOON_INFO, synced: false };
export const courseInfo = () => courseState.info;
/** The course's word for a label (labels: course, school, lessons, patches, patch). */
export const courseLabel = (k, fb = "") => ((courseState.info && courseState.info.labels) || {})[k] || MOON_INFO.labels[k] || fb;
/** Installed courses the switcher offers (it stays hidden with fewer than two). */
export const installed = () => courseState.courses.filter(c => c && c.status !== "draft");

/** Launch: read the registry, make the backend play this cadet's course. Never throws: an older backend (no
 *  /api/courses) or a network error leaves the Moon. */
export async function syncCourse({ fetchFn = typeof fetch === "function" ? fetch : null, storage = ls() } = {}) {
  if (!fetchFn) return courseState;
  try {
    const r = await fetchFn("/api/courses");
    if (!r.ok) return courseState;
    const d = await r.json();
    const list = Array.isArray(d.courses) && d.courses.length ? d.courses : [MOON_INFO];
    let want = activeCourse(storage);
    if (!list.some(c => c.id === want)) { want = DEFAULT_COURSE; sset(storage, COURSE_KEY, null); }
    if (d.active !== want) {
      const p = await fetchFn("/api/courses/active", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: want }) });
      if (!p.ok) want = d.active || DEFAULT_COURSE;
    }
    courseState.active = want; courseState.courses = list; courseState.synced = true;
    courseState.info = list.find(c => c.id === want) || MOON_INFO;
  } catch (e) { /* the Moon */ }
  O.course = courseState.info;
  return courseState;
}

/** Switch this cadet to an installed course: store it, tell the backend, announce it, then reload the app.
 *  -> false when the backend refused (not installed). */
export async function setCourse(id, { fetchFn = typeof fetch === "function" ? fetch : null, storage = ls(), reload = () => location.reload() } = {}) {
  if (!validCourse(id) || !fetchFn) return false;
  try {
    const r = await fetchFn("/api/courses/active", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }) });
    if (!r.ok) return false;
  } catch (e) { return false; }
  sset(storage, COURSE_KEY, id === DEFAULT_COURSE ? null : id);
  try { dispatchEvent(new CustomEvent("outpost:course-changed", { detail: { id } })); } catch (e) { /* node */ }
  reload();
  return true;
}
