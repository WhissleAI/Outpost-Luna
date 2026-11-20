// Voice in: always-on mic over WS /ws/listen (listen.js), Web Speech fallback, Space push-to-talk (Head Start model).
// The mic opens after the first gesture and stays open. Holding Space marks the turn "for the guide"; on release
// (after a 500 ms tail so the last word lands) or on the server's turn end, the app asks.
// Barge-in follows docs/SESSION_CONTRACT.md §3 rule 2: Space always wins; open-mic speech while the guide or the crew
// is playing wins only for a real, intentional interruption (barge.js decideBarge: words not energy, not an echo,
// directed, loud enough over the speaker leak, sustained, outside the grace windows). A barge-in that produced no
// actionable turn says the interrupted sentence again, once (BARGE_TUNING.RECOVER_MS). Every stop and every held turn
// lands in window.__outpost.bargeLog (bargelog.js).
// Drives the .askbar state classes, #listenState, #liveWords, #spaceHint and the #micLevel meter.
// (floor.css is imported by main.js, so this module loads under `node --test`: tests/voice_gate.test.js)
import { createListener as defaultListener } from "./listen.js";
import { floor as defaultFloor, spaceAction, micErrorText, isFiller, normWords, takesOffer, turnIsEcho, stepOpen, BARGE } from "./floor.js";
import { decideBarge, isCommand, saysStop, BARGE_TUNING, energyNeed } from "./barge.js";
import { logBarge } from "./bargelog.js";
import { maskProfanity, hasProfanity } from "./profanity.js";
import { paintLinked } from "./highlight.js";   // the ear's linked names, marked in the kid's words
import * as echoref from "./echoref.js";       // what we play -> the ear's echo reference (libarc ABI 2)
import { videoCommand } from "./media/commands.js";   // [media] the video overlay's four voice controls
import { onEngine, earNote, earErrorIsFatal, setEarFailed, earFailed, noEar } from "./engine.js";      // [#87] the desktop shell's "ear restarting" / "voice off"
import { createRoom, effectiveFilter } from "./room.js";   // the automatic room state: calm / busy / loud (docs/HANDSFREE.md)
export { spaceAction, micErrorText };

const CLASSES = ["is-idle", "is-listening", "is-hearing", "is-thinking", "is-speaking", "is-notice"];
const CLASS_OF = { off: ["is-idle"], error: ["is-idle"], listening: ["is-listening"], hearing: ["is-hearing"], thinking: ["is-thinking"],
  speaking: ["is-speaking"], notice: ["is-listening", "is-notice"] };
/** The displayed state (P0, the owner's "keeps flickering badly"): every state the bar shows stays up at least DWELL ms,
 *  and a request superseded inside that window never paints. "Thinking" shows only for a turn the router took (or one
 *  still undecided THINK_AFTER ms after it ended); an open-mic turn shows no words and no "Hearing you" until the
 *  router accepts it (room talk leaves no trace). Space / push-to-talk and the Web Speech fallback are explicit: the
 *  kid meant us, so their words and "Hearing you" show at once. */
/** [0.4.1] The bar's word for room talk the router kept off a guess or a choice (turn_router.crew_talk): a tap or Space
 *  still answers. */
export const CREW_TALK = "Crew talk";
export const DISPLAY = { DWELL: 600, THINK_AFTER: 450, THINK_MAX: 3000, NOTICE_MS: 1800, DECIDED_MS: 4000 };
const ECHO_TAIL_MS = 2000;   // after output stops, the mic can still deliver its echo for a moment (hard mute ≥ 600 ms)
const ECHO_LINES_MS = 12000; // what we said in the last 12 s is an echo reference too (the last few lines, not only this one)

/**
 * @param {object} o
 * @param {(text:string)=>Promise} o.onTurn   the kid finished a turn
 * @param {(o:{keepGuide:boolean, reason:string})=>void} o.onBargeIn  the kid started talking (the floor already stopped the
 *                                            guide, ducked the crew; keepGuide: muted, the silent line keeps its captions)
 * @param {()=>void} o.onKidDone              the kid stopped without asking
 * @param {(label:string)=>void} o.onEmotion
 * @param {()=>boolean} [o.isOutputBusy]      extra "audio is playing" signal (the floor's holder is the main one)
 * @param {()=>object|null} [o.screen]        the screen frame the router gets ({screen, step_type, offer}, main.js)
 * @param {object} [o.floor]                  the floor manager (default: the app's one floor; tests pass their own)
 * @param {Function} [o.createListener]       the mic socket factory (default: listen.js; tests pass a fake ear)
 */
export function createVoice({ onTurn, onBargeIn, onKidDone, onEmotion, isOutputBusy = () => false, screen = () => null,
  floor = defaultFloor, createListener = defaultListener }) {
  const $ = id => document.getElementById(id);
  const bar = $("askbar"), stateEl = $("listenState"), wordsEl = $("liveWords"), hintEl = $("spaceHint"), micBtn = $("mic");
  let mode = "off", wsBroken = false, starting = false, srOn = false;
  let lastContext = null;
  let finalBuf = "", interim = "", turnAsked = false, kidTalking = false, state = "off";
  const ptt = { held: false, tail: null, latch: false, latchT: 0 };
  const turnText = () => (finalBuf + " " + interim).trim();
  /** Settings → Listening → "Hold to talk": open-mic turns are ignored; only Space / a held mic turn counts. */
  const prefListen = () => !!(window.__outpost && window.__outpost.prefs && window.__outpost.prefs.listen === "ptt");
  // ----- the room (room.js): busy / loud rooms make listening stricter on their own, never looser than Settings -----
  // A busy room raises the filter one level (here, in barge.js and on the server); when open mic keeps catching chatter
  // it asks for hold to talk; a loud room, or voice that keeps failing, offers typing and then switches to it. Calm
  // again: open voice, silently. One short line in the bar says what changed (roomChanged).
  const roomEst = createRoom({ onChange: (s, p) => roomChanged(s, p) });
  const roomLine = () => roomEst.snapshot().line;
  /** Hold to talk: Settings → Listening → "Hold to talk", or the room asked for it. Space / the mic / controller X talk. */
  const pttOnly = () => prefListen() || roomEst.mode !== "open";
  const prefFilter = () => (window.__outpost && window.__outpost.prefs && window.__outpost.prefs.filter) || "normal";

  // ----- mic level meter (#micLevel, in the listen row) -----
  const meter = document.createElement("span");
  meter.id = "micLevel"; meter.className = "mic-level"; meter.setAttribute("aria-hidden", "true"); meter.hidden = true;
  meter.innerHTML = "<i></i>";
  const listenRow = $("listen"); if (listenRow) listenRow.insertBefore(meter, stateEl);
  // Smoothed, and silent below the room's noise floor (a hum never moves it); "hot" has hysteresis so it can't blink.
  let lvl = 0, hot = false;
  const NOISE_FLOOR = 0.12;
  // Mic energy for the barge-in check (ducked-reference gating). The ear turns our own voice leaking back from the
  // speakers into confident nonsense and Arc rates it device-directed, so the words can't tell it from the kid; the
  // level can. Each 80 ms mic frame is compared with what we are putting out at that moment (floor.outputLevel: the
  // playing sentence's decoded envelope) times the speaker-to-mic coupling (the median mic/output ratio while we play,
  // kept across lines: it is a property of the room and the device, not of the line). A frame is the kid's when it is
  // ENERGY_LEAK_X louder than that expected leak, and above the room floor. A turn heard while we play needs
  // ENERGY_FRAMES such frames (~320 ms) in its window. Where no envelope exists (crew clips, video, the browser voice)
  // the expected leak is the loud end (p90) of the mic level while that audio plays.
  const mic = [];   // [{t, rms, kid}] the last 6 s of 80 ms frames
  let room = 0, leakPrior = 0, line = null;   // line: {frames, barged} while one of our lines plays
  const ratios = [];   // mic / output while our audio is loud: the coupling is their median
  const p90 = xs => { const v = xs.map(f => f.rms).sort((a, b) => a - b); return v.length ? v[Math.min(v.length - 1, Math.floor(v.length * 0.9))] : 0; };
  const coupling = () => { if (ratios.length < 6) return null; const v = ratios.slice().sort((a, b) => a - b); return v[Math.floor(v.length / 2)]; };
  if (floor) floor.on("playback", e => {
    if (!e || (e.kind !== "guide" && e.kind !== "crew")) return;
    if (e.state === "start") { line = { frames: [], barged: false }; return; }
    if (line && !line.barged && !muted() && line.frames.length >= 8) { const x = p90(line.frames); leakPrior = leakPrior ? leakPrior * 0.7 + x * 0.3 : x; }
    line = null;
  });
  function track(rms) {
    const t = performance.now(), busy = outputBusy();
    const out = busy && floor && floor.outputLevel ? floor.outputLevel() : null;
    if (out != null && out > 0.02) { ratios.push(rms / out); if (ratios.length > 150) ratios.shift(); }
    const c = coupling(), T = BARGE_TUNING;
    // kid: true / false against the envelope; null when there's no envelope (the p90 fallback decides)
    const kid = out == null || !busy ? null : c == null ? false : rms >= Math.max(T.ENERGY_ABS_MIN, room * T.ENERGY_FLOOR_X, T.ENERGY_LEAK_X * c * out);
    mic.push({ t, rms, kid }); while (mic.length && t - mic[0].t > 6000) mic.shift();
    if (line && busy) { line.frames.push({ t, rms }); if (line.frames.length > 400) line.frames.shift(); }
    else if (!busy && !gated && !kidTalking && !ptt.held) room = !room ? rms : rms < room ? room * 0.7 + rms * 0.3 : room * 0.995 + rms * 0.005;
  }
  /** The turn's energy: {turn: the loudest 3-frame mean in the window, need (fallback), loud: the kid's frames}.
   *  null when no mic levels came (tests with a fake ear). */
  function turnEnergy(g) {
    const now = performance.now();
    const win = mic.filter(f => f.t >= (g.ended ? g.t0 - 800 : now - 1000));
    if (!mic.length || !win.length) return null;
    const pre = line ? line.frames.filter(f => f.t < g.t0 - 300) : [];
    const need = energyNeed(Math.max(leakPrior, pre.length >= 4 ? p90(pre) : 0), room);
    const top = win.map(f => f.rms).sort((a, b) => b - a).slice(0, 3);
    const loud = win.filter(f => (f.kid == null ? f.rms >= need : f.kid)).length;
    return { turn: top.reduce((a, b) => a + b, 0) / top.length, need, loud, coupling: coupling() };
  }
  function level(rms) {
    track(rms);
    roomEst.frame(rms, { playing: outputBusy() || ptt.held });   // our own voice and a held Space turn are not the room
    if (gated && !gated.timer) check();   // the energy test runs per frame: no waiting for the ear's next message
    let v = Math.min(1, Math.sqrt(Math.max(0, rms)) * 2.2);   // perceptual-ish: quiet speech still moves the bar
    v = v < NOISE_FLOOR ? 0 : (v - NOISE_FLOOR) / (1 - NOISE_FLOOR);
    lvl = lvl * 0.75 + v * 0.25;
    if (lvl < 0.01) lvl = 0;
    meter.style.setProperty("--lvl", lvl.toFixed(3));
    hot = hot ? lvl > 0.18 : lvl > 0.3;
    meter.classList.toggle("is-hot", hot && shown === "hearing");
  }

  // ----- the displayed state: one state machine with a minimum dwell (DISPLAY) -----
  // `state` is the logical state (what the voice module is doing); `shown` is what the bar paints. The bar's classes
  // (border glow, the orb's animation, the label) come only from paint(), so they follow the displayed state.
  const explicit = () => ptt.held || pttTurn || srOn;
  let shown = null, shownLabel = "", shownAt = 0, showT = 0, want = null, wantLabel = "", noticeT = 0;
  function paint(s, label) {
    shown = s; shownLabel = label; shownAt = Date.now();
    bar.classList.remove(...CLASSES); bar.classList.add(...CLASS_OF[s]); stateEl.textContent = label;
  }
  function request(s, label = "") {
    want = s; wantLabel = label; clearTimeout(showT);
    if (s === shown && label === shownLabel) return;
    const wait = shownAt + DISPLAY.DWELL - Date.now();
    if (wait > 0) showT = setTimeout(() => request(want, wantLabel), wait);
    else paint(s, label);
  }
  const displayOf = s => (s === "hearing" && !explicit() ? "listening" : s);   // room talk never shows "Hearing you"
  function set(s, label = "") {
    state = s;
    if (!noticeT || s !== "listening") { clearTimeout(noticeT); noticeT = 0; request(displayOf(s), label); }
    micBtn.classList.toggle("on", mode === "ws" || srOn);
    micBtn.setAttribute("aria-label", mode === "ws" ? "Turn the mic off" : "Turn the mic on");
    meter.hidden = mode !== "ws"; if (meter.hidden) { lvl = 0; meter.style.setProperty("--lvl", "0"); }
  }
  const idle = () => { if (!kidTalking) set(mode === "ws" ? "listening" : "off"); };
  /** The kid's words show live only for an explicit turn (Space held, the Web Speech fallback). An open-mic turn shows
   *  its words only once the router took it (main.js showHeard), so overheard room talk is never on screen. */
  let turnLinks = [];   // the ear's names on this turn's final words (linked / abstain / not_in_list, with p)
  const showWords = () => { if (explicit()) paintLinked(wordsEl, turnText(), turnLinks, maskProfanity); };

  // ----- the router's decision for a finished turn (main.js forwards every `heard` decision: decided()) -----
  let pending = null, thinkT = 0;
  const decisions = [];   // [{q, outcome, at}] recent decisions: the ear relay's can arrive before the client's own turn ends
  const keyOf = t => normWords(t || "").join(" ");
  function thinking() {
    set("thinking"); clearTimeout(thinkT);
    thinkT = setTimeout(() => { if (state === "thinking") idle(); }, DISPLAY.THINK_MAX);   // a nav with nothing to say
  }
  function resolve(outcome) {
    if (pending) { clearTimeout(pending.timer); pending = null; }
    if (outcome === "ignore") { if (state === "thinking") idle(); return; }
    if (state !== "speaking") thinking();
  }
  const HOLD = hintEl.lastElementChild.textContent || "Hold to talk";
  const note = text => { hintEl.lastElementChild.textContent = text; };
  // ----- the room's effects on the bar: one short line, the hold-to-talk mic, typing (room.js) -----
  const qEl = $("q"), Q_PLACEHOLDER = qEl ? qEl.placeholder : "";
  function roomChanged(s, p) {
    if (bar.dataset) bar.dataset.room = s.mode;
    if (hintEl.dataset) hintEl.dataset.room = s.mode;
    if (!earNote()) note(s.line || HOLD);
    if (qEl) qEl.placeholder = s.mode === "type" ? s.line : Q_PLACEHOLDER;
    // typing: the text box takes the keyboard once (not from another text box, not under Settings or a dialog)
    if (s.mode === "type" && p.mode !== "type" && qEl && typeof document.querySelector === "function") {
      const a = document.activeElement, busy = a && a !== document.body && (/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable);
      const modal = document.querySelector(".a11y-panel:not([hidden]), dialog[open]");
      if (!busy && !modal) { try { qEl.focus({ preventScroll: true }); } catch (e) { /* hidden */ } }
    }
    if (s.mode === "open" && ptt.latch) release();
    try { dispatchEvent(new CustomEvent("outpost:room", { detail: { ...s, filter: effectiveFilter(prefFilter(), s.state) } })); } catch (e) { /* tests */ }
  }
  // the turn's speech-to-noise: its loudest 80 ms frame in the last 1.5 s over the room's floor
  const turnSnr = () => { const now = performance.now(), f = roomEst.floor; const pk = mic.filter(x => now - x.t < 1500).reduce((a, x) => Math.max(a, x.rms), 0);
    return f > 0 && pk > 0 ? pk / f : null; };
  const roomTurns = [];   // [{q, text, dd, uconf, snr, ptt, at}] heard turns waiting for the router's decision
  function roomTurn({ text, ptt: viaPtt }) {
    roomTurns.push({ q: keyOf(text), text, dd: turnDD, uconf: turnUconf, snr: turnSnr(), ptt: !!viaPtt, at: Date.now() });
    while (roomTurns.length > 6) roomTurns.shift();
  }
  /** An open-mic turn heard while hold to talk is on: never sent, but still evidence (room talk, or calm again). */
  function roomOpenMic(text) {
    const lo = (BARGE[effectiveFilter(prefFilter(), roomEst.state)] || BARGE.normal)[0];
    roomEst.turn({ text, outcome: null, dd: turnDD, lo, uconf: turnUconf, snr: turnSnr() });
  }
  // [qa] The ear can drop (model server restarted, too many sessions): never show the server's words to a kid; reconnect
  // on our own with a back-off, and put "Hold to talk" back once the mic is live again.
  let retryT = 0, retries = 0, userOff = false, everOn = false;
  function earLost() {
    if (userOff || retryT) return;
    note(earNote() || "Voice paused. Reconnecting…");
    const wait = Math.min(30000, 2000 * 2 ** retries++);
    retryT = setTimeout(async () => { retryT = 0; wsBroken = false; if (!(await startAlwaysOn()) && !userOff && mode !== "ws") earLost(); }, wait);
  }
  function micBlocked(e) {
    set("error", "Mic blocked");
    const msg = micErrorText(e);
    wordsEl.textContent = msg; wordsEl.title = msg; note("Type instead");
  }

  // ----- the floor -----
  const muted = () => !!(floor && floor.muted);
  /** The kid takes the floor. `reason`: ptt | webspeech | turn_start (nothing playing) | speech | command | awaited. */
  function bargeIn(reason = "speech", text = "", g = null) {
    kidTalking = true;
    const playing = !!floor && (floor.holder === "guide" || floor.holder === "crew" || floor.guideBusy || !!isOutputBusy());
    const keep = muted() && reason !== "ptt";   // Mute: our line plays silently (captions), nothing to barge into
    if (floor) { floor.setKid(true); if (!keep) floor.stopGuide("barge:" + reason); floor.duck(0.15); }
    if (playing) {
      const en = g ? turnEnergy(g) : null;
      logBarge({ kind: "barge", reason, text, energy: en ? +en.turn.toFixed(4) : null, need: en ? +en.need.toFixed(4) : null, loud: en ? en.loud : null,
        ms: g ? Math.round(performance.now() - g.t0) : 0, playing: !keep, dd: turnDD, muted: keep });
      if (!keep && reason !== "ptt" && reason !== "webspeech") armRecover(text);
    }
    // Hook for the flow code (tours, lessons): which line a barge-in cut, so a flow can offer Resume. Fired for every
    // barge-in, with playing=false when nothing of ours was audible.
    try {
      const li = floor && floor.interrupted;
      dispatchEvent(new CustomEvent("outpost:barge", { detail: { reason, text, playing: playing && !keep,
        lineId: li ? li.id : null, lineText: li ? li.text : "", resumable: !!(li && !li.resumed) } }));
    } catch (e) { /* no window / CustomEvent (tests) */ }
    onBargeIn({ keepGuide: keep, reason });
  }
  // ----- a false interruption: say the interrupted sentence again (once) -----
  let recov = null, playStarts = 0;
  if (floor) floor.on("playback", e => { if (e && e.state === "start") playStarts++; });
  const frameKey = () => { const f = frameNow() || {}; return [f.screen, f.lesson_id, f.step, f.offer, f.step_type].join("|"); };
  function armRecover(text) {
    if (recov) clearTimeout(recov.timer);
    recov = null;
    if (!floor || !floor.resumeInterrupted || isCommand(text) || saysStop(text)) return;   // "stop", "skip", "next": the kid meant it
    recov = { at: performance.now(), text, frame: frameKey(), plays: playStarts, endAt: 0, dropped: false, outcome: null, answered: false, timer: 0 };
    recov.timer = setTimeout(tickRecover, BARGE_TUNING.RECOVER_MS);
  }
  function tickRecover() {
    const r = recov; if (!r) return;
    const now = performance.now();
    const drop = () => { recov = null; };
    if (now - r.at > BARGE_TUNING.RECOVER_MAX_MS) return drop();
    if (playStarts !== r.plays || frameKey() !== r.frame) return drop();     // the turn did something: a reply, a new step
    if (r.outcome && r.outcome !== "ignore") return drop();
    if (r.final && saysStop(r.final)) return drop();                       // "… Stop." at the end of the turn: keep quiet
    const open = kidTalking || ptt.held || !!gated;
    if (!open && r.endAt && (r.dropped || r.outcome === "ignore" || r.answered || now - r.endAt >= BARGE_TUNING.RECOVER_MS)) {
      recov = null; floor.resumeInterrupted({ maxAgeMs: BARGE_TUNING.RECOVER_MAX_MS }); return;
    }
    r.timer = setTimeout(tickRecover, 150);
  }
  const recEnd = (how, text = "") => { if (!recov || recov.endAt) return; recov.endAt = performance.now(); recov.final = text; if (how === "dropped") recov.dropped = true; };
  function kidDone() {
    recEnd("dropped");
    kidTalking = false;
    if (floor) { floor.setKid(false); floor.unduck(); }      // no request: the crew comes back, the guide doesn't repeat
    onKidDone(); idle();
  }
  function askTurn(text) {
    const exp = explicit();
    turnAsked = true; finalBuf = ""; interim = ""; kidTalking = false;
    if (exp) paintLinked(wordsEl, text || "", turnLinks, maskProfanity);
    if (floor) floor.setKid(false);
    if (!text) { kidDone(); return; }
    // Never answer ourselves or a hum: filler ("oh", "mm-mm") and echoes of our last few lines are dropped silently.
    // The reply the screen waits for (an offer's "next" / "yes", a step's answer) is an echo only when one of our
    // lines was on air at the turn start (turnIsEcho: the same rule as backend turn_router.echo()).
    const onAir = turnAir || airNow(); turnAir = false;
    if (!ptt.held && !pttTurn && (isFiller(text) || turnIsEcho({ text, frame: frameNow(), onAir, refs: refsNow(),
      oldRefs: saidRefs(3000, ECHO_LINES_MS) }))) { if (exp) wordsEl.textContent = ""; kidDone(); return; }   // filler / echo: no state change at all
    recEnd("asked", text);
    const viaPtt = pttTurn; pttTurn = false;
    roomTurn({ text, ptt: viaPtt });
    // "Thinking" waits for the router (decided()): an ignored turn goes back to "Listening" with no flash. A decision
    // that already arrived (the server's ear relay can beat the client's own turn end) is used at once.
    const q = keyOf(text), now = Date.now(), early = decisions.find(d => d.q === q && now - d.at < DISPLAY.DECIDED_MS);
    if (pending) clearTimeout(pending.timer);
    pending = null;
    // The client already knows most room talk: Arc says it was for someone else (the router's not_directed rule), or
    // it is rude. Those never start the "Thinking" clock; a late "yes, it's for us" from the router still shows it.
    const lo = (BARGE[effectiveFilter(prefFilter(), roomEst.state)] || BARGE.normal)[0];
    const roomTalk = !exp && ((turnDD != null && turnDD < lo) || hasProfanity(text));
    if (early) { if (early.outcome === "ignore") idle(); else thinking(); }
    else if (roomTalk) { idle(); pending = { q, timer: 0 }; }
    else {
      idle();
      const p = pending = { q, timer: setTimeout(() => { if (pending === p) { pending = null; thinking(); } }, DISPLAY.THINK_AFTER) };
    }
    const done = r => {   // no session (POST /api/ask): no decision will come; the answer is over, so the turn is too
      if (r === "session") return;
      if (recov) recov.answered = true;
      if (pending) { clearTimeout(pending.timer); pending = null; }
      if (state === "thinking") idle();
    };
    Promise.resolve(onTurn(text, { ptt: viaPtt, dd: turnDD, safety: turnSafety })).then(done, () => done()).finally(() => {
      if (floor && !floor.guideBusy && !kidTalking) floor.unduck();   // the answer didn't take the floor: un-duck the crew
    });
  }

  // Echo references: what we're playing now, plus what we played in the last ECHO_TAIL_MS (the mic lags the speaker).
  let recent = { refs: [], until: 0 };
  const liveRefs = () => floor ? [floor.guideText, floor.guideSentence, floor.crewText].filter(Boolean) : [];
  if (floor) floor.on("floor", ({ holder }) => {
    if (holder === "guide" || holder === "crew") recent = { refs: liveRefs(), until: Infinity };
    else if (recent.until === Infinity) recent.until = performance.now() + ECHO_TAIL_MS;
  });
  if (floor) floor.on("sentence", () => { recent.refs = liveRefs(); });
  // On air: a line of ours is playing right now (no tail). A turn keeps the value it had at its start.
  // floor.onAir also covers a queued multi-line say between its lines (the next line's audio still loading): the
  // whole CAPCOM sequence is one on-air span, so the ear never slips into the gap (the server's Spoken `more` hold).
  const airNow = () => { if (muted()) return false; const h = floor ? floor.holder : "none"; return h === "guide" || h === "crew" || !!(floor && floor.onAir) || !!isOutputBusy(); };
  const frameNow = () => { try { return screen() || null; } catch (e) { return null; } };
  let turnAir = false;
  const outputBusy = () => {
    if (muted()) return false;   // Mute: nothing audible, so nothing for the mic to hear back and nothing to barge into
    const h = floor ? floor.holder : "none";
    return h === "guide" || h === "crew" || !!(floor && floor.onAir) || isOutputBusy() || performance.now() < recent.until;
  };
  const said = [];   // [{text, at}] the last few lines any app voice spoke
  const remember = t => { if (!t) return; said.push({ text: t, at: performance.now() }); if (said.length > 8) said.shift(); };
  if (floor) floor.on("playback", e => { if (e && e.text) remember(e.text); });
  if (floor) floor.on("sentence", e => { if (e && e.text) remember(e.text); });
  const saidRefs = (lo, hi) => { const now = performance.now(); return said.filter(x => now - x.at >= lo && now - x.at < hi).map(x => x.text); };
  const refsNow = () => [...liveRefs(), ...recent.refs, ...saidRefs(0, 3000)];
  // Lines older than 3 s (turnIsEcho's oldRefs): only a near-verbatim repeat of ≥ 3 words is an echo.

  // An open-mic turn heard while audio plays: held back until it passes the barge-in check (barge.js decideBarge), or
  // dropped at its end (echo, room talk, noise). A check that waits on a timing window runs again when it ends.
  let gated = null, turnDD = null, turnSafety = null, pttTurn = false, idleStart = false, turnUconf = null;
  let arcSeen = false;   // this ear sends Arc metadata: a turn it never rated (noise, far-off chatter) can't interrupt
  function gate(m) {
    if (m.t === "turn" && (m.state === "start" || m.state === "resumed")) {
      if (gated) clearTimeout(gated.timer);
      gated = { text: m.text || "", air: airNow(), t0: performance.now(), ended: false, timer: 0 };
      check(); return;
    }
    if (!gated) return;                                     // words of a turn whose start we didn't see while busy
    if (m.text) gated.text = m.text;
    if (airNow()) gated.air = true;                         // one of our lines started during the turn
    if (m.t === "turn" && m.state === "end") gated.ended = true;
    check();
  }
  function check() {
    const g = gated; if (!g) return;
    clearTimeout(g.timer); g.timer = 0;
    // Only the echo tail (our line already ended): the reply the screen waits for gets through, as on the server.
    const f = frameNow() || {};
    const awaited = !!g.text && ((f.screen === "video" && !!videoCommand(g.text)) ||   // [media] "pause" while a video plays
      (!g.air && !isFiller(g.text) && (takesOffer(g.text, f.offer) || stepOpen(f)) &&
      !turnIsEcho({ text: g.text, frame: f, onAir: false, refs: refsNow() })));
    const en = awaited ? null : turnEnergy(g);
    const d = awaited ? { act: "barge", reason: "awaited" } : decideBarge({ text: g.text, refs: refsNow(), dd: turnDD, final: g.ended,
      speechMs: performance.now() - g.t0, sinceLineMs: floor ? floor.lineMs : Infinity, sinceSentenceMs: floor ? floor.sentenceMs : Infinity, energy: en,
      rated: !arcSeen || turnDD != null });
    if (typeof window !== "undefined" && window.__bargeTrace) window.__bargeTrace({ d, text: g.text, en, dd: turnDD });   // harness only
    if (d.act === "barge") {
      const text = g.text; turnAir = g.air; gated = null;
      turnAsked = false; finalBuf = ""; interim = text;
      if (line) line.barged = true;
      bargeIn(d.reason, text, g); set("hearing"); showWords();
      if (g.ended) askTurn(text);
      return;
    }
    if (d.act === "wait" && d.retryMs) { g.timer = setTimeout(() => { if (gated === g) check(); }, d.retryMs); return; }
    if (g.ended) {                                          // echo / chatter / noise: dropped, the line plays on
      gated = null;
      roomEst.held(d.reason);
      if (g.text || d.reason !== "no_words") logBarge({ kind: "held", reason: d.reason, text: g.text, energy: en ? +en.turn.toFixed(4) : null, loud: en ? en.loud : null,
        need: en ? +en.need.toFixed(4) : null, ms: Math.round(performance.now() - g.t0), playing: outputBusy(), dd: turnDD });
    }
  }

  const listener = createListener({
    message(m) {
      if (m.t === "ready") { if (earFailed()) { setEarFailed(false); note(earNote() || roomLine() || HOLD); } idle(); if (lastContext) listener.send(lastContext); }   // [0.3.12] an ear that answers clears "Voice off"
      else if (m.t === "arc") { arcSeen = true; if (typeof m.device_directed === "number") turnDD = m.device_directed; if (Array.isArray(m.safety)) turnSafety = m.safety; }
      else if ((m.t === "words" || m.t === "turn") && pttOnly() && !ptt.held && !ptt.tail && !pttTurn) {   // hold to talk (Settings or the room)
        if (m.t === "turn" && m.state === "start") { turnDD = null; turnUconf = null; }
        if (m.t === "words" && m.final && typeof m.uconf === "number") turnUconf = m.uconf;
        if (m.t === "turn" && m.state === "end" && (m.text || "").trim()) roomOpenMic((m.text || "").trim());   // still room evidence
      }
      else if (m.t === "words" || m.t === "turn") {
        if (m.t === "turn" && m.state === "start") { turnDD = null; turnSafety = null; turnLinks = []; turnUconf = null; }
        if (m.t === "words" && m.final && typeof m.uconf === "number") turnUconf = m.uconf;
        // While the guide or the crew plays, the mic also hears our speakers: open-mic speech is gated (§3.2).
        // A turn that began in silence and has no real word yet when one of our lines starts: from now on it is gated
        // like any turn heard while we play (it must not take the floor and cut the new line).
        if (idleStart && !kidTalking && !ptt.held && outputBusy()) {
          idleStart = false; gated = { text: turnText(), air: true, t0: performance.now(), ended: false, timer: 0 };
        }
        if (!ptt.held && !kidTalking && (gated || outputBusy())) { gate(m); return; }
        if (m.t === "words") {
          if (m.final) { finalBuf += (m.text || "") + " "; interim = ""; if (Array.isArray(m.names)) turnLinks = turnLinks.concat(m.names);
            // the ear's speaking time for this stretch (numbers only): a read-aloud step's words a minute (academy/speech_steps.js)
            if (typeof m.speech_s === "number") { try { dispatchEvent(new CustomEvent("outpost:ear-final", { detail: { speech_s: m.speech_s, max_pause_s: m.max_pause_s } })); } catch (e) { /* */ } } } else interim = m.text || "";
          if (idleStart && !isFiller(turnText())) { idleStart = false; bargeIn("turn_start", turnText()); set("hearing"); }
          showWords();
        }
        // Nothing playing: the turn takes the floor at its first real word (a hum or a noise "start" never does: it
        // would hold back the next line and cancel what the session has queued).
        else if (m.state === "start") { turnAir = airNow(); turnAsked = false; finalBuf = ""; interim = m.text || "";
          if (isFiller(m.text || "")) idleStart = true; else { idleStart = false; bargeIn("turn_start", m.text || ""); set("hearing"); } }
        else if (m.state === "resumed") { kidTalking = true; if (floor) floor.setKid(true); turnAsked = false; set("hearing"); }
        else if (m.state === "end") { if (ptt.held && ptt.latch && (m.text || turnText())) { release(); return; } if (ptt.held) return; idleStart = false; if (!turnAsked) askTurn((m.text || turnText()).trim()); }
      }
      else if (m.t === "emotion") { if (m.label) onEmotion(m.label); }
      else if (m.t === "error") { console.warn("ear error:", m.message); if (earErrorIsFatal(m.message)) setEarFailed(true); note(earNote() || "Voice paused. Reconnecting…"); }   // a kid never reads "sent 1011 (internal error)"
    },
    level,
    close() { if (mode === "ws") { mode = "off"; kidTalking = false; if (floor) floor.setKid(false); set("off"); earLost(); } },
    micError: micBlocked,
  });

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null;
  if (SR) {
    rec = new SR(); rec.lang = "en-US"; rec.interimResults = true; rec.continuous = true;
    rec.onresult = e => {
      interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) { const r = e.results[i]; if (r.isFinal) finalBuf += r[0].transcript + " "; else interim += r[0].transcript; }
      showWords(); if (!kidTalking) bargeIn("webspeech", turnText());
    };
    rec.onstart = () => { srOn = true; set("hearing"); };
    rec.onend = () => { srOn = false; askTurn(turnText()); };
    rec.onerror = e => { if (e.error === "not-allowed" || e.error === "service-not-allowed" || e.error === "audio-capture") micBlocked(e); };
  }
  const canWS = !!(navigator.mediaDevices && window.AudioWorkletNode);
  if ((!canWS || noEar()) && !SR) { set("error", "Type to ask"); micBtn.hidden = true; } else { micBtn.hidden = false; set("off"); }
  if (noEar()) note(earNote());

  async function startAlwaysOn() {
    if (noEar()) return false;   // [ipad] no local ear on this device: the mic button is the system's recognition (srStart)
    if (mode === "ws" || starting || wsBroken || !canWS) return mode === "ws";
    starting = true; set("thinking", "Mic on…");
    const ok = await listener.start(); starting = false;
    if (ok === true && typeof listener.clock === "function") echoref.bind(listener);
    if (ok === true) { mode = "ws"; retries = 0; userOff = false; everOn = true; note(earNote() || roomLine() || HOLD); idle(); return true; }
    if (ok !== "mic") { wsBroken = true; set("off"); earLost(); }   // [qa] retry with a back-off (the ear may be warming up)       // "mic": micBlocked already showed why
    return false;
  }
  function stopAlwaysOn() { userOff = true; clearTimeout(retryT); retryT = 0; echoref.bind(null); listener.stop(); mode = "off"; kidTalking = false; if (floor) floor.setKid(false); set("off"); }
  function srStart() { if (!rec || srOn) return; finalBuf = ""; interim = ""; turnAsked = false; try { rec.start(); } catch (e) { /* already running */ } }

  // [#87] The desktop shell restarted the ear (engine.js): say so while it is away; once it is back, reconnect at once
  // (not at the end of the back-off), but only a mic that was on before and that the kid did not switch off.
  onEngine((s, prev) => {
    const n = earNote(s);
    if (n) { note(n); return; }
    if (s.ear !== "ok" || prev.ear === "ok") return;
    note(roomLine() || HOLD);
    if (mode === "ws" || userOff || !everOn) return;
    clearTimeout(retryT); retryT = 0; retries = 0; wsBroken = false;
    startAlwaysOn().then(ok => { if (!ok && !userOff && mode !== "ws") earLost(); });
  });

  // First gesture anywhere opens the mic (browsers need a gesture for audio + mic).
  const firstGesture = () => { removeEventListener("pointerdown", firstGesture, true); removeEventListener("keydown", firstGesture, true); startAlwaysOn(); };
  addEventListener("pointerdown", firstGesture, true); addEventListener("keydown", firstGesture, true);

  micBtn.onclick = async () => {
    if (skipClick) { skipClick = false; return; }                     // the press-and-hold above already talked
    if (mode === "ws" && pttOnly()) { if (ptt.held) release(); else pttDown({ latch: true }); return; }   // hold to talk: a tap talks
    if (mode === "ws") { stopAlwaysOn(); return; }
    if (srOn) { rec.stop(); return; }
    userOff = false; wsBroken = false;   // [qa] a tap always tries the local ear again (it may have been warming up)
    if (await startAlwaysOn()) return;
    if (!starting) srStart();
  };

  // Space = push-to-talk anywhere except while typing. A focused button is blurred first (it would otherwise eat the
  // key, or click on keyup).
  addEventListener("keydown", async e => {
    if (e.code !== "Space" || e.metaKey || e.ctrlKey || e.altKey) return;
    const act = spaceAction(e.target);
    if (act === "ignore") return;
    e.preventDefault();
    if (act === "blur" && document.activeElement && document.activeElement.blur) document.activeElement.blur();
    if (e.repeat || ptt.held) return;
    await pttDown();
  });
  /** Push-to-talk starts: Space held, the mic held, or (latch) a tap of the mic / M / controller X in hold-to-talk. A
   *  latched turn ends with the ear's turn end (or a second tap, or LATCH_MS). */
  const LATCH_MS = 12000;
  async function pttDown({ latch = false } = {}) {
    ptt.held = true; pttTurn = true; if (ptt.tail) { clearTimeout(ptt.tail); ptt.tail = null; }
    clearTimeout(ptt.latchT); ptt.latch = latch; if (latch) ptt.latchT = setTimeout(release, LATCH_MS);
    if (gated) clearTimeout(gated.timer);
    gated = null; idleStart = false;
    bargeIn("ptt"); turnAsked = false; finalBuf = ""; interim = ""; wordsEl.textContent = "";
    if (mode !== "ws" && !wsBroken) await startAlwaysOn();
    set("hearing");
    if (mode !== "ws" && ptt.held) srStart();
  }
  // Hold to talk on the mic button itself (pointer / touch): press = talk, let go = send. A click (keyboard Enter, the
  // M key, controller X) taps a latched turn instead (micBtn.onclick).
  let micHeld = false, skipClick = false;
  if (micBtn.addEventListener) micBtn.addEventListener("pointerdown", e => {
    if (!pttOnly() || e.button !== 0 || mode !== "ws") return;
    e.preventDefault(); micHeld = true; skipClick = true; pttDown();
  });
  const micUp = () => { if (!micHeld) return; micHeld = false; release(); };
  if (micBtn.addEventListener) ["pointerup", "pointercancel", "pointerleave"].forEach(ev => micBtn.addEventListener(ev, micUp));
  function release() {
    if (!ptt.held) return; ptt.held = false; ptt.latch = false; clearTimeout(ptt.latchT);
    ptt.tail = setTimeout(() => {
      ptt.tail = null;
      if (mode === "ws") { if (!turnAsked) askTurn(turnText()); }
      else if (srOn) rec.stop();
      else kidDone();
    }, 500);
  }
  addEventListener("keyup", e => { if (e.code !== "Space" || !ptt.held) return; e.preventDefault(); release(); });
  addEventListener("blur", release);

  // tests / tools / screenshots: window.__outpost.roomEst.force("busy") (or "loud", "loud","type"; null = automatic)
  (window.__outpost = window.__outpost || {}).room = {
    get state() { return roomEst.state; }, get mode() { return roomEst.mode; }, get floor() { return roomEst.floor; },
    snapshot: () => ({ ...roomEst.snapshot(), filter: effectiveFilter(prefFilter(), roomEst.state) }),
    filter: pref => effectiveFilter(pref || prefFilter(), roomEst.state), force: (st, m) => roomEst.force(st, m),
  };
  { const iv = setInterval(() => roomEst.tick(), 1000); if (iv && iv.unref) iv.unref(); }   // evidence decays with no new frames (mic off)

  return {
    /** Show the guide speaking / thinking / back to listening. Never overrides the kid's own turn. */
    show(s) { if (kidTalking || ptt.held) return; if (s === "idle") idle(); else set(s); },
    clearWords() { wordsEl.textContent = ""; },
    /** the ear's names on the last turn's final words (main.js showHeard marks the linked ones) */
    links() { return turnLinks; },
    /** The router's decision for a turn (main.js forwards every `heard` decision): "ignore" ends it quietly (no
     *  "Thinking", no words); anything else shows "Thinking" until the reply speaks. */
    decided(outcome, text, d = null) {
      const q = keyOf(text), now = Date.now();
      { const i = roomTurns.findIndex(x => x.q && (x.q === q || x.q.includes(q) || q.includes(x.q)) && now - x.at < DISPLAY.DECIDED_MS);
        if (i >= 0) { const u = roomTurns.splice(i, 1)[0];
          roomEst.turn({ ...u, outcome, reason: (d && d.reason) || "", notice: !!(d && d.notice), lo: (BARGE[effectiveFilter(prefFilter(), roomEst.state)] || BARGE.normal)[0] }); } }
      if (recov && !recov.outcome) recov.outcome = outcome;
      decisions.push({ q, outcome, at: now });
      while (decisions.length > 8 || (decisions[0] && now - decisions[0].at > DISPLAY.DECIDED_MS)) decisions.shift();
      if (pending && (!q || pending.q === q || pending.q.includes(q) || q.includes(pending.q))) resolve(outcome);
      else if (outcome !== "ignore" && !pending && state !== "speaking" && !kidTalking && !ptt.held) thinking();   // e.g. a typed turn it took
    },
    /** A tiny, silent "didn't catch that" on the mic chip (hands-free: a device-directed turn we could not use). */
    notice(text = "Didn't catch that") {
      if (kidTalking || ptt.held) return;
      clearTimeout(noticeT); request("notice", text);
      noticeT = setTimeout(() => { noticeT = 0; request(displayOf(state), ""); }, DISPLAY.NOTICE_MS);
    },
    /** What the bar shows right now (tests, tools/chatter_steady.py). */
    get displayed() { return shown; },
    /** Forward a context frame on the listen socket (kept and re-sent when the socket becomes ready). */
    sendContext(frame) { lastContext = frame; listener.send(frame); },
    get kidTalking() { return kidTalking || ptt.held; },
    get micOn() { return mode === "ws" || srOn; },
  };
}
