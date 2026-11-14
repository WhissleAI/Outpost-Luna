// Outpost Luna icons and patches: inline SVG strings, fully offline (no fetches, no external references).
// GENERATED from icons.template.js + icons/*.svg + build-art.mjs. Do not edit icons.js by hand:
//   cd frontend && node src/assets/build-art.mjs
//
// UI icons: 24px grid, 2px round stroke, drawn in `currentColor`, so they follow the theme (light, dark,
// data-contrast="high") from the text colour of their button. Set the stroke with CSS (`.ic { stroke-width: 1.75 }`).
// Most are Lucide (ISC, icons/LICENSE-lucide.txt); rover, astronaut, storm and outpost are originals on the same grid.
//
//   import { icon, patch } from "./assets/icons.js";
//   btn.innerHTML = icon("mic") + "<span>Talk</span>";          // decorative: aria-hidden
//   btn.innerHTML = icon("close", { title: "Close" });           // the only content: role="img" + <title>
//   shelf.innerHTML = patch("moon", { earned: true, size: 40 });
//   patch("radiation", { earned: false })                       // locked: dashed outline + grey silhouette
//
// Patches: one per Flight School lesson (course.json lesson ids; the badge ids work too) and the mission patches.
// Earned patches use a small fixed thread palette that reads on light and dark. Locked ones draw in
// `var(--color-text-3)` (grey in light/dark, white in high contrast).

export const ICONS = /*@ICONS@*/{};

/** Other names the UI may use for the same picture. */
export const ALIASES = {
  speaker: "speaker", volume: "speaker", "hear-again": "speaker", listen: "speaker",
  forward: "next", "arrow-right": "next", "arrow-left": "back", x: "close",
  accessibility: "access", satellite: "mission", school: "academy", "flight-school": "academy",
  ok: "check", done: "check", correct: "check-circle", caution: "warning", alarm: "alert",
  houston: "houston", capcom: "houston", phone: "call", dish: "comms", antenna: "comms",
  shields: "shield", "life-support": "air", life_support: "air", oxygen: "air", heaters: "heater", heat: "heater",
  lab: "science", plants: "greenhouse", home: "shelter", "leave-shelter": "leave", door: "leave",
  views: "view", eye: "view", location: "site", pin: "site", landing: "site", subtitles: "captions", cc: "captions",
  rate: "speed", dose: "radiation", "solar-storm": "storm", flare: "storm", compass: "explore", dice: "random",
  replay: "retry", again: "retry", score: "star", link: "external", source: "external", pointer: "tap",
  "next-step": "todo", clipboard: "debrief", scroll: "history", book: "words", vocab: "words", "check-ride": "rocket",
  "call-sign": "astronaut", callsign: "astronaut", crew: "astronaut", cadet: "astronaut", habitat: "outpost", base: "outpost",
  up: "trend-up", down: "trend-down", grade: "trophy", type: "keyboard", ear: "hear", "low-battery": "low-power",
  battery: "low-power", energy: "power", ice_run: "ice", collect_ice: "ice", water_ice: "ice",
};

/** Every emoji / symbol the UI used before this set, and the icon that replaces it (for the migration). */
export const EMOJI = {
  "🎓": "academy", "🛰": "mission", "♿": "access", "▶": "play", "🚀": "rocket", "🔊": "speaker",
  "🧑‍🚀": "astronaut", "🧑": "astronaut", "🧭": "explore", "📋": "debrief", "🌙": "moon", "📻": "radio",
  "☀": "sun", "🛡": "shield", "🧊": "ice", "📜": "history", "📖": "words", "🔥": "heater", "🏠": "shelter",
  "🚪": "leave", "🎙": "mic", "👆": "tap", "👉": "todo", "🎲": "random", "🚨": "alert", "✅": "check-circle",
  "🔁": "retry", "❄": "ice", "🌍": "earth", "⚡": "power", "☢": "radiation", "⚠": "warning", "★": "star",
  "💨": "air", "🌱": "greenhouse", "🔬": "science", "🚙": "rover", "📡": "comms", "📞": "call", "✓": "check",
  "⌖": "place", "▸": "chevron-right", "▲": "trend-up", "▼": "trend-down", "◌": "impression", "↗": "external",
};

export const PATCHES = /*@PATCHES@*/{};

/** Patch lookups by badge id (course.json `badge.id`) as well as lesson id. */
const BADGE = Object.fromEntries(Object.entries(PATCHES).filter(([, p]) => p.badge).map(([id, p]) => [p.badge, id]));

const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const dim = v => (typeof v === "number" ? `${v}` : esc(v));

/** The canonical icon name for `name` (resolving aliases), or null. */
export function iconName(name) {
  if (ICONS[name]) return name;
  const a = ALIASES[name];
  return a && ICONS[a] ? a : null;
}
export const hasIcon = name => iconName(name) !== null;
export const iconNames = () => Object.keys(ICONS);

/**
 * Inline SVG string for a UI icon.
 * @param {string} name   icon name or alias (see ICONS / ALIASES)
 * @param {{size?: number|string, title?: string, className?: string, strokeWidth?: number}} [opts]
 *   size: px number or any CSS length ("1.25em"); default 24. title: accessible name (otherwise aria-hidden).
 */
export function icon(name, { size = 24, title, className = "", strokeWidth } = {}) {
  const key = iconName(name);
  if (!key) {
    if (typeof console !== "undefined") console.warn(`icon(): unknown icon "${name}"`);
    return "";
  }
  const a11y = title ? `role="img" aria-label="${esc(title)}"` : `aria-hidden="true"`;
  return `<svg xmlns="http://www.w3.org/2000/svg" class="ic ic-${key}${className ? " " + esc(className) : ""}" width="${dim(size)}" height="${dim(size)}"`
    + ` viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${strokeWidth || 2}" stroke-linecap="round" stroke-linejoin="round"`
    + ` focusable="false" ${a11y}>${title ? `<title>${esc(title)}</title>` : ""}${ICONS[key]}</svg>`;
}

/** The canonical patch id for a lesson id, badge id or mission patch id, or null. */
export function patchId(id) {
  if (PATCHES[id]) return id;
  return BADGE[id] || null;
}
export const patchIds = () => Object.keys(PATCHES);

/**
 * Inline SVG string for a mission patch.
 * @param {string} id  lesson id (course.json), badge id, or mission patch id (storm_survivor, outpost_luna)
 * @param {{earned?: boolean, size?: number|string, title?: string|boolean, className?: string}} [opts]
 *   earned: full colour (default) or locked (outline + grey silhouette). size: default 64.
 *   title: true → the patch name ("… (not yet earned)" when locked); a string → that; omitted → aria-hidden.
 */
export function patch(id, { earned = true, size = 64, title, className = "" } = {}) {
  const key = patchId(id);
  if (!key) {
    if (typeof console !== "undefined") console.warn(`patch(): unknown patch "${id}"`);
    return "";
  }
  const p = PATCHES[key];
  const label = title === true ? p.name + (earned ? " patch" : " patch, not yet earned") : title;
  const a11y = label ? `role="img" aria-label="${esc(label)}"` : `aria-hidden="true"`;
  const tone = earned ? "" : ` style="color:var(--color-text-3,#7D8796)"`;
  return `<svg xmlns="http://www.w3.org/2000/svg" class="patch patch-${key} ${earned ? "is-earned" : "is-locked"}${className ? " " + esc(className) : ""}"`
    + ` width="${dim(size)}" height="${dim(size)}" viewBox="0 0 160 160" focusable="false" ${a11y}${tone}>`
    + `${label ? `<title>${esc(label)}</title>` : ""}${earned ? p.earned : p.locked}</svg>`;
}
