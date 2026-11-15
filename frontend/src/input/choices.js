// Gestures blended into answering (docs/GESTURES.md §Answers): thumbs up = yes, thumbs down = no on ANY on-screen
// choice that has an affirmative / negative option, and "show N fingers" picks option N, the way the number keys do.
//
// The option is found by what it MEANS, never by where it sits: an explicit hook on the button (data-yes / data-no,
// or data-intent="yes|no") first, then a small word list on its label ("Yes", "Do it", "Watch", "Shelter now" …
// / "No", "No thanks", "Skip", "Not now" …). "Steer left / Steer right" has neither: thumbs do nothing there and a hint
// says what does work. A gesture answers exactly like a tap: the chosen button wears the focus ring for a moment
// (FLASH_MS, so the kid sees what their thumb picked), then it is clicked: same grading, same feedback.
// Pure parts (polarity, resolveYesNo, labelOf) are unit-tested in tests/choices.test.js.
import { onIntent } from "./intents.js";

export const FLASH_MS = 300;
export const HINT_NO_YESNO = "Point at an answer, or hold up fingers";

// whole label, or the label's first words ("Watch (2 min)", "Shelter now", "No thanks, I'm good")
const YES = ["yes", "yeah", "yep", "sure", "ok", "okay", "do it", "take it", "take", "accept", "watch", "play", "done", "i did it",
  "start", "start lesson", "ready", "confirm", "shelter now", "fly again", "try again", "let s go", "go", "keep going"];
const NO = ["no", "nope", "no thanks", "not now", "decline", "skip", "skip it", "skip for now", "cancel", "later", "maybe later",
  "not yet", "wait", "wait a shift"];
// words that start an affirmative-looking label but mean something else ("Go back", "Start over" is a reset)
const NOT_YES = ["go back", "start over", "play again later"];

export const norm = t => String(t || "").toLowerCase().replace(/[’']/g, " ").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
const hit = (t, words) => words.some(w => t === w || t.startsWith(w + " "));

/** "yes" | "no" | null for one option: {label, yes?, no?, intent?}. Hooks win over words. */
export function polarity(o) {
  if (!o) return null;
  if (o.yes || o.intent === "yes") return "yes";
  if (o.no || o.intent === "no") return "no";
  const t = norm(o.label);
  if (!t) return null;
  if (hit(t, NO)) return "no";
  if (hit(t, NOT_YES)) return null;
  if (hit(t, YES)) return "yes";
  return null;
}

/** The index of the option a thumbs up ("yes") / down ("no") means, or -1 when no option means that. A hooked option
 *  (data-yes / data-no) beats one matched by its words; otherwise the first match. */
export function resolveYesNo(options, kind) {
  let byWord = -1;
  for (let i = 0; i < (options || []).length; i++) {
    const o = options[i];
    const hooked = kind === "yes" ? (o.yes || o.intent === "yes") : (o.no || o.intent === "no");
    if (hooked) return i;
    if (byWord < 0 && polarity(o) === kind) byWord = i;
  }
  return byWord;
}

/** A button's label without its number / letter badge (.a-key, kbd) or hint (small). */
export function labelOf(el) {
  if (!el) return "";
  const c = el.cloneNode(true);
  c.querySelectorAll(".a-key, kbd, small, svg, [aria-hidden=true]").forEach(x => x.remove());
  return (c.textContent || el.getAttribute("aria-label") || "").trim();
}
const optionOf = el => ({ label: labelOf(el), yes: el.hasAttribute("data-yes"), no: el.hasAttribute("data-no"), intent: el.dataset ? el.dataset.intent : "" });

// The on-screen choice sets, most specific first (the first one with visible, enabled buttons is "the" choice).
// The same lists the number keys use (input/keys.js), plus the video step, the prep card and the wipe confirm.
export const CHOICE_LISTS = [".mx-wipe [data-w]", "#aPanel [data-intent=yes], #aPanel [data-intent=no]", ".cb-offer-b",
  "#aPanel .a-choice", "#aPanel .v-opt", "#aPanel .a-order", "#aPanel .vs-row button", ".a-csb", ".mx-site",
  ".cb-now-btns .cb-now-b", "#card .card-actions button"];

const vis = el => !!(el && !el.hidden && !el.closest("[hidden]") && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden");

/** The buttons of the choice on screen now ([] when none). Never while a modal sheet or dialog is up. */
export function activeChoices(doc = document) {
  if (doc.querySelector("dialog[open]") || vis(doc.querySelector(".a11y-panel")) || doc.querySelector(".gx-calib")) return [];
  for (const s of CHOICE_LISTS) {
    const l = [...doc.querySelectorAll(s)].filter(b => vis(b) && !b.disabled);
    if (l.length) return l;
  }
  return [];
}

/** Press like a tap, after the kid has seen which one: the focus ring (and .is-gesture-pick) for FLASH_MS, then click. */
export function pressWithFlash(el, ms = FLASH_MS, relocate = null) {
  try { el.focus({ preventScroll: true }); } catch (e) { /* */ }
  el.classList.add("is-gesture-pick");
  return new Promise(res => setTimeout(() => {
    el.classList.remove("is-gesture-pick");
    // a screen that re-rendered its buttons meanwhile (the Now card on a clock tick): press the same option, found again
    const b = el.isConnected ? el : relocate && relocate();
    if (b && b.isConnected && !b.disabled && (b === el || labelOf(b) === labelOf(el))) b.click();
    res(true);
  }, ms));
}

/**
 * Install the gesture answers on the intent bus. `hint(text)` shows the gentle hint (gesture/ui.js's chip).
 * yes / no from a gesture: the matching option → flash + click. No yes/no option: thumbs up presses the choice the
 * point cursor has focused ("yes, that one"); otherwise the hint. No choice on screen: not ours (the cabin's spoken
 * confirm, the tour …).
 * pick {n} from a gesture (fingers): option n → flash + click; a choice without an option n: a hint.
 */
export function installChoiceGestures({ hint = () => {}, doc = document } = {}) {
  const yesNo = kind => (a, ev) => {
    if (ev.source !== "gesture") return false;
    const els = activeChoices(doc);
    if (!els.length) return false;
    const i = resolveYesNo(els.map(optionOf), kind);
    if (i >= 0) { pressWithFlash(els[i], FLASH_MS, () => activeChoices(doc)[i]); return true; }
    const f = doc.activeElement;
    if (kind === "yes" && f && els.includes(f) && doc.documentElement.dataset.input === "gesture") { pressWithFlash(f); return true; }
    hint(HINT_NO_YESNO);
    return true;
  };
  onIntent("yes", yesNo("yes"), { priority: 20 });
  onIntent("no", yesNo("no"), { priority: 20 });
  onIntent("pick", (a, ev) => {
    if (ev.source !== "gesture") return false;
    const els = activeChoices(doc);
    if (!els.length) return false;
    const b = els[((a && a.n) | 0) - 1];
    if (!b) { hint(els.length === 1 ? "Just one answer here. Point at it" : `Show 1 to ${Math.min(els.length, 4)} fingers`); return true; }
    pressWithFlash(b, FLASH_MS, () => activeChoices(doc)[((a && a.n) | 0) - 1]);
    return true;
  }, { priority: 20 });
}
