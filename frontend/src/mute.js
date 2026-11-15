// Global Mute (top bar, next to Settings): silences every sound the app makes and keeps everything on screen (captions,
// the cards, the CAPCOM log). Output only: the mic and the ear are untouched. Persisted in prefs (prefs.muted).
//
// What it silences:
//   * the voice floor: the line playing stops now (stopSpeaking), the browser voice is cancelled, and floor.js reads
//     levels().muted for every new line (its <audio> plays muted; the browser voice at volume 0);
//   * Web Audio (chimes, the radio beep, crew clips through player.js's master gain): levels().master is 0;
//   * every <audio>/<video> element, in the page or not (crew clips, previews, our video player): muted on play and now;
//   * YouTube embeds: the iframe API's postMessage {func: "mute"} (the media branch's player may also listen to the
//     "outpost:mute" event, the hook for any other player).
// Keys: Shift+M (M alone is the mic). Voice: "mute" / "unmute" (router intents mute_sound / unmute_sound).
import { icon } from "./assets/icons.js";
import { stopSpeaking } from "./floor.js";

const played = new Set();   // media elements that played while we ran (not all are in the DOM: new Audio())
let installed = false;

export const isMuted = () => !!(window.__outpost && window.__outpost.prefs && window.__outpost.prefs.muted);

function applyMedia(m) {
  played.forEach(el => { try { if (el.ended) { played.delete(el); return; } el.muted = m; } catch (e) { played.delete(el); } });
  document.querySelectorAll("audio, video").forEach(el => { el.muted = m; });
  document.querySelectorAll('iframe[src*="youtube"]').forEach(f => {
    try { f.contentWindow.postMessage(JSON.stringify({ event: "command", func: m ? "mute" : "unMute", args: [] }), "*"); } catch (e) { /* cross-origin not ready */ }
  });
}

/** Mute or unmute: every sound stops now (or comes back), the button and the prefs follow, listeners hear outpost:mute. */
export function setMuted(on, { quiet = false } = {}) {
  const api = window.__outpost && window.__outpost.prefsApi;
  if (api && api.value.muted !== !!on) api.update({ muted: !!on });
  if (on) {
    try { stopSpeaking("mute"); } catch (e) { /* no floor yet */ }
    try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (e) { /* no synth */ }
  }
  applyMedia(!!on);
  paint();
  dispatchEvent(new CustomEvent("outpost:mute", { detail: { muted: !!on } }));
  if (!quiet) toast(on ? "Sound off. Captions stay on." : "Sound on.");
  return !!on;
}
export const toggleMute = () => setMuted(!isMuted());

function toast(text) {
  const live = document.getElementById("muteLive"); if (live) live.textContent = text;
}

function paint() {
  const b = document.getElementById("muteBtn"); if (!b) return;
  const m = isMuted();
  b.setAttribute("aria-pressed", String(m));
  b.setAttribute("aria-label", m ? "Unmute" : "Mute sound");
  b.title = m ? "Unmute (Shift+M)" : "Mute sound (Shift+M)";
  b.innerHTML = icon(m ? "mute" : "speaker", { size: 20 });
  document.documentElement.dataset.muted = m ? "1" : "";
}

/** Put the button in the top bar (left of Settings), hook every media element's play(), and apply the stored state. */
export function installMute() {
  if (installed) return; installed = true;
  const nav = document.querySelector(".topnav"), gear = document.getElementById("a11yBtn");
  if (nav && !document.getElementById("muteBtn")) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "btn-icon"; b.id = "muteBtn";
    b.onclick = () => toggleMute();
    if (gear) gear.after(b); else nav.prepend(b);   // right next to the Settings gear
    const live = document.createElement("span"); live.id = "muteLive"; live.className = "sr-only"; live.setAttribute("role", "status"); live.setAttribute("aria-live", "polite");
    nav.append(live);
  }
  const P = HTMLMediaElement.prototype, play = P.play;
  P.play = function (...a) { played.add(this); if (isMuted()) this.muted = true; return play.apply(this, a); };
  addEventListener("outpost:prefs", e => { if (e.detail && "muted" in e.detail) { applyMedia(!!e.detail.muted); paint(); } });
  paint(); if (isMuted()) applyMedia(true);
}
