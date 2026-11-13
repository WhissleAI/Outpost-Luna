// Voice in: always-on mic over WS /ws/listen (listen.js), Web Speech fallback, Space push-to-talk (Head Start model).
// The mic opens after the first gesture and stays open. Holding Space marks the turn "for the guide"; on release
// (after a 500 ms tail so the last word lands) or on the server's turn end, the app asks.
// Drives the .askbar state classes, #listenState, #liveWords and #spaceHint from index.html.
import { createListener } from "./listen.js";

const CLASSES = ["is-idle", "is-listening", "is-hearing", "is-thinking", "is-speaking"];
const CLASS_OF = { off: "is-idle", error: "is-idle", listening: "is-listening", hearing: "is-hearing", thinking: "is-thinking", speaking: "is-speaking" };

/**
 * @param {object} o
 * @param {(text:string)=>Promise} o.onTurn   the kid finished a turn
 * @param {()=>void} o.onBargeIn              the kid started talking (stop the guide, duck the crew)
 * @param {()=>void} o.onKidDone              the kid stopped without asking
 * @param {(label:string)=>void} o.onEmotion
 */
export function createVoice({ onTurn, onBargeIn, onKidDone, onEmotion, isOutputBusy = () => false }) {
  const $ = id => document.getElementById(id);
  const bar = $("askbar"), stateEl = $("listenState"), wordsEl = $("liveWords"), hintEl = $("spaceHint"), micBtn = $("mic");
  let mode = "off", wsBroken = false, starting = false, srOn = false;
  let lastContext = null;
  let finalBuf = "", interim = "", turnAsked = false, kidTalking = false, state = "off";
  const ptt = { held: false, tail: null };
  const turnText = () => (finalBuf + " " + interim).trim();

  function set(s, label = "") {
    state = s; bar.classList.remove(...CLASSES); bar.classList.add(CLASS_OF[s]);
    stateEl.textContent = label;
    micBtn.classList.toggle("on", mode === "ws" || srOn);
    micBtn.setAttribute("aria-label", mode === "ws" ? "Turn the mic off" : "Turn the mic on");
  }
  const idle = () => { if (!kidTalking) set(mode === "ws" ? "listening" : "off"); };
  const showWords = () => { wordsEl.textContent = turnText(); };
  const note = text => { hintEl.lastElementChild.textContent = text; };

  function bargeIn() { kidTalking = true; onBargeIn(); }
  function kidDone() { kidTalking = false; onKidDone(); idle(); }
  function askTurn(text) {
    turnAsked = true; finalBuf = ""; interim = ""; kidTalking = false; wordsEl.textContent = text || "";
    if (!text) { kidDone(); return; }
    set("thinking");
    onTurn(text).finally(() => { if (state === "thinking") idle(); });
  }

  const listener = createListener({
    message(m) {
      if (m.t === "ready") { idle(); if (lastContext) listener.send(lastContext); }
      // While the guide or the crew is playing, the open mic hears the speakers too (echo cancellation misses some of it).
      // Then only a held Space counts as the kid; open-mic words and turns are ignored.
      else if ((m.t === "words" || m.t === "turn") && isOutputBusy() && !ptt.held && !kidTalking) return;
      else if (m.t === "words") { if (m.final) { finalBuf += (m.text || "") + " "; interim = ""; } else interim = m.text || ""; showWords(); }
      else if (m.t === "turn") {
        if (m.state === "start") { turnAsked = false; bargeIn(); set("hearing"); }
        else if (m.state === "resumed") { kidTalking = true; turnAsked = false; set("hearing"); }
        else if (m.state === "end") { if (ptt.held) return; if (!turnAsked) askTurn((m.text || turnText()).trim()); }
      }
      else if (m.t === "emotion") { if (m.label) onEmotion(m.label); }
      else if (m.t === "error") note("Voice hiccup: " + (m.message || "try again"));
    },
    close() { if (mode === "ws") { mode = "off"; kidTalking = false; set("off"); } },
    micError() { set("error", "Mic blocked"); note("Allow the mic, or type"); },
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
    rec.onerror = e => { if (e.error === "not-allowed" || e.error === "service-not-allowed") set("error", "Mic blocked"); };
  }
  const canWS = !!(navigator.mediaDevices && window.AudioWorkletNode);
  if (!canWS && !SR) { set("error", "Type to ask"); micBtn.hidden = true; } else { micBtn.hidden = false; set("off"); }

  async function startAlwaysOn() {
    if (mode === "ws" || starting || wsBroken || !canWS) return mode === "ws";
    starting = true; set("thinking", "Mic on…");
    const ok = await listener.start(); starting = false;
    if (ok === true) { mode = "ws"; idle(); return true; }
    if (ok !== "mic") wsBroken = true;
    set(ok === "mic" ? "error" : "off", ok === "mic" ? "Mic blocked" : ""); return false;
  }
  function stopAlwaysOn() { listener.stop(); mode = "off"; kidTalking = false; set("off"); }
  function srStart() { if (!rec || srOn) return; finalBuf = ""; interim = ""; turnAsked = false; try { rec.start(); } catch (e) { /* already running */ } }

  // First gesture anywhere opens the mic (browsers need a gesture for audio + mic).
  const firstGesture = () => { removeEventListener("pointerdown", firstGesture, true); removeEventListener("keydown", firstGesture, true); startAlwaysOn(); };
  addEventListener("pointerdown", firstGesture, true); addEventListener("keydown", firstGesture, true);

  micBtn.onclick = async () => {
    if (mode === "ws") { stopAlwaysOn(); return; }
    if (srOn) { rec.stop(); return; }
    if (await startAlwaysOn()) return;
    if (!starting) srStart();
  };

  const typing = e => e.target && e.target.closest && e.target.closest("input, textarea, select, button, [contenteditable], dialog[open]");
  addEventListener("keydown", async e => {
    if (e.code !== "Space" || typing(e) || e.metaKey || e.ctrlKey || e.altKey) return;
    e.preventDefault(); if (e.repeat || ptt.held) return;
    ptt.held = true; if (ptt.tail) { clearTimeout(ptt.tail); ptt.tail = null; }
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
    /** Forward a context frame on the listen socket (kept and re-sent when the socket becomes ready). */
    sendContext(frame) { lastContext = frame; listener.send(frame); },
    get kidTalking() { return kidTalking || ptt.held; },
    get micOn() { return mode === "ws" || srOn; },
  };
}
