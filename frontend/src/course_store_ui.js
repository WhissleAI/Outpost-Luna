// Settings → For grown-ups → Course storage (docs/COURSES.md §4.2): download, remove and switch courses. The Moon is
// built in. A course pack downloads from the same catalog and Dropbox folder as the app's other downloads
// (backend/app/course_packs.py; the desktop app does the download). Removing a course keeps its patches; removing the
// course being played switches to the Moon first. School network mode blocks a download and says so; so does a full
// disk. Behind the grown-up hold, so a kid can switch courses (the top-bar chip) but not download or delete one; the
// one exception is the first-run course pick (course_pick.js): a new cadet may download one catalog course, once.
import { COURSE_KEY, courseState, setCourse, syncCourse, REMOVED_KEY } from "./courses.js";
import { size } from "./storage_ui.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || {}) : {};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  title: "Course storage",
  line: "Courses download once and stay on this computer. Removing one keeps its patches.",
  moon: "Built in",
  playing: "Playing",
  get: s => `Get (${s})`,
  queued: "Waiting to download…",
  downloading: "Downloading…",
  downloadingPct: n => `Downloading… ${n}%`,   // [arch QA] the real percent (it said "Downloading…" only)
  verify: "Checking the download…",
  install: "Installing…",
  installed: "On this computer",
  play: "Switch to it",
  remove: "Remove",
  sure: "Remove? Tap again",
  removed: "Removed. Its patches stay.",
  school: "Off on the school network.",
  free: s => `Free space: ${s}.`,
  none: "No other courses yet.",
  offline: "Couldn't reach the app. Try again.",
  // [course switch] the playing course's own videos and an outdated pack's update download in the background
  updating: n => (n != null ? `Getting the new course files… ${n}%` : "Getting the new course files…"),
  videos: (r, t, n) => `Getting its videos… ${r} of ${t}${n != null ? ` (${n}%)` : ""}`,
  videosWait: { offline: k => `${k} ${k === 1 ? "video" : "videos"} still to get. They download when you're online.`,
    failed: k => `${k} ${k === 1 ? "video" : "videos"} didn't download yet. They try again next time.`,
    school: k => `${k} ${k === 1 ? "video is" : "videos are"} off on the school network.`,
    off: k => `${k} ${k === 1 ? "video plays" : "videos play"} from the internet.` },
  videosDone: t => `All ${t} videos saved.`,
};
const pct = x => (typeof x === "number" && isFinite(x) ? Math.max(0, Math.min(100, Math.round(100 * x))) : null);

/** The playing course's downloads, as a row note (pure): {note, bar (0-100 | null), busy}. */
export function dlNote(p) {
  if (!p || p.state !== "installed") return { note: "", bar: null, busy: false };
  if (p.updating) return { note: COPY.updating(pct(p.progress)), bar: pct(p.progress) ?? 0, busy: true };
  const v = p.videos;
  if (!v || !v.total || v.state === "none") return { note: "", bar: null, busy: false };
  if (v.state === "downloading" || v.state === "paused") return { note: COPY.videos(v.ready, v.total, pct(v.progress)), bar: pct(v.progress) ?? 0, busy: true };
  if (v.state === "waiting") return { note: (COPY.videosWait[v.reason] || COPY.videosWait.offline)(v.total - v.ready), bar: null, busy: false };
  return { note: COPY.videosDone(v.total), bar: null, busy: false };
}

/** One row's view (pure): {id, title, sub, actions: [{act, label}], note}. */
export function rowOf(p, { moon = false } = {}) {
  if (moon) return { id: "moon", title: "The Moon", sub: [COPY.moon, courseState.active === "moon" ? COPY.playing : ""].filter(Boolean).join(" · "),
    actions: courseState.active === "moon" ? [] : [{ act: "play", label: COPY.play }], note: "" };
  const sub = [size(p.size), p.version ? `v${p.version}` : "", p.active ? COPY.playing : ""].filter(Boolean).join(" · ");
  const r = { id: p.id, title: p.title.replace(/^Course:\s*/, ""), sub, actions: [], note: "" };
  if (p.state === "installed") {
    r.actions = [...(p.active ? [] : [{ act: "play", label: COPY.play }]), { act: "remove", label: COPY.remove }];
    const d = dlNote(p);
    r.note = d.note; r.bar = d.bar; r.busy = d.busy;
  }
  else if (p.state === "downloading") {
    const n = pct(p.progress);
    r.note = p.phase === "install" ? COPY.install : p.phase === "verify" || n === 100 ? COPY.verify : n != null ? COPY.downloadingPct(n) : COPY.downloading;
    r.bar = n ?? 0; r.busy = true;
  }
  else if (p.state === "queued") r.note = COPY.queued;
  else if (p.blocked) r.note = COPY.school;
  else { r.actions = [{ act: "get", label: COPY.get(size(p.size)) }]; if (p.state === "failed") r.note = p.reason || ""; }
  return r;
}

/** The part's HTML (pure). d: GET /api/courses/packs. */
export function listHtml(d) {
  const packs = (d && d.packs) || [];
  const rows = [rowOf(null, { moon: true }), ...packs.map(p => rowOf(p))];
  return `<ul class="crs-store">${rows.map(r => `<li data-crs-row="${esc(r.id)}"><span class="crs-name"><b>${esc(r.title)}</b><small>${esc(r.sub)}</small></span>
    <span class="crs-acts">${r.actions.map(a => `<button type="button" class="btn${a.act === "get" ? "" : " btn-quiet"}" data-crs-act="${a.act}" data-id="${esc(r.id)}">${esc(a.label)}</button>`).join("")}</span>
    ${r.note ? `<small class="crs-note${r.busy ? " is-dl" : ""}" role="status">${esc(r.note)}</small>` : ""}
    ${r.bar != null ? `<span class="crs-bar" role="progressbar" aria-label="${esc(r.note)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${r.bar}"><i style="width:${Math.max(4, r.bar)}%"></i></span>` : ""}</li>`).join("")}</ul>
    ${packs.length ? "" : `<p class="set-help">${esc(COPY.none)}</p>`}
    ${d && d.free_bytes != null ? `<p class="set-help">${esc(COPY.free(size(d.free_bytes)))}</p>` : ""}`;
}

/** Something is on its way (a pack download, an update, the playing course's videos): Course storage keeps polling. */
export const busy = d => !!(d && (d.packs || []).some(p => p.state === "queued" || p.state === "downloading" || dlNote(p).busy));

/** A course arrived or left: the registry again, and the top-bar chip (it shows once two courses are installed). */
const refreshChip = fetchFn => syncCourse({ fetchFn }).then(() => { if (O.courseSwitch) O.courseSwitch.paint(); }).catch(() => {});

let last = null;
const load = (fetchFn = fetch) => fetchFn("/api/courses/packs").then(r => (r.ok ? r.json() : null))
  .then(d => { last = d; if (O.courseSwitch) O.courseSwitch.paint(); return d; }).catch(() => null);
/** A catalog course this computer could download (the chip's "Get more courses" with only the Moon installed). Pure. */
export const moreCourses = (d = last) => !!(d && (d.downloadable || d.managed) && (d.packs || []).some(p => p.state !== "installed"));

const section = {
  id: "courses", title: COPY.title, after: "progress", grownup: true,
  html: () => (last && !(last.packs || []).length && courseState.courses.length < 2 ? "" :
    `<p class="set-help">${esc(COPY.line)}</p><div data-crs-store>${last ? listHtml(last) : "…"}</div><p class="set-help crs-msg" role="status" data-crs-msg></p>`),
  bind(el, { fetchFn = typeof fetch === "function" ? fetch : null } = {}) {
    const box = el.querySelector("[data-crs-store]"), msg = el.querySelector("[data-crs-msg]");
    if (!box || !fetchFn) return;
    let alive = true, poll = 0, armed = null;
    const paint = d => { if (!alive) return; if (d) box.innerHTML = listHtml(d); };
    const watch = () => {   // while something downloads: every 2 s until it lands or fails
      clearInterval(poll);
      poll = setInterval(async () => {
        const d = await load(fetchFn); paint(d);
        if (!busy(d)) { clearInterval(poll); refreshChip(fetchFn); }
      }, 2000);
    };
    load(fetchFn).then(d => { paint(d); if (busy(d)) watch(); });
    box.addEventListener("click", async e => {
      const b = e.target.closest("[data-crs-act]"); if (!b) return;
      const id = b.dataset.id, act = b.dataset.crsAct;
      msg.textContent = "";
      if (act === "play") { b.disabled = true; if (!(await setCourse(id, { fetchFn }))) { b.disabled = false; msg.textContent = COPY.offline; } return; }
      if (act === "remove" && armed !== id) { armed = id; b.textContent = COPY.sure; return; }
      b.disabled = true;
      try {
        const r = await fetchFn(`/api/courses/packs/${encodeURIComponent(id)}/${act === "get" ? "get" : "remove"}`, { method: "POST" });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { msg.textContent = d.detail || COPY.offline; b.disabled = false; return; }
        if (act === "remove") {
          msg.textContent = COPY.removed;
          // it was being played: the Moon now (its patches stay; the choice goes, so it doesn't come back with a re-download)
          if (courseState.active === id) {
            try { localStorage.removeItem(COURSE_KEY); } catch (e) { /* */ }
            // [arch QA] the map says what happened after the reload (academy/ui.js), never a silent jump to the Moon
            try { sessionStorage.setItem(REMOVED_KEY, String((courseState.info && courseState.info.title) || id)); } catch (e) { /* */ }
            location.reload(); return;
          }
        }
        paint(await load(fetchFn));
        if (act === "get" && d.state !== "installed") watch();
        if (act === "get" && d.state === "installed") refreshChip(fetchFn);
      } catch (x) { msg.textContent = COPY.offline; b.disabled = false; }
      armed = null;
    });
    return { destroy() { alive = false; clearInterval(poll); } };
  },
};
if (typeof window !== "undefined") {
  (O.settingsSections = O.settingsSections || []).push(section);
  if (typeof fetch === "function" && typeof document !== "undefined") load();
}
export default section;
