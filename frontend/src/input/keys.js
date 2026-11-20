// The keyboard as a TV remote (docs/KEYBOARD.md). Every key emits an intent on the one bus (input/intents.js), the same
// intents voice and gestures emit, so a screen never knows which device asked:
//
//   arrows → move {dir}          Enter / Space-tap → select      Esc / Backspace → back (never quits)
//   M → mic   H / ? → help        1–4, A–D → pick {n}             N / P → next / prev   Y / N → yes / no in a confirm
//   S → settings   B → My Brain   C → captions   V → window view   O → open the lit panel   / → the text box   Space held → talk
//
// The pure part (keyAction, helpRows, screenName) is unit-tested in tests/keys.test.js; installKeys() is the DOM glue:
// keyboard-vs-pointer mode, the Space tap/hold split, the help sheet, the key-hint chip, the optional focus sound and
// Settings → Keyboard & controller.
import { onIntent, emitIntent } from "./intents.js";
import { createSpatial, KEY_DIR, valueControl, isTextField, createRepeatGate, REPEAT_MS } from "./spatial.js";

// ---------------------------------------------------------------- pure ----------------------------------------------

/** Space shorter than this on a focused control is a tap (select); longer is hold-to-talk. */
export const SPACE_TAP_MS = 260;

/**
 * One keydown → what it means. ev: {key, shift, ctrl, meta, alt, repeat}; c: {typing, value (valueControl kind),
 * lettered (A–D answers on screen), confirm (a yes / no is waiting)}. Returns {intent, args} | {act} | null (not ours).
 */
export function keyAction(ev, c = {}) {
  if (!ev || ev.ctrl || ev.meta || ev.alt) return null;
  const k = ev.key;
  if (c.typing) return k === "Escape" ? { act: "leave_input" } : null;
  const dir = KEY_DIR[k];
  if (dir) {
    const horiz = dir === "left" || dir === "right";
    if (horiz && (c.value === "range" || c.value === "radio" || c.value === "slider")) return null;   // the control adjusts
    if (horiz && c.value === "select") return { act: "select_step", d: dir === "right" ? 1 : -1 };
    return { intent: "move", args: { dir, shift: !!ev.shift } };
  }
  if (ev.repeat && k !== "Backspace") return null;   // a held letter never fires twice
  if (k === "Enter") return { intent: "select", args: {} };
  if (k === "Escape" || k === "Backspace") return ev.repeat ? null : { intent: "back", args: {} };
  if (k === "?" || k === "/" && ev.shift) return { intent: "help", args: {} };
  if (k === "/") return { intent: "focus_input", args: {} };
  if (/^[1-9]$/.test(k)) return { intent: "pick", args: { n: +k } };
  if (k === "=" || k === "+") return { act: "zoom", f: 1.25 };
  if (k === "-" || k === "_") return { act: "zoom", f: 0.8 };
  const l = k.length === 1 ? k.toLowerCase() : "";
  if (c.lettered && "abcd".includes(l) && l) return { intent: "pick", args: { n: "abcd".indexOf(l) + 1 } };
  switch (l) {
    case "m": return ev.shift ? { intent: "mute", args: {} } : { intent: "mic", args: {} };   // Shift+M: the top bar's Mute
    case "h": return { intent: "help", args: {} };
    case "s": return { intent: "settings", args: {} };
    case "b": return { intent: "brain", args: {} };   // [brain] My Brain (brain.js)
    case "c": return { intent: "captions", args: {} };
    case "v": return { intent: "view_next", args: {} };
    case "o": return { intent: "panel_open", args: {} };
    case "y": return { intent: "yes", args: {} };
    case "n": return c.confirm ? { intent: "no", args: {} } : { intent: "next", args: {} };
    case "p": return { intent: "prev", args: {} };
    // the live mission clock and the Now card (docs/GAMEPLAY.md); no other screen uses these letters
    case "t": return { intent: "task_step", args: {} };
    case "k": return { intent: "time_toggle", args: {} };
    case "w": return { intent: "time_warp", args: {} };
    case "e": return { intent: "skip_event", args: {} };
    case "r": return { intent: "recenter", args: {} };   // cabin: Look ahead, the seat pose (C is captions)
    case "i": return { intent: "why", args: {} };        // cabin: the "Why?" card for the lit gauge (docs/PHYSICS.md)
    default: return null;
  }
}

/** The screen the kid is on, for the help sheet and the parity table. */
export function screenName(s) {
  if (!s) return "app";
  if (s.settings) return "settings";
  if (s.tour) return "tour";
  if (s.cabin) return s.panel && s.panel !== "seat" ? "cabin_panel" : "cabin_seat";
  if (s.mode === "cadet") return "library";
  if (s.mode === "mission") return s.mission === "debrief" ? "debrief" : "picker";
  if (s.aview === "home") return "home";
  if (s.aview === "lesson" || s.aview === "ride") return s.ride ? "ride" : s.moon ? "lesson_moon" : "lesson";
  if (s.aview === "badge") return "patch";
  return "map";
}
const SCREEN_TITLE = { home: "Home", map: "Moon map", lesson: "Lesson", lesson_moon: "Lesson on the Moon", patch: "Patch earned", ride: "Check ride",
  picker: "Site picker", tour: "Cabin tour", cabin_seat: "Cabin, seat view", cabin_panel: "Cabin, panel open", debrief: "Debrief", library: "Library", settings: "Settings", app: "Outpost Luna" };
const GLOBAL_ROWS = [["← ↑ → ↓", "Move"], ["Enter", "Select"], ["Space", "Tap: select. Hold: talk"], ["Esc", "Back"], ["M", "Mic on or off"], ["Shift+M", "Sound on or off"],
  ["/", "Type instead"], ["S", "Settings"], ["B", "My Brain"], ["C", "Captions"], ["H", "These keys"]];
const SCREEN_ROWS = {
  home: [["1–3", "Pick a call sign"], ["/", "Type your own"]],
  map: [["← → ↑ ↓", "Move between lesson pins"], ["Enter", "Pick a pin, then start it"], ["N", "Start the next lesson"], ["Y", "Take the offer"]],
  lesson: [["1–4 or A–D", "Pick an answer"], ["N", "Next, after a right answer"], ["Esc", "Back to the map"]],
  lesson_moon: [["← → ↑ ↓", "On the Moon: hop to a place"], ["Shift with ← → ↑ ↓", "Turn the Moon"], ["+ or −", "Zoom"], ["Enter", "Pick the place under the ring"], ["N", "Next, after a right answer"]],
  patch: [["N or Y", "Next lesson"], ["Enter", "Select"]],
  ride: [["1–5", "Pick an order"], ["N", "Next step"]],
  picker: [["↑ ↓", "Pick a site"], ["N or P", "Next or previous site"], ["Y", "Take command"]],
  tour: [["Enter or N", "Next"], ["Esc", "Skip tour"], ["← →", "Next or Skip tour button"]],
  cabin_seat: [["R", "Look ahead"], ["T or Y", "Do the Now job"], ["1–4", "Pick a choice on the Now card"], ["K", "Pause or run the clock"], ["Esc", "Pause menu: speed, restart or end the shift, settings"], ["Hold F", "Fast-forward"], ["W", "Time speed 1x, 2x, 4x"], ["E", "Skip to next event"], ["I", "Why? Explain a gauge"],
    ["← → ↑ ↓", "Light a panel (it starts on the one Now points at)"], ["Enter or O", "Open it"], ["V or N or P", "Window view"], ["Y or N", "Yes or no to CAPCOM"]],
  cabin_panel: [["← → ↑ ↓", "Move between controls"], ["← →", "Turn a knob"], ["N or P", "Next or previous panel"], ["Esc", "Back to the seat"], ["T", "Do the Now job"], ["K", "Pause or run the clock"], ["E", "Skip to next event"], ["I", "Why? Explain this panel's gauge"]],
  debrief: [["Y", "Fly again"], ["Enter", "Select"]],
  library: [["← → ↑ ↓", "On the Moon: hop to a place"], ["Shift with ← → ↑ ↓", "Turn the Moon"], ["N or P", "Next or previous tour stop"]],
  settings: [["↑ ↓", "Move"], ["← →", "Change a slider or choice"], ["Esc", "Close"]],
  app: [],
};
const PAD_ROWS = [["D-pad or Left-stick", "Move"], ["A or Cross", "Select"], ["B or Circle", "Back"], ["X or Square", "Mic"], ["Y or Triangle", "These keys"],
  ["LB or RB", "Previous or next"], ["Right-stick", "Turn the Moon, look around the cabin"], ["Start", "Settings (cabin: the pause menu)"],
  ["View or Share", "Cabin: pause or run the clock"], ["RT or R2", "Cabin: tap to skip ahead, hold to fast-forward"], ["LT or L2", "Cabin: time speed"]];
/** The help sheet's rows: [{title, rows}] for this screen, everywhere, and (when one is connected) the controller. */
export function helpRows(screen, { pad = false } = {}) {
  const out = [];
  if ((SCREEN_ROWS[screen] || []).length) out.push({ title: SCREEN_TITLE[screen] || "This screen", rows: SCREEN_ROWS[screen] });
  out.push({ title: "Everywhere", rows: GLOBAL_ROWS });
  if (pad) out.push({ title: "Controller", rows: PAD_ROWS });
  return out;
}

// ---------------------------------------------------------------- settings ------------------------------------------

export const KEY_DEFAULTS = Object.freeze({ sound: false, repeat: "normal", lefty: false });
const STORE = "outpost-keys";
export function loadKeySettings(storage = globalThis.localStorage) {
  let x = {}; try { x = JSON.parse((storage && storage.getItem(STORE)) || "{}") || {}; } catch (e) { x = {}; }
  return { sound: typeof x.sound === "boolean" ? x.sound : KEY_DEFAULTS.sound, repeat: REPEAT_MS[x.repeat] ? x.repeat : KEY_DEFAULTS.repeat, lefty: typeof x.lefty === "boolean" ? x.lefty : KEY_DEFAULTS.lefty };
}
function saveKeySettings(s) { try { localStorage.setItem(STORE, JSON.stringify(s)); } catch (e) { /* private mode */ } }

// ---------------------------------------------------------------- DOM -----------------------------------------------

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const vis = el => !!(el && !el.hidden && !el.closest("[hidden]") && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden");

/**
 * deps: { globe, places, mission (missionUI), inCabin(), cabinPanel(), a11y }
 * Returns the API on window.__outpost.keys: { spatial, settings, help(on?), toast(text), screen(), padConnected(on) }.
 */
export function installKeys({ globe = null, places = [], mission = null, inCabin = () => false, cabinPanel = () => null, a11y = null } = {}) {
  const doc = document, html = doc.documentElement, O = (window.__outpost = window.__outpost || {});
  let S = loadKeySettings();
  const say = (t) => { const A = O.a11y || a11y; if (A && A.describe) A.describe(t, { quiet: true }); };
  const spatial = createSpatial({ globe, places, mission, inCabin, cabinPanel, onMove: () => tick(), describe: say });
  const gate = createRepeatGate();

  // ---- keyboard vs pointer: focus rings, hint chips and auto-focus only while the kid drives with keys (or a pad) ----
  const setMode = m => { if (html.dataset.input !== m) { html.dataset.input = m; paintHint(); } };
  addEventListener("keydown", e => { if (!["Shift", "Control", "Alt", "Meta"].includes(e.key)) setMode("keys"); }, true);
  addEventListener("pointerdown", e => { if (e.isTrusted && e.pointerId !== 77) setMode("pointer"); }, true);
  addEventListener("mousemove", e => { if (Math.abs(e.movementX) + Math.abs(e.movementY) > 3) setMode("pointer"); }, true);
  addEventListener("wheel", () => setMode("pointer"), { capture: true, passive: true });

  // ---- the focus sound (off by default): a soft 25 ms tick ----
  let ac = null;
  function tick() {
    if (!S.sound) return;
    try {
      ac = ac || new (window.AudioContext || window.webkitAudioContext)();
      const o = ac.createOscillator(), g = ac.createGain(), t = ac.currentTime;
      o.frequency.value = 880; g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.05, t + 0.005); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
      o.connect(g).connect(ac.destination); o.start(t); o.stop(t + 0.04);
    } catch (e) { /* no audio */ }
  }

  // ---- what is on screen (help sheet, pick, Y / N) ----
  const ap = () => doc.getElementById("aPanel");
  function screenState() {
    const b = doc.body.dataset, a = ap();
    return { mode: b.mode, aview: b.aview, ride: b.ride === "1", cabin: inCabin(), panel: cabinPanel(), settings: vis(doc.querySelector(".a11y-panel")), tour: vis(doc.querySelector(".m-tour")),
      mission: mission && mission.screen ? (mission.screen() || {}).screen : null, moon: spatial.moonActive() && !!(a && a.dataset.step) };
  }
  const screen = () => screenName(screenState());
  const lettered = () => [...doc.querySelectorAll("#aPanel .a-choice:not([disabled]) .a-key")].some(k => vis(k) && /^[A-D]$/.test(k.textContent.trim()));
  const wipeBtn = k => { const b = doc.querySelector(`.mx-wipe [data-w="${k}"]`); return vis(b) ? b : null; };   // QA-26: "start over?" on a paused debrief
  const confirmWaiting = () => !!(mission && mission.pending) || !!wipeBtn("no") || [...doc.querySelectorAll('[data-intent="no"], #card .card-actions button, .cb-offer-b')].some(b => vis(b) && /^no$/i.test(b.textContent.trim()));
  const PICK_LISTS = ["#aPanel .a-choice", "#aPanel .v-opt", "#aPanel .a-order", ".a-csb", ".mx-site", ".cb-offer-b", ".cb-now-btns .cb-now-b", "#card .card-actions button"];
  function pickList() { for (const s of PICK_LISTS) { const l = [...doc.querySelectorAll(s)].filter(b => vis(b) && !b.disabled); if (l.length) return l; } return []; }

  // ---- the help sheet ----
  const help = doc.createElement("div");
  help.id = "keysHelp"; help.className = "keys-help"; help.hidden = true;
  help.setAttribute("role", "dialog"); help.setAttribute("aria-modal", "true"); help.setAttribute("aria-labelledby", "keysHelpTitle");
  doc.body.append(help);
  let helpReturn = null, padOn = false;
  function showHelp(on = help.hidden) {
    if (!on) { help.hidden = true; if (helpReturn && helpReturn.isConnected) helpReturn.focus({ preventScroll: true }); return; }
    helpReturn = doc.activeElement;
    const groups = helpRows(screen(), { pad: padOn });
    help.innerHTML = `<div class="kh-card"><header><h2 id="keysHelpTitle">Keys</h2><button type="button" class="x" data-close aria-label="Close keys">&times;</button></header>
      <div class="kh-cols">${groups.map(g => `<section><h3>${esc(g.title)}</h3><dl>${g.rows.map(([k, v]) => `<div><dt>${k.split(" ").map(x => /^(or|with|and)$/.test(x) ? esc(x) : `<kbd>${esc(x)}</kbd>`).join(" ")}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl></section>`).join("")}</div>
      <p class="kh-foot">Voice and gestures do the same things. Settings → Keyboard &amp; controller.</p></div>`;
    help.querySelector("[data-close]").onclick = () => showHelp(false);
    help.hidden = false; help.querySelector("[data-close]").focus({ preventScroll: true });
  }
  help.addEventListener("click", e => { if (e.target === help) showHelp(false); });

  // ---- toast ----
  const toastEl = doc.createElement("div"); toastEl.className = "keys-toast"; toastEl.hidden = true; toastEl.setAttribute("role", "status"); doc.body.append(toastEl);
  let toastT = 0;
  function toast(text) { toastEl.textContent = text; toastEl.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => { toastEl.hidden = true; }, 2200); say(text); }

  // ---- key-hint chip next to the focused control + a corner legend ----
  const hint = doc.createElement("span"); hint.className = "key-hint"; hint.setAttribute("aria-hidden", "true"); hint.hidden = true;
  const legend = doc.createElement("div"); legend.className = "key-legend"; legend.setAttribute("aria-hidden", "true");
  legend.innerHTML = `<span><kbd>Esc</kbd> Back</span><span><kbd>/</kbd> Type</span><span><kbd>H</kbd> Help</span>`;
  doc.body.append(hint, legend);
  function hintText(el) {
    if (!el || el === doc.body) return "";
    if (el === spatial.moonEl) return "Enter · pick   Shift ← → turn";
    if (el === spatial.seatEl) return "Enter · open";
    const v = valueControl(el); if (v) return v === "select" ? "← → change" : "← → adjust";
    if (isTextField(el)) return "Esc · leave";
    if (el.matches("button, a[href], summary, [role=button], [role=radio], input")) return "Enter";
    return "";
  }
  function paintHint() {
    const on = html.dataset.input === "keys" || html.dataset.input === "pad", a = doc.activeElement, t = on ? hintText(a) : "";
    if (!t || !vis(a) && a !== spatial.seatEl) { hint.hidden = true; return; }
    const r = a.getBoundingClientRect();
    hint.textContent = html.dataset.input === "pad" ? t.replace("Enter", "A").replace("Esc", "B") : t;
    hint.hidden = false;
    const w = hint.offsetWidth || 40, h = hint.offsetHeight || 18;
    let x = Math.max(4, Math.min(innerWidth - w - 4, r.right - w + 6)), y = r.bottom + h + 8 < innerHeight ? r.bottom + 6 : Math.max(4, r.top - h - 6);
    // [0.4.1] a control in a card's header (the patches card's close): the chip sits beside it, never over the subtitle
    if (a.closest && a.closest("[role=dialog] header") && r.left - w - 6 >= 4) { x = r.left - w - 6; y = r.top + (r.height - h) / 2; }
    hint.style.transform = `translate(${x.toFixed(0)}px,${y.toFixed(0)}px)`;
  }
  doc.addEventListener("focusin", () => requestAnimationFrame(paintHint));
  setInterval(() => { if (html.dataset.input === "keys" || html.dataset.input === "pad") paintHint(); }, 250);

  // ---- the keydown source ----
  let zoomKey = null;        // the +/- key being held (zoom_rate until its keyup)
  let beforeInput = null;   // where focus was before "/" (Esc in the text box goes back there)
  addEventListener("keydown", e => {
    if (e.defaultPrevented || e.isComposing) return;
    const t = e.target, typing = isTextField(t) || (t && t.closest && !!t.closest("[contenteditable=true]"));
    if (e.key === " " || e.code === "Space") return;   // Space: the capture handler below (tap = select, hold = talk)
    const a = keyAction({ key: e.key, shift: e.shiftKey, ctrl: e.ctrlKey, meta: e.metaKey, alt: e.altKey, repeat: e.repeat },
      { typing, value: valueControl(t), lettered: lettered(), confirm: confirmWaiting() });
    if (!a) return;
    if (a.act === "leave_input") {
      e.preventDefault();
      const back = beforeInput && beforeInput.isConnected && beforeInput !== t ? beforeInput : null;
      t.blur(); beforeInput = null;
      if (back) back.focus({ preventScroll: true }); else spatial.restore();
      return;
    }
    if (a.act === "select_step") { e.preventDefault(); const n = t.selectedIndex + a.d; if (n >= 0 && n < t.options.length) { t.selectedIndex = n; t.dispatchEvent(new Event("change", { bubbles: true })); } return; }
    // +/- zoom at the same rate as the pinch and slide while held (zoom_rate, input/defaults.js); a quick tap still
    // zooms a tap step. On the Moon (any screen showing it); the cabin ignores it.
    if (a.act === "zoom") { e.preventDefault(); zoomKey = e.key; emitIntent("zoom_rate", { phase: "start", rate: a.f > 1 ? 1 : -1, tap: true }, "keyboard"); return; }
    if (a.intent === "move" && !gate.ok(e.repeat, REPEAT_MS[S.repeat])) { e.preventDefault(); return; }
    // Enter on a text field submits (native); Enter on a native <select> / summary keeps its own behaviour
    if (a.intent === "select" && t && t.tagName === "SELECT") return;
    e.preventDefault();
    emitIntent(a.intent, a.args, "keyboard");
  });
  addEventListener("keyup", e => {
    if (KEY_DIR[e.key]) gate.reset();
    if (zoomKey && (e.key === zoomKey || "=+-_".includes(e.key))) { zoomKey = null; emitIntent("zoom_rate", { phase: "end", rate: 0 }, "keyboard"); }
  });
  addEventListener("blur", () => { if (zoomKey) { zoomKey = null; emitIntent("zoom_rate", { phase: "end", rate: 0 }, "keyboard"); } });

  // ---- Space: a tap on a focused control selects it; held, it is hold-to-talk (voice.js, unchanged) ----
  // Runs in the capture phase, before voice.js. A tap swallows the key; a hold re-sends it to voice.js from the body.
  const sp = { t: 0, el: null, held: false, talking: false };
  const spaceTarget = el => el && el !== doc.body && el.matches && el.matches("button, summary, [role=button], [role=radio], [role=slider], input[type=checkbox], input[type=radio], a[href], .moon-focus, .seat-focus");
  addEventListener("keydown", e => {
    if (e.code !== "Space" || e.ctrlKey || e.metaKey || e.altKey || e.__keysSynthetic) return;
    if (sp.held) { if (!sp.talking) { e.preventDefault(); e.stopImmediatePropagation(); } return; }   // auto-repeat
    if (!spaceTarget(e.target)) return;   // nothing selectable focused: Space is talk, as before
    e.preventDefault(); e.stopImmediatePropagation();
    sp.held = true; sp.talking = false; sp.el = e.target;
    sp.t = setTimeout(() => {   // still down: talk
      sp.talking = true;
      const ev = new KeyboardEvent("keydown", { key: " ", code: "Space", bubbles: true, cancelable: true });
      ev.__keysSynthetic = true; doc.body.dispatchEvent(ev);
    }, SPACE_TAP_MS);
  }, true);
  addEventListener("keyup", e => {
    if (e.code !== "Space" || !sp.held) return;
    sp.held = false; clearTimeout(sp.t);
    if (sp.talking) return;   // voice.js's own keyup ends the turn
    e.preventDefault(); e.stopImmediatePropagation();
    if (sp.el && sp.el.isConnected && doc.activeElement === sp.el) emitIntent("select", {}, "keyboard");
  }, true);
  addEventListener("blur", () => { if (sp.held && !sp.talking) { sp.held = false; clearTimeout(sp.t); } });

  // ---- intents the keys (and the gamepad) bring; voice and gestures reach the same handlers ----
  onIntent("move", a => spatial.move(a.dir, { shift: a.shift }) || true, { priority: 0 });
  onIntent("select", a => (a && a.x != null ? false : spatial.activate()), { priority: 5 });
  onIntent("help", (a, ev) => { if (ev.source !== "keyboard" && ev.source !== "gamepad" && help.hidden) return false; showHelp(); return true; }, { priority: 10 });
  onIntent("focus_input", () => {
    const cs = doc.getElementById("aCsIn"), q = doc.getElementById("q"), f = vis(cs) ? cs : q;
    if (!f) return false; beforeInput = doc.activeElement !== f ? doc.activeElement : beforeInput; f.focus(); if (f.select && f === cs) f.select(); return true;
  }, { priority: 0 });
  onIntent("mic", () => { const m = doc.getElementById("mic"); if (!m || m.hidden) return false; m.click(); return true; }, { priority: 0 });
  onIntent("captions", () => {
    const A = O.a11y || a11y; if (!A || !A.set) return false;
    const on = !A.settings.captions; A.set({ captions: on }); toast(on ? "Captions on" : "Captions off"); return true;
  }, { priority: 0 });
  onIntent("pick", a => { const l = pickList(), b = l[(a.n | 0) - 1]; if (!b) return false; b.focus({ preventScroll: true }); b.click(); return true; }, { priority: 0 });
  // yes / no answer an on-screen confirm that has its own buttons (the debrief's "start over?"), from any device
  onIntent("yes", () => { const b = wipeBtn("yes"); if (!b) return false; b.click(); return true; }, { priority: 15 });
  onIntent("no", () => { const b = wipeBtn("no"); if (!b) return false; b.click(); return true; }, { priority: 15 });
  const cabin = (n, arg) => !!(inCabin() && mission && mission.intent && mission.intent(n, arg));
  onIntent("view_next", () => cabin("view_next"), { priority: 0 });
  onIntent("view_prev", () => cabin("view_prev"), { priority: 0 });
  // O / the gamepad: open the lit panel (the seat focus, a head aim, or the default)
  onIntent("panel_open", a => {
    if (!inCabin() || (a && a.panel)) return false;
    const id = spatial.seatPanel || (mission && mission.highlighted); if (!id) return false;
    return cabin("panel_open", id);
  }, { priority: 5 });
  // back: the top layer first (a sheet, a dialog, a card), then an open cabin panel; else the screen's own back
  // (screens at 10, then shellNav). Never quits the app.
  onIntent("back", () => {
    if (!help.hidden) { showHelp(false); return true; }
    const skip = doc.querySelector(".m-tour:not([hidden]) [data-t=skip]"); if (vis(skip)) { skip.click(); return true; }   // the cabin tour: back = Skip tour
    const A = O.a11y || a11y, set = doc.querySelector(".a11y-panel");
    if (set && !set.hidden && A && A.open) { A.open(false); return true; }
    const dlg = [...doc.querySelectorAll("dialog[open]")].pop(); if (dlg) { dlg.close(); return true; }
    const cal = doc.querySelector(".gx-calib [data-close]"); if (vis(cal)) { cal.click(); return true; }
    const gl = doc.querySelector(".hl-card:not([hidden]) [data-x]"); if (vis(gl)) { gl.click(); return true; }
    const brief = doc.getElementById("aBrief"); if (brief && !brief.hidden && vis(doc.getElementById("aBriefBtn"))) { doc.getElementById("aBriefBtn").click(); return true; }
    // the answer card; in the cabin it is CAPCOM's status line, closed by back only when focus is on it
    const card = doc.getElementById("card"); if (card && !card.hidden && (!inCabin() || card.contains(doc.activeElement))) { doc.getElementById("cardClose").click(); return true; }
    const mc = doc.getElementById("missionCard"); if (mc && !mc.hidden) { doc.getElementById("mClose").click(); return true; }
    if (inCabin() && (cabinPanel() || "seat") !== "seat") return cabin("panel_back");
    return false;
  }, { priority: 20 });

  // ---- Settings → Keyboard & controller (the Settings sheet's extension point) ----
  const section = {
    id: "keys", title: "Keyboard & controller", after: "display",
    html: () => `<p class="set-help">Arrows move, <kbd>Enter</kbd> selects, <kbd>Esc</kbd> goes back, <kbd>H</kbd> shows every key.</p>
      <button type="button" class="btn" data-keys-help>Show all keys</button>
      <label class="a11y-sw"><input type="checkbox" data-keys="sound" ${S.sound ? "checked" : ""}><span><b>Focus sound</b><small>A soft tick when focus moves</small></span></label>
      <fieldset class="set-seg"><legend>Key repeat</legend><div class="a11y-speed">${[["slow", "Slow"], ["normal", "Normal"], ["fast", "Fast"]].map(([v, t]) =>
        `<label><input type="radio" name="keys-repeat" data-keys="repeat" value="${v}" ${S.repeat === v ? "checked" : ""}><span>${t}</span></label>`).join("")}</div></fieldset>
      <label class="a11y-sw"><input type="checkbox" data-keys="lefty" ${S.lefty ? "checked" : ""}><span><b>Left-handed controller</b><small>Swap the sticks: right stick moves, left stick looks</small></span></label>
      <p class="set-help" data-keys-pad>${padOn ? "Controller connected." : "No controller connected. Plug one in or pair it, then press a button."}</p>`,
    bind(el) {
      el.querySelector("[data-keys-help]").onclick = () => { if (A0().open) A0().open(false); showHelp(true); };
      el.addEventListener("change", e => {
        const k = e.target.dataset.keys; if (!k) return;
        S = { ...S, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }; saveKeySettings(S);
        if (k === "sound" && S.sound) tick();
        dispatchEvent(new CustomEvent("outpost:keys", { detail: S }));
      });
    },
  };
  const A0 = () => O.a11y || a11y || {};
  (O.settingsSections = O.settingsSections || []).push(section);

  const api = {
    spatial, help: showHelp, toast, screen, screenState,
    get settings() { return S; },
    padConnected(on) { padOn = !!on; },
  };
  O.keys = api;
  return api;
}
