// Accessibility: settings, the settings panel (#a11yBtn), voice-only operation, audio description, visual alerts,
// captions/transcripts, keyboard + ARIA helpers (docs/ACCESSIBILITY.md).
// Settings live in localStorage only ("outpost-a11y"); they are never sent to the server.

// ---------- settings (pure; tests/a11y.test.js) ----------

export const SPEEDS = [0.75, 1, 1.25, 1.5];
export const DEFAULTS = Object.freeze({
  speed: 1,              // TTS speed: Steer rate + pace (server); crew audio playbackRate
  contrast: false,       // high-contrast theme
  textScale: 1,          // 1 – 1.5
  reducedMotion: false,  // also on when the OS asks
  dyslexia: false,       // Atkinson Hyperlegible + wider spacing
  describe: false,       // audio description: the Director's visual moves, spoken + aria-live
  visualAlerts: true,    // flash + banner icon with every alert chime
  vibrate: true,         // navigator.vibrate on alerts, where supported
  captions: true,        // captions for every voice (always on by default)
  captionChars: 42,      // caption line length limit (reading support)
});
const KEY = "outpost-a11y";

/** Any stored object → valid settings (unknown keys dropped, values clamped / snapped). */
export function normalize(s) {
  const o = { ...DEFAULTS }, x = s && typeof s === "object" ? s : {};
  const near = (v, list) => list.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));
  if (isFinite(+x.speed)) o.speed = near(+x.speed, SPEEDS);
  if (isFinite(+x.textScale)) o.textScale = Math.round(Math.max(1, Math.min(1.5, +x.textScale)) * 4) / 4;
  if (isFinite(+x.captionChars)) o.captionChars = Math.max(24, Math.min(80, Math.round(+x.captionChars)));
  ["contrast", "reducedMotion", "dyslexia", "describe", "visualAlerts", "vibrate", "captions"].forEach(k => { if (typeof x[k] === "boolean") o[k] = x[k]; });
  return o;
}
export function loadSettings(storage) {
  try { const raw = storage && storage.getItem(KEY); return normalize(raw ? JSON.parse(raw) : {}); } catch (e) { return { ...DEFAULTS }; }
}
export function saveSettings(storage, s) {
  const v = normalize(s);
  try { storage && storage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* private mode: in-memory only */ }
  return v;
}
/** The next speed up/down the ladder. */
export function stepSpeed(cur, dir) { const i = SPEEDS.indexOf(normalize({ speed: cur }).speed); return SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, i + dir))]; }

/** A typed or spoken a11y command → {cmd, arg} or null. Kept narrow so lesson answers aren't swallowed. */
export function parseCommand(text) {
  const t = String(text || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  if (!t) return null;
  if (/^(where am i|what screen is this|what s on (the )?screen|describe (the )?screen)$/.test(t)) return { cmd: "where" };
  if (/^(what can i do|what can i say|help me|options|what are my options)$/.test(t)) return { cmd: "options" };
  if (/^(speak |talk )?(faster|speed up)( please)?$/.test(t)) return { cmd: "speed", arg: 1 };
  if (/^(speak |talk )?(slower|slow down)( please)?$/.test(t)) return { cmd: "speed", arg: -1 };
  if (/^(normal speed|regular speed)$/.test(t)) return { cmd: "speed", arg: 0 };
  if (/^(bigger|larger) (text|words)$/.test(t)) return { cmd: "text", arg: 1 };
  if (/^smaller (text|words)$/.test(t)) return { cmd: "text", arg: -1 };
  if (/^high contrast( on)?$/.test(t)) return { cmd: "contrast", arg: true };
  if (/^high contrast off$/.test(t)) return { cmd: "contrast", arg: false };
  if (/^(describe things|audio description)( on)?$/.test(t)) return { cmd: "describe", arg: true };
  if (/^(audio description|stop describing)( off)?$/.test(t) && /off|stop/.test(t)) return { cmd: "describe", arg: false };
  if (/^(say (that|it) again|repeat (that|it)|read (that|it) again)$/.test(t)) return { cmd: "repeat" };
  if (/^(open )?(accessibility|settings)( settings)?$/.test(t)) return { cmd: "panel" };
  let m = t.match(/^(?:press|tap|click|choose|pick|select) (?:the )?(.+?)(?: button)?$/);
  if (m) return { cmd: "press", arg: m[1] };
  m = t.match(/^(?:option|answer|number) (\d|one|two|three|four)$/);
  if (m) return { cmd: "nth", arg: { one: 1, two: 2, three: 3, four: 4 }[m[1]] || +m[1] };
  return null;
}

/** The best visible control for a spoken label: exact, then starts-with, then contains (≥ 3 chars). */
export function findControl(label, controls) {
  const n = s => String(s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const want = n(label); if (!want) return null;
  const named = controls.map(c => ({ c, l: n(c.getAttribute && c.getAttribute("aria-label") || c.textContent) }));
  return (named.find(x => x.l === want) || named.find(x => x.l.startsWith(want)) || (want.length >= 3 && named.find(x => x.l.includes(want))) || {}).c || null;
}

// ---------- DOM ----------

const isVisible = el => !!(el && el.getClientRects().length && !el.closest("[hidden]") && getComputedStyle(el).visibility !== "hidden");

/** ARIA helper for the cockpit (and anyone): name, role, state, live. Returns the element. */
export function ariaControl(el, label, { role, pressed, expanded, live, describedBy } = {}) {
  if (!el) return el;
  if (label) el.setAttribute("aria-label", label);
  if (role) el.setAttribute("role", role);
  if (pressed != null) el.setAttribute("aria-pressed", String(!!pressed));
  if (expanded != null) el.setAttribute("aria-expanded", String(!!expanded));
  if (live) el.setAttribute("aria-live", live);
  if (describedBy) el.setAttribute("aria-describedby", describedBy);
  if (!el.matches("button, a[href], input, select, textarea") && !el.hasAttribute("tabindex")) el.tabIndex = 0;
  return el;
}

export function initA11y({ floor, say, ask, setMode, tap, places = [], playCrew } = {}) {
  if (typeof document === "undefined") return null;
  const O = (window.__outpost = window.__outpost || { stepRenderers: {} });
  const store = (() => { try { return window.localStorage; } catch (e) { return null; } })();
  let S = loadSettings(store);
  const root = document.documentElement;

  // ---- live regions: polite (descriptions) + assertive (alerts) ----
  const live = mk("div", "sr-only", { id: "a11yLive", "aria-live": "polite", role: "status" });
  const alertLive = mk("div", "sr-only", { id: "a11yAlert", "aria-live": "assertive", role: "alert" });
  document.body.append(live, alertLive);
  // Skip link: the first Tab stop.
  const skip = mk("a", "skip-link", { href: "#q" }); skip.textContent = "Skip to the answer box";
  document.body.prepend(skip);

  // ---- "no audio needed" indicator + visual alert banner ----
  const noAudio = mk("span", "a11y-noaudio", { role: "note", title: "Every sound here also shows as text" });
  noAudio.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M4 5h16v11H8l-4 4V5Zm3 4v2h10V9H7Zm0 3v2h7v-2H7Z"/></svg><span>No audio needed</span>`;
  const flash = mk("div", "a11y-flash", { "aria-hidden": "true" });
  const vbanner = mk("div", "a11y-vbanner", { role: "alert", hidden: "" });
  document.body.append(flash, vbanner);

  // ---- settings button + panel ----
  let btn = document.getElementById("a11yBtn");
  if (!btn) {                      // the layout agent adds #a11yBtn to the top bar; a fallback until then
    btn = mk("button", "icon-btn a11y-btn", { id: "a11yBtn", type: "button" });
    (document.querySelector(".topnav") || document.querySelector(".topbar") || document.body).append(btn);
  }
  if (!btn.innerHTML.trim()) btn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="4.5" r="2" fill="currentColor"/><path fill="currentColor" d="M4 8.5 12 10l8-1.5.4 2L15 11.6V14l2 7-2 .6-2.4-6.2h-1.2L9 21.6 7 21l2-7v-2.4l-5.4-1.1.4-2Z"/></svg>`;
  ariaControl(btn, "Accessibility settings", { expanded: false });
  btn.setAttribute("aria-haspopup", "dialog"); btn.title = "Accessibility: speed, captions, contrast, text size";
  (document.querySelector(".topnav") || btn.parentElement).append(noAudio);

  const panel = mk("div", "a11y-panel", { role: "dialog", "aria-modal": "true", "aria-labelledby": "a11yTitle", hidden: "" });
  document.body.append(panel);
  function renderPanel() {
    const sw = (k, label, help) => `<label class="a11y-sw"><input type="checkbox" data-k="${k}" ${S[k] ? "checked" : ""}><span><b>${label}</b><small>${help}</small></span></label>`;
    panel.innerHTML = `
      <header><h2 id="a11yTitle">Accessibility</h2><button type="button" class="x" data-close aria-label="Close accessibility settings">&times;</button></header>
      <fieldset class="a11y-speed"><legend>Voice speed</legend>
        ${SPEEDS.map(v => `<label><input type="radio" name="a11ySpeed" value="${v}" ${S.speed === v ? "checked" : ""}><span>${v}×</span></label>`).join("")}</fieldset>
      <label class="a11y-range"><b>Text size <output>${Math.round(S.textScale * 100)}%</output></b>
        <input type="range" min="1" max="1.5" step="0.25" value="${S.textScale}" data-k="textScale" aria-valuetext="${Math.round(S.textScale * 100)} percent"></label>
      <div class="a11y-group" role="group" aria-label="Seeing">
        ${sw("contrast", "High contrast", "Stronger colours and borders")}
        ${sw("describe", "Describe what happens", "Says out loud when the Moon moves, a card opens or an alert shows")}
        ${sw("reducedMotion", "Less motion", "No spinning or flying animations")}
        ${sw("dyslexia", "Easy-read font", "Atkinson Hyperlegible, wider spacing")}
      </div>
      <div class="a11y-group" role="group" aria-label="Hearing">
        ${sw("captions", "Captions", "Show every voice as text, word by word")}
        ${sw("visualAlerts", "Flash for alerts", "The screen edge flashes with every alert sound")}
        ${sw("vibrate", "Vibrate for alerts", "On phones and tablets that can")}
      </div>
      <label class="a11y-range"><b>Caption line length <output>${S.captionChars}</output></b>
        <input type="range" min="24" max="80" step="2" value="${S.captionChars}" data-k="captionChars"></label>
      <details class="a11y-transcript"><summary>Transcript (everything said)</summary><ol id="a11yTranscript"></ol></details>
      <details><summary>Voice and keyboard commands</summary><ul class="a11y-help">
        <li>“Where am I?” · “What can I do?” · “Press Next” · “Option 2”</li>
        <li>“Faster” · “Slower” · “Say that again” · “Bigger text” · “High contrast”</li>
        <li>Keys: <kbd>Tab</kbd> move · <kbd>Enter</kbd> press · <kbd>Esc</kbd> close · <kbd>Alt</kbd>+<kbd>A</kbd> this panel · <kbd>Alt</kbd>+<kbd>W</kbd> where am I · <kbd>Alt</kbd>+<kbd>P</kbd> pick a place</li></ul></details>
      ${places.length ? `<label class="a11y-place"><b>Pick a place on the Moon</b><small>Same as tapping it on the globe</small>
        <span><select id="a11yPlace">${places.filter(p => p.name).sort((a, b) => a.name.localeCompare(b.name)).map(p => `<option value="${p.id}">${escH(p.name)}</option>`).join("")}</select>
        <button type="button" class="pill" id="a11yPlaceGo">Tap it</button></span></label>` : ""}
      <div id="a11yGestures"></div>
      <p class="a11y-note">Saved on this device only. Never sent anywhere.</p>`;
    fillTranscript();
    dispatchEvent(new CustomEvent("outpost:settings-render", { detail: panel }));   // [gestures] Camera & gestures mounts here
  }
  function open(v = panel.hidden) {
    if (v) { renderPanel(); panel.hidden = false; btn.setAttribute("aria-expanded", "true"); (panel.querySelector("input:checked") || panel.querySelector("input")).focus(); }
    else { panel.hidden = true; btn.setAttribute("aria-expanded", "false"); btn.focus(); }
  }
  btn.addEventListener("click", () => open());
  panel.addEventListener("click", e => {
    if (e.target.closest("[data-close]")) open(false);
    if (e.target.id === "a11yPlaceGo") pickPlace(panel.querySelector("#a11yPlace").value);
  });
  panel.addEventListener("change", e => {
    const t = e.target;
    if (t.name === "a11ySpeed") set({ speed: +t.value });
    else if (t.dataset.k && t.type === "checkbox") set({ [t.dataset.k]: t.checked });
    else if (t.dataset.k) set({ [t.dataset.k]: +t.value });
    const out = t.closest("label") && t.closest("label").querySelector("output");
    if (out) out.textContent = t.dataset.k === "textScale" ? Math.round(S.textScale * 100) + "%" : S[t.dataset.k];
  });
  panel.addEventListener("keydown", e => {
    if (e.key === "Escape") { e.stopPropagation(); open(false); }
    if (e.key === "Tab") {        // keep focus inside the dialog
      const f = [...panel.querySelectorAll("button, input, select, summary, [tabindex]")].filter(isVisible);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    }
  });

  function set(patch) { S = saveSettings(store, { ...S, ...patch }); apply(); }
  function apply() {
    root.dataset.contrast = S.contrast ? "high" : "";
    root.dataset.dyslexia = S.dyslexia ? "1" : "";
    root.dataset.motion = S.reducedMotion || (matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) ? "reduce" : "";
    root.dataset.captions = S.captions ? "on" : "off";
    root.style.setProperty("--a11y-zoom", String(S.textScale));
    root.dataset.textScale = S.textScale > 1 ? "big" : "";
    if (S.dyslexia && !document.getElementById("a11yFont")) {
      const l = mk("link", "", { id: "a11yFont", rel: "stylesheet", href: "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap" });
      document.head.append(l);
    }
    if (floor) floor.setSpeed(S.speed);
    const c = floor && floor.crewEl; if (c) { c.playbackRate = S.speed; c.preservesPitch = true; }
  }
  apply();
  // Crew audio: the same speed as a playbackRate (it's a recording, so it can't be re-rendered).
  if (floor) floor.on("playback", e => { if (e.kind === "crew" && e.state === "start" && floor.crewEl) { floor.crewEl.playbackRate = S.speed; floor.crewEl.preservesPitch = true; } });

  // ---- transcript ----
  function fillTranscript() {
    const ol = panel.querySelector("#a11yTranscript"); if (!ol) return;
    ol.innerHTML = (O.transcript || []).slice(-60).map(e => `<li><b>${escH(e.who === "crew" ? "Crew" : e.who === "capcom" ? "CAPCOM" : e.who === "kid" ? "You" : e.who === "describe" ? "Description" : "Guide")}:</b> ${escH(e.text)}</li>`).join("");
  }
  window.addEventListener("outpost:transcript", () => { if (!panel.hidden) fillTranscript(); });

  // ---- audio description ----
  let lastDesc = "", lastDescT = 0;
  function describe(text, { alert = false, quiet = false } = {}) {
    if (!text) return;
    const now = Date.now();
    if (text === lastDesc && now - lastDescT < 4000) return;
    lastDesc = text; lastDescT = now;
    (alert ? alertLive : live).textContent = text;             // screen readers always get it
    if (S.describe && !quiet && say) say(text, { describe: true });   // spoken only in audio-description mode
    if (O.captions && S.describe) O.captions.log("describe", text);
  }

  // Visual moves → descriptions. The globe is wrapped once (fly / show a feature).
  function wrapGlobe(globe, placeById) {
    if (!globe || globe.__a11y) return; globe.__a11y = true;
    const sf = globe.showFeature.bind(globe);
    globe.showFeature = (f, ...a) => { if (f && f.name) describe(`The Moon turns to ${f.name}.`); return sf(f, ...a); };
    const fly = globe.flyTo.bind(globe);
    globe.flyTo = (lat, lon, ...a) => { describe(`The Moon turns to ${Math.abs(Math.round(lat))}° ${lat >= 0 ? "north" : "south"}, ${Math.abs(Math.round(lon))}° ${lon >= 0 ? "east" : "west"}.`); return fly(lat, lon, ...a); };
    O.flyTo = id => { const f = placeById && placeById(id); if (f) globe.showFeature(f); };
  }
  // Cards, banners, HUD alerts and badges: watched in the DOM (no coupling to the UIs that draw them).
  const watch = (sel, fn, opts) => { const el = document.querySelector(sel); if (el) new MutationObserver(() => fn(el)).observe(el, opts); };
  watch("#card", el => { if (!el.hidden) { const t = el.querySelector("#cardTitle"); describe(`Card: ${t ? t.textContent : "answer"}.`, { quiet: true }); } }, { attributes: true, attributeFilter: ["hidden"], childList: true, subtree: false });
  watch("#mBanner", el => { if (!el.hidden && el.textContent.trim()) visualAlert(el.textContent.trim()); }, { attributes: true, attributeFilter: ["hidden", "class"], childList: true, subtree: true });
  const hudSeen = new Set();
  new MutationObserver(() => {
    document.querySelectorAll(".m-bar.is-alert").forEach(b => { const n = b.querySelector("b"); const k = b.id; if (!hudSeen.has(k)) { hudSeen.add(k); describe(`Warning: ${n ? n.textContent : "a resource"} is in the red.`, { alert: true }); } });
    document.querySelectorAll(".m-bar:not(.is-alert)").forEach(b => hudSeen.delete(b.id));
    const st = document.querySelector(".a-step.is-alert:not([data-a11y-seen])"); if (st) { st.dataset.a11ySeen = "1"; visualAlert("Alert: " + (st.querySelector(".a-prompt") || st).textContent.trim().slice(0, 120)); }
    const bd = document.querySelector(".a-badge:not([data-a11y-seen])"); if (bd) { bd.dataset.a11ySeen = "1"; describe(`Badge earned: ${(bd.querySelector(".m-title") || bd).textContent.trim()}.`, { quiet: true }); }
  }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ["class"] });

  // ---- visual alerts (hearing) ----
  function visualAlert(text) {
    if (S.visualAlerts) {
      flash.classList.remove("is-on"); void flash.offsetWidth; flash.classList.add("is-on");
      vbanner.innerHTML = `<span class="a11y-vb-icon" aria-hidden="true">⚠</span><span>${escH(text.slice(0, 140))}</span>`;
      vbanner.hidden = false; clearTimeout(visualAlert.t); visualAlert.t = setTimeout(() => { vbanner.hidden = true; }, 5000);
    }
    if (S.vibrate && navigator.vibrate) { try { navigator.vibrate([180, 80, 180]); } catch (e) { /* not allowed */ } }
    describe(text, { alert: true, quiet: true });
  }

  // ---- screen state on request ----
  function where() {
    const mode = document.body.dataset.mode, M = { academy: "the Academy", mission: "Mission control", cadet: "the Moon library" };
    const bits = [`You are in ${M[mode] || "the app"}.`];
    const ap = document.getElementById("aPanel");
    if (ap && !ap.hidden) {
      const title = ap.querySelector(".m-title"), eb = ap.querySelector(".m-head .eyebrow"), pr = ap.querySelector(".a-prompt"), fb = ap.querySelector(".a-feedback");
      if (eb) bits.push(eb.textContent.trim() + ".");
      if (title) bits.push(title.textContent.trim() + ".");
      if (pr) bits.push("The question: " + pr.textContent.trim());
      if (fb && fb.textContent.trim()) bits.push(fb.textContent.trim());
    }
    const mp = document.getElementById("mPanel");
    if (mp && !mp.hidden) {
      const bars = [...mp.querySelectorAll(".m-bar")].map(b => `${(b.querySelector("b") || {}).textContent} ${(b.querySelector(".m-val") || {}).textContent}`);
      if (bars.length) bits.push("Resources: " + bars.join(", ") + ".");
    }
    const card = document.getElementById("card");
    if (card && !card.hidden) bits.push("A card is open: " + (card.querySelector("#cardTitle") || {}).textContent + ".");
    return bits.join(" ");
  }
  function controls() {
    const scope = [document.getElementById("aPanel"), document.getElementById("mPanel"), document.getElementById("card"), document.querySelector(".topbar")].filter(isVisible);
    return scope.flatMap(s => [...s.querySelectorAll("button, a[href], [role=button]")]).filter(isVisible).filter(b => !b.closest(".a11y-panel"));
  }
  function options() {
    const names = controls().map(b => (b.getAttribute("aria-label") || b.textContent).replace(/\s+/g, " ").trim()).filter(Boolean);
    const uniq = [...new Set(names)].slice(0, 8);
    const g = O.gestures && O.gestures.summary ? O.gestures.summary() : "";   // [gestures] only while the camera is on
    return `You can say or type your answer, or say press and a button name. Buttons: ${uniq.join(", ")}.${g ? " " + g : ""}`;
  }
  function pickPlace(id) {
    const p = places.find(x => x.id === id); if (!p || !tap) return;
    open(false); tap({ lat: p.lat, lon: p.lon, place: p.id, ...p });
  }

  /** A typed or spoken turn. True when it was an a11y command. */
  async function handleText(text) {
    const c = parseCommand(text); if (!c) return false;
    const reply = t => { describe(t, { quiet: true }); if (say) say(t, {}); };
    switch (c.cmd) {
      case "where": reply(where()); break;
      case "options": reply(options()); break;
      case "speed": set({ speed: c.arg === 0 ? 1 : stepSpeed(S.speed, c.arg) }); reply(`Voice speed ${S.speed} times.`); break;
      case "text": set({ textScale: Math.max(1, Math.min(1.5, S.textScale + 0.25 * c.arg)) }); reply(`Text size ${Math.round(S.textScale * 100)} percent.`); break;
      case "contrast": set({ contrast: c.arg }); reply(`High contrast ${c.arg ? "on" : "off"}.`); break;
      case "describe": set({ describe: c.arg }); reply(`Audio description ${c.arg ? "on" : "off"}.`); break;
      case "repeat": { const last = (O.transcript || []).filter(e => e.who !== "describe" && e.who !== "kid").slice(-1)[0]; if (last && say) say(last.text, {}); break; }
      case "panel": open(true); break;
      case "press": { const b = findControl(c.arg, controls()); if (!b) return false; b.focus({ preventScroll: true }); b.click(); describe(`Pressed ${(b.getAttribute("aria-label") || b.textContent).trim()}.`, { quiet: true }); break; }
      case "nth": { const opts = [...document.querySelectorAll("#aPanel .a-choice, #aPanel .v-opt")].filter(isVisible); const b = opts[c.arg - 1]; if (!b) return false; b.focus(); b.click(); break; }
      default: return false;
    }
    return true;
  }

  // ---- keyboard ----
  addEventListener("keydown", e => {
    if (!e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "a" || e.code === "KeyA") { e.preventDefault(); open(); }
    else if (k === "w" || e.code === "KeyW") { e.preventDefault(); const t = where(); describe(t, { quiet: true }); if (say) say(t, {}); }
    else if (k === "p" || e.code === "KeyP") { e.preventDefault(); open(true); const s = panel.querySelector("#a11yPlace"); if (s) s.focus(); }
  });
  // Every icon-only control gets a name (title → aria-label), and focusable marks show focus (CSS :focus-visible).
  const nameControls = () => document.querySelectorAll("button:not([aria-label]), [role=button]:not([aria-label])").forEach(b => {
    if (!b.textContent.trim() && b.title) b.setAttribute("aria-label", b.title);
  });
  nameControls(); new MutationObserver(() => { cancelAnimationFrame(nameControls.r); nameControls.r = requestAnimationFrame(nameControls); }).observe(document.body, { childList: true, subtree: true });

  O.a11y = { get settings() { return S; }, set, describe, visualAlert, handleText, where, options, wrapGlobe, ariaControl, open, playCrew };
  return O.a11y;
}

function mk(tag, cls, attrs = {}) { const e = document.createElement(tag); if (cls) e.className = cls; Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); return e; }
const escH = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
