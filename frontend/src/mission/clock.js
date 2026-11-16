// The live mission clock (docs/GAMEPLAY.md §2). Mission time runs on its own: about one sim hour per HOUR_MS of real
// time at 1x, so a 6-hour shift is ~70 s of clock plus the tasks (2–4 minutes of play). The kid can pause it, warp it
// (1x / 2x / 4x) or skip to the next event; it pauses by itself during any decision, confirm, card or tour, and while
// the app is hidden (`held()` names why).
//
// Pure timing, no DOM and no network: the UI passes `held` (why time must wait, or null) and `post(dtH)` (send the
// hours that passed to the sim, POST /api/mission/{id}/step). Tested with node --test (tests/gameplay.test.js) using a
// fake timer.
export const HOUR_MS = 12000;      // one sim hour at 1x: 12 s (the brief asked 8–15 s)
export const WARPS = [1, 2, 4];
export const FF_WARP = 8;          // [polish 2] hold-to-fast-forward (the Skip button, F, RT): this fast while held
export const TICK_MS = 250;        // frame rate of the clock's own bookkeeping
export const POST_MS = 1000;       // the sim hears about the passing time about once a second

/**
 * @param {object} o
 * @param {(dtH:number)=>Promise} o.post       send mission hours to the sim (one call in flight at a time)
 * @param {()=>string|null} [o.held]           why time can't run right now (decision, confirm, card, tour, hidden), or null
 * @param {(c:object)=>void} [o.onChange]      the clock's running / warp / held state changed (repaint the controls)
 * @param {()=>number} [o.now]                 ms clock (performance.now)
 * @param {object} [o.timers]                  {setInterval, clearInterval} (tests pass fakes)
 * @param {number|(()=>number)} [o.hourMs]     ms of real time per sim hour at 1x (default HOUR_MS)
 */
export function createMissionClock({ post, held = () => null, onChange = () => {}, now = () => (globalThis.performance ? performance.now() : Date.now()),
  timers = globalThis, hourMs = HOUR_MS } = {}) {
  let started = false, userPaused = true, warp = 1, owed = 0, last = null, sinceP = 0, inflight = false, iv = null, why = null, total = 0, ff = false;
  const snapshot = () => ({ started, running: running(), warp, held: why, paused: userPaused, total, ff: ff && running() });
  const running = () => started && !userPaused && !why;
  let lastKey = "";
  function changed() { const s = snapshot(), k = JSON.stringify([s.started, s.running, s.warp, s.held, s.paused, s.ff]); if (k !== lastKey) { lastKey = k; onChange(s); } }
  async function flush(force) {
    if (inflight || owed <= 0) return;
    if (!force && sinceP < POST_MS && owed < 0.5) return;
    const dt = owed; owed = 0; sinceP = 0; inflight = true;
    try { await post(dt); total += dt; } catch (e) { /* the next tick tries again with the next slice */ }
    finally { inflight = false; }
  }
  function tick() {
    const t = now(), dtMs = last == null ? 0 : Math.max(0, Math.min(2000, t - last)); last = t;
    why = held() || null;
    const H = (typeof hourMs === "function" ? hourMs() : hourMs) || HOUR_MS;
    if (running()) { owed += dtMs / H * (ff ? FF_WARP : warp); sinceP += dtMs; }
    changed();
    flush(false);
  }
  return {
    /** Begin ticking (the cabin is up). The clock itself waits for play(). */
    attach() { if (!iv) { last = now(); iv = timers.setInterval(tick, TICK_MS); } changed(); },
    detach() { if (iv) { timers.clearInterval(iv); iv = null; } owed = 0; last = null; },
    play() { started = true; userPaused = false; last = now(); changed(); },
    pause() { userPaused = true; flush(true); changed(); },
    toggle() { if (running() || (started && !userPaused)) this.pause(); else this.play(); return !userPaused; },
    /** 1, 2 or 4; no argument: the next speed up (4 wraps to 1). */
    setWarp(w) { warp = WARPS.includes(+w) ? +w : WARPS[(WARPS.indexOf(warp) + 1) % WARPS.length]; changed(); return warp; },
    /** Something happened (an event that stops a skip): drop to 1x, like a console game's time warp. A held
     *  fast-forward stays the player's (a decision holds the clock anyway; letting go ends it). */
    dropWarp() { if (warp !== 1) { warp = 1; changed(); } },
    /** [polish 2] Hold to fast-forward: FF_WARP while held (only while the clock runs), back to the speed on release. */
    hold(on) { if (!!on === ff) return ff; ff = !!on; last = now(); changed(); return ff; },
    /** A skip or an end-shift moved time on the server: forget the slice owed so far. */
    reset() { owed = 0; sinceP = 0; },
    tick, flush: () => flush(true),
    get started() { return started; }, get running() { return running(); }, get warp() { return warp; }, get held() { return why; },
    get paused() { return userPaused; }, get ff() { return ff && running(); }, get state() { return snapshot(); },
  };
}
