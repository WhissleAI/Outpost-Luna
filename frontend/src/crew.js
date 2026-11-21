// Crew rotation (D3, docs/BRAIN.md §9): a class mode for several cadets on one computer, with no voiceprints.
//
// Turned on in Settings → Cadets ("Crew rotation"). The cadets on this computer are named in a small crew bar under
// the top bar; the one whose turn it is is lit. A tap (or Enter / a controller's A on the focused name) passes the
// turn, with no reload, and CAPCOM says "Nova, your turn." From then on every turn, practice count, safety count and
// care flag lands on that cadet: the session gets her profile id (prefs.js turnProfileId → wire `profile`), and the
// practice counts go to her saved profile (brain.js recordFor).
//
// Push-to-talk per cadet: while crew rotation is on, listening is "Hold to talk" (the cadet on turn holds Space or the
// mic), so a voice turn belongs to the cadet on turn exactly. Open-mic counts can't be put on a cadet (a classmate may
// have spoken), and in crew rotation there are none. The listening choice from before comes back when it is turned off.
//
// The flight progress (patches, the half-done lesson) stays the playing cadet's: the crew flies one outpost together.
// State: localStorage "outpost-crew" (prefs.js CREW_KEY), per computer, never sent anywhere but as the profile id.
import { CREW_KEY, crewState } from "./prefs.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || {}) : {};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  label: "Crew rotation",
  help: "Cadets on this computer take turns. Tap a name to pass the turn. Hold Space or the mic to talk.",
  needTwo: "Add a second cadet to take turns.",
  bar: "Crew",
  turn: cs => `${cs}, your turn.`,
  hold: cs => `${cs}: hold Space to talk`,
  pass: cs => `Pass the turn to ${cs}`,
  newCadet: "New cadet",
};

const ls = () => { try { return typeof localStorage !== "undefined" ? localStorage : null; } catch (e) { return null; } };
const write = (st, v) => { try { if (!st) return; if (v == null) st.removeItem(CREW_KEY); else st.setItem(CREW_KEY, JSON.stringify(v)); } catch (e) { /* private mode */ } };

/** Turn crew rotation on or off. On: the playing cadet starts, listening becomes hold-to-talk (the old choice is kept
 *  to restore). prefsApi: prefs.js createPrefs() (its update() re-sends prefs to the session). */
export function setCrew(on, { storage = ls(), prefsApi = O.prefsApi } = {}) {
  const c = crewState(storage);
  if (on && c.ids.length < 2) return false;
  if (on) {
    const was = prefsApi && prefsApi.value ? prefsApi.value.listen : "handsfree";
    write(storage, { on: true, turn: c.turn || null, listen_was: c.on ? c.listen_was : was });
    if (prefsApi && prefsApi.value && prefsApi.value.listen !== "ptt") prefsApi.update({ listen: "ptt" });
  } else {
    write(storage, null);
    if (prefsApi && c.on && c.listen_was && prefsApi.value && prefsApi.value.listen !== c.listen_was) prefsApi.update({ listen: c.listen_was });
  }
  try { dispatchEvent(new CustomEvent("outpost:crew", { detail: crewState(storage) })); } catch (e) { /* node tests */ }
  return true;
}

/** Pass the turn to a cadet on this computer. Returns false for an unknown id or when crew rotation is off. */
export function passTurn(id, { storage = ls() } = {}) {
  const c = crewState(storage);
  if (!c.on || !c.ids.includes(id)) return false;
  write(storage, { on: true, turn: id, listen_was: c.listen_was });
  try { dispatchEvent(new CustomEvent("outpost:crew", { detail: crewState(storage) })); } catch (e) { /* node tests */ }
  return true;
}

/** The crew bar (pure). cadets: [{id, callsign}] in profile order; turn: the id on turn. Names only, never counts:
 *  nothing about how a cadet is doing is shown to the class. */
export function crewBarHtml(cadets, turn) {
  const cur = cadets.find(c => c.id === turn) || cadets[0];
  const name = c => c.callsign || COPY.newCadet;
  return `<span class="crew-lbl">${esc(COPY.bar)}</span><ul class="crew-list">${cadets.map(c => `<li><button type="button" class="crew-cadet${c.id === (cur && cur.id) ? " is-turn" : ""}" data-crew-turn="${esc(c.id)}"
      aria-pressed="${c.id === (cur && cur.id) ? "true" : "false"}" aria-label="${esc(COPY.pass(name(c)))}"><span class="set-av" aria-hidden="true">${esc(name(c).slice(0, 1).toUpperCase())}</span>${esc(name(c))}</button></li>`).join("")}</ul>
    ${cur ? `<span class="crew-ptt" role="status">${esc(COPY.hold(name(cur)))}</span>` : ""}`;
}

/** Wire the bar. say: CAPCOM speaks the turn line (main.js). */
export function installCrew({ prefsApi = O.prefsApi, say = () => {}, doc = typeof document !== "undefined" ? document : null, storage = ls() } = {}) {
  if (!doc) return null;
  const bar = doc.createElement("div");
  bar.className = "crew-bar"; bar.id = "crewBar"; bar.setAttribute("role", "toolbar"); bar.setAttribute("aria-label", COPY.bar); bar.hidden = true;
  doc.body.append(bar);
  const cadets = () => (prefsApi && prefsApi.listProfiles ? prefsApi.listProfiles() : []).map(p => ({ id: p.id, callsign: p.callsign }));
  function render() {
    const c = crewState(storage);
    bar.hidden = !c.on;
    doc.body.dataset.crewMode = c.on ? "on" : "off";
    if (c.on) bar.innerHTML = crewBarHtml(cadets(), c.turn);
  }
  bar.addEventListener("click", e => {
    const b = e.target.closest("[data-crew-turn]"); if (!b) return;
    const id = b.dataset.crewTurn, before = crewState(storage).turn;
    if (passTurn(id, { storage }) && id !== before) {
      const cs = (cadets().find(x => x.id === id) || {}).callsign || COPY.newCadet;
      try { say(COPY.turn(cs)); } catch (e2) { /* no voice */ }
    }
    render();
    const again = bar.querySelector(`[data-crew-turn="${id}"]`); if (again) again.focus();
  });
  addEventListener("outpost:crew", render);
  render();
  const api = { set: on => { const ok = setCrew(on, { storage, prefsApi }); render(); return ok; }, pass: id => { const ok = passTurn(id, { storage }); render(); return ok; },
    get state() { return crewState(storage); }, render };
  O.crew = api;
  return api;
}
