// What each gesture does, in kid words: the cheat-sheet (Settings, "What can I do?") and the contextual hint chip.
// One source for the UI, the spoken help and docs/GESTURES.md. Copy budget: hints ≤ 6 words; no emoji.

export const CHEATSHEET = [
  { id: "palm", icon: "hand", name: "Open hand, hold still", does: "Stop. Quiets the voice and the Moon." },
  { id: "thumbs_up", icon: "thumbs-up", name: "Thumbs up", does: "Yes. Confirms, or takes the offer." },
  { id: "thumbs_down", icon: "thumbs-down", name: "Thumbs down", does: "No. Cancels, or says no thanks." },
  { id: "fingers", icon: "hand", name: "Show 1, 2, 3 or 4 fingers", does: "Picks answer 1 to 4, like the number keys. Hold still a moment." },
  { id: "swipe", icon: "swipe", name: "Swipe with an open hand", does: "Swipe left for next, right for back." },
  { id: "point", icon: "pointer", name: "Point and hold", does: "Picks what the ring is on. Works on any button and the Moon." },
  { id: "grab", icon: "grab", name: "Make a fist, then lean it", does: "Spins the Moon that way: lean more to go faster. Open your hand to stop. In the cabin it looks around." },
  { id: "twist", icon: "grab", name: "Twist your fist", does: "Zooms the Moon in or out while you hold it." },
  { id: "head", icon: "head", name: "Move your head (cabin)", does: "Look around. Lean in to open a panel, sit back to return." },
];
export const CHEATSHEET_PHASE2 = [
  { id: "zoom", icon: "zoom", name: "Two-hand pinch", does: "Pinch both hands and pull apart to zoom the Moon." },
];

/** The hint for a screen frame (main.js screenFrame(): {screen, step_type, offer}) plus flags. null = no hint. */
export function hintFor(frame = {}, { confirm = false, speaking = false, headLook = true } = {}) {
  if (confirm) return { icon: "thumbs-up", text: "Thumbs up to confirm" };
  const s = frame.screen;
  if (s === "lesson_done" || s === "patch") return { icon: "swipe", text: "Swipe left for next" };
  if (s === "lesson" || s === "ride") {
    if (frame.step_type === "tap") return { icon: "pointer", text: "Point and hold on the Moon" };
    if (frame.step_options && frame.step_options.length) return { icon: "thumbs-up", text: "Thumbs up, or show fingers" };
    return speaking ? { icon: "hand", text: "Open hand to stop" } : null;
  }
  if (s === "map") return { icon: "swipe", text: "Swipe left to start" };
  if (s === "brief") return { icon: "thumbs-up", text: "Thumbs up to take command" };
  if (s === "debrief") return { icon: "thumbs-up", text: "Thumbs up to fly again" };
  if (s === "cabin") return headLook ? { icon: "head", text: "Lean in to open a panel" } : { icon: "swipe", text: "Swipe to change the view" };
  if (s === "library") return { icon: "grab", text: "Make a fist to spin" };
  if (speaking) return { icon: "hand", text: "Open hand to stop" };
  return null;
}

/** One sentence for "What can I do?" when the camera is on. */
export function spokenSummary({ cabin = false } = {}) {
  return "With the camera: open hand to stop, thumbs up for yes, thumbs down for no, show fingers to pick an answer, swipe for next or back, point and hold to press"
    + (cabin ? ", and lean in to open a panel." : ", and make a fist and lean it to spin the Moon.");
}

/** A friendly line for a camera getUserMedia failure (engine.js). Windows has no per-app camera prompt: the switch is
 * Settings → Privacy & security → Camera, and Chromium reports it off as NotAllowedError or, with some drivers, as
 * NotReadableError: the same error as a camera another app is holding. */
export function cameraErrorText(e) {
  const n = String((e && e.name) || "");
  if (/NotAllowed|Security|PermissionDenied/i.test(n)) return "Camera blocked. Allow it in your computer's privacy settings.";
  if (/NotFound|Overconstrained|DevicesNotFound/i.test(n)) return "No camera found.";
  if (/NotReadable|TrackStart|Abort/i.test(n)) return "The camera didn't start. Close other apps using it, or check your privacy settings.";
  return "The camera didn't start.";
}
