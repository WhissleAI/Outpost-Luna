// Room state (automatic, docs/HANDSFREE.md "Room state"): is the room calm, busy (classroom chatter) or too loud for
// voice? One estimator, fed by what the client already has, decides how the app listens. It is never a setting: the
// kid's own Settings → Listening choice stays, and the room only ever makes listening STRICTER than that choice.
//
//   calm  → open mic, the kid's filter                                (nothing shown)
//   busy  → the filter one level stricter (client barge gate + the server router's dd gates)
//         → and when open mic keeps catching chatter: hold to talk     ("Busy room: hold the mic to talk")
//   loud  → hold to talk, typing offered                               ("Noisy room: hold the mic, or type")
//         → still failing a while later: typing                        ("Too noisy: type instead")
//   calm again → open voice, silently.
//
// Evidence (each read on the moment and forgotten; nothing is stored or sent but the state):
//   - the noise floor: the 15th percentile of mic RMS over the last FLOOR_N quiet-side frames, only while none of our audio plays
//     (a kid talking leaves gaps; classroom babble does not, so the low percentile rises only in a busy room);
//   - turns: room talk the router or Arc kept off (dd under the filter floor, crew_talk / not_directed / chatter /
//     room_yes_no / callsign_other, a held barge-in for not_directed / not_rated), versus turns that worked;
//   - failures: a directed turn the app could not use ("Didn't catch that"), a very low utterance confidence (uconf), a
//     turn repeated after it was ignored, a speech-to-noise ratio under SNR_WEAK on a turn that was then ignored.
// Hysteresis: entering a state needs more than staying in it (separate enter / exit levels), every state is held at
// least its DWELL, and evidence decays (sliding windows).
// Pure: createRoom({now}) takes the clock from the caller; tests and frontend/tools/room_harness.mjs drive it.

export const ROOM_TUNING = {
  FLOOR_N: 125,             // noise floor = p15 (FLOOR_Q) of the last 125 quiet-side frames (10 s of mic; frames while we play are skipped)
  FLOOR_MAX_MS: 30000,      // ... none older than 30 s (so a room that talks over our lines still gets measured)
  FLOOR_Q: 0.15,            // the low percentile: a kid's own speech leaves gaps, babble does not
  FLOOR_MIN_FRAMES: 40,     // ~3 s of quiet-side frames before the floor counts at all
  FLOOR_BUSY_IN: 0.016,     // floor >= this, held BUSY_HOLD_MS → busy  (≈ -36 dBFS: babble 2-3 m away, AEC/NS on)
  FLOOR_BUSY_OUT: 0.009,    // ... back under this, held CALM_HOLD_MS → may leave busy
  FLOOR_LOUD_IN: 0.05,      // floor >= this, held LOUD_HOLD_MS → loud (≈ -26 dBFS: a loud room right at the mic)
  FLOOR_LOUD_OUT: 0.03,     // ... under this, held CALM_HOLD_MS → may leave loud
  BUSY_HOLD_MS: 4000, LOUD_HOLD_MS: 3000, CALM_HOLD_MS: 8000,
  TURN_WIN_MS: 30000,       // chatter / fail evidence window
  CHATTER_IN: 3,            // >= 3 room-talk turns in the window, and >= CHATTER_SHARE of the open-mic turns → busy
  CHATTER_SHARE: 0.6,
  CHATTER_OUT: 1,           // <= 1 room-talk turn in the window → the turns allow calm
  HOLD_CHATTER: 4,          // busy, and >= 4 room-talk turns in the window → ask for hold to talk
  FAIL_IN: 3,               // >= 3 failed turns in FAIL_WIN_MS → loud (voice keeps failing)
  FAIL_WIN_MS: 40000,
  FAIL_OUT: 1,
  OFFER_MS: 20000,          // loud: typing is offered first; still loud (or one more fail) after this → typing
  DWELL: { calm: 0, busy: 10000, loud: 15000 },
  UCONF_FAIL: 0.35,         // utterance confidence under this on a directed turn = a fail
  SNR_WEAK: 2.0,            // turn energy / floor under this, and the turn was ignored = room talk
  REPEAT_MS: 20000,         // the same words again within 20 s of an ignore: the kid had to repeat = a fail
};

/** Router ignore reasons that mean "someone else was talking". */
export const CHATTER_REASONS = new Set(["crew_talk", "not_directed", "chatter", "room_yes_no", "callsign_other"]);
/** Held barge-in reasons (bargelog) that mean room talk over our voice. */
export const HELD_CHATTER = new Set(["not_directed", "not_rated"]);

/** The filter one level stricter (busy / loud rooms). Never looser than the kid's choice. */
export const STRICTER = { relaxed: "normal", normal: "strict", strict: "strict" };
export function effectiveFilter(pref, state) {
  const f = STRICTER[pref] ? pref : "normal";
  return state === "busy" || state === "loud" ? STRICTER[f] : f;
}

/** The voice bar's line per mode (docs/COPY.md: short, plain, verb first where it can). "" = the usual hint. */
export const ROOM_LINES = {
  open: "",
  hold: "Busy room: hold the mic to talk",
  offer: "Noisy room: hold the mic, or type",
  type: "Too noisy: type instead",
};

const pct = (xs, q) => { if (!xs.length) return 0; const v = xs.slice().sort((a, b) => a - b); return v[Math.min(v.length - 1, Math.floor(v.length * q))]; };
const norm = t => String(t || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();

/**
 * @param {{now?:()=>number, tuning?:object, onChange?:(snap:object, prev:object)=>void}} o
 */
export function createRoom({ now = () => Date.now(), tuning = {}, onChange = () => {} } = {}) {
  const T = { ...ROOM_TUNING, ...tuning, DWELL: { ...ROOM_TUNING.DWELL, ...(tuning.DWELL || {}) } };
  let state = "calm", mode = "open", since = now(), forced = null;
  let frames = [];             // [{t, rms}] quiet-side frames
  let floor = 0, floorAt = 0;
  const turns = [];            // [{t, kind: "ok"|"chatter"|"fail"|"other", text}]
  let over = { busy: 0, loud: 0, calmB: 0, calmL: 0 };   // when each floor condition started holding (0 = not)
  let offerAt = 0, failsAtOffer = 0, lastIgnored = null;

  function prune(t) {
    while (frames.length && (frames.length > T.FLOOR_N || t - frames[0].t > T.FLOOR_MAX_MS)) frames.shift();
    while (turns.length && t - turns[0].t > Math.max(T.TURN_WIN_MS, T.FAIL_WIN_MS)) turns.shift();
  }
  const count = (kind, win, t) => turns.filter(x => x.kind === kind && t - x.t <= win).length;
  const openMic = (win, t) => turns.filter(x => x.kind !== "other" && t - x.t <= win).length;

  /** Hold-condition timers: cond true → remember when it started; false → reset. Returns held ms. */
  function held(key, cond, t) { if (!cond) { over[key] = 0; return 0; } if (!over[key]) over[key] = t; return t - over[key]; }

  function evaluate() {
    const t = now();
    prune(t);
    if (frames.length >= T.FLOOR_MIN_FRAMES && t - floorAt >= 250) { floor = pct(frames.map(f => f.rms), T.FLOOR_Q); floorAt = t; }
    const hasFloor = frames.length >= T.FLOOR_MIN_FRAMES;
    const busyF = held("busy", hasFloor && floor >= T.FLOOR_BUSY_IN, t) >= T.BUSY_HOLD_MS;
    const loudF = held("loud", hasFloor && floor >= T.FLOOR_LOUD_IN, t) >= T.LOUD_HOLD_MS;
    const quietB = held("calmB", !hasFloor || floor < T.FLOOR_BUSY_OUT, t) >= T.CALM_HOLD_MS;
    const quietL = held("calmL", !hasFloor || floor < T.FLOOR_LOUD_OUT, t) >= T.CALM_HOLD_MS;
    const chat = count("chatter", T.TURN_WIN_MS, t), om = openMic(T.TURN_WIN_MS, t), fails = count("fail", T.FAIL_WIN_MS, t);
    const busyT = chat >= T.CHATTER_IN && chat / Math.max(1, om) >= T.CHATTER_SHARE;
    const loudT = fails >= T.FAIL_IN;
    const dwellOk = t - since >= (T.DWELL[state] || 0);

    let next = state;
    if (forced) next = forced;
    else if (state === "calm") next = loudF || loudT ? "loud" : busyF || busyT ? "busy" : "calm";
    else if (state === "busy") {
      if (loudF || loudT) next = "loud";
      else if (dwellOk && quietB && chat <= T.CHATTER_OUT && fails <= T.FAIL_OUT) next = "calm";
    } else if (state === "loud") {
      if (dwellOk && quietL && fails <= T.FAIL_OUT) next = quietB && chat <= T.CHATTER_OUT ? "calm" : "busy";
    }
    let nmode = mode;
    if (next === "calm") nmode = "open";
    // busy: the stricter filter alone (nothing shown) until open mic keeps catching chatter; then hold to talk, which
    // stays until the room is calm again (never flips back and forth inside a busy spell). Coming down from loud: hold.
    else if (next === "busy") nmode = mode !== "open" || forced === "busy" || chat >= T.HOLD_CHATTER ? "hold" : "open";
    else if (next === "loud") {
      if (mode !== "offer" && mode !== "type") { nmode = "offer"; offerAt = t; failsAtOffer = fails; }
      else if (mode === "offer" && (t - offerAt >= T.OFFER_MS || fails > failsAtOffer)) nmode = "type";
    }
    if (next !== state || nmode !== mode) {
      const prev = snapshot();
      if (next !== state) since = t;
      state = next; mode = nmode;
      onChange(snapshot(), prev);
    }
    return snapshot();
  }

  function snapshot() {
    return { state, mode, floor: +floor.toFixed(4), line: ROOM_LINES[mode] || "", holdToTalk: mode !== "open", typing: mode === "type" };
  }

  return {
    /** One 80 ms mic frame. playing: our own audio is audible (its leak is not the room). */
    frame(rms, { playing = false } = {}) {
      const t = now();
      if (!playing && isFinite(rms) && rms >= 0) frames.push({ t, rms });
      return evaluate();
    },
    /**
     * A finished turn. outcome: the router's ("ignore" | "answer" | …) or null (dropped on the client); reason: the
     * router's ignore reason; dd: Arc device_directed; lo: the effective filter floor; uconf; snr: turn energy / floor;
     * notice: the router said it was for us but unusable; ptt / typed: explicit turns (never room talk).
     */
    turn({ text = "", outcome = null, reason = "", dd = null, lo = 0.5, uconf = null, snr = null, notice = false, ptt = false, typed = false } = {}) {
      const t = now(), key = norm(text);
      let kind = "other";
      const repeat = !!(key && lastIgnored && lastIgnored.key === key && t - lastIgnored.t <= T.REPEAT_MS);
      if (typed) kind = "other";
      else if (notice || reason === "unclear" || repeat) kind = "fail";
      else if (ptt) kind = outcome === "ignore" && !text ? "fail" : "other";
      else if (CHATTER_REASONS.has(reason) || (dd != null && dd < lo) || (outcome === "ignore" && snr != null && snr < T.SNR_WEAK)) kind = "chatter";
      else if (uconf != null && uconf < T.UCONF_FAIL && (dd == null || dd >= lo)) kind = "fail";
      else if (outcome && outcome !== "ignore") kind = "ok";
      turns.push({ t, kind, text: key });
      if (outcome === "ignore" && key && !ptt) lastIgnored = { key, t }; else if (outcome && outcome !== "ignore") lastIgnored = null;
      return evaluate();
    },
    /** A barge-in check held a turn while we played (bargelog reason). Room talk over our voice counts as chatter. */
    held(reason) { if (HELD_CHATTER.has(reason)) turns.push({ t: now(), kind: "chatter", text: "" }); return evaluate(); },
    /** Re-check on a timer (decay with no new evidence). */
    tick: evaluate,
    filter: pref => effectiveFilter(pref, state),
    /** Tests / screenshots: pin a state ("calm" | "busy" | "loud"), or null to go back to automatic (from calm). A forced busy room
     *  asks for hold to talk at once; a forced loud room offers typing, then switches after OFFER_MS (or force(...,"type")). */
    force(s, m = null) {
      forced = s === "calm" || s === "busy" || s === "loud" ? s : null;
      if (forced && m && ROOM_LINES[m] !== undefined) { const prev = snapshot(); state = forced; mode = m; since = now(); onChange(snapshot(), prev); return snapshot(); }
      if (!forced) {   // back to automatic from a clean, calm slate
        over = { busy: 0, loud: 0, calmB: 0, calmL: 0 }; frames = []; turns.length = 0; floor = 0; lastIgnored = null;
        if (state !== "calm" || mode !== "open") { const prev = snapshot(); state = "calm"; mode = "open"; since = now(); onChange(snapshot(), prev); }
      }
      return evaluate();
    },
    get state() { return state; }, get mode() { return mode; }, get floor() { return floor; },
    snapshot,
  };
}
