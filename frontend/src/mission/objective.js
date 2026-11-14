// The cabin's "what now": the Now task card from the sim state (and the live clock), and the story of a finished
// mission. Pure functions (no DOM), so node --test covers them (frontend/tests/story.test.js, gameplay.test.js). Copy
// lives in story.js (NOW, DEBRIEF).
//
// nowCard(state, clock?) -> card | null           (docs/GAMEPLAY.md §5)
//   key       a stable id ("task:ice_run-4:steer", "first_shift", "steady", ...) so the UI speaks a change once
//   title     the task's name ("Storm prep"), or "Now"
//   text      the one line after NOW (12 words or fewer), also spoken for "what do I do?"
//   target    the control to glow (cabin.js point()): shields | shelter | night | houston | rover:<task> | load:<k> |
//             play | skip | warp | task (the card's own buttons) | end_shift
//   panel     the panel that control lives on (Cadet keeps the rest dim)
//   level     "info" | "caution" | "warn"
//   progress  {done, total} for a task with steps, else null
//   left_h    sim hours left before the task's deadline (the countdown), else null
//   buttons   [{label, hint?, cmd? | task? | clock?}]: what the card's buttons do (an order, a task press or choice, a
//             clock action: play | skip | warp)
//   choice    true when the kid must pick (the clock pauses for a decision)
//   lesson    {id, n, title} ("Lesson 5 helps here") or null
//   readouts  [{k, v}]: battery, dose rate, rover ETA... for the task
// clock: {started, running, warp} from mission/clock.js (optional; the strip works without it).
//
// nowObjective(state, clock?) -> {key, text, target, panel, level} | null: the card's strip fields (older callers).
import { NOW, DEBRIEF } from "../story.js";

const n0 = v => Math.max(0, Math.round(+v || 0));

/** A storm warning in any of the shapes the sim has sent (env.warning, env.storm_warning, env.storm_forecast). */
function warningOf(s) {
  const e = (s && s.env) || {};
  const w = e.warning || e.storm_warning || e.storm_forecast;
  if (!w || w.active === false || (e.storm && e.storm.active)) return null;
  return { lead: w.eta_h ?? w.lead_h ?? null };
}

/** The panel each task's controls live on (cabin.js data-panel ids; "power" is the displays' power page). */
const TARGET_PANEL = { shields: "radiation", shelter: "radiation", night: "power", houston: "comm", play: "pedestal", skip: "pedestal",
  warp: "pedestal", end_shift: "pedestal" };
const panelOf = (target, fallback) => {
  const k = String(target || "").split(":")[0];
  return k === "rover" ? "rover" : k === "load" ? "power" : TARGET_PANEL[k] || fallback || null;
};

/** The line for a step that can't be done yet (waiting on the rover, on the storm to come closer). */
function waitLine(t, s, st) {
  if (s.wait) return s.wait;
  const rv = (st && st.rover) || {};
  if (s.id === "steer") return NOW.driving(n0(rv.eta_h));
  if (s.id === "back") return NOW.roverOut(n0(rv.eta_h));
  if (s.id === "test") return NOW.repairing;
  return NOW.waiting;
}

function taskCard(s, t, clock) {
  const st = t.step;
  const base = { title: t.title, panel: t.panel, level: t.level || "info", lesson: t.lesson || null, readouts: t.readouts || [],
    progress: { done: t.done_count, total: t.total }, left_h: t.time_left_h ?? null, kind: t.kind, task: t.id };
  if (!st) return { ...base, key: `task:${t.id}:done`, text: NOW.taskDone(t.title), target: null, buttons: [], choice: false };
  const key = `task:${t.id}:${st.id}:${st.ready ? "go" : "wait"}`;
  if (!st.ready) {
    // nothing to press yet: the clock is the job (skip ahead to the moment it's ready)
    return { ...base, key, text: waitLine(t, st, s), target: "skip", panel: "pedestal", buttons: [{ label: NOW.skipBtn, clock: "skip" }], choice: false, step: st };
  }
  let buttons;
  if (st.kind === "order") buttons = [{ label: st.label, cmd: st.cmd }];
  else if (st.kind === "choice") buttons = (st.options || []).map(o => ({ label: o.label, hint: o.hint || null, task: { type: "task", task: t.id, step: st.id, choice: o.id } }));
  else buttons = [{ label: st.label, task: { type: "task", task: t.id, step: st.id } }];
  return { ...base, key, text: st.label, target: st.target === "task" ? "task" : st.target, panel: st.target === "task" ? t.panel : panelOf(st.target, t.panel),
    buttons, choice: st.kind === "choice", hint: st.hint || null, step: st };
}

export function nowCard(s, clock = null) {
  if (!s || s.over) return null;
  if (s.task) return taskCard(s, s.task, clock);
  const o = legacy(s, clock);
  if (!o) return null;
  const b = o.target === "play" ? [{ label: NOW.playBtn, clock: "play" }] : o.target === "skip" ? [{ label: NOW.skipBtn, clock: "skip" }]
    : o.target === "warp" ? [{ label: NOW.warpBtn, clock: "warp" }, { label: NOW.skipBtn, clock: "skip" }] : [];
  return { title: NOW.label, progress: null, left_h: null, lesson: null, readouts: [], choice: false, buttons: b, ...o };
}

/** The strip from the state alone (no task from the sim: the sample model, a storm with the crew sheltered, steady). */
function legacy(s, clock) {
  const e = s.env || {}, r = s.resources || {}, rv = s.rover || {}, al = s.alerts || [], L = s.loads || {};
  const O = s.objectives || {}, ice = O.ice || {};
  const storm = !!(e.storm && e.storm.active), wn = warningOf(s);
  const sunH = e.next_sun_change_h != null ? n0(e.next_sun_change_h) : null;
  const o = (key, text, target, panel, level = "info") => ({ key, text, target, panel, level });
  const started = !clock || clock.started;
  const acted = !!(s.acted && s.acted.allocate);
  if ((s.mission_time_h || 0) === 0 && !acted && !storm) return o("first_shift", NOW.firstShift, "shields", "radiation");
  if ((s.mission_time_h || 0) === 0 && !started) return o("start_clock", NOW.startClock, "play", "pedestal");
  if (storm && e.storm.sep === false) return o("weak_storm", NOW.weakStorm, "skip", "pedestal", "info");   // QA-27: a near miss
  if (storm && !s.shelter) return o("storm_hit", NOW.stormHit, "shelter", "radiation", "warn");
  if (storm && s.shelter) return o("sheltered", NOW.sheltered, "skip", "pedestal", "info");
  if (wn) return o("warning", NOW.warning(wn.lead != null ? n0(wn.lead) : null), (L.shields || 0) >= 40 ? "shelter" : "shields", "radiation", "caution");
  if (al.includes("low_power") || (r.power_pct != null && r.power_pct < 25)) {
    return s.power_save ? o("low_power", NOW.lowPower, "load:science", "power", "caution") : o("low_power", NOW.lowPower, "night", "power", "caution");
  }
  if (al.includes("life_support_low") || (r.life_support_pct != null && r.life_support_pct < 25)) {
    return rv.busy ? o("rover_out", NOW.roverOut(n0(rv.eta_h)), "skip", "pedestal", "caution") : o("low_air", NOW.lowAir, "rover:collect_ice", "rover", "caution");
  }
  if (rv.busy) {
    const darkSoon = e.in_sun && sunH != null && sunH <= Math.max(6, n0(rv.eta_h));
    if (darkSoon && rv.task !== "return" && rv.task !== "return_home") return o("rover_dark", NOW.roverDark, "rover:return", "rover", "caution");
    return o("rover_out", NOW.roverOut(n0(rv.eta_h)), "skip", "pedestal");
  }
  if (e.in_sun && sunH != null && sunH <= 6 && !s.power_save) return o("sunset", NOW.sunset(sunH), "night", "power", "caution");
  if (e.in_sun === false && !s.power_save) return o("dark", NOW.dark, "night", "power");
  if (ice.goal != null && !ice.met && e.in_sun) return o("ice", NOW.ice, "rover:collect_ice", "rover");
  if (clock && clock.started && !clock.running && !clock.held) return o("paused", NOW.paused, "play", "pedestal");
  return o("steady", NOW.steady, "warp", "pedestal");
}

export function nowObjective(s, clock = null) {
  const c = nowCard(s, clock);
  return c ? { key: c.key, text: c.text, target: c.target, panel: c.panel, level: c.level } : null;
}

/** The spoken answer to "what do I do?" in the cabin. */
export const nowSpoken = (s, clock = null) => { const c = nowCard(s, clock); return c ? `${NOW.ask} ${c.text}` : null; };

/** The nudge after ~20 s with nothing done: the task by name and its next step (20 words or fewer). */
export const nudgeLine = (s, clock = null) => {
  const c = nowCard(s, clock); if (!c) return null;
  return c.progress ? NOW.nudge(c.title, c.text) : c.text;
};

/** Time left as a kid reads it: "6 h", "40 min" (sim time). */
export const leftLabel = h => (h == null ? "" : h >= 1 ? `${Math.round(h)} h` : `${Math.max(1, Math.round(h * 60))} min`);

/**
 * The debrief as a story: three beats (where, what happened, how the goals went, then how it ended), one "try next"
 * line, and the one clear choice. `d` is GET /debrief, `st` the last State.
 *   -> {beats: [string, string, string], tryLine, choice: "again" | "resume" }
 */
export function debriefStory(d = {}, st = {}) {
  const outcome = d.outcome || st.outcome || (st.over ? "" : "in_progress");
  const paused = outcome === "in_progress" || !outcome, won = outcome === "survived" || outcome === "success";
  const site = (((st.site && st.site.name) || (d.site && d.site.name) || "the outpost") + "").split(" (")[0];
  const tl = d.timeline || [], lastH = Math.max(st.mission_time_h || 0, ...tl.map(t => +t.t_h || 0));
  const days = Math.max(1, Math.min(10, Math.ceil(lastH / 24) || 1));
  const stormShifts = tl.filter(t => (t.events || []).includes("solar_storm")).length;
  const storms = tl.reduce((n, t, i) => n + ((t.events || []).includes("solar_storm") && !(i && (tl[i - 1].events || []).includes("solar_storm")) ? 1 : 0), 0);
  const lim = (st.resources && st.resources.dose_limit_msv) || 50, dose = (st.resources && st.resources.dose_msv) || 0;
  const hurt = outcome === "dose_limit" || dose / lim > 0.6;
  const b1 = DEBRIEF.start(site, days);
  const b2 = storms || stormShifts ? (hurt ? DEBRIEF.stormHurt(storms || 1) : DEBRIEF.stormSafe(storms || 1)) : DEBRIEF.noStorm;
  const O = d.objectives || st.objectives || {}, sci = !!(O.science && O.science.met), ice = !!(O.ice && O.ice.met);
  const goals = sci && ice ? DEBRIEF.goalsBoth : sci ? DEBRIEF.goalsScience : ice ? DEBRIEF.goalsIce : DEBRIEF.goalsNone;
  const end = paused ? DEBRIEF.endPaused(st.day || days) : won ? DEBRIEF.endWon : DEBRIEF.endLost;
  // three beats: the setting, the storm, then goals + ending folded into the last one only when it stays short
  const beats = [b1, b2, paused || won ? goals : end];
  const tryLine = firstSentence(d.try) || (won && sci && ice ? DEBRIEF.tryNewSite : DEBRIEF.tryDefault);
  return { beats, end, tryLine, choice: paused ? "resume" : "again", won, paused };
}

function firstSentence(t) { const m = String(t || "").match(/^.*?[.!?](?=\s|$)/); return (m ? m[0] : String(t || "")).trim(); }
