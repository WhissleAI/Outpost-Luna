// Camera gestures: everything the kid sees. The camera indicator (always visible while on, one-click off), the
// movable self-view with the hand skeleton, the dwell cursor, the contextual hint chip, gesture feedback, the fist
// stick indicator and the Moon's heading arrow, the per-screen coach mark and "Gestures" help card, the
// "Camera & gestures" settings section, the calibration (hand, fist, head) and the cheat-sheet. docs/GESTURES.md.
//
// Off by default. Turning it on is an explicit choice in Settings (or "turn on the camera", which opens Settings).
// Frames never leave the device and are never stored; settings live in localStorage on this device only.
import "./gestures.css";
import { emitIntent, recentIntents } from "../input/intents.js";
import { spinState, configureSpin } from "../input/defaults.js";
import { tick } from "../sound.js";
import { createGestureEngine } from "./engine.js";
import { gestureIntents, FEEDBACK } from "./bind.js";
import { CHEATSHEET, CHEATSHEET_PHASE2, hintFor, spokenSummary } from "./guide.js";
import { screenKey, helpRows, coachRows } from "./map.js";
import { createFistCalibration, loadSpinCal, saveSpinCal } from "./calibration.js";
import { CALIBRATION } from "./tuning.js";
import { fistReading } from "./spin.js";
import { icon } from "./icons.js";
import { handPose } from "./classifier.js";

const KEY = "outpost-gestures";
// coached: the screens whose first-use coach mark was shown; spinOffered: the first-time fist calibration was offered
export const SETTINGS_DEFAULTS = Object.freeze({ enabled: false, deviceId: "", preview: true, sensitivity: 1, headLook: true, handed: "right", phase2: false, previewPos: null, minHandScale: null,
  invertSpin: false, coached: {}, spinOffered: false });
export function loadSettings(storage = globalThis.localStorage) {
  try { return { ...SETTINGS_DEFAULTS, ...(JSON.parse(storage.getItem(KEY) || "null") || {}) }; } catch (e) { return { ...SETTINGS_DEFAULTS }; }
}
function saveSettings(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* private mode: this visit only */ } }

// hand skeleton edges (MediaPipe hand topology)
const EDGES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17]];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/**
 * ctx: { screen() → the router's screen frame, inCabin(), cabinPanel(), isSpeaking(), announce(text) }
 */
export function initGestures(ctx = {}) {
  const S = loadSettings();
  const set = patch => { Object.assign(S, patch); saveSettings(S); };
  const root = document.createElement("div"); root.className = "gx-ui";
  root.innerHTML = `
    <div class="gx-indicator" id="gxIndicator" role="status" hidden>
      <span class="gx-dot" aria-hidden="true"></span>${icon("camera")}<span class="gx-ind-text">Camera on</span>
      <button type="button" class="gx-off gx-help-btn" id="gxHelpBtn" aria-haspopup="dialog">Gestures</button>
      <button type="button" class="gx-off" id="gxOff">Turn off</button>
    </div>
    <div class="gx-preview" id="gxPreview" hidden aria-label="Camera self-view. Only on this computer.">
      <div class="gx-preview-bar" id="gxGrip" tabindex="0" role="button" aria-label="Move the self-view (arrow keys)">${icon("hand", { size: 14 })}<span>You</span>
        <button type="button" class="gx-x" id="gxHidePreview" aria-label="Hide the self-view">${icon("close", { size: 14 })}</button></div>
      <div class="gx-view"><canvas class="gx-skel" id="gxSkel" width="240" height="180" aria-hidden="true"></canvas></div>
    </div>
    <div class="gx-hint" id="gxHint" hidden aria-hidden="true"></div>
    <div class="gx-stick" id="gxStick" hidden aria-hidden="true"><svg viewBox="-40 -40 80 80"><circle class="gx-stick-ring" r="34"/><circle class="gx-stick-dead" r="6"/>
      <path class="gx-stick-arrow" d="M0 -14 L0 -14"/><circle class="gx-stick-knob" r="11"/></svg><span class="gx-stick-text"></span></div>
    <div class="gx-heading" id="gxHeading" hidden aria-hidden="true"><svg viewBox="-60 -60 120 120"><g class="gx-chev"><path d="M18 -16 L34 0 L18 16"/><path d="M38 -16 L54 0 L38 16"/></g></svg></div>
    <div class="gx-toast" id="gxToast" hidden aria-hidden="true"></div>
    <div class="gx-live" role="status" aria-live="polite" id="gxLive"></div>`;
  const cursor = document.createElement("div"); cursor.className = "gx-cursor"; cursor.hidden = true; cursor.setAttribute("aria-hidden", "true");
  cursor.innerHTML = `<svg viewBox="0 0 48 48"><circle class="gx-ring-bg" cx="24" cy="24" r="20"/><circle class="gx-ring" cx="24" cy="24" r="20" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100"/><circle class="gx-tip" cx="24" cy="24" r="5"/></svg>`;
  // the help card / coach mark: outside .gx-ui, so point + dwell (and keys) can press its Close button
  const card = document.createElement("div"); card.className = "gx-card gx-ui-vars"; card.hidden = true;
  card.setAttribute("role", "dialog"); card.setAttribute("aria-labelledby", "gxCardTitle");
  document.body.append(root, cursor, card);
  const $ = id => root.querySelector("#" + id);
  const ind = $("gxIndicator"), prev = $("gxPreview"), skel = $("gxSkel"), hint = $("gxHint"), toast = $("gxToast"), live = $("gxLive");
  const stickEl = $("gxStick"), headingEl = $("gxHeading");
  let spinCal = loadSpinCal();
  configureSpin({ invert: !!S.invertSpin });
  const view = prev.querySelector(".gx-view");

  let status = { state: "off" }, calib = null, lastLm = null, hover = null;
  const engine = createGestureEngine({
    classifierOptions: classifierOpts(),
    onStatus: st => { status = st; paintStatus(); },
    onLandmarks: f => { lastLm = f; if (!prev.hidden) drawSkeleton(f); if (calib) calib.frame(f); },
    onEvents: evs => evs.forEach(handle),
  });
  engine.video.className = "gx-video"; view.prepend(engine.video);

  function classifierOpts() {
    return { sensitivity: S.sensitivity, handed: S.handed, headLook: S.headLook, phase2: S.phase2, spinCal, ...(S.minHandScale ? { minHandScale: S.minHandScale } : {}) };
  }

  // ---------- gesture events → intents ----------
  function context() {
    const p = ctx.cabinPanel ? ctx.cabinPanel() : null;
    return { cabin: !!(ctx.inCabin && ctx.inCabin()), panel: p, vw: innerWidth, vh: innerHeight, phase2: S.phase2 };
  }
  // a hand gesture drives like the keys / remote: the same focus ring (keys.css, html[data-input=gesture])
  const DRIVES = new Set(["palm_hold", "thumbs_up", "thumbs_down", "swipe_left", "swipe_right", "point", "select", "grab_start"]);
  function handle(ev) {
    if (calib) { calib.event(ev); return; }
    if (DRIVES.has(ev.type)) document.documentElement.dataset.input = "gesture";
    if (ev.type === "point") showCursor(ev);
    if (ev.type === "point_end") hideCursor();
    if (ev.type === "grab_start") { tick("grab"); paintSpinSoon(); }
    if (ev.type === "grab_end") tick("release");
    if (ev.type !== "point" && ev.type !== "point_end" && ev.type !== "head" && ev.type !== "grab_move" && !card.hidden && card.dataset.mode === "coach") hideCard();
    for (const [name, args] of gestureIntents(ev, context())) {
      emitIntent(name, args, "gesture").then(ok => {
        if (FEEDBACK[name] && ok) feedback(FEEDBACK[name], name);
        if (name === "prev" && !ok) feedback("Say go back", null);
      });
    }
  }

  // ---------- cursor + dwell ring (hover highlight on the control under it) ----------
  function showCursor(ev) {
    const x = ev.x * innerWidth, y = ev.y * innerHeight;
    cursor.hidden = false; cursor.style.transform = `translate(${x.toFixed(0)}px, ${y.toFixed(0)}px)`;
    cursor.querySelector(".gx-ring").setAttribute("stroke-dashoffset", String(100 - Math.round(ev.progress * 100)));
    const stack = document.elementsFromPoint(x, y).filter(e => !e.closest(".gx-ui, .gx-cursor"));
    const c = stack[0] && stack[0].closest("button, a[href], [role=button], input, select, label, summary, canvas");
    if (c !== hover) {
      if (hover) hover.classList.remove("gx-hover");
      hover = c;
      // a focusable control takes focus (the same ring keys and the remote show); anything else gets an outline
      const f = hover && hover.tagName !== "CANVAS" ? (hover.tagName === "LABEL" ? hover.querySelector("input, select, button") || hover : hover) : null;
      if (f && f.focus && f.tabIndex >= 0 && !f.disabled) f.focus({ preventScroll: true });
      else if (hover && hover.tagName !== "CANVAS") hover.classList.add("gx-hover");
    }
    cursor.classList.toggle("is-target", !!c);
  }
  function hideCursor() { cursor.hidden = true; if (hover) hover.classList.remove("gx-hover"); hover = null; }

  // ---------- feedback toast + hint chip ----------
  let toastT = 0;
  function feedback(text, name) {
    const ic = { stop: "hand", yes: "thumbs-up", no: "thumbs-down", next: "swipe", prev: "swipe", select: "pointer", panel_open: "head", panel_back: "head" }[name] || "hand";
    toast.innerHTML = icon(ic) + `<span>${esc(text)}</span>`; toast.hidden = false;
    live.textContent = ""; requestAnimationFrame(() => { live.textContent = `Gesture: ${text}`; });
    clearTimeout(toastT); toastT = setTimeout(() => { toast.hidden = true; }, 900);
  }
  let hintKey = "", hintT = 0;
  function paintHint() {
    if (!engine.running || calib) { hint.hidden = true; hintKey = ""; return; }
    const frame = (ctx.screen && ctx.screen()) || {};
    const confirm = [...document.querySelectorAll("#card button")].some(b => b.offsetParent && /^(yes|no)$/i.test(b.textContent.trim()));
    const h = hintFor(frame, { confirm, speaking: !!(ctx.isSpeaking && ctx.isSpeaking()), headLook: S.headLook });
    const k = h ? h.text : "";
    if (k === hintKey) return;
    hintKey = k; clearTimeout(hintT);
    if (!h) { hint.hidden = true; return; }
    hint.innerHTML = icon(h.icon) + `<span>${esc(h.text)}</span>`; hint.hidden = false;
    hintT = setTimeout(() => { hint.hidden = true; }, 6000);
  }
  setInterval(paintHint, 500);

  // ---------- the fist: stick indicator (grab, direction, speed) + the Moon's heading arrow ----------
  let spinRaf = 0;
  function paintSpinSoon() { if (!spinRaf) spinRaf = requestAnimationFrame(paintSpin); }
  function paintSpin() {
    spinRaf = 0;
    const st = spinState(), stick = st.stick, cab = !!(ctx.inCabin && ctx.inCabin());
    const on = st.grabbed || st.speed > 0;
    stickEl.hidden = !on || (!engine.running && st.source === "gesture");
    if (on) {
      const x = stick ? Math.max(-1, Math.min(1, stick.x)) : 0, y = stick ? Math.max(-1, Math.min(1, stick.y)) : 0, m = Math.min(1, Math.hypot(x, y));
      stickEl.classList.toggle("is-grabbed", st.grabbed);
      stickEl.querySelector(".gx-stick-knob").setAttribute("transform", `translate(${(x * 22).toFixed(1)} ${(y * 22).toFixed(1)})`);
      const L = 14 + m * 18, a = Math.atan2(y, x);
      stickEl.querySelector(".gx-stick-arrow").setAttribute("d", m > 0.05 ? `M0 0 L${(Math.cos(a) * L).toFixed(1)} ${(Math.sin(a) * L).toFixed(1)}` : "M0 0");
      stickEl.querySelector(".gx-stick-text").textContent = !st.grabbed ? "" : m < 0.15 ? (cab ? "Lean your fist to look" : "Lean your fist to spin") : "Open your hand to stop";
    }
    // the Moon shows where it is heading: chevrons at its centre, the way the surface turns, brighter when faster
    const stage = document.getElementById("stage");
    if (!cab && stage && st.speed > 0.03) {
      const r = stage.getBoundingClientRect(), sg = S.invertSpin ? -1 : 1;
      headingEl.hidden = false;
      headingEl.style.left = (r.left + r.width / 2).toFixed(0) + "px"; headingEl.style.top = (r.top + r.height / 2).toFixed(0) + "px";
      headingEl.style.setProperty("--gx-rot", (Math.atan2(st.vy * sg, st.vx * sg) * 180 / Math.PI).toFixed(1) + "deg");
      headingEl.style.opacity = Math.min(1, 0.25 + st.speed / 1.2).toFixed(2);
    } else headingEl.hidden = true;
    if (on || !headingEl.hidden) spinRaf = requestAnimationFrame(paintSpin);
  }

  // ---------- the "Gestures" help card + the first-use coach mark per screen ----------
  function currentKey() {
    const settingsUp = !!document.querySelector(".a11y-panel:not([hidden])");
    const video = document.body.dataset.video === "1";   // hook: the video overlay (another branch) sets body[data-video=1]
    return screenKey((ctx.screen && ctx.screen()) || {}, { cabin: !!(ctx.inCabin && ctx.inCabin()), settings: settingsUp, video });
  }
  const KEY_NAMES = { moon: "the Moon", lesson: "lessons", menu: "this screen", cabin: "the cabin", video: "videos", settings: "Settings" };
  let cardT = 0;
  function showCard(mode) {
    const key = currentKey(), rows = mode === "coach" ? coachRows(key, S) : helpRows(key, S);
    if (!rows.length) return false;
    card.dataset.mode = mode; card.dataset.screen = key;
    card.innerHTML = `<h3 id="gxCardTitle">${icon("hand")}<span>${mode === "coach" ? "Try this here" : "Gestures on " + esc(KEY_NAMES[key] || "this screen")}</span></h3>
      <ul>${rows.map(r => `<li data-g="${esc(r.id)}">${icon(r.icon)}<span><b>${esc(r.name)}</b><small>${esc(r.does)}</small></span></li>`).join("")}</ul>
      <p class="gx-note">Voice, touch and keys work too.</p><button type="button" class="pill" data-close>${mode === "coach" ? "Got it" : "Close"}</button>`;
    card.hidden = false;
    card.querySelector("[data-close]").onclick = hideCard;
    clearTimeout(cardT);
    if (mode === "coach") cardT = setTimeout(hideCard, 8000);
    else card.querySelector("[data-close]").focus({ preventScroll: true });
    return true;
  }
  function hideCard() { clearTimeout(cardT); const was = !card.hidden && card.dataset.mode === "help"; card.hidden = true; if (was) $("gxHelpBtn").focus({ preventScroll: true }); }
  card.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); hideCard(); } });
  $("gxHelpBtn").onclick = () => (card.hidden || card.dataset.mode !== "help" ? showCard("help") : hideCard());
  let lastKey = "";
  function coachTick() {
    if (!engine.running || calib) return;
    const k = currentKey(); if (k === lastKey) return; lastKey = k;
    if (!(S.coached || {})[k] && card.hidden && showCard("coach")) set({ coached: { ...(S.coached || {}), [k]: 1 } });
  }
  setInterval(coachTick, 700);

  // ---------- indicator + preview ----------
  function paintStatus() {
    const on = status.state === "on" || status.state === "starting";
    ind.hidden = !on; document.body.dataset.camera = on ? "on" : "off";
    ind.classList.toggle("is-starting", status.state === "starting");
    ind.querySelector(".gx-ind-text").textContent = status.state === "starting" ? "Camera starting" : "Camera on";
    prev.hidden = !(on && S.preview);
    if (!on) hideCursor();
    if (status.error) live.textContent = status.error;
    paintSettings();
  }
  $("gxOff").onclick = () => setEnabled(false);
  $("gxHidePreview").onclick = () => { set({ preview: false }); paintStatus(); };
  // the self-view moves: drag the bar, or arrow keys on it; the spot is remembered on this device
  (function movable() {
    const place = p => { if (!p) return; prev.style.left = Math.max(8, Math.min(innerWidth - prev.offsetWidth - 8, p.x)) + "px"; prev.style.top = Math.max(8, Math.min(innerHeight - prev.offsetHeight - 8, p.y)) + "px"; prev.style.right = "auto"; prev.style.bottom = "auto"; };
    place(S.previewPos);
    const grip = $("gxGrip"); let d = null;
    grip.addEventListener("pointerdown", e => { if (e.target.closest("button")) return; const r = prev.getBoundingClientRect(); d = { dx: e.clientX - r.left, dy: e.clientY - r.top }; grip.setPointerCapture(e.pointerId); });
    grip.addEventListener("pointermove", e => { if (d) place({ x: e.clientX - d.dx, y: e.clientY - d.dy }); });
    grip.addEventListener("pointerup", () => { if (!d) return; d = null; const r = prev.getBoundingClientRect(); set({ previewPos: { x: r.left, y: r.top } }); });
    grip.addEventListener("keydown", e => {
      const k = { ArrowLeft: [-24, 0], ArrowRight: [24, 0], ArrowUp: [0, -24], ArrowDown: [0, 24] }[e.key]; if (!k) return;
      e.preventDefault(); const r = prev.getBoundingClientRect(); place({ x: r.left + k[0], y: r.top + k[1] }); const q = prev.getBoundingClientRect(); set({ previewPos: { x: q.left, y: q.top } });
    });
  })();

  function drawSkeleton(f) {
    const c = skel, g = c.getContext("2d"); if (!g) return;
    const w = c.width, h = c.height; g.clearRect(0, 0, w, h);
    const css = getComputedStyle(root);
    (f.hands || []).forEach((hd, i) => {
      g.strokeStyle = i === 0 ? (css.getPropertyValue("--gx-skel").trim() || "#7CC7FF") : "rgba(255,255,255,.45)"; g.lineWidth = 2.5; g.lineCap = "round";
      const P = hd.lm.map(p => [p[0] * w, p[1] * h]);
      g.beginPath(); EDGES.forEach(([a, b]) => { g.moveTo(P[a][0], P[a][1]); g.lineTo(P[b][0], P[b][1]); }); g.stroke();
      g.fillStyle = "#fff"; P.forEach(p => { g.beginPath(); g.arc(p[0], p[1], 2.5, 0, Math.PI * 2); g.fill(); });
    });
    // the face box only as a frame (no identity, nothing drawn on the face itself)
    (f.faces || []).slice(0, 1).forEach(fc => { g.strokeStyle = "rgba(255,255,255,.35)"; g.lineWidth = 1.5; g.strokeRect(fc.box.x * w, fc.box.y * h, fc.box.w * w, fc.box.h * h); });
  }

  // ---------- on / off ----------
  async function setEnabled(on) {
    set({ enabled: !!on });
    if (on) {
      engine.configure(classifierOpts());
      const ok = await engine.start({ deviceId: S.deviceId || undefined });
      if (!ok) set({ enabled: false });
      else {
        refreshCams(); if (ctx.announce) ctx.announce("Camera on. Gestures ready.");
        // the first time: a short calibration (hand, fist, head). Skippable; the defaults feel fine without it.
        if (!spinCal && !S.spinOffered) { set({ spinOffered: true }); setTimeout(() => calibrate({ first: true }), 400); }
      }
    }
    else { await engine.stop(); if (ctx.announce) ctx.announce("Camera off."); }
    paintStatus();
  }

  // ---------- Settings → Camera & gestures: a section of the Settings sheet (window.__outpost.settingsSections) ----------
  let cams = [];
  const refreshCams = () => engine.listDevices().then(c => { const was = cams.length; cams = c; if (c.length > 1 && was <= 1) paintSettings(true); });
  refreshCams();
  const sensName = v => (v < 0.9 ? "Careful" : v > 1.1 ? "Quick" : "Normal");
  function sectionHtml() {
    const on = status.state === "on" || status.state === "starting";
    const sheet = rows => rows.map(r => `<li>${icon(r.icon)}<span><b>${esc(r.name)}</b><small>${esc(r.does)}</small></span></li>`).join("");
    return `<div class="gx-settings">
        <label class="a11y-sw"><input type="checkbox" id="gxEnabled" ${on ? "checked" : ""}><span><b>Use the camera for gestures</b>
          <small>Off until you turn it on. The picture stays on this computer and is never saved or sent.</small></span></label>
        <p class="gx-state" aria-live="polite">${esc(stateText())}</p>
        ${cams.length > 1 ? `<label class="gx-row"><b>Camera</b><select id="gxCam">${cams.map(c => `<option value="${esc(c.id)}" ${c.id === S.deviceId ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select></label>` : ""}
        <label class="a11y-sw"><input type="checkbox" id="gxPreviewSw" ${S.preview ? "checked" : ""}><span><b>Show me on screen</b><small>A small self-view with your hand's skeleton</small></span></label>
        <label class="a11y-sw"><input type="checkbox" id="gxHead" ${S.headLook ? "checked" : ""}><span><b>Look around with your head</b><small>In the cabin: turn to look, lean in to open a panel</small></span></label>
        <label class="a11y-range"><b>Sensitivity <span class="gx-out">${sensName(S.sensitivity)}</span></b>
          <input type="range" id="gxSens" min="0.6" max="1.4" step="0.2" value="${S.sensitivity}" aria-valuetext="${sensName(S.sensitivity)}"></label>
        <fieldset class="set-seg gx-hand"><legend>I use my</legend>
          <label><input type="radio" name="gxHanded" value="right" ${S.handed === "right" ? "checked" : ""}><span>Right hand</span></label>
          <label><input type="radio" name="gxHanded" value="left" ${S.handed === "left" ? "checked" : ""}><span>Left hand</span></label></fieldset>
        <label class="a11y-sw"><input type="checkbox" id="gxInvert" ${S.invertSpin ? "checked" : ""}><span><b>Flip the spin</b><small>Off: the Moon turns the way your fist leans. On: the other way.</small></span></label>
        <label class="a11y-sw"><input type="checkbox" id="gxPhase2" ${S.phase2 ? "checked" : ""}><span><b>Extra gestures (try-out)</b><small>Two-hand pinch to zoom</small></span></label>
        <button type="button" class="btn" id="gxCalib" data-needs-on ${on ? "" : "disabled"}>Recalibrate (about 20 seconds)</button>
        <details class="gx-sheet"><summary>Gesture cheat-sheet</summary><ul>${sheet(CHEATSHEET)}${S.phase2 ? sheet(CHEATSHEET_PHASE2) : ""}</ul>
          <p class="gx-note">Everything also works with voice, touch and keys. Keys: <kbd>Alt</kbd>+<kbd>→</kbd> next, <kbd>Alt</kbd>+<kbd>←</kbd> back, <kbd>Alt</kbd>+<kbd>Y</kbd> yes, <kbd>Alt</kbd>+<kbd>N</kbd> no, <kbd>Alt</kbd>+<kbd>.</kbd> stop.</p></details>
      </div>`;
  }
  let host = null;
  function bindSection(el) {
    host = el;
    const $h = s => el.querySelector(s);
    $h("#gxEnabled").onchange = e => setEnabled(e.target.checked);
    const cam = $h("#gxCam"); if (cam) cam.onchange = e => { set({ deviceId: e.target.value }); if (engine.running) setEnabled(true); };
    $h("#gxPreviewSw").onchange = e => { set({ preview: e.target.checked }); paintStatus(); };
    $h("#gxHead").onchange = e => { set({ headLook: e.target.checked }); engine.configure({ headLook: S.headLook }); };
    $h("#gxSens").oninput = e => { set({ sensitivity: +e.target.value }); engine.configure({ sensitivity: S.sensitivity }); const o = $h(".gx-out"); o.textContent = sensName(S.sensitivity); e.target.setAttribute("aria-valuetext", o.textContent); };
    el.querySelectorAll("[name=gxHanded]").forEach(r => { r.onchange = e => { set({ handed: e.target.value }); engine.configure({ handed: S.handed }); }; });
    $h("#gxPhase2").onchange = e => { set({ phase2: e.target.checked }); engine.configure({ phase2: S.phase2 }); paintSettings(true); };
    $h("#gxInvert").onchange = e => { set({ invertSpin: e.target.checked }); configureSpin({ invert: S.invertSpin }); };
    $h("#gxCalib").onclick = () => calibrate();
  }
  /** Repaint the section if it is showing: light (state line, enabled flags) or full (re-render, keep focus by id). */
  function paintSettings(full) {
    const box = host && host.isConnected && host.querySelector(".gx-settings"); if (!box) return;
    const on = status.state === "on" || status.state === "starting";
    if (!full) {
      box.querySelector("#gxEnabled").checked = on;
      box.querySelector(".gx-state").textContent = stateText();
      box.querySelectorAll("[data-needs-on]").forEach(e => { e.disabled = !on; });
      return;
    }
    const focusId = document.activeElement && box.contains(document.activeElement) ? document.activeElement.id : null;
    const wrap = document.createElement("div"); wrap.innerHTML = sectionHtml(); box.replaceWith(wrap.firstElementChild);
    bindSection(host);
    if (focusId) { const f = host.querySelector("#" + focusId); if (f) f.focus(); }
  }
  const section = { id: "camera", title: "Camera & gestures", after: "display", html: sectionHtml, bind: bindSection };
  function stateText() {
    const st = engine.stats;
    if (status.state === "on") return `On. ${st.fps || "…"} frames a second${st.delegate ? `, ${st.delegate === "GPU" ? "graphics chip" : "processor"}` : ""}. ${spinCal ? "Fist tuned for you." : "Fist: standard."}`;
    if (status.state === "starting") return "Starting the camera…";
    if (status.state === "denied" || status.state === "error") return status.error || "The camera didn't start.";
    return "Off.";
  }

  // ---------- calibration: hand size, the fist's comfortable range per direction, the head (≤ 30 s, skippable) ----------
  // "Hold up your open hand… Make a fist… now tilt it left… right… up… down… Sit back and look at the screen."
  // Step holds run on the landmark clock (frame t), so injected frames (tests) calibrate the same way as a camera.
  function calibrate({ first = false } = {}) {
    if (!engine.running || calib) return;
    hideCard();
    const dlg = document.createElement("div"); dlg.className = "gx-calib"; dlg.setAttribute("role", "dialog"); dlg.setAttribute("aria-modal", "true"); dlg.setAttribute("aria-labelledby", "gxCalTitle");
    dlg.innerHTML = `<div class="gx-calib-card"><h3 id="gxCalTitle">${first ? "Let's tune your gestures" : "Tune your gestures"}</h3><div class="gx-calib-view"><div class="gx-calib-dir" aria-hidden="true"></div></div>
      <p class="gx-calib-step" aria-live="assertive"></p><div class="gx-calib-bar"><i></i></div>
      <div class="gx-calib-row"><button type="button" class="pill" data-skip>${first ? "Skip for now" : "Skip"}</button><button type="button" class="pill" data-close>Done</button></div></div>`;
    document.body.append(dlg);
    const v = dlg.querySelector(".gx-calib-view"); v.prepend(engine.video, skel);   // borrow the self-view, put it back after
    const stepEl = dlg.querySelector(".gx-calib-step"), bar = dlg.querySelector(".gx-calib-bar i"), dirEl = dlg.querySelector(".gx-calib-dir");
    const fc = createFistCalibration();
    const pose = f => (f.hands.length ? handPose(f.hands[0], f.aspect).pose : "none");
    const steps = [
      { id: "palm", text: "Hold up your open hand.", icon: "hand", until: f => pose(f) === "palm", hold: 500 },
      { id: "fist", text: "Make a fist. Keep it still.", icon: "grab", until: f => pose(f) === "fist", hold: CALIBRATION.fistHoldMs, still: CALIBRATION.fistStill },
      { id: "left", text: "Now tilt it left.", icon: "grab", dir: "left" },
      { id: "right", text: "Now tilt it right.", icon: "grab", dir: "right" },
      { id: "up", text: "Now tilt it up.", icon: "grab", dir: "up" },
      { id: "down", text: "Now tilt it down.", icon: "grab", dir: "down" },
      { id: "head", text: "Sit back and look at the screen.", icon: "head", until: f => f.faces.length > 0, hold: 900 },
    ];
    let i = 0, since = null, scale = null, spun = false, anchor = null; const t0 = performance.now(), BUDGET = 30000;
    const show = () => {
      const st = steps[i]; stepEl.innerHTML = icon(st.icon) + " " + esc(st.text);
      dirEl.dataset.dir = st.dir || ""; bar.style.width = ((i / steps.length) * 100).toFixed(0) + "%";
    };
    show();
    const next = () => { i++; since = null; if (steps[i]) show(); else { stepEl.textContent = "All set."; bar.style.width = "100%"; setTimeout(() => finish(true), 600); } };
    const finish = ok => {
      if (!calib) return;
      clearInterval(tickT); calib = null;
      if (ok && scale) { set({ minHandScale: Math.max(0.03, +(scale * 0.45).toFixed(3)) }); }
      if (spun) { const c = fc.result(); if (saveSpinCal(c)) spinCal = loadSpinCal(); }
      engine.configure({ ...(S.minHandScale ? { minHandScale: S.minHandScale } : {}), spinCal });
      view.prepend(engine.video); view.append(skel); dlg.remove();
      if (ctx.announce) ctx.announce(ok ? "All set. Your gestures are ready." : spun ? "Saved what we tuned." : "Calibration stopped. The standard settings work fine.");
      paintSettings();
      const b = host && host.querySelector("#gxCalib"); if (b && b.isConnected) b.focus();
    };
    calib = {
      frame(f) {
        const st = steps[i]; if (!st) return;
        const t = f.t;
        if (st.dir) {
          if (!f.hands.length) return;
          const r = fc.feed(st.dir, fistReading(f.hands[0], f.aspect), t);
          dirEl.style.setProperty("--gx-k", r.progress.toFixed(2));
          if (r.done) { spun = true; next(); }
          return;
        }
        const hit = st.until(f);
        if (hit && st.id === "palm") { const P = f.hands[0].lm; scale = Math.hypot((P[9][0] - P[0][0]) * f.aspect, P[9][1] - P[0][1]); }
        // a still fist: if it wanders while held, the hold starts again from there (the neutral pose must be neutral)
        if (hit && st.still) {
          const r = fistReading(f.hands[0], f.aspect);
          if (anchor && Math.hypot((r.palm[0] - anchor.palm[0]) * f.aspect, r.palm[1] - anchor.palm[1]) / (anchor.scale || 1) > st.still) since = null;
          if (since == null) anchor = r;
        }
        if (hit) {
          if (since == null) since = t;
          if (t - since >= st.hold) {
            if (st.id === "fist") fc.begin(fistReading(f.hands[0], f.aspect));   // the neutral: where the still fist is now
            if (st.id === "head") engine.classifier.setNeutral();
            next();
          }
        } else since = null;
      },
      event() { /* gestures don't act during calibration */ },
    };
    const tickT = setInterval(() => { if (performance.now() - t0 >= BUDGET && calib) finish(i >= steps.length - 1); }, 250);
    dlg.querySelector("[data-close]").onclick = () => finish(i >= 2);
    dlg.querySelector("[data-skip]").onclick = () => { if (steps[i] && steps[i].dir) { next(); } else finish(false); };
    dlg.addEventListener("keydown", e => { if (e.key === "Escape") finish(false); });
    dlg.querySelector("[data-skip]").focus();
  }

  // The camera-on chip lives in the top bar (next to the Settings gear) when the shell gives it a spot.
  if (ctx.indicatorBefore) { ind.classList.add("is-docked", "gx-ui-vars"); ctx.indicatorBefore.before(ind); }
  // The floating voice bar keeps clear of the self-view (and the chip when it floats).
  if (ctx.addObstacle) { ctx.addObstacle(".gx-preview:not([hidden])"); if (!ctx.indicatorBefore) ctx.addObstacle(".gx-indicator:not([hidden])"); }
  // Settings → Camera & gestures (ux-v3's extension point; the sheet renders it after Display)
  window.__outpost = window.__outpost || {};
  (window.__outpost.settingsSections = window.__outpost.settingsSections || []).push(section);

  // start where the kid left it (the indicator shows at once); never on a first run
  if (S.enabled) setEnabled(true);
  paintStatus();

  let lastInjT = 0;
  const api = {
    enable: () => setEnabled(true), disable: () => setEnabled(false), section, calibrate,
    get active() { return engine.running; }, get settings() { return { ...S }; }, get stats() { return engine.stats; },
    /** Tests: push landmark frames as if the camera saw them (works with the camera off). */
    inject: frames => { const fs = [].concat(frames); fs.forEach(f => { lastInjT = Math.max(lastInjT, f.t); }); return engine.inject(fs); },
    /** Tests: the same, played in real time (the frames' own spacing), so rate control and its animation run. The
     *  frames are re-timed after anything injected before (the classifier needs time to go forwards). */
    injectPaced: async frames => {
      const fs = [].concat(frames); if (!fs.length) return [];
      const out = [], tA = fs[0].t, w0 = performance.now(), base = Math.max(Math.round(w0), lastInjT + 1000);
      lastInjT = base + (fs[fs.length - 1].t - tA);
      engine.mute(true);
      try {
        for (const f of fs) {
          const wait = (f.t - tA) - (performance.now() - w0);
          if (wait > 1) await new Promise(r => setTimeout(r, wait));
          out.push(...engine.inject([{ ...f, t: Math.round(base + (f.t - tA)) }]));
        }
      } finally { engine.mute(false); }
      return out.map(e => e.type);
    },
    spin: () => spinState(),
    get calibration() { return spinCal; },
    showHelp: () => showCard("help"),
    recent: recentIntents,
    summary: () => (engine.running ? spokenSummary({ cabin: !!(ctx.inCabin && ctx.inCabin()) }) : ""),
  };
  window.__outpost = window.__outpost || {};
  window.__outpost.gestures = api;
  return api;
}
