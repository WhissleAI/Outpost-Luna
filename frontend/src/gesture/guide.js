// What each gesture does, in kid words: the cheat-sheet (Settings, "What can I do?") and the contextual hint chip.
// One source for the UI, the spoken help and docs/GESTURES.md. Copy budget: hints ≤ 6 words; no emoji.

export const CHEATSHEET = [
  { id: "palm", icon: "hand", name: "Open hand, hold still", does: "Stop. Quiets the voice and the Moon." },
  { id: "thumbs_up", icon: "thumbs-up", name: "Thumbs up", does: "Yes. Confirms, or takes the offer." },
  { id: "thumbs_down", icon: "thumbs-down", name: "Thumbs down", does: "No. Cancels, or says no thanks." },
  { id: "swipe", icon: "swipe", name: "Swipe with an open hand", does: "Swipe left for next, right for back." },
  { id: "point", icon: "pointer", name: "Point and hold", does: "Picks what the ring is on. Works on any button and the Moon." },
  { id: "grab", icon: "grab", name: "Make a fist and move", does: "Turns the Moon, or looks around the cabin." },
  { id: "head", icon: "head", name: "Move your head (cabin)", does: "Look around. Lean in to open a panel, sit back to return." },
];
export const CHEATSHEET_PHASE2 = [
  { id: "zoom", icon: "zoom", name: "Two-hand pinch", does: "Pinch both hands and pull apart to zoom the Moon." },
  { id: "raise", icon: "hand", name: "Raise your hand", does: "Calls Houston (in the cabin)." },
];

/** The hint for a screen frame (main.js screenFrame(): {screen, step_type, offer}) plus flags. null = no hint. */
export function hintFor(frame = {}, { confirm = false, speaking = false, headLook = true } = {}) {
  if (confirm) return { icon: "thumbs-up", text: "Thumbs up to confirm" };
  const s = frame.screen;
  if (s === "lesson_done" || s === "patch") return { icon: "swipe", text: "Swipe left for next" };
  if (s === "lesson" || s === "ride") {
    if (frame.step_type === "tap") return { icon: "pointer", text: "Point and hold on the Moon" };
    if (frame.step_options && frame.step_options.length) return { icon: "pointer", text: "Point and hold an answer" };
    return speaking ? { icon: "hand", text: "Open hand to stop" } : null;
  }
  if (s === "map") return { icon: "swipe", text: "Swipe left to start" };
  if (s === "brief") return { icon: "thumbs-up", text: "Thumbs up to take command" };
  if (s === "debrief") return { icon: "thumbs-up", text: "Thumbs up to fly again" };
  if (s === "cabin") return headLook ? { icon: "head", text: "Lean in to open a panel" } : { icon: "swipe", text: "Swipe to change the view" };
  if (s === "library") return { icon: "grab", text: "Grab to turn the Moon" };
  if (speaking) return { icon: "hand", text: "Open hand to stop" };
  return null;
}

/** One sentence for "What can I do?" when the camera is on. */
export function spokenSummary({ cabin = false } = {}) {
  return "With the camera: open hand to stop, thumbs up for yes, thumbs down for no, swipe for next or back, point and hold to pick"
    + (cabin ? ", and lean in to open a panel." : ", and make a fist to turn the Moon.");
}
