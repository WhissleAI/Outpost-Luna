// Flight School (the Academy) UI: home (call sign + Start) → course map (a flight path of patches + one "Next up" card)
// → lesson (CAPCOM's brief, 2–4 steps with voice/type/tap answers, hints after 2 misses) → patch earned. The last stop, the
// check ride, is the cadet's first solo shift in a simplified Outpost Luna cockpit (mission/cockpit.js, mode "mini") on
// the real mission simulator; passing it qualifies the cadet for Mission mode. Grading is server-side
// (POST /api/academy/attempt); progress and the call sign stay on this device. Story copy lives in ../story.js; the few
// UI labels below (UI) are listed in docs/UX_ROUNDS.md for the copy owner.
//
// Steps render through a registry, STEP_RENDERERS[accept.type] = {html(step, ctx) → string, wire?(el, ctx)}, exported
// and attached to window.__outpost.stepRenderers so other modules can register new step types without editing this file.
import { pretendLabel } from "../pretend.js";   // the "pretend tech" mark (shields)
import "../school.css";
import { flowLog } from "../flows.js";   // [flows] a lesson's "continue" is logged like the other flows
import { academyApi, progress, saveStep, clearStep, resumeStep, resumeTarget } from "./client.js";   // [0.4.1] lesson resume
import { sayStyle } from "../floor.js";
import { createCabin } from "../mission/cabin.js";   // [ride] the check ride sits in the real cabin
import { rideInset } from "../mission/ride.js";   // [0.3.12] the ride cabin fits left of the lesson card
import { icon } from "../assets/icons.js";
import { anyPatch as patch, registerClassLessons } from "./class_patch.js";   // Class lessons draw a letter patch (docs/CURRICULUM.md)
import { APP_TAGLINE } from "../brand.js";
import { SCHOOL, LESSON_STORY, CAPCOM, OFFER, CALLSIGNS, CALLSIGN_COPY, CREDIT, PRETEND_BASE, callSign, LESSON_BLURB, TRANSITION, COURSE_DONE, COURSE_CREDIT, HELP, PRETEND_TECH, PRETEND_TECH_TIP, PREP, EXPLORER, FIELD, CLASS } from "../story.js";
import { isAvailable, openVideo, getVideo, watchLabel, catalog as videoCatalog } from "../media/video.js";   // [media] the patch-screen video
import { missionsFlown, unlocked, isExplorer, isField, isBonus, isClass, coreLessons, fieldLessons } from "../explorer.js";   // explorer lessons open after missions; Field School after the ride
import { pinInnerHtml, fieldTrackHtml, classTrackHtml, clusterNudges, clusterOf, regionOf, REGION_DIST } from "./pins.js";   // [0.4.1] numbered pins, a lock on locked ones, the Field School track
import { FIELD_STEP_TYPES as MOON_FIELD_TYPES } from "./field_steps.js";   // [0.5] Field School steps: describe, sequence, rounds
import { ARCH_BUILDUP_TYPES } from "./arch_steps.js";   // [courses] layers and hillshade build up over turns the same way
import { SPEECH_STEP_TYPES } from "./speech_steps.js";   // speech learning steps: read, vocab, summary (docs/SPEECH_LEARNING.md)
const FIELD_STEP_TYPES = [...MOON_FIELD_TYPES, ...ARCH_BUILDUP_TYPES, ...SPEECH_STEP_TYPES];
import { image as viewImage, onViews } from "../media/nasa_views.js";   // [0.5] a lesson's NASA photo hook (optional pack)
import { marks, doLine, helpLine, introFor, introText, prepPlace, prepVideos, firstUse, needsTurn } from "./guide.js";
import { earnedPatches, patchStripHtml } from "./earned.js";   // the map header's earned patches (always in view)
import { courseState, courseLabel, setRoles, roleName, REMOVED_KEY, REMOVED_COPY } from "../courses.js";
import { options as pickOptions, shouldOffer as offerPick, mountPick, WELCOME_KEY } from "../course_pick.js";   // [courses] the first-run course pick
/** The camera gestures are on (gesture/ui.js): the do-lines say the gesture. */
const gesturesOn = () => { try { return !!(window.__outpost && window.__outpost.gestures && window.__outpost.gestures.active); } catch (e) { return false; } };
import { runDirective, GLOBE_STEP_TYPES } from "./globe_steps.js";   // guidance: docs/PLAYTEST.md
import { stepWord as videoStepWord } from "../media/video_ui.js";   // [media] the video step (docs/MEDIA.md)

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const src = s => s && s.url ? `<a class="chip-src" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : "";
const NEXT_WORDS = /^(next|next one|continue|go on|ok|okay|ready|let s go|lets go|start|yes)\b/;
/** UI labels (not story copy). Copy requests: docs/UX_ROUNDS.md. */
/** [courses] The Moon (course #1) keeps every line as it was; another course gets its own words (courses.js labels). */
const moonCourse = () => !courseState.active || courseState.active === "moon";
/** [arch QA] The learner's name when no call sign is spoken: "cadet" on the Moon; another course says nothing
 *  ("Here we go.", never "Here we go, cadet."). cap: the sentence-start form. */
const learner = (cap = false) => (moonCourse() ? (cap ? "Cadet" : "cadet") : "");
const UI = {
  begin: "Start", start: SCHOOL.start, cont: SCHOOL.continue, replay2: "Replay", next: "Next", map: "Map", replay: "Hear it again", brief: "Brief",
  get facts() { return moonCourse() ? "NASA facts" : "Facts"; },   // [courses] another course's facts aren't NASA's
  nextUp: SCHOOL.next, lesson: (n, of) => `Lesson ${n} of ${of}`, step: (n, of) => `Step ${n} of ${of}`, min: SCHOOL.minutes,
  patches: SCHOOL.progress, qualified: "Qualified", retry: "Fly it again", shuffle: CALLSIGN_COPY.random,
  callsign: CALLSIGN_COPY.edit, ride: "Check ride", commander: SCHOOL.go,
  get patchEarned() { const w = courseLabel("patch", "patch"); return `${w.charAt(0).toUpperCase()}${w.slice(1)} earned`; },   // [courses] the course's word
  patchNext: "Get your patch", bonus: "Bonus patch",
  resumed: n => `Picking up at step ${n}.`,   // [0.4.1] a half-done lesson reopened
  tryAgain: "Try again",   // [arch QA] a decide step's other call: think again before moving on
};
/** Where each lesson sits on the Moon, when course.json doesn't say (a lesson's `place`: {name, lat, lon} or a place
 *  id from /api/places wins). The route runs from the near side down to the south-pole outpost, where the check ride
 *  (and then the Mission) happens. Close stops are pushed apart on screen by the globe (route layer). */
const LESSON_PLACE = {
  moon: { name: "Sea of Rains", lat: 32.8, lon: -15.6 },
  comms: { name: "Tranquility Base", lat: 0.67, lon: 23.47 },
  words: { name: "Aristarchus Plateau", lat: 26, lon: -51 },
  history: { name: "Surveyor 3 · Apollo 12", lat: -3.02, lon: -23.42 },
  power: { name: "Malapert Massif", lat: -85.98, lon: -1.67 },
  radiation: { name: "de Gerlache Rim", lat: -88.71, lon: -68.7 },
  life: { name: "Cabeus · LCROSS", lat: -84.68, lon: -48.73 },
  checkride: { name: "Outpost Luna · Connecting Ridge", lat: -89.44, lon: -141.8 },
};
/** Cockpit orders a kid can tap on a command step (each is sent as the words, so voice and tap grade the same way). */
const ORDERS = [["heater", "Heaters up", "more power to the heaters"], ["shield", "Shields up", "more power to the shields"],
  ["shelter", "Into the shelter", "everyone into the shelter"], ["leave", "Leave the shelter", "leave the shelter"], ["rover", "Rover: get ice", "send the rover for ice"],
  ["call", "Call Houston", "houston, any space weather?"]];

/** The step registry. ctx: {L, i, answer(input, btn), esc, clip, done, stop} */
export const STEP_RENDERERS = {
  choice: {
    html: (st) => `<div class="a-choices">${st.accept.options.map((o, k) => `<button type="button" class="a-choice" data-c="${esc(o.id)}"><span class="a-key" data-n="${k + 1}" aria-hidden="true">${"ABCD"[k]}</span><span>${esc(o.label)}</span></button>`).join("")}</div>`,
    wire: (el, ctx) => el.querySelectorAll(".a-choice").forEach(b => b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)),
  },
  // [arch QA] a word step has no buttons: one points at the voice bar's field, so a novice sees where to type
  keywords: {
    html: () => `<button type="button" class="btn-quiet a-typeit">${icon("keyboard", { size: 16 })}<span>Type your answer</span></button>`,
    wire: el => { const b = el.querySelector(".a-typeit"); if (b) b.onclick = () => { const q = document.getElementById("q"); if (q) q.focus(); }; },
  },
  tap: { html: () => "" },
  intent: { html: () => "" },
  command: {
    html: () => `<div class="a-orders" role="group" aria-label="Orders">${ORDERS.map(([ico, label, words]) => `<button type="button" class="a-order" data-say="${esc(words)}">${icon(ico, { size: 18 })}<span>${ico === "shield" ? pretendLabel(label) : esc(label)}</span></button>`).join("")}</div>`,
    wire: (el, ctx) => el.querySelectorAll(".a-order").forEach(b => b.onclick = () => ctx.answer({ text: b.dataset.say }, b)),
  },
};
try {   // share one registry: keep anything registered before this module loaded (e.g. academy/vocab.js)
  const O = (window.__outpost = window.__outpost || {});
  Object.keys(O.stepRenderers || {}).forEach(k => { if (!(k in STEP_RENDERERS)) STEP_RENDERERS[k] = O.stepRenderers[k]; });
  O.stepRenderers = STEP_RENDERERS;
} catch (e) { /* no window (tests) */ }

/**
 * @param {object} o
 * @param {object} o.globe       globe.js instance
 * @param {(id:string)=>object} o.placeById
 * @param {(text:string, style?)=>Promise} o.say    speak as CAPCOM
 * @param {object} o.player      crew player (lesson clips)
 * @param {()=>void} o.alertSound
 * @param {()=>void} o.goMission  switch to Mission mode (site briefing)
 * @param {(p:object)=>void} o.onProgress  progress changed (badges / qualified)
 */
export function createAcademyUI({ globe, placeById, say, player, alertSound = () => {}, stop = () => {}, goMission = () => {}, openLibrary = () => {}, onProgress = () => {} }) {
  const panel = document.getElementById("aPanel");
  let course = null, prog = progress.load(), view = "off", L = null, i = 0, misses = 0, waitingNext = false, busy = false, typedTurn = false;
  let stepKey = "", stepAt = 0;   // which step is open and since when (render() stamps it): the reveal waits ~20 s
  const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());
  // [0.6] hesitation (docs/LEARNING_DESIGN.md §13): the session flags a heard turn with fillers or a long pause
  // (`heard.hes`, just before the answer it carries). A miss on that answer gets the next hint rung at once (the
  // server's ladder counts one more miss), once per step. The pause itself is never shown, said or stored; only the
  // count of early hints the app gave (its own action) goes to the Brain's practice counts (brain_store.js "pause").
  const HES_MS = 4000;
  let hesAt = 0;
  const hesUsed = new Set();
  let rideRO = null;   // [0.3.12] the lesson card's width -> the ride cabin's seat view
  let ride = null, rideSite = null, feedback = null, rideEl = null, rideCk = null, nagged = false, stepTap = null;
  let pendingBadge = null, focusPrompt = false;   // the last step's patch waits for Next; Next lands focus on the question
  let booted = false;   // [0.4.1] the first Flight School entry of this launch reopens a half-done lesson at its step
  // guidance (docs/PLAYTEST.md): the hint-ladder rung and what the server said to draw; per-step state that survives
  // a re-render (the route's taps); the first-use intro line for this step
  let gs = { rung: 0 }, stepState = { taps: [] }, intro = null, baseRung = 0;   // baseRung: the glow a step starts with (not a hint)
  const freshStep = () => {
    const st = L && L.steps[i], acc = (st && st.accept) || {};
    // [novice playtest 5] a find-a-place step never tests a place nobody showed: its target already glows (rung 1,
    // no name); help and misses climb to the label, then to "here it is"
    gs = !L || L.ride || !["intent", "tap"].includes(acc.type) || !acc.place || (st.ring || []).includes(acc.place) ? { rung: 0 } : { rung: 1, focus: [acc.place] };
    baseRung = gs.rung || 0;
    if (stepState.rec) clearTimeout(stepState.rec.timer);   // a summary's quiet timer / a read-aloud ends with its step
    if (stepState.aloud && stepState.aloud.off) stepState.aloud.off();
    stepState = { taps: [] }; pendingBadge = null;
    // a terminator step's night side never leaks into the next step or lesson (it re-locks the Sun when it renders)
    if (globe.setSunDir) globe.setSunDir(null);
    const t = acc.type; intro = t && !L.ride && firstUse(t) ? introFor(t, moonCourse()) : null;
  };
  /** Merge a hint reply into the guidance state: help never takes back what the card already shows. */
  const climb = (g, r) => ({ ...g, rung: Math.max(g.rung || 0, r.rung || 0), focus: r.focus || g.focus,
    label: [...new Set([...(g.label || []), ...(r.label || [])])], eliminate: r.eliminate || g.eliminate, cue: r.cue || g.cue,
    answer: r.answer || g.answer, phrase: r.phrase || g.phrase, line_lon: r.line_lon != null ? r.line_lon : g.line_lon,
    label_line: !!(r.label_line || g.label_line), show: !!(r.show || g.show) });
  const ui = {
    active: false, enter, exit, handleText, onTap, onArtifact, get progress() { return prog; },
    screen, nav, answerText,   // hands-free: the session routes every turn (backend/app/turn_router.py)
    hesitant: () => { if (ui.active && view === "lesson" && L && !L.ride) hesAt = now(); },   // [0.6] heard.hes
    editCallSign: () => { if (ui.active) showCallSign(() => showMap(true)); },   // [brain] My Brain's "Change call sign"
    lessons: () => lessons(),  // the course lessons (mission_learning.js: which explorer lesson a mission unlocked)
    /** Earned patches, for the Mission cockpit (mission/patches.js): [{id, name, patch (inline SVG), lesson, track}];
     *  track: "core" (Flight School), "field" (Field School), "explorer" (bonus) or "ride" (the check ride) */
    badges: () => (course ? null : fetchCourse().catch(() => {}), lessons().filter(l => has(l.badge.id))).map(l => ({ id: l.badge.id, name: l.badge.name, lesson: l.id, patch: patch(l.id, { size: 22 }),
      track: l.ride ? "ride" : isField(l) ? "field" : isExplorer(l) ? "explorer" : isClass(l) ? "class" : "core" })),
    has: lessonId => { const l = lessons().find(x => x.id === lessonId); return !!(l && has(l.badge.id)); },
    /** [0.3.12] For Mission's "Fly the check ride": core lessons done / total, the ride's id, and the lesson to fly
     *  next while the ride is not open yet. */
    /** Class packs changed (Settings → For grown-ups → Class lessons): fetch the course again; the map repaints. */
    reloadCourse,
    rideStatus: () => { const c = coreDone(), r = lessons().find(l => l.ride), nx = coreLessons(lessons()).find(l => !has(l.badge.id));
      return { ...c, ride: r ? r.id : null, next: nx ? nx.id : null }; },
  };

  const lessons = () => (course ? course.lessons : []);
  // The course, fetched once. Mission mode asks for the badges before Flight School was ever opened (the app can start
  // in Mission): the first ask fetches the course, and "outpost:patches" (no id: nothing newly earned) repaints the
  // cockpit's patch key when it lands.
  let coursePending = null;
  function fetchCourse() {
    if (course) return Promise.resolve(course);
    return coursePending || (coursePending = academyApi.course().then(c => {
      if (!course) { course = c; registerClassLessons(c.lessons); setRoles(c.roles); }
      try { dispatchEvent(new CustomEvent("outpost:patches", { detail: {} })); } catch (e) { /* tests */ }
      return course;
    }, e => { coursePending = null; throw e; }));
  }
  /** [class] the course again (a teacher saved, imported or removed a Class pack, or started a preview). A lesson on
   *  screen keeps playing; the map repaints with the new pins. */
  function reloadCourse() {
    return academyApi.course().then(c => {
      course = c; coursePending = null; registerClassLessons(c.lessons); setRoles(c.roles);
      try { (window.__outpost = window.__outpost || {}).patchTotal = lessons().filter(l => !isClass(l)).length; } catch (e) { /* tests */ }
      if (ui.active && view === "map") showMap(true);
      try { dispatchEvent(new CustomEvent("outpost:patches", { detail: {} })); } catch (e) { /* tests */ }
      return course;
    });
  }
  try { addEventListener("outpost:class-changed", () => { reloadCourse().catch(() => {}); }); } catch (e) { /* tests */ }
  // [0.5] the pack can land mid-lesson: a photo hook or a rock step then shows the real thing
  try { onViews(() => { if (ui.active && view === "lesson" && L && !L.ride && (L.photo || L.steps.some(x => (x.accept || {}).type === "rounds"))) render(); }); } catch (e) { /* tests */ }
  /** The step that carries the lesson's crew-audio hook: the first one that isn't a video. */
  const hookAt = l => Math.max(0, l.steps.findIndex(x => (x.accept || {}).type !== "video"));
  /** "Lesson n of 6" counts core lessons; the check ride shows "Check ride", an explorer lesson "Explorer". */
  // core lessons only: explorer lessons and the check ride aren't numbered (the patch total still counts every lesson)
  const lessonNo = l => { const ls = coreLessons(lessons()); return { n: ls.indexOf(l) + 1, of: ls.length }; };
  const has = id => prog.badges.includes(id);
  const lessonDone = id => { const x = lessons().find(y => y.id === id); return !!(x && x.badge && has(x.badge.id)); };
  const open = l => unlocked(l, missionsFlown(callSign.get()), prog.qualified, lessonDone);
  const lockedWhen = l => (l.unlock_after === "checkride" ? "checkride" : l.unlock_after_missions);
  /** When a locked lesson opens, in words: a Field School lesson says "Opens after your check ride". */
  const lockedText = l => (isField(l) ? FIELD.lockedTrack : EXPLORER.locked(lockedWhen(l)));
  /** [novice playtest 14] a bonus lesson that opened and isn't flown yet: the map card offers it by name. */
  const newLesson = () => lessons().find(l => isBonus(l) && !isClass(l) && open(l) && !has(l.badge.id)) || null;
  /** [0.5] "Field School 2 of 4" (a Field lesson's place in its own track). */
  const fieldNo = l => { const fs = fieldLessons(lessons()); return { n: fs.indexOf(l) + 1, of: fs.length }; };
  /** The eyebrow over a lesson: its number in the core track, Field School's count, "Bonus lesson", or the ride. */
  const eyebrowOf = l => (l.preview ? `${CLASS.preview} · ${CLASS.eyebrow((l.pack && l.pack.title) || CLASS.name)}` : isClass(l) ? CLASS.eyebrow((l.pack && l.pack.title) || CLASS.name) : l.ride ? UI.ride : isField(l) ? FIELD.eyebrow(fieldNo(l).n, fieldNo(l).of) : isExplorer(l) ? EXPLORER.eyebrow : UI.lesson(lessonNo(l).n, lessonNo(l).of));
  /** [novice playtest 9] one count: the core lessons ("3 of 6"), then the check ride; bonus lessons apart. */
  const coreDone = () => { const c = coreLessons(lessons()); return { n: c.filter(l => has(l.badge.id)).length, of: c.length }; };
  const nextLesson = () => lessons().find(l => !l.preview && !has(l.badge.id) && open(l)) || null;
  const speakLine = (t, r) => { if (t) say(t, sayStyle(r)); };   // r: the attempt response; its say.style steers
  /** Panel layout for this view. The Moon is always the backdrop: home and map are overlays on it, lesson / patch /
   *  ride are glass cards. The route pins live only on the map; the place dots only on steps that ask for a tap. */
  function setLayout(kind) {
    panel.className = "apanel is-" + kind;
    document.body.dataset.aview = kind;
    if (kind !== "map") { globe.route.clear(); globe.setViewport(null); }
    // a lesson's place name never outlives it (novice playtest #31: "Shackleton (south pole)" stayed as a label)
    if (kind !== "lesson" && kind !== "ride" && globe.clearHighlight) globe.clearHighlight();
    if (kind !== "lesson" && kind !== "ride" && globe.setSunDir) globe.setSunDir(null);
    if (globe.guide) globe.guide.clear();
    globe.setDecor(false);   // no unlabelled place dots in Flight School: a step draws only its own labelled marks
  }

  async function enter() {
    ui.active = true; panel.hidden = false;
    if (!course) {
      setLayout("map"); panel.innerHTML = `<p class="a-wait">Loading ${esc(SCHOOL.eyebrow)}…</p>`;
      // [audit2] the course failing once was a dead end ("Close the app and open it again"): keep trying, like the Moon does
      for (let tries = 0; !course; tries++) {
        try { course = await fetchCourse(); }
        catch (e) {
          if (!ui.active) return;
          if (!tries) panel.innerHTML = `<p class="a-wait is-error"><b>Can&rsquo;t reach ${esc(SCHOOL.eyebrow)}</b><span>Trying again. If this stays, close the app and open it again.</span></p>`;
          await new Promise(res => setTimeout(res, 3000));
          if (!ui.active) return;
        }
      }
    }
    if (!ui.active) return;
    try { (window.__outpost = window.__outpost || {}).patchTotal = lessons().filter(l => !isClass(l)).length; } catch (e) { /* tests */ }   // NASA patches only
    if (resume()) return;
    // [courses] the pick was open when the kid left Flight School: it comes back (a choice is never made for them)
    if (pickPending && callSign.get()) { view = "callsign"; afterCallSign(callSign.spoken(learner(true))); return; }
    // [arch QA] the reload after the playing course was removed (Course storage): the map says so, once
    let gone = ""; try { gone = sessionStorage.getItem(REMOVED_KEY) || ""; if (gone) sessionStorage.removeItem(REMOVED_KEY); } catch (e) { /* */ }
    if (gone && callSign.get()) {
      booted = true; showMap(true);
      const left = panel.querySelector(".mp-left");
      if (left) left.insertAdjacentHTML("afterbegin", `<p class="mp-beat mp-notice" role="status">${esc(REMOVED_COPY(gone))}</p>`);
      say(REMOVED_COPY(gone).split(" Get it again")[0], { situation: "badge" });
      return;
    }
    // [courses] the reload after the first-run pick switched course: the welcome, on the new course's map
    let fresh = false; try { fresh = sessionStorage.getItem(WELCOME_KEY) === "1"; if (fresh) sessionStorage.removeItem(WELCOME_KEY); } catch (e) { /* */ }
    if (fresh && callSign.get()) { booted = true; welcome(callSign.spoken(learner(true))); return; }
    // [0.4.1] reopening the app: a half-done lesson comes back at its step (academy/client.js resumeTarget)
    if (!booted) {
      booted = true;
      const t = callSign.get() ? resumeTarget(prog, lessons()) : null;
      if (t && open(t.lesson)) { openLesson(t.lesson.id); return; }
    }
    showMap();
  }
  /** [0.4.1] Remember the step on screen (progress storage), so the app can reopen the lesson there. */
  function rememberStep() {
    if (!L || L.ride || L.preview) return;
    const np = saveStep(prog, L, i);
    if (np.current !== (prog.current || null) || JSON.stringify(np.steps) !== JSON.stringify(prog.steps || {})) { prog = np; progress.save(prog); }
  }
  function forgetStep(id) { if (!id || !((prog.steps || {})[id] || prog.current === id)) return; prog = clearStep(prog, id); progress.save(prog); }
  // Switching mode (Mission, Library) suspends the lesson; coming back to Flight School resumes it at the same step,
  // with the same answer state. The check ride lives in the cabin and is not suspended (it restarts from the map).
  let suspended = null;
  function exit() {
    if (!ui.active) { panel.hidden = true; return; }   // already suspended (Mission → Library): keep the lesson
    suspended =view === "lesson" && L && !L.ride ? { L, i, misses, waitingNext, feedback, nagged, stepKey, stepAt, gs, stepState, intro, pendingBadge } : null;
    ui.active = false; view = "off"; panel.hidden = true; busy = false;
    if (picker) { picker.destroy(); picker = null; }
    endRide(); leaveCatalog(); globe.route.clear(); globe.setViewport(null); if (globe.guide) globe.guide.clear();
  }
  function resume() {
    const s = suspended; suspended = null;
    if (!s || !lessons().includes(s.L)) return false;
    ({ L, i, misses, waitingNext, feedback, nagged, stepKey, stepAt, gs, stepState, intro, pendingBadge } = s);
    stepState.directed = false;   // the step's camera move runs again
    view = "lesson";
    const st = L.steps[i], f = st && st.accept && (st.accept.place ? placeById(st.accept.place) : null);
    if (f) globe.showFeature(f); else { const at = placeOf(L); globe.flyTo(at.lat, at.lon, 2.6); }
    render();
    return true;
  }

  // ---------- home: what this is, a call sign, one Start ----------
  const shuffled = () => [...CALLSIGNS].sort(() => Math.random() - .5);
  let csDeck = shuffled(), csTyped = null;
  function showCallSign(back, reshuffled) {
    // [courses playtest] another course's call-sign screen is its own: its name and program, its region on the globe and
    // its imagery credit (it said "Junior Astronaut Mission Trainer / Nobody's landed at the pole yet" over Africa)
    const region = mapRegion(), info = courseState.info || {};
    view = "callsign"; setLayout("home");
    if (!reshuffled) { if (region) globe.flyTo(region.lat, region.lon, region.dist); else globe.flyTo(-20, 10, 3.2); }
    const cur = callSign.get(), pick = (!reshuffled && cur) || csDeck[0];
    const hero = moonCourse() ? { eyebrow: APP_TAGLINE, lines: [SCHOOL.hero, SCHOOL.hero2] }
      : { eyebrow: [info.title, info.grades ? `grades ${info.grades}` : ""].filter(Boolean).join(" · "),
          lines: [info.program || info.title || "", `${courseLabel("school", "Field School")} starts here.`].filter(Boolean) };
    panel.innerHTML = `
      <div class="h-wrap">
        <div class="h-copy">
          <p class="eyebrow">${esc(hero.eyebrow)}</p>
          <h1 class="h-title">${hero.lines.map(esc).join("<br>")}</h1>
        </div>
        <form class="h-form" id="aCsForm">
          <label class="h-label" for="aCsIn">${esc(CALLSIGN_COPY.title)}</label>
          <div class="h-field">
            <input id="aCsIn" maxlength="18" autocomplete="off" value="${esc(pick)}" aria-describedby="aCsHelp">
            <button type="button" class="btn-icon" id="aCsRand" aria-label="${esc(UI.shuffle)}" title="${esc(UI.shuffle)}">${icon("random")}</button>
          </div>
          <div class="h-chips" role="group" aria-label="${esc(CALLSIGN_COPY.title)}">${csDeck.slice(0, 3).map(c => `<button type="button" class="chip a-csb" aria-pressed="${c === pick}" data-cs="${esc(c)}">${esc(c)}</button>`).join("")}</div>
          <p class="sr-only" id="aCsHelp">${esc(CALLSIGN_COPY.sub)}</p>
          <p class="h-err" id="aCsErr" role="status" hidden></p>
          <button type="submit" class="btn-primary h-start" id="aCsGo">${esc(back ? CALLSIGN_COPY.save : UI.begin)}${icon("chevron-right")}</button>
        </form>
        <p class="h-credit">${esc(mapCredit())}</p>
      </div>`;
    const input = panel.querySelector("#aCsIn");
    const err = panel.querySelector("#aCsErr");
    // [audit2] an empty Start used to do nothing at all: say what's missing, on the card
    const done = v => { if (!callSign.set(v)) { err.textContent = CALLSIGN_COPY.empty; err.hidden = false; input.focus(); return; } const cs = callSign.spoken(learner(true)); if (back) { say(CALLSIGN_COPY.saved(cs), { situation: "badge" }); back(); } else afterCallSign(cs); };
    const select = v => { input.value = v; err.hidden = true; panel.querySelectorAll(".a-csb").forEach(b => b.setAttribute("aria-pressed", b.dataset.cs === v)); };
    panel.querySelectorAll(".a-csb").forEach(b => b.onclick = () => select(b.dataset.cs));
    input.addEventListener("input", () => select(input.value));
    csTyped = t => { select(t.slice(0, 18)); input.focus(); };   // [audit2] a name typed in the voice bar lands in the field
    panel.querySelector("#aCsForm").onsubmit = e => { e.preventDefault(); done(input.value); };
    // Shuffle deals six new call signs and suggests the first ("surprise me" by voice picks one and goes: handleText).
    panel.querySelector("#aCsRand").onclick = () => { csDeck = shuffled(); showCallSign(back, true); panel.querySelector("#aCsRand").focus(); };
    if (!back && !reshuffled) say(CALLSIGN_COPY.say, { situation: "lesson_brief" });
    if (!back) pickList = loadPickList();   // [courses] the course pick's catalog, ready by the time Start is pressed
  }

  // ---------- [courses] the first-run course pick (course_pick.js): after the call sign, before the welcome ----------
  let pickList = null, picker = null, pickPending = false;
  /** The pick's options when this cadet gets the pick, else null (a course already stored, only the Moon, no backend). */
  function loadPickList() {
    if (typeof fetch !== "function") return Promise.resolve(null);
    const t = new Promise(res => setTimeout(() => res(null), 2500));   // never hold the welcome up for a slow backend
    return Promise.race([t, fetch("/api/courses/packs").then(r => (r.ok ? r.json() : null)).catch(() => null)])
      .then(d => { if (!d) return null; const o = pickOptions(d, courseState.courses); return offerPick(o, localStorage) ? o : null; })
      .catch(() => null);
  }
  async function afterCallSign(cs) {
    if (view !== "callsign") return;
    view = "coursewait";
    const opts = await (pickList || loadPickList());
    if (view !== "coursewait") return;
    if (!opts) { welcome(cs); return; }
    view = "coursepick"; setLayout("home"); pickPending = true;
    picker = mountPick(panel, { opts, eyebrow: APP_TAGLINE, say: (t, o) => say(t, o || { situation: "lesson_brief" }),
      onDone: () => { picker = null; pickPending = false; welcome(callSign.spoken(learner(true))); } });
  }

  /** First launch -> map: the welcome, where you are on the story, and the first offer (each its own short line). */
  function welcome(cs) {
    showMap(true);
    say([cs ? `Copy that, ${cs}. Welcome to ${TRANSITION.firstMap.where}.` : `Welcome to ${TRANSITION.firstMap.where}.`, TRANSITION.firstMap.say, OFFER.firstLesson], { situation: "badge" });   // one on-air span
  }
  /** "What do I do?" outside a lesson (the router's help; lessons keep their own hint ladder). */
  function whatNow() {
    if (!ui.active) return null;
    if (view === "callsign") return HELP.callsign;
    if (view === "coursepick" && picker) return picker.help();
    if (view === "map") return help();   // [audit2] names the button the card really shows
    if (view === "badge") return prog.qualified ? HELP.mapQualified : HELP.patch;
    return null;
  }

  // ---------- course map = the Moon: each lesson is a pin on a real place, the route ends at the south-pole outpost ----------
  /** Lessons in the order the map shows them (track by track), so the numbers read 1, 2, 3… along the route. */
  const shownOrder = () => lessons().filter(l => !l.preview);   // course.json is in map order (near side first, then the pole); Class lessons after; a preview never shows
  let mapSel = null;   // the pin the cadet tapped (null = the next lesson)
  /** A lesson's place on the Moon: course data first, then the fallback table. */
  function placeOf(l) {
    const p = l && l.place;
    // [courses] a lesson's `site` (course.json: "Cliff Palace", "Long House") names the spot inside its park; the pin
    // stays at the park's published point (docs/COURSES.md §1.5 rule 1: park-level places only, never a site's coordinates)
    const site = l && typeof l.site === "string" && l.site.trim() ? l.site.trim() : "";
    if (p && typeof p === "object" && p.lat != null) return { name: site || p.name || "", park: p.name || "", lat: +p.lat, lon: +p.lon };
    if (typeof p === "string") { const f = placeById(p); if (f) return { name: site || f.name.split(" (")[0], park: f.name.split(" (")[0], lat: f.lat, lon: f.lon }; }
    return (l && LESSON_PLACE[l.id]) || LESSON_PLACE.moon;
  }
  /** [courses] A non-Moon course's lesson map: its region, close (pins.js regionOf), or null (the whole-globe view). */
  function mapRegion() { return moonGlobe() ? null : regionOf(lessons().map(placeOf)); }
  /** [courses] The globe is the Moon (its polar route layout and NASA credit stay exactly as they were). */
  function moonGlobe() { const g = courseState.info && courseState.info.globe; return moonCourse() || !g || !g.body || g.body === "moon"; }
  /** The map's small print: the Moon's NASA / pretend-outpost line; another globe credits its own imagery (or nothing). */
  function mapCredit() { return moonGlobe() ? `${CREDIT} ${PRETEND_BASE}` : (COURSE_CREDIT[courseState.info.globe.body] || ""); }
  /** The patch screen's count. "then your check ride" only in a course that has one. */
  function patchProgressLine() { const c = coreDone(); return lessons().some(l => l.ride) ? TRANSITION.patchProgress(c.n, c.of) : COURSE_DONE.progress(c.n, c.of); }
  /** A pin (or its patch in the header strip) tapped: select it and fly there; a second tap opens it. */
  function pickPin(l, sel) {
    if (sel && sel.id === l.id) { openLesson(l.id); return; }
    const at = placeOf(l); mapSel = l.id; showMap(true);
    if (!mapRegion()) globe.flyTo(at.lat, at.lon, 2.6);   // [courses] a regional map stays put: every pin is already in view
  }
  function showMap(quiet) {
    if (!callSign.get()) return showCallSign();
    view = "map"; L = null; endRide(); setLayout("map");
    const ls = shownOrder(), nx = nextLesson(), n = ls.filter(l => has(l.badge.id)).length, cs = callSign.shown();
    const sel = (mapSel && ls.find(l => l.id === mapSel)) || nx;
    // the whole route in view, the Moon lifted above the Next-up card and the voice strip
    const H = panel.clientHeight || innerHeight; globe.setViewport(Math.max(.55, (H - 250) / H));
    // face the next stop (a polar one turns the south pole toward the cadet); the done legs stay in view
    // a polar next stop zooms to a ~35° field round the pole so the polar pins spread out; anywhere else, the whole Moon
    // [courses] another course's lessons that share a region: the region, close, so its pins sit round their park
    const region = mapRegion();
    if (region && (!quiet || !mapSel)) globe.flyTo(region.lat, region.lon, region.dist);
    else if (!quiet || !mapSel) { const c = placeOf(sel || ls[0]); const polar = Math.abs(c.lat) > 70; globe.flyTo(polar ? Math.sign(c.lat) * 89 : c.lat, c.lon, polar ? 1.8 : 4.2, polar ? 88 : 75); }
    // pins: earned patch art for done lessons, a grey outline for the rest; the next one is bigger and labelled
    const stops = ls.map((l, k) => {
      const done = has(l.badge.id), next = nx && nx.id === l.id, at = placeOf(l);
      const b = document.createElement("button"); b.type = "button";
      b.className = `pin a-lcard${done ? " is-done" : ""}${next ? " is-next" : ""}${sel && sel.id === l.id ? " is-sel" : ""}`;
      b.dataset.l = l.id;
      const no = l.ride || isBonus(l) ? "" : String(lessonNo(l).n);
      if (!open(l)) b.classList.add("is-locked");   // a locked explorer pin: tap it (or Enter) to read when it opens
      const said = `${no ? no + ". " : ""}${isField(l) ? FIELD.name + ": " : isClass(l) ? CLASS.eyebrow((l.pack && l.pack.title) || CLASS.name) + ": " : ""}${l.title}${done ? `, ${l.badge.name} patch earned` : next ? ", next up" : !open(l) ? `, locked. ${lockedText(l)}` : ""}`;
      b.setAttribute("aria-label", `${said}${/[.!?]$/.test(said) ? "" : "."} ${at.name}${at.park && at.park !== at.name ? `, ${at.park}` : ""}`);   // "Who decides?" not "Who decides?."
      // [0.4.1] the core lesson number always shows on the pin; a locked pin carries a lock
      b.innerHTML = pinInnerHtml({ patchHtml: patch(l.id, { earned: done, size: next ? 64 : 44 }), no, locked: !open(l), title: l.title, esc, lockIcon: icon("lock", { size: 12 }) });
      b.onclick = () => pickPin(l, sel);
      if (isClass(l)) b.classList.add("is-class");
      return { id: l.id, lat: at.lat, lon: at.lon, el: b, done, next: !!next, noLeg: isClass(l) };   // Class pins: no route leg
    });
    // [courses] lessons that share a spot (Archaeology: nine at Mesa Verde) get fixed slots round it, so an earned pin
    // stays where it was lesson after lesson (pins.js clusterNudges). The Moon's route is laid out as it always was.
    // On the regional map only spots closer than ~20 km share slots (Chimney Rock, 105 km off, keeps its own place).
    // [arch QA] and the globe folds a shared spot into one count pin while zoomed out too far for its fan (pins.js fanFits)
    const near = region ? { deg: 0.2, gap: 34 } : undefined, groups = moonGlobe() ? [] : clusterOf(stops, near);
    if (!moonGlobe()) clusterNudges(stops, near).forEach((nd, k) => { if (nd) { stops[k].nudge = nd; stops[k].group = groups[k]; } });
    globe.route.set(stops, n, { cluster: { label: c => SCHOOL.clusterPin(c), onPick: g => (region ? globe.flyTo(region.lat, region.lon, region.dist) : globe.flyTo(g.lat, g.lon, REGION_DIST)) } });
    const k = sel ? ls.indexOf(sel) : -1, selDone = sel && has(sel.badge.id), at = sel && placeOf(sel);
    const cta = ctaFor(sel, nx, n);
    const nl = prog.qualified ? newLesson() : null;
    const card = prog.qualified && (!mapSel || !sel)
      ? `<div class="mp-card"><span class="mp-patch">${patch("checkride", { earned: true, size: 64 })}</span>
          <div class="mp-copy"><p class="eyebrow">${esc(UI.qualified)}</p><h2>${esc(SCHOOL.titleDone(cs))}</h2>
            ${nl ? `<p class="mp-sub mp-new">${icon("star", { size: 16 })}<span><b>${esc(isField(nl) ? FIELD.openTitle : EXPLORER.unlockedTitle)}:</b> ${esc(nl.title)}</span></p>` : ""}</div>
          <div class="mp-actions"><button type="button" class="btn-primary" id="aGoMission">${esc(UI.commander)}${icon("chevron-right")}</button>
          ${nl ? `<button type="button" class="btn" id="aNewLesson" data-l="${esc(nl.id)}">${esc(EXPLORER.open)}</button>` : ""}</div></div>`
      : sel ? `<div class="mp-card"><span class="mp-patch">${patch(sel.id, { earned: selDone, size: 64 })}</span>
          <div class="mp-copy"><p class="eyebrow">${esc(sel === nx && !isField(sel) ? UI.nextUp : eyebrowOf(sel))}${at && at.name ? ` · ${esc(at.name)}` : ""}</p>
            <h2>${esc(sel.title)}</h2><p class="mp-sub">${open(sel) ? "" : `${icon("lock", { size: 14 })} `}${esc(open(sel) ? (LESSON_BLURB[sel.id] || sel.brief) : lockedText(sel))}</p></div>
          ${open(sel) ? `<div class="mp-actions"><button type="button" class="btn-primary" id="aStart" data-l="${esc(sel.id)}">${esc(cta)}${icon("chevron-right")}</button>
          ${sel.prep && has(sel.badge.id) ? `<button type="button" class="btn-quiet" id="aPrepMap" data-l="${esc(sel.id)}">${icon("todo", { size: 16 })}${esc(PREP.open)}</button>` : ""}</div>` : ""}</div>`
      // [courses] a course with no check ride: every lesson done used to leave the map with no card at all
      : !ls.length || moonCourse() ? "" : `<div class="mp-card mp-done"><span class="mp-patch">${patch(ls[ls.length - 1].id, { earned: true, size: 64 })}</span>
          <div class="mp-copy"><p class="eyebrow">${esc(SCHOOL.eyebrow)}</p><h2>${esc(COURSE_DONE.title(n, courseLabel("patches", "patches")))}</h2>
            <p class="mp-sub">${esc(COURSE_DONE.next)}</p></div>
          <div class="mp-actions"><button type="button" class="btn-primary" id="aDoneLib">${esc(COURSE_DONE.library)}${icon("chevron-right")}</button>
            <button type="button" class="btn" id="aDoneBrain">${esc(COURSE_DONE.brain)}</button></div></div>`;
    panel.innerHTML = `
      <header class="mp-top">
        <h1 class="mp-title">${esc(SCHOOL.eyebrow)}</h1>
        <span class="mp-count" aria-label="${esc(SCHOOL.lessonsCount(coreDone().n, coreDone().of))}">${coreDone().n}<small>/${coreDone().of}</small></span>
        ${patchStripHtml(earnedPatches(ls, prog.badges), { patch, esc })}
        <button type="button" class="chip a-csedit" id="aCsEdit" title="My Brain">${icon("astronaut", { size: 16 })}${esc(cs)}</button>
      </header>
      <div class="mp-left">
      ${!prog.qualified && nx ? (n === 0 && !nx.ride
        // [novice playtest 29] the first map: three beats on how it works; then one line on where you are
        ? `<div class="mp-beat mp-intro"><b>${esc(TRANSITION.firstMap.where)} · ${esc(SCHOOL.lessonsCount(0, coreDone().of))}</b><ol>${TRANSITION.firstMap.intro.map(t => `<li>${esc(t)}</li>`).join("")}</ol></div>`
        // [0.3.12] the count only: the Next up card below already names the lesson (it said it twice)
        : `<p class="mp-beat"><b>${esc(nx.ride ? TRANSITION.toRide.where : `${TRANSITION.firstMap.where} · ${SCHOOL.lessonsCount(coreDone().n, coreDone().of)}`)}</b>${nx.ride ? esc(TRANSITION.toRide.line) : ""}</p>`) : ""}
      ${fieldTrackHtml({ qualified: prog.qualified, fieldLessons: fieldLessons(ls), copy: FIELD, esc, lockIcon: icon("lock", { size: 16 }) })}
      ${classTrackHtml({ lessons: ls.filter(isClass), has, copy: CLASS, esc, patch })}
      </div>
      ${card}
      ${mapCredit() ? `<p class="mp-credit">${esc(mapCredit())}</p>` : ""}`;
    // [brain] the cadet chip opens My Brain (brain.js: stars, voice, how the outpost thinks); it has "Change call sign"
    panel.querySelector("#aCsEdit").onclick = () => { const O = window.__outpost || {}; if (O.brain && O.brain.open) O.brain.open(); else showCallSign(() => showMap(true)); };
    // [0.4.1] the earned patches stay in view in the header (the polar view hides the near-side pins: academy/earned.js)
    panel.querySelectorAll(".mp-patchbtn").forEach(pb => pb.onclick = () => { const l = ls.find(x => x.id === pb.dataset.l); if (l) pickPin(l, sel); });
    const go = panel.querySelector("#aGoMission"); if (go) go.onclick = () => goMission();
    // [0.4.1] the locked Field School track: selects its first lesson (the card says when it opens)
    const ft = panel.querySelector("#aFieldTrack"); if (ft) ft.onclick = () => { const l = ls.find(x => x.id === ft.dataset.l); if (l) pickPin(l, sel); };
    // [class] a Class pack's row: selects its next lesson (its pin and card), a second press opens it
    panel.querySelectorAll("[data-class-pack]").forEach(cb => cb.onclick = () => { const l = ls.find(x => x.id === cb.dataset.l); if (l) pickPin(l, sel); });
    const nb = panel.querySelector("#aNewLesson"); if (nb) nb.onclick = () => openLesson(nb.dataset.l);
    const dl = panel.querySelector("#aDoneLib"); if (dl) dl.onclick = () => openLibrary();   // [arch QA] the course is done: what next
    const db = panel.querySelector("#aDoneBrain"); if (db) db.onclick = () => { const O = window.__outpost || {}; if (O.brain && O.brain.open) O.brain.open(); };
    const st = panel.querySelector("#aStart"); if (st) st.onclick = () => openLesson(st.dataset.l);
    const pm = panel.querySelector("#aPrepMap"); if (pm) pm.onclick = () => openLesson(pm.dataset.l, { prep: true });   // Mission prep, from the map
  }
  function leaveCatalog() { mapSel = null; delete document.body.dataset.aview; }
  /** The card's button for a lesson: Replay (done), Fly check ride, Continue (the next one, after the first patch),
   *  or Start lesson. One place, so "what do I do?" names the button the card really shows. */
  function ctaFor(sel, nx, n) { return !sel || !open(sel) ? "" : resumeStep(prog, sel) > 0 ? UI.cont : has(sel.badge.id) ? UI.replay2 : sel.ride ? SCHOOL.ride : sel === nx && n > 0 ? UI.cont : UI.start; }   // [0.4.1] a half-done lesson: Continue

  // ---------- lesson ----------
  async function openLesson(id, { prep = false, step = null } = {}) {
    const want = lessons().find(l => l.id === id); if (!want) return;
    if (!open(want)) { mapSel = want.id; showMap(true); say(want.unlock_after === "checkride" ? EXPLORER.lockedSayRide : EXPLORER.lockedSay); return; }   // an explorer lesson, still locked
    L = want; booted = true;
    // [0.4.1] a half-done lesson picks up at its step
    view = "lesson"; i = L.ride ? 0 : resumeStep(prog, L); misses = 0; waitingNext = false; feedback = null; nagged = false; stepKey = ""; leaveCatalog(); freshStep();
    if (!L.ride && Number.isInteger(step) && step > 0 && L.steps[step]) { i = step; freshStep(); }   // [D5] a concept's review opens at its step
    try { dispatchEvent(new CustomEvent("outpost:lesson", { detail: { id } })); } catch (e) { /* tests */ }   // main.js closes a stale answer card
    endRide();
    if (L.ride) {
      try { ride = await academyApi.ride(); } catch (e) { ride = null; }
      await showRideSite();
    } else if (L.bridge === "moon" && !moonGlobe() && globe.bridgeFrom) {
      // [arch QA] the Moon <-> Earth bridge (LESSONS.md, DEMO.md): the Moon, then Earth, then the lesson's place
      const at = placeOf(L), me = L;
      globe.flyTo(at.lat, at.lon, 3.6);
      globe.bridgeFrom().then(() => { if (L === me && view === "lesson") globe.flyTo(at.lat, at.lon, REGION_DIST); });
    } else if (L.globe) {
      const f = L.globe.place && placeById(L.globe.place);
      if (f) globe.showFeature(f, { dist: L.globe.dist }); else if (L.globe.lat != null) globe.flyTo(L.globe.lat, L.globe.lon, L.globe.dist || 3.6);
    } else { const at = placeOf(L); globe.flyTo(at.lat, at.lon, moonGlobe() ? 2.6 : REGION_DIST); }   // [arch QA] Earth: fly to the lesson's place
    // [novice playtest 8] the home activity is optional: only when asked for (the map card's or the patch's "Try it at
    // home"), never a gate before the lesson
    if (L.prep && !L.ride && prep) { showPrep(); return; }
    beginLesson();
  }
  /** The lesson proper: its card, then hello + brief + the first question as one say. */
  function beginLesson() {
    view = "lesson";
    render();
    const beat = (LESSON_STORY[L.id] || {}).beat || "";
    // Three short lines, not one long one (the spoken limit is about 20 words a line): hello, the brief, the question.
    // They are ONE say (a list of lines): one on-air span, so the ear's hard mute has no gap between them (a gap let
    // room chatter and our own echo in as "answers"; docs/HANDSFREE.md). Leaving the lesson stops it (stop()).
    // [0.4.1] a resumed lesson: hello, where it picks up, and that step's question (the brief is on the card)
    const lines = i > 0 ? [CAPCOM.lessonHello(callSign.spoken(learner()), beat), UI.resumed(i + 1), L.steps[i].prompt] : [CAPCOM.lessonHello(callSign.spoken(learner()), beat), L.brief, L.steps[0].prompt];
    say([...lines, ...(intro ? [introText(intro)] : [])], { situation: "lesson_brief" });
    if (L.steps[i].alert) alertSound();
  }

  // ---------- Try it at home: an optional hands-on job (course.json lesson.prep; docs/LEARNING_DESIGN.md) ----------
  // Up to 3 spoken steps, then "We did it!" (voice, thumbs-up, or the button) or "Not now". [novice playtest 8] Never a
  // gate: it opens only from the lesson's map card or its patch screen, and either answer goes back to the map. "I don't
  // have a lamp" gets a way out, never the steps again. The NASA activity is credited in course.json, not on screen.
  const PREP_KEY = "outpost-prep-seen";
  const prepSeen = id => { try { return JSON.parse(localStorage.getItem(PREP_KEY) || "[]").includes(id); } catch (e) { return true; } };
  const markPrep = id => { try { const a = JSON.parse(localStorage.getItem(PREP_KEY) || "[]"); if (!a.includes(id)) a.push(id); localStorage.setItem(PREP_KEY, JSON.stringify(a)); } catch (e) { /* private mode */ } };
  function showPrep() {
    const p = L && L.prep; if (!p) return;
    markPrep(L.id);
    view = "prep"; setLayout("lesson");
    panel.dataset.step = "prep";
    panel.innerHTML = `
      <header class="a-head m-head">
        <button type="button" class="btn-quiet a-back" id="aBack" aria-label="Back to the map">${icon("chevron-left", { size: 18 })}${esc(UI.map)}</button>
        <span class="eyebrow a-where">${esc(PREP.eyebrow)}</span>
      </header>
      <div class="a-body">
        <div class="a-title"><span class="a-patch">${patch(L.id, { earned: has(L.badge.id), size: 44 })}</span><h2 class="m-title">${esc(p.title)}</h2></div>
        <section class="a-step a-prep" aria-live="polite">
          ${p.grown_up ? `<p class="a-prep-tag">${icon("astronaut", { size: 16 })}${esc(PREP.grownUp)}</p>` : ""}
          <ol class="a-prep-steps">${p.steps.map(t => `<li>${esc(t)}</li>`).join("")}</ol>
          <div class="a-prep-videos" id="aPrepVideos" role="group" aria-label="${esc(PREP.watchGroup)}" hidden></div>
          <p class="a-how a-do">${esc(PREP.how)}</p>
        </section>
      </div>
      <footer class="a-foot"><button type="button" class="btn a-prep-skip" id="aPrepSkip" data-intent="no">${esc(PREP.skip)}</button>
        <button type="button" class="btn-primary" id="aPrepDone" data-intent="yes">${icon("check", { size: 18 })}${esc(PREP.done)}</button></footer>`;
    panel.querySelector("#aBack").onclick = () => { stop(); showMap(); };
    panel.querySelector("#aPrepDone").onclick = () => prepDone(true);
    panel.querySelector("#aPrepSkip").onclick = () => prepDone(false);
    panel.querySelector("#aPrepSkip").focus({ preventScroll: true });   // Enter is never a "We did it!" nobody did
    say([PREP.intro, ...(p.grown_up ? [PREP.grownUpSay] : []), ...p.steps], { situation: "lesson_brief" });
    fillPrepVideos(p);
  }
  /** [diy videos] "Watch how": the catalog's videos for this task (entry.prep === task id), NASA first, each shown only
   *  when it can play now (online: never a dead button). A non-NASA video says whose it is and "Not from NASA". */
  let prepVideoIds = [];
  async function fillPrepVideos(p, { where = "prep", nasaOnly = false } = {}) {
    prepVideoIds = [];
    const box = panel.querySelector("#aPrepVideos"); if (!box) return;
    let list = [];
    try { list = prepVideos(await videoCatalog(), p.id, { nasaOnly }); } catch (e) { return; }
    // all at once (one slow check never holds the others back)
    const st = await Promise.all(list.map(v => isAvailable(v.id)));
    const ok = list.filter((v, k) => st[k] !== "offline");
    if (!box.isConnected || view !== where || !ok.length) return;
    prepVideoIds = ok.map(v => v.id);
    box.innerHTML = ok.map(v => `<button type="button" class="btn a-prep-video" data-v="${esc(v.id)}">${icon("play", { size: 16 })}<span>${esc(PREP.watch)} <small>${esc(watchLabel(v).replace(/^Watch\s*/, ""))}</small></span>
        <small class="a-prep-src">${esc(prepVideoSource(v))}</small></button>`).join("");
    box.hidden = false;
    box.querySelectorAll("[data-v]").forEach(b => b.onclick = () => watchPrepVideo(b.dataset.v));
  }
  function prepVideoSource(v) { return v.nasa === false ? `${v.channel || v.credit} · ${PREP.notNasa}` : (v.channel || v.credit); }
  function watchPrepVideo(id) {
    const vid = id || prepVideoIds[0];
    if (!vid) { say(PREP.noVideo); return false; }
    flowLog({ flow: "prep", event: "video", source: id ? "tap" : "voice" });
    stop(); openVideo(vid, { context: "prep" });
    return true;
  }
  function prepDone(done) {
    if (view !== "prep" || !L) return;
    stop();
    say(done ? PREP.doneSay : PREP.skipSay, { situation: done ? "badge" : "lesson_brief" });
    mapSel = L.id; showMap(true);   // back to the lesson's card: Start lesson (or Replay) is one tap away
  }

  /** [0.5] A lesson's NASA photo hook (course.json lesson.photo, an image of the optional nasa_views pack): the photo
   *  with its credit, or, without the pack, its one-line description (the lesson never waits for it). */
  function photoHook(l) {
    const p = l && l.photo; if (!p) return "";
    const cls = l.step ? "a-photo is-step" : "a-photo";   // [arch QA] a step's picture is shown whole (it is the question)
    const im = p.url ? { url: p.url, source: p.source && p.source.url } : viewImage(p.id), credit = `<a class="chip-src" href="${esc((p.source && p.source.url) || (im && im.source) || "")}" target="_blank" rel="noopener">${esc(p.credit || "NASA")}</a>`;
    return im ? `<figure class="${cls}"><img src="${esc(im.url)}" alt="${esc(p.alt)}" loading="lazy"><figcaption>${esc(p.alt)} ${credit}</figcaption></figure>`
      : `<p class="a-photo-alt">${icon("camera", { size: 16 })}<span>${esc(p.alt)} ${credit}</span></p>`;
  }
  /** The question as shown. A fill-the-blank prompt that quotes its own sentence shows only its lead-in ("Fill the
   *  blank"), because the step draws the sentence itself, with the blank (the full prompt is still spoken). */
  function promptOf(st) {
    const a = st.accept || {}, p = String(st.prompt || "");
    if (a.type === "vocab_fill" && a.sentence && p.includes(a.sentence.slice(0, 16)) && p.includes(":")) return p.split(":")[0].trim();
    return p;
  }
  function render() {
    if (view !== "lesson" || !L) return;
    const st = L.steps[i], acc = st.accept;
    if (stepKey !== L.id + ":" + i) { stepKey = L.id + ":" + i; stepAt = now(); rememberStep(); }
    const clip = st.clip || (i === hookAt(L) ? L.clip : null), clipAfter = !!(clip && clip.when === "after");
    setLayout(L.ride ? "ride" : "lesson");
    panel.dataset.step = acc.type;   // [keys] a Moon step gets the keyboard reticle (input/spatial.js)
    const ctx = { L, i, answer, esc, clip, done: waitingNext };
    // Registry entries are either {html(step, ctx), wire?(el, ctx)} or, for modules like academy/vocab.js,
    // a factory fn({step, acc, answer, esc, say, playCrew, captions}) → {html, bind(el)}.
    const A11 = typeof window !== "undefined" && window.__outpost && window.__outpost.a11y;
    const E = STEP_RENDERERS[acc.type];
    const R = typeof E === "function"
      ? (o => ({ html: () => o.html, wire: el => o.bind && o.bind(el), onTap: o.onTap }))(E({ step: st, acc, answer, esc, say: (t, style) => say(t, style, { repeat: true }) /* step buttons ("hear it"): a deliberate replay */, playCrew: m => player.play(m), captions: A11 ? A11.settings.captions : true, globe, locked: waitingNext, state: stepState, guide: gs, lesson: L, stepIndex: i }))
      : (E || { html: () => "" });
    stepTap = R.onTap || null;   // [learning-v3] globe steps (academy/globe_steps.js) take taps on the Moon
    const firstLook = i === 0 && !waitingNext && !feedback;
    // [video fix 0.3.11] a lesson with a Try-at-home task shows its "Watch how" videos (online only); just buttons, never
    // a gate before the lesson (playtest 8). [0.3.12] Predict before watch: they wait in the Brief until the first
    // answer is in (a video showed how before the guess), then sit under the feedback.
    const prepHere = prepPlace(L, i, waitingNext);
    const how = doLine(st, { gesture: gesturesOn() });
    // [0.3.12] one instruction per step: the first time a kind of step appears its "New" chip says how, in place of the
    // "do this" bullet (it said the same thing twice); the bullet comes back once the chip goes
    const showIntro = !!intro && !waitingNext && !feedback;
    const FB_ICON = { ok: "check", reveal: "explore", shown: "info", progress: "check" };
    const revealSrc = feedback && (feedback.kind === "reveal" || (feedback.kind === "ok" && acc.type === "predict")) && st.reveal && st.reveal.source;
    const fb = feedback ? `<div class="a-feedback is-${feedback.kind}" id="aFeedback" role="status">${FB_ICON[feedback.kind] ? icon(FB_ICON[feedback.kind], { size: 18 }) : ""}<p>${esc(feedback.text)}${revealSrc ? ` ${src(revealSrc)}` : ""}</p></div>` : `<div class="a-feedback" id="aFeedback" role="status"></div>`;
    panel.innerHTML = `
      <header class="a-head m-head">
        <button type="button" class="btn-quiet a-back" id="aBack" aria-label="Back to the map">${icon("chevron-left", { size: 18 })}${esc(UI.map)}</button>
        <span class="eyebrow a-where">${esc(eyebrowOf(L))}<span class="sr-only"> · ${esc(UI.step(i + 1, L.steps.length))}</span></span>
        <span class="a-steps" role="img" aria-label="${esc(UI.step(i + 1, L.steps.length))}">${L.steps.map((_, j) => `<i class="${j < i || (j === i && waitingNext) ? "is-done" : j === i ? "is-now" : ""}"></i>`).join("")}</span>
      </header>
      <div class="a-body">
        <div class="a-title"><span class="a-patch">${patch(L.id, { earned: has(L.badge.id), size: 44 })}</span><h2 class="m-title">${esc(L.title)}</h2>
          ${L.ride && !firstLook ? "" : `<button type="button" class="btn-quiet a-brief-btn" id="aBriefBtn" aria-expanded="false" aria-controls="aBrief">${icon("info", { size: 16 })}${esc(UI.brief)}</button>`}</div>
        ${L.ride && !firstLook ? "" : `<div class="a-brief" id="aBrief" hidden>
          <p>${esc(L.brief)}</p>
          ${prepHere === "brief" ? `<div class="a-prep-videos" id="aPrepVideos" role="group" aria-label="${esc(PREP.watchGroup)}" hidden></div>` : ""}
          <div class="a-row"><button type="button" class="btn-quiet" id="aReplay">${icon("speaker", { size: 16 })}${esc(UI.replay)}</button>
            ${L.library ? `<button type="button" class="btn-quiet" id="aLib">${icon("library", { size: 16 })}${esc(L.library.label)}</button>` : ""}
            ${L.facts && L.facts.length ? `<details class="a-facts"><summary>${esc(isClass(L) ? CLASS.facts : UI.facts)} (${L.facts.length})</summary><ul>${L.facts.map(f => `<li>${esc(f.text)} ${src(f.source)}</li>`).join("")}</ul></details>` : ""}</div></div>`}
        <section class="a-step${st.alert ? " is-alert" : ""}" aria-live="polite">
          ${st.alert ? `<p class="a-alert">${icon("warning", { size: 16 })}<span>Alert</span></p>` : ""}
          ${firstLook && !L.ride ? `<p class="a-lead">${esc(L.brief)}</p>` : ""}
          ${i === hookAt(L) && !waitingNext ? photoHook(L) : ""}
          ${st.photo ? photoHook({ step: true, photo: st.photo.url || !st.photo.file ? st.photo : { ...st.photo, url: `/api/courses/${encodeURIComponent(courseState.active || "moon")}/media/${encodeURIComponent(st.photo.file)}` } }) : ""}
          ${st.quote ? `<blockquote class="a-quote"><p>${esc(st.quote.text)}</p><cite>${esc(st.quote.who)} ${src(st.quote.source)}</cite></blockquote>` : ""}
          <p class="a-prompt" tabindex="-1">${esc(promptOf(st))}</p>
          ${showIntro ? `<p class="a-intro"><b>New</b>${esc(introText(intro))}</p>` : ""}
          ${how && !waitingNext && !showIntro ? `<p class="a-how a-do">${esc(how)}</p>` : ""}
          ${gs.phrase && !waitingNext ? `<p class="a-phrase">Say: &ldquo;${esc(gs.phrase)}&rdquo;</p>` : ""}
          ${clip && clipAfter === waitingNext ? `<button type="button" class="btn a-clip" id="aClip">${icon("play", { size: 16 })}Hear ${esc(clip.who)}</button>${clip.note ? `<p class="a-how a-clipnote">${esc(clip.note)}</p>` : ""}` : ""}
          <div class="a-input${waitingNext ? " is-locked" : ""}" id="aInput">${R.html(st, ctx)}</div>
          ${fb}
          ${prepHere === "step" ? `<div class="a-prep-videos a-prep-start" id="aPrepVideos" role="group" aria-label="${esc(PREP.watchGroup)}" hidden></div>` : ""}

        </section>
        ${ride ? `<div id="aRideSlot"></div>` : ""}
      </div>
      <footer class="a-foot">${waitingNext && stepState.retry ? `<button type="button" class="btn-quiet a-retry" id="aRetry">${esc(UI.tryAgain)}</button>` : ""}${waitingNext ? `<button type="button" class="btn-primary" id="aNext">${esc(pendingBadge ? UI.patchNext : UI.next)}${icon("chevron-right")}</button>` : ""}</footer>`;
    panel.querySelector("#aBack").onclick = () => { stop(); showMap(); };
    const bb = panel.querySelector("#aBriefBtn");
    if (bb) bb.onclick = () => { const b = panel.querySelector("#aBrief"), open = b.hidden; b.hidden = !open; bb.setAttribute("aria-expanded", open); };
    const rp = panel.querySelector("#aReplay"); if (rp) rp.onclick = () => say(L.brief, undefined, { repeat: true });
    const lib = panel.querySelector("#aLib"); if (lib) lib.onclick = () => openLibrary(L.library.place);
    const cb = panel.querySelector("#aClip");
    if (cb) cb.onclick = () => Promise.resolve(clip.note ? say(clip.note) : null)   // frame the clip first ("She means the night side")
      .then(() => player.play({ clip_id: clip.clip_id, t0: clip.t0, t1: clip.t1, speaker: clip.who, places: [], jargon: [] }));
    if (!waitingNext && R.wire) R.wire(panel.querySelector("#aInput"), ctx);
    if (!waitingNext && !stepState.directed && st.globe && !GLOBE_STEP_TYPES.includes(acc.type)) runDirective(globe, st.globe, { target: acc.place || null });
    stepState.directed = true;
    if (waitingNext) lockInput(panel.querySelector("#aInput"));
    const slot = panel.querySelector("#aRideSlot"); if (slot && rideEl) { slot.replaceWith(rideEl); if (ride.state) rideCk.update(ride.state); }
    if (ride && rideCk) { if (ride.state) rideCk.update(ride.state); setTimeout(rideCue, 400); }   // [ride]
    const nb = panel.querySelector("#aNext"); if (nb) { nb.onclick = next; nb.focus({ preventScroll: true }); }
    const rb = panel.querySelector("#aRetry"); if (rb) rb.onclick = retryStep;
    // [novice playtest 12] after Next, focus is on the new question, never on its first answer (one more Enter used
    // to order "Heaters up" in a storm)
    // (a Moon step keeps its own focus: the keyboard's Moon reticle, input/spatial.js)
    else if (focusPrompt && panel.querySelector("#aInput button")) { const q = panel.querySelector(".a-prompt"); if (q) q.focus({ preventScroll: true }); }
    focusPrompt = false;
    if (prepHere) fillPrepVideos(L.prep, { where: "lesson", nasaOnly: !isExplorer(L) });
    applyGuide();
    fitBody();
  }
  /** The card's body scrolls only when it can't fit (school.css): a fade marks the edge with more, and the focused or
   *  picked answer is always scrolled into view (card_clear.py; the owner's answer 3 under the caption). */
  function fitBody() {
    const b = panel.querySelector(".a-body"); if (!b) return;
    const upd = () => { b.classList.toggle("is-more", b.scrollHeight - b.clientHeight - b.scrollTop > 4); b.classList.toggle("is-scrolled", b.scrollTop > 4); };
    b.addEventListener("scroll", upd, { passive: true });
    b.addEventListener("focusin", e => { const t = e.target.closest("button, input, select, [role=option], [tabindex]"); if (t && b.contains(t)) t.scrollIntoView({ block: "nearest" }); });
    requestAnimationFrame(() => {
      const pick = b.querySelector('.a-choice[aria-pressed="true"], .a-choice.is-picked, .a-choice.is-wrong, #aFeedback');
      if (pick && b.scrollHeight > b.clientHeight) pick.scrollIntoView({ block: "nearest" });
      upd();
    });
  }

  // ---------- guidance: the step's marks on the Moon and the hint ladder on the card (docs/PLAYTEST.md) ----------
  const findPlace = id => placeById(id) || (rideSite && rideSite.id === id ? rideSite : null);
  function applyGuide() {
    if (view !== "lesson" || !L || L.ride || !globe.guide) return;
    const st = L.steps[i];
    const ms = marks(st, { ...gs, next: stepState.taps.length, done: waitingNext, after: waitingNext && st.after_place ? [st.after_place] : [] }, findPlace);
    if (!waitingNext && ms.some(m => m.label || m.gold)) globe.clearHighlight();   // one label per place, nothing else named
    globe.guide.set(ms);
    if (waitingNext) return;
    const inp = panel.querySelector("#aInput"); if (!inp) return;
    if (gs.eliminate) { const b = inp.querySelector(`[data-c="${CSS.escape(gs.eliminate)}"]`); if (b) { b.classList.add("is-out"); b.disabled = true; } }
    if (gs.cue) {
      const c = gs.cue, words = c.side ? null : RIDE_WORDS(c);
      const b = c.side ? inp.querySelector(`.g-side[data-c="${CSS.escape(c.side)}"]`) : words && inp.querySelector(`.a-order[data-say="${CSS.escape(words)}"]`);
      if (b) b.classList.add("is-cue");
    }
    if (gs.answer) { const b = inp.querySelector(`[data-c="${CSS.escape(gs.answer)}"]`); if (b) b.classList.add("is-cue"); }   // rung 3: "Here's the answer"
  }
  /** Rung 3 ("show"): the camera goes to what CAPCOM points at, and it stays named on the Moon. */
  function showOnGlobe() {
    const acc = (L && L.steps[i] && L.steps[i].accept) || {};
    if (gs.line_lon != null && acc.type === "terminator") { globe.flyTo(0, gs.line_lon, 3.4); return; }
    const f = (gs.focus || []).map(findPlace).find(Boolean); if (!f) return;
    if (Math.abs(f.lat) > 70) globe.poleView(f.lat > 0 ? "north" : "south", 1.9); else globe.flyTo(f.lat, f.lon, 2.6);
  }
  /** Turn the Moon toward what the hint is about, when it's round the back or on the edge. */
  function turnToFocus(ids) {
    const f = (ids || []).map(findPlace).find(Boolean); if (!f || !globe.project) return;
    if (!needsTurn(f, globe.project)) return;
    if (Math.abs(f.lat) > 70) globe.poleView(f.lat > 0 ? "north" : "south", 2.2); else globe.flyTo(f.lat, f.lon, 3.2);
  }
  /** "What do I do?" (voice, a11y.js): the screen's current hint, said briefly. Also lights rung 1 if nothing shows yet. */
  function help() {
    if (!ui.active) return "";
    if (view === "callsign") return "Pick a call sign, then tap Start.";
    if (view === "map") {
      const nx = nextLesson(), n = lessons().filter(l => has(l.badge.id)).length, sel = (mapSel && lessons().find(l => l.id === mapSel)) || nx;
      if (prog.qualified && (!mapSel || !sel)) return newLesson() ? "Tap Open it for your new lesson, or Take command." : "Tap Take command to run the outpost.";
      return sel ? SCHOOL.mapHelp(ctaFor(sel, nx, n), sel.title, !!sel.ride && !has(sel.badge.id)) : moonCourse() ? "Tap a patch to fly a lesson again." : COURSE_DONE.sub;
    }
    if (view === "badge") return "Tap Next for the next lesson, or Map.";
    if (view === "prep") return PREP.ask;
    if (view !== "lesson" || !L) return "";
    if (waitingNext) return pendingBadge ? `Tap ${UI.patchNext}, or say next.` : "Tap Next, or say next.";
    return climbHelp();
  }
  /** [novice playtest 1] "help", "I don't know", "where is it?" in a step: the NEXT rung of the hint ladder, every
   *  time (highlight, then label, then show), with no miss counted, never the last miss line again. The server
   *  composes the rung (POST /api/academy/hint, guide.help_rung); the card and the Moon show it; the line is returned
   *  for the caller to say (a11y.js awaits it). */
  async function climbHelp() {
    const st = L.steps[i], at = { L, i };
    const fallback = helpLine(doLine(st, { gesture: gesturesOn() }), st.hint);
    let r = null;
    try {
      r = await academyApi.hint({ lesson_id: L.id, step: i, rung: Math.min(3, (gs.rung || 0) + 1),
        got: st.accept.type === "route" || FIELD_STEP_TYPES.includes(st.accept.type) ? (stepState.got || []) : undefined,
        ...(st.accept.type === "vocab" && stepState.plan ? { plan: stepState.plan } : {}) });
    } catch (e) { r = null; }
    if (!ui.active || view !== "lesson" || L !== at.L || i !== at.i || waitingNext) return "";   // moved on meanwhile
    if (!r || !r.say) { feedback = { kind: "help", text: fallback }; render(); return fallback; }
    if (!L.ride) gs = climb(gs, r);
    feedback = { kind: "help", text: r.say };
    render();
    if (r.show) showOnGlobe(); else if (r.focus) turnToFocus(r.focus);
    return r.say;
  }
  /** [novice playtest 1] "what?", "huh?": the step again, simply: what it asks (its last sentence) and how to answer.
   *  Not a rung; "help" climbs. Outside a lesson: the screen's help. */
  function explain() {
    if (!ui.active) return "";
    if (view !== "lesson" || !L || waitingNext) return help();
    const st = L.steps[i], sents = String(promptOf(st)).match(/[^.!?]+[.!?]*/g) || [promptOf(st)];
    const ask = sents[sents.length - 1].trim().replace(/^(CAPCOM:\s*)/, "");
    const line = `${ask} ${doLine(st, { gesture: gesturesOn() })}.`.replace(/\.\.$/, ".");
    feedback = { kind: "help", text: line }; render();
    return line;
  }
  /** [courses playtest] A typed turn that isn't an answer ("dinosaur bones" on a keywords step): the step again, simply,
   *  keeping the hint already on the card ("It starts with arch."). Never a miss. -> the line to say ("" outside a step). */
  function typedNudge() {
    if (!ui.active || view !== "lesson" || !L || waitingNext) return "";
    const prev = feedback && (feedback.kind === "help" || feedback.kind === "retry") ? String(feedback.text || "") : "";
    const line = explain();
    if (prev && !line.includes(prev)) { feedback = { kind: "help", text: `${line} ${prev}` }; render(); }
    return line;
  }
  try { Object.assign((window.__outpost = window.__outpost || {}), { help, explain, typedNudge }); } catch (e) { /* tests */ }

  /** After the answer the step stays on screen, locked: the kid's pick, the right one, and any data the reply carried. */
  function lockInput(el) {
    if (!el || !feedback) return;
    el.querySelectorAll(".a-choice, .a-order, [data-view], [data-reset]").forEach(b => { b.disabled = true; b.tabIndex = -1; });
    const pick = feedback.chosen && el.querySelector(`[data-c="${CSS.escape(feedback.chosen)}"]`);
    if (pick) pick.classList.add(feedback.kind === "ok" ? "is-correct" : "is-picked");
    const right = feedback.right && el.querySelector(`[data-c="${CSS.escape(feedback.right)}"]`);
    if (right) right.classList.add("is-answer");
    if (feedback.data) {   // compare: the step's metric first, then the other numbers
      const metric = (L.steps[i].accept || {}).metric || "sun_days";
      const ROWS = { sun_days: ["sun", "sunny days"], earth_days: ["earth", "days Earth is up"], ice_km: ["ice", "km to ice"] };   // plain words (playtest #26)
      el.querySelectorAll(".g-data").forEach(d => {
        const x = feedback.data[d.dataset.for]; if (!x) return;
        d.innerHTML = [metric, ...Object.keys(ROWS).filter(k => k !== metric)].filter(k => x[k] != null && ROWS[k])
          .map((k, j) => `<span class="${j === 0 ? "is-metric" : ""}">${icon(ROWS[k][0], { size: 14 })}<b>${esc(x[k])}</b> ${ROWS[k][1]}</span>`).join("");
      });
    }
  }
  /** CAPCOM shows the answer (after 3 misses): on the Moon too. */
  function showAnswerOnGlobe(sa) {
    if (!sa) return;
    if (sa.place) { const f = placeById(sa.place); if (f) globe.showFeature(f); }
    if (sa.side) globe.flyTo(0, sa.side === "far" ? 180 : 0, 3.4);
    if (Array.isArray(sa.stops)) {
      const pts = sa.stops.map(placeById).filter(Boolean);
      globe.route.set(pts.map((f, k) => { const e = document.createElement("span"); e.className = "g-tapdot" + (sa.shown ? " is-shown" : ""); e.textContent = String(k + 1); return { id: f.id, lat: f.lat, lon: f.lon, el: e }; }), pts.length);
    }
  }
  async function answer(input, btn) {
    if (busy || view !== "lesson" || waitingNext) return false;
    busy = true; if (btn) btn.classList.add("is-busy");
    const acc0 = L.steps[i].accept;
    if (acc0.type === "route" && !input.taps && !L.ride) input = { ...input, taps: stepState.taps.slice() };   // "...then Ohm" after tapping Orientale
    // [0.5] a Field step builds up: send what counts so far ([0.4.1] the check ride's readback and confirm too)
    const field = FIELD_STEP_TYPES.includes(acc0.type) && (!L.ride || acc0.type === "sequence");
    if (field && !input.got && (stepState.got || []).length) input = { ...input, got: stepState.got.slice() };
    if (acc0.type === "vocab" && stepState.plan && !input.plan) input = { ...input, plan: stepState.plan.slice() };   // spaced repetition order
    let r;
    const step_s = Math.max(0, Math.round((now() - stepAt) / 100) / 10);   // the reveal needs ~20 s (grade.reveal_due)
    const sk = L.id + ":" + i, hes = !L.ride && !!hesAt && now() - hesAt < HES_MS && !hesUsed.has(sk);
    hesAt = 0;
    try { r = await academyApi.attempt({ lesson_id: L.id, step: i, input, misses, step_s, ride_id: ride && ride.ride_id, rung: L.ride ? 0 : Math.min(3, gs.rung || 0), ...(hes ? { hes: true } : {}) }); }
    catch (e) { busy = false; feedback = { kind: "retry", text: "I can't reach CAPCOM right now. Try again." }; render(); return true; }
    busy = false;
    if (hes && r && r.status === "hint") hesUsed.add(sk);   // the one early rung for this step is spent
    // the step's grade, for the opt-in turn log's outcome signals (main.js forwards it to the session; docs/DIRECTOR_LOOP.md)
    // [brain] and the cadet's own practice counts (brain_store.js: ids and counts only, on this device; docs/BRAIN.md)
    try { dispatchEvent(new CustomEvent("outpost:lesson-result", { detail: { status: r.status, step_type: (L.steps[i].accept || {}).type,
      lesson: L.id, shown: !!r.shown, misses, helped: !L.ride && (gs.rung || 0) > baseRung, hes: hes && r.status === "hint", step_s, ride: !!L.ride,
      lesson_id: L.id, reply: r, input, preview: !!L.preview } })); } catch (e) { /* no window */ }   // + speech steps' counts (academy/speech_steps.js)
    if (!ui.active || view !== "lesson") return true;   // the kid switched mode while it was graded: never speak or render
    // not a try (grade.plausible: "Oh, it's", "okay", room talk): no miss, no line, nothing changes on screen
    if (r.status === "ignored") {
      if (btn) btn.classList.remove("is-busy");
      // [courses playtest] typed on purpose ("dinosaurs" on a two-choice guess): say what the step wants, never silence.
      // An open-mic turn stays silent (room talk must never cost a line); a button tap is never ignored.
      if (typedTurn && input && input.text && !btn) { typedTurn = false; const line = typedNudge(); if (line) speakLine(line, null); }
      return true;
    }
    if (r.state && ride) { ride.state = r.state; syncRideGlobe(); }
    if (ride && r.events && r.events.length) ride.events = r.events;
    if (r.status === "progress" && field) {   // [0.5] a Field step: a descriptor, an item or a round counted
      stepState.got = r.got || [];
      misses = 0; gs = { rung: 0 };   // each part gets its own hint ladder (a crossed-out tool belongs to its round)
      feedback = { kind: r.shown ? "shown" : "progress", text: r.say };
      render(); speakLine(r.say, r);
      if (r.shown && r.shown_answer && r.shown_answer.choice) { const b = panel.querySelector(`#aInput [data-c="${CSS.escape(r.shown_answer.choice)}"]`); if (b) b.classList.add("is-answer"); }
      return r;
    }
    if (r.status === "progress") {   // a route stop was right: not a miss, just the next stop
      stepState.taps = (r.got || []).map((id, k) => stepState.taps[k] || (f => f && { lat: f.lat, lon: f.lon })(findPlace(id))).filter(Boolean);
      stepState.got = r.got || [];
      feedback = { kind: "progress", text: r.say }; render(); speakLine(r.say, r); return r;
    }
    if (r.status === "passed" || r.status === "missed" || r.status === "done") {
      if (L.ride) return rideStep(r);
      const acc = L.steps[i].accept, sa = r.shown ? r.shown_answer || {} : null;
      if (field && r.got) stepState.got = r.got;   // [0.5] the locked card shows the whole report / order
      // shown = CAPCOM showed the answer (3 misses); a predict guess is never wrong, it reveals the real number
      const kind = sa ? "shown" : (acc.type === "predict" || acc.type === "video") && r.correct === false ? "reveal" : acc.type === "decide" && r.best === false ? "reveal" : "ok";
      if (acc.type === "decide" && r.law) stepState.law = r.law;   // [courses] the law card stays on the locked step
      // [arch QA] a tree-ring step's shown answer: the beam slides to that year (the bars match on screen)
      { const y = sa && (sa.year != null ? sa.year : sa.choice); if (acc.type === "rings" && y != null && Number.isFinite(+y)) stepState.outer = +y; }
      // [arch QA] a decide step's other call: its reason stays, and "Try again" offers the better call before moving on
      stepState.retry = acc.type === "decide" && r.best === false;
      // a video step's guess chip (novice playtest #7): the kid's guess and the answer light up after the video or Skip
      const vg = acc.type === "video" && r.answer ? { chosen: r.guess || null, right: r.answer } : null;
      feedback = { kind, text: r.say, chosen: vg ? vg.chosen : input && input.choice || (acc.type === "decide" ? r.choice : null), right: vg ? vg.right : sa ? (sa.choice || sa.side) : acc.type === "decide" && r.better ? r.better : null, data: r.data || null };
      // [novice playtest 2] "Here it is" on the day/night step points at the line: drawn, labelled and in view
      if (acc.type === "terminator") gs = { ...gs, line_lon: acc.sun_lon - 90, label_line: true };
      // the reveal on the Moon: the traced route, or the far side turned toward the kid
      const reveal = sa ? { ...sa, shown: true } : acc.type === "route" ? { stops: acc.stops } : acc.type === "globe_side" && acc.want ? { side: acc.want } : null;
      if (acc.type === "intent" || acc.type === "tap") { const f = placeById(acc.place); if (f) globe.showFeature(f); }
      // the last step: the answer stays up to read (a Skip's reveal used to vanish under the patch in 0.9 s); the patch
      // is earned now and shown on Next ("Get your patch")
      if (r.badge) { award(r.badge); pendingBadge = r.badge; speakLine(r.say, r); waitingNext = true; render(); showAnswerOnGlobe(reveal); return true; }
      waitingNext = true; render(); showAnswerOnGlobe(reveal);
      // a crew clip marked "after" plays once the success line is said (it's the reward)
      const st = L.steps[i], c = st.clip || (i === hookAt(L) ? L.clip : null), at = { L, i };
      // QA-71 (the owner's double speech): the success line paraphrases the crew clip that follows it ("Roger. The far
      // side gets sunlight too." then an astronaut saying just that), so one tap said the same thing twice in two
      // voices. With an "after" clip CAPCOM only acknowledges ("Roger.") and the crew tell it; the full line is on the card.
      const after = !!(c && c.when === "after" && !sa);
      const ack = after ? (String(r.say || "").match(/^\s*([^.!?]{1,24}[.!?])/) || [])[1] : null;
      const line = after ? (ack && ack.trim().split(/\s+/).length <= 3 ? ack.trim() : "") : r.say;
      Promise.resolve(line ? say(line, sayStyle(r)) : null).then(() => {
        if (c && c.when === "after" && view === "lesson" && L === at.L && i === at.i && waitingNext) player.play({ clip_id: c.clip_id, t0: c.t0, t1: c.t1, speaker: c.who, places: [], jargon: [] });
      });
      return r;
    }
    misses++;
    feedback = { kind: "retry", text: r.say, hint: r.hint };
    if (!L.ride) {
      // a miss climbs the same ladder as "help", and never takes back what the card already showed
      gs = climb(gs, { rung: r.rung || Math.min(2, misses), focus: r.focus, label: r.label, eliminate: r.eliminate, cue: r.cue, phrase: r.phrase,
        line_lon: r.line_lon, label_line: r.label_line });
      if (acc0.type === "route") { stepState.taps = stepState.taps.slice(0, (r.got || []).length); stepState.got = r.got || []; }
      if (field && r.got) stepState.got = r.got;
    }
    render();
    if (r.focus) turnToFocus(r.focus);
    const again = btn && panel.querySelector(btn.dataset.c ? `.a-choice[data-c="${btn.dataset.c}"]` : `.a-order[data-say="${btn.dataset.say}"]`);
    if (again) again.classList.add("is-wrong");
    speakLine(r.say, r);
    return r;
  }

  /** [arch QA] "Try again" on a decide step's other call: the same step, fresh (the reason was read; nothing counted). */
  function retryStep() {
    if (!waitingNext || !L || L.ride) return;   // (the last step's patch is already earned: answering again keeps it)
    if (player.active) player.stop(true);
    waitingNext = false; feedback = null; misses = 0; nagged = false; stepKey = ""; freshStep(); render();
    say(L.steps[i].prompt, sayStyle());
  }
  function next() {
    if (!waitingNext) return;
    if (pendingBadge) { const b = pendingBadge; pendingBadge = null; stop(); if (player.active) player.stop(true); showBadge(b); return; }
    if (i + 1 >= L.steps.length) { forgetStep(L.id); showMap(); return; }   // never a dead end
    if (player.active) player.stop(true);
    waitingNext = false; feedback = null; misses = 0; nagged = false; i++; freshStep();
    if (globe.setSunDir) globe.setSunDir(null);   // [learning-v3] a terminator step's lighting ends with the step
    focusPrompt = true;
    render();
    // the question, then (first time only) how this kind of step works, then a "Listen to…" step's own crew clip
    const st = L.steps[i], at = { L, i }, here = () => view === "lesson" && L === at.L && i === at.i && !waitingNext;
    const c = st.clip && st.clip.when !== "after" ? st.clip : null;
    Promise.resolve(say(intro ? [st.prompt, introText(intro)] : st.prompt, sayStyle()))   // one say: one on-air span (docs/HANDSFREE.md)
      .then(() => { if (c && here() && /^listen/i.test(st.prompt)) player.play({ clip_id: c.clip_id, t0: c.t0, t1: c.t1, speaker: c.who, places: [], jargon: [] }); });
    if (L.steps[i].alert) alertSound();
  }

  // ---------- check ride: the first solo shift, in a simplified cockpit ----------
  /** [ride] a cabin control → the same words as the order buttons, graded by the same path */
  const RIDE_WORDS = c => c.type === "allocate" ? `more power to the ${String(c.to).replace("_", " ")}` : c.type === "shelter" ? (c.on ? "everyone into the shelter" : "leave the shelter")
    : c.type === "dispatch" ? (c.task === "collect_ice" ? "send the rover for ice" : c.task === "return" ? "bring the rover home" : `send the rover to ${c.task}`) : null;
  async function showRideSite() {
    if (!rideSite) {
      try { const s = await (await fetch("/api/mission/sites")).json(); rideSite = s.sites.find(x => x.id === L.ride.site); } catch (e) { rideSite = null; }
    }
    // [ride] the cabin, full stage behind the lesson card; its controls answer the step like the order buttons do
    rideEl = null; if (rideCk && rideCk.dispose) rideCk.dispose();
    let host = document.getElementById("aRideCabin");
    if (!host) { host = document.createElement("section"); host.id = "aRideCabin"; host.className = "m-cabin a-ridecabin"; host.setAttribute("aria-label", "Check ride cabin"); panel.parentNode.insertBefore(host, panel); }
    host.hidden = false; document.body.dataset.ride = "1";
    // [0.3.12] one cabin across the stage; the part under the lesson card (--ride-inset) is left out of the seat view
    const insetRight = () => rideInset(host, panel);
    host.style.setProperty("--ride-inset", insetRight() + "px");
    if (!rideRO && typeof ResizeObserver !== "undefined") rideRO = new ResizeObserver(() => { const h = document.getElementById("aRideCabin"); if (!h || h.hidden) return;
      h.style.setProperty("--ride-inset", rideInset(h, panel) + "px"); if (rideCk && rideCk.relayout) rideCk.relayout(); });
    if (rideRO) { rideRO.observe(panel); rideRO.observe(host); }
    rideCk = createCabin(host, { mode: "ride", terrain: true, site: rideSite, insetRight, onCommand: c => { const t = RIDE_WORDS(c); if (t && L && L.steps[i] && L.steps[i].accept.type === "command") answer({ text: t }); }, onEndShift() {}, onHouston() {}, onDebrief() {} });
    if (ride && ride.state) rideCk.update(ride.state);
    setTimeout(rideCue, 400);
    if (!rideSite) return;
    globe.mission.enter();
    globe.mission.setSite({ ...rideSite, short: rideSite.name.split(" (")[0] }, { dist: 2.2 });
    syncRideGlobe();
  }
  function syncRideGlobe() {
    if (!ride || !ride.state) return;
    if (rideCk) { rideCk.update(ride.state); rideCue(); }
    if (!rideSite) return;
    const e = ride.state.env;
    globe.mission.setSun(e.sun_elev_deg, ride.state.mission_time_h); globe.mission.setEarth(e.earth_elev_deg);
  }
  function endRide() { if (ride) { ride = null; globe.mission.exit(); } rideEl = null; if (rideCk && rideCk.dispose) rideCk.dispose(); rideCk = null;
    if (rideRO) { rideRO.disconnect(); rideRO = null; }
    const h = document.getElementById("aRideCabin"); if (h) { h.hidden = true; h.innerHTML = ""; } delete document.body.dataset.ride; }
  /** [ride] the step's expected order lights its control in the cabin, one at a time */
  function rideCue() {
    if (!rideCk || !rideCk.cue || !L || !L.steps[i]) return;
    const x = (L.steps[i].accept || {}).expect || {};
    rideCk.cue(x.type === "allocate" ? (x.to === "shields" ? "shields" : `load:${x.to}`) : x.type === "shelter" ? "shelter" : x.type === "dispatch" ? `rover:${x.task}` : null);
  }
  function rideStep(r) {
    if (r.status === "done") {
      feedback = { kind: r.passed ? "ok" : "retry", text: r.say };
      if (r.passed && r.badge) { award(r.badge, true); waitingNext = true; render(); speakLine(r.say, r); setTimeout(() => showBadge(r.badge, true), 1200); return true; }
      waitingNext = false; render(); speakLine(r.say, r);
      const inp = panel.querySelector("#aInput"); inp.innerHTML = `<button type="button" class="btn-primary" id="aRetry">${icon("retry")}${esc(UI.retry)}</button>`;
      panel.querySelector("#aRetry").onclick = () => openLesson(L.id);
      return true;
    }
    feedback = { kind: r.status === "passed" ? "ok" : "retry", text: r.say + (r.sim_say ? " " + r.sim_say : "") };
    waitingNext = true; misses = 0; render(); speakLine(r.say, r);
    return true;
  }

  // ---------- patches ----------
  function award(badge, qualifies) {
    if (L && L.preview) return;            // [class] a teacher's preview earns nothing and saves nothing
    if (L) prog = clearStep(prog, L.id);   // [0.4.1] a finished lesson starts from the top next time
    if (!prog.badges.includes(badge.id)) prog.badges.push(badge.id);
    if (qualifies) prog.qualified = true;
    progress.save(prog); onProgress(prog);
    // the Mission cockpit's patch key repaints at once (mission/cabin.js paintPatches), even while the cabin is up
    try { dispatchEvent(new CustomEvent("outpost:patches", { detail: { id: badge.id } })); } catch (e) { /* tests */ }
  }
  function showBadge(badge, commander) {
    if (view !== "lesson") return;
    view = "badge"; setLayout("badge");
    const nx = nextLesson(), cs = callSign.shown();
    panel.innerHTML = `
      <div class="a-badge" role="status">
        <span class="a-bigpatch">${patch(L.id, { earned: true, size: 168 })}</span>
        <p class="eyebrow">${esc(commander ? UI.qualified : UI.patchEarned)}</p>
        <h2 class="m-title">${esc(badge.name)}</h2>
        <p class="a-badge-sub">${commander ? esc(TRANSITION.qualified.line) : isField(L) ? esc(FIELD.patchProgress(fieldLessons(lessons()).filter(l => has(l.badge.id)).length, fieldNo(L).of)) : isExplorer(L) ? esc(TRANSITION.bonusPatch) : isClass(L) ? esc(L.preview ? CLASS.previewNote : CLASS.patch) : esc(patchProgressLine())}</p>
        <div class="a-actions">
          ${commander ? `<button type="button" class="btn-primary" id="aGoMission">${esc(UI.commander)}${icon("chevron-right")}</button>`
            : nx ? `<button type="button" class="btn-primary" id="aNextLesson">${esc(UI.next)}: ${esc(nx.ride ? UI.ride : nx.title)}${icon("chevron-right")}</button>` : ""}
          <button type="button" class="btn-quiet" id="aMap">${icon("map", { size: 16 })}${esc(UI.map)}</button>
          ${L.prep ? `<button type="button" class="btn-quiet" id="aPrepBadge">${icon("todo", { size: 16 })}${esc(PREP.open)}: ${esc(L.prep.title)}</button>` : ""}
        </div>
        ${L.patch_video ? `<button type="button" class="btn-quiet a-patchvideo" id="aPatchVideo" hidden>${icon("play", { size: 16 })}${esc(L.patch_video.line)} <small></small></button>` : ""}
      </div>`;
    // Hands-free: one short offer, spoken once with the patch line; "yes" / "next" takes it (screen().offer).
    const offer = commander ? OFFER.mission : nx ? (nx.ride ? OFFER.ride : OFFER.nextLesson) : "";
    // the patch line and the offer: one say, one on-air span (no gap for the ear between them); before the check ride
    // the story beat sits between them (docs/STORY.md: last lesson -> ride)
    const patchLine = commander ? CAPCOM.qualified(callSign.spoken(), badge.name) : CAPCOM.patch(callSign.spoken(learner()), badge.name);
    const lines = [patchLine, ...(!commander && nx && nx.ride ? [TRANSITION.toRide.say] : []), ...(offer ? [offer] : [])];
    say(lines.length > 1 ? lines : patchLine, { situation: "badge" });
    const g = panel.querySelector("#aGoMission"); if (g) g.onclick = () => goMission();
    const n = panel.querySelector("#aNextLesson"); if (n) n.onclick = () => openLesson(nx.id);
    panel.querySelector("#aMap").onclick = () => showMap();
    const pb = panel.querySelector("#aPrepBadge"), lid = L.id; if (pb) pb.onclick = () => openLesson(lid, { prep: true });   // optional, after the lesson
    (g || n || panel.querySelector("#aMap")).focus({ preventScroll: true });
    const pv = panel.querySelector("#aPatchVideo"), pvm = L.patch_video && L.patch_video.media;
    if (pv) Promise.all([isAvailable(pvm), getVideo(pvm)]).then(([st, v]) => {   // only when it can play now (never a dead button)
      if (!pv.isConnected || st === "offline") return;
      if (v) pv.querySelector("small").textContent = watchLabel(v).replace(/^Watch\s*/, "");
      pv.hidden = false; pv.onclick = () => { stop(); openVideo(pvm, { context: "patch" }); };
    });
  }

  // ---------- hands-free (the session's router decides; these run what it decided) ----------
  /** What the router needs to know about this screen. */
  function screen() {
    if (!ui.active) return null;
    if (view === "callsign" || view === "coursewait") return { screen: "callsign" };
    if (view === "coursepick" && picker) return { screen: "coursepick", step_options: picker.names };
    if (view === "map") { const nx = nextLesson(); return { screen: "map", offer: prog.qualified ? "mission" : nx ? "next_lesson" : null }; }
    if (view === "badge") { const nx = nextLesson(); return { screen: "patch", offer: prog.qualified ? "mission" : nx ? "next_lesson" : null }; }
    // the router's prep screen (turn_router.PREP_CMDS): done / skip / wait / help
    if (view === "prep" && L) return { screen: "prep", offer: "prep_task", lesson_id: L.id };
    if (view !== "lesson" || !L) return { screen: "map" };
    if (waitingNext) return { screen: "lesson_done", offer: "next_step" };
    const acc = L.steps[i].accept;
    // lesson_id + step: the router looks up the step to tell a real try from room talk (grade.plausible)
    return { screen: L.ride ? "ride" : "lesson", step_type: acc.type, step_options: (acc.options || (acc.guess || {}).options || []).map(o => o.label), lesson_id: L.id, step: i };
  }
  /** [flows] "continue" / "resume" in a lesson (often after "stop" cut the question off): the question again. */
  function reAsk(source) { flowLog({ flow: L && L.ride ? "check_ride" : "lesson", event: "repeat", source, step: i }); say(L.steps[i].prompt, undefined, { repeat: true }); }
  /** A navigation intent. True when the Academy ran it. */
  function nav(intent, arg) {
    if (!ui.active) return false;
    if (view === "callsign" || view === "coursewait") return false;
    if (view === "coursepick") return picker ? picker.nav(intent, arg) : false;
    const nx = nextLesson();
    if (intent === "lesson") { if (lessons().some(l => l.id === arg)) { stop(); openLesson(arg); return true; } return false; }
    if (view === "prep") {   // Mission prep: the router's prep_* intents; yes / next / a thumbs-up is Done; no is Skip
      if (["prep_done", "next", "start", "accept_offer", "yes"].includes(intent)) { prepDone(true); return true; }
      if (["prep_skip", "decline_offer", "no", "skip_tour"].includes(intent)) { prepDone(false); return true; }
      if (intent === "prep_wait") { flowLog({ flow: "prep", event: "pause", source: "voice" }); say(PREP.waitSay); return true; }
      if (intent === "prep_watch") { watchPrepVideo(); return true; }
      if (intent === "prep_help" && arg === "missing") { flowLog({ flow: "prep", event: "missing", source: "voice" }); return true; }   // the session said PREP_MISSING_LINE: never the steps again
      if (intent === "prep_help" || intent === "repeat_step") { flowLog({ flow: "prep", event: "repeat", source: "voice" }); say(L.prep.steps); return true; }
    }
    if (view === "lesson" && L && !waitingNext && L.steps[i].accept.type === "video" && stepState.video) {   // [media] next skips
      // "yes" / "no" before a guess is the guess (novice playtest #7: "yes" used to open the video)
      const gw = { yes: "yes", accept_offer: "yes", no: "no", decline_offer: "no" }[intent];
      if (gw && stepState.video.needsGuess && stepState.video.needsGuess() && stepState.video.guessText(gw)) return true;
      if (["next", "decline_offer", "no"].includes(intent)) { stepState.video.skip(); return true; }
      if (["accept_offer", "yes"].includes(intent)) { stepState.video.watch(); return true; }
    }
    if (intent === "map" || (intent === "back" && view !== "map")) { stop(); showMap(); return true; }
    if (intent === "repeat_step" && view === "lesson" && L) { say(L.steps[i].prompt, undefined, { repeat: true }); return true; }
    if (["next", "start", "accept_offer"].includes(intent)) {
      if (view === "lesson" && waitingNext) { next(); return true; }
      // [flows] "continue" / "resume" in a lesson (often after "stop" cut the question off): the question again
      if (view === "lesson" && intent === "start") { reAsk("voice"); return true; }
      // [audit2] "next" before the step is answered did nothing at all: say why, and how (the hint shows on the card)
      if (view === "lesson" && intent === "next") { Promise.resolve(help()).then(t => { if (t) say(`${SCHOOL.answerFirst} ${t}`); }); return true; }
      if (view === "badge" || view === "map") {
        if (prog.qualified && (view === "badge" || !nx || arg === "mission")) { goMission(); return true; }
        if (nx) { openLesson(nx.id); return true; }
      }
      return false;
    }
    if (intent === "decline_offer") return true;    // stay here, quietly
    return false;
  }
  /** The router's "answer": the current step's answer (or a call sign). */
  function answerText(text, o) { return handleText(text, o); }

  // ---------- inputs from the rest of the app ----------
  /** A typed or spoken turn. True when the Academy used it. */
  async function handleText(text, { typed = false, sure = false } = {}) {
    typedTurn = !!typed;   // [courses playtest] a typed non-answer gets the step again, never silence (answer() below)
    if (!ui.active) return false;
    const t = text.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
    if (view === "coursepick" && picker) return picker.handleText(text);
    if (view === "coursewait") return true;
    if (view === "callsign") {
      const hit = CALLSIGNS.find(c => t.includes(c.toLowerCase()));
      if (hit) { callSign.set(hit); afterCallSign(hit); return true; }
      if (/surprise|random|any|you pick|pick for me/.test(t)) { const c = CALLSIGNS[Math.floor(Math.random() * CALLSIGNS.length)]; callSign.set(c); afterCallSign(c); return true; }
      // [audit2] a short name typed in the voice bar: put it in the field, so the screen shows what happens next
      const typed = String(text || "").replace(/[^\p{L}\p{N} '-]/gu, "").trim();
      if (csTyped && typed && typed.length <= 18 && typed.split(/\s+/).length <= 3) { csTyped(typed); say(CALLSIGN_COPY.typed); return true; }
      say(CALLSIGN_COPY.pick); return true;
    }
    if (view === "badge" || view === "map") {
      if (NEXT_WORDS.test(t)) { const nx = nextLesson(); if (prog.qualified && (view === "badge" || !nx)) goMission(); else if (nx) openLesson(nx.id); return true; }
      return false;
    }
    if (view === "prep") {   // "done", "finished", "yes" / "skip", "no", "not now"
      // "I don't have a lamp", "we can't find flour": a way out, never the task's steps again (novice playtest #8)
      if (/\b(don ?t|do not|haven ?t|have no|got no) (have|got|own)\b|\bcan ?t find\b|\b(we|i) have no\b|^no \w+$/.test(t) && !/^no (thanks|thank you)$/.test(t)) { say(PREP.missingSay); return true; }
      if (/\b(done|did it|finished|all done|ready|yes|yeah|next)\b/.test(t)) { prepDone(true); return true; }
      if (/\b(skip|no|nope|not now|later)\b/.test(t)) { prepDone(false); return true; }
      if (/^(continue|resume|keep going|go on|carry on|i m back|we re back)$/.test(t)) { flowLog({ flow: "prep", event: "repeat", source: "typed" }); say(L.prep.steps); return true; }
      if (/\b(show (me|us) how|watch (how|the video|a video)|play (the|a) video|show (me|us) the video)\b/.test(t)) { watchPrepVideo(); return true; }
      say(PREP.ask); return true;
    }
    if (view !== "lesson") return false;
    if (waitingNext) { if (NEXT_WORDS.test(t)) next(); else if (!nagged) { nagged = true; speakLine(OFFER.nextStep); } return true; }
    // [flows] no session (POST /api/ask): "continue" after a stop asks the question again, never grades it as an answer
    if (/^(continue|resume|keep going|go on|carry on)$/.test(t)) { reAsk("typed"); return true; }
    // [media] a video step: "watch" plays it here, "skip" moves on (the server never has to grade those words)
    if (L.steps[i].accept.type === "video" && stepState.video) {
      if (stepState.video.needsGuess && stepState.video.needsGuess() && stepState.video.guessText(text)) return true;   // "yes" is a guess first
      const w = videoStepWord(text); if (w) { stepState.video[w](); return true; }
    }
    // [owner bug] the far side step: "far side" / "near side" by voice turns the Moon first, exactly like the button
    // (academy/globe_steps.js grades after the turn); anything else still goes to the server's grader
    if (L.steps[i].accept.type === "globe_side") {
      const far = /\b(far|four side|back side|dark side|other side)\b/.test(t), near = /\b(near|front|this side)\b/.test(t);
      const b = far !== near && panel.querySelector(`.g-side[data-c="${far ? "far" : "near"}"]`);
      if (b && !b.disabled) { b.click(); return true; }
    }
    // a speech step collecting words (a summary, or reading aloud): it keeps them until the cadet is done
    if (stepState.onText && stepState.onText(text)) return true;
    // tap steps: naming the place counts too (hands-free, and kids who can't tap); the server grades it.
    // [arch QA] sure: typed, Space held or the router's "answer": a wrong word is a miss with the next hint
    return answer(sure && !L.ride ? { text, sure: true } : { text });
  }
  /** A tap on the globe (lat/lon). True when the Academy used it. */
  function onTap(p) {
    if (!ui.active || view !== "lesson" || waitingNext || L.ride) return ui.active;
    const acc = L.steps[i].accept;
    if (acc.type !== "tap" && acc.type !== "intent") { if (stepTap) stepTap(p); return true; }
    const { f, d } = globe.nearest(p);
    answer({ tap: { lat: p.lat, lon: p.lon, ...(f && d < 12 ? { place: f.id } : {}) } });
    return true;
  }
  function onArtifact(a) {
    if (!ui.active) return false;
    if (view === "lesson" && !waitingNext && !L.ride && ["tap", "intent"].includes(L.steps[i].accept.type)) answer({ tap: { place: a.id, lat: a.lat, lon: a.lon } });
    return true;
  }

  ui.whatNow = whatNow;
  /** [D5] A concept's spaced review (brain.js): open its lesson at the step that practises it. */
  ui.review = (id, step) => { if (!lessons().some(l => l.id === id)) return false; openLesson(id, { step }); return true; };
  // test hook (tests/e2e/answers_e2e.py, robustness_e2e.py; only when the page sets window.__outpostTest): jump the open
  // lesson to step n, fresh, as if the kid had just arrived there
  try { if (window.__outpostTest) (window.__outpost = window.__outpost || {}).academyTest = {
    step: n => { if (view !== "lesson" || !L || !L.steps[n]) return false; i = n; misses = 0; waitingNext = false; feedback = null; stepKey = ""; freshStep(); render(); return true; },
    prep: id => openLesson(id, { prep: true }),   // "Try at home" (opened from the map card or the patch screen)
    get where() { return { view, lesson: L && L.id, step: i, waitingNext }; } }; } catch (e) { /* */ }
  return ui;
}
