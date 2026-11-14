// Camera gestures → intents. One table, so the gesture layer never reaches into a screen: it only emits intents on the
// bus (input/intents.js), and screens decide what an intent means for them. docs/GESTURES.md §"Gesture → intent".

/** Which cabin panel the head is aimed at, in the 3D cabin's layout (mission/cockpit3d.js LAYOUT): power (DU1) in the
 *  middle; habitat (upper) and rover (lower) on the left; radiation (upper) and comm (lower) on the right.
 *  x, y: look, -1..1 (y > 0 = head lowered). */
export function lookTarget(x, y = 0) {
  if (Math.abs(x) <= 0.33) return "power";
  return x < 0 ? (y > 0.15 ? "rover" : "habitat") : (y > 0.15 ? "comm" : "radiation");
}

/**
 * One classifier event → the intents it makes, as [name, args] pairs.
 * ctx: { cabin: the Mission cabin is up, panel: the open cabin panel (null / "seat" = the seat view),
 *        vw, vh: the viewport in CSS px (point / select are in px), phase2 }
 */
export function gestureIntents(ev, ctx = {}) {
  const vw = ctx.vw || 1, vh = ctx.vh || 1, px = (x, y) => ({ x: Math.round(x * vw), y: Math.round(y * vh) });
  const atSeat = !ctx.panel || ctx.panel === "seat";
  switch (ev.type) {
    case "palm_hold": return [["stop", {}]];
    case "thumbs_up": return [["yes", {}]];
    case "thumbs_down": return [["no", {}]];
    // a swipe to the left pulls the next thing in (as on a phone); to the right brings the previous one back
    case "swipe_left": return [["next", {}]];
    case "swipe_right": return [["prev", {}]];
    case "point": return [["point", { ...px(ev.x, ev.y), progress: ev.progress }]];
    case "point_end": return [["point", { end: true }]];
    case "select": return [["select", px(ev.x, ev.y)]];
    case "grab_start": return [["rotate", { phase: "start", dx: 0, dy: 0 }]];
    case "grab_move": return [["rotate", { phase: "move", dx: ev.dx, dy: ev.dy }]];
    case "grab_end": return [["rotate", { phase: "end", dx: 0, dy: 0 }]];
    case "head": return ctx.cabin ? [["look", { x: ev.x, y: ev.y }]] : [];
    case "lean_in": return ctx.cabin && atSeat ? [["panel_open", { panel: lookTarget(ev.x, ev.y) }]] : [];
    case "lean_back": return ctx.cabin && !atSeat ? [["panel_back", {}]] : [];
    case "raise_hand": return ctx.phase2 ? [["call_houston", {}]] : [];
    case "zoom": return ctx.phase2 ? [["zoom", { factor: ev.factor }]] : [];
    default: return [];
  }
}

/** Short feedback shown (and announced) when a gesture made an intent, so a kid knows it worked. No emoji. */
export const FEEDBACK = {
  stop: "Stop", yes: "Yes", no: "No", next: "Next", prev: "Back", select: "Picked",
  panel_open: "Opening panel", panel_back: "Back to your seat", call_houston: "Calling Houston",
};
