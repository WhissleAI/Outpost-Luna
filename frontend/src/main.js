// Wiring only: load places, build the modules, route asks / taps / voice turns between them.
import "./tokens.css";
import "./styles.css";
import "./outpost.css";
import "./mission.css";
import { api, normMoment, hwType } from "./api.js";
import { SAMPLE_ARTIFACTS } from "./dev-artifacts.js";
import { createGlobe } from "./globe.js";
import { createCard, readoutLine } from "./card.js";
import { createPlayer } from "./player.js";
import "./floor.css";               // the voice bar's styles (was imported by voice.js; kept in the same cascade order)
import { createVoice } from "./voice.js";
import { createMissions } from "./missions.js";
import { initAbout } from "./about.js";
import { createMissionUI } from "./mission/ui.js";
import { createAcademyUI } from "./academy/ui.js";   // Academy
import { APP_NAME, APP_TAGLINE } from "./brand.js";
import { callSign, HELP } from "./story.js";
import { chime } from "./sound.js";
// ---- audio floor (floor.js owns guide/crew/effects; docs/SESSION_CONTRACT.md §3-4) ----
import { speak, stopSpeaking, isSpeaking, STORY_VOICE, CAPCOM_VOICE, floor, sayStyle } from "./floor.js";
// ---- end audio floor ----
import { createSession } from "./session.js";
// ---- [a11y] accessibility, captions, key-span highlighting, Space words (docs/ACCESSIBILITY.md) ----
import "./a11y.css";
import { initA11y } from "./a11y.js";
import { initCaptions } from "./caption.js";
import { initHighlight } from "./highlight.js";
import { initVoiceBar } from "./voicebar.js";
import { createPrefs } from "./prefs.js";
import "./academy/vocab.js";
import "./academy/globe_steps.js";   // [learning-v3] globe step renderers (docs/LEARNING_DESIGN.md §3)
// ---- end [a11y] ----
// ---- [input] one intent bus for voice, tap, keys and camera gestures (docs/GESTURES.md) ----
import { emitIntent, onIntent } from "./input/intents.js";
import { installDefaultIntents, installKeyboardIntents, cabinPanel } from "./input/defaults.js";
import { lookTarget } from "./gesture/bind.js";
import { initGestures } from "./gesture/ui.js";
// ---- end [input] ----

// [session] The session Director (docs/SESSION_CONTRACT.md) is ON unless ?session=0 or localStorage atm-session=0.
// If its socket fails, mission turns fall back to POST /api/ask exactly as before.
const SESSION_ON = (() => { try { return new URLSearchParams(location.search).get("session") !== "0" && localStorage.getItem("atm-session") !== "0"; } catch (e) { return true; } })();

const $ = id => document.getElementById(id);
const CHIPS = ["Where did Apollo 11 land?", "Show me the rovers", "Play the launch"];
const HW_LABEL = { lander: "Lander", rover: "Rover", impact: "Impact site", instrument: "Instrument", memorial: "Memorial" };
const TOUR_MS = 3000;   // minimum time at each tour stop
// Shown on the card with "I don't know that one yet", never spoken (a spoken example is heard back by the open mic).
const TRY = "Try: “show me the giant bullseye” or “where did Apollo 11 land?”";
/** Mirrors turn_router.clear_question: a wh- / "tell me" / "can you" question of ≥ 3 words. */
const clearQuestion = t => { const q = String(t || "").toLowerCase().replace(/[^a-z0-9 ?]/g, " ").replace(/\s+/g, " ").trim();
  return q.split(" ").length >= 3 && (/^(what|where|when|why|who|whose|which|how)\b/.test(q) || /^(tell me|show me|can you tell|can you show|could you tell|explain|teach me)\b/.test(q)); };
/** First two sentences: a tour stop's short story. */
const shortStory = t => ((t || "").match(/[^.!?]+[.!?]+/g) || [t || ""]).slice(0, 2).join(" ").trim();

async function boot() {
  initAbout();
  const nameEl = document.querySelector(".appname");
  if (nameEl) { nameEl.textContent = APP_NAME; nameEl.title = APP_TAGLINE; }
  // The askbar shows the kid's call sign (local only).
  const csTag = $("csTag"), paintCs = () => { const c = callSign.get(); csTag.textContent = c; csTag.hidden = !c; };
  paintCs(); addEventListener("outpost:callsign", paintCs);
  let places;
  try { places = await api.places(); }
  catch (e) { $("loading").innerHTML = "<b>Can&rsquo;t reach Outpost Luna</b><span>Close the app and open it again.</span>"; $("loading").classList.add("is-error"); return; }
  // Until the backend ships hardware, the UI runs on clearly labelled sample artifacts.
  const sample = !places.some(p => p.kind === "artifact");
  if (sample) places = places.concat(SAMPLE_ARTIFACTS.map(a => ({ ...a, km: 0, hw: hwType(a) })));
  const byId = Object.fromEntries(places.map(f => [f.id, f]));
  const placeById = id => byId[id] || null;
  (window.__outpost = window.__outpost || {}).placeById = placeById;   // [learning-v3] globe step directives

  const turn = { lastPlace: null, emotion: null, seq: 0, lastUnknown: -1e9 };
  const card = createCard();
  const globe = createGlobe({ stage: $("stage"), label: $("label"), loading: $("loading"), places, onTap, onArtifact });
  const player = createPlayer({
    api, globe, placeById, isKidTalking: () => voice.kidTalking,
    onPlace: id => { turn.lastPlace = id; }, onEnd: scheduleNudge,
  });
  const voice = createVoice({
    onTurn: (text, o = {}) => ask(text, "voice", o),
    onBargeIn: () => { cancelNudge(); cancelTour(); if (isSpeaking()) stopSpeaking(); player.duck(); if (useSession()) { session.dropAll(); session.ui("barge_in"); } },
    onKidDone: () => { player.unduck(); if (useSession()) session.ui("kid_done"); },
    onEmotion: label => { turn.emotion = label; },
    isOutputBusy: () => isSpeaking() || player.active,
    screen: () => screenFrame(),          // the pending offer / open step: their reply is never an echo of the tail
  });
  // [session] the socket, its decision handlers, and the hooks the mission UI calls.
  let session = null;
  const useSession = () => !!(session && session.connected);
  const missionUI = createMissionUI({
    globe, card, placeById, say: (t, style) => guideSay(t, { voice: CAPCOM_VOICE, style }) /* audio floor: CAPCOM voice, Director style */,
    onContext: f => voice.sendContext(session ? { ...f, session: session.id } : f), askDirector: t => ask(t),
    alertSound: () => { chime(); setTimeout(chime, 220); setTimeout(chime, 440); },
    academy: { badges: () => academyUI.badges(), has: id => academyUI.has(id) },   // Flight School patches carry over
    session: {
      onStart: st => { if (useSession()) session.hello({ mode: "mission", mission_id: st.id, role: (missionUI.context() || {}).role || null }); },
      endShift: () => useSession() && session.ui("end_shift"),
    },
  });
  // Academy: lessons before the mission; the check ride qualifies the cadet for Mission mode.
  const academyUI = createAcademyUI({
    globe, placeById, player, say: (t, style, o = {}) => guideSay(t, { voice: CAPCOM_VOICE, style, repeat: o.repeat, source: "academy" }) /* floor.say, CAPCOM voice, steered */, stop: () => stopSpeaking(),
    alertSound: () => { chime(); setTimeout(chime, 220); setTimeout(chime, 440); },
    goMission: () => setMode("mission"),
    openLibrary: id => { setMode("cadet"); const a = placeById(id); if (a) setTimeout(() => (a.kind === "artifact" ? onArtifact(a) : onTap(a)), 300); },
    onProgress: p => { document.body.dataset.qualified = p.qualified ? "1" : ""; },
  });
  document.body.dataset.qualified = academyUI.progress.qualified ? "1" : "";
  const missions = createMissions({ globe, placeById, places, say: t => guideSay(t), onFound: f => { turn.lastPlace = f.id; } });

  // ---- [a11y] settings + voice commands + audio description, captions, highlights ----
  const a11ySay = (t, o = {}) => o.describe
    ? (floor ? floor.say(t, { voice: "guide", priority: 5, style: { situation: "explain" } }) : speak(t))
    : guideSay(t, { voice: CAPCOM_VOICE, style: o.situation ? { situation: o.situation, vocab: o.vocab } : undefined, keepCrew: true,
      repeat: true /* "say that again", a word's "hear it" button: asked for on purpose */, source: "a11y" });
  const a11y = initA11y({ floor, say: a11ySay, ask: t => ask(t), setMode: m => setMode(m), tap: p => (p.kind === "artifact" ? onArtifact(p) : onTap(p)), places, playCrew: m => player.play(m) });
  if (a11y) a11y.wrapGlobe(globe, placeById);
  initCaptions({ floor, settings: () => (a11y ? a11y.settings : {}) });
  const vbar = initVoiceBar({ announce: t => { if (a11y) a11y.describe(t); } });   // the floating voice bar
  // Settings v1 (prefs.js): voice, sound, listening, display, level, cadet profiles. The session gets the steering bits.
  const prefs = createPrefs({ globe });
  (window.__outpost = window.__outpost || {}).prefsApi = prefs;
  const sendPrefs = () => { if (useSession()) session.sendRaw(prefs.wire(a11y ? a11y.settings.speed : 1)); };
  prefs.on(() => sendPrefs());
  // the opt-in turn log (prefs.improve): the Academy's grade of a step, so the server can mark a step that went to hint
  addEventListener("outpost:lesson-result", e => { if (prefs.value.improve && useSession() && e.detail) session.sendRaw({ t: "ui", event: "lesson_result", status: e.detail.status, step_type: e.detail.step_type }); }); addEventListener("outpost:a11y", e => { if (e.detail && "speed" in e.detail) sendPrefs(); });
  initHighlight({ api, say: a11ySay, playCrew: m => { stopSpeaking(); player.play(m); }, flyTo: id => { const f = placeById(id); if (f) { globe.showFeature(f); turn.lastPlace = f.id; } } });
  // ---- end [a11y] ----

  /** The guide speaks (card text is the caption). Never over crew audio: the moment ends first. */
  async function guideSay(text, { keepCrew, voice: v, style, repeat, source } = {}) {
    if (!text) return false;
    if (!keepCrew && player.active) player.stop(true);
    voice.show("speaking");
    const ok = await speak(text, { ...(v || {}), style: style || (turn.emotion ? { emotion: turn.emotion } : undefined), repeat, source });
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
    const heard = source === "voice";
    // [hands-free] One router for every turn (backend/app/turn_router.py): with a live session, every turn (spoken or
    // typed, in every screen) goes up the socket with the current screen; the Director answers with nav / answer /
    // say decisions, or stays silent. Echo, filler and chatter never reach the screens.
    if (useSession()) {
      if (!heard && a11y && await a11y.handleText(text)) { $("q").value = ""; return; }   // typed a11y commands stay local
      $("q").value = ""; pushScreen(true);
      session.typed(text, opts.ptt ? "ptt" : heard ? "voice" : "typed"); voice.clearWords(); voice.show("idle"); return;
    }
    const my = ++turn.seq; cancelNudge(); cancelTour();
    $("q").value = ""; voice.show("thinking");
    if (window.__outpost && window.__outpost.captions) window.__outpost.captions.log("kid", text);   // [a11y] transcript
    if (a11y && await a11y.handleText(text)) { voice.clearWords(); voice.show("idle"); return; }   // [a11y] "where am I?", "faster", "press next"
    if (missionUI.active && await missionUI.handleText(text)) { voice.clearWords(); voice.show("idle"); return; }
    if (academyUI.active && await academyUI.handleText(text)) { voice.clearWords(); voice.show("idle"); return; }   // Academy
    // [session] Mission mode with a live session: the turn goes up the socket; decisions come back on their own.
    if (missionUI.active && missionUI.running && !missionUI.sample && useSession()) {
      session.typed(text, source); voice.clearWords(); voice.show("idle"); return;
    }
    let r;
    try { r = await api.ask(text, context()); }
    catch (e) {
      if (my === turn.seq) { card.show({ title: "Hmm", asked: text, say: "I can't reach my brain right now. Is the backend running?" }); voice.show("idle"); }
      return;
    }
    for (let w = 0; voice.kidTalking && w < 100; w++) await new Promise(res => setTimeout(res, 100));   // WAIT
    if (my !== turn.seq) return;
    // [hands-free] no session: the "I don't know" fallback only for a clear spoken question, at most once per 30 s.
    if (heard && (r.source === "none" || (r.action === "ask" && r.readout && r.readout.brain && /ask|unknown/.test(r.readout.brain.status)))) {
      if (!clearQuestion(text) || (r.source === "none" && performance.now() - turn.lastUnknown < 30000)) { voice.clearWords(); voice.show("idle"); return; }
      if (r.source === "none") turn.lastUnknown = performance.now();
    }
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
    const add = m => m && card.addAction(token, { label: "Hear the crew", hot: true, onClick: () => { stopSpeaking(); player.play(m); } });
    if (moment) add(moment);
    else if (f) api.moments(f.id).then(ms => add(ms[0]));
  }

  /** ASK: options preview-fly the globe; a tap re-asks with that place name. */
  function askCard(r, asked, arc) {
    const q = r.ask.question || r.say, opts = (r.ask.options || []).map(placeById).filter(Boolean);
    card.show({
      title: "Did you mean…", asked, say: q, arc,
      actions: opts.map(f => ({ label: f.name, hot: true, once: true, onPreview: () => globe.showFeature(f), onClick: () => { turn.lastPlace = f.id; ask(f.name); } })),
    });
    guideSay(q);
    opts.forEach((f, i) => setTimeout(() => { if (!voice.kidTalking) globe.showFeature(f); }, 400 + i * 1600));
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
      onClick: () => { cancelTour(); stopSpeaking(); player.play({ clip_id: v.clip_id, t0: v.t0, t1: v.t1, speaker: v.who || "crew", places: [a.id], jargon: [] }); },
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
    cancelTour(); cancelNudge();
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

  // ---------- tour: fly through stops one by one; kid speech, Space, a tap or a new question cancels it ----------
  const tour = { id: 0, active: false, stops: [], i: -1, timer: null, token: 0 };
  function cancelTour(note) {
    if (!tour.active) return;
    tour.active = false; tour.id++; clearTimeout(tour.timer);
    $("tourBtn").setAttribute("aria-pressed", "false");
    card.update(tour.token, { actions: [], eyebrow: note || "Tour stopped" });
  }
  async function runTour(ids, intro, { asked, arc } = {}) {
    const stops = (ids || []).map(placeById).filter(Boolean);
    if (!stops.length) { card.show({ title: "Guide", asked, say: intro, arc }); await guideSay(intro); return; }
    cancelTour(); cancelNudge(); ++turn.seq;
    Object.assign(tour, { active: true, stops, i: -1 }); const my = ++tour.id;
    $("tourBtn").setAttribute("aria-pressed", "true");
    if (intro) {
      tour.token = card.show({ title: "Hardware tour", eyebrow: `Tour · ${stops.length} stops`, asked, say: intro, arc, actions: tourActions(), transient: true });
      if (player.active) player.stop(true);
      await guideSay(intro);
    }
    tourStep(my, 0);
  }
  function tourActions() {
    return [
      { label: "Next ›", hot: true, onClick: () => { if (!tour.active) return; stopSpeaking(); tourStep(++tour.id, tour.i + 1); } },
      { label: "Stop", onClick: () => { stopSpeaking(); cancelTour(); } },
    ];
  }
  async function tourStep(my, i) {
    if (my !== tour.id || !tour.active) return;
    if (i >= tour.stops.length) { cancelTour("Tour done"); scheduleNudge(); return; }
    tour.i = i; const a = tour.stops[i], hw = a.kind === "artifact";
    chime(); globe.showFeature(a); turn.lastPlace = a.id;
    const extra = { eyebrow: `Tour · stop ${i + 1} of ${tour.stops.length}`, actions: tourActions(), transient: true };
    tour.token = card.show(hw ? artifactEntry(a, extra) : { title: a.name, place: true, say: a.fact, ...extra });
    const t0 = performance.now();
    if (hw) await storySay(shortStory(a.story)); else await guideSay(a.fact);
    if (my !== tour.id) return;
    tour.timer = setTimeout(() => tourStep(my, i + 1), Math.max(400, TOUR_MS - (performance.now() - t0)));
  }
  // Space always cancels a tour (even when a card button has focus).
  addEventListener("keydown", e => { if (e.code === "Space" && tour.active && !(e.target && e.target.closest && e.target.closest("input, textarea"))) { stopSpeaking(); cancelTour(); } }, true);

  function onTap(p) {
    if (missionUI.active) return;   // the globe is a map of the outpost in mission mode
    if (academyUI.onTap(p)) return;   // Academy
    voice.clearWords(); cancelTour();
    if (missions.onTap(p)) return;
    const { f, d } = globe.nearest(p);
    ++turn.seq;
    if (d < 12) {
      if (f.id !== turn.lastPlace) chime();
      globe.showFeature(f); turn.lastPlace = f.id;
      const token = card.show({ title: f.name, place: true, say: f.fact, arc: readoutLine({ source: "tap", action: "fly" }),
        note: f.est ? "Location estimated from the crew's own directions." : "" });
      offerCrew(token, f, null);
      guideSay(f.fact);
    } else {
      const say = `That spot is ${Math.abs(p.lat).toFixed(0)}° ${p.lat >= 0 ? "north" : "south"}, ${Math.abs(p.lon).toFixed(0)}° ${p.lon >= 0 ? "east" : "west"}. No named place is close. Try a darker or brighter patch!`;
      card.show({ title: "Unnamed spot", say }); guideSay(say);
    }
  }

  // NUDGE: 8 s of quiet after an answer
  let nudgeT = null;
  function cancelNudge() { clearTimeout(nudgeT); nudgeT = null; $("nudge").hidden = true; }
  function scheduleNudge() {
    clearTimeout(nudgeT);
    nudgeT = setTimeout(async () => {
      if (missionUI.active || academyUI.active) return;
      if (voice.kidTalking || isSpeaking() || player.active) return;
      const n = $("nudge");
      if (!missions.started && !missions.open) { n.textContent = "Try a mission?"; n.onclick = () => { cancelNudge(); missions.openCard(); }; n.hidden = false; return; }
      const ms = await api.moments(null), m = ms.find(x => x.places.some(p => p !== turn.lastPlace && byId[p])) || ms[0];
      if (!m) return;
      n.textContent = `Hear the crew at ${(byId[m.places[0]] || { name: "the Moon" }).name}?`;
      n.onclick = () => { cancelNudge(); player.play(m); }; n.hidden = false;
    }, 8000);
  }

  // ---------- [session] decisions → modules ----------
  const sendRaw = m => { if (!m) return; if (m.t === "typed") ask(m.text); else session.sendRaw(m); };
  const handlers = {
    // The floor manager is the only audio owner: say decisions go to floor.say() with the contract priority.
    say: async d => {
      if (d.delay_ms) { await missionUI.houston(d.text, +d.delay_ms, d.style); return true; }
      if (!floor) return guideSay(d.text, { voice: d.voice === "story" ? STORY_VOICE : d.voice === "capcom" ? CAPCOM_VOICE : undefined, style: d.style });
      if (player.active && (d.priority ?? 3) <= 3) player.stop(true);
      voice.show("speaking");
      const ok = await floor.say(d.text, { voice: d.voice || "guide", priority: d.priority ?? 3, id: d.id, style: d.style });
      voice.show("idle");
      return ok;
    },
    play: async d => { const m = normMoment(d.moment || { clip_id: d.clip_id, t0: d.t0, t1: d.t1, jargon: d.explain }); if (m) await player.play(m); },
    stop: () => { stopSpeaking(); if (player.active) player.stop(true); },
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
      if (d.outcome === "ignore") { if (d.notice) voice.notice(); return; }
      if (window.__outpost && window.__outpost.captions) window.__outpost.captions.log("kid", d.text);
      showHeard(d.text);
      if (missionUI.running) missionUI.radioKid(d.text);
      cancelNudge(); cancelTour();
    },
    nav: d => runNav(d.intent, d.arg, d.text),
    answer: d => {   // an explorer answer outside the cabin: the client renders it (artifacts, tours, crew audio)
      const r = d.r || {}, my = ++turn.seq;
      if (missionUI.active) { card.show({ title: "CAPCOM", asked: d.asked, say: r.source === "none" ? `${r.say} ${TRY}` : r.say }); guideSay(r.say, { voice: CAPCOM_VOICE }); return; }
      if (academyUI.active) { card.show({ title: "CAPCOM", asked: d.asked, say: r.source === "none" ? `${r.say} ${TRY}` : r.say, claims: r.claims }); guideSay(r.say, { voice: CAPCOM_VOICE }); return; }
      act(r, d.asked, my);
    },
  };

  // [input] A router decision is a voice intent on the bus: screens (onIntent, priority 10) get it first, then the
  // shell's defaults, then shellNav below (input/defaults.js). Gestures and keys emit the same intents.
  const runNav = (intent, arg, text) => emitIntent(intent, { arg, text }, "voice");
  /** What was heard, shown briefly in the comm strip (never a transcript; the full log is in Access → Transcript). */
  let heardT = 0;
  function showHeard(text) {
    const w = $("liveWords"); if (!text || voice.kidTalking) return;
    w.textContent = text; w.classList.add("is-heard"); clearTimeout(heardT);
    heardT = setTimeout(() => { if (w.classList.contains("is-heard")) { w.classList.remove("is-heard"); w.textContent = ""; } }, 2600);
  }
  new MutationObserver(() => { if (document.getElementById("askbar").classList.contains("is-hearing")) $("liveWords").classList.remove("is-heard"); })
    .observe($("askbar"), { attributes: true, attributeFilter: ["class"] });
  // Model warming up: until the model server reports the ear and the voice loaded, the voice bar says so (typing works).
  // After ~3 min without them it says voice is offline instead. /api/health is local; polled every 2 s while warming.
  (function warm(t0 = performance.now()) {
    const bar = $("askbar");
    fetch("/api/health").then(r => r.json()).then(h => {
      const m = (h.model_server && h.model_server.models) || {}, ear = m.arc_ear || {}, tts = m.steer_tts || {};
      const ready = !!(h.model_server && h.model_server.ok && ear.decoder_loaded !== false && tts.loaded !== false);
      bar.classList.toggle("is-warming", !ready && performance.now() - t0 < 180000);
      bar.classList.toggle("is-voiceoff", !ready && performance.now() - t0 >= 180000);
      if (!ready) setTimeout(() => warm(t0), 2000);
    }).catch(() => { bar.classList.add("is-warming"); if (performance.now() - t0 < 180000) setTimeout(() => warm(t0), 2000); else { bar.classList.remove("is-warming"); bar.classList.add("is-voiceoff"); } });
  })();
  // Cards keep clear of the voice strip, whose height changes as the caption comes and goes (--strip-h).
  new ResizeObserver(() => { const a = $("askbar"); if (a.closest("#stage")) $("stage").style.setProperty("--strip-live", a.offsetHeight + "px"); }).observe($("askbar"));
  // A spoken line that is already on screen (the lesson question, the feedback, the brief) is not shown twice: the
  // caption stays in #captionBar for screen readers and the transcript, but folds out of the voice strip (.is-dup).
  const norm = t => String(t || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const onScreen = () => norm([...document.querySelectorAll("#aPanel .a-prompt, #aPanel .a-feedback, #aPanel .a-brief p, #aPanel .m-title, #card:not([hidden]) .card-say")]
    .filter(e => e.getClientRects().length).map(e => e.textContent).join(" | "));
  const dupCheck = () => { const bar = $("captionBar"), line = norm((bar.querySelector(".cap-line") || bar).textContent);
    bar.classList.toggle("is-dup", !!line && line.length > 3 && onScreen().includes(line)); };
  new MutationObserver(dupCheck).observe($("captionBar"), { childList: true, subtree: true });
  new MutationObserver(dupCheck).observe($("aPanel"), { childList: true, subtree: true });
  /** [hands-free] Run a navigation intent the router chose (screen-first, then app-wide). */
  async function shellNav(intent, arg, text) {
    const a11yCmd = { repeat: "say that again", slower: "slower", faster: "faster", settings: "settings" }[intent];
    if (a11yCmd) { if (a11y) await a11y.handleText(a11yCmd); return; }
    if (intent === "a11y") { if (vbar && vbar.handleText(text)) return; if (a11y) await a11y.handleText(text); return; }
    if (intent === "answer") {
      if (academyUI.active) await academyUI.answerText(text);
      return;
    }
    if (intent === "academy") { setMode("academy"); return; }
    if (intent === "library") { setMode("cadet"); return; }
    if (intent === "go_mission") { setMode("mission"); return; }
    if (academyUI.active && academyUI.nav(intent, arg)) return;
    if (missionUI.active && missionUI.nav(intent, arg)) return;
    const mode = document.body.dataset.mode;
    if (intent === "lesson" || intent === "map") { setMode("academy"); setTimeout(() => academyUI.nav(intent, arg), 400); return; }
    if (intent === "accept_offer" && arg === "mission") { setMode("mission"); return; }
    if (["take_command", "pick_site", "debrief", "fly_again"].includes(intent) && mode !== "mission") {
      setMode("mission"); setTimeout(() => missionUI.nav(intent, arg), 600); return;
    }
    if (intent === "back" && mode === "cadet") { setMode(lastMode); return; }
  }
  // [hands-free] The router needs the screen the kid is looking at (server-relayed ear turns arrive before the client's).
  let lastScreen = "";
  function screenFrame() {
    const m = document.body.dataset.mode;
    if (m === "cadet") return { screen: "library" };
    const f = m === "academy" ? academyUI.screen() : missionUI.screen();
    return f || { screen: m === "academy" ? "map" : "brief" };
  }
  function pushScreen(force) {
    if (!useSession()) return;
    const f = screenFrame(), k = JSON.stringify(f);
    if (force || k !== lastScreen) { lastScreen = k; session.ui("screen", f); }
  }
  setInterval(() => pushScreen(false), 400);
  Object.assign(window.__outpost = window.__outpost || {}, { screenFrame, floor, globe });   // what tests read (tools/*.py)

  // ---- [input] defaults for every intent, the keyboard source, and camera gestures (off until Settings turns them on) ----
  const inCabin = () => missionUI.running && document.body.dataset.cabin === "1";
  installDefaultIntents({
    nav: shellNav, globe, inCabin, a11y, ask: t => ask(t), mission: missionUI, lookTarget,   // the cabin: missionUI.intent()
    stopAll: () => { cancelNudge(); cancelTour(); if (isSpeaking()) stopSpeaking(); if (player.active) player.stop(true); if (useSession()) session.dropAll(); },
  });
  installKeyboardIntents();
  // Library tour: next / previous stop (swipe, Alt+arrows, or "next" by voice) while a tour runs.
  const tourStepBy = d => { if (!tour.active) return false; stopSpeaking(); const i = Math.max(0, tour.i + d); tourStep(++tour.id, i); return true; };
  onIntent("next", () => tourStepBy(1), { priority: 10 });
  onIntent("prev", () => tourStepBy(-1), { priority: 10 });
  // [story] "What do I do?" outside a lesson: one spoken line for the screen (Mission answers its own screens first).
  onIntent("help", () => { const m = document.body.dataset.mode, t = m === "academy" ? academyUI.whatNow() : m === "cadet" ? HELP.library : null;
    if (!t) return false; guideSay(t, { voice: CAPCOM_VOICE }); return true; }, { priority: 5 });
  // [gestures] Settings → Camera & gestures registers itself (settingsSections); the camera chip sits next to the gear.
  initGestures({
    screen: screenFrame, inCabin, isSpeaking, cabinPanel,
    indicatorBefore: $("a11yBtn"), addObstacle: sel => vbar && vbar.addObstacle && vbar.addObstacle(sel),
    announce: t => { if (a11y) a11y.describe(t, { quiet: true }); },
  });
  // ---- end [input] ----
  if (SESSION_ON) {
    session = createSession({ handlers, reportsPlayback: !!floor, onClose: () => console.warn("session closed; /api/ask fallback") });
    // The floor reports playback (guide + crew) and holder changes; forward them on /ws/session.
    if (floor) { floor.on("playback", e => session.playback(e)); floor.on("floor", e => { if (e && e.holder === "kid") session.ui("barge_in"); else if (e && e.holder === "none") session.ui("kid_done"); }); }
    let m0 = "mission"; try { m0 = localStorage.getItem("atm-mode") === "cadet" ? "cadet" : "mission"; } catch (e) { /* private mode */ }
    session.hello({ mode: m0 });
    session.connect().then(ok => {
      if (!ok) { session = null; console.info("session socket unavailable; using /api/ask"); return; }
      voice.sendContext({ t: "context", session: session.id });   // [hands-free] the ear posts its turns into this session
      pushScreen(true); sendPrefs();
    });
  }

  $("askForm").addEventListener("submit", e => { e.preventDefault(); ask($("q").value); });
  CHIPS.forEach(c => { const b = document.createElement("button"); b.type = "button"; b.textContent = c; b.onclick = () => ask(c); $("chips").append(b); });
  $("nearBtn").onclick = () => globe.flyTo(0, 0, 3.6);
  $("farBtn").onclick = () => globe.flyTo(0, 180, 3.6);
  $("pinsBtn").onclick = e => { e.currentTarget.setAttribute("aria-pressed", globe.togglePins()); };
  $("hwBtn").onclick = e => { const on = globe.toggleHardware(); e.currentTarget.setAttribute("aria-pressed", on); };
  // Client tour of every piece of hardware, oldest first (the Director can also start a tour with action "tour").
  $("tourBtn").onclick = () => {
    if (tour.active) { stopSpeaking(); cancelTour(); return; }
    const hw = places.filter(p => p.kind === "artifact").sort((a, b) => String(a.landed).localeCompare(String(b.landed)));
    if (!globe.hardwareOn) $("hwBtn").click();
    runTour(hw.map(a => a.id), `Here is the hardware people left on the Moon. ${hw.length} stops!`);
  };

  // ---------- modes: Mission (the headline) and Cadet (the explorer, as training) ----------
  let lastMode = "academy";
  const PH = { mission: "Type an order", cadet: "Ask about the Moon", academy: "Type instead" };
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
    cancelTour(); cancelNudge(); stopSpeaking(); card.hide();
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
      missionUI.exit(); card.hide();
      if (byId.orientale) globe.showFeature(byId.orientale, { dist: 3.3 });
    }
    screenInvariant();
    pushScreen(true);          // the router hears about the new screen now, not on the next 400 ms tick
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
  // The Moon library (the explorer) is a place you visit, not a mode: the button toggles back to where you were.
  $("libraryBtn").onclick = () => setMode("cadet");
  // A new cadet starts in the Academy; a qualified one in Mission.
  setMode(academyUI.progress.qualified ? "mission" : "academy");
}

boot();
