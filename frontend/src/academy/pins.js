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
