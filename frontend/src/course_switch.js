// The course switcher (docs/COURSES.md §4.2): a chip next to the app name names the course being played; tapping it
// (or Enter / A on it, or saying "switch course") opens a short list of the installed courses. Picking one asks once
// ("Switch to Archaeology? Your Moon patches stay."), then switches (courses.js setCourse: the app reloads on the new
// course). P2 adds "Get more courses" (Settings → For grown-ups → Course storage, behind the hold) for courses that are
// not downloaded yet. The chip shows once two courses are installed, or (first-run pick round) with only the Moon when
// the catalog has a course this computer can download, so the feature is discoverable; hidden otherwise (the iPad).
import { courseState, installed, setCourse } from "./courses.js";

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
export function installCourseSwitch({ chip = document.getElementById("courseChip"), doc = document, onMore = null, more = () => false, set = setCourse } = {}) {
  let box = null, back = null;
  const visible = () => installed().length > 1 || (!!onMore && !!more());
  function paint() {
    if (!chip) return;
    chip.hidden = !visible();
    chip.textContent = shortName(courseState.info);
    chip.setAttribute("aria-label", COPY.chip(shortName(courseState.info)));
    document.documentElement.dataset.course = courseState.active;
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
  return { open, close, paint, isOpen: () => !!box, visible };
}
