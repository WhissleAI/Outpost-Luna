// Speech learning progress (docs/SPEECH_LEARNING.md §5): counts only, kept in the cadet Brain's store (brain_store.js
// "outpost-brain", a per-cadet progress key) as its `speech` section, per course (a lesson id "<course>:<id>" names
// its course; bare ids are the Moon). brain_store.clean() keeps the section through this file's parse().
// Never the words a cadet said or typed: passages read, questions answered, read-aloud sessions and words read
// correctly, words practised with their spaced-repetition box, summaries and key points told.
//
// Spaced repetition: a Leitner box per word (0..4). Right moves a word up a box, a miss (or a sound-alike trap) puts it
// back in box 1. A word is due again after BOX_DAYS[box] days (a date, YYYY-MM-DD: the Brain keeps nothing finer than
// a day). The vocab step asks due words first, then new ones.
export const KEY = "outpost-brain";
export const BOX_DAYS = [0, 1, 3, 7, 14];
export const LEARNED_BOX = 3;
const DAY = 86400000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
export const dayOf = (t = Date.now()) => { const d = new Date(t); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

export const courseOf = lessonId => (String(lessonId || "").includes(":") ? String(lessonId).split(":")[0] : "moon");

const blank = () => ({ read: 0, questions: 0, aloud: 0, aloud_words: 0, summaries: 0, points: 0, words: {} });

/** Parse the Brain's `speech` section (or anything) into {v:1, c:{course: counts}}; junk becomes empty. Pure. */
export function parse(raw) {
  let s = null;
  try { s = typeof raw === "string" ? JSON.parse(raw) : raw; } catch (e) { s = null; }
  const out = { v: 1, c: {} };
  const cs = s && s.c && typeof s.c === "object" ? s.c : {};
  for (const [course, v] of Object.entries(cs)) {
    if (!/^[a-z0-9_-]{1,24}$/.test(course) || !v || typeof v !== "object") continue;
    const b = blank();
    for (const k of ["read", "questions", "aloud", "aloud_words", "summaries", "points"]) b[k] = Math.max(0, Math.floor(+v[k] || 0));
    for (const [w, e] of Object.entries(v.words && typeof v.words === "object" ? v.words : {})) {
      if (typeof w !== "string" || w.length > 40 || !e) continue;
      if (!/^[a-z][a-z '-]{0,39}$/.test(w)) continue;   // a glossary word, never free text
      b.words[w] = { box: Math.max(0, Math.min(4, Math.floor(+e.box || 0))), due: typeof e.due === "string" && DATE.test(e.due) ? e.due : "", n: Math.max(0, Math.floor(+e.n || 0)) };
    }
    if (Object.keys(b.words).length || ["read", "questions", "aloud", "summaries"].some(k => b[k])) out.c[course] = b;   // empty: dropped
  }
  return out;
}

const storage = () => { try { return typeof localStorage !== "undefined" ? localStorage : null; } catch (e) { return null; } };
const brainRaw = st => { try { const v = JSON.parse((st && st.getItem(KEY)) || "null"); return v && typeof v === "object" ? v : null; } catch (e) { return null; } };
export function load(st = storage()) { const b = brainRaw(st); return parse(b && b.speech); }
/** Write the speech section into the Brain's store, leaving its other sections as they are. */
export function save(s, st = storage()) {
  try { if (!st) return; const b = brainRaw(st) || { v: 1, course: "moon", lessons: {}, days: [] }; b.speech = parse(s); st.setItem(KEY, JSON.stringify(b)); } catch (e) { /* private mode */ }
}

function bucket(s, course) { s.c[course] = s.c[course] || blank(); return s.c[course]; }

/** Pure updates (each returns the same object, changed). */
export function addCount(s, course, key, n = 1) { const b = bucket(s, course); b[key] = (b[key] || 0) + Math.max(0, Math.floor(n)); return s; }
export function recordWord(s, course, term, ok, now = Date.now()) {
  const b = bucket(s, course), w = String(term || "").toLowerCase().slice(0, 40);
  if (!w) return s;
  const e = b.words[w] || { box: 0, due: "", n: 0 };
  e.box = ok ? Math.min(4, e.box + 1) : 1;
  e.due = dayOf(now + BOX_DAYS[e.box] * DAY);
  e.n += 1;
  b.words[w] = e;
  return s;
}

/** The order to ask a step's items in: due words (most overdue first), then words never seen, then the rest by
 *  when they come due. items: [{id, term}]. Pure. */
export function planFor(items, s, course, now = Date.now()) {
  const words = ((s.c || {})[course] || {}).words || {}, today = dayOf(now);
  const rank = it => {
    const e = words[String(it.term || "").toLowerCase()];
    if (!e) return [1, ""];
    return e.due <= today ? [0, e.due] : [2, e.due];
  };
  return items.map((it, k) => ({ it, k, r: rank(it) }))
    .sort((a, b) => a.r[0] - b.r[0] || (a.r[1] < b.r[1] ? -1 : a.r[1] > b.r[1] ? 1 : 0) || a.k - b.k).map(x => x.it.id);
}

/** Counts for Progress / Brain: {course: {read, questions, aloud, aloud_words, summaries, points, practised, learned,
 *  review}}. Pure. */
export function summary(s, now = Date.now()) {
  const out = {};
  for (const [course, b] of Object.entries((s && s.c) || {})) {
    const ws = Object.values(b.words || {});
    const today = dayOf(now);
    const row = { ...b, practised: ws.length, learned: ws.filter(e => e.box >= LEARNED_BOX).length, review: ws.filter(e => e.due <= today).length };
    delete row.words;
    if (row.read || row.questions || row.aloud || row.summaries || row.practised) out[course] = row;
  }
  return out;
}

/** One lesson reply → the counts it adds (academy/ui.js sends every reply as "outpost:lesson-result"). Pure. */
export function applyReply(s, { lesson_id, step_type, status, reply = {}, input = {} } = {}, now = Date.now()) {
  const course = courseOf(lesson_id);
  if (!["read", "vocab", "summary"].includes(step_type) || !reply) return s;
  const prior = Array.isArray(input.got) ? input.got.length : 0, got = Array.isArray(reply.got) ? reply.got.length : prior;
  if (step_type === "read") {
    if (got > prior && !reply.shown) addCount(s, course, "questions", got - prior);
    if (status === "passed") addCount(s, course, "read");
  }
  if (step_type === "vocab" && reply.term) {
    if (got > prior || status === "passed") recordWord(s, course, reply.term, !reply.shown, now);
    else if (status === "hint") recordWord(s, course, reply.term, false, now);
  }
  if (step_type === "summary" && status === "passed") { addCount(s, course, "summaries"); addCount(s, course, "points", got); }
  return s;
}
