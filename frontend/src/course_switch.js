// The course switcher (docs/COURSES.md §4.2): a chip next to the app name names the course being played; tapping it
// (or Enter / A on it, or saying "switch course") opens a short list of the installed courses. Picking one asks once
// ("Switch to Archaeology? Your Moon patches stay."), then switches (courses.js setCourse: the app reloads on the new
// course). P2 adds "Get more courses" (Settings → For grown-ups → Course storage, behind the hold) for courses that are
// not downloaded yet. The chip shows once two courses are installed, or (first-run pick round) with only the Moon when
// the catalog has a course this computer can download, so the feature is discoverable; hidden otherwise (the iPad).
// [course switch] Right after a switch the new course's videos (and an outdated pack's update) download in the
// background: the chip shows a thin, calm progress line under the name and says it in its label ("Course: Archaeology.
// Getting its videos… 40%"); it polls GET /api/courses/active/progress every few seconds only while something is on
// its way, then goes quiet. The name itself never changes (textContent stays the course's short name).
import { courseState, installed, setCourse, courseProgress, progressView } from "./courses.js";

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  chip: t => `Course: ${t}`,
  title: "Pick a course",
  line: "Each course keeps its own patches.",
  playing: "Playing",
  ask: t => `Switch to ${t}?`,
  keep: t => `Your ${t} patches stay.`,
  yes: "Switch",
  no: "Cancel",
  more: "Get more courses",
  failed: "Couldn't switch. Try again.",
  switching: "Switching…",
};

/** The chip's progress (pure): the progress answer -> {show, pct, label} (label: the chip's aria-label and tooltip). */
export function chipProgress(p, name) {
  const v = progressView(p);
  return v.busy ? { show: true, pct: v.pct, label: `${COPY.chip(name)}. ${v.label}` } : { show: false, pct: null, label: COPY.chip(name) };
}
export const POLL_MS = 3000;

/** The chip's label: the course's short name (labels.course, else the title). Pure. */
export const shortName = c => (c && ((c.labels && c.labels.course) || c.title)) || "Moon";

/** The list view's HTML (pure): one button per installed course, the playing one marked. */
export function listHtml(courses, active, { more = false } = {}) {
  return `<h2 class="crs-title" id="crsTitle">${esc(COPY.title)}</h2><p class="crs-line">${esc(COPY.line)}</p>
    <ul class="crs-list">${courses.map(c => `<li><button type="button" class="crs-item${c.id === active ? " is-on" : ""}" data-course="${esc(c.id)}"
      ${c.id === active ? 'aria-current="true"' : ""}><b>${esc(c.title)}</b><small>${esc(c.id === active ? COPY.playing : [c.subject, c.grades && `grades ${c.grades}`].filter(Boolean).join(" · "))}</small></button></li>`).join("")}</ul>
    <div class="crs-actions">${more ? `<button type="button" class="btn-quiet" data-crs-more>${esc(COPY.more)}</button>` : ""}<button type="button" class="btn-quiet" data-crs-close>${esc(COPY.no)}</button></div>`;
}
/** The confirm view's HTML (pure). */
export function confirmHtml(to, from) {
  return `<h2 class="crs-title" id="crsTitle">${esc(COPY.ask(to.title))}</h2><p class="crs-line">${esc(COPY.keep(shortName(from)))}</p>
    <p class="crs-err" role="status" data-crs-err></p>
    <div class="crs-actions"><button type="button" class="btn-primary" data-crs-yes="${esc(to.id)}">${esc(COPY.yes)}</button><button type="button" class="btn-quiet" data-crs-back>${esc(COPY.no)}</button></div>`;
}

/** Wire the chip and its dialog. -> {open, close, paint, isOpen}. */
export function installCourseSwitch({ chip = document.getElementById("courseChip"), doc = document, onMore = null, more = () => false, set = setCourse,
  fetchFn = typeof window !== "undefined" && typeof window.fetch === "function" ? window.fetch.bind(window) : null, pollMs = POLL_MS } = {}) {
  let box = null, back = null, dl = null, timer = 0, idle = 0;
  const visible = () => installed().length > 1 || (!!onMore && !!more());
  function paint() {
    if (!chip) return;
    chip.hidden = !visible();
    chip.textContent = shortName(courseState.info);
    paintProgress();
    document.documentElement.dataset.course = courseState.active;
  }
  function paintProgress() {
    if (!chip) return;
    const v = chipProgress(dl, shortName(courseState.info));
    chip.setAttribute("aria-label", v.label);
    if (!chip.dataset) return;   // (a bare test stub)
    if (v.show) {
      chip.dataset.dl = v.pct != null ? String(v.pct) : "";
      chip.title = v.label;
      if (chip.style) chip.style.setProperty("--crs-dl", `${v.pct != null ? v.pct : 8}%`);
    } else if ("dl" in chip.dataset) {
      delete chip.dataset.dl; chip.title = "";
      if (chip.style) chip.style.removeProperty("--crs-dl");
    }
  }
  /** Ask how far the course's downloads are; again in a few seconds while something is on its way. */
  async function watch() {
    clearTimeout(timer);
    if (!fetchFn || courseState.active === "moon") { if (dl) { dl = null; paintProgress(); } return null; }
    dl = await courseProgress({ fetchFn });
    paintProgress();
    const v = dl && dl.videos;
    // keep asking while busy; videos still to get but not on their way yet (the launch download starts a few seconds
    // after the app): ask twice more, slowly, then stop
    if (dl && dl.busy) { idle = 0; timer = setTimeout(watch, pollMs); }
    else if (v && v.state === "waiting" && v.reason !== "school" && v.reason !== "off" && idle < 2) { idle++; timer = setTimeout(watch, pollMs * 4); }
    return dl;
  }
  function close() {
    if (!box) return;
    box.remove(); box = null;
    if (chip) chip.setAttribute("aria-expanded", "false");
    if (back && back.focus) back.focus();
  }
  function view(html) {
    box.querySelector(".crs-card").innerHTML = html;
    const f = box.querySelector("[data-crs-yes]") || box.querySelector(".crs-item:not(.is-on)") || box.querySelector("[data-crs-more]") || box.querySelector("button");
    if (f) f.focus();
  }
  function open() {
    if (box || !visible()) return false;
    back = doc.activeElement;
    box = doc.createElement("div");
    box.className = "crs-scrim"; box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true"); box.setAttribute("aria-labelledby", "crsTitle");
    box.innerHTML = `<div class="crs-card"></div>`;
    doc.body.append(box);
    if (chip) chip.setAttribute("aria-expanded", "true");
    view(listHtml(installed(), courseState.active, { more: !!onMore }));
    box.addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } });
    box.addEventListener("click", async e => {
      if (e.target === box) return close();
      const b = e.target.closest("button"); if (!b) return;
      if (b.dataset.crsClose !== undefined) return close();
      if (b.dataset.crsBack !== undefined) return view(listHtml(installed(), courseState.active, { more: !!onMore }));
      if (b.dataset.crsMore !== undefined) { close(); if (onMore) onMore(); return; }
      if (b.dataset.course) {
        const to = installed().find(c => c.id === b.dataset.course);
        if (!to || to.id === courseState.active) return close();
        return view(confirmHtml(to, courseState.info));
      }
      if (b.dataset.crsYes) {
        b.disabled = true; b.textContent = COPY.switching;
        const ok = await set(b.dataset.crsYes);
        if (!ok && box) { b.disabled = false; b.textContent = COPY.yes; const er = box.querySelector("[data-crs-err]"); if (er) er.textContent = COPY.failed; }
      }
    });
    return true;
  }
  if (chip) {
    chip.setAttribute("aria-haspopup", "dialog"); chip.setAttribute("aria-expanded", "false");
    chip.addEventListener("click", () => (box ? close() : open()));
  }
  paint();
  watch();
  return { open, close, paint, isOpen: () => !!box, visible, watch, progress: () => dl, stop: () => clearTimeout(timer) };
}
