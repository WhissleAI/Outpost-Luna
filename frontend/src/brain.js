// My Brain (docs/BRAIN.md): the cadet's own page about what they've learned and how the outpost works with them.
// Opens from the top bar's "My Brain" button, the call-sign chip on the Flight School map, the B key, a controller's
// focus + A, and voice ("my brain", "what have I learned", "how does the outpost think"; backend turn_router NAV).
//
// It reads only what the app already keeps, plus one small on-device aggregate:
//   - the course (GET /api/academy/course) and this cadet's Flight School progress ("atm-academy", via progress.js);
//   - missions flown ("outpost-missions-flown:<call sign>", explorer.js);
//   - the practice counts (brain_store.js "outpost-brain": lesson ids and counts, never words);
//   - what on-device learning holds for this cadet (GET /api/learn?profile=; learning_ui.js shows the same to grown-ups).
// The grown-ups' side is Settings → For grown-ups → Progress (progress.js), which renders practiceHtml() below.
// Pure builders are exported for tests/brain.test.js; installBrain() wires the drawer (the About drawer's look).
import { icon } from "./assets/icons.js";
import * as store from "./brain_store.js";
import { callSign } from "./story.js";
import { isClass, isExplorer, isField } from "./explorer.js";
import { readCadets, summarize } from "./progress.js";
import { activeProfile } from "./learning_ui.js";
import { courseState, qid, splitQid } from "./courses.js";   // [courses] big ideas from the course manifest; counts per course

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || {}) : {};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Every lesson step the Academy grades lands in the practice counts (ids and counts only; brain_store.js).
if (typeof window !== "undefined" && typeof window.addEventListener === "function") window.addEventListener("outpost:lesson-result", e => { if (e && e.detail) store.add({ ...e.detail, lesson: lessonKey(e.detail.lesson) }); });

export const COPY = {
  title: "My Brain",
  close: "Close My Brain",
  say: "Here's your brain. The stars are what you've learned.",
  cadet: "Cadet", commander: "Commander",
  change: "Change call sign",
  stats: { stars: "Stars lit", patches: "Patches", missions: "Missions", streak: "Days in a row" },
  mapTitle: "Your star map",
  mapLine: "Each star is a big idea. Earn its patch and it lights up.",
  legend: { lit: "Learned", practising: "Practising", dim: "Not yet" },
  tryTitle: "Try next",
  tryGo: "Go to Flight School",
  voiceTitle: "How the outpost knows your voice",
  voiceEmpty: "Talk to CAPCOM. The outpost learns how you say Moon names.",
  alias: (heard, name) => `You say “${heard}”. The outpost knows you mean ${name}.`,
  waits: "You take a moment before you answer. The outpost waits for you.",
  quick: "You answer quickly. The outpost answers quickly too.",
  thinkTitle: "How the outpost thinks",
  think: [
    ["hear", "It listens", "It turns your voice into words, right here on this computer."],
    ["comms", "It checks who you're talking to", "Talking to a friend? It stays quiet. Talking to CAPCOM? It answers."],
    ["shield", "It keeps your words private", "Names and addresses stay secret. Rude words get filtered."],
    ["radio", "It takes turns", "One voice at a time. You can always cut in."],
  ],
  foot: "Saved on this computer only. A grown-up can see it all in Settings, For grown-ups.",
  loading: "Loading…",
};

/** Plain names for each NASA lesson's big idea (the star's label) and what it teaches, with the NGSS hooks the
 *  curriculum cites (docs/LEARNING_DESIGN.md §1, §11.2, §12; cited, not alignment-reviewed). A Class lesson uses its title. */
export const SKILLS = {
  moon: { star: "One face", idea: "The Moon keeps one face to Earth. The far side gets sunlight too.", ngss: ["1-ESS1-1"] },
  phases: { star: "Phases", idea: "Why the Moon's shape changes, and what an eclipse is.", ngss: ["1-ESS1-1", "MS-ESS1-1"] },
  power: { star: "Sun power", idea: "Sunlight at the south pole, and planning for the dark.", ngss: ["5-ESS1-2", "MS-ETS1-1"] },
  comms: { star: "Radio", idea: "Radio needs Earth in the sky. Radio words and readbacks.", ngss: [] },
  radiation: { star: "Space weather", idea: "Solar storms, and acting on a warning in time.", ngss: ["MS-ETS1-1"] },
  life: { star: "Air and ice", idea: "Ice in dark craters, and keeping a crew alive.", ngss: [] },
  checkride: { star: "Check ride", idea: "Running the outpost: power, life support and radiation together.", ngss: ["MS-ETS1-2"] },
  gravity: { star: "Gravity", idea: "Moon gravity and dust.", ngss: ["5-PS2-1"] },
  history: { star: "Apollo", idea: "From Apollo to Artemis, and what each taught the next.", ngss: [] },
  observe: { star: "Observe", idea: "Describing a place like a geologist: size, shape, brightness.", ngss: ["MS-ESS1-3"] },
  craters: { star: "Craters", idea: "Impacts and lava, and which came first.", ngss: ["MS-ESS1-3", "HS-ESS1-6"] },
  rocks: { star: "Rock ages", idea: "Reading the Moon's age from its rocks and surface.", ngss: ["HS-ESS1-6"] },
  fieldkit: { star: "Field kit", idea: "Field tools and the sampling routine.", ngss: ["MS-ESS1-3", "3-5-ETS1-1"] },
};
/** [courses] The practice-count key for a lesson id: bare on the Moon (the counts saved before courses stay valid),
 *  "<course>:<id>" in another course, so two courses' lessons never share counts. */
export const lessonKey = (id, course = courseState.active) => (!course || course === "moon" ? id : qid(course, id));
/** [courses] The course's own big ideas (manifest big_ideas, docs/COURSES.md §4.8), else the table above (the Moon's). */
const courseSkill = l => { const b = l && ((courseState.info && courseState.info.big_ideas) || {})[splitQid(l.id).id];
  return b && b.star ? { star: b.star, idea: b.idea || "", ngss: Array.isArray(b.codes) ? b.codes : [] } : null; };
export const skillOf = l => courseSkill(l) || SKILLS[l && l.id] || { star: String((l && l.title) || "").split(" ").slice(0, 2).join(" "), idea: (l && l.title) || "", ngss: [] };

const trackOf = l => (l.ride || (!isClass(l) && !isExplorer(l) && !isField(l)) ? "core" : isField(l) ? "field" : isExplorer(l) ? "explorer" : "class");
const badgeId = l => (l && l.badge && l.badge.id) || "";

// ---------- aggregates (pure) ----------
/** The days-in-a-row count ending today (or yesterday, so the morning doesn't break a streak). days: YYYY-MM-DD. */
export function streak(days, today = store.dayOf()) {
  const set = new Set((days || []).filter(d => typeof d === "string"));
  const back = (d, n) => { const t = new Date(d + "T12:00:00"); t.setDate(t.getDate() - n); return store.dayOf(t); };
  let start = set.has(today) ? today : set.has(back(today, 1)) ? back(today, 1) : null;
  let n = 0;
  while (start && set.has(back(start, n))) n++;
  return n;
}

/** One row per lesson practised, in course order: counts, first-try share and minutes (pure). */
export function practice(brain, lessons = []) {
  const b = store.clean(brain);
  return (lessons || []).filter(l => l && l.id && b.lessons[lessonKey(l.id)] && b.lessons[lessonKey(l.id)].steps + b.lessons[lessonKey(l.id)].misses > 0).map(l => {
    const c = b.lessons[lessonKey(l.id)], sk = skillOf(l);
    return { id: l.id, title: l.title || l.id, idea: sk.idea, ngss: sk.ngss, track: trackOf(l), ...c,
      firstPct: c.steps ? Math.round((100 * c.first) / c.steps) : 0, mins: Math.round(c.secs / 60) };
  });
}

/** The lessons that needed the most help so far (at least 3 graded steps; up to two; pure). */
export function hardest(rows) {
  return (rows || []).filter(r => r.steps >= 3 && r.helped + r.shown > 0)
    .sort((a, b) => (b.helped + 2 * b.shown) / b.steps - (a.helped + 2 * a.shown) / a.steps).slice(0, 2);
}

/** Totals across lessons (pure). */
export function totals(rows) {
  const t = { steps: 0, first: 0, helped: 0, shown: 0, misses: 0, pause: 0, secs: 0 };
  (rows || []).forEach(r => Object.keys(t).forEach(k => { t[k] += r[k] || 0; }));
  return { ...t, mins: Math.round(t.secs / 60), firstPct: t.steps ? Math.round((100 * t.first) / t.steps) : 0 };
}

/** The star map's stars: each lesson with a patch, lit when earned, "practising" when started (pure). */
export function stars(lessons, academy, brain) {
  const got = new Set((academy && academy.badges) || []), b = store.clean(brain), steps = (academy && academy.steps) || {};
  return (lessons || []).filter(l => l && l.id && l.badge && !l.preview).map(l => {
    const sk = skillOf(l);
    const state = got.has(badgeId(l)) ? "lit" : (b.lessons[lessonKey(l.id)] || steps[l.id]) ? "practising" : "dim";
    return { id: l.id, star: sk.star, title: l.title || l.id, track: trackOf(l), state };
  });
}

/** Kid-friendly lines from GET /api/learn's `learned` (pure). Up to three names, then the waiting habit. */
export function voiceLines(learned) {
  if (!learned || typeof learned !== "object") return [];
  const out = ((learned.aliases || []).filter(a => a && a.heard && a.name).slice(0, 3)).map(a => COPY.alias(a.heard, a.name));
  const h = learned.habits || {};
  if ((h.turns || 0) >= 5) out.push(+h.end_silence_s > 0.5 ? COPY.waits : COPY.quick);
  return out;
}

// ---------- the star map (inline SVG, no script) ----------
// Each track is a constellation along its own path; stars on a track are joined by a line where both are learned.
const PATHS = { core: [[44, 214], [330, 64]], explorer: [[370, 56], [470, 40]], field: [[440, 126], [610, 206]], class: [[330, 246], [600, 252]] };
// labels alternate below / above along a track, so neighbouring stars' names never overlap
export function layout(list) {
  const by = {};
  list.forEach(s => (by[s.track] = by[s.track] || []).push(s));
  const out = [];
  Object.entries(by).forEach(([t, ss]) => {
    const [[x0, y0], [x1, y1]] = PATHS[t] || PATHS.class;
    ss.forEach((s, k) => {
      const f = ss.length === 1 ? 0.5 : k / (ss.length - 1);
      out.push({ ...s, i: k, x: Math.round(x0 + (x1 - x0) * f), y: Math.round(y0 + (y1 - y0) * f + (k % 2 ? -14 : 10)) });
    });
  });
  return out;
}
export function starMapSvg(list) {
  const pts = layout(list);
  const lines = [];
  for (let k = 1; k < pts.length; k++) {
    const a = pts[k - 1], b = pts[k];
    if (a.track !== b.track) continue;
    lines.push(`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" class="bm-link${a.state === "lit" && b.state === "lit" ? " is-lit" : ""}"/>`);
  }
  const star = s => {
    const r = s.state === "lit" ? 9 : s.state === "practising" ? 7 : 5;
    const pts5 = Array.from({ length: 10 }, (_, i) => { const a = -Math.PI / 2 + (i * Math.PI) / 5, rr = i % 2 ? r * 0.45 : r; return `${(s.x + rr * Math.cos(a)).toFixed(1)},${(s.y + rr * Math.sin(a)).toFixed(1)}`; }).join(" ");
    return `<g class="bm-star is-${s.state}"><title>${esc(s.title)}: ${esc(COPY.legend[s.state === "lit" ? "lit" : s.state === "practising" ? "practising" : "dim"])}</title>
      ${s.state === "lit" ? `<circle cx="${s.x}" cy="${s.y}" r="${r + 7}" class="bm-glow"/>` : ""}<polygon points="${pts5}"/>
      <text x="${s.x}" y="${s.i % 2 ? s.y - r - 7 : s.y + r + 14}" text-anchor="middle">${esc(s.star)}</text></g>`;
  };
  return `<svg class="bm-map" viewBox="0 0 640 280" role="img" aria-label="${esc(`${pts.filter(s => s.state === "lit").length} of ${pts.length} stars lit`)}">
    ${lines.join("")}${pts.map(star).join("")}</svg>`;
}

// ---------- the cadet's page ----------
/** The whole drawer body (pure). d: {callsign, academy, flown, lessons, brain, learned, today} */
export function cadetHtml(d) {
  const cs = d.callsign || COPY.cadet, academy = d.academy || { badges: [], qualified: false };
  const list = stars(d.lessons, academy, d.brain);
  const lit = list.filter(s => s.state === "lit").length;
  const st = streak(store.clean(d.brain).days, d.today);
  const next = d.lessons && d.lessons.length ? summarize({ academy: { badges: academy.badges || [], qualified: !!academy.qualified, steps: academy.steps || {}, current: academy.current || null }, flown: d.flown || [] }, d.lessons).next : [];
  const voice = voiceLines(d.learned);
  const stat = (k, v) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`;
  return `<header class="bm-head"><span class="set-av" aria-hidden="true">${esc(cs.slice(0, 1).toUpperCase())}</span>
      <div class="bm-who"><h1 id="brainTitle">${esc(cs)}</h1><p>${esc(academy.qualified ? COPY.commander : COPY.cadet)}</p></div>
      <button type="button" class="btn" data-bm-cs>${icon("astronaut", { size: 16 })}${esc(COPY.change)}</button></header>
    <dl class="mx-score bm-stats">${stat(COPY.stats.stars, `${lit}<small> of ${list.length}</small>`)}${stat(COPY.stats.patches, (academy.badges || []).length)}${stat(COPY.stats.missions, (d.flown || []).length)}${stat(COPY.stats.streak, st)}</dl>
    <section class="bm-sec"><h2>${esc(COPY.mapTitle)}</h2><p class="bm-line">${esc(COPY.mapLine)}</p>
      ${list.length ? starMapSvg(list) : `<p class="set-help">${esc(COPY.loading)}</p>`}
      <ul class="bm-legend">${["lit", "practising", "dim"].map(k => `<li class="is-${k}"><i aria-hidden="true"></i>${esc(COPY.legend[k])}</li>`).join("")}</ul></section>
    ${next.length ? `<section class="bm-sec bm-next"><h2>${esc(COPY.tryTitle)}</h2><ul>${next.map(t => `<li>${esc(t)}</li>`).join("")}</ul>
      <button type="button" class="btn-primary" data-bm-go>${esc(COPY.tryGo)}${icon("chevron-right")}</button></section>` : ""}
    <section class="bm-sec"><h2>${esc(COPY.voiceTitle)}</h2>
      ${voice.length ? `<ul class="bm-voice">${voice.map(t => `<li>${icon("hear", { size: 18 })}<span>${esc(t)}</span></li>`).join("")}</ul>` : `<p class="bm-line">${esc(COPY.voiceEmpty)}</p>`}</section>
    <section class="bm-sec"><h2>${esc(COPY.thinkTitle)}</h2>
      <ol class="bm-think">${COPY.think.map(([ic, t, s]) => `<li><span class="bm-ic" aria-hidden="true">${icon(ic, { size: 20 })}</span><div><b>${esc(t)}</b><p>${esc(s)}</p></div></li>`).join("")}</ol></section>
    <p class="foot">${esc(COPY.foot)}</p>`;
}

// ---------- the grown-ups' practice block (Settings → For grown-ups → Progress) ----------
export const GROWN = {
  title: "Practice",
  none: "No graded lesson steps yet.",
  th: ["Lesson", "What it teaches", "Steps", "First try", "With help", "Shown", "Minutes"],
  ngss: "NGSS hooks",
  ngssNote: "Standards the lessons cite. Not an alignment review.",
  hard: t => `Needed the most help: ${t}.`,
  totals: t => `${t.steps} steps answered, ${t.firstPct}% on the first try, about ${t.mins} min on lessons.`,
  hints: (m, p) => `${m} tries weren't right yet.${p ? ` The app gave ${p} hint${p === 1 ? "" : "s"} early, after a long pause.` : ""}`,
  days: n => `Practised on ${n} day${n === 1 ? "" : "s"} (last 60 days).`,
};
/** The practice block for one cadet (pure): totals, the hardest lessons, the table with NGSS hooks. */
export function practiceHtml(brain, lessons) {
  const rows = practice(brain, lessons), t = totals(rows), hard = hardest(rows), days = store.clean(brain).days.length;
  if (!rows.length) return `<section class="pg-block"><h5>${esc(GROWN.title)}</h5><p class="set-help">${esc(GROWN.none)}</p></section>`;
  const tr = r => `<tr><td>${esc(r.title)}</td><td>${esc(r.idea)}${r.ngss.length ? `<small class="bm-ngss">${esc(r.ngss.join(", "))}</small>` : ""}</td>
    <td>${r.steps}</td><td>${r.first}${r.steps ? `<small> (${r.firstPct}%)</small>` : ""}</td><td>${r.helped}</td><td>${r.shown}</td><td>${r.mins}</td></tr>`;
  return `<section class="pg-block pg-practice"><h5>${esc(GROWN.title)}</h5>
    <p class="pg-cur">${esc(GROWN.totals(t))} ${esc(GROWN.days(days))}</p>
    <p class="pg-cur">${esc(GROWN.hints(t.misses, t.pause))}</p>
    ${hard.length ? `<p class="pg-cur">${esc(GROWN.hard(hard.map(r => r.title).join(", ")))}</p>` : ""}
    <div class="tbl pg-tbl"><table><thead><tr>${GROWN.th.map(h => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(tr).join("")}</tbody></table></div>
    <p class="foot">${esc(GROWN.ngss)}: ${esc(GROWN.ngssNote)}</p></section>`;
}

// ---------- this computer's numbers (GET /api/brain/summary), on the playing cadet's card ----------
export const COMPUTER = {
  title: "Talking with the app",
  note: "Every cadet on this computer, last 30 days. From the voice-guide log, when it's on. Counts only, never words.",
  off: "The voice-guide log is off, so there are no talk counts. Turn it on in Settings, Voice log and playtest.",
  talk: c => `${c.turns} turns on ${c.days} day${c.days === 1 ? "" : "s"}: ${c.voice} by voice, ${c.typed} typed.`,
  heard: c => `The app answered ${c.answered}, and let ${c.passed_by} pass that weren't meant for it.`,
  room: r => `Room: calm ${r.calm}, busy ${r.busy}, too loud ${r.loud}.`,
  safetyTitle: "Safety",
  safety: s => `${s.guarded} turn${s.guarded === 1 ? "" : "s"} kept private by the privacy guard or the word filter. Nothing leaves this computer.`,
  care: n => (n ? `${n} time${n === 1 ? "" : "s"} since the app opened, CAPCOM suggested a break and talking to a grown-up.` : ""),
  adaptTitle: "What the app adapted",
  adapt: a => `Learned ${a.names} name${a.names === 1 ? "" : "s"} the way this cadet says them. Waits ${a.wait_s} s before answering${a.waits_longer ? " (a little longer, so the cadet can finish)" : ""}.`,
  adaptMore: "See or reset it in What the app has learned, below.",
  controlsTitle: "Your controls",
  controls: ["Voice log and playtest: turn the log on or off, delete it, or export a playtest.", "What the app has learned: remove a name or reset learning.", "Reset Outpost Luna: start over, and erase progress if you want."],
};
/** The computer block (pure). s: GET /api/brain/summary's body or null. */
export function computerHtml(s) {
  const c = (s && s.talk) || null, sf = (s && s.safety) || { guarded: 0, care: 0 }, a = s && s.adapted;
  return `<section class="pg-block pg-computer"><h5>${esc(COMPUTER.title)}</h5>
      <p class="set-help">${esc(COMPUTER.note)}</p>
      ${c && c.turns ? `<p class="pg-cur">${esc(COMPUTER.talk(c))}</p><p class="pg-cur">${esc(COMPUTER.heard(c))}</p><p class="pg-cur">${esc(COMPUTER.room(c.room))}</p>`
        : `<p class="pg-cur">${esc(COMPUTER.off)}</p>`}</section>
    <section class="pg-block"><h5>${esc(COMPUTER.safetyTitle)}</h5><p class="pg-cur">${esc(COMPUTER.safety(sf))}</p>${sf.care ? `<p class="pg-cur">${esc(COMPUTER.care(sf.care))}</p>` : ""}</section>
    ${a ? `<section class="pg-block"><h5>${esc(COMPUTER.adaptTitle)}</h5><p class="pg-cur">${esc(COMPUTER.adapt(a))} ${esc(COMPUTER.adaptMore)}</p></section>` : ""}
    <section class="pg-block"><h5>${esc(COMPUTER.controlsTitle)}</h5><ul class="pg-ctl">${COMPUTER.controls.map(t => `<li>${esc(t)}</li>`).join("")}</ul></section>`;
}

/** The practice counts saved for another cadet on this computer (their profile snapshot, prefs.js). */
export function brainOf(profileId, storage = typeof localStorage !== "undefined" ? localStorage : null) {
  try {
    const s = JSON.parse(storage.getItem("outpost-profiles") || "null");
    if (!s || s.active === profileId || !Array.isArray(s.list)) return store.load(storage);
    const p = s.list.find(x => x && x.id === profileId);
    return store.clean(JSON.parse((p && p.data && p.data[store.KEY]) || "null"));
  } catch (e) { return store.blank(); }
}

// ---------- the drawer ----------
async function getJson(fetchFn, url) { try { const r = await fetchFn(url); return r && r.ok ? await r.json() : null; } catch (e) { return null; } }

/** Wire the drawer. setMode / editCallSign come from main.js; say speaks a line when voice opened it. */
export function installBrain({ setMode = () => {}, editCallSign = () => {}, fetchFn = typeof fetch === "function" ? fetch : null, doc = document } = {}) {
  const dlg = doc.createElement("dialog");
  dlg.className = "about brain"; dlg.id = "brain"; dlg.setAttribute("aria-labelledby", "brainTitle");
  dlg.innerHTML = `<div class="about-bar"><span class="eyebrow">${icon("sparkle", { size: 16 })}${esc(COPY.title)}</span><button class="x" type="button" data-bm-close aria-label="${esc(COPY.close)}">&times;</button></div>
    <div class="about-body bm-body" data-bm-body aria-live="polite"><p class="set-help" role="status">${esc(COPY.loading)}</p></div>`;
  doc.body.append(dlg);
  const btn = doc.getElementById("brainBtn"), body = dlg.querySelector("[data-bm-body]");
  let course = null;
  async function fill() {
    if (!course && fetchFn) { const c = await getJson(fetchFn, "/api/academy/course"); course = c && Array.isArray(c.lessons) ? c.lessons : null; }
    const me = readCadets().find(c => c.active) || { academy: { badges: [] }, flown: [], callsign: "" };
    const learned = fetchFn ? await getJson(fetchFn, `/api/learn?profile=${activeProfile()}`) : null;
    body.innerHTML = cadetHtml({ callsign: callSign.get(), academy: me.academy, flown: me.flown, lessons: course || [], brain: store.load(), learned: learned && learned.learned });
    const cs = body.querySelector("[data-bm-cs]"), go = body.querySelector("[data-bm-go]");
    if (cs) cs.onclick = () => { dlg.close(); setMode("academy"); setTimeout(() => editCallSign(), 450); };
    if (go) go.onclick = () => { dlg.close(); setMode("academy"); };
  }
  const api = {
    open() {
      if (dlg.open) return;
      try { dispatchEvent(new CustomEvent("outpost:modal-open", { detail: { kind: "brain" } })); } catch (e) { /* Settings steps aside */ }
      dlg.showModal(); body.scrollTop = 0; if (btn) btn.setAttribute("aria-expanded", "true");
      fill();
    },
    close() { if (dlg.open) dlg.close(); },
    toggle() { if (dlg.open) dlg.close(); else api.open(); },
    get isOpen() { return dlg.open; },
  };
  dlg.querySelector("[data-bm-close]").onclick = () => dlg.close();
  dlg.addEventListener("close", () => { if (btn) { btn.setAttribute("aria-expanded", "false"); btn.focus(); } });
  dlg.addEventListener("click", e => { if (e.target === dlg) dlg.close(); });   // the backdrop
  if (btn) btn.onclick = () => api.open();
  O.brain = api;
  return api;
}
