// Debrief "Learn more" (NASA Moon Learning & Media Plan v1): one NASA video per mission outcome, or a fact card when
// the outcome has no video yet or the video can't play now (offline, no player). Pure apart from the `probe`, so the
// mapping is unit-tested (frontend/tests/learning_v1.test.js). Outcome names are the sim's (backend/app/mission/sim.py).
import { LEARN_MORE } from "./story.js";

/** Can the kid watch it now? (media/video.js isAvailable: "cached" | "online" | "offline") */
export const playable = state => state === "cached" || state === "online";

/** The outcomes that get a Learn more card. A paused mission ("in_progress") gets none. */
export const LEARN_MORE_OUTCOMES = ["dose_limit", "power_out", "life_support_out", "survived"];

/**
 * What the debrief shows under "Learn more".
 * @param {string} outcome   sim outcome ("survived" | "dose_limit" | "power_out" | "life_support_out" | ...)
 * @param {(id: string) => Promise<string>|string} probe   video availability: "cached" | "online" | "offline" | "missing"
 * @returns {Promise<null | {kind: "video", media: string, line: string} | {kind: "fact", text: string}>}
 */
export async function pickLearnMore(outcome, probe) {
  const e = LEARN_MORE[outcome === "success" ? "survived" : outcome];
  if (!e) return null;
  const state = async id => { try { return await probe(id); } catch (err) { return "missing"; } };
  // the online-only pick first, but only when the internet is really up (YouTube is never cached)
  if (e.online && (await state(e.online)) === "online") return { kind: "video", media: e.online, line: e.line };
  if (e.media && playable(await state(e.media))) return { kind: "video", media: e.media, line: e.line };
  return { kind: "fact", text: e.fact };
}
