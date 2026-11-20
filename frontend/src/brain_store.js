// The Brain's one new aggregate (docs/BRAIN.md §5): per-lesson practice counts for the cadet playing, on this device.
//
// Stored in localStorage under "outpost-brain", which is a per-cadet key (prefs.js PROFILE_KEYS: it moves with the
// cadet's profile) and a progress key (reset.js PROGRESS_KEYS: "Start over" keeps it, "Erase progress too" erases it;
// Settings → Cadets → Reset progress clears it with the patches). Never sent anywhere.
//
// What it holds, and nothing else: lesson ids (course ids, never titles), small counts, rounded seconds and the dates
// (YYYY-MM-DD) a lesson step was answered. No words, no answers, no call sign, no names, no audio, no timestamps finer
// than a day. Sanitised on read and on write (clean()), so a hand-edited value can't smuggle text into the views.
//
//   lessons: { <lessonId>: { steps, first, helped, shown, misses, pause, secs } }
//     steps   graded steps finished (a replay counts again)
//     first   right on the first try, no hint
//     helped  right after a miss or a hint
//     shown   CAPCOM showed the answer (or a check-ride order was missed)
//     misses  tries that weren't right yet
//     pause   extra-early hints the app gave after a long pause (the app's action, not a trait: docs/BRAIN.md §6)
//     secs    seconds on graded steps (each step capped at 5 minutes, so a walk away doesn't count)
//   days: ["2026-11-19", ...]   the days with a graded step, newest last, at most 60
//   course: "moon"               which course the lesson ids belong to (default "moon"; ready for more courses)
//   speech: { c: { <course>: {read, questions, aloud, aloud_words, summaries, points, words: {<glossary word>:
//            {box, due: YYYY-MM-DD, n}}} } }   reading / vocab / summary counts and the vocab spaced repetition
//            (academy/speech_store.js; docs/SPEECH_LEARNING.md). Counts and glossary words only, never what was said.

import { parse as parseSpeech } from "./academy/speech_store.js";

export const KEY = "outpost-brain";
export const MAX_DAYS = 60;
export const STEP_CAP_S = 300;
const ID = /^[a-z0-9][a-z0-9_:.-]{0,63}$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;
/** Steps that are guesses or watching, never right or wrong: they don't count toward practice. */
export const UNGRADED = new Set(["video", "predict"]);
const FIELDS = ["steps", "first", "helped", "shown", "misses", "pause", "secs"];

export const COURSE = "moon";   // the course these counts belong to (a future course switcher adds others)
const COURSE_ID = /^[a-z0-9][a-z0-9-]{0,23}$/;
export const blank = (course = COURSE) => ({ v: 1, course, lessons: {}, days: [] });
const n = x => (Number.isFinite(+x) && +x > 0 ? Math.min(1e6, Math.floor(+x)) : 0);

/** Keep only known ids, whole counts and real dates (pure). */
export function clean(raw) {
  const out = blank(raw && typeof raw.course === "string" && COURSE_ID.test(raw.course) ? raw.course : COURSE);
  if (!raw || typeof raw !== "object") return out;
  const ls = raw.lessons && typeof raw.lessons === "object" ? raw.lessons : {};
  for (const [id, v] of Object.entries(ls)) {
    if (!ID.test(id) || !v || typeof v !== "object") continue;
    out.lessons[id] = Object.fromEntries(FIELDS.map(f => [f, n(v[f])]));
  }
  const sp = parseSpeech(raw.speech);
  if (Object.keys(sp.c).length) out.speech = sp;
  out.days = [...new Set((Array.isArray(raw.days) ? raw.days : []).filter(d => typeof d === "string" && DAY.test(d)))].sort().slice(-MAX_DAYS);
  return out;
}

/** The local calendar day of a Date (pure). */
export const dayOf = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/**
 * Add one graded attempt (pure; returns a new store).
 * ev: {lesson, type, status, shown, misses, helped, hes, step_s, ride}
 *   status "hint"   a try that wasn't right (the server's miss)        → misses (+ pause when the app hinted early)
 *   status "passed" the step is done                                   → first | helped | shown, secs
 *   status "missed" a check-ride order the world moved past            → shown
 * Anything else ("progress", "ignored", "done", "help") changes nothing.
 */
export function record(store, ev, today = dayOf()) {
  const s = clean(store);
  if (!ev || !ID.test(String(ev.lesson || "")) || UNGRADED.has(ev.type)) return s;
  const st = ev.status;
  if (!["hint", "passed", "missed"].includes(st)) return s;
  const L = s.lessons[ev.lesson] || Object.fromEntries(FIELDS.map(f => [f, 0]));
  if (st === "hint") { L.misses++; if (ev.hes) L.pause++; }
  else {
    L.steps++;
    if (st === "missed" || ev.shown) L.shown++;
    else if (n(ev.misses) === 0 && !ev.helped) L.first++;
    else L.helped++;
    L.secs += Math.min(STEP_CAP_S, n(Math.round(+ev.step_s || 0)));
  }
  s.lessons[ev.lesson] = L;
  if (DAY.test(today) && !s.days.includes(today)) s.days = [...s.days, today].sort().slice(-MAX_DAYS);
  return s;
}

// ---------- localStorage (try/catch: private mode keeps it for this visit only) ----------
const ls = () => { try { return typeof localStorage !== "undefined" ? localStorage : null; } catch (e) { return null; } };
export function load(storage = ls()) {
  try { return clean(JSON.parse((storage && storage.getItem(KEY)) || "null")); } catch (e) { return blank(); }
}
export function save(s, storage = ls()) { try { if (storage) storage.setItem(KEY, JSON.stringify(clean(s))); } catch (e) { /* full or blocked */ } }
export function add(ev, storage = ls(), today = dayOf()) { const s = record(load(storage), ev, today); save(s, storage); return s; }
export function wipe(storage = ls()) { try { if (storage) storage.removeItem(KEY); } catch (e) { /* none */ } }
