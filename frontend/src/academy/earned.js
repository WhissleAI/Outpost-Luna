// The map's earned-patch strip (academy/ui.js showMap). Pure, so tests can import it without the DOM.
//
// Why it exists: the map faces the next stop, and from lesson 3 on that stop is at the south pole. Seen from the pole,
// the near-side stops (Lessons 1 and 2) are round the limb, so their pins fade out (globe.js tickRoute, n·cam <= 0.3).
// A cadet with two patches saw none; with three, one. No single camera shows both the pole and the near side, so the
// earned patches also sit in the map header, always in view. Tapping one selects its lesson and flies the Moon to it.

/** Earned lessons in course order: [{id (lesson id, for patch()), name (the badge's name)}]. */
export function earnedPatches(lessons, badges) {
  const got = new Set(badges || []);
  return (lessons || []).filter(l => l && l.badge && got.has(l.badge.id)).map(l => ({ id: l.id, name: l.badge.name || l.title || l.id }));
}

/** The strip's HTML: one button per earned patch (empty string when there are none). */
export function patchStripHtml(list, { patch, esc, size = 28 }) {
  if (!list || !list.length) return "";
  return `<div class="mp-patches" role="group" aria-label="Patches earned">${list.map(p =>
    `<button type="button" class="mp-patchbtn" data-l="${esc(p.id)}" title="${esc(p.name)}" aria-label="${esc(p.name)} patch">${patch(p.id, { earned: true, size })}</button>`).join("")}</div>`;
}
