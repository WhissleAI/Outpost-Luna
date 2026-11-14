// Camera gestures: everything the kid sees. The camera indicator (always visible while on, one-click off), the
// movable self-view with the hand skeleton, the dwell cursor, the contextual hint chip, gesture feedback, the
// "Camera & gestures" settings section, the 10-second calibration and the cheat-sheet. docs/GESTURES.md.
//
// Off by default. Turning it on is an explicit choice in Settings (or "turn on the camera", which opens Settings).
// Frames never leave the device and are never stored; settings live in localStorage on this device only.
import "./gestures.css";
import { emitIntent, recentIntents } from "../input/intents.js";
import { createGestureEngine } from "./engine.js";
import { gestureIntents, FEEDBACK } from "./bind.js";
import { CHEATSHEET, CHEATSHEET_PHASE2, hintFor, spokenSummary } from "./guide.js";
import { icon } from "./icons.js";
import { handPose } from "./classifier.js";

const KEY = "outpost-gestures";
export const SETTINGS_DEFAULTS = Object.freeze({ enabled: false, deviceId: "", preview: true, sensitivity: 1, headLook: true, handed: "right", phase2: false, previewPos: null, minHandScale: null });
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
      <button type="button" class="gx-off" id="gxOff">Turn off</button>
    </div>
    <div class="gx-preview" id="gxPreview" hidden aria-label="Camera self-view. Only on this computer.">
      <div class="gx-preview-bar" id="gxGrip" tabindex="0" role="button" aria-label="Move the self-view (arrow keys)">${icon("hand", { size: 14 })}<span>You</span>
        <button type="button" class="gx-x" id="gxHidePreview" aria-label="Hide the self-view">${icon("close", { size: 14 })}</button></div>
      <div class="gx-view"><canvas class="gx-skel" id="gxSkel" width="240" height="180" aria-hidden="true"></canvas></div>
    </div>
    <div class="gx-hint" id="gxHint" hidden aria-hidden="true"></div>
    <div class="gx-toast" id="gxToast" hidden aria-hidden="true"></div>
    <div class="gx-live" role="status" aria-live="polite" id="gxLive"></div>`;
  const cursor = document.createElement("div"); cursor.className = "gx-cursor"; cursor.hidden = true; cursor.setAttribute("aria-hidden", "true");
  cursor.innerHTML = `<svg viewBox="0 0 48 48"><circle class="gx-ring-bg" cx="24" cy="24" r="20"/><circle class="gx-ring" cx="24" cy="24" r="20" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100"/><circle class="gx-tip" cx="24" cy="24" r="5"/></svg>`;
  document.body.append(root, cursor);
  const $ = id => root.querySelector("#" + id);
  const ind = $("gxIndicator"), prev = $("gxPreview"), skel = $("gxSkel"), hint = $("gxHint"), toast = $("gxToast"), live = $("gxLive");
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
    return { sensitivity: S.sensitivity, handed: S.handed, headLook: S.headLook, phase2: S.phase2, ...(S.minHandScale ? { minHandScale: S.minHandScale } : {}) };
  }

  // ---------- gesture events → intents ----------
  function context() {
    const p = ctx.cabinPanel ? ctx.cabinPanel() : null;
    return { cabin: !!(ctx.inCabin && ctx.inCabin()), panel: p, vw: innerWidth, vh: innerHeight, phase2: S.phase2 };
  }
  function handle(ev) {
    if (calib) { calib.event(ev); return; }
    if (ev.type === "point") showCursor(ev);
    if (ev.type === "point_end") hideCursor();
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
    if (c !== hover) { if (hover) hover.classList.remove("gx-hover"); hover = c; if (hover && hover.tagName !== "CANVAS") hover.classList.add("gx-hover"); }
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
    if (on) { engine.configure(classifierOpts()); const ok = await engine.start({ deviceId: S.deviceId || undefined }); if (!ok) set({ enabled: false }); else if (ctx.announce) ctx.announce("Camera on. Gestures ready."); }
    else { await engine.stop(); if (ctx.announce) ctx.announce("Camera off."); }
    paintStatus();
  }

  // ---------- Settings → Camera & gestures (mounted into the Settings sheet's slot) ----------
  let host = null;
  function mountSettings(el) { host = el; paintSettings(true); }
  async function paintSettings(full) {
    if (!host || !host.isConnected) return;
    const on = status.state === "on" || status.state === "starting";
    if (!full && host.querySelector("#gxEnabled")) {   // light refresh: keep focus where it is
      host.querySelector("#gxEnabled").checked = on || status.state === "starting";
      host.querySelector(".gx-state").textContent = stateText();
      host.querySelectorAll("[data-needs-on]").forEach(e => { e.disabled = !on; });
      return;
    }
    const cams = await engine.listDevices();
    const sheet = rows => rows.map(r => `<li>${icon(r.icon)}<span><b>${esc(r.name)}</b><small>${esc(r.does)}</small></span></li>`).join("");
    host.innerHTML = `
      <section class="gx-settings" aria-labelledby="gxTitle">
        <h3 id="gxTitle">${icon("camera")} Camera &amp; gestures</h3>
        <label class="a11y-sw"><input type="checkbox" id="gxEnabled" ${on ? "checked" : ""}><span><b>Use the camera for gestures</b>
          <small>Off until you turn it on. The picture stays on this computer and is never saved or sent.</small></span></label>
        <p class="gx-state" aria-live="polite">${esc(stateText())}</p>
        ${cams.length > 1 ? `<label class="gx-row"><b>Camera</b><select id="gxCam">${cams.map(c => `<option value="${esc(c.id)}" ${c.id === S.deviceId ? "selected" : ""}>${esc(c.label)}</option>`).join("")}</select></label>` : ""}
        <label class="a11y-sw"><input type="checkbox" id="gxPreviewSw" ${S.preview ? "checked" : ""}><span><b>Show me on screen</b><small>A small self-view with your hand's skeleton</small></span></label>
        <label class="a11y-sw"><input type="checkbox" id="gxHead" ${S.headLook ? "checked" : ""}><span><b>Look around with your head</b><small>In the cabin: turn to look, lean in to open a panel</small></span></label>
        <label class="a11y-range"><b>Sensitivity <span class="gx-out">${S.sensitivity < 0.9 ? "Careful" : S.sensitivity > 1.1 ? "Quick" : "Normal"}</span></b>
          <input type="range" id="gxSens" min="0.6" max="1.4" step="0.2" value="${S.sensitivity}" aria-valuetext="${S.sensitivity < 0.9 ? "Careful" : S.sensitivity > 1.1 ? "Quick" : "Normal"}"></label>
        <fieldset class="gx-hand"><legend>I use my</legend>
          <label><input type="radio" name="gxHanded" value="right" ${S.handed === "right" ? "checked" : ""}><span>Right hand</span></label>
          <label><input type="radio" name="gxHanded" value="left" ${S.handed === "left" ? "checked" : ""}><span>Left hand</span></label></fieldset>
        <label class="a11y-sw"><input type="checkbox" id="gxPhase2" ${S.phase2 ? "checked" : ""}><span><b>Extra gestures (try-out)</b><small>Two-hand pinch to zoom; raise your hand to call Houston</small></span></label>
        <button type="button" class="pill" id="gxCalib" data-needs-on ${on ? "" : "disabled"}>Show me your hand (10 seconds)</button>
        <details class="gx-sheet"><summary>Gesture cheat-sheet</summary><ul>${sheet(CHEATSHEET)}${S.phase2 ? sheet(CHEATSHEET_PHASE2) : ""}</ul>
          <p class="gx-note">Everything also works with voice, touch and keys. Keys: <kbd>Alt</kbd>+<kbd>→</kbd> next, <kbd>Alt</kbd>+<kbd>←</kbd> back, <kbd>Alt</kbd>+<kbd>Y</kbd> yes, <kbd>Alt</kbd>+<kbd>N</kbd> no, <kbd>Alt</kbd>+<kbd>.</kbd> stop.</p></details>
      </section>`;
    host.querySelector("#gxEnabled").onchange = e => setEnabled(e.target.checked);
    const cam = host.querySelector("#gxCam"); if (cam) cam.onchange = e => { set({ deviceId: e.target.value }); if (engine.running) setEnabled(true); };
    host.querySelector("#gxPreviewSw").onchange = e => { set({ preview: e.target.checked }); paintStatus(); };
    host.querySelector("#gxHead").onchange = e => { set({ headLook: e.target.checked }); engine.configure({ headLook: S.headLook }); };
    host.querySelector("#gxSens").oninput = e => { set({ sensitivity: +e.target.value }); engine.configure({ sensitivity: S.sensitivity }); const o = e.target.closest("label").querySelector(".gx-out"); o.textContent = S.sensitivity < 0.9 ? "Careful" : S.sensitivity > 1.1 ? "Quick" : "Normal"; e.target.setAttribute("aria-valuetext", o.textContent); };
    host.querySelectorAll("[name=gxHanded]").forEach(r => { r.onchange = e => { set({ handed: e.target.value }); engine.configure({ handed: S.handed }); }; });
    host.querySelector("#gxPhase2").onchange = e => { set({ phase2: e.target.checked }); engine.configure({ phase2: S.phase2 }); paintSettings(true); };
    host.querySelector("#gxCalib").onclick = () => calibrate();
  }
  function stateText() {
    const st = engine.stats;
    if (status.state === "on") return `On. ${st.fps || "…"} frames a second${st.delegate ? `, ${st.delegate === "GPU" ? "graphics chip" : "processor"}` : ""}.`;
    if (status.state === "starting") return "Starting the camera…";
    if (status.state === "denied" || status.state === "error") return status.error || "The camera didn't start.";
    return "Off.";
  }

  // ---------- calibration: "show me your hand" (≤ 10 s) ----------
  function calibrate() {
    if (!engine.running || calib) return;
    const dlg = document.createElement("div"); dlg.className = "gx-calib"; dlg.setAttribute("role", "dialog"); dlg.setAttribute("aria-modal", "true"); dlg.setAttribute("aria-labelledby", "gxCalTitle");
    dlg.innerHTML = `<div class="gx-calib-card"><h3 id="gxCalTitle">Show me your hand</h3><div class="gx-calib-view"></div>
      <p class="gx-calib-step" aria-live="assertive"></p><div class="gx-calib-bar"><i></i></div>
      <button type="button" class="pill" data-close>Done</button></div>`;
    document.body.append(dlg);
    const v = dlg.querySelector(".gx-calib-view"); v.append(engine.video, skel);   // borrow the self-view, put it back after
    const stepEl = dlg.querySelector(".gx-calib-step"), bar = dlg.querySelector(".gx-calib-bar i");
    const steps = [
      { text: "Hold up your open hand.", icon: "hand", until: f => f.hands.length && handPose(f.hands[0], f.aspect).pose === "palm", hold: 600 },
      { text: "Now a thumbs up.", icon: "thumbs-up", until: f => f.hands.length && handPose(f.hands[0], f.aspect).pose === "thumbs_up", hold: 400 },
      { text: "Sit back and look at the screen.", icon: "head", until: f => f.faces.length > 0, hold: 1200 },
    ];
    let i = 0, since = null, scale = null; const t0 = performance.now();
    const show = () => { stepEl.innerHTML = icon(steps[i].icon) + " " + esc(steps[i].text); };
    show();
    const finish = ok => {
      clearInterval(tick); calib = null;
      if (ok && scale) { set({ minHandScale: Math.max(0.03, +(scale * 0.45).toFixed(3)) }); engine.configure({ minHandScale: S.minHandScale }); }
      view.prepend(engine.video); view.append(skel); dlg.remove();
      if (ctx.announce) ctx.announce(ok ? "All set. Your gestures are ready." : "Calibration stopped.");
      const b = host && host.querySelector("#gxCalib"); if (b) b.focus();
    };
    calib = {
      frame(f) {
        if (!steps[i]) return;
        const hit = steps[i].until(f);
        if (hit && i === 0) { const P = f.hands[0].lm; scale = Math.hypot((P[9][0] - P[0][0]) * f.aspect, P[9][1] - P[0][1]); }
        if (hit) { if (since == null) since = performance.now(); if (performance.now() - since >= steps[i].hold) { if (i === 2) engine.classifier.setNeutral(); i++; since = null; if (steps[i]) show(); else { stepEl.textContent = "All set."; setTimeout(() => finish(true), 600); } } }
        else since = null;
      },
      event() { /* gestures don't act during calibration */ },
    };
    const tick = setInterval(() => { const k = Math.min(1, (performance.now() - t0) / 10000); bar.style.width = (k * 100).toFixed(0) + "%"; if (k >= 1 && calib) finish(i >= 2); }, 100);
    dlg.querySelector("[data-close]").onclick = () => finish(i >= 2);
    dlg.addEventListener("keydown", e => { if (e.key === "Escape") finish(false); });
    dlg.querySelector("[data-close]").focus();
  }

  // start where the kid left it (the indicator shows at once); never on a first run
  if (S.enabled) setEnabled(true);
  paintStatus();

  const api = {
    enable: () => setEnabled(true), disable: () => setEnabled(false), mountSettings, calibrate,
    get active() { return engine.running; }, get settings() { return { ...S }; }, get stats() { return engine.stats; },
    /** Tests: push landmark frames as if the camera saw them (works with the camera off). */
    inject: frames => engine.inject(frames),
    recent: recentIntents,
    summary: () => (engine.running ? spokenSummary({ cabin: !!(ctx.inCabin && ctx.inCabin()) }) : ""),
  };
  window.__outpost = window.__outpost || {};
  window.__outpost.gestures = api;
  return api;
}
