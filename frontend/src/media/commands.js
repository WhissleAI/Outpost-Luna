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
  return s < 50 ? `${s} sec` : `${Math.max(1, Math.round(s / 60))} min`;
}
export const watchLabel = v => `Watch (${lengthLabel(v && v.duration_s)})`;
export const NEEDS_NET = "Needs internet";
export const OFFLINE_LINE = "Needs internet. Ask a grown-up to connect.";
/** The player failed while we ARE online (YouTube error 2/5/100/101/150/153, an unknown id): not "Needs internet". */
export const NO_PLAY_LINE = "This video won't play here.";

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
