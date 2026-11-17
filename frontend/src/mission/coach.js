// First mission, teach by doing (docs/MISSION_POLISH_SPEC.md, wave 4): replaces the 12-step cabin tour, which stays
// in Settings -> Help ("Show me around"). One prompt at a time, in place, beside the one control it is about:
//   now  — the Now card's button ("Your job is always here. Press Enter to do it.")
//   time — Skip ahead ("Time runs by itself. Hold F to speed it up.")
//   menu — Menu ("Esc pauses. The menu has speed and restart.")
// A prompt goes away when the player does it (ui.js calls did(id)); "time" and "menu" also step aside after a while,
// so a player who never needs them is not nagged. Prompts have no buttons: the Now card stays the only place that
// says what to do (play_mission.py counts competing buttons). They hide during an event takeover and while the Now
// card has nothing to press. The words follow the input in use (keys, controller, touch / mouse).
import { COACH } from "../story.js";

export const COACH_STEPS = ["now", "time", "menu"];
const KEY = cs => "outpost-coach-done:" + (cs || "cadet");
export const coachDone = cs => { try { return localStorage.getItem(KEY(cs)) === "1"; } catch (e) { return false; } };
export const markCoachDone = cs => { try { localStorage.setItem(KEY(cs), "1"); } catch (e) { /* private mode */ } };
/** The prompt's words for an input mode: "keys" | "pad" | anything else (touch, mouse, voice). */
export const coachText = (id, input) => { const c = COACH[id]; if (!c) return ""; return input === "keys" ? c.keys : input === "pad" ? c.pad : c.touch; };
/** How long a prompt that the player may never need stays up (ms); "now" waits for the press. */
export const COACH_MAX_MS = { now: 0, time: 25000, menu: 15000 };

/** Where each prompt points (inside the cabin root). The first match that is on screen wins. */
const ANCHOR = { now: ["#cbNow:not([hidden]) .cb-now-b.is-hot", "#cbNow:not([hidden]) .cb-now-b"], time: ["#cbSkip"], menu: ["#cbMenuBtn"] };

/**
 * @param {object} o
 * @param {HTMLElement} o.host        the cabin's root (#mCabin): the prompt is positioned inside it
 * @param {() => string} o.callsign   the stored call sign (done is remembered per call sign)
 * @param {() => string} [o.input]    the input mode (html[data-input])
 * @param {(id:string) => boolean} [o.ready]  may this prompt show now (e.g. "time" once the clock runs)
 */
export function createCoach({ host, callsign = () => "", input = () => document.documentElement.dataset.input || "", ready = () => true, log = () => {} }) {
  let i = -1, el = null, raf = 0, shownAt = 0;
  const active = () => i >= 0 && i < COACH_STEPS.length;
  const cur = () => (active() ? COACH_STEPS[i] : null);
  function bubble() {
    if (el && el.isConnected) return el;
    el = document.createElement("div"); el.className = "cb-coach"; el.setAttribute("role", "note"); el.setAttribute("aria-live", "polite"); el.hidden = true;
    host.append(el); return el;
  }
  const visible = n => !!(n && n.getClientRects().length && getComputedStyle(n).visibility !== "hidden");
  function anchor(id) { for (const s of ANCHOR[id] || []) { const n = host.querySelector(s); if (visible(n)) return n; } return null; }
  function place() {
    raf = 0; if (!active()) return;
    raf = requestAnimationFrame(place);
    const id = cur(), b = bubble(), a = anchor(id), take = !!host.querySelector(".cb.is-takeover");
    const show = !!a && !take && ready(id);
    if (!show) { if (!b.hidden) b.hidden = true; return; }
    const text = coachText(id, input());
    if (b.dataset.id !== id || b.dataset.text !== text) {
      b.dataset.id = id; b.dataset.text = text;
      b.innerHTML = `<span class="cb-coach-n" aria-hidden="true">${i + 1}/${COACH_STEPS.length}</span><span class="cb-coach-t"></span>`;
      b.querySelector(".cb-coach-t").textContent = text;
    }
    if (b.hidden) { b.hidden = false; if (!shownAt) { shownAt = Date.now(); log("show", id); } }
    if (COACH_MAX_MS[id] && shownAt && Date.now() - shownAt > COACH_MAX_MS[id]) { next("timeout"); return; }
    // beside the control: right of the Now card's button (the card sits at the top left); under the deck buttons
    const hr = host.getBoundingClientRect(), r = a.getBoundingClientRect(), w = b.offsetWidth, h = b.offsetHeight;
    let side = id === "now" ? "right" : "below", x, y;
    if (side === "right" && r.right + 14 + w > hr.right - 8) side = "below";
    if (side === "right") { x = r.right + 14; y = r.top + r.height / 2 - h / 2; }
    else { x = r.left + r.width / 2 - w / 2; y = r.bottom + 12; }
    x = Math.max(hr.left + 8, Math.min(x, hr.right - w - 8)); y = Math.max(hr.top + 8, Math.min(y, hr.bottom - h - 8));
    b.dataset.side = side;
    b.style.setProperty("--ax", `${Math.round(side === "below" ? r.left + r.width / 2 - x : 0)}px`);
    b.style.transform = `translate(${Math.round(x - hr.left)}px,${Math.round(y - hr.top)}px)`;
  }
  function next(why) {
    if (!active()) return;
    log(why || "done", cur());
    i++; shownAt = 0;
    if (el) { el.hidden = true; el.dataset.id = ""; }
    if (!active()) { markCoachDone(callsign()); stop(); }
  }
  function start() { if (coachDone(callsign())) return false; i = 0; shownAt = 0; bubble(); if (!raf) raf = requestAnimationFrame(place); return true; }
  /** The player did something: the prompt about it (if it is the one showing, or an earlier one) is done. */
  function did(id) { const k = COACH_STEPS.indexOf(id); if (!active() || k < 0 || k < i) return false; while (active() && COACH_STEPS.indexOf(cur()) <= k) next("did"); return true; }
  function stop() { cancelAnimationFrame(raf); raf = 0; if (i < COACH_STEPS.length) i = -1; if (el) { el.remove(); el = null; } }
  return { start, did, stop, get active() { return active(); }, get step() { return cur(); } };
}
