// Accessibility: settings, the settings panel (#a11yBtn), voice-only operation, audio description, visual alerts,
// captions/transcripts, keyboard + ARIA helpers (docs/ACCESSIBILITY.md).
// Settings live in localStorage only ("outpost-a11y"); they are never sent to the server.
import { TOUR, MOON_BASE } from "./story.js";
import { isAvailable, openVideo, offlineLine } from "./media/video.js";   // Help: replay NASA's Moon Base video
import { icon } from "./assets/icons.js";
import { maskProfanity } from "./profanity.js";   // [P0] the transcript never shows a rude word
import { roleName } from "./courses.js";   // [courses] the transcript names the course's guide (Field Director)
import { moreVoicesHint, engineChoiceHtml } from "./prefs.js";   // Settings → Voice: where a parent adds clearer OS voices
import { onIntent } from "./input/intents.js";   // [robustness] Settings is modal for gestures, keys and the controller too
import { zoneHtml, confirmHtml, bindConfirm, holdButtonHtml, bindHold } from "./reset.js";   // Settings → Reset (docs/RESET.md)

/** [0.4.1] Settings → For grown-ups: one section, behind the 3-second hold, for everything that erases or saves files.
 *  Kids' settings (voice, speed, theme, captions…) stay open. Extra sections with `grownup: true` (Videos, Help &
 *  diagnostics, What the app has learned) are drawn inside it instead of in the sidebar. */
export const GROWNUPS = {
  title: "For grown-ups",
  gate: "Progress, courses, class lessons, reset, videos, diagnostics, the voice log and the school network. Hold the button for 3 seconds to open them.",
  hold: "Hold for 3 seconds to open",
  inside: ["See progress", "Get or remove courses", "Write class lessons", "Reset the app", "Clear saved videos", "Save diagnostics", "What the app has learned", "Voice log and playtest", "School network", "Reset my patches"],
  patches: "Reset my patches",
  patchesNote: "Hold for 3 seconds. Clears this cadet's patches and lesson progress. The call sign stays.",
  sayLocked: "Here's Reset, in For grown-ups. A grown-up holds the button for 3 seconds to open it.",
  sayOpen: "Here's Reset. A grown-up can choose Start over or Reset everything.",
  // School network (network_ui.js, docs/SCHOOL_IT.md): voice opens it; only a grown-up's hold and tap change it
  sayNetLocked: "Here's School network, in For grown-ups. A grown-up holds the button for 3 seconds to open it.",
  sayNetOpen: "Here's School network. A grown-up can switch it.",
  // [D4] care flags waiting for a grown-up (GET /api/safety/flags): a count on the gate, the details behind the hold
  notes: n => `${n} safety note${n === 1 ? "" : "s"} in Progress`,
};
/** [D4] How many care flags wait for a grown-up (0 when the backend can't say). */
export async function safetyNotes(fetchFn = typeof fetch === "function" ? fetch : null) {
  try { const r = fetchFn ? await fetchFn("/api/safety/flags") : null; const b = r && r.ok ? await r.json() : null; return b && Array.isArray(b.flags) ? b.flags.length : 0; } catch (e) { return 0; }
}
/** Settings → Listening: the turn log switch (prefs.improve, on by default since 0.4.3; docs/DIRECTOR_LOOP.md §1). */
export const IMPROVE = {
  label: "Help improve the voice guide",
  help: "Keeps what it heard as text, on this computer only. No audio, no names.",
  clear: "Delete what's saved",
};
/** The grown-ups section's HTML (pure; tests/settings_gate.test.js). parts: [{id, title, html}] drawn when open. */
export function grownupsHtml({ open = false, parts = [], esc = x => String(x) } = {}) {
  if (!open) return `<div class="gu-gate" role="group" aria-label="${esc(GROWNUPS.title)}">
      <p class="set-help">${esc(GROWNUPS.gate)}</p>
      <ul class="gu-list">${GROWNUPS.inside.map(t => `<li>${esc(t)}</li>`).join("")}</ul>
      <p class="gu-notes" data-gu-notes role="status" hidden></p>
      ${holdButtonHtml(GROWNUPS.hold, "data-gu-open")}</div>`;
  return parts.map(p => `<section class="gu-part" data-gu="${esc(p.id)}" aria-label="${esc(p.title)}"><h4>${esc(p.title)}</h4>${p.html}</section>`).join("");
}

// ---------- settings (pure; tests/a11y.test.js) ----------

export const SPEEDS = [0.75, 1, 1.25, 1.5];
export const DEFAULTS = Object.freeze({
  speed: 1,              // TTS speed: the OS voice's rate (server); crew audio playbackRate
  contrast: false,       // high-contrast theme
  textScale: 1,          // 1 – 1.5
  reducedMotion: false,  // also on when the OS asks
  dyslexia: false,       // Atkinson Hyperlegible + wider spacing
  describe: false,       // audio description: the Director's visual moves, spoken + aria-live
  visualAlerts: true,    // flash + banner icon with every alert chime
  vibrate: true,         // navigator.vibrate on alerts, where supported; [0.6] also a controller's rumble (haptics.js)
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

// "What do I do?": the screen's current hint (window.__outpost.help: academy/ui.js, main.js), docs/PLAYTEST.md. In a
// Flight School step each one climbs the hint ladder (novice playtest 2026-11-16 #1: "where is it?", "I dont know").
// Mirrored in backend/app/turn_router.py NAV ("a11y").
export const HELP_RE = /^(help|help please|help me please|hint|give me a hint|i need (a hint|help)|what do i do( now| here)?|what should i do|what am i supposed to do|i m stuck|i don t get it|i dont get it|i don t know what to do|i dont know what to do|i don t know|i dont know|i do not know|idk|dunno|i have no idea|no idea|how do i do this|what do i do next|what should i do (now|next)|i m lost|i am lost|what s my job|whats my job|what do i have to do|where is it|where s it|wheres it|where|where is that|where do i tap|where do i click|i can t find it|i cant find it|i can t see it|i cant see it|show me where|show me where it is)$/;
// "what?", "huh?": the step again, simply (window.__outpost.explain), never silence (playtest #1, #13)
export const CONFUSED_RE = /^(what|what what|huh|hmm what|eh|what do you mean|what does that mean|i don t understand|i dont understand|i don t get what you mean|what was that|come again|pardon|sorry what)$/;

/** A typed or spoken a11y command → {cmd, arg} or null. Kept narrow so lesson answers aren't swallowed. */
export function parseCommand(text) {
  // [courses playtest] "um, I don't know" / "hmm so what do I do" climb the hint ladder like the bare words (the session
  // router strips the same fillers: backend/app/turn_router.py nav_intent); a filler alone stays nothing
  const t = String(text || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim()
    .replace(/^(?:(?:um+|uh+|uhm|erm?|hmm+|mm+|so|okay|ok)\s+)+(?=\S)/, "");
  if (!t) return null;
  if (/^(where am i|what screen is this|what s on (the )?screen|describe (the )?screen)$/.test(t)) return { cmd: "where" };
  if (/^(what can i do|what can i say|help me|options|what are my options)$/.test(t)) return { cmd: "options" };
  // "what do I do?": the screen's current hint (window.__outpost.help: academy/ui.js, main.js), docs/PLAYTEST.md
  if (HELP_RE.test(t)) return { cmd: "help" };
  if (CONFUSED_RE.test(t)) return { cmd: "confused" };
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
  // voice can only OPEN the reset confirm; the 3-second hold is the only way to do it
  if (/^(reset|start over|erase) (everything|it all|all)$|^(reset|erase) (the )?(whole )?(app|game|outpost luna) (and )?(downloads|everything)$/.test(t)) return { cmd: "reset", arg: "all" };
  if (/^(reset|reset (the |my )?(whole )?(app|game|progress|outpost luna)|start the (whole )?(app|game) over|erase (my )?(progress|everything))$/.test(t)) return { cmd: "reset", arg: "start" };
  if (/^(open )?(the )?school (network|mode)( mode| settings)?$/.test(t)) return { cmd: "network" };   // opens it, never switches it
  if (/^(switch|change|pick|choose|open) (the |a |my )?(course|courses|subject)s?$|^(other|more) courses$/.test(t)) return { cmd: "course" };   // opens the switcher (course_switch.js); picking still asks once
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
  if (!btn.innerHTML.trim()) btn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4.5" r="1.8"/><path d="M5 8.5 12 10l7-1.5M12 10v4l-3 7M12 14l3 7"/></svg>`;
  ariaControl(btn, "Settings", { expanded: false });
  btn.setAttribute("aria-haspopup", "dialog"); btn.title = "Settings";
  // "No audio needed" lives in the settings panel (the top bar stays quiet).

  const scrim = mk("div", "set-scrim", { hidden: "", "aria-hidden": "true" });
  const panel = mk("div", "a11y-panel", { role: "dialog", "aria-modal": "true", "aria-labelledby": "a11yTitle", hidden: "" });
  document.body.append(scrim, panel);
  // Settings: a modal sheet with a section list (left) and one section at a time (right). Accessibility settings
  // (this module) and Settings v1 prefs (prefs.js, window.__outpost.prefsApi) share it. Everything here works.
  const SECTIONS = [["voice", "Voice"], ["sound", "Sound"], ["listen", "Listening"], ["read", "Reading & captions"], ["display", "Display"],
    ["cadets", "Cadets"], ["help", "Help"], ["grownups", GROWNUPS.title]];   // the grown-ups section (Reset and the rest): always last (docs/RESET.md)
  // guOpen: the grown-up held the gate (until Settings closes)
  let section = "voice", resetArmed = false, resetView = null, unbindReset = () => {}, steerPoll = 0, guOpen = false;
  function renderPanel() {
    const PA = O.prefsApi, P = PA ? PA.value : {};
    const sw = (k, label, help) => `<label class="a11y-sw"><input type="checkbox" data-k="${k}" ${S[k] ? "checked" : ""}><span><b>${label}</b><small>${help}</small></span></label>`;
    const seg = (key, label, opts) => `<fieldset class="set-seg"><legend>${label}</legend><div class="a11y-speed">${opts.map(([v, t]) =>
      `<label><input type="radio" name="p-${key}" data-p="${key}" value="${v}" ${P[key] === v ? "checked" : ""}><span>${t}</span></label>`).join("")}</div></fieldset>`;
    const range = (key, label, lo, hi, step, fmt) => `<label class="a11y-range"><b>${label} <output>${fmt(P[key])}</output></b>
      <input type="range" min="${lo}" max="${hi}" step="${step}" value="${P[key]}" data-p="${key}" aria-valuetext="${fmt(P[key])}"></label>`;
    const pct = v => Math.round((+v || 0) * 100) + "%";
    const body = {
      voice: `<div class="set-voices" id="setVoices" aria-live="polite"></div>
        <fieldset class="set-seg"><legend>Speed</legend><div class="a11y-speed">
          ${SPEEDS.map(v => `<label><input type="radio" name="a11ySpeed" value="${v}" ${S.speed === v ? "checked" : ""} aria-label="Voice speed ${v} times"><span>${v}×</span></label>`).join("")}</div></fieldset>
        ${PA ? range("expressiveness", "Expressiveness", 0, 1, 0.25, v => (v <= 0.25 ? "Calm" : v >= 0.75 ? "Lively" : "Balanced")) : ""}
        ${sw("describe", "Describe what happens", "Say out loud when the Moon moves or an alert shows")}`,
      sound: PA ? `${range("volume", "Volume", 0, 2, 0.1, pct)}${range("alarms", "Alarms", 0, 1, 0.05, pct)}
        ${sw("visualAlerts", "Flash for alerts", "The screen edge flashes with every alarm")}
        ${sw("vibrate", "Vibrate for alerts", "Phones, tablets and game controllers")}` : "",
      listen: PA ? `${seg("listen", "How to talk", [["handsfree", "Hands-free"], ["ptt", "Hold to talk"]])}
        <p class="set-help">${P.listen === "ptt" ? "Hold <kbd>Space</kbd> or the mic while you talk." : "The mic listens all the time. <kbd>Space</kbd> still works."}</p>
        ${seg("filter", "Ignore other voices", [["relaxed", "Relaxed"], ["normal", "Normal"], ["strict", "Strict"]])}
        <p class="set-help">Strict ignores more room chatter.</p>
        <label class="a11y-sw"><input type="checkbox" data-pb="improve" ${PA.value.improve ? "checked" : ""}><span><b>${escH(IMPROVE.label)}</b><small>${escH(IMPROVE.help)}</small></span></label>
        <button type="button" class="btn-quiet" data-turnlog-clear>${escH(IMPROVE.clear)}</button>` : "",
      read: `${sw("captions", "Captions", "Every voice as text, word by word")}
        <label class="a11y-range"><b>Caption line length <output>${S.captionChars}</output></b>
          <input type="range" min="24" max="80" step="2" value="${S.captionChars}" data-k="captionChars"></label>
        <label class="a11y-range"><b>Text size <output>${Math.round(S.textScale * 100)}%</output></b>
          <input type="range" min="1" max="1.5" step="0.25" value="${S.textScale}" data-k="textScale" aria-valuetext="${Math.round(S.textScale * 100)} percent"></label>
        ${sw("dyslexia", "Easy-read font", "Atkinson Hyperlegible, wider spacing")}`,
      display: `${PA ? seg("theme", "Theme", [["system", "System"], ["light", "Light"], ["dark", "Dark"]]) : ""}
        ${sw("contrast", "High contrast", "Black, white and yellow")}
        ${sw("reducedMotion", "Less motion", "No flying or spinning")}
        ${PA ? seg("graphics", "Graphics", [["high", "High"], ["low", "Low"]]) : ""}
        <button type="button" class="btn-quiet a11y-vbar" data-vbar-reset>Reset voice bar position</button>`,
      cadets: PA ? `<ul class="set-cadets">${PA.listProfiles().map(p => `<li class="${p.active ? "is-active" : ""}">
          <span class="set-av" aria-hidden="true">${escH((p.callsign || "?").slice(0, 1).toUpperCase())}</span>
          <span class="set-cn"><b>${escH(p.callsign || "New cadet")}</b><small>${p.qualified ? "Qualified" : `${p.patches} of ${O.patchTotal || 9} patches`}</small></span>
          ${p.active ? `<span class="set-tag">Playing</span>` : `<button type="button" class="btn" data-prof-switch="${p.id}">Switch</button>`}</li>`).join("")}</ul>
        ${PA.listProfiles().length < 6 ? `<button type="button" class="btn" data-prof-add>Add a cadet</button>` : `<p class="set-note">Up to 6 cadets.</p>`}
        ${O.crew ? `<label class="a11y-sw"><input type="checkbox" data-crew-sw ${O.crew.state.on ? "checked" : ""} ${PA.listProfiles().length < 2 ? "disabled" : ""}><span><b>Crew rotation</b><small>${PA.listProfiles().length < 2 ? "Add a second cadet to take turns." : "Cadets on this computer take turns. Tap a name to pass the turn. Hold Space or the mic to talk."}</small></span></label>` : ""}
        ${seg("level", "Level", [["cadet", "Cadet · 7–9"], ["commander", "Commander · 10–12"], ["engineer", "Engineer · real units"]])}
        <p class="set-help rs-link">Reset the app or erase progress? <button type="button" class="btn-link" data-sec-go="grownups">${escH(GROWNUPS.title)}</button></p>` : "",
      help: `<p class="a11y-noaudio" role="note">${noAudio.innerHTML}</p>
        <button type="button" class="btn" data-cabin-tour>${escH(TOUR.replay)}</button>
        <button type="button" class="btn" data-help-video="moon_base_6mo">${escH(MOON_BASE.help)}</button>
        <details class="a11y-transcript"><summary>Transcript</summary><ol id="a11yTranscript"></ol></details>
        <details><summary>Voice and keyboard commands</summary><ul class="a11y-help">
          <li>“Where am I?” · “What can I do?” · “Press Next” · “Option 2”</li>
          <li>“Faster” · “Slower” · “Say that again” · “Bigger text” · “High contrast”</li>
          <li>“Move the voice bar to the top” · “Reset the voice bar”</li>
          <li>Keys: <kbd>Tab</kbd> move · <kbd>Enter</kbd> press · <kbd>Esc</kbd> close · <kbd>Alt</kbd>+<kbd>A</kbd> settings · <kbd>Alt</kbd>+<kbd>W</kbd> where am I · <kbd>Alt</kbd>+<kbd>P</kbd> pick a place</li></ul></details>
        ${places.length ? `<details class="a11y-place"><summary>Pick a place on the Moon</summary>
          <span><select id="a11yPlace" aria-label="Place on the Moon">${places.filter(p => p.name).sort((a, b) => a.name.localeCompare(b.name)).map(p => `<option value="${p.id}">${escH(p.name)}</option>`).join("")}</select>
          <button type="button" class="pill" id="a11yPlaceGo">Go there</button></span></details>` : ""}
        <p class="a11y-note">Saved on this device only.</p>`,
      grownups: "x",   // drawn below, once the grown-up extras are known
    };
    // Sections other modules add (e.g. "Camera & gestures" from the gestures agent): window.__outpost.settingsSections =
    // [{id, title, after?, html() → string, bind?(el)}]. A section with nothing to show is not listed.
    const extraSecs = (O.settingsSections || []).filter(x => x && x.id && x.title && typeof x.html === "function");
    extraSecs.forEach(x => { try { body[x.id] = x.html(); } catch (e) { body[x.id] = ""; } });
    const order = SECTIONS.slice(); extraSecs.forEach(x => { const k = order.findIndex(s => s[0] === (x.after || "listen")); order.splice(k < 0 ? order.length - 1 : k + 1, 0, [x.id, x.title]); });
    { const r = order.findIndex(s => s[0] === "grownups"); if (r >= 0 && r !== order.length - 1) order.push(order.splice(r, 1)[0]); }   // For grown-ups stays last
    // [0.4.1] the grown-up parts: Reset, then the grown-up extras (Videos, diagnostics, learning), then Reset my patches.
    // An open confirm view stands alone (nothing else to press by mistake next to it).
    const guExtras = extraSecs.filter(x => x.grownup && body[x.id]);
    const parts = resetView ? [{ id: "reset", title: "Reset", html: confirmHtml(resetView) }]
      : [...guExtras.filter(x => x.first).map(x => ({ id: x.id, title: x.title, html: body[x.id] })), { id: "reset", title: "Reset", html: zoneHtml() }, ...guExtras.filter(x => !x.first).map(x => ({ id: x.id, title: x.title, html: body[x.id] })),   // `first`: Progress opens the section
        ...(PA ? [{ id: "patches", title: GROWNUPS.patches, html: `${holdButtonHtml(GROWNUPS.patches, "data-prof-reset")}<small class="rs-note">${escH(GROWNUPS.patchesNote)}</small>` }] : [])];
    body.grownups = grownupsHtml({ open: guOpen, parts, esc: escH });
    const shown = order.filter(([id]) => body[id] && !guExtras.some(x => x.id === id));
    if (!shown.some(([id]) => id === section)) section = shown[0][0];
    panel.innerHTML = `
      <header><h2 id="a11yTitle">Settings</h2><button type="button" class="x" data-close aria-label="Close settings">&times;</button></header>
      <div class="set-body">
        <nav class="set-nav" aria-label="Settings sections">${shown.map(([id, t]) => `<button type="button" data-sec="${id}" aria-current="${id === section ? "page" : "false"}">${escH(t)}</button>`).join("")}</nav>
        <section class="set-sec" aria-labelledby="set-h">
          <h3 id="set-h">${escH(order.find(s => s[0] === section)[1])}</h3>${body[section]}</section>
      </div>`;
    fillTranscript();
    unbindReset(); unbindReset = () => {};
    const undo = [];
    if (section === "grownups") {
      const gate = panel.querySelector("[data-gu-open]");
      // [D4] the safety notes waiting for a grown-up: a count on the gate (never what they are, until the hold)
      if (gate) safetyNotes().then(n => { const el = panel.querySelector("[data-gu-notes]"); if (el && n) { el.textContent = GROWNUPS.notes(n); el.hidden = false; } });
      // the grown-up gate: the shared 3-second hold (a click or a tap does nothing); open until Settings closes
      if (gate) { const h = bindHold(gate, { onFire: () => { guOpen = true; renderPanel(); const f = panel.querySelector(".gu-part button"); if (f) f.focus({ preventScroll: true }); } }); undo.push(() => h.destroy()); }
      // "Reset my patches": its own 3-second hold too
      const pr = panel.querySelector("[data-prof-reset]");
      if (pr && PA) { const h = bindHold(pr, { onFire: () => PA.resetProgress() }); undo.push(() => h.destroy()); }
      if (guOpen && resetView) undo.push(bindConfirm(panel, { onCancel: () => { const was = resetView; resetView = null; renderPanel(); const b = panel.querySelector(`[data-reset-open="${was}"]`); if (b) b.focus(); } }));
      if (guOpen && !resetView) guExtras.forEach(x => { const el = panel.querySelector(`.gu-part[data-gu="${x.id}"]`); if (el && x.bind) { try { const r = x.bind(el); if (r && r.destroy) undo.push(() => r.destroy()); } catch (e) { /* its own bug */ } } });
    }
    unbindReset = () => undo.forEach(f => f());
    const xs = extraSecs.find(x => x.id === section && !x.grownup); if (xs && xs.bind) { try { xs.bind(panel.querySelector(".set-sec")); } catch (e) { /* its own bug */ } }
    // Settings → Voice: exactly two engines. "Your computer's voice" picks the OS voice by itself (Siri on a Mac, the
    // best WinRT voice on Windows): no voice list. "Steer TTS (Whissle)" shows Steer's voices, with previews.
    if (section === "voice" && PA) Promise.resolve(PA.steerState ? PA.steerState() : { state: "off" }).then(async (steer) => {
      const box = panel.querySelector("#setVoices"); if (!box) return;
      const steerOn = PA.value.engine === "steer" && steer.state === "ready";
      const engineHtml = engineChoiceHtml(PA.value, steer, escH);
      clearTimeout(steerPoll);
      if (steer.state === "downloading") steerPoll = setTimeout(() => { if (!panel.hidden && section === "voice") renderPanel(); }, 3000);
      const ap = PA.applied;
      const mood = ap && ap.expressiveness != null ? ` · ${ap.expressiveness <= 0.25 ? "calm" : ap.expressiveness >= 0.75 ? "lively" : "balanced"}` : "";
      if (!steerOn) {
        box.innerHTML = `${engineHtml}
        <label class="a11y-sw"><input type="checkbox" data-pb="pack" ${PA.value.pack !== false ? "checked" : ""}><span><b>Use the recorded guide voice for story lines</b><small>Lessons, the tour and mission lines play a studio recording. Only at normal speed.</small></span></label>
        ${moreVoicesHint() ? `<p class="set-help">${escH(moreVoicesHint())}</p>` : ""}
        ${ap ? `<p class="set-help set-applied" role="status">In use: your computer's voice${mood}</p>` : ""}`;
        bindSteer(box); return;
      }
      const vs = await PA.loadSteerVoices();
      const vname = id => ((vs.find(v => v.id === id) || vs[0] || {}).name) || "Aurora";
      box.innerHTML = `${engineHtml}${vs.length ? `<fieldset class="set-seg" data-steer-voices><legend>Steer voice</legend><div class="set-vlist">${vs.map((v, i) => `
        <label class="set-voice"><input type="radio" name="p-voice" data-p="steer_voice" value="${escH(v.id)}" ${PA.value.steer_voice === v.id || (!PA.value.steer_voice && i === 0) ? "checked" : ""}>
          <span><b>${escH(v.name)}</b><small>${escH(v.desc || "")}</small></span>
          ${v.preview_url ? `<button type="button" class="btn-icon" data-preview="${escH(v.id)}" aria-label="Hear ${escH(v.name)}"><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4.5v15l12-7.5Z"/></svg></button>` : ""}</label>`).join("")}</div></fieldset>` : ""}
        <p class="set-help">With Steer every line is spoken live in the Steer voice.</p>
        ${ap ? `<p class="set-help set-applied" role="status">In use: Steer · ${escH(vname(PA.value.steer_voice || ""))}${mood}</p>` : ""}`;
      box.querySelectorAll("[data-preview]").forEach(b => b.onclick = e => { e.preventDefault(); PA.previewVoice(vs.find(v => v.id === b.dataset.preview)); });
      bindSteer(box);
    });
    function bindSteer(box) {
      const g = box.querySelector("[data-get-steer]");
      if (g) g.onclick = async e => { e.preventDefault(); g.disabled = true; g.textContent = "Downloading Steer voice…"; await PA.requestSteer(); renderPanel(); };
    }
  }
  function open(v = panel.hidden) {
    if (v) {
      const about = document.getElementById("about"); if (about && about.open) about.close();   // one sheet at a time
      // [robustness] the video overlay is a native modal <dialog> (the top layer): Settings opened over it (by voice)
      // sat underneath, inert, and the kid could not touch it. One sheet at a time: the video closes first.
      if (O.video && O.video.isOpen && O.video.isOpen()) O.video.command("stop");
      try { dispatchEvent(new CustomEvent("outpost:modal-open", { detail: { kind: "settings" } })); } catch (e) { /* the calibration steps aside */ }
      renderPanel(); panel.hidden = false; scrim.hidden = false; btn.setAttribute("aria-expanded", "true");
      { const f = panel.querySelector('.set-nav [aria-current="page"]') || panel.querySelector(".set-nav button, input"); if (f) f.focus(); }
    } else { panel.hidden = true; scrim.hidden = true; resetArmed = false; guOpen = false; resetView = null; btn.setAttribute("aria-expanded", "false"); btn.focus(); }
  }
  scrim.addEventListener("click", () => open(false));
  // [robustness] Settings is modal: while it is up, gestures / keys / the controller move and press inside it, and screen
  // intents (next, yes / no, pick, the clock, the cabin) never reach the screen underneath. A swipe "next" used to
  // advance the lesson behind the sheet and pull focus out of it. Swipe right ("Go back") closes it. Voice still
  // navigates (the router closes nothing it does not own; a screen change is what the kid asked for).
  const IN_SETTINGS = new Set(["move", "select", "point", "back", "stop", "mute", "mute_sound", "unmute_sound", "captions", "mic", "help",
    "settings", "a11y", "repeat", "focus_input"]);
  onIntent("*", (a, ev) => {
    if (ev.source === "voice" || ev.source === "typed" || ev.source === "system") return false;
    const calib = !!document.querySelector(".gx-calib");   // the gestures calibration is modal the same way
    if (panel.hidden && !calib) return false;
    if (ev.name === "prev" && !panel.hidden) { open(false); return true; }
    return !IN_SETTINGS.has(ev.name);
  }, { priority: 90 });
  // a native modal (the video overlay) opening on top: close Settings, so nothing sits inert underneath it
  addEventListener("outpost:modal-open", e => { if (e.detail && e.detail.kind === "settings") return; if (!panel.hidden) { panel.hidden = true; scrim.hidden = true; resetArmed = false; guOpen = false; resetView = null; btn.setAttribute("aria-expanded", "false"); } });
  addEventListener("outpost:voice-missing", () => { section = "voice"; if (panel.hidden) open(true); else renderPanel(); });
  // [courses] the switcher's "Get more courses": For grown-ups (behind the hold), where Course storage lives
  addEventListener("outpost:course-storage", () => { section = "grownups"; resetView = null; if (panel.hidden) open(true); else renderPanel(); { const b = panel.querySelector('[data-crs-act="get"]') || panel.querySelector("[data-gu-open]"); if (b) b.focus(); } });
  // the session's echo of what it applied: refresh the Voice section's "In use" line
  addEventListener("outpost:prefs-applied", () => { if (!panel.hidden && section === "voice") { const f = document.activeElement && document.activeElement.dataset; renderPanel(); if (f && f.p) { const e = panel.querySelector(`[data-p="${f.p}"]:checked, input[type=range][data-p="${f.p}"]`); if (e) e.focus(); } } });
  btn.addEventListener("click", () => open());
  panel.addEventListener("click", e => {
    const PA = O.prefsApi;
    if (e.target.closest("[data-close]")) open(false);
    const go = e.target.closest("[data-sec-go]"); if (go) { section = go.dataset.secGo; resetView = null; renderPanel(); const f = panel.querySelector(`[data-sec="${section}"]`); if (f) f.focus(); return; }
    const ro = e.target.closest("[data-reset-open]"); if (ro) { resetView = ro.dataset.resetOpen; renderPanel(); return; }
    const s = e.target.closest("[data-sec]"); if (s) { section = s.dataset.sec; resetArmed = false; resetView = null; renderPanel(); const f = panel.querySelector(`[data-sec="${section}"]`); if (f) f.focus(); }
    const vb = e.target.closest("[data-vbar-reset]");
    if (vb && O.voiceBar) { O.voiceBar.reset(); vb.textContent = "Voice bar is back at the bottom"; vb.disabled = true;   // [audit2] it gave no sign it worked
      setTimeout(() => { if (vb.isConnected) { vb.textContent = "Reset voice bar position"; vb.disabled = false; } }, 2200); }
    // [vidfix] data-help-video, a BUTTON inside the panel: the old closest on data-video matched <body data-video>
    // (main.js marks an open video overlay on body), so after any video every click in Settings (the Camera & gestures
    // switch) "found" the body and wrote "Needs internet…" into body.textContent: the whole app gone, unstyled, stuck.
    const vb2 = e.target.closest("button[data-help-video]");
    if (vb2 && panel.contains(vb2)) {   // a NASA video from Help (the first-mission Moon Base video); offline or no player: say so on the button
      const id = vb2.dataset.helpVideo;
      isAvailable(id).then(st => {
        if (st !== "offline") { open(false); openVideo(id, { context: "help" }); return; }
        vb2.textContent = offlineLine(); vb2.disabled = true;
      });
    }
    if (e.target.closest("[data-cabin-tour]")) { open(false); if (setMode && document.body.dataset.mode !== "mission") setMode("mission"); dispatchEvent(new CustomEvent("outpost:tour")); }
    if (e.target.id === "a11yPlaceGo") pickPlace(panel.querySelector("#a11yPlace").value);
    const sw = e.target.closest("[data-prof-switch]"); if (sw && PA) PA.switchProfile(sw.dataset.profSwitch);
    if (e.target.closest("[data-prof-add]") && PA) PA.addProfile();
    const tl = e.target.closest("[data-turnlog-clear]");
    if (tl) { fetch("/api/turnlog", { method: "DELETE" }).then(() => { tl.textContent = "Deleted"; tl.disabled = true; }).catch(() => { tl.textContent = "Couldn't delete. Try again."; }); }
    // [0.4] "Reset my patches" is a 3-second hold (bindHold, bound in renderPanel): a click or a tap never clears.
    // [0.4.1] It lives in For grown-ups, behind the gate's own hold.
  });
  panel.addEventListener("change", e => {
    const t = e.target;
    if ("crewSw" in t.dataset && O.crew) { O.crew.set(t.checked); renderPanel(); const again = panel.querySelector("[data-crew-sw]"); if (again) again.focus(); return; }   // [D3] crew rotation
    if (t.dataset.pb && O.prefsApi) { O.prefsApi.update({ [t.dataset.pb]: t.checked }); if (t.dataset.pb === "improve") { renderPanel(); const again = panel.querySelector(`[data-pb="improve"]`); if (again) again.focus(); } return; }   // a boolean pref
    if (t.dataset.p && O.prefsApi) {   // Settings v1 prefs (prefs.js)
      const k = t.dataset.p, v = t.type === "range" ? +t.value : t.value;
      O.prefsApi.update({ [k]: v });
      if (t.type === "range") { const out = t.closest("label").querySelector("output"); renderPanel(); const again = panel.querySelector(`[data-p="${k}"]`); if (again) again.focus(); void out; }
      else if (k === "listen" || k === "engine") { renderPanel(); const again = panel.querySelector(`[data-p="${k}"]:checked`); if (again) again.focus(); }
      return;
    }
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

  function set(patch) { S = saveSettings(store, { ...S, ...patch }); apply(); dispatchEvent(new CustomEvent("outpost:a11y", { detail: S })); }
  function apply() {
    root.dataset.contrast = S.contrast ? "high" : "";
    root.dataset.dyslexia = S.dyslexia ? "1" : "";
    root.dataset.motion = S.reducedMotion || (matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches) ? "reduce" : "";
    root.dataset.captions = S.captions ? "on" : "off";
    root.style.setProperty("--a11y-zoom", String(S.textScale));
    root.dataset.textScale = S.textScale > 1 ? "big" : "";
    if (S.dyslexia && !apply.font) {   // easy-read font: bundled with the app (offline), loaded only when chosen
      apply.font = Promise.all([import("@fontsource/atkinson-hyperlegible/400.css"), import("@fontsource/atkinson-hyperlegible/700.css")]).catch(() => {});
    }
    if (floor) floor.setSpeed(S.speed);
    const c = floor && floor.crewEl; if (c) { c.playbackRate = S.speed; c.preservesPitch = true; }
  }
  apply();
  // [qa] the OS "reduce motion" switch can change while the app is open
  try { matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", apply); } catch (e) { /* old engine */ }
  // Crew audio: the same speed as a playbackRate (it's a recording, so it can't be re-rendered).
  if (floor) floor.on("playback", e => { if (e.kind === "crew" && e.state === "start" && floor.crewEl) { floor.crewEl.playbackRate = S.speed; floor.crewEl.preservesPitch = true; } });

  // ---- transcript ----
  function fillTranscript() {
    const ol = panel.querySelector("#a11yTranscript"); if (!ol) return;
    ol.innerHTML = (O.transcript || []).slice(-60).map(e => `<li><b>${escH(e.who === "crew" ? "Crew" : e.who === "capcom" ? roleName("capcom", "CAPCOM") : e.who === "kid" ? "You" : e.who === "describe" ? "Description" : "Guide")}:</b> ${escH(e.who === "kid" ? maskProfanity(e.text) : e.text)}</li>`).join("");
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
    // an alert is news, not a label: it leaves the live region once read, so a screen reader never meets a storm alert
    // from Lesson 5 in the Mission (novice playtest 2026-11-16 #31)
    if (alert) { clearTimeout(describe.at); describe.at = setTimeout(() => { if (alertLive.textContent === text) alertLive.textContent = ""; }, 8000); }
    if (S.describe && !quiet && say) say(text, { describe: true });   // spoken only in audio-description mode
    if (O.captions && S.describe) O.captions.log("describe", text);
  }

  // Visual moves → descriptions. The globe is wrapped once (fly / show a feature).
  function wrapGlobe(globe, placeById) {
    if (!globe || globe.__a11y) return; globe.__a11y = true;
    const sf = globe.showFeature.bind(globe);
    const turns = () => (globe.bodyName && globe.bodyName !== "Moon" ? `${globe.bodyName} turns` : "The Moon turns");   // [courses]
    globe.showFeature = (f, ...a) => { if (f && f.name) describe(`${turns()} to ${f.name}.`); return sf(f, ...a); };
    const fly = globe.flyTo.bind(globe);
    globe.flyTo = (lat, lon, ...a) => { describe(`${turns()} to ${Math.abs(Math.round(lat))}° ${lat >= 0 ? "north" : "south"}, ${Math.abs(Math.round(lon))}° ${lon >= 0 ? "east" : "west"}.`); return fly(lat, lon, ...a); };
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
      // the flash ends with its animation (with reduced motion `is-on` is a static border that would otherwise stay)
      clearTimeout(visualAlert.f); visualAlert.f = setTimeout(() => flash.classList.remove("is-on"), 1800);
      vbanner.innerHTML = `<span class="a11y-vb-icon" aria-hidden="true">${icon("warning", { size: 18 })}</span><span>${escH(text.slice(0, 140))}</span>`;
      vbanner.hidden = false; clearTimeout(visualAlert.t); visualAlert.t = setTimeout(() => { vbanner.hidden = true; }, 5000);
    }
    if (S.vibrate && navigator.vibrate) { try { navigator.vibrate([180, 80, 180]); } catch (e) { /* not allowed */ } }
    describe(text, { alert: true, quiet: true });
  }

  /** QA-68: an alert's flash and banner belong to the screen that raised it: a mode switch ends them. */
  function clearAlerts() { clearTimeout(visualAlert.t); clearTimeout(visualAlert.f); flash.classList.remove("is-on"); vbanner.hidden = true; alertLive.textContent = ""; }
  new MutationObserver(clearAlerts).observe(document.body, { attributes: true, attributeFilter: ["data-mode"] });

  // ---- screen state on request ----
  function where() {
    const mode = document.body.dataset.mode, M = { academy: "Flight School", mission: "Mission", cadet: "the Library" };   // [qa] the tab names
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
    const h = O.help && O.help();   // a screen that knows what the kid should do says that, not a list of buttons
    if (h && typeof h === "string") return h;
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
    // a screen's help may be async (a Flight School step asks the server for the next hint rung)
    const replyAsync = (h, orElse) => (h && typeof h.then === "function" ? h.then(t => reply(t || orElse())) : reply(h || orElse()));
    switch (c.cmd) {
      case "where": reply(where()); break;
      case "options": reply(options()); break;
      case "help": await replyAsync(O.help && O.help(), options); break;
      case "confused": await replyAsync((O.explain && O.explain()) || (O.help && O.help()), options); break;
      case "speed": set({ speed: c.arg === 0 ? 1 : stepSpeed(S.speed, c.arg) }); reply(`Voice speed ${S.speed} times.`); break;
      case "text": set({ textScale: Math.max(1, Math.min(1.5, S.textScale + 0.25 * c.arg)) }); reply(`Text size ${Math.round(S.textScale * 100)} percent.`); break;
      case "contrast": set({ contrast: c.arg }); reply(`High contrast ${c.arg ? "on" : "off"}.`); break;
      case "describe": set({ describe: c.arg }); reply(`Audio description ${c.arg ? "on" : "off"}.`); break;
      case "repeat": { const last = (O.transcript || []).filter(e => e.who !== "describe" && e.who !== "kid").slice(-1)[0]; if (last && say) say(last.text, {}); break; }
      case "panel": open(true); break;
      // voice opens the Reset panel itself (both options); it never confirms. The option asked for gets focus.
      // [0.4.1] Reset lives in For grown-ups: voice opens the section; behind the gate unless a grown-up already opened it
      case "reset": section = "grownups"; resetView = null; if (panel.hidden) open(true); else { try { dispatchEvent(new CustomEvent("outpost:modal-open", { detail: { kind: "settings" } })); } catch (e) { /* */ } renderPanel(); } { const b = panel.querySelector(`[data-reset-open="${c.arg}"]`) || panel.querySelector("[data-gu-open]"); if (b) b.focus(); } reply(guOpen ? GROWNUPS.sayOpen : GROWNUPS.sayLocked); break;
      case "course": { const cs = window.__outpost && window.__outpost.courseSwitch; if (cs && cs.visible()) { cs.open(); reply("Pick a course."); } else reply("The Moon is the only course on this computer."); break; }
      case "network": section = "grownups"; resetView = null; if (panel.hidden) open(true); else { try { dispatchEvent(new CustomEvent("outpost:modal-open", { detail: { kind: "settings" } })); } catch (e) { /* */ } renderPanel(); } { const b = panel.querySelector("[data-nw-sw]:not([disabled])") || panel.querySelector("[data-gu-open]"); if (b) b.focus(); } reply(guOpen ? GROWNUPS.sayNetOpen : GROWNUPS.sayNetLocked); break;
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
    else if (k === "p" || e.code === "KeyP") { e.preventDefault(); section = "help"; open(true); /* [qa] the picker lives in Help */ const s = panel.querySelector("#a11yPlace"); if (s) { s.closest("details").open = true; s.focus(); } }
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
