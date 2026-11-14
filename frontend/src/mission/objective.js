// The cabin's "what now": one objective from the sim state, and the story of a finished mission. Pure functions (no
// DOM), so node --test covers them (frontend/tests/story.test.js). Copy lives in story.js (NOW, DEBRIEF).
//
// nowObjective(state) -> {key, text, target, panel, level} | null
//   key     a stable id ("first_shift", "storm_hit", ...) so the UI speaks a change once
//   text    the line after "Now:" (12 words or fewer), also spoken for "what do I do?"
//   target  the control to glow (cabin.js point()): end_shift | shelter | shields | night | houston | rover:<task> | load:<k>
//   panel   the panel that control lives on (Cadet keeps the rest dim)
//   level   "info" | "caution" | "warn"
import { NOW, DEBRIEF } from "../story.js";

const n0 = v => Math.max(0, Math.round(+v || 0));

/** A storm warning in any of the shapes the sim has sent (env.warning, env.storm_warning, env.storm_forecast). */
function warningOf(s) {
  const e = (s && s.env) || {};
  const w = e.warning || e.storm_warning || e.storm_forecast;
  if (!w || w.active === false || (e.storm && e.storm.active)) return null;
  return { lead: w.eta_h ?? w.lead_h ?? null };
}

export function nowObjective(s) {
  if (!s || s.over) return null;
  const e = s.env || {}, r = s.resources || {}, rv = s.rover || {}, al = s.alerts || [], L = s.loads || {};
  const O = s.objectives || {}, ice = O.ice || {};
  const storm = !!(e.storm && e.storm.active), wn = warningOf(s);
  const sunH = e.next_sun_change_h != null ? n0(e.next_sun_change_h) : null;
  const o = (key, text, target, panel, level = "info") => ({ key, text, target, panel, level });
  if (storm && e.storm.sep === false) return o("weak_storm", NOW.weakStorm, "end_shift", "pedestal", "info");   // QA-27: a near miss
  if (storm && !s.shelter) return o("storm_hit", NOW.stormHit, "shelter", "radiation", "warn");
  if (storm && s.shelter) return o("sheltered", NOW.sheltered, "end_shift", "pedestal", "info");
  if (wn) return o("warning", NOW.warning(wn.lead != null ? n0(wn.lead) : null), (L.shields || 0) >= 40 ? "shelter" : "shields", "radiation", "caution");
  if (al.includes("low_power") || (r.power_pct != null && r.power_pct < 25)) {
    return s.power_save ? o("low_power", NOW.lowPower, "load:science", "power", "caution") : o("low_power", NOW.lowPower, "night", "power", "caution");
  }
  if (al.includes("life_support_low") || (r.life_support_pct != null && r.life_support_pct < 25)) {
    return rv.busy ? o("rover_out", NOW.roverOut(n0(rv.eta_h)), "end_shift", "pedestal", "caution") : o("low_air", NOW.lowAir, "rover:collect_ice", "rover", "caution");
  }
  if (rv.busy) {
    const darkSoon = e.in_sun && sunH != null && sunH <= Math.max(6, n0(rv.eta_h));
    if (darkSoon && rv.task !== "return") return o("rover_dark", NOW.roverDark, "rover:return", "rover", "caution");
    return o("rover_out", NOW.roverOut(n0(rv.eta_h)), "end_shift", "pedestal");
  }
  if (e.in_sun && sunH != null && sunH <= 6 && !s.power_save) return o("sunset", NOW.sunset(sunH), "night", "power", "caution");
  if (e.in_sun === false && !s.power_save) return o("dark", NOW.dark, "night", "power");
  if ((s.mission_time_h || 0) === 0) return o("first_shift", NOW.firstShift, "start", ["power", "pedestal"]);
  if (ice.goal != null && !ice.met && e.in_sun) return o("ice", NOW.ice, "rover:collect_ice", "rover");
  return o("steady", NOW.steady, "end_shift", "pedestal");
}

/** The spoken answer to "what do I do?" in the cabin. */
export const nowSpoken = s => { const ob = nowObjective(s); return ob ? `${NOW.ask} ${ob.text}` : null; };

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
