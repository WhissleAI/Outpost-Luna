// The first-run course pick (docs/COURSES.md §4.10): right after a new cadet picks a call sign, "Pick your course".
// The Moon is built in and starts now; every course in our catalog is listed with its one line, reading level and
// size. Picking a pack course downloads it through the same backend + desktop flow as Course storage
// (POST /api/courses/packs/<id>/get, the desktop's .want flag), shows real progress, then switches to it (the app
// reloads on the new course, as a switch always does). Offline, School network mode, a failed or stuck download: said
// plainly, and the cadet starts on the Moon ("You can get it later in For grown-ups → Course storage").
//
// Policy: this is the one place a kid may download a course, once, at first run, and only from our catalog. Removing
// a course stays behind the grown-up hold (Course storage). The choice is stored per call sign in the existing profile
// key "outpost-course" ("moon" written explicitly here, so a cadet who picked is never asked again); a cadet with no
// stored course and no call sign (a new cadet, a second call sign later) gets the pick.
// Pure helpers first (tests/course_pick.test.js), then the panel controller academy/ui.js mounts.
import { COURSE_KEY, DEFAULT_COURSE, validCourse, setCourse } from "./courses.js";
import { size } from "./storage_ui.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/** A one-shot for the reload after a switch: the map says the welcome on the new course. */
export const WELCOME_KEY = "outpost-course-welcome";

export const COPY = {
  title: "Pick your course",
  sub: "Each course keeps its own patches.",
  moonMeta: "Built in · starts now",
  onDisk: "On this computer",
  skip: "Skip",
  say: "Pick your course. The Moon starts now.",
  getting: t => `Getting ${t}…`,
  pct: n => `${n}%`,
  waiting: "Waiting to download…",
  instead: "Start on the Moon instead",
  offline: t => `You're offline, so ${t} can't download. Starting on the Moon.`,
  school: t => `School network mode is on, so ${t} can't download here. Starting on the Moon.`,
  failed: t => `${t} didn't download. Starting on the Moon.`,
  timeout: t => `${t} is taking too long. Starting on the Moon.`,
  later: "You can get it later in For grown-ups → Course storage.",
  go: "Start on the Moon",
  switching: t => `Opening ${t}…`,
  help: names => `Say ${names}. Or say skip.`,
};

// ---------------------------------------------------------------- pure
const titleOf = p => String((p && p.title) || "").replace(/^Course:\s*/, "") || (p && p.id) || "";
const gradesOf = g => (g ? `grades ${g}` : "");

/** The pick's options: the Moon first, then every catalog course (and any installed course the catalog does not list).
 *  listing: GET /api/courses/packs; courses: courseState.courses (GET /api/courses).
 *  -> [{id, title, line, meta, state, installed, blocked, size}] */
export function options(listing, courses = []) {
  const moon = (courses || []).find(c => c && c.id === DEFAULT_COURSE) || {};
  const out = [{ id: DEFAULT_COURSE, title: "The Moon", short: "Moon", line: moon.program || "Junior Astronaut Academy",
    meta: [gradesOf(moon.grades || "3-8"), COPY.moonMeta].filter(Boolean).join(" · "), installed: true, state: "installed", blocked: false, size: 0 }];
  const can = !!(listing && (listing.downloadable || listing.managed));
  for (const p of (listing && listing.packs) || []) {
    if (!p || !validCourse(p.id) || p.id === DEFAULT_COURSE) continue;
    const inst = p.state === "installed";
    if (!inst && !can) continue;   // nothing could fetch it here (the iPad shell): never offered
    out.push({ id: p.id, title: titleOf(p), short: titleOf(p), line: p.program || p.subject || "",
      meta: [gradesOf(p.grades), inst ? COPY.onDisk : size(p.size)].filter(Boolean).join(" · "),
      installed: inst, state: p.state || "missing", blocked: !!p.blocked, size: p.size || 0 });
  }
  for (const c of courses || []) {   // installed but not in the catalog (an offline-pack import, a bundled course)
    if (!c || c.id === DEFAULT_COURSE || c.status === "draft" || out.some(o => o.id === c.id)) continue;
    out.push({ id: c.id, title: c.title, short: (c.labels && c.labels.course) || c.title, line: c.program || c.subject || "",
      meta: [gradesOf(c.grades), COPY.onDisk].filter(Boolean).join(" · "), installed: true, state: "installed", blocked: false, size: 0 });
  }
  return out;
}

/** Does this cadet get the pick? Not when they already have a course stored, and not when the Moon is the only option. */
export function shouldOffer(opts, storage) {
  let stored = null;
  try { stored = storage ? storage.getItem(COURSE_KEY) : null; } catch (e) { stored = null; }
  return !validCourse(stored) && Array.isArray(opts) && opts.length > 1;
}

/** Store the choice for this call sign (the profile key "outpost-course"; "moon" too, so the pick never comes back). */
export function remember(id, storage) {
  try { if (storage) storage.setItem(COURSE_KEY, validCourse(id) ? id : DEFAULT_COURSE); } catch (e) { /* private mode */ }
}

const SKIP = /^(skip|skip it|skip this|not now|no thanks|no|nope|later|you pick|pick for me|any|just start|start|let s go|lets go|go)$/;
const flat = t => String(t || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
const norm = t => flat(t).replace(/^(okay |ok |um |uh |so |i want |i ll take |let s do |lets do |i pick |pick )+/, "").replace(/( please| course)+$/, "").trim();
const bare = t => t.replace(/^the /, "");
/** A spoken or typed turn on the pick -> a course id ("moon" for skip), or null. */
export function matchPick(text, opts) {
  const q = norm(text);
  if (!q) return null;
  if (SKIP.test(q) || SKIP.test(flat(text))) return DEFAULT_COURSE;
  for (const o of opts || []) {
    const names = [o.title, o.short, o.id].filter(Boolean).map(n => bare(norm(n)));
    if (names.includes(bare(q))) return o.id;
  }
  if (q.split(" ").length <= 4) for (const o of opts || []) {   // "the archaeology one", "moon please"
    const names = [o.title, o.short, o.id].filter(Boolean).map(n => bare(norm(n)));
    if (names.some(n => n.length > 3 && new RegExp(`\\b${n}\\b`).test(q))) return o.id;
  }
  return null;
}
/** The words the router and the ear listen for on this screen (Ctx.step_options). */
export const spokenNames = opts => [...new Set((opts || []).flatMap(o => [o.title, o.short]).filter(Boolean))];

/** Why a download stopped, from the backend's plain reason. */
export function whyOf(reason) {
  const r = String(reason || "");
  if (/school network/i.test(r)) return "school";
  if (/offline|internet|network error|can't reach|cannot reach/i.test(r)) return "offline";
  return "failed";
}
/** The line said and shown when a pack can't be had now. */
export const failLine = (why, title) => (COPY[why] || COPY.failed)(title);

const sleepMs = ms => new Promise(r => setTimeout(r, ms));
/** Get a course pack for the pick. -> {ok: true} | {ok: false, why: offline | school | failed | timeout, detail?}.
 *  Never throws. deps: fetchFn, online (navigator.onLine), onState({state, progress}), sleep, now, timeoutMs, pollMs,
 *  cancelled (() => true stops the wait; the desktop may still finish the download in the background). */
export async function getCourse(id, { fetchFn = typeof fetch === "function" ? fetch : null, online = () => (typeof navigator === "undefined" ? true : navigator.onLine !== false),
  onState = () => {}, sleep = sleepMs, now = () => Date.now(), timeoutMs = 180000, pollMs = 1000, cancelled = () => false } = {}) {
  if (id === DEFAULT_COURSE) return { ok: true };
  if (!fetchFn || !validCourse(id)) return { ok: false, why: "failed" };
  const list = async () => { try { const r = await fetchFn("/api/courses/packs"); return r.ok ? await r.json() : null; } catch (e) { return null; } };
  const d = await list();
  const p = d && (d.packs || []).find(x => x.id === id);
  if (!p) return { ok: false, why: "failed" };
  if (p.state === "installed") return { ok: true };
  if (p.blocked) return { ok: false, why: "school" };
  if (!online()) return { ok: false, why: "offline" };
  let st;
  try {
    const r = await fetchFn(`/api/courses/packs/${encodeURIComponent(id)}/get`, { method: "POST" });
    const j = await r.json().catch(() => ({}));
    if (r.status === 403) return { ok: false, why: "school", detail: j.detail };
    if (!r.ok) return { ok: false, why: whyOf(j.detail), detail: j.detail };
    st = j.state;
  } catch (e) { return { ok: false, why: online() ? "failed" : "offline" }; }
  if (st === "installed") return { ok: true };
  onState({ state: st || "queued" });
  const t0 = now();
  while (now() - t0 < timeoutMs) {
    await sleep(pollMs);
    if (cancelled()) return { ok: false, why: "cancelled" };
    const q = await list();
    const x = q && (q.packs || []).find(y => y.id === id);
    if (!x) continue;   // a blip: keep waiting
    if (x.state === "installed") { onState({ state: "installed", progress: 1 }); return { ok: true }; }
    if (x.state === "failed") return { ok: false, why: whyOf(x.reason), detail: x.reason };
    if (x.state === "missing") return { ok: false, why: online() ? "failed" : "offline" };   // the ask was dropped
    onState({ state: x.state, progress: x.progress });
  }
  return { ok: false, why: "timeout" };
}

// ---------------------------------------------------------------- views (pure HTML)
export function pickHtml(opts, eyebrow = "") {
  return `<div class="h-wrap crp-wrap">
      <div class="h-copy">${eyebrow ? `<p class="eyebrow">${esc(eyebrow)}</p>` : ""}<h1 class="h-title crp-title" id="aCrpTitle">${esc(COPY.title)}</h1></div>
      <div class="h-form crp-form" role="group" aria-labelledby="aCrpTitle">
        <p class="h-label crp-sub">${esc(COPY.sub)}</p>
        <ul class="crp-list">${opts.map((o, k) => `<li><button type="button" class="a-crs-opt${k === 0 ? " is-default" : ""}" data-crs="${esc(o.id)}">
          <span class="a-key" data-n="${k + 1}" aria-hidden="true">${k + 1}</span><span class="crp-txt"><b>${esc(o.title)}</b>${o.line ? `<span class="crp-line">${esc(o.line)}</span>` : ""}<small class="crp-meta">${esc(o.meta)}</small></span></button></li>`).join("")}</ul>
        <div class="crp-actions"><button type="button" class="btn-quiet" id="aCrpSkip">${esc(COPY.skip)}</button></div>
      </div>
    </div>`;
}
export function progressHtml(title, state = {}) {
  const pct = state.progress != null ? Math.round(100 * state.progress) : null;
  const label = pct != null ? COPY.pct(pct) : state.state === "queued" ? COPY.waiting : "";
  return `<div class="h-wrap crp-wrap"><div class="h-form crp-form" role="group" aria-labelledby="aCrpTitle">
      <h1 class="h-title crp-title" id="aCrpTitle">${esc(COPY.getting(title))}</h1>
      <div class="crp-bar" role="progressbar" aria-label="${esc(COPY.getting(title))}" aria-valuemin="0" aria-valuemax="100"${pct != null ? ` aria-valuenow="${pct}"` : ""}><i style="width:${pct != null ? pct : 4}%"></i></div>
      <p class="crp-state" role="status">${esc(label)}</p>
      <div class="crp-actions"><button type="button" class="btn-quiet" id="aCrpCancel">${esc(COPY.instead)}</button></div>
    </div></div>`;
}
export function failHtml(why, title) {
  return `<div class="h-wrap crp-wrap"><div class="h-form crp-form" role="group" aria-labelledby="aCrpTitle">
      <h1 class="h-title crp-title" id="aCrpTitle">${esc(failLine(why, title))}</h1>
      <p class="crp-later">${esc(COPY.later)}</p>
      <div class="crp-actions"><button type="button" class="btn-primary h-start" id="aCrpMoon">${esc(COPY.go)}</button></div>
    </div></div>`;
}

// ---------------------------------------------------------------- the controller
/** Mount the pick in the Flight School panel. onDone("moon") starts the Moon here (no reload); another course stores
 *  the choice and reloads into it (setCourse). -> {view, handleText(t), nav(intent), help(), names, destroy} */
export function mountPick(panel, { opts, say = () => {}, onDone = () => {}, eyebrow = "", storage = null, session = null,
  get = getCourse, set = setCourse, deps = {} } = {}) {
  let view = "pick", busy = false, gone = false, title = "";
  const S = storage || (typeof localStorage !== "undefined" ? localStorage : null);
  const SS = session || (typeof sessionStorage !== "undefined" ? sessionStorage : null);
  const focus = sel => { const b = panel.querySelector(sel); if (b && b.focus) b.focus({ preventScroll: true }); };
  const moon = () => { if (gone) return; gone = true; remember(DEFAULT_COURSE, S); onDone(DEFAULT_COURSE); };
  function pick() {
    view = "pick"; panel.innerHTML = pickHtml(opts, eyebrow);
    panel.querySelectorAll(".a-crs-opt").forEach(b => { b.onclick = () => choose(b.dataset.crs); });
    panel.querySelector("#aCrpSkip").onclick = moon;
    focus(".a-crs-opt.is-default");
  }
  function fail(why) {
    if (gone) return;
    view = "fail"; busy = false; panel.innerHTML = failHtml(why, title);
    panel.querySelector("#aCrpMoon").onclick = moon;
    focus("#aCrpMoon");
    say([failLine(why, title), COPY.later]);
  }
  async function choose(id) {
    if (busy || gone) return;
    const o = opts.find(x => x.id === id);
    if (!o || id === DEFAULT_COURSE) return moon();
    busy = true; title = o.title;
    if (!o.installed) {
      view = "progress"; panel.innerHTML = progressHtml(title, { state: "queued" });
      panel.querySelector("#aCrpCancel").onclick = moon;
      focus("#aCrpCancel");
      say(COPY.getting(title));
      const paint = st => {
        if (view !== "progress" || gone) return;
        const bar = panel.querySelector(".crp-bar"), lab = panel.querySelector(".crp-state");
        const pct = st.progress != null ? Math.round(100 * st.progress) : null;
        if (bar) { bar.querySelector("i").style.width = `${pct != null ? pct : 4}%`; if (pct != null) bar.setAttribute("aria-valuenow", String(pct)); }
        if (lab) lab.textContent = pct != null ? COPY.pct(pct) : st.state === "queued" ? COPY.waiting : "";
      };
      const r = await get(id, { ...deps, onState: paint, cancelled: () => gone });
      if (gone) return;
      if (!r.ok) return fail(r.why);
    }
    if (gone) return;
    view = "switching";
    try { if (SS) SS.setItem(WELCOME_KEY, "1"); } catch (e) { /* */ }
    const lab = panel.querySelector(".crp-state"); if (lab) lab.textContent = COPY.switching(title);
    const ok = await set(id, { storage: S || undefined });   // stores "outpost-course", tells the backend, reloads
    if (!ok) { try { if (SS) SS.removeItem(WELCOME_KEY); } catch (e) { /* */ } fail("failed"); }
  }
  const names = spokenNames(opts);
  const helpLine = () => COPY.help(names.filter((n, i, a) => a.findIndex(m => bare(norm(m)) === bare(norm(n))) === i).slice(0, 3).join(", or "));
  pick();
  say(COPY.say);
  return {
    get view() { return view; }, names,
    handleText(t) {
      if (view === "pick") { const id = matchPick(t, opts); if (id) choose(id); else say(helpLine()); return true; }
      if (view === "progress") { if (matchPick(t, [opts[0]]) === DEFAULT_COURSE) moon(); return true; }
      if (view === "fail") { if (/\b(start|ok|okay|moon|next|yes|yeah|go|sure)\b/.test(norm(t)) || !norm(t)) moon(); return true; }
      return true;
    },
    nav(intent) {
      if (["no", "decline_offer", "back", "skip_tour"].includes(intent)) { if (view !== "switching") moon(); return true; }
      if (["next", "start", "accept_offer", "yes"].includes(intent)) {
        if (view === "pick") { const f = panel.ownerDocument && panel.ownerDocument.activeElement; const id = f && f.dataset && f.dataset.crs; choose(id || DEFAULT_COURSE); }
        else if (view === "fail") moon();
        return true;
      }
      return false;
    },
    help: () => (view === "pick" ? helpLine() : view === "fail" ? COPY.later : COPY.instead),
    destroy() { gone = true; },
  };
}
