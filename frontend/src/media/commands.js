// Pure helpers for the video overlay (media/video.js), unit-tested in tests/video.test.js. No DOM here.

/** Voice while a video plays: only these four (mirrors backend/app/turn_router.py VIDEO_CMDS). */
const CMDS = [
  ["pause", /^(?:pause|pause it|pause (?:the|this) video|wait|hold on|hang on|freeze)$/],
  ["play", /^(?:play|play it|resume|unpause|keep going|go on|continue|keep playing|start it)$/],
  ["skip", /^(?:skip|skip it|skip (?:the|this) video|skip this|next)$/],
  ["stop", /^(?:stop|stop it|stop (?:the|this) video|close|close it|close (?:the|this) video|that s enough|enough|i m done|done)$/],
];
const norm = t => String(t || "").toLowerCase().replace(/[’']/g, " ").replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
/** "Pause it, please." → "pause"; anything else → null. */
export function videoCommand(text) {
  const q = norm(text).replace(/^(?:(?:okay|ok|please|capcom|hey) )+/, "").replace(/(?: (?:please|now|capcom))+$/, "");
  const hit = CMDS.find(([, rx]) => rx.test(q));
  return hit ? hit[0] : null;
}
/** The router's nav intents for the video screen → the overlay's command. */
export const INTENT_CMD = Object.freeze({ video_pause: "pause", video_play: "play", video_skip: "skip", video_stop: "stop",
  stop: "stop", no: "stop", time_toggle: "toggle", time_pause: "pause", time_resume: "play",
  resume: "play", pause: "pause" });   // [flows] the router's flow words

/** The button's length: "Watch (2 min)", "Watch (15 sec)". */
export function lengthLabel(seconds) {
  const s = Math.max(1, Math.round(+seconds || 0));
  // to the nearest half minute: a 1:29 video is "1½ min", never "1 min" (novice playtest 2026-11-16 #25)
  const m = Math.max(1, Math.round(s / 30) / 2);
  return s < 50 ? `${s} sec` : `${m % 1 ? Math.floor(m) + "½" : m} min`;
}
export const watchLabel = v => `Watch (${lengthLabel(v && v.duration_s)})`;
export const NEEDS_NET = "Needs internet";
export const OFFLINE_LINE = "Needs internet. Ask a grown-up to connect.";
// School network mode (docs/SCHOOL_IT.md, network_ui.js): the internet is off on purpose, so "connect" is the wrong ask
export const SCHOOL_NET = "Off on the school network";
export const SCHOOL_LINE = "Off on the school network. Saved videos still play.";
const school = () => { try { return !!(window.__outpost && window.__outpost.network && window.__outpost.network.school_network); } catch (e) { return false; } };
export const needsNet = (on = school()) => (on ? SCHOOL_NET : NEEDS_NET);
export const offlineLine = (on = school()) => (on ? SCHOOL_LINE : OFFLINE_LINE);
/** The player failed while we ARE online (YouTube error 2/5/100/101/150/153, an unknown id): not "Needs internet". */
export const NO_PLAY_LINE = "This video won't play here.";
/** In a lesson, a video that can't play is never a dead end: closing it gives the step's answer (playtest #25). */
export const NO_PLAY_LESSON = "Close it, and I'll tell you the answer.";

/** watched = the kid saw most of it: the end, or at least 70% of its length. */
export function watchedEnough(seconds, duration, ended) {
  if (ended) return true;
  const d = +duration || 0;
  return d > 0 && +seconds >= 0.7 * d;
}

/** The YouTube embed (youtube-nocookie; captions on; related videos from the same channel only; JS API for pause/play). */
export function youtubeSrc(id, origin) {
  const q = new URLSearchParams({ rel: "0", cc_load_policy: "1", playsinline: "1", enablejsapi: "1", origin: origin || "" });
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?${q}`;
}

/** [videos offline] The plain youtube.com watch page, for "Watch on YouTube" on the "won't play here" card: a signed-in
 *  browser usually passes the bot check the embed fails. The desktop opens it only through the grown-up gate
 *  (desktop/main/gate.js classifyOpen → "youtube"). Null for anything that is not an 11-character video id. */
export function youtubeWatchUrl(id) {
  return /^[A-Za-z0-9_-]{11}$/.test(String(id || "")) ? `https://www.youtube.com/watch?v=${id}` : null;
}
export const WATCH_ON_YOUTUBE = "Watch on YouTube";

/**
 * [video fix 0.3.11] The YouTube watchdog. An embed can sit forever on a card of its own ("Sign in to confirm you're
 * not a bot") with no IFrame API error: it says onReady, takes playVideo and never plays. Every play request must reach
 * "playing" (state 1) within `ms`, or onStall() runs once (the overlay then shows "This video won't play here" and the
 * NASA fallback). A pause (2) or the end (0) disarms it until the next play request; playing once ends the watch.
 */
export const YT_STALL_MS = 12000;
export function stallWatch(onStall, { ms = YT_STALL_MS, timers = globalThis } = {}) {
  let t = 0, done = false;
  const clear = () => { if (t) timers.clearTimeout(t); t = 0; };
  return {
    play(wait = ms) { if (done) return; clear(); t = timers.setTimeout(() => { t = 0; if (!done) { done = true; onStall(); } }, wait); },
    state(s) { if (s === 1) { done = true; clear(); } else if (s === 0 || s === 2) clear(); },
    dispose() { done = true; clear(); },
    get armed() { return !!t; },
  };
}
