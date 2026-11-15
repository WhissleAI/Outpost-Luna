// First-mission cabin tour: CAPCOM shows the cabin one beat at a time (story.js TOUR). The camera and the glow do the
// showing; each beat is one line (12 words or fewer), spoken and on a small card with Next and Skip tour.
//
// Moves on with: the Next button, Enter, voice "next" / "yes" (the router's next / accept_offer, offer "tour"),
// a swipe (next) or a thumbs up (yes). "skip tour" (router skip_tour) or the Skip button ends it. "show me around"
// (router cabin_tour) or Settings -> Help replays it. Done is stored per cadet (localStorage, try/catch).
import { TOUR } from "../story.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Where the camera looks for a beat (cockpit.look dx, dy), so the panel being named is in the middle of the view. */
const LOOK = { "panel:habitat": [-0.32, 0.02], "panel:rover": [-0.36, 0.2], "panel:radiation": [0.32, 0.02], "panel:comm": [0.36, 0.2],
  "du:0": [-0.12, 0.1], "du:2": [0.12, 0.1], lamps: [0, 0.26], start: [0, 0.18], goals: [-0.32, 0.02], "panel:power": [-0.12, 0.1] };
/** The panel a beat is about (Cadet keeps the others dim). */
const PANEL = { "du:0": "displays", "du:1": "displays", "du:2": "displays", "panel:power": "displays", "panel:habitat": "habitat",
  "panel:rover": "rover", "panel:radiation": "radiation", "panel:comm": "comm", lamps: "pedestal", goals: "habitat", start: ["displays", "pedestal"] };

const KEY = cs => "outpost-tour-done:" + (cs || "cadet");
export const tourDone = cs => { try { return localStorage.getItem(KEY(cs)) === "1"; } catch (e) { return false; } };
export const markTourDone = cs => { try { localStorage.setItem(KEY(cs), "1"); } catch (e) { /* private mode */ } };
/** The beats for a level: Cadet the full tour, Commander the short one. */
export const tourBeats = level => (level === "commander" ? TOUR.commander : TOUR.cadet);

/**
 * @param {object} o
 * @param {HTMLElement} o.host        where the card goes (the stage)
 * @param {() => object} o.cockpit    the live cabin (cabin.js): point, focus, look, seat
 * @param {(t:string)=>Promise} o.say speak as CAPCOM
 * @param {() => string} o.callsign   the stored call sign (the key the tour is remembered under)
 * @param {(done:boolean)=>void} o.onEnd  after the last beat (true) or a skip (false)
 */
export function createTour({ host, cockpit, say, hush = () => {}, callsign = () => "", onEnd = () => {} }) {
  let beats = [], i = -1, el = null, keyOff = null;
  const active = () => i >= 0;
  function card() {
    if (el && el.isConnected) return el;
    el = document.createElement("section"); el.className = "m-tour"; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", TOUR.title);
    host.append(el); return el;
  }
  function show(lead) {
    const b = beats[i], ck = cockpit(), last = i === beats.length - 1;
    const c = card(); c.hidden = false;
    c.className = "m-tour is-docked";
    dock(c);
    c.innerHTML = `<p class="t-eye">${esc(TOUR.title)} · ${esc(TOUR.step(i + 1, beats.length))}</p>
      <p class="t-text" aria-live="polite">${esc(b.text)}</p>
      <div class="t-row"><span class="t-dots" aria-hidden="true">${beats.map((_, k) => `<i class="${k === i ? "is-on" : ""}"></i>`).join("")}</span>
        <span class="t-acts"><button type="button" class="t-skip" data-t="skip">${esc(TOUR.skip)}</button>
        <button type="button" class="t-next" data-t="next">${esc(last ? TOUR.done : TOUR.next)}</button></span></div>`;
    c.querySelector('[data-t="next"]').onclick = () => next();
    c.querySelector('[data-t="skip"]').onclick = () => end(false);
    if (ck) {
      if (ck.seat && ck.panel) ck.seat();
      if (ck.point) ck.point(b.show === "start" ? "start" : b.show);
      if (ck.focus) ck.focus(b.show === "window" ? null : PANEL[b.show] || null);
      const lk = LOOK[b.show] || [0, 0]; if (ck.look) ck.look(lk[0], lk[1], { hold: true });   // held until the next beat
    }
    requestAnimationFrame(() => { const n = c.querySelector(".t-next"); if (n) n.focus({ preventScroll: true }); });
    // a list goes through the floor's line queue as one on-air span (the hello + the first beat)
    Promise.resolve(say(lead ? [lead, b.text] : b.text)).catch(() => {});
  }
  /** Dock the card in the window, just under the HUD (clock, site name, sky readout), so it never covers them. The
   *  camera turns a little for each beat, so it is re-docked as the camera settles. */
  let dockRaf = 0;
  function dock(c) {
    cancelAnimationFrame(dockRaf);
    // follows the HUD every frame while the card shows (the camera turns and eases for each beat; the HUD moves with it)
    const place = () => {
      if (!c.isConnected || c.hidden || !active()) return;
      dockRaf = requestAnimationFrame(place);
      const hb = host.getBoundingClientRect();
      const hud = [...document.querySelectorAll(".cb-deck, .cb-hole .cb-sky, .cb-glass > .cb-sky")]
        .filter(n => n.getClientRects().length).map(n => n.getBoundingClientRect());
      const below = hud.length ? Math.max(...hud.map(r => r.bottom)) - hb.top + 10 : 16;
      const top = Math.round(Math.max(8, Math.min(below, hb.height - c.offsetHeight - 96)));
      if (Math.abs((parseFloat(c.style.top) || 0) - top) > 1) c.style.top = top + "px";
    };
    place();
  }
  function start(level, { lead = null } = {}) {
    beats = tourBeats(level); i = 0;
    if (!keyOff) { const k = e => { if (!active() || e.key !== "Enter" || e.altKey || e.ctrlKey || e.metaKey) return;
        const t = e.target; if (t && t.closest && t.closest("input, textarea, select, [contenteditable=true]")) return;
        if (t && t.closest && t.closest("button") && !t.closest(".m-tour")) return;   // Enter on another control presses it
        e.preventDefault(); next(); };
      addEventListener("keydown", k, true); keyOff = () => removeEventListener("keydown", k, true); }
    show(lead);
  }
  function next() { if (!active()) return false; hush(); if (i + 1 >= beats.length) { end(true); return true; } i++; show(); return true; }
  function end(done) {
    if (!active()) return false;
    if (!done) hush();   // skipped: the beat stops now (the last beat has already been heard through)
    i = -1; if (el) { el.hidden = true; el.innerHTML = ""; }
    if (keyOff) { keyOff(); keyOff = null; }
    const ck = cockpit(); if (ck) { if (ck.look) ck.look(0, 0); if (ck.point) ck.point(null); if (ck.focus) ck.focus(null); }
    markTourDone(callsign());
    onEnd(!!done); return true;
  }
  return { start, next, end, get active() { return active(); }, get beat() { return active() ? beats[i] : null; }, get index() { return i; }, get count() { return beats.length; } };
}
