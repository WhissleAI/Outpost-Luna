// Settings → For grown-ups → Progress: a summary for parents and teachers, one card per call sign on this computer.
// It reads only what the app already keeps (nothing new is tracked or stored):
//   - each cadet's Flight School progress ("atm-academy": patches, qualified, the half-done lesson) and call sign, from
//     the live keys for the cadet playing and from the cadet snapshots in "outpost-profiles" for the others (prefs.js);
//   - missions flown ("outpost-missions-flown:<call sign>", explorer.js), and, for a mission the app still holds while it
//     runs, its debrief (GET /api/mission/{id}/debrief: stars, grade, the three checks, "Try next");
//   - the paused mission on this computer (GET /api/mission/saved);
//   - lesson titles and patches from the course (GET /api/academy/course). Class lessons (track "class") are listed
//     by pack, apart from NASA's: they never count toward "n of 9 patches".
// "Print" prints the sheet alone (progress.css, imported by main.js so this module loads under node --test, @media print): one cadet per page, light paper, no app chrome.
// Pure builders below (tests/progress.test.js); the section object at the end plugs into Settings (a11y.js).
import { icon } from "./assets/icons.js";
import { anyPatch as defaultPatch, registerClassLessons } from "./academy/class_patch.js";   // Class lessons: the same letter patch as on the map
import { coreLessons, fieldLessons, isExplorer, isField, unlocked } from "./explorer.js";
import { debriefStory } from "./mission/objective.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || {}) : {};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  title: "Progress",
  line: "Lessons, patches and missions for each cadet on this computer.",
  print: "Print",
  loading: "Loading progress…",
  none: "No cadets yet.",
  newCadet: "New cadet",
  playing: "Playing",
  qualified: "Qualified",
  lessons: "Lessons",
  patches: "Patches",
  missions: "Missions",
  nasaPatches: "NASA patches",
  noPatches: "No patches yet.",
  inProgress: "In progress",
  missionsTitle: "Missions",
  missionNo: n => `Mission ${n}`,
  missionCounted: "Flown to the end. Details show while the app is open.",
  paused: (site, day) => `Paused at ${site}, day ${day} of 10.`,
  classTitle: "Class lessons",
  done: "Done",
  notYet: "Not yet",
  tryTitle: "Try next",
  grade: "Grade",
  stars: n => `${n} of 3 stars`,
  step: (i, n) => `step ${i + 1} of ${n}`,
  nextLesson: t => `Lesson: ${t}.`,
  nextRide: "The check ride, to take command.",
  nextField: t => `Field School: ${t}.`,
  nextBonus: t => `Bonus lesson: ${t}.`,
  nextClass: t => `Class lesson: ${t}.`,
  nextMission: "A mission at a new site.",
  firstMission: "A first mission, from the Mission tab.",
  printedOn: d => `Outpost Luna progress · ${d}`,
};

// ---------- reading what is saved ----------
const parse = s => { try { return JSON.parse(s || "null"); } catch (e) { return null; } };
const get = (storage, k) => { try { return storage ? storage.getItem(k) : null; } catch (e) { return null; } };
const flownKey = cs => "outpost-missions-flown:" + (cs || "cadet");

function academyOf(raw) {
  const p = parse(raw);
  return { badges: p && Array.isArray(p.badges) ? p.badges.filter(b => typeof b === "string") : [], qualified: !!(p && p.qualified),
    steps: p && p.steps && typeof p.steps === "object" ? p.steps : {}, current: p && typeof p.current === "string" ? p.current : null };
}

/** Every cadet profile on this computer → [{id, active, callsign, academy, flown}]. The playing cadet's data is in the
 *  live keys; the others' in their snapshot (prefs.js switchProfile). Missions flown are keyed by call sign. */
export function readCadets(storage = typeof localStorage !== "undefined" ? localStorage : null) {
  const s = parse(get(storage, "outpost-profiles"));
  const list = s && Array.isArray(s.list) && s.list.length ? s.list : [{ id: "p1", data: null }];
  const active = s && typeof s.active === "string" ? s.active : list[0].id;
  return list.filter(p => p && typeof p.id === "string").map(p => {
    const live = p.id === active, d = (!live && p.data && typeof p.data === "object") ? p.data : {};
    const read = k => (live ? get(storage, k) : (d[k] ?? null));
    const callsign = String(read("outpost-callsign") || "").slice(0, 18);
    const fl = parse(get(storage, flownKey(callsign)));
    return { id: p.id, active: live, callsign, academy: academyOf(read("atm-academy")), flown: Array.isArray(fl) ? fl.filter(x => typeof x === "string") : [] };
  });
}

// ---------- one cadet's summary (pure) ----------
const isClass = l => !!(l && l.track === "class");
const badgeOf = l => (l && l.badge && l.badge.id) || "";

/** {nasa, core, field, classes, current, next} for one cadet against the course's lessons. */
export function summarize(cadet, lessons = []) {
  const ls = (lessons || []).filter(l => l && l.id && l.badge);
  const got = new Set(cadet.academy.badges), has = l => got.has(badgeOf(l));
  const nasa = ls.filter(l => !isClass(l)), core = coreLessons(nasa), field = fieldLessons(nasa);
  const flown = cadet.flown.length, q = cadet.academy.qualified;
  const open = l => unlocked(l, flown, q);
  // Class lessons by pack, in course order
  const packs = [];
  ls.filter(isClass).forEach(l => {
    const pk = l.pack || {}, id = pk.id || "class";
    let g = packs.find(x => x.id === id); if (!g) packs.push(g = { id, title: pk.title || COPY.classTitle, lessons: [] });
    g.lessons.push({ id: l.id, title: l.title, badge: l.badge, done: has(l) });
  });
  // the half-done lesson (resume point)
  const cur = cadet.academy.current && ls.find(l => l.id === cadet.academy.current);
  const st = cur && cadet.academy.steps[cur.id];
  const current = cur && st && Number.isInteger(st.i) && st.i > 0 && !has(cur) ? { title: cur.title, i: st.i, n: Array.isArray(cur.steps) ? cur.steps.length : st.n } : null;
  // what to try next: up to two, in the order the app itself opens them
  const next = [];
  const nc = core.find(l => !has(l) && open(l));
  const ride = nasa.find(l => l.ride);
  if (nc) next.push(COPY.nextLesson(nc.title));
  else if (ride && !q) next.push(COPY.nextRide);
  const nf = field.find(l => !has(l) && open(l)); if (nf && next.length < 2) next.push(COPY.nextField(nf.title));
  const nb = nasa.find(l => isExplorer(l) && !has(l) && open(l)); if (nb && next.length < 2) next.push(COPY.nextBonus(nb.title));
  const ncl = ls.find(l => isClass(l) && !has(l)); if (ncl && next.length < 2) next.push(COPY.nextClass(ncl.title));
  if (next.length < 2 && q) next.push(flown ? COPY.nextMission : COPY.firstMission);
  return {
    nasa: { earned: nasa.filter(has).map(l => ({ id: l.id, name: l.badge.name || l.title, track: l.ride ? "ride" : isField(l) ? "field" : isExplorer(l) ? "explorer" : "core" })), total: nasa.length },
    core: { done: core.filter(has).length, of: core.length },
    classes: packs, current, next: next.slice(0, 2),
  };
}

// ---------- HTML ----------
/** A lesson's patch art: the app's own patch (by lesson id, then badge id); a class lesson without art gets a round
 *  badge with its glyph, in the same patch frame. */
export function patchArt(id, badge, { patch = defaultPatch, earned = true, size = 44 } = {}) {
  const svg = patch(id, { earned, size }) || (badge && badge.id ? patch(badge.id, { earned, size }) : "");
  if (svg) return svg;
  const g = esc(String((badge && (badge.glyph || badge.name)) || "?").slice(0, 2).toUpperCase());
  return `<span class="pg-glyph ${earned ? "is-earned" : "is-locked"}" style="--s:${+size || 44}px" aria-hidden="true">${g}</span>`;
}

const starsHtml = n => `<span class="mx-bigstars pg-stars" role="img" aria-label="${esc(COPY.stars(n))}">${[0, 1, 2].map(k =>
  `<span class="${k < n ? "is-on" : ""}" style="--i:${k}">${icon("star", { size: 20 })}</span>`).join("")}</span>`;

/** One mission row: with its debrief (stars, grade, site, the three checks, "Try next") or just counted. */
export function missionHtml(n, d) {
  if (!d || !d.outcome || d.outcome === "in_progress") return `<li class="pg-mission is-counted"><b>${esc(COPY.missionNo(n))}</b><small>${esc(COPY.missionCounted)}</small></li>`;
  const story = debriefStory(d, {}), site = String((d.site && d.site.name) || "").split(" (")[0];
  const stars = d.stars != null ? Math.max(0, Math.min(3, +d.stars || 0)) : null;
  return `<li class="pg-mission">
    <div class="pg-mhead">${stars != null ? starsHtml(stars) : ""}<span class="pg-mname"><b>${esc(COPY.missionNo(n))}${site ? ` · ${esc(site)}` : ""}</b></span>
      ${d.grade ? `<dl class="mx-score pg-score"><div><dt>${esc(COPY.grade)}</dt><dd class="mx-grade">${esc(d.grade)}</dd></div></dl>` : ""}</div>
    <ul class="mx-checks pg-checks">${story.checks.map(c => `<li class="${c.ok ? "is-ok" : "is-no"}"><span class="mx-ck" aria-hidden="true">${icon(c.ok ? "check" : "close", { size: 16 })}</span><span class="sr-only">${c.ok ? "Done: " : "Not yet: "}</span>${esc(c.text)}</li>`).join("")}</ul>
    ${story.tryLine ? `<p class="mx-try pg-mtry"><b>${esc(COPY.tryTitle)}</b> ${esc(story.tryLine)}</p>` : ""}</li>`;
}

/** One cadet's card. debriefs: {missionId: debrief|null}. */
export function cadetHtml(cadet, lessons, { debriefs = {}, patch = defaultPatch } = {}) {
  const s = summarize(cadet, lessons), name = cadet.callsign || COPY.newCadet;
  const stat = (k, v) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`;
  const tag = cadet.academy.qualified ? `<span class="set-tag pg-q">${esc(COPY.qualified)}</span>` : "";
  const nasaPatches = s.nasa.earned.length ? `<ul class="pg-patches">${s.nasa.earned.map(p =>
    `<li>${patchArt(p.id, null, { patch, size: 44 })}<span>${esc(p.name)}</span></li>`).join("")}</ul>` : `<p class="set-help">${esc(COPY.noPatches)}</p>`;
  const flown = cadet.flown.slice(-5), first = cadet.flown.length - flown.length;
  const missions = cadet.flown.length ? `<section class="pg-block"><h5>${esc(COPY.missionsTitle)}</h5>
    <ul class="pg-missions">${flown.map((id, k) => missionHtml(first + k + 1, debriefs[id])).reverse().join("")}</ul></section>` : "";
  const classes = s.classes.map(g => `<section class="pg-block pg-class"><h5>${esc(COPY.classTitle)} · ${esc(g.title)}</h5>
    <ul class="pg-lessons">${g.lessons.map(l => `<li class="${l.done ? "is-done" : ""}">${patchArt(l.id, l.badge, { patch, earned: l.done, size: 36 })}
      <span>${esc(l.title)}</span><small>${esc(l.done ? COPY.done : COPY.notYet)}</small></li>`).join("")}</ul></section>`).join("");
  return `<article class="pg-cadet${cadet.active ? " is-active" : ""}" data-cadet="${esc(cadet.id)}" aria-label="${esc(name)}">
    <header class="pg-head"><span class="set-av" aria-hidden="true">${esc(name.slice(0, 1).toUpperCase())}</span>
      <h4>${esc(name)}</h4>${tag}${cadet.active ? `<span class="set-tag pg-now">${esc(COPY.playing)}</span>` : ""}</header>
    <dl class="mx-score pg-stats">${stat(COPY.lessons, `${s.core.done}<small> of ${s.core.of}</small>`)}${stat(COPY.nasaPatches, `${s.nasa.earned.length}<small> of ${s.nasa.total}</small>`)}${stat(COPY.missions, cadet.flown.length)}</dl>
    ${s.current ? `<p class="pg-cur"><b>${esc(COPY.inProgress)}</b> ${esc(s.current.title)}, ${esc(COPY.step(s.current.i, s.current.n))}</p>` : ""}
    <section class="pg-block"><h5>${esc(COPY.patches)}</h5>${nasaPatches}</section>
    ${classes}${missions}
    ${s.next.length ? `<p class="mx-try pg-try"><b>${esc(COPY.tryTitle)}</b> ${s.next.map(esc).join(" ")}</p>` : ""}</article>`;
}

/** The whole sheet. saved: GET /api/mission/saved's body (the paused mission on this computer) or null. */
export function sheetHtml({ cadets = [], lessons = [], debriefs = {}, saved = null, patch = defaultPatch, date = "" } = {}) {
  if (!cadets.length) return `<p class="set-help">${esc(COPY.none)}</p>`;
  const pause = saved && saved.site_name ? `<p class="pg-paused">${esc(COPY.paused(String(saved.site_name).split(" (")[0], saved.day || 1))}</p>` : "";
  return `<div class="pg-sheet">${date ? `<p class="pg-printed">${esc(COPY.printedOn(date))}</p>` : ""}${pause}
    ${cadets.map(c => cadetHtml(c, lessons, { debriefs, patch })).join("")}</div>`;
}

/** The part's frame (drawn at once; bind() fills the sheet). */
export const zoneHtml = () => `<div class="pg-zone">
    <div class="pg-bar"><p class="set-help">${esc(COPY.line)}</p>
      <button type="button" class="btn" data-pg-print>${esc(COPY.print)}</button></div>
    <div data-pg-view aria-live="polite"><p class="set-help" role="status">${esc(COPY.loading)}</p></div></div>`;

// ---------- loading + print ----------
async function getJson(fetchFn, url) {
  try { const r = await fetchFn(url); return r && r.ok ? await r.json() : null; } catch (e) { return null; }
}
/** Everything the sheet needs, read-only: the course, the debriefs the app still holds, the paused mission. */
export async function loadData({ fetchFn, storage } = {}) {
  const cadets = readCadets(storage);
  const course = await getJson(fetchFn, "/api/academy/course");
  if (course && Array.isArray(course.lessons)) registerClassLessons(course.lessons);
  const ids = [...new Set(cadets.flatMap(c => c.flown.slice(-5)))].filter(id => /^m-[0-9a-f]{4,16}$/.test(id));
  const debriefs = {};
  await Promise.all(ids.map(async id => { debriefs[id] = await getJson(fetchFn, `/api/mission/${id}/debrief`); }));
  const saved = await getJson(fetchFn, "/api/mission/saved");
  return { cadets, lessons: (course && course.lessons) || [], debriefs, saved: saved && saved.saved !== undefined ? saved.saved : saved };
}

/** Print the sheet alone: a copy at the body's top level (#pgPrint), everything else hidden by progress.css. */
export function printSheet(html, { doc = document, win = window } = {}) {
  const old = doc.getElementById("pgPrint"); if (old) old.remove();
  const box = doc.createElement("div"); box.id = "pgPrint"; box.innerHTML = html;
  doc.body.append(box); doc.body.classList.add("pg-printing");
  const done = () => { doc.body.classList.remove("pg-printing"); box.remove(); win.removeEventListener("afterprint", done); };
  win.addEventListener("afterprint", done);
  win.print();
}

const section = {
  id: "progress", title: COPY.title, grownup: true, first: true,   // the first part in Settings → For grown-ups
  html: zoneHtml,
  bind(el, { fetchFn = typeof fetch === "function" ? fetch : null, storage = typeof localStorage !== "undefined" ? localStorage : null } = {}) {
    const view = el.querySelector("[data-pg-view]"), pr = el.querySelector("[data-pg-print]");
    if (!view || !fetchFn) return;
    let data = null, alive = true;
    loadData({ fetchFn, storage }).then(d => { if (!alive) return; data = d; view.innerHTML = sheetHtml(d); });
    if (pr) pr.onclick = () => {
      const date = new Date().toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
      printSheet(sheetHtml({ ...(data || { cadets: readCadets(storage) }), date }));
    };
    return { destroy() { alive = false; } };
  },
};
if (typeof window !== "undefined") (O.settingsSections = O.settingsSections || []).push(section);
export default section;
