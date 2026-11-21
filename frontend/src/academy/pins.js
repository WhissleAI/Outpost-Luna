// [0.4.1] The Flight School map's pins and the Field School track (academy/ui.js showMap). Pure, so tests can import it
// without the DOM.
//
// Every core pin carries its lesson number, always (it used to show only in the hover label, so the route read as a
// row of unnumbered grey circles). A locked pin carries a lock. Before the check ride, Field School is shown as a
// visible locked track ("Field School · Opens after your check ride"); the unlock logic itself (explorer.js unlocked)
// is unchanged.

/** The inside of one map pin: its patch, the core lesson number (if any), the lock (if locked) and the hover label. */
export function pinInnerHtml({ patchHtml, no = "", locked = false, title = "", esc, lockIcon = "" }) {
  return `<span class="pin-badge">${patchHtml}</span>`
    + (no ? `<span class="pin-no" aria-hidden="true">${esc(no)}</span>` : "")
    + (locked ? `<span class="pin-lock" aria-hidden="true">${lockIcon}</span>` : "")
    + `<span class="pin-label">${no ? `<b>${esc(no)}</b>` : ""}${esc(title)}</span>`;
}

/** The locked Field School track on the map, before the check ride ("" once qualified, or with no Field lessons).
 *  A button: tapping it selects the first Field School lesson, whose card says when it opens. */
export function fieldTrackHtml({ qualified, fieldLessons, copy, esc, lockIcon = "" }) {
  if (qualified || !fieldLessons || !fieldLessons.length) return "";
  return `<button type="button" class="mp-track is-locked" id="aFieldTrack" data-l="${esc(fieldLessons[0].id)}"
      aria-label="${esc(`${copy.name}: ${fieldLessons.length} lessons, locked. ${copy.lockedTrack}`)}">
      <span class="mp-track-lock" aria-hidden="true">${lockIcon}</span>
      <span><b>${esc(copy.name)}</b> · ${esc(copy.lockedTrack)}</span>
      <small>${esc(copy.trackCount(fieldLessons.length))}</small></button>`;
}

/** The map's Class lesson rows (teacher-written packs, docs/CURRICULUM.md): one button per pack, next to the Field School
 *  track. It selects the pack's first lesson not yet done (or its first), so its pin and card come up like any other.
 *  lessons: the course's Class lessons (preview ones already left out); has(badgeId) → earned. */
export function classTrackHtml({ lessons, has, copy, esc, patch }) {
  const packs = [];
  (lessons || []).forEach(l => {
    const id = (l.pack && l.pack.id) || "class";
    let p = packs.find(x => x.id === id);
    if (!p) packs.push(p = { id, title: (l.pack && l.pack.title) || copy.name, lessons: [] });
    p.lessons.push(l);
  });
  return packs.map(p => {
    const done = p.lessons.filter(l => has(l.badge.id)).length, pick = p.lessons.find(l => !has(l.badge.id)) || p.lessons[0];
    return `<button type="button" class="mp-track is-class" data-class-pack="${esc(p.id)}" data-l="${esc(pick.id)}"
      aria-label="${esc(`${copy.name}: ${p.title}. ${copy.track(done, p.lessons.length)}`)}">
      <span class="mp-track-patch" aria-hidden="true">${patch(pick.id, { earned: has(pick.badge.id), size: 28 })}</span>
      <span><b>${esc(copy.name)}</b> · ${esc(p.title)}</span>
      <small>${esc(copy.track(done, p.lessons.length))}</small></button>`;
  }).join("");
}

/** [courses] Fixed screen slots for pins that share a spot (academy/ui.js showMap; globe.js route stop `nudge`).
 *  The Archaeology course puts nine of its ten lessons at Mesa Verde. Left to the route layer's push-apart alone, nine
 *  pins on one point were flung across the continent, and to different places every time the next lesson changed, so
 *  an earned patch seemed to vanish after each lesson. Stops within `deg` degrees of a cluster's first stop share that
 *  cluster; its k-th stop (in route order) gets slot k of a sunflower round the spot, so a pin keeps its place as
 *  lessons are earned. A stop alone gets null (no nudge). Pure. stops: [{lat, lon}] -> [[dx, dy] | null]. */
export function clusterNudges(stops, { deg = 3, gap = 34 } = {}) {
  const rad = Math.PI / 180;
  const apart = (a, b) => {   // great-circle distance in degrees
    const h = Math.sin((b.lat - a.lat) * rad / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin((b.lon - a.lon) * rad / 2) ** 2;
    return 2 * Math.asin(Math.min(1, Math.sqrt(h))) / rad;
  };
  const groups = [];
  const of = (stops || []).map(s => {
    if (!s || !Number.isFinite(+s.lat) || !Number.isFinite(+s.lon)) return null;
    let g = groups.find(x => apart(x.at, s) <= deg);
    if (!g) groups.push(g = { at: s, n: 0 });
    return { g, k: g.n++ };
  });
  const GOLDEN = Math.PI * (3 - Math.sqrt(5));
  return of.map(o => {
    if (!o || o.g.n < 2) return null;
    const r = gap * Math.sqrt(o.k + 0.5), t = o.k * GOLDEN - Math.PI / 2;
    return [Math.round(r * Math.cos(t)), Math.round(r * Math.sin(t))];
  });
}

/** [courses] Where a non-Moon course's lesson map looks: its lessons' region, close up. Archaeology's ten lessons sit at
 *  two parks 105 km apart; the map used to show the whole continent (the next lesson's place at 4.2 globe radii), so
 *  the Mesa Verde cluster read as pins in Canada and Texas. The view is the lessons' middle (weighted by lesson, so
 *  the park holding nine sits in the middle and Chimney Rock off to one side), close enough that they fill the view
 *  (a draped regional picture, the Field Library's, shows there). Lessons spread wider than `maxDeg` (a course across
 *  a continent): null, and the map keeps the old whole-globe view.
 *  -> {lat, lon, dist, deg}: deg = how far the places spread from the middle. Pure. */
export function regionOf(points, { maxDeg = 12, near = 1.09, perDeg = 0.035 } = {}) {
  const ps = (points || []).filter(p => p && Number.isFinite(+p.lat) && Number.isFinite(+p.lon));
  if (!ps.length) return null;
  const lat = ps.reduce((s, p) => s + +p.lat, 0) / ps.length, lon = ps.reduce((s, p) => s + +p.lon, 0) / ps.length;
  const deg = Math.max(...ps.map(p => Math.hypot(+p.lat - lat, (+p.lon - lon) * Math.cos(lat * Math.PI / 180))));
  if (deg > maxDeg) return null;
  return { lat: +lat.toFixed(3), lon: +lon.toFixed(3), dist: +(near + deg * perDeg).toFixed(3), deg: +deg.toFixed(3) };
}
