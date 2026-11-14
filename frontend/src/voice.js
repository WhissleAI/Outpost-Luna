// Voice in: always-on mic over WS /ws/listen (listen.js), Web Speech fallback, Space push-to-talk (Head Start model).
// The mic opens after the first gesture and stays open. Holding Space marks the turn "for the guide"; on release
// (after a 500 ms tail so the last word lands) or on the server's turn end, the app asks.
// Barge-in follows docs/SESSION_CONTRACT.md §3 rule 2: Space always wins; open-mic speech while the guide or the crew
// is playing wins only when it isn't an echo of what we're playing (shouldBargeIn in floor.js).
// Drives the .askbar state classes, #listenState, #liveWords, #spaceHint and the #micLevel meter.
// (floor.css is imported by main.js, so this module loads under `node --test`: tests/voice_gate.test.js)
import { createListener as defaultListener } from "./listen.js";
import { floor as defaultFloor, shouldBargeIn, spaceAction, micErrorText, isFiller, normWords, takesOffer, turnIsEcho, stepOpen, BARGE } from "./floor.js";
import { maskProfanity, hasProfanity } from "./profanity.js";
export { spaceAction, micErrorText };

const CLASSES = ["is-idle", "is-listening", "is-hearing", "is-thinking", "is-speaking", "is-notice"];
const CLASS_OF = { off: ["is-idle"], error: ["is-idle"], listening: ["is-listening"], hearing: ["is-hearing"], thinking: ["is-thinking"],
  speaking: ["is-speaking"], notice: ["is-listening", "is-notice"] };
/** The displayed state (P0, the owner's "keeps flickering badly"): every state the bar shows stays up at least DWELL ms,
 *  and a request superseded inside that window never paints. "Thinking" shows only for a turn the router took (or one
 *  still undecided THINK_AFTER ms after it ended); an open-mic turn shows no words and no "Hearing you" until the
 *  router accepts it (room talk leaves no trace). Space / push-to-talk and the Web Speech fallback are explicit: the
 *  kid meant us, so their words and "Hearing you" show at once. */
export const DISPLAY = { DWELL: 600, THINK_AFTER: 450, THINK_MAX: 3000, NOTICE_MS: 1800, DECIDED_MS: 4000 };
const ECHO_TAIL_MS = 2000;   // after output stops, the mic can still deliver its echo for a moment (hard mute ≥ 600 ms)
const ECHO_LINES_MS = 12000; // what we said in the last 12 s is an echo reference too (the last few lines, not only this one)

/**
 * @param {object} o
 * @param {(text:string)=>Promise} o.onTurn   the kid finished a turn
 * @param {()=>void} o.onBargeIn              the kid started talking (the floor already stopped the guide, ducked the crew)
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
  const ptt = { held: false, tail: null };
  const turnText = () => (finalBuf + " " + interim).trim();
  /** Settings → Listening → "Hold to talk": open-mic turns are ignored; only Space / a held mic turn counts. */
  const pttOnly = () => !!(window.__outpost && window.__outpost.prefs && window.__outpost.prefs.listen === "ptt");

  // ----- mic level meter (#micLevel, in the listen row) -----
  const meter = document.createElement("span");
  meter.id = "micLevel"; meter.className = "mic-level"; meter.setAttribute("aria-hidden", "true"); meter.hidden = true;
  meter.innerHTML = "<i></i>";
  const listenRow = $("listen"); if (listenRow) listenRow.insertBefore(meter, stateEl);
  // Smoothed, and silent below the room's noise floor (a hum never moves it); "hot" has hysteresis so it can't blink.
  let lvl = 0, hot = false;
  const NOISE_FLOOR = 0.12;
  function level(rms) {
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
  const showWords = () => { if (explicit()) wordsEl.textContent = maskProfanity(turnText()); };

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
  // [qa] The ear can drop (model server restarted, too many sessions): never show the server's words to a kid; reconnect
  // on our own with a back-off, and put "Hold to talk" back once the mic is live again.
  let retryT = 0, retries = 0, userOff = false;
  function earLost() {
    if (userOff || retryT) return;
    note("Voice paused. Reconnecting…");
    const wait = Math.min(30000, 2000 * 2 ** retries++);
    retryT = setTimeout(async () => { retryT = 0; wsBroken = false; if (!(await startAlwaysOn()) && !userOff && mode !== "ws") earLost(); }, wait);
  }
  function micBlocked(e) {
    set("error", "Mic blocked");
    const msg = micErrorText(e);
    wordsEl.textContent = msg; wordsEl.title = msg; note("Type instead");
  }

  // ----- the floor -----
  function bargeIn() {
    kidTalking = true;
    if (floor) { floor.setKid(true); floor.stopGuide(); floor.duck(0.15); }
    onBargeIn();
  }
  function kidDone() {
    kidTalking = false;
    if (floor) { floor.setKid(false); floor.unduck(); }      // no request: the crew comes back, the guide doesn't repeat
    onKidDone(); idle();
  }
  function askTurn(text) {
    const exp = explicit();
    turnAsked = true; finalBuf = ""; interim = ""; kidTalking = false;
    if (exp) wordsEl.textContent = maskProfanity(text || "");
    if (floor) floor.setKid(false);
    if (!text) { kidDone(); return; }
    // Never answer ourselves or a hum: filler ("oh", "mm-mm") and echoes of our last few lines are dropped silently.
    // The reply the screen waits for (an offer's "next" / "yes", a step's answer) is an echo only when one of our
    // lines was on air at the turn start (turnIsEcho: the same rule as backend turn_router.echo()).
    const onAir = turnAir || airNow(); turnAir = false;
    if (!ptt.held && !pttTurn && (isFiller(text) || turnIsEcho({ text, frame: frameNow(), onAir, refs: refsNow(),
      oldRefs: saidRefs(3000, ECHO_LINES_MS) }))) { if (exp) wordsEl.textContent = ""; kidDone(); return; }   // filler / echo: no state change at all
    const viaPtt = pttTurn; pttTurn = false;
    // "Thinking" waits for the router (decided()): an ignored turn goes back to "Listening" with no flash. A decision
    // that already arrived (the server's ear relay can beat the client's own turn end) is used at once.
    const q = keyOf(text), now = Date.now(), early = decisions.find(d => d.q === q && now - d.at < DISPLAY.DECIDED_MS);
    if (pending) clearTimeout(pending.timer);
    pending = null;
    // The client already knows most room talk: Arc says it was for someone else (the router's not_directed rule), or
    // it is rude. Those never start the "Thinking" clock; a late "yes, it's for us" from the router still shows it.
    const lo = (BARGE[(window.__outpost && window.__outpost.prefs && window.__outpost.prefs.filter) || "normal"] || BARGE.normal)[0];
    const roomTalk = !exp && ((turnDD != null && turnDD < lo) || hasProfanity(text));
    if (early) { if (early.outcome === "ignore") idle(); else thinking(); }
    else if (roomTalk) { idle(); pending = { q, timer: 0 }; }
    else {
      idle();
      const p = pending = { q, timer: setTimeout(() => { if (pending === p) { pending = null; thinking(); } }, DISPLAY.THINK_AFTER) };
    }
    const done = r => {   // no session (POST /api/ask): no decision will come; the answer is over, so the turn is too
      if (r === "session") return;
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
  const airNow = () => { const h = floor ? floor.holder : "none"; return h === "guide" || h === "crew" || !!(floor && floor.onAir) || !!isOutputBusy(); };
  const frameNow = () => { try { return screen() || null; } catch (e) { return null; } };
  let turnAir = false;
  const outputBusy = () => {
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

  // An open-mic turn heard while audio plays: held back until it passes the barge-in check (or ends as an echo).
  let gated = null, turnDD = null, turnSafety = null, pttTurn = false;
  function gate(m) {
    if (m.t === "turn" && (m.state === "start" || m.state === "resumed")) { gated = { text: m.text || "", air: airNow() }; return; }
    if (!gated) return;                                     // words of a turn whose start we didn't see while busy
    if (m.text) gated.text = m.text;
    if (airNow()) gated.air = true;                         // one of our lines started during the turn
    // Only the echo tail (our line already ended): the reply the screen waits for gets through, as on the server.
    const f = frameNow() || {};
    const awaited = !gated.air && !isFiller(gated.text) && (takesOffer(gated.text, f.offer) || stepOpen(f)) &&
      !turnIsEcho({ text: gated.text, frame: f, onAir: false, refs: refsNow() });
    const pass = awaited || shouldBargeIn({ started: true, text: gated.text, refs: refsNow(), dd: turnDD });
    if (!pass) { if (m.t === "turn" && m.state === "end") gated = null; return; }   // echo / chatter: drop it
    const text = gated.text; turnAir = gated.air; gated = null;
    turnAsked = false; finalBuf = ""; interim = text;
    bargeIn(); set("hearing"); showWords();
    if (m.t === "turn" && m.state === "end") askTurn(text);
  }

  const listener = createListener({
    message(m) {
      if (m.t === "ready") { idle(); if (lastContext) listener.send(lastContext); }
      else if (m.t === "arc") { if (typeof m.device_directed === "number") turnDD = m.device_directed; if (Array.isArray(m.safety)) turnSafety = m.safety; }
      else if ((m.t === "words" || m.t === "turn") && pttOnly() && !ptt.held && !ptt.tail && !pttTurn) { /* Settings → Listening: hold to talk */ }
      else if (m.t === "words" || m.t === "turn") {
        if (m.t === "turn" && m.state === "start") { turnDD = null; turnSafety = null; }
        // While the guide or the crew plays, the mic also hears our speakers: open-mic speech is gated (§3.2).
        if (!ptt.held && !kidTalking && (gated || outputBusy())) { gate(m); return; }
        if (m.t === "words") { if (m.final) { finalBuf += (m.text || "") + " "; interim = ""; } else interim = m.text || ""; showWords(); }
        else if (m.state === "start") { turnAir = airNow(); turnAsked = false; bargeIn(); set("hearing"); }
        else if (m.state === "resumed") { kidTalking = true; if (floor) floor.setKid(true); turnAsked = false; set("hearing"); }
        else if (m.state === "end") { if (ptt.held) return; if (!turnAsked) askTurn((m.text || turnText()).trim()); }
      }
      else if (m.t === "emotion") { if (m.label) onEmotion(m.label); }
      else if (m.t === "error") { console.warn("ear error:", m.message); note("Voice paused. Reconnecting…"); }   // a kid never reads "sent 1011 (internal error)"
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
      showWords(); if (!kidTalking) bargeIn();
    };
    rec.onstart = () => { srOn = true; set("hearing"); };
    rec.onend = () => { srOn = false; askTurn(turnText()); };
    rec.onerror = e => { if (e.error === "not-allowed" || e.error === "service-not-allowed" || e.error === "audio-capture") micBlocked(e); };
  }
  const canWS = !!(navigator.mediaDevices && window.AudioWorkletNode);
  if (!canWS && !SR) { set("error", "Type to ask"); micBtn.hidden = true; } else { micBtn.hidden = false; set("off"); }

  async function startAlwaysOn() {
    if (mode === "ws" || starting || wsBroken || !canWS) return mode === "ws";
    starting = true; set("thinking", "Mic on…");
    const ok = await listener.start(); starting = false;
    if (ok === true) { mode = "ws"; retries = 0; userOff = false; note(HOLD); idle(); return true; }
    if (ok !== "mic") { wsBroken = true; set("off"); earLost(); }   // [qa] retry with a back-off (the ear may be warming up)       // "mic": micBlocked already showed why
    return false;
  }
  function stopAlwaysOn() { userOff = true; clearTimeout(retryT); retryT = 0; listener.stop(); mode = "off"; kidTalking = false; if (floor) floor.setKid(false); set("off"); }
  function srStart() { if (!rec || srOn) return; finalBuf = ""; interim = ""; turnAsked = false; try { rec.start(); } catch (e) { /* already running */ } }

  // First gesture anywhere opens the mic (browsers need a gesture for audio + mic).
  const firstGesture = () => { removeEventListener("pointerdown", firstGesture, true); removeEventListener("keydown", firstGesture, true); startAlwaysOn(); };
  addEventListener("pointerdown", firstGesture, true); addEventListener("keydown", firstGesture, true);

  micBtn.onclick = async () => {
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
    ptt.held = true; pttTurn = true; if (ptt.tail) { clearTimeout(ptt.tail); ptt.tail = null; }
    gated = null;
    bargeIn(); turnAsked = false; finalBuf = ""; interim = ""; wordsEl.textContent = "";
    if (mode !== "ws" && !wsBroken) await startAlwaysOn();
    set("hearing");
    if (mode !== "ws" && ptt.held) srStart();
  });
  function release() {
    if (!ptt.held) return; ptt.held = false;
    ptt.tail = setTimeout(() => {
      ptt.tail = null;
      if (mode === "ws") { if (!turnAsked) askTurn(turnText()); }
      else if (srOn) rec.stop();
      else kidDone();
    }, 500);
  }
  addEventListener("keyup", e => { if (e.code !== "Space" || !ptt.held) return; e.preventDefault(); release(); });
  addEventListener("blur", release);

  return {
    /** Show the guide speaking / thinking / back to listening. Never overrides the kid's own turn. */
    show(s) { if (kidTalking || ptt.held) return; if (s === "idle") idle(); else set(s); },
    clearWords() { wordsEl.textContent = ""; },
    /** The router's decision for a turn (main.js forwards every `heard` decision): "ignore" ends it quietly (no
     *  "Thinking", no words); anything else shows "Thinking" until the reply speaks. */
    decided(outcome, text) {
      const q = keyOf(text), now = Date.now();
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
