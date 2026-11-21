// Wiring only: load places, build the modules, route asks / taps / voice turns between them.
import "./tokens.css";
import "./styles.css";
import "./outpost.css";
import "./mission.css";
import { api, normMoment, hwType } from "./api.js";
import { SAMPLE_ARTIFACTS } from "./dev-artifacts.js";
import { createGlobe } from "./globe.js";
import { wireViews } from "./views_wire.js";   // 0.4 real NASA views (optional nasa_views pack)
import { createCard, readoutLine } from "./card.js";
import { createPlayer } from "./player.js";
import "./floor.css";               // the voice bar's styles (was imported by voice.js; kept in the same cascade order)
import { createVoice, CREW_TALK } from "./voice.js";
import { createCrewPick } from "./crewpick.js";   // [0.4.1] crew talk: "Heard “…” · Use it"
import { onEngine, engineState, askbarClasses, warmState, WARM_MS, VOICE_FIX, earFailed, onEarFailed, setEarFailed } from "./engine.js";   // [#87] the desktop shell's ear state
import { createMissions } from "./missions.js";
import { initAbout } from "./about.js";
import { createMissionUI } from "./mission/ui.js";
import { installMissionLearning } from "./mission_learning.js";   // Moon Base offer + debrief Learn more (outside mission/ui.js)
import { createAcademyUI } from "./academy/ui.js";   // Academy
import { APP_NAME, APP_TAGLINE } from "./brand.js";
import { callSign, HELP, rideReady, SCHOOL, TRANSITION } from "./story.js";
import { courseState, courseLabel, syncCourse } from "./courses.js";   // courses (docs/COURSES.md): the Moon is course #1
import { installCourseSwitch } from "./course_switch.js";
import "./course_switch.css";
import { moreCourses } from "./course_store_ui.js";   // Settings → For grown-ups → Course storage: download / remove / switch (docs/COURSES.md §4.2)
import { chime } from "./sound.js";
import { maskProfanity, hasProfanity } from "./profanity.js";   // [P0] kid text is never shown unmasked
// ---- audio floor (floor.js owns guide/crew/effects; docs/SESSION_CONTRACT.md §3-4) ----
import { speak, stopSpeaking, isSpeaking, STORY_VOICE, CAPCOM_VOICE, floor, sayStyle } from "./floor.js";
// ---- end audio floor ----
import { createSession } from "./session.js";
// ---- [a11y] accessibility, captions, key-span highlighting, Space words (docs/ACCESSIBILITY.md) ----
import "./a11y.css";
import { initA11y } from "./a11y.js";
import { initCaptions } from "./caption.js";
import { initHighlight, paintLinked } from "./highlight.js";
import { initVoiceBar } from "./voicebar.js";
import { createPrefs } from "./prefs.js";
import "./academy/vocab.js";
import "./academy/globe_steps.js";   // [learning-v3] globe step renderers (docs/LEARNING_DESIGN.md §3)
import "./academy/field_steps.js";   // [0.5] Field School step renderers (docs/LEARNING_DESIGN.md §12)
import "./academy/arch_steps.js";   // [courses] archaeology step renderers: layers, rings, hillshade, decide (docs/COURSES.md §3.2)
// ---- [media] NASA video: the overlay, the lesson's video step, Settings → Videos, the credits (docs/MEDIA.md) ----
import "./media/video.css";
import "./field_library.css";   // [courses] a non-Moon course's Library
import { installPretendExplain } from "./pretend.js";   // "pretend tech": say why, the first time
import { initVideo, isOpen as videoOpen, handleVoice as videoVoice, onVideoChange, current as videoNow, openVideo } from "./media/video.js";
import { installFieldLibrary } from "./field_library.js";   // [courses] a non-Moon course's Library: real NASA views, sites, videos
import { installMapLayers } from "./map_layers.js";   // [open data] the Library's Maps: whole-globe layers (the Moon's USGS age + height maps)
import { fillCredits } from "./media/video_ui.js";
import "./storage_ui.js";   // Settings → Storage & updates (desktop asset versions and updates)
import "./learning_ui.js";      // Settings → What the app has learned (on-device learning, docs/ON_DEVICE_LEARNING.md)
import "./progress.css";
import "./brain.css";
import { installBrain, COPY as BRAIN_COPY } from "./brain.js";   // [brain] My Brain (docs/BRAIN.md)
import "./progress.js";         // Settings → For grown-ups → Progress (lessons, patches, missions per cadet; printable)
import "./class_editor.css";
import "./class_editor.js";     // Settings → For grown-ups → Class lessons (teacher-written lessons, docs/CURRICULUM.md)
import "./diagnostics_ui.js";   // Settings → Help & diagnostics (the diagnostics file, docs/DIAGNOSTICS.md)
import "./playtest_ui.js";      // Settings → For grown-ups → Voice log and playtest (docs/DIRECTOR_LOOP.md §1b)
import "./app_update_ui.js";    // Settings → App version: "Check for updates" (desktop only; docs/DESKTOP.md "App updates")
import "./network_ui.js";       // Settings → For grown-ups → School network (docs/SCHOOL_IT.md)
// ---- end [a11y] ----
// ---- [input] one intent bus for voice, tap, keys and camera gestures (docs/GESTURES.md) ----
import { emitIntent, onIntent } from "./input/intents.js";
import { installDefaultIntents, installKeyboardIntents, cabinPanel } from "./input/defaults.js";
import { lookTarget } from "./gesture/bind.js";
import { initGestures } from "./gesture/ui.js";
import "./input/keys.css";   // [keys]
import { installKeys } from "./input/keys.js";
import { installMute, setMuted, toggleMute } from "./mute.js";   // the top bar's Mute (next to Settings)   // [keys] the keyboard as a TV remote (docs/KEYBOARD.md)
import { installGamepad } from "./input/gamepad.js";   // [keys]
import { registerFlow, installFlowIntents, flowLog, flowFrame, pauseCaption, flowWord } from "./flows.js";   // pause / resume every flow
import { REPEAT_MS } from "./input/spatial.js";   // [keys]
// ---- end [input] ----

// [session] The session Director (docs/SESSION_CONTRACT.md) is ON unless ?session=0 or localStorage atm-session=0.
// If its socket fails, mission turns fall back to POST /api/ask exactly as before.
const SESSION_ON = (() => { try { return new URLSearchParams(location.search).get("session") !== "0" && localStorage.getItem("atm-session") !== "0"; } catch (e) { return true; } })();

const $ = id => document.getElementById(id);
const CHIPS = ["Where did Apollo 11 land?", "Show me the rovers", "Play the launch"];
const HW_LABEL = { lander: "Lander", rover: "Rover", impact: "Impact site", instrument: "Instrument", memorial: "Memorial" };
const TOUR_MS = 3000;   // minimum time at each tour stop
/** [qa] The hardware tour: a few firsts (first to reach the Moon, first robot rover, first crew, rovers, the latest lander). */
const TOUR_IDS = ["luna2_impact", "surveyor1", "lunokhod1", "apollo11_lm_eagle", "apollo15_lrv", "apollo17_lm_challenger", "change3_lander", "yutu_rover"];
// Shown on the card with "I don't know that one yet", never spoken (a spoken example is heard back by the open mic).
const TRY = "Try: “show me the giant bullseye” or “where did Apollo 11 land?”";
/** Mirrors turn_router.clear_question: a wh- / "tell me" / "can you" question of ≥ 3 words. */
const clearQuestion = t => { const q = String(t || "").toLowerCase().replace(/[^a-z0-9 ?]/g, " ").replace(/\s+/g, " ").trim();
  return q.split(" ").length >= 3 && (/^(what|where|when|why|who|whose|which|how)\b/.test(q) || /^(tell me|show me|can you tell|can you show|could you tell|explain|teach me)\b/.test(q)); };
/** First two sentences: a tour stop's short story. */
/** Router intents a running / paused flow owns: they never pause it (main.js heard). */
const FLOW_NAV = ["next", "prev", "back", "accept_offer", "resume", "pause", "repeat", "start"];
const shortStory = t => ((t || "").match(/[^.!?]+[.!?]+/g) || [t || ""]).slice(0, 2).join(" ").trim();

async function boot() {
  initAbout();
  const nameEl = document.querySelector(".appname");
  if (nameEl) { nameEl.textContent = APP_NAME; nameEl.title = APP_TAGLINE; }
  // The askbar shows the kid's call sign (local only).
  const csTag = $("csTag"), paintCs = () => { const c = callSign.get(); csTag.textContent = c; csTag.hidden = !c; };
  paintCs(); addEventListener("outpost:callsign", paintCs);
  let places;
  // [qa] Offline: keep trying (the desktop app's backend may still be starting), so this is never a dead end.
  for (let tries = 0; !places; tries++) {
    try { if (!courseState.synced) await syncCourse(); places = await api.places(); }   // the cadet's course first: its places, lessons, names
    catch (e) {
      if (!tries) { $("loading").innerHTML = "<b>Can&rsquo;t reach Outpost Luna</b><span>Trying again. If this stays, close the app and open it again.</span>"; $("loading").classList.add("is-error"); }
      await new Promise(res => setTimeout(res, 3000));
    }
  }
  if ($("loading").classList.contains("is-error")) { $("loading").classList.remove("is-error"); $("loading").textContent = "Loading the Moon…"; }
  if (courseState.active !== "moon") {   // [courses] the few map lines that name the Moon or Flight School; the rest of a
    // course's copy (spoken lines, story beats) comes with its content (docs/COURSES.md P3)
    const school = courseLabel("school", "Flight School"), body = (courseState.info.globe && courseState.info.globe.name) || courseState.info.title;
    SCHOOL.eyebrow = school; TRANSITION.firstMap.where = school;
    TRANSITION.firstMap.intro = [`This is ${body === "Earth" ? "Earth" : `the ${body}`}. Drag it to spin it.`, ...TRANSITION.firstMap.intro.slice(1)];
    TRANSITION.firstMap.say = "Each pin is a lesson. Earn the patches.";
    if (courseState.info.missions !== "outpost") $("modeMission").hidden = true;   // no outpost mission in this course (a season engine is P4)
  }
  if (courseState.active !== "moon") { $("loading").textContent = `Loading ${courseState.info.title}…`; $("stage").setAttribute("aria-label", (courseState.info.globe && courseState.info.globe.name) || courseState.info.title); }
  // Until the backend ships hardware, the UI runs on clearly labelled sample artifacts.
  const sample = courseState.active === "moon" && !places.some(p => p.kind === "artifact");   // Moon hardware samples: the Moon course only
  if (sample) places = places.concat(SAMPLE_ARTIFACTS.map(a => ({ ...a, km: 0, hw: hwType(a) })));
  const byId = Object.fromEntries(places.map(f => [f.id, f]));
  const placeById = id => byId[id] || null;
  (window.__outpost = window.__outpost || {}).placeById = placeById;   // [learning-v3] globe step directives

  const turn = { lastPlace: null, emotion: null, seq: 0, lastUnknown: -1e9 };
  const card = createCard();
  const tour = { id: 0, active: false, paused: false, held: false, why: "", stops: [], i: -1, timer: null, token: 0, heldT: 0 };
  // [flows] while the Library tour is paused, any other card (an answer, a tapped place) offers the way back to it
  { const show = card.show.bind(card);
    card.show = entry => { const tk = show(entry);
      if (!entry.tour && tour.active && tour.paused) card.addAction(tk, { label: "Resume tour", hot: true, onClick: () => resumeTour("button") });
      return tk; }; }
  // [audit2] a tap on empty space, where a tap on the Moon is the answer (a Moon step, the Library, Find it): one quiet
  // chip on the voice bar instead of nothing
  const TAP_STEPS = ["tap", "intent", "route", "terminator", "compare", "globe_side"];
  const onMiss = () => {
    const m = document.body.dataset.mode, f = m === "academy" ? academyUI.screen() : null;
    if (m === "cadet" || (f && f.screen === "lesson" && TAP_STEPS.includes(f.step_type))) voice.notice(`Tap on ${onMoon ? "the Moon" : bodyName}`);
  };
  // [courses] the course's body: the Moon (unchanged, MOON_BODY) or another course's globe (Earth: the pack's Blue Marble)
  const onMoon = courseState.active === "moon" || !courseState.info.globe || courseState.info.globe.body === "moon";
  const bodyName = onMoon ? "Moon" : (courseState.info.globe.name || courseState.info.title);   // "Earth" (no article)
  const globe = createGlobe({ stage: $("stage"), label: $("label"), loading: $("loading"), places, onTap, onArtifact, onMiss, body: onMoon ? undefined : courseState.info.globe });
  window.__outpost.globe = globe;   // the playtest (frontend/tools/playtest.py) reads where a step's places are on screen
  if (onMoon) wireViews({ globe, stage: $("stage"), hudRow: $("tourBtn").parentElement });   // Moon-only: its real sky, hardware models, rocks, sharp pole   // real sky, LM / LRO / LADEE models, Moon rocks tray, sharp south pole
  // [courses] another course's Library (field_library.js): its real pictures, videos, places, tour and chips. The Moon's
  // Library stays as it was (hardware, crew audio, the NASA views pack).
  const fieldLib = onMoon ? null : installFieldLibrary({
    stage: $("stage"), chipsEl: $("chips"), globe, card, places, placeById, say: t => guideSay(t),
    openVideo: (id, o) => openVideo(id, o), runTour: (ids, intro, o) => runTour(ids, intro, o), goLibrary: () => setMode("cadet"),
    mapUrl: (courseState.info.globe || {}).map || "",
  });
  if (fieldLib) window.__outpost.fieldLib = fieldLib;
  // [open data] the Library's Maps button (docs/OPEN_DATA.md): a course's whole-globe layers, the photo back on leaving
  installMapLayers({ globe, hudRow: $("tourBtn").parentElement, host: $("stage"), say: t => guideSay(t), bodyName });
  const player = createPlayer({
    api, globe, placeById, isKidTalking: () => voice.kidTalking,
    onPlace: id => { turn.lastPlace = id; }, onEnd: scheduleNudge,
  });
  const voice = createVoice({
    onTurn: (text, o = {}) => ask(text, "voice", o),
    onBargeIn: o => onBarge(o),
    onKidDone: () => onKidDone(),
    onEmotion: label => { turn.emotion = label; },
    isOutputBusy: () => isSpeaking() || player.active,
    screen: () => screenFrame(),          // the pending offer / open step: their reply is never an echo of the tail
  });
  // [session] the socket, its decision handlers, and the hooks the mission UI calls.
  let session = null;
  const useSession = () => !!(session && session.connected);
  // [media] a video starts clean: no guide line, no crew clip, nothing queued from the session (docs/MEDIA.md)
  initVideo({ stopOthers: () => { cancelNudge(); cancelTour("video"); stopSpeaking("video"); if (player.active) player.stop(true); if (useSession()) session.dropAll(); } });
  // body[data-video=1] while a video is up: the gestures layer's "video" coach mark and help card read it (gesture/ui.js)
  onVideoChange(() => { if (videoOpen()) document.body.dataset.video = "1"; else delete document.body.dataset.video; pushScreen(true); });
  $("aboutBtn").addEventListener("click", () => { fillCredits(); });
  const missionUI = createMissionUI({
    globe, card, placeById, say: (t, style, o = {}) => guideSay(t, { voice: CAPCOM_VOICE, style, priority: o.priority }) /* audio floor: CAPCOM voice, Director style; priority 4 = proactive (waits, never cuts a readback) */,
    onContext: f => voice.sendContext(session ? { ...f, session: session.id } : f), askDirector: t => ask(t),
    alertSound: () => { chime(true); setTimeout(() => chime(true), 220); setTimeout(() => chime(true), 440); },
    academy: { badges: () => academyUI.badges(), has: id => academyUI.has(id), qualified: () => !!academyUI.progress.qualified,
      rideStatus: () => academyUI.rideStatus(),
      // [0.3.12] straight into the check ride, or, before the core lessons are done, into the next lesson (the button
      // says "Unlocks after 6 lessons (2/6)"); it used to drop the cadet on the map with no reason
      goRide: () => { const r = academyUI.rideStatus(), id = rideReady(r) ? r.ride : r.next; setMode("academy");
        if (id) setTimeout(() => academyUI.nav("lesson", id), 400); } },   // Flight School patches carry over; the check ride gates command (Cadet before)
    session: {
      onStart: st => { if (useSession()) session.hello({ mode: "mission", mission_id: st.id, role: (missionUI.context() || {}).role || null }); },
      endShift: () => useSession() && session.ui("end_shift"),
      live: () => useSession(),   // the session Director speaks story beats; without it the cabin does
    },
  });
  // Academy: lessons before the mission; the check ride qualifies the cadet for Mission mode.
  const academyUI = createAcademyUI({
    globe, placeById, player, say: (t, style, o = {}) => guideSay(t, { voice: CAPCOM_VOICE, style, repeat: o.repeat, source: "academy" }) /* floor.say, CAPCOM voice, steered */, stop: () => stopSpeaking("academy_stop"),
    alertSound: () => { chime(true); setTimeout(() => chime(true), 220); setTimeout(() => chime(true), 440); },
    goMission: () => setMode("mission"),
    openLibrary: id => { setMode("cadet"); const a = placeById(id); if (a) setTimeout(() => (a.kind === "artifact" ? onArtifact(a) : onTap(a)), 300); },
    onProgress: p => { document.body.dataset.qualified = p.qualified ? "1" : ""; },
  });
  document.body.dataset.qualified = academyUI.progress.qualified ? "1" : "";
  // [brain] My Brain: the top bar's button, the map's call-sign chip, B, voice (docs/BRAIN.md)
  const brain = installBrain({ setMode: m => setMode(m), editCallSign: () => academyUI.editCallSign() });
  // [class] Settings → Class lessons → Preview: the course again (the preview joined it), then the lesson, as a cadet sees it
  addEventListener("outpost:class-open", e => {
    const id = e.detail && e.detail.id; if (!id) return;
    academyUI.reloadCourse().catch(() => {}).then(() => { setMode("academy"); setTimeout(() => academyUI.nav("lesson", id), 400); });
  });
  const missionLearning = installMissionLearning({
    missionUI, say: t => guideSay(t, { voice: CAPCOM_VOICE }), stop: () => stopSpeaking("mission_stop"),
    lessons: () => academyUI.lessons(),
    openLesson: id => { setMode("academy"); setTimeout(() => academyUI.nav("lesson", id), 400); },
  });
  const missions = createMissions({ globe, placeById, places, say: t => guideSay(t), onFound: f => { turn.lastPlace = f.id; } });

  // ---- [a11y] settings + voice commands + audio description, captions, highlights ----
  const a11ySay = (t, o = {}) => o.describe
    ? (floor ? floor.say(t, { voice: "guide", priority: 5, style: { situation: "explain" } }) : speak(t))
    : guideSay(t, { voice: CAPCOM_VOICE, style: o.situation ? { situation: o.situation, vocab: o.vocab } : undefined, keepCrew: true,
      repeat: true /* "say that again", a word's "hear it" button: asked for on purpose */, source: "a11y" });
  const a11y = initA11y({ floor, say: a11ySay, ask: t => ask(t), setMode: m => setMode(m), tap: p => {   // [qa] Help → "Pick a place": a globe tap (Flight School tap steps included); in Mission, shown in the Library
    // [audit2] Flight School outside a tap step (the map, a choice step) swallowed the pick: show it in the Library too
    const af = document.body.dataset.mode === "academy" ? academyUI.screen() : null, tapStep = af && af.screen === "lesson" && ["tap", "intent"].includes(af.step_type);
    if (document.body.dataset.mode === "mission" || (af && !tapStep)) { setMode("cadet"); setTimeout(() => (p.kind === "artifact" ? onArtifact(p) : onTap(p)), 300); return; }
    return p.kind === "artifact" ? onArtifact(p) : onTap(p); }, places, playCrew: m => player.play(m) });
  if (a11y) a11y.wrapGlobe(globe, placeById);
  initCaptions({ floor, settings: () => (a11y ? a11y.settings : {}) });
  const vbar = initVoiceBar({ announce: t => { if (a11y) a11y.describe(t); } });   // the floating voice bar
  // Settings v1 (prefs.js): voice, sound, listening, display, level, cadet profiles. The session gets the steering bits.
  const prefs = createPrefs({ globe });
  (window.__outpost = window.__outpost || {}).prefsApi = prefs;
  installMute();   // every screen: Flight School, Mission, Library, the cabin
  // "Pretend tech": the first pick of something marked pretend says why, once (src/pretend.js)
  installPretendExplain({ speak: t => speak(t, { priority: 2 }) });   // the guide's line is captioned like any other
  const sendPrefs = () => { if (useSession()) session.sendRaw(prefs.wire(a11y ? a11y.settings.speed : 1)); };
  prefs.on(() => sendPrefs());
  addEventListener("outpost:room", () => sendPrefs());   // the automatic room state (room.js): the server's dd gates follow it
  // the turn log (prefs.improve, or a grown-up's Playtest session): the Academy's grade of a step, so the server can mark
  // a step that passed or went to hint (the server ignores it when the log is off)
  addEventListener("outpost:lesson-result", e => { if (useSession() && e.detail) session.sendRaw({ t: "ui", event: "lesson_result", status: e.detail.status, step_type: e.detail.step_type }); }); addEventListener("outpost:a11y", e => { if (e.detail && "speed" in e.detail) sendPrefs(); });
  initHighlight({ api, say: a11ySay, playCrew: m => { stopSpeaking("highlight_crew"); player.play(m); }, flyTo: id => { const f = placeById(id); if (f) { globe.showFeature(f); turn.lastPlace = f.id; } } });
  // ---- end [a11y] ----

  /** The guide speaks (card text is the caption). Never over crew audio: the moment ends first. */
  async function guideSay(text, { keepCrew, voice: v, style, repeat, source, priority } = {}) {
    if (!text) return false;
    if (!keepCrew && player.active) player.stop(true);
    voice.show("speaking");
    const ok = await speak(text, { ...(v || {}), style: style || (turn.emotion ? { emotion: turn.emotion } : undefined), repeat, source, ...(priority != null ? { priority } : {}) });
    voice.show("idle");
    return ok;
  }

  const context = () => {
    const c = {};
    if (turn.lastPlace) c.last_place = turn.lastPlace;
    if (turn.emotion) c.emotion = turn.emotion;
    const p = player.playing; if (p) c.playing = p;
    const m = missionUI.active && missionUI.context(); if (m) c.mission = m;
    return c;
  };

  /** The hardware tells its own story, in its own voice. */
  const storySay = text => guideSay(text, { voice: STORY_VOICE, style: { situation: "story" } });

  async function ask(raw, source, opts = {}) {
    const text = (raw || "").trim(); if (!text) return;
    if (vbar && vbar.handleText(text)) { $("q").value = ""; voice.clearWords(); voice.show("idle"); return; }   // "move the voice bar to the top"
    { const w = text.toLowerCase().replace(/[^a-z ]/g, "").trim();   // the top bar's Mute by voice or typing (no session needed)
      if (/^(mute|mute (the )?(sound|audio|app)|sound off|be quiet)$/.test(w)) { setMuted(true); $("q").value = ""; voice.clearWords(); voice.show("idle"); return; }
      if (/^(unmute|unmute (the )?(sound|audio|app)|sound on)$/.test(w)) { setMuted(false); $("q").value = ""; voice.clearWords(); voice.show("idle"); return; } }
    // [media] a video is up: pause / play / skip / stop run here; nothing else is a turn until it closes
    if (videoOpen()) { videoVoice(text); $("q").value = ""; voice.clearWords(); voice.show("idle"); return; }
    const heard = source === "voice";
    // [owner bug] "what is lava?" / "what does that mean?": a space word on screen opens its card and is said (highlight.js)
    { const H = window.__outpost && window.__outpost.highlight;
      if (H && H.define && H.define(text)) { $("q").value = ""; voice.clearWords(); voice.show("idle"); return; } }
    // [hands-free] One router for every turn (backend/app/turn_router.py): with a live session, every turn (spoken or
    // typed, in every screen) goes up the socket with the current screen; the Director answers with nav / answer /
    // say decisions, or stays silent. Echo, filler and chatter never reach the screens.
    if (useSession()) {
      if (!heard && a11y && await a11y.handleText(text)) { $("q").value = ""; return; }   // typed a11y commands stay local
      $("q").value = ""; pushScreen(true);
      // [P0] a spoken turn waits for the router's `heard` decision (voice.decided): no words, no "Thinking" before it
      session.typed(text, opts.ptt ? "ptt" : heard ? "voice" : "typed", heard ? { dd: opts.dd ?? null, safety: opts.safety || null } : null);
      if (!heard) { voice.clearWords(); voice.show("idle"); }
      return "session";
    }
    // [P0] no session (the router is server-side): the client's own gate for open-mic turns. Arc says it was for
    // someone else, or it is rude: dropped, silently, and never graded or shown.
    if (heard && !opts.ptt && ((opts.dd != null && opts.dd < 0.5) || hasProfanity(text))) return;
    { const fw = flowWord(text);   // [flows] no session: "continue" / "stop" / "next" reach a running or paused flow here
      if (fw && await emitIntent(fw, { text }, "voice")) { $("q").value = ""; voice.clearWords(); voice.show("idle"); return; } }
    const my = ++turn.seq; cancelNudge(); cancelTour("question");
    $("q").value = "";
    // [P0] a spoken turn shows "Thinking" only if it is still undecided after a moment (voice.js), and reaches the
    // transcript only once something used it (logKid below); a typed one was meant for us
    const logKid = () => { if (window.__outpost && window.__outpost.captions) window.__outpost.captions.log("kid", text); };
    if (!heard) { voice.show("thinking"); logKid(); }
    const used = () => { if (heard) logKid(); voice.clearWords(); voice.show("idle"); };
    if (a11y && await a11y.handleText(text)) { used(); return; }   // [a11y] "where am I?", "faster", "press next"
    if (missionUI.active && await missionUI.handleText(text)) { used(); return; }
    if (academyUI.active && await academyUI.handleText(text)) { used(); return; }   // Academy
    // [session] Mission mode with a live session: the turn goes up the socket; decisions come back on their own.
    if (missionUI.active && missionUI.running && !missionUI.sample && useSession()) {
      session.typed(text, source); voice.clearWords(); voice.show("idle"); return;
    }
    let r;
    try { r = await api.ask(text, context()); }
    catch (e) {
      if (my === turn.seq) { card.show({ title: "Hmm", asked: text, say: "I can't answer right now. Try again in a moment." }); voice.show("idle"); }   // [qa] no developer text
      return;
    }
    for (let w = 0; voice.kidTalking && w < 100; w++) await new Promise(res => setTimeout(res, 100));   // WAIT
    if (my !== turn.seq) return;
    // [hands-free] no session: the "I don't know" fallback only for a clear spoken question, at most once per 30 s.
    if (heard && (r.source === "none" || (r.action === "ask" && r.readout && r.readout.brain && /ask|unknown/.test(r.readout.brain.status)))) {
      if (!clearQuestion(text) || (r.source === "none" && performance.now() - turn.lastUnknown < 30000)) { voice.clearWords(); voice.show("idle"); return; }
      if (r.source === "none") turn.lastUnknown = performance.now();
    }
    if (heard) logKid();
    voice.clearWords();
    if (missionUI.active) {
      // Mission mode: the globe stays on the outpost. Non-mission answers are shown and spoken, without flying or touring.
      if (await missionUI.handleDirector(r)) { voice.show("idle"); return; }
      card.show({ title: "CAPCOM", asked: text, say: r.say || "Say a mission command, like “shields to 40” or “end shift”.", arc: readoutLine(r) });
      await guideSay(r.say, { voice: CAPCOM_VOICE, style: sayStyle(r) }); return;   // audio floor: CAPCOM voice
    }
    await act(r, text, my);
  }

  async function act(r, asked, my) {
    const f = placeById(r.place), moment = normMoment(r.moment), say = r.say || "";
    const arc = readoutLine(r);
    if (r.action === "guard") { card.show({ title: "Let's keep that private", asked, say, arc }); await guideSay(say, { style: sayStyle(r) }); scheduleNudge(); return; }
    if (r.action === "ask" && r.ask) { askCard(r, asked, arc); return; }
    if (r.action === "tour") { runTour(r.places, say, { asked, arc }); return; }
    if (f && f.kind === "artifact") { await artifactAnswer(f, r, asked, my); return; }
    if (r.view && !f) globe.flyTo(r.view.lat, r.view.lon, 3.6);
    if (f) { if (f.id !== turn.lastPlace) chime(); globe.showFeature(f); if (r.view) globe.flyTo(r.view.lat, r.view.lon); turn.lastPlace = f.id; }
    const token = card.show({
      title: f ? f.name : "Guide", place: !!f, asked, say: r.source === "none" ? `${say} ${TRY}` : say, arc, claims: r.claims,
      note: f && f.est ? "Location estimated from the crew's own directions." : "",
    });
    if (r.action !== "play") offerCrew(token, f, moment);
    if (player.active) player.stop(true);
    const spoke = await guideSay(say, { style: sayStyle(r) });
    if (my !== turn.seq) return;
    if (r.action === "play" && moment) { if (!spoke && voice.kidTalking) return; await player.play(moment); return; }
    scheduleNudge();
  }

  /** "▶ Hear the crew" when the server has a kid-safe moment for this place. */
  function offerCrew(token, f, moment) {
    const add = m => m && card.addAction(token, { label: "Hear the crew", hot: true, onClick: () => { stopSpeaking("hear_crew"); player.play(m); } });
    if (moment) add(moment);
    else if (f) api.moments(f.id).then(ms => add(ms[0]));
  }

  /** ASK: options preview-fly the globe; a tap re-asks with that place name. */
  function askCard(r, asked, arc) {
    const q = r.ask.question || r.say, opts = (r.ask.options || []).map(placeById).filter(Boolean);
    card.show({
      title: "Did you mean…", asked, say: q, arc,
      actions: opts.map(f => ({ label: f.name, hot: true, once: true, onPreview: () => globe.showFeature(f), onClick: () => { clearPreviews(); turn.lastPlace = f.id; if (useSession()) session.ui("confirm_pick", { id: f.id }); ask(f.name); } })),
    });
    guideSay(q);
    // [qa] the preview flights stop on a choice, a new turn or a mode switch (cancelNudge clears them)
    const my = turn.seq;
    previewT = opts.map((f, i) => setTimeout(() => { if (!voice.kidTalking && my === turn.seq && document.body.dataset.mode === "cadet") globe.showFeature(f); }, 400 + i * 1600));
    scheduleNudge();
  }

  // ---------- ghost hardware ----------
  function artifactEntry(a, extra = {}) {
    const eyebrow = [extra.eyebrow, HW_LABEL[a.hw], sample ? "Sample data" : ""].filter(Boolean).join(" · ");
    return { title: a.name, artifact: a, ...extra, eyebrow, actions: [...voiceActions(a), ...(extra.actions || [])] };
  }
  /** "▶ Hear Charlie Duke": the artifact's own audio segments, played through the crew player. */
  function voiceActions(a) {
    return (a.voices || []).filter(v => v && v.clip_id).map(v => ({
      label: "Hear " + (v.who || "the crew"), hot: true,
      onClick: () => { cancelTour("crew"); stopSpeaking("tap_crew"); player.play({ clip_id: v.clip_id, t0: v.t0, t1: v.t1, speaker: v.who || "crew", places: [a.id], jargon: [] }); },
    }));
  }
  function focusArtifact(a) { if (a.id !== turn.lastPlace) chime(); globe.showFeature(a); turn.lastPlace = a.id; }

  /** The Director answered with an artifact: its line first (guide voice), then the artifact's story (its own voice). */
  async function artifactAnswer(a, r, asked, my) {
    const moment = normMoment(r.moment);
    focusArtifact(a);
    const token = card.show(artifactEntry(a, { asked, say: r.say, arc: readoutLine(r), claims: r.claims }));
    if (r.action !== "play") offerCrew(token, null, moment);
    if (player.active) player.stop(true);
    const spoke = await guideSay(r.say || "", { style: sayStyle(r) });
    if (my !== turn.seq) return;
    if (r.action === "play" && moment) { if (!spoke && voice.kidTalking) return; await player.play(moment); return; }
    await storySay(a.story);
    if (my === turn.seq) scheduleNudge();
  }

  /** Tapped a ghost marker: card + story right away, and the Director is asked about it so it stays in charge of what's said. */
  async function onArtifact(a) {
    voice.clearWords();
    if (academyUI.onArtifact(a)) return;   // Academy
    if (missions.onTap({ lat: a.lat, lon: a.lon }, a)) return;
    cancelTour("tap"); cancelNudge();
    const my = ++turn.seq;
    focusArtifact(a);
    const token = card.show(artifactEntry(a, { arc: readoutLine({ source: "tap", action: "fly" }) }));
    if (player.active) player.stop(true);
    let r = null;
    try { r = await api.ask(a.name, context()); } catch (e) { /* the story alone is fine */ }
    if (my !== turn.seq) return;
    if (r && r.action !== "guard" && r.say) {
      card.update(token, { say: r.say, claims: r.claims, arc: readoutLine(r) });
      offerCrew(token, null, normMoment(r.moment));
      await guideSay(r.say, { style: sayStyle(r) });
      if (my !== turn.seq) return;
    }
    await storySay(a.story);
    if (my === turn.seq) scheduleNudge();
  }

  // barge-in (voice.js: the kid started talking over us) and its end. The tour is HELD, not stopped (holdTour).
  // o.keepGuide (fix/barge-in: a soft barge where the guide talks on): the tour is not held either
  function onBarge(o = {}) { cancelNudge(); if (!o.keepGuide) holdTour(); if (isSpeaking() && !o.keepGuide) stopSpeaking("barge:" + (o.reason || "speech")); player.duck(); if (useSession()) { session.dropAll(); session.ui("barge_in"); } }
  function onKidDone() { player.unduck(); releaseHold(); if (useSession()) session.ui("kid_done"); }

  // ---------- tour: fly through stops one by one. A stop PAUSES it (flows.js): the card says why, Resume (focused),
  // Previous / Next and Close; "continue", a thumbs up, Enter or the button resume it from the current stop. ----------
  const tourLog = (event, source, extra) => flowLog({ flow: "library_tour", event, source, step: tour.i, of: tour.stops.length, ...(extra || {}) });
  /** The card for the current stop: running (Pause, Next stop) or paused (Resume, Previous, Next, Close). */
  function tourCard() {
    const i = Math.max(0, tour.i), a = tour.stops[i]; if (!a) return;
    const n = tour.stops.length, hw = a.kind === "artifact";
    const acts = tour.paused
      ? [{ label: "Resume", hot: true, onClick: () => resumeTour("button") },
        ...(i > 0 ? [{ label: "Previous", onClick: () => tourStepBy(-1, "button") }] : []),
        ...(i < n - 1 ? [{ label: "Next", onClick: () => tourStepBy(1, "button") }] : []),
        { label: "Close tour", onClick: () => { closeTour("button"); card.hide(); } }]
      : [{ label: "Pause", onClick: () => pauseTour("button") },
        { label: i < n - 1 ? "Next stop" : "Finish", hot: true, onClick: () => tourStepBy(1, "button") }];
    const extra = { eyebrow: `${tour.paused ? "Paused" : "Tour"} · stop ${i + 1} of ${n}`, actions: acts, transient: true, tour: true,
      note: tour.paused ? tour.why : "" };
    tour.token = card.show(hw ? artifactEntry(a, extra) : { title: a.name, place: true, say: a.fact, ...(fieldLib ? fieldLib.placeEntry(a) : {}), ...extra });
    if (tour.paused) requestAnimationFrame(() => { const b = document.querySelector("#cardActions .pill.hot"); if (b && tour.paused) b.focus({ preventScroll: true }); });
  }
  /** Pause where we are (the line stops). source: voice | gesture | keyboard | barge | question | tap | video | crew | button */
  function pauseTour(source, { quiet = false } = {}) {
    if (!tour.active || tour.paused) return false;
    tour.paused = true; tour.held = false; clearTimeout(tour.heldT); tour.id++; clearTimeout(tour.timer);
    tour.why = pauseCaption(source);
    $("tourBtn").setAttribute("aria-pressed", "false");
    if (!quiet && isSpeaking()) stopSpeaking("tour_pause");
    tourLog("pause", source);
    if (!quiet) tourCard(); else card.update(tour.token, { eyebrow: `Paused · stop ${tour.i + 1} of ${tour.stops.length}`, note: tour.why, actions: [{ label: "Resume tour", hot: true, onClick: () => resumeTour("button") }] });
    return true;
  }
  /** Resume: the current stop's line again, from the start (they are two sentences). */
  function resumeTour(source) {
    if (!tour.active || (!tour.paused && !tour.held)) return false;
    tour.paused = false; tour.held = false; clearTimeout(tour.heldT); tour.why = "";
    $("tourBtn").setAttribute("aria-pressed", "true");
    tourLog("resume", source);
    cancelNudge(); tourStep(++tour.id, Math.max(0, tour.i));
    return true;
  }
  /** Barge-in: the kid started talking. Hold the tour (the floor already stopped the line); if the turn turns out not to
   *  be for us (filler, echo, room talk: the router ignores it) the stop plays again; a real turn pauses it. */
  function holdTour() {
    if (!tour.active || tour.paused || tour.held) return;
    tour.held = true; tour.id++; clearTimeout(tour.timer); clearTimeout(tour.heldT);
    tourLog("hold", "barge");
  }
  function releaseHold(ms = 1800) {
    if (!tour.held) return;
    clearTimeout(tour.heldT);
    tour.heldT = setTimeout(() => { if (tour.held && !voice.kidTalking) resumeTour("barge_ignored"); }, ms);
  }
  /** End the tour (Close, the last stop, leaving the Library). */
  function closeTour(source, note) {
    if (!tour.active) return;
    tour.active = false; tour.paused = false; tour.held = false; tour.id++; clearTimeout(tour.timer); clearTimeout(tour.heldT);
    $("tourBtn").setAttribute("aria-pressed", "false");
    tourLog(note ? "done" : "close", source);
    card.update(tour.token, { actions: [], note: "", eyebrow: note || "Tour closed" });
  }
  /** Something else took over (a tap, a question, a video, a crew clip): the tour pauses, never ends. */
  const cancelTour = source => pauseTour(source || "question", { quiet: true });
  async function runTour(ids, intro, { asked, arc, title } = {}) {
    const stops = (ids || []).map(placeById).filter(Boolean);
    if (!stops.length) { card.show({ title: "Guide", asked, say: intro, arc }); await guideSay(intro); return; }
    closeTour("restart"); cancelNudge(); ++turn.seq;
    Object.assign(tour, { active: true, paused: false, held: false, why: "", stops, i: -1 }); const my = ++tour.id;
    $("tourBtn").setAttribute("aria-pressed", "true");
    tourLog("start", "button");
    if (intro) {
      tour.token = card.show({ title: title || "Hardware tour", eyebrow: `Tour · ${stops.length} stops`, asked, say: intro, arc, transient: true, tour: true,
        actions: [{ label: "Start", hot: true, onClick: () => { if (my === tour.id && tour.active) { stopSpeaking("tour_start"); tourStep(++tour.id, 0); } } }, { label: "Close tour", onClick: () => { closeTour("button"); card.hide(); } }] });
      if (player.active) player.stop(true);
      await guideSay(intro);
    }
    tourStep(my, 0);
  }
  async function tourStep(my, i) {
    if (my !== tour.id || !tour.active || tour.paused) return;
    if (i >= tour.stops.length) { closeTour("end", "Tour done"); scheduleNudge(); return; }
    tour.i = i; const a = tour.stops[i], hw = a.kind === "artifact";
    tourLog("step", "flow");
    chime(); globe.showFeature(a); turn.lastPlace = a.id;
    tourCard();
    const t0 = performance.now();
    if (hw) await storySay(shortStory(a.story)); else await guideSay(a.fact);
    if (my !== tour.id) return;
    tour.timer = setTimeout(() => tourStep(my, i + 1), Math.max(400, TOUR_MS - (performance.now() - t0)));
  }
  // next / previous stop (buttons, swipe, arrows, P / N, "next", "go back"): steps and plays that stop, paused or not
  function tourStepBy(d, source) {
    if (!tour.active) return false;
    const i = tour.i + d;
    if (i < 0) return true;                              // already at the first stop: nothing before it
    if (i >= tour.stops.length) { stopSpeaking("tour_step"); closeTour(source, "Tour done"); return true; }
    stopSpeaking("tour_step"); tour.paused = false; tour.held = false; tour.why = ""; clearTimeout(tour.heldT);
    $("tourBtn").setAttribute("aria-pressed", "true");
    tourLog(d > 0 ? "next" : "prev", source);
    tourStep(++tour.id, i);
    return true;
  }
  registerFlow({
    name: "library_tour", rank: 30,
    active: () => tour.active && document.body.dataset.mode === "cadet",
    paused: () => tour.paused,
    pause: src => pauseTour(src),
    resume: src => resumeTour(src),
    next: src => tourStepBy(1, src), prev: src => tourStepBy(-1, src),
    repeat: src => { tourLog("repeat", src); tour.paused = true; return resumeTour(src); },
    close: src => { closeTour(src); card.hide(); return true; },
  });
  // A crew clip: an open hand or "stop" holds it where it is; "continue", a thumbs up, Enter or a tap on the bar plays on.
  registerFlow({
    name: "crew_clip", rank: 10, keys: false,
    active: () => player.active && !videoOpen(),
    paused: () => player.paused,
    pause: src => { const ok = player.pause(pauseCaption(src)); if (ok) flowLog({ flow: "crew_clip", event: "pause", source: src }); return ok || player.paused; },
    resume: src => { const ok = player.resume(); if (ok) flowLog({ flow: "crew_clip", event: "resume", source: src }); return ok; },
    repeat: src => { flowLog({ flow: "crew_clip", event: "repeat", source: src }); player.replay(); return true; },
    close: src => { flowLog({ flow: "crew_clip", event: "close", source: src }); player.stop(true); return true; },
  });

  function onTap(p) {
    if (missionUI.active) return;   // the globe is a map of the outpost in mission mode
    if (academyUI.onTap(p)) return;   // Academy
    voice.clearWords(); cancelTour("tap");
    if (missions.onTap(p)) return;
    const { f, d } = globe.nearest(p);
    ++turn.seq;
    if (d < 12) {
      if (f.id !== turn.lastPlace) chime();
      globe.showFeature(f); turn.lastPlace = f.id;
      if (fieldLib && fieldLib.lib) { fieldLib.openPlace(f); scheduleNudge(); return; }   // [courses] its real photo + sources
      const token = card.show({ title: f.name, place: true, say: f.fact, arc: readoutLine({ source: "tap", action: "fly" }),
        note: f.est ? "Location estimated from the crew's own directions." : "" });
      offerCrew(token, f, null);
      guideSay(f.fact);
    } else {
      const say = `That spot is ${Math.abs(p.lat).toFixed(0)}° ${p.lat >= 0 ? "north" : "south"}, ${Math.abs(p.lon).toFixed(0)}° ${p.lon >= 0 ? "east" : "west"}. No named place is close.`;   // [qa] COPY.md: no hype
      card.show({ title: "Unnamed spot", say }); guideSay(say);
    }
  }

  // NUDGE: 8 s of quiet after an answer
  let nudgeT = null, previewT = [];
  const clearPreviews = () => { previewT.forEach(clearTimeout); previewT = []; };
  function cancelNudge() { clearTimeout(nudgeT); nudgeT = null; $("nudge").hidden = true; clearPreviews(); }
  function scheduleNudge() {
    clearTimeout(nudgeT);
    nudgeT = setTimeout(async () => {
      if (missionUI.active || academyUI.active) return;
      if (voice.kidTalking || isSpeaking() || player.active) return;
      const n = $("nudge");
      if (!missions.started && !missions.open) { n.textContent = "Play Find it?"; n.onclick = () => { cancelNudge(); missions.openCard(); }; n.hidden = false; return; }
      const ms = await api.moments(null).catch(() => []), m = ms.find(x => x.places.some(p => p !== turn.lastPlace && byId[p])) || ms[0];
      if (!m || !nudgeT || missionUI.active || academyUI.active || voice.kidTalking || isSpeaking() || player.active) return;   // [qa] the world moved on during the fetch
      n.textContent = `Hear the crew at ${(byId[m.places[0]] || { name: "the Moon" }).name}?`;
      n.onclick = () => { cancelNudge(); player.play(m); }; n.hidden = false;
    }, 8000);
  }

  // ---------- [session] decisions → modules ----------
  const sendRaw = m => { if (!m) return; if (m.t === "typed") ask(m.text); else session.sendRaw(m); };
  const handlers = {
    // The floor manager is the only audio owner: say decisions go to floor.say() with the contract priority.
    say: async d => {
      if (videoOpen()) return false;   // [media] never over a video (the router keeps quiet on the video screen)
      if (d.delay_ms) { await missionUI.houston(d.text, +d.delay_ms, d.style); return true; }
      if (!floor) return guideSay(d.text, { voice: d.voice === "story" ? STORY_VOICE : d.voice === "capcom" ? CAPCOM_VOICE : undefined, style: d.style });
      if (player.active && (d.priority ?? 3) <= 3) player.stop(true);
      voice.show("speaking");
      const ok = await floor.say(d.text, { voice: d.voice || "guide", priority: d.priority ?? 3, id: d.id, style: d.style });
      voice.show("idle");
      return ok;
    },
    play: async d => { if (videoOpen()) return; const m = normMoment(d.moment || { clip_id: d.clip_id, t0: d.t0, t1: d.t1, jargon: d.explain }); if (m) await player.play(m); },
    stop: () => { stopSpeaking("session_cancel"); if (player.active) player.stop(true); },
    card: d => { if (missionUI.active) missionUI.showCard(d, sendRaw); else card.show({ title: d.title, asked: d.asked, say: d.body, claims: d.claims, arc: readoutLine({ readout: d.readout, source: d.source, action: d.action }) }); },
    hud: d => missionUI.applyRemote(d.state),
    alert: d => missionUI.active && missionUI.alert(d),
    ask_confirm: d => missionUI.askConfirm(d, sendRaw),
    fly: d => { if (missionUI.active) return; const f = placeById(d.place); if (f) globe.showFeature(f); else if (d.view) globe.flyTo(d.view.lat, d.view.lon, 3.6); },
    highlight: () => {},
    floor: d => { document.body.dataset.floor = d.holder; },
    lesson: d => dispatchEvent(new CustomEvent("atm:lesson", { detail: d })),   // the Academy UI listens
    prefs: d => prefs.setApplied(d.applied),   // Settings v1: what the session applied
    // [hands-free] what the router made of a turn (only a used turn is logged; a clearly-directed miss shows a chip)
    heard: d => {
      voice.decided(d.outcome, d.text, d);   // [P0] the bar's "Thinking" waits for this; an ignored turn leaves no trace
      // not for us: a held tour plays on. [0.4.1] room talk on a guess or a choice (the router's crew_talk) says so
      // a quiet exact answer comes back as one chip (crewpick.js); anything else heard clears an old one
      if (d.reason === "crew_talk" && d.pick) crewPick.show(d.pick); else crewPick.hide();
      if (d.outcome === "ignore") { if (d.notice) voice.notice(d.reason === "crew_talk" ? CREW_TALK : undefined); releaseHold(600); return; }
      // [P0] kid text is masked wherever it shows: a turn Arc Tagger's safety tags flagged (d.safety) shows nothing at
      // all; the offline word list catches what the tagger misses (profanity.js)
      const shownText = d.safety ? "" : maskProfanity(d.text);
      if (shownText) {
        if (window.__outpost && window.__outpost.captions) window.__outpost.captions.log("kid", shownText);
        showHeard(shownText);
        if (missionUI.running) missionUI.radioKid(shownText);
      }
      // [0.6] a hesitant turn (fillers, a long pause): the next hint rung comes sooner, once per step (never said why)
      if (d.hes) { if (missionUI.running) missionUI.hesitant(); if (academyUI.active) academyUI.hesitant(); }
      cancelNudge();
      // [audit2] "next" during the Library tour stopped the tour (this ran before the nav it decided): a flow intent
      // (next, back, resume, pause, repeat, yes) is the flow's own; anything else pauses it (never ends it)
      if (!(d.outcome === "navigate" && FLOW_NAV.includes(d.intent))) cancelTour(d.outcome === "navigate" ? "router" : "question");
    },
    nav: d => runNav(d.intent, d.arg, d.text),
    answer: d => {   // an explorer answer outside the cabin: the client renders it (artifacts, tours, crew audio)
      if (videoOpen()) return;   // [media]
      const r = d.r || {}, my = ++turn.seq;
      if (missionUI.active) { card.show({ title: "CAPCOM", asked: d.asked, say: r.source === "none" ? `${r.say} ${TRY}` : r.say }); guideSay(r.say, { voice: CAPCOM_VOICE }); return; }
      if (academyUI.active) { card.show({ title: "CAPCOM", asked: d.asked, say: r.source === "none" ? `${r.say} ${TRY}` : r.say, claims: r.claims }); guideSay(r.say, { voice: CAPCOM_VOICE }); return; }
      act(r, d.asked, my);
    },
  };

  // [input] A router decision is a voice intent on the bus: screens (onIntent, priority 10) get it first, then the
  // shell's defaults, then shellNav below (input/defaults.js). Gestures and keys emit the same intents.
  const runNav = (intent, arg, text) => emitIntent(intent, { arg, text }, "voice");
  // [0.4.1] the crew-talk chip: a lesson option is tapped as it is on screen; a Now-card choice goes as its label
  const crewPick = createCrewPick(document, p => {
    const opt = p.choice != null && document.querySelector(`#aPanel .a-choice[data-c="${CSS.escape(String(p.choice))}"]:not([disabled])`);
    if (opt) { opt.click(); return true; }
    if (p.choice == null && p.label) { emitIntent("task_choice", { arg: p.label, text: p.label }, "tap"); return true; }
    return false;
  });
  try { (window.__outpost = window.__outpost || {}).crewPick = crewPick; } catch (e) { /* no window */ }   // tools / tests
  // Enter (keys emit "select" on the focused control) and controller A use the chip while it has focus
  onIntent("select", () => (crewPick.pick && crewPick.el && document.activeElement === crewPick.el ? (crewPick.el.click(), true) : false), { priority: 50 });
  /** What was heard, shown briefly in the comm strip (never a transcript; the full log is in Access → Transcript). */
  let heardT = 0;
  function showHeard(text) {
    const w = $("liveWords"); if (!text || voice.kidTalking) return;
    paintLinked(w, text, voice.links ? voice.links() : []); w.classList.add("is-heard"); clearTimeout(heardT);
    heardT = setTimeout(() => { if (w.classList.contains("is-heard")) { w.classList.remove("is-heard"); w.textContent = ""; } }, 2600);
  }
  new MutationObserver(() => { if (document.getElementById("askbar").classList.contains("is-hearing")) $("liveWords").classList.remove("is-heard"); })
    .observe($("askbar"), { attributes: true, attributeFilter: ["class"] });
  // Model warming up: until the model server reports the ear and the voice loaded, the voice bar says so (typing works).
  // [0.3.12] A failed ear is "Voice off · type" at once (engine.js warmState: the health's load error, or the ear's
  // first {"t":"error"} in voice.js), never minutes of "Starting voice…"; after ~3 min of no answer it is off too.
  // /api/health is local; polled every 2 s while warming, every 30 s once off (a fixed ear clears it).
  const paintVoice = st => {
    const bar = $("askbar"), off = st === "off" || (st !== "ready" && earFailed());
    bar.classList.toggle("is-warming", st === "warming" && !off);
    bar.classList.toggle("is-voiceoff", off);
    if (off) $("spaceHint").lastElementChild.textContent = VOICE_FIX;
  };
  let voiceSt = "warming";
  onEarFailed(on => paintVoice(on ? "off" : voiceSt));
  (function warm(t0 = performance.now()) {
    fetch("/api/health").then(r => r.json()).then(h => {
      voiceSt = warmState(h, performance.now() - t0);
      if (voiceSt !== "warming") setEarFailed(voiceSt === "off");   // voice.js's hint follows (engine.earNote)
      paintVoice(voiceSt);
      if (voiceSt !== "ready") setTimeout(() => warm(t0), voiceSt === "warming" ? 2000 : 30000);   // [qa] QA-57: back off once "Voice off"
    }).catch(() => { voiceSt = performance.now() - t0 < WARM_MS ? "warming" : "off"; paintVoice(voiceSt); setTimeout(() => warm(t0), voiceSt === "warming" ? 2000 : 30000); });
  })();
  // [#87] The desktop shell's engine state (engine.js): "Ear restarting…" / "Voice off · type" on the voice bar.
  const paintEngine = st => { const bar = $("askbar"); for (const [c, on] of Object.entries(askbarClasses(st))) bar.classList.toggle(c, on); };
  onEngine(paintEngine);
  paintEngine(engineState());   // [ipad] a shell's boot state (engine.js __lunaEngineBoot) paints before any change
  // Cards keep clear of the voice strip, whose height changes as the caption comes and goes (--strip-h).
  new ResizeObserver(() => { const a = $("askbar"); if (a.closest("#stage")) $("stage").style.setProperty("--strip-live", a.offsetHeight + "px"); }).observe($("askbar"));
  // A spoken line that is already on screen (the lesson question, the feedback, the brief, [0.3.12] the lead and the
  // "New" line) is not shown twice: the
  // caption stays in #captionBar for screen readers and the transcript, but folds out of the voice strip (.is-dup).
  const norm = t => String(t || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const onScreen = () => norm([...document.querySelectorAll("#aPanel .a-prompt, #aPanel .a-feedback, #aPanel .a-brief p, #aPanel .a-lead, #aPanel .a-intro, #aPanel .m-title, #card:not([hidden]) .card-say")]
    .filter(e => e.getClientRects().length).map(e => e.textContent).join(" | "));
  const dupCheck = () => { const bar = $("captionBar"), line = norm((bar.querySelector(".cap-line") || bar).textContent);
    bar.classList.toggle("is-dup", !!line && line.length > 3 && onScreen().includes(line)); };
  new MutationObserver(dupCheck).observe($("captionBar"), { childList: true, subtree: true });
  new MutationObserver(dupCheck).observe($("aPanel"), { childList: true, subtree: true });
  /** [hands-free] Run a navigation intent the router chose (screen-first, then app-wide). */
  async function shellNav(intent, arg, text) {
    // [flows] "continue" / "stop" reached no flow (it ended meanwhile): "continue" is the screen's start, "stop" hushes
    if (intent === "pause") { if (isSpeaking()) stopSpeaking("voice_pause"); return; }
    if (intent === "resume") intent = "start";
    if (intent === "mute_sound" || intent === "unmute_sound") { setMuted(intent === "mute_sound"); return; }
    const a11yCmd = { repeat: "say that again", slower: "slower", faster: "faster", settings: "settings" }[intent];
    if (a11yCmd) { if (a11y) await a11y.handleText(a11yCmd); return; }
    if (intent === "a11y") { if (vbar && vbar.handleText(text)) return; if (a11y) await a11y.handleText(text); return; }
    if (intent === "answer") {
      if (academyUI.active) await academyUI.answerText(text);
      return;
    }
    if (intent === "brain") { if (brain) { const was = brain.isOpen; brain.toggle(); if (!was && text) guideSay(BRAIN_COPY.say, { voice: CAPCOM_VOICE }); } return; }   // [brain] B, voice "my brain"
    if (intent === "academy") { setMode("academy"); return; }
    if (intent === "library") { setMode("cadet"); return; }
    if (intent === "go_mission") { setMode("mission"); return; }
    if (academyUI.active && academyUI.nav(intent, arg)) return;
    if (missionUI.active && missionLearning.nav(intent, arg)) return;   // the first-mission Moon Base card, if it's up
    if (missionUI.active && missionUI.nav(intent, arg)) return;
    const mode = document.body.dataset.mode;
    if (intent === "lesson" || intent === "map") { setMode("academy"); setTimeout(() => academyUI.nav(intent, arg), 400); return; }
    if (intent === "accept_offer" && arg === "mission") { setMode("mission"); return; }
    if (["take_command", "pick_site", "debrief", "fly_again"].includes(intent) && mode !== "mission") {
      setMode("mission"); setTimeout(() => missionUI.nav(intent, arg), 600); return;
    }
    if (intent === "back" && mode === "cadet") { setMode(lastMode); return; }
  }
  // [flows] test hooks (tests/e2e/flows_e2e.py): the Library tour's state, and a barge-in / its end as voice.js makes them
  Object.assign(window.__outpost, { flowTest: { tour: () => ({ active: tour.active, paused: tour.paused, held: tour.held, i: tour.i, n: tour.stops.length, why: tour.why }),
    barge: () => onBarge(), kidDone: () => onKidDone() } });
  // test hooks (tests/e2e/robustness_e2e.py): drive a screen the way the router would, and start a crew clip
  try { Object.assign((window.__outpost = window.__outpost || {}), { shellNav, hear: t => ask(t, "voice", { dd: 1 }),
    playCrew: async () => { const ms = await api.moments(null); if (ms[0]) { stopSpeaking("play_crew"); player.play(ms[0]); return true; } return false; } }); } catch (e) { /* */ }
  // [hands-free] The router needs the screen the kid is looking at (server-relayed ear turns arrive before the client's).
  let lastScreen = "";
  function screenFrame() {
    const vn = videoNow(); if (vn) return { screen: "video", video: vn.id };   // [media] the router takes only pause / play / skip / stop
    const m = document.body.dataset.mode;
    if (m === "cadet") return { screen: "library", ...flowFrame() };
    const f = m === "academy" ? academyUI.screen() : (missionLearning.screen() || missionUI.screen());
    return { ...(f || { screen: m === "academy" ? "map" : "brief" }), ...flowFrame() };   // [flows] flow / flow_state for the router
  }
  function pushScreen(force) {
    if (!useSession()) return;
    const f = screenFrame(), k = JSON.stringify(f);
    if (force || k !== lastScreen) { lastScreen = k; session.ui("screen", f); }
  }
  setInterval(() => pushScreen(false), 400);
  Object.assign(window.__outpost = window.__outpost || {}, { screenFrame, floor, globe, missionUI, academyUI });   // what tests read (tools/*.py; academyUI: the cockpit patch key e2e)

  // ---- [input] defaults for every intent, the keyboard source, and camera gestures (off until Settings turns them on) ----
  const inCabin = () => missionUI.running && document.body.dataset.cabin === "1";
  installDefaultIntents({
    nav: shellNav, globe, inCabin, a11y, ask: t => ask(t), mission: missionUI, lookTarget,   // the cabin: missionUI.intent()
    stopAll: () => { cancelNudge(); cancelTour("voice"); if (isSpeaking()) stopSpeaking("stop_all"); if (player.active) player.stop(true); if (useSession()) session.dropAll(); },
  });
  installKeyboardIntents();
  // [keys] arrows / Enter / Esc / letters and game controllers emit the same intents (docs/KEYBOARD.md)
  const keys = installKeys({ globe, places, mission: missionUI, inCabin, cabinPanel, a11y });
  installGamepad({ settings: () => keys.settings, repeatMs: () => REPEAT_MS[keys.settings.repeat], inCabin,
    setMode: () => { document.documentElement.dataset.input = "pad"; },
    onConnect: on => { keys.padConnected(on); keys.toast(on ? "Controller connected" : "Controller disconnected"); } });
  // Flows (the Library tour, the cabin tour, a crew clip, a paused mission): pause / resume / step for every device
  installFlowIntents();
  // [story] "What do I do?" outside a lesson: one spoken line for the screen (Mission answers its own screens first).
  onIntent("help", () => { const m = document.body.dataset.mode, t = m === "academy" ? academyUI.whatNow() : m === "cadet" ? HELP.library : null;
    if (!t) return false; guideSay(t, { voice: CAPCOM_VOICE }); return true; }, { priority: 5 });
  // [gestures] Settings → Camera & gestures registers itself (settingsSections); the camera chip sits next to the gear.
  initGestures({
    screen: screenFrame, inCabin, isSpeaking, cabinPanel,
    onGesture: id => { if (useSession()) session.ui("gesture", { id }); },   // round 8: {"t":"ui","event":"gesture","id"}
    indicatorBefore: $("a11yBtn"), addObstacle: sel => vbar && vbar.addObstacle && vbar.addObstacle(sel),
    announce: t => { if (a11y) a11y.describe(t, { quiet: true }); },
  });
  // ---- end [input] ----
  if (SESSION_ON) {
    let reconnect = () => {};
    session = createSession({ handlers, reportsPlayback: !!floor, onClose: () => { console.warn("session closed; /api/ask fallback (retrying)"); reconnect(); } });
    // The floor reports playback (guide + crew) and holder changes; forward them on /ws/session.
    // [qa] QA-74: the socket can fail (session = null below): forwarding then threw a TypeError on every playback event
    if (floor) { floor.on("playback", e => { if (session) session.playback(e); }); floor.on("floor", e => { if (!session) return; if (e && e.holder === "kid") session.ui("barge_in"); else if (e && e.holder === "none") session.ui("kid_done"); }); }
    let m0 = "mission"; try { m0 = localStorage.getItem("atm-mode") === "cadet" ? "cadet" : "mission"; } catch (e) { /* private mode */ }
    session.hello({ mode: m0 });
    // [P0] the router lives in the session: without it, open-mic turns had no gate but the client's. If the socket
    // can't connect (the backend still starting), keep retrying with a back-off instead of staying on /api/ask for good.
    const sess = session;
    const up = () => { session = sess; voice.sendContext({ t: "context", session: sess.id }); pushScreen(true); sendPrefs(); };   // the ear posts its turns into this session
    let retrying = false;
    const retry = (n = 0) => { retrying = true; setTimeout(() => {
      sess.hello({ mode: document.body.dataset.mode || "academy", mission_id: (missionUI.context() || {}).id || null });   // sent on open
      sess.connect(5000).then(ok => { if (ok) { retrying = false; up(); } else retry(n + 1); });
    }, Math.min(30000, 2000 * 2 ** n)); };
    reconnect = () => { if (!retrying) retry(); };
    sess.connect().then(ok => {
      if (ok) { up(); return; }
      session = null; console.info("session socket unavailable; using /api/ask (retrying)"); retry();
    });
  }

  $("cardClose").addEventListener("click", () => { if (tour.active) { closeTour("button"); card.hide(); } if (isSpeaking()) stopSpeaking("card_close"); if (player.active) player.stop(true); });   // [qa] closing the card ends what it was saying
  $("askForm").addEventListener("submit", e => { e.preventDefault(); ask($("q").value); });
  if (onMoon) CHIPS.forEach(c => { const b = document.createElement("button"); b.type = "button"; b.textContent = c; b.onclick = () => ask(c); $("chips").append(b); });
  $("nearBtn").onclick = () => (fieldLib ? fieldLib.enter() : globe.flyTo(0, 0, 3.6));
  $("farBtn").onclick = () => (fieldLib ? globe.flyTo(30, -100, 3.6) : globe.flyTo(0, 180, 3.6));
  if (!onMoon) {   // [courses] a globe without Moon hardware: no Hardware switch; Near / Far side become the region / the whole globe
    HELP.library = `Tap a place on ${bodyName}, or ask a question.`;
    $("hwBtn").hidden = true; $("nearBtn").textContent = "The region"; $("farBtn").textContent = `Whole ${bodyName}`;
    document.querySelector(".hud").setAttribute("aria-label", `${bodyName} library`);
  }
  $("pinsBtn").onclick = e => { e.currentTarget.setAttribute("aria-pressed", globe.togglePins()); };
  $("hwBtn").onclick = e => { const on = globe.toggleHardware(); e.currentTarget.setAttribute("aria-pressed", on); };
  // Client tour of every piece of hardware, oldest first (the Director can also start a tour with action "tour").
  $("tourBtn").onclick = () => {
    if (tour.active) { if (tour.paused) resumeTour("button"); else pauseTour("button"); return; }
    if (fieldLib) { fieldLib.tour(); return; }   // [courses] the course's own site tour
    // [qa] 36 stops was ~4 minutes: a short tour of firsts, oldest first (the rest stay a tap away on the globe)
    const all = places.filter(p => p.kind === "artifact"), pick = TOUR_IDS.map(id => all.find(a => a.id === id)).filter(Boolean);
    const hw = (pick.length >= 4 ? pick : all).sort((a, b) => String(a.landed).localeCompare(String(b.landed)));
    if (!globe.hardwareOn) $("hwBtn").click();
    runTour(hw.map(a => a.id), `Here is some of the hardware people left on the Moon. ${hw.length} stops.`);
  };

  // ---------- modes: Mission (the headline) and Cadet (the explorer, as training) ----------
  let lastMode = "academy";
  const PH = { mission: "Type an order", cadet: `Ask about ${onMoon ? "the Moon" : bodyName}`, academy: "Type instead" };
  function setMode(mode) {
    const m = ["cadet", "academy"].includes(mode) ? mode : "mission";
    document.body.dataset.mode = m;
    $("modeMission").setAttribute("aria-pressed", m === "mission");
    $("modeAcademy").setAttribute("aria-pressed", m === "academy");
    $("libraryBtn").setAttribute("aria-pressed", m === "cadet");
    if (m !== "cadet") lastMode = m;
    $("q").placeholder = PH[m]; $("mShade").hidden = m !== "mission";
    globe.setDecor(m === "cadet");   // place dots + hardware belong to the Library; Flight School draws its own route
    // Suspend the screen we leave: its speech, tour / nudge timers, crew audio and its cards (the card belongs to the
    // screen it was shown on). Flight School keeps its lesson and resumes it on the way back (academyUI.exit/enter).
    closeTour("mode"); cancelNudge(); stopSpeaking("mode_switch"); card.hide();
    if (useSession()) session.dropAll();
    if (session) session.hello({ mode: m, mission_id: m === "mission" ? (missionUI.context() || {}).id || null : null });   // [session]
    if (m !== "academy") academyUI.exit();
    if (m === "academy") {   // Academy
      if (player.active) player.stop(true);
      if (missions.open) $("mClose").click();
      missionUI.exit(); card.hide(); academyUI.enter();
    } else if (m === "mission") {
      if (player.active) player.stop(true);
      if (missions.open) $("mClose").click();
      missionUI.enter();
    } else {
      $("pinsBtn").setAttribute("aria-pressed", globe.pinsOn !== false); $("hwBtn").setAttribute("aria-pressed", globe.hardwareOn);   // [qa]
      missionUI.exit(); card.hide();
      if (fieldLib && fieldLib.enter()) { /* the course's region, close, with its real picture and named places */ }
      else if (byId.orientale) globe.showFeature(byId.orientale, { dist: 3.3 });
    }
    screenInvariant();
    pushScreen(true);          // the router hears about the new screen now, not on the next 400 ms tick
  }
  // A lesson starts clean: an answer card left open from the map or the patch screen would sit over the step.
  addEventListener("outpost:lesson", () => card.hide());
  // "What do I do?" (a11y.js help): the Academy answers for its own screens (academy/ui.js); here, the rest.
  {
    const O = window.__outpost, academyHelp = O.help || (() => "");
    O.help = () => {
      const m = document.body.dataset.mode;
      if (m === "academy") return academyHelp();
      if (m === "cadet") return `Tap a place on ${onMoon ? "the Moon" : bodyName} to hear about it, or ask a question.`;
      const own = missionUI.whatNow && missionUI.whatNow();   // the cabin's objective strip, picker, debrief (docs/STORY.md)
      if (own) return own;
      const sc = (missionUI.screen && missionUI.screen()) || {};
      if (sc.screen === "debrief") return "Tap Fly again, or pick a new site.";
      if (sc.screen === "cabin") return "Set your power, then tap End shift.";
      return "Pick a site from the list, then tap Take command.";
    };
  }
  // The screen manager's one rule: only the current mode's cards may show. A stray card from another mode (a late
  // render, an answer graded after the switch) is hidden on sight; styles.css enforces the same by body[data-mode].
  const OWNED = { aPanel: "academy", mPanel: "mission", mDebrief: "mission", mBanner: "mission" };
  function screenInvariant() {
    const m = document.body.dataset.mode;
    for (const [id, owner] of Object.entries(OWNED)) {
      const e = $(id);
      if (e && owner !== m && !e.hidden) { e.hidden = true; console.warn(`[screen] hid #${id}: it belongs to ${owner}, the screen is ${m}`); }
    }
  }
  Object.keys(OWNED).forEach(id => { const e = $(id); if (e) new MutationObserver(screenInvariant).observe(e, { attributes: true, attributeFilter: ["hidden"] }); });
  (window.__outpost = window.__outpost || {}).screenInvariant = screenInvariant;
  $("modeMission").onclick = () => setMode("mission");
  $("modeAcademy").onclick = () => setMode("academy");
  // [courses] the chip names the course (hidden with one course installed); another course names its own school
  window.__outpost.courseSwitch = installCourseSwitch({ onMore: () => { try { dispatchEvent(new CustomEvent("outpost:course-storage")); } catch (e) { /* */ } }, more: () => moreCourses() });
  if (courseState.active !== "moon") $("modeAcademy").textContent = courseLabel("school", "Flight School");
  // The Moon library (the explorer) is a place you visit, not a mode: the button toggles back to where you were.
  $("libraryBtn").onclick = () => setMode(document.body.dataset.mode === "cadet" ? lastMode : "cadet");   // [qa] a second press goes back
  // A new cadet starts in the Academy; a qualified one in Mission.
  setMode(academyUI.progress.qualified ? "mission" : "academy");
}

boot();
