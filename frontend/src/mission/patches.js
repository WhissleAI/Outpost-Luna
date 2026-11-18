// The cockpit's patch key: the cadet's earned Flight School and Field School patches on the Habitat console, the
// left-hand switch panel (cabin.js paintPatches). Pure, so tests can import it without the DOM.
//
// Why it exists: the Academy hands the mission its earned patches (academy/ui.js badges()), but the cabin never drew
// them; the old patch row lived in cockpit.js, which the cabin replaced. The cockpit bar's display unit has no room
// left at 1440 px or below (Days · Science · Ice · Log fill it), so the patches sit on the Habitat console like patches
// on a real spacecraft panel: the newest three, the word "Patches" and the count (console text, sized by the consoles'
// readable floor, frontend/tools/mission_ui.py), in the switch row's empty third column, so the console grows no
// taller. Pressing the key opens a card over the cabin that names every patch,
// in course order, with its school; every word on the card is at least 18 px (the HUD floor,
// docs/MISSION_POLISH_SPEC.md).

/** Which school a patch belongs to (course.json `track`), as the card says it. */
export const TRACK = { core: "Flight School", field: "Field School", explorer: "Bonus lesson", ride: "Check ride" };
/** How many patches the key itself shows (the rest are counted). */
export const KEY_MAX = 3;

/** academy badges() → [{id, name, lesson, track}] with only the fields the cockpit uses; bad entries dropped. */
export function normPatches(list) {
  const seen = new Set();
  return (Array.isArray(list) ? list : []).filter(b => b && b.id && !seen.has(b.id) && seen.add(b.id))
    .map(b => ({ id: String(b.id), name: String(b.name || b.id), lesson: b.lesson || b.id, track: TRACK[b.track] ? b.track : "core" }));
}

/** A stable signature: the cabin repaints only when the earned set changes. */
export const patchSig = list => normPatches(list).map(b => b.id).join(",");

/** Patches in `now` that weren't in `before` (by id), in `now`'s order. */
export function newPatches(before, now) {
  const had = new Set(normPatches(before).map(b => b.id));
  return normPatches(now).filter(b => !had.has(b.id));
}

/** "Patches: 3 earned. Show them" (the key's accessible name). */
export const keyLabel = n => `Patches: ${n} earned. Show them`;

/** "4 Flight School · 2 Field School" (the card's summary line; schools with none are left out). */
export function trackSummary(list) {
  const n = {}; normPatches(list).forEach(b => { n[b.track] = (n[b.track] || 0) + 1; });
  return Object.keys(TRACK).filter(t => n[t]).map(t => `${n[t]} ${TRACK[t]}`).join(" · ");
}

/** The key's inside: the newest KEY_MAX patches (art only) and the count. "" when nothing is earned. */
export function patchKeyHtml(list, { patch, esc, size = 44 }) {
  const ls = normPatches(list); if (!ls.length) return "";
  const show = ls.slice(-KEY_MAX);
  return `<span class="cb-patchart" aria-hidden="true">${show.map(b => patch(b.lesson, { earned: true, size })).join("")}</span>`
    + `<span class="cb-patchl" aria-hidden="true">Patches <b class="cb-patchn num">${ls.length}</b></span>`;
}

/** The card's list: every earned patch with its name and school, in course order. */
export function patchListHtml(list, { patch, esc, size = 44 }) {
  return normPatches(list).map(b => `<li class="cb-patchli is-${esc(b.track)}">${patch(b.lesson, { earned: true, size })}`
    + `<span><b>${esc(b.name)}</b><small>${esc(TRACK[b.track])}</small></span></li>`).join("");
}
