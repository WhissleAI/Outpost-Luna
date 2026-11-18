// [0.3.12] The check ride's cabin, pure helpers (no DOM writes; tests/ride_cabin.test.js). The ride is the Flight
// School's first time in the seat: a 2-day shift on the real simulator (backend/app/academy/ride.py), in the real cabin
// (mission/cabin.js, mode "ride") behind the lesson card.

/** The ride's panels: what its orders use (shields, shelter, the rover), the displays, and the caution & warning strip
 *  with the master alarm, so the storm lights its lamps as in a mission (End shift / See debrief stay hidden there:
 *  cabin.css `.is-ride .cb-ped`). */
export const RIDE_PANELS = { ride: ["displays", "radiation", "rover", "pedestal"] };

/** The clock's day: the check ride counts its own days ("Day 1 of 2", the HUD's `ride`), never the sim's ("Day 8" on a
 *  two-day ride that starts a week into the window); a mission shows "Day n" (1–10). HTML (the number is .num). */
export function clockDay(s, t) {
  const r = s && s.ride;
  if (r && r.days) return `Day <span class="num">${Math.max(1, Math.min(r.days, +r.day || 1))}</span> of ${r.days}`;
  return `Day <span class="num">${Math.min(10, Math.floor((+t || 0) / 24) + 1)}</span>`;
}

/** "Shift 2 · Shackleton Crater Rim"; with no site name just "Shift 2" (never a dangling "·"). Plain text. */
export function clockSub(shift, site) {
  const name = ((site && site.name) || "").split(" (")[0].trim();
  return name ? `Shift ${shift} · ${name}` : `Shift ${shift}`;
}

/** The part of the ride cabin under the lesson card, in px from the cabin's right edge: the card's left edge to the
 *  cabin's right edge plus a gap. 0 when the card is not beside the cabin (hidden, or a narrow stacked layout). Takes
 *  anything with getBoundingClientRect(). */
export function rideInset(host, card, gap = 12) {
  if (!host || !card || card.hidden) return 0;
  const h = host.getBoundingClientRect(), c = card.getBoundingClientRect();
  if (!c.width || c.left <= h.left + h.width * 0.35) return 0;
  return Math.max(0, Math.round(h.right - c.left + gap));
}
