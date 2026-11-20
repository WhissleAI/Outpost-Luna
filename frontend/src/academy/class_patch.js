// Class lesson patches (docs/CURRICULUM.md): a teacher's lesson has no drawn art, so its patch is the round mission
// patch shape (assets/build-art.mjs OUTLINE.round: the same field, stitch ring and merrowed border, in the same palette)
// with the lesson's letter. Earned: full colour; not yet: the dashed outline the drawn patches use. Pure: no DOM.
import { patch as artPatch, patchId } from "../assets/icons.js";

const PAL = { navy: "#1A2B4C", deep: "#0E1A30", white: "#F3EFE4", gold: "#F0B43C" };
// fields per pack (stable: the pack id picks one), all from the patch palette
const FIELDS = ["#2C5AA0", "#4FA46A", "#E86F2C", "#C73A2E", "#5B9BE6", "#7F8898"];
const EARTH = ["#8A5A35", "#A0703C", "#6E7B3A", "#9A4E2F", "#7A6248", "#B08442"];   // course patches: earth tones
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const dim = v => (typeof v === "number" ? `${v}` : esc(v));
const hash = s => [...String(s || "")].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);

const REG = new Map();   // lesson id and badge id -> {name, glyph, field}
/** Register the course's Class lessons (academy/ui.js calls this whenever the course loads). */
export function registerClassLessons(lessons) {
  registerLetterPatches(lessons);
  REG.clear();
  // [courses] a course's own lessons (ids "<course>:<id>", docs/COURSES.md §4.4) draw the same round patch with their
  // glyph, on an earth-tone field (§3.4) until the course ships drawn art
  (lessons || []).filter(l => l && (l.track === "class" || String(l.id || "").includes(":")) && l.badge).forEach(l => {
    const course = l.track !== "class";
    const v = { name: l.badge.name || l.title, glyph: String(l.badge.glyph || l.title || "C").slice(0, 1).toUpperCase(),
      field: course ? EARTH[hash(l.id) % EARTH.length] : FIELDS[hash((l.pack && l.pack.id) || l.id) % FIELDS.length] };
    REG.set(l.id, v); REG.set(l.badge.id, v);
  });
}
export const isClassPatch = id => REG.has(id);

/** The SVG of one Class patch. */
export function classPatchSvg({ name = "Class", glyph = "C", field = FIELDS[0] } = {}, { earned = true, size = 64, title, className = "" } = {}) {
  const label = title === true ? name + (earned ? " patch" : " patch, not yet earned") : title;
  const a11y = label ? `role="img" aria-label="${esc(label)}"` : `aria-hidden="true"`;
  const g = esc(glyph);
  const body = earned
    ? `<circle cx="80" cy="80" r="68" fill="${field}"/>`
      + `<circle cx="80" cy="80" r="63.5" fill="none" stroke="${PAL.white}" stroke-width="1.6" stroke-dasharray="3.5 3" opacity=".55"/>`
      + `<path d="M28 104a56 56 0 0 0 104 0Z" fill="${PAL.deep}" opacity=".28"/>`
      + `<circle cx="112" cy="48" r="9" fill="${PAL.white}" opacity=".9"/><circle cx="116" cy="45" r="7" fill="${field}"/>`
      + `<text x="80" y="98" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-weight="800" font-size="58" fill="${PAL.white}">${g}</text>`
      + `<circle cx="80" cy="80" r="72" fill="none" stroke="${PAL.navy}" stroke-width="8"/>`
      + `<circle cx="80" cy="80" r="72" fill="none" stroke="${PAL.gold}" stroke-width="7" stroke-dasharray="1 1.8" opacity=".55"/>`
      + `<circle cx="80" cy="80" r="76" fill="none" stroke="#0B1222" stroke-opacity=".45" stroke-width="1.5"/>`
    : `<circle cx="80" cy="80" r="72" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="7 6" stroke-linecap="round"/>`
      + `<text x="80" y="98" text-anchor="middle" font-family="Inter, system-ui, sans-serif" font-weight="800" font-size="58" fill="currentColor" opacity=".7">${g}</text>`;
  const tone = earned ? "" : ` style="color:var(--color-text-3,#7D8796)"`;
  return `<svg xmlns="http://www.w3.org/2000/svg" class="patch patch-class ${earned ? "is-earned" : "is-locked"}${className ? " " + esc(className) : ""}"`
    + ` width="${dim(size)}" height="${dim(size)}" viewBox="0 0 160 160" focusable="false" ${a11y}${tone}>`
    + `${label ? `<title>${esc(label)}</title>` : ""}${body}</svg>`;
}

/** patch() for any lesson: a registered Class lesson draws its letter patch; everything else the drawn art. */
export function anyPatch(id, opts = {}) {
  const c = REG.get(id) || (patchId(id) ? null : LETTER.get(id));
  return c ? classPatchSvg(c, opts) : artPatch(id, opts);
}

// Lessons without drawn art (the speech lessons, a course's new lessons): the same letter patch, from their badge glyph
const LETTER = new Map();
export function registerLetterPatches(lessons) {
  (lessons || []).filter(l => l && l.badge && l.track !== "class" && !patchId(l.id) && !patchId(l.badge.id)).forEach(l => {
    const v = { name: l.badge.name || l.title, glyph: String(l.badge.glyph || l.title || "?").slice(0, 1).toUpperCase(), field: FIELDS[hash(l.id) % FIELDS.length] };
    LETTER.set(l.id, v); LETTER.set(l.badge.id, v);
  });
}
