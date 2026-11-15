// The one door to NASA video (docs/LEARNING_DESIGN.md, "Video"). The player, its downloads and its offline cache are
// built in frontend/src/media/video.js (feat/media-v1): openVideo(id, {context}) -> Promise<{watched, seconds}> and
// isAvailable(id) -> "cached" | "online" | "offline". Until that module lands (or if it fails to load), every call
// here answers "missing" / {watched: false} and the caller simply goes on: a video never blocks a lesson, a briefing
// or a debrief. Skip and offline continue the same way.
//
// import.meta.glob resolves at build time: with no ./media/video.js it is an empty map (no build error), and once the
// file exists Vite bundles it as a lazy chunk. Node (the unit tests) has no import.meta.glob: the map stays empty.
let loaders = {};
try { loaders = import.meta.glob("./media/video.js"); } catch (e) { loaders = {}; }

let injected;      // tests: _setVideoModule(mod | null)
let loaded;        // the module once loaded (or null when it is missing or broken)

/** The video module, or null when it isn't there. Never throws. */
export async function videoModule() {
  if (injected !== undefined) return injected;
  if (loaded !== undefined) return loaded;
  const load = loaders["./media/video.js"];
  if (!load) return (loaded = null);
  try {
    const m = await load();
    loaded = m && typeof m.openVideo === "function" ? m : null;
  } catch (e) { loaded = null; }
  return loaded;
}

/** "cached" | "online" | "offline" from the player, or "missing" when there is no player. Never throws. */
export async function videoState(id) {
  const m = await videoModule();
  if (!m) return "missing";
  if (typeof m.isAvailable !== "function") return "online";   // a player without the probe: try to open it
  try { return (await m.isAvailable(id)) || "offline"; } catch (e) { return "offline"; }
}

/** True when the kid can watch it now (cached, or online with a connection). */
export const playable = state => state === "cached" || state === "online";

/** Play one video. Always resolves {watched, seconds}; {watched: false} when there is no player or it failed. */
export async function playVideo(id, opts = {}) {
  const m = await videoModule();
  if (!m) return { watched: false, seconds: 0, missing: true };
  try {
    const r = await m.openVideo(id, opts);
    return { watched: !!(r && r.watched), seconds: (r && +r.seconds) || 0 };
  } catch (e) { return { watched: false, seconds: 0, error: true }; }
}

/** Tests only: stand in a fake player (or null for "no player"); undefined restores the real lookup. */
export function _setVideoModule(m) { injected = m; }
