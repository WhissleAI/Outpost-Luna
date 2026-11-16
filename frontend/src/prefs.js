// Settings v1 beyond accessibility (a11y.js keeps its own keys): voice, sound, listening, display, level, and cadet
// profiles. Everything is stored on this device (localStorage, try/catch) per cadet profile. The server gets only what
// it needs to steer the session: {t:"prefs", type:"prefs", voice, rate, expressiveness, filter, level, listen} on the
// session socket (main.js sends it whenever a pref changes).
//
// Profiles: the active cadet's data lives in the usual keys; switching snapshots them into the profile list, loads
// the other cadet's, and reloads the app (so every module starts clean).

export const PREF_DEFAULTS = Object.freeze({
  voice: "",                 // always "": the computer's voice is picked by the OS (Siri / the best Windows voice); no list
  voice_all: false,          // retired (Houston is relayed by CAPCOM); kept false for old saved prefs
  engine: "os",              // Settings → Voice: "os" (the computer's own voice, default) | "steer" (Steer TTS, Whissle)
  steer_voice: "",           // with engine "steer": "" = Aurora (the default Steer voice); else an id from GET /api/voices?engine=steer
  pack: true,                // "Use the recorded guide voice for story lines": the voice pack (docs/VOICE_PACK.md)
  expressiveness: 0.5,       // 0 calm … 1 lively
  volume: 1,                 // master, 0–2 (1 = 100% = the −14 LUFS target): sent to the server; crew audio follows it here
  alarms: 1,                 // alarm chimes
  listen: "handsfree",       // "handsfree" | "ptt" (hold Space / the mic to talk)
  filter: "normal",          // background-voice filter: "relaxed" | "normal" | "strict"
  theme: "system",           // "system" | "light" | "dark"
  graphics: "high",          // "high" | "low"
  level: "cadet",            // "cadet" (7–9) | "commander" (10–12) | "engineer" (Commander in real units, docs/PHYSICS.md)
  improve: false,            // "Help improve the voice guide": the on-device, text-only turn log (docs/DIRECTOR_LOOP.md). Off by default.
  muted: false,              // the top bar's Mute: every sound off, captions and text stay (mute.js); output only, never the mic
  update_check: false,       // Settings → App version → "Check for updates automatically" (app_update_ui.js). Off by default.
});
/** Settings → Voice: where a parent downloads clearer voices on this OS (the app speaks with the OS's own offline
 *  voices, docs/VOICES.md). "" on any other OS. */
export function moreVoicesHint(ua = typeof navigator !== "undefined" ? navigator.userAgent : "") {
  if (/Windows/.test(ua)) return "Parents can download clearer Windows voices: Settings → Time & language → Speech → Manage voices.";
  if (/Mac OS X|Macintosh/.test(ua)) return "Parents can download clearer macOS voices: System Settings → Accessibility → Spoken Content → System voice → Manage Voices.";
  return "";
}
/** Settings → Voice, the engine choice: the computer's voice (default) or Steer TTS. Steer is bundled on 0.1.x; on the
 *  0.3 line it is a first-run download (steer.downloadable): until it is ready its option is disabled, with a "Get"
 *  button or "Downloading Steer voice…". Pure. */
export function engineChoiceHtml(P, steer, esc = x => String(x)) {
  const st = (steer && steer.state) || "missing", ready = st === "ready";
  const note = ready ? "Whissle's expressive voice, with exact captions. Pick a voice below." : st === "downloading" ? "Downloading Steer voice…"
    : st === "missing" && steer && steer.downloadable ? "Downloads when you pick it" : "Not available on this computer";
  const opt = (v, label, small, on, dis) => `<label class="set-voice"><input type="radio" name="p-engine" data-p="engine" value="${v}" ${on ? "checked" : ""} ${dis ? "disabled" : ""}>
    <span><b>${esc(label)}</b><small>${esc(small)}</small></span></label>`;
  return `<fieldset class="set-seg" data-engine-state="${esc(st)}"><legend>Voice</legend><div class="set-vlist">
    ${opt("os", "Your computer's voice", "Siri on a Mac, the best Windows voice on a PC", P.engine !== "steer" || !ready, false)}
    ${opt("steer", "Steer TTS (Whissle)", note, P.engine === "steer" && ready, !ready)}
    ${st === "missing" && steer && steer.downloadable ? `<button type="button" class="btn-quiet" data-get-steer>Get the Steer voice (13 MB)</button>` : ""}</div></fieldset>`;
}
const KEY = "outpost-prefs";
const PROFILES = "outpost-profiles";
/** The keys that belong to one cadet. */
export const PROFILE_KEYS = ["outpost-callsign", "atm-academy", "outpost-a11y", KEY, "outpost-voicebar", "atm-theme", "outpost-gestures", "outpost-tier"];   // [qa] + camera and mission tier

const store = (() => { try { return window.localStorage; } catch (e) { return null; } })();
const get = k => { try { return store ? store.getItem(k) : null; } catch (e) { return null; } };
const set = (k, v) => { try { if (!store) return; if (v == null) store.removeItem(k); else store.setItem(k, v); } catch (e) { /* private mode */ } };

/** Any stored object → valid prefs (unknown keys dropped, values clamped to their options). */
export function normalizePrefs(x) {
  const o = { ...PREF_DEFAULTS }, s = x && typeof x === "object" ? x : {};
  const num = (v, lo, hi) => (isFinite(+v) ? Math.max(lo, Math.min(hi, +v)) : null);
  if (typeof s.voice === "string") o.voice = s.voice.slice(0, 64);
  [["expressiveness", 0, 1], ["volume", 0, 2], ["alarms", 0, 1]].forEach(([k, lo, hi]) => { const v = num(s[k], lo, hi); if (v != null) o[k] = v; });
  const pick = (k, opts) => { if (opts.includes(s[k])) o[k] = s[k]; };
  pick("listen", ["handsfree", "ptt"]); pick("filter", ["relaxed", "normal", "strict"]); pick("theme", ["system", "light", "dark"]);
  pick("graphics", ["high", "low"]); pick("level", ["cadet", "commander", "engineer"]);
  o.voice = ""; o.voice_all = false;   // the OS voice list and "use this voice for everyone" are gone: the OS picks
  pick("engine", ["os", "steer"]);
  if (typeof s.steer_voice === "string") o.steer_voice = s.steer_voice.slice(0, 32);
  o.pack = s.pack !== false;          // on unless explicitly turned off
  o.improve = s.improve === true;     // opt-in only: anything but an explicit true is off
  o.muted = s.muted === true;
  o.update_check = s.update_check === true;   // opt-in only, like improve
  return o;
}

export function createPrefs({ globe = null } = {}) {
  let P = (() => { try { return normalizePrefs(JSON.parse(get(KEY) || "null")); } catch (e) { return { ...PREF_DEFAULTS }; } })();
  const subs = new Set();
  const root = document.documentElement;

  // ---- effects ----
  // Master volume: the server renders every voice line at it (prefs.volume), so the guide's <audio> stays at 1; the
  // crew audio (player.js, Web Audio) and the chimes (sound.js) read window.__outpost.levels.master.
  function applyTheme() {
    if (P.theme === "system") delete root.dataset.theme; else root.dataset.theme = P.theme;
    set("atm-theme", P.theme === "system" ? null : P.theme);
    const b = document.getElementById("themeBtn"), mq = window.matchMedia && matchMedia("(prefers-color-scheme: dark)");
    const dark = (root.dataset.theme || (mq && mq.matches ? "dark" : "light")) === "dark";
    if (b) { b.dataset.mode = dark ? "dark" : "light"; b.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode"); }
  }
  function apply(changed) {
    const O = (window.__outpost = window.__outpost || {});
    O.prefs = P; O.levels = { master: P.muted ? 0 : P.volume, alarms: P.alarms, muted: !!P.muted };   // Mute: Web Audio and the browser voice at 0
    root.dataset.listen = P.listen; root.dataset.graphics = P.graphics;
    if (changed ? "theme" in changed : P.theme !== "system") applyTheme();
    if (globe && globe.setQuality && (!changed || "graphics" in changed)) globe.setQuality(P.graphics);
  }
  apply();
  // the top-bar theme button flips light/dark: keep the pref in step
  const tb = document.getElementById("themeBtn");
  if (tb) tb.addEventListener("click", () => setTimeout(() => { P = { ...P, theme: root.dataset.theme === "dark" ? "dark" : "light" }; set(KEY, JSON.stringify(P)); subs.forEach(f => f(P, { theme: P.theme })); }, 0));

  function update(patch) {
    P = normalizePrefs({ ...P, ...patch }); set(KEY, JSON.stringify(P));
    apply(patch); subs.forEach(f => f(P, patch));
    dispatchEvent(new CustomEvent("outpost:prefs", { detail: P }));
  }
  /** What the session needs (main.js sends it on the socket). */
  const wire = (rate = 1) => ({ t: "prefs", type: "prefs", voice: P.voice || null, voice_all: P.voice_all, pack: P.pack !== false,
    engine: P.engine === "steer" ? "steer" : "os", steer_voice: P.steer_voice || null, rate: Math.max(0.6, Math.min(1.6, rate)),
    volume: P.volume, expressiveness: P.expressiveness, filter: P.filter, level: P.level, listen: P.listen, improve: P.improve === true });
  /** What the server applied ({t:"prefs", applied}); Settings shows it. */
  let applied = null;
  const setApplied = a => { applied = a || null; dispatchEvent(new CustomEvent("outpost:prefs-applied", { detail: applied })); };

  // ---- voices (GET /api/voices → [{id, name, desc, preview_url}]); none = only the default voice, no picker ----
  let voices = null;
  async function loadVoices() {
    if (voices) return voices;
    try { const r = await fetch("/api/voices"); voices = r.ok ? (await r.json()) : []; if (!Array.isArray(voices)) voices = voices.voices || []; }
    catch (e) { voices = []; }
    try { (window.__outpost = window.__outpost || {}).defaultVoice = (voices[0] && voices[0].id) || ""; } catch (e) { /* tests */ }
    return voices;
  }
  loadVoices().then(vs => {
    if (P.voice && vs.length && !vs.some(v => v.id === P.voice)) { update({ voice: "" }); dispatchEvent(new CustomEvent("outpost:voice-missing")); }
  });
  // ---- Steer TTS, the optional engine (GET /api/tts/engines, GET /api/voices?engine=steer, POST /api/tts/engines/steer) ----
  let steerVoices = null;
  async function loadSteerVoices() {
    if (steerVoices && steerVoices.length) return steerVoices;
    try { const r = await fetch("/api/voices?engine=steer"); steerVoices = r.ok ? (await r.json()) : []; } catch (e) { steerVoices = []; }
    return Array.isArray(steerVoices) ? steerVoices : [];
  }
  async function steerState() {
    try { const r = await fetch("/api/tts/engines"); return r.ok ? ((await r.json()).steer || { state: "missing" }) : { state: "missing" }; }
    catch (e) { return { state: "missing" }; }
  }
  /** The kid asked for Steer: the desktop downloads it now (the backend drops a request file for the main process). */
  async function requestSteer() {
    try { const r = await fetch("/api/tts/engines/steer", { method: "POST" }); return r.ok ? await r.json() : { state: "missing" }; }
    catch (e) { return { state: "missing" }; }
  }
  let preview = null;
  function previewVoice(v) {
    if (!v || !v.preview_url) return;
    try { if (preview) preview.pause(); preview = new Audio(v.preview_url); preview.volume = Math.min(1, P.volume); /* [qa] the Volume setting */ preview.play().catch(() => {}); } catch (e) { /* no audio */ }
  }

  // ---- cadet profiles ----
  const snapshot = () => Object.fromEntries(PROFILE_KEYS.map(k => [k, get(k)]));
  const restore = data => PROFILE_KEYS.forEach(k => set(k, data && data[k] != null ? data[k] : null));
  function profiles() {
    let s; try { s = JSON.parse(get(PROFILES) || "null"); } catch (e) { s = null; }
    if (!s || !Array.isArray(s.list) || !s.list.length) { s = { active: "p1", list: [{ id: "p1", data: null }] }; set(PROFILES, JSON.stringify(s)); }
    return s;
  }
  const summary = data => {
    const d = data || {}; let prog = { badges: [] }; try { prog = JSON.parse(d["atm-academy"] || "null") || prog; } catch (e) { /* none */ }
    return { callsign: d["outpost-callsign"] || "", patches: (prog.badges || []).length, qualified: !!prog.qualified };
  };
  /** [{id, callsign, patches, qualified, active}] */
  function listProfiles() {
    const s = profiles();
    return s.list.map(p => ({ id: p.id, active: p.id === s.active, ...summary(p.id === s.active ? snapshot() : p.data) }));
  }
  function switchProfile(id) {
    const s = profiles(); if (id === s.active || !s.list.some(p => p.id === id)) return;
    s.list = s.list.map(p => (p.id === s.active ? { ...p, data: snapshot() } : p));
    const to = s.list.find(p => p.id === id); restore(to.data); to.data = null; s.active = id;
    set(PROFILES, JSON.stringify(s)); location.reload();
  }
  function addProfile() {
    const s = profiles(); if (s.list.length >= 6) return false;
    s.list = s.list.map(p => (p.id === s.active ? { ...p, data: snapshot() } : p));
    const id = "p" + (Math.max(...s.list.map(p => +p.id.slice(1) || 0)) + 1);
    s.list.push({ id, data: null }); s.active = id; restore(null);
    set(PROFILES, JSON.stringify(s)); location.reload(); return true;
  }
  /** Clear this cadet's patches and qualification (the call sign and settings stay). */
  function resetProgress() { set("atm-academy", null); location.reload(); }

  return {
    get value() { return P; }, update, on(f) { subs.add(f); return () => subs.delete(f); }, wire, setApplied, get applied() { return applied; },
    loadVoices, loadSteerVoices, steerState, requestSteer, previewVoice, listProfiles, switchProfile, addProfile, resetProgress,
  };
}
