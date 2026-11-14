// Voice in: always-on mic over WS /ws/listen (listen.js), Web Speech fallback, Space push-to-talk (Head Start model).
// The mic opens after the first gesture and stays open. Holding Space marks the turn "for the guide"; on release
// (after a 500 ms tail so the last word lands) or on the server's turn end, the app asks.
// Barge-in follows docs/SESSION_CONTRACT.md §3 rule 2: Space always wins; open-mic speech while the guide or the crew
// is playing wins only when it isn't an echo of what we're playing (shouldBargeIn in floor.js).
// Drives the .askbar state classes, #listenState, #liveWords, #spaceHint and the #micLevel meter.
// (floor.css is imported by main.js, so this module loads under `node --test`: tests/voice_gate.test.js)
import { createListener as defaultListener } from "./listen.js";
import { floor as defaultFloor, shouldBargeIn, spaceAction, micErrorText, isFiller, normWords, takesOffer, turnIsEcho, stepOpen } from "./floor.js";
export { spaceAction, micErrorText };

const CLASSES = ["is-idle", "is-listening", "is-hearing", "is-thinking", "is-speaking"];
const CLASS_OF = { off: "is-idle", error: "is-idle", listening: "is-listening", hearing: "is-hearing", thinking: "is-thinking", speaking: "is-speaking" };
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
  let lvl = 0;
  function level(rms) {
    const v = Math.min(1, Math.sqrt(rms) * 2.2);          // perceptual-ish: quiet speech still moves the bar
    lvl = v > lvl ? v : lvl * 0.7 + v * 0.3;
    meter.style.setProperty("--lvl", lvl.toFixed(3));
    meter.classList.toggle("is-hot", lvl > 0.25);
  }

  function set(s, label = "") {
    state = s; bar.classList.remove(...CLASSES); bar.classList.add(CLASS_OF[s]);
    stateEl.textContent = label;
    micBtn.classList.toggle("on", mode === "ws" || srOn);
    micBtn.setAttribute("aria-label", mode === "ws" ? "Turn the mic off" : "Turn the mic on");
    meter.hidden = mode !== "ws"; if (meter.hidden) meter.style.setProperty("--lvl", "0");
  }
  const idle = () => { if (!kidTalking) set(mode === "ws" ? "listening" : "off"); };
  const showWords = () => { wordsEl.textContent = turnText(); };
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
    turnAsked = true; finalBuf = ""; interim = ""; kidTalking = false; wordsEl.textContent = text || "";
    if (floor) floor.setKid(false);
    if (!text) { kidDone(); return; }
    // Never answer ourselves or a hum: filler ("oh", "mm-mm") and echoes of our last few lines are dropped silently.
    // The reply the screen waits for (an offer's "next" / "yes", a step's answer) is an echo only when one of our
    // lines was on air at the turn start (turnIsEcho: the same rule as backend turn_router.echo()).
    const onAir = turnAir || airNow(); turnAir = false;
    if (!ptt.held && !pttTurn && (isFiller(text) || turnIsEcho({ text, frame: frameNow(), onAir, refs: refsNow(),
      oldRefs: saidRefs(3000, ECHO_LINES_MS) }))) { wordsEl.textContent = ""; kidDone(); return; }
    const viaPtt = pttTurn; pttTurn = false;
    set("thinking");
    onTurn(text, { ptt: viaPtt }).finally(() => {
      if (state === "thinking") idle();
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
  let gated = null, turnDD = null, pttTurn = false;
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
      else if (m.t === "arc") { if (typeof m.device_directed === "number") turnDD = m.device_directed; }
      else if ((m.t === "words" || m.t === "turn") && pttOnly() && !ptt.held && !ptt.tail && !pttTurn) { /* Settings → Listening: hold to talk */ }
      else if (m.t === "words" || m.t === "turn") {
        if (m.t === "turn" && m.state === "start") turnDD = null;
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
    /** A tiny, silent "didn't catch that" on the mic chip (hands-free: a device-directed turn we could not use). */
    notice(text = "Didn't catch that") {
      if (kidTalking || ptt.held) return;
      stateEl.textContent = text; bar.classList.add("is-notice");
      clearTimeout(this._nt); this._nt = setTimeout(() => { bar.classList.remove("is-notice"); if (stateEl.textContent === text) stateEl.textContent = ""; }, 1800);
    },
    /** Forward a context frame on the listen socket (kept and re-sent when the socket becomes ready). */
    sendContext(frame) { lastContext = frame; listener.send(frame); },
    get kidTalking() { return kidTalking || ptt.held; },
    get micOn() { return mode === "ws" || srOn; },
  };
}
