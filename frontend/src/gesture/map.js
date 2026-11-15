// The one gesture → action map (docs/GESTURES.md §The map). Same gesture, same meaning, on every screen:
//   open hand = stop / pause · thumbs up = yes · thumbs down = no · swipe left = next · swipe right = back ·
//   show 1-4 fingers = pick answer 1-4 · point and hold = press · fist = turn the view (spin the Moon, look round the cabin) ·
//   pinch and slide = zoom (pinch thumb to index, slide up = closer, down = farther; the fist never zooms) ·
//   head (cabin) = look, lean in = open, sit back = close.
// bind.js turns classifier events into these intents; screens decide what an intent does for them (input/intents.js).
// This file is also what the per-screen coach mark, the "Gestures" help card and the docs table are made from.
//
// Hooks for screens that don't exist yet (the video overlay, built on another branch): the gestures already emit the
// intents below. The overlay registers its own handlers while it is open, e.g.
//   onIntent("stop", () => { if (!videoOpen) return false; togglePause(); return true; }, { priority: 10 })
// and the help card / coach mark pick up SCREEN_MAP.video when screenKey(…, { video: true }) says it is up.

/** Every gesture, the intent it makes (the same everywhere), and how a kid says it. Copy: no emoji. */
export const GESTURES = Object.freeze({
  palm: { intent: "stop", icon: "hand", name: "Open hand, hold still", short: "Open hand" },
  thumbs_up: { intent: "yes", icon: "thumbs-up", name: "Thumbs up", short: "Thumbs up" },
  thumbs_down: { intent: "no", icon: "thumbs-down", name: "Thumbs down", short: "Thumbs down" },
  swipe_left: { intent: "next", icon: "swipe", name: "Swipe left, open hand", short: "Swipe left" },
  swipe_right: { intent: "prev", icon: "swipe", name: "Swipe right, open hand", short: "Swipe right" },
  fingers: { intent: "pick", icon: "hand", name: "Show 1, 2, 3 or 4 fingers", short: "Show fingers" },
  point: { intent: "select", icon: "pointer", name: "Point and hold", short: "Point and hold" },
  fist: { intent: "spin", icon: "grab", name: "Make a fist, then lean it", short: "Fist" },
  pinch: { intent: "zoom_rate", icon: "zoom", name: "Pinch, then slide up or down", short: "Pinch and slide" },
  head: { intent: "look", icon: "head", name: "Turn your head", short: "Turn head" },
  lean: { intent: "panel_open", icon: "head", name: "Lean in / sit back", short: "Lean in" },
  pinch2: { intent: "zoom", icon: "zoom", name: "Two-hand pinch (try-out)", short: "Two-hand pinch", phase2: true },
});

/** Classifier event → gesture id (for the table above). */
export const EVENT_GESTURE = Object.freeze({
  palm_hold: "palm", thumbs_up: "thumbs_up", thumbs_down: "thumbs_down", swipe_left: "swipe_left", swipe_right: "swipe_right", fingers: "fingers",
  point: "point", select: "point", point_end: "point", grab_start: "fist", grab_move: "fist", grab_end: "fist",
  pinch_start: "pinch", pinch_move: "pinch", pinch_end: "pinch",
  head: "head", lean_in: "lean", lean_back: "lean", zoom: "pinch2", zoom_end: "pinch2",
});

/** What each gesture does on each screen, in kid words (≤ 6 words). A gesture missing from a screen does nothing there. */
export const SCREEN_MAP = Object.freeze({
  moon: {        // Flight School map, the Library, Home: the Moon fills the screen
    palm: "Stop the voice and the Moon", thumbs_up: "Yes, take the offer", thumbs_down: "No thanks",
    swipe_left: "Start the next lesson", swipe_right: "Go back", point: "Pick a pin or a place",
    fist: "Turn the Moon", pinch: "Zoom: slide up or down", pinch2: "Zoom",
  },
  lesson: {      // a lesson step, the check ride
    palm: "Stop the voice", thumbs_up: "Yes, on a yes/no answer", thumbs_down: "No, on a yes/no answer",
    fingers: "Pick answer 1 to 4", swipe_left: "Next, after you answer", swipe_right: "Go back",
    point: "Pick an answer or a place", fist: "Turn the Moon to find it", pinch: "Zoom: slide up or down", pinch2: "Zoom",
  },
  menu: {        // mission brief, site picker, debrief, patch earned, call sign
    palm: "Stop the voice", thumbs_up: "Yes, the big button", thumbs_down: "No thanks", fingers: "Pick option 1 to 4",
    swipe_left: "Next", swipe_right: "Go back", point: "Press a button", fist: "Turn the Moon",
  },
  cabin: {       // Mission cabin (the seat view and an open panel)
    palm: "Stop the voice and the clock", thumbs_up: "Yes, confirm or do it", thumbs_down: "No, cancel", fingers: "Pick a choice on the card",
    swipe_left: "Next view or panel", swipe_right: "Previous view or panel", point: "Press a control",
    fist: "Look around", head: "Look around", lean: "Lean in opens, sit back closes",
  },
  video: {       // hooks for the video overlay (another branch): same meanings, the overlay handles the intents
    palm: "Pause or play", thumbs_up: "Yes, watch the next one", thumbs_down: "No thanks, close the video",
    swipe_left: "Next clip", swipe_right: "Previous clip", point: "Press a button",
  },
  settings: {    // the Settings sheet (and other dialogs)
    palm: "Stop the voice", point: "Press any switch or button", swipe_right: "Go back",
  },
});

/** Which column of SCREEN_MAP is up. frame: main.js screenFrame(); flags from the shell. */
export function screenKey(frame = {}, { cabin = false, settings = false, video = false } = {}) {
  if (video) return "video";
  if (settings) return "settings";
  if (cabin) return "cabin";
  const s = frame.screen;
  if (s === "lesson" || s === "lesson_done" || s === "ride" || s === "prep") return "lesson";   // prep: learning v1
  if (s === "brief" || s === "debrief" || s === "patch" || s === "callsign") return "menu";
  return "moon";
}

/** The help card's rows for a screen: [{id, icon, name, does}], in GESTURES order. */
export function helpRows(key, { phase2 = false, headLook = true } = {}) {
  const m = SCREEN_MAP[key] || SCREEN_MAP.moon;
  return Object.entries(GESTURES)
    .filter(([id, g]) => m[id] && (phase2 || !g.phase2) && (headLook || (id !== "head" && id !== "lean")))
    .map(([id, g]) => ({ id, icon: g.icon, name: g.short, does: m[id] }));
}

/** The first-use coach mark for a screen: the two or three gestures worth learning there first. */
export const COACH = Object.freeze({
  moon: ["fist", "pinch", "point"],
  lesson: ["thumbs_up", "fingers", "point"],
  menu: ["thumbs_up", "point", "swipe_left"],
  cabin: ["lean", "swipe_left", "thumbs_up"],
  video: ["palm", "swipe_left"],
  settings: ["point"],
});
export function coachRows(key, opts = {}) {
  const rows = helpRows(key, opts), want = COACH[key] || [];
  return want.map(id => rows.find(r => r.id === id)).filter(Boolean);
}
