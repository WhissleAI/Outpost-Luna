// Wiring only: load places, build the modules, route asks / taps / voice turns between them.
import "./styles.css";
import { api, normMoment, hwType } from "./api.js";
import { SAMPLE_ARTIFACTS } from "./dev-artifacts.js";
import { createGlobe } from "./globe.js";
import { createCard, readoutLine } from "./card.js";
import { createPlayer } from "./player.js";
import { createVoice } from "./voice.js";
import { createMissions } from "./missions.js";
import { initAbout } from "./about.js";
import { createMissionUI } from "./mission/ui.js";
import { chime, speak, stopSpeaking, isSpeaking, STORY_VOICE } from "./sound.js";

const $ = id => document.getElementById(id);
const CHIPS = ["Show me the rovers left on the Moon", "Where did Apollo 11 land?", "What did Surveyor 3 do?",
  "Who drove the Apollo 16 rover?", "What did the astronauts see?", "Play the launch"];
const HW_LABEL = { lander: "Lander", rover: "Rover", impact: "Impact site", instrument: "Instrument", memorial: "Memorial" };
const TOUR_MS = 3000;   // minimum time at each tour stop
/** First two sentences: a tour stop's short story. */
const shortStory = t => ((t || "").match(/[^.!?]+[.!?]+/g) || [t || ""]).slice(0, 2).join(" ").trim();

async function boot() {
  initAbout();
  let places;
  try { places = await api.places(); }
  catch (e) { $("loading").textContent = "Can't reach the backend. Start everything with `make dev`."; return; }
  // Until the backend ships hardware, the UI runs on clearly labelled sample artifacts.
  const sample = !places.some(p => p.kind === "artifact");
  if (sample) places = places.concat(SAMPLE_ARTIFACTS.map(a => ({ ...a, km: 0, hw: hwType(a) })));
  const byId = Object.fromEntries(places.map(f => [f.id, f]));
  const placeById = id => byId[id] || null;

  const turn = { lastPlace: null, emotion: null, seq: 0 };
  const card = createCard();
  const globe = createGlobe({ stage: $("stage"), label: $("label"), loading: $("loading"), places, onTap, onArtifact });
  const player = createPlayer({
    api, globe, placeById, isKidTalking: () => voice.kidTalking,
    onPlace: id => { turn.lastPlace = id; }, onEnd: scheduleNudge,
  });
  const voice = createVoice({
    onTurn: text => ask(text),
    onBargeIn: () => { cancelNudge(); cancelTour(); if (isSpeaking()) stopSpeaking(); player.duck(); },
    onKidDone: () => player.unduck(),
    onEmotion: label => { turn.emotion = label; },
    isOutputBusy: () => isSpeaking() || player.active,
  });
  const missionUI = createMissionUI({
    globe, card, placeById, say: t => guideSay(t), onContext: f => voice.sendContext(f),
    alertSound: () => { chime(); setTimeout(chime, 220); setTimeout(chime, 440); },
  });
  const missions = createMissions({ globe, placeById, places, say: t => guideSay(t), onFound: f => { turn.lastPlace = f.id; } });

  /** The guide speaks (card text is the caption). Never over crew audio: the moment ends first. */
  async function guideSay(text, { keepCrew, voice: v } = {}) {
    if (!text) return false;
    if (!keepCrew && player.active) player.stop(true);
    voice.show("speaking");
    const ok = await speak(text, v);
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
  const storySay = text => guideSay(text, { voice: STORY_VOICE });

  async function ask(raw) {
    const text = (raw || "").trim(); if (!text) return;
    const my = ++turn.seq; cancelNudge(); cancelTour();
    $("q").value = ""; voice.show("thinking");
    if (missionUI.active && await missionUI.handleText(text)) { voice.clearWords(); voice.show("idle"); return; }
    let r;
    try { r = await api.ask(text, context()); }
    catch (e) {
      if (my === turn.seq) { card.show({ title: "Hmm", asked: text, say: "I can't reach my brain right now. Is the backend running?" }); voice.show("idle"); }
      return;
    }
    for (let w = 0; voice.kidTalking && w < 100; w++) await new Promise(res => setTimeout(res, 100));   // WAIT
    if (my !== turn.seq) return;
    voice.clearWords();
    if (missionUI.active) {
      // Mission mode: the globe stays on the outpost. Non-mission answers are shown and spoken, without flying or touring.
      if (await missionUI.handleDirector(r)) { voice.show("idle"); return; }
      card.show({ title: "CAPCOM", asked: text, say: r.say || "Say a mission command, like “shields to 40” or “end shift”.", arc: readoutLine(r) });
      await guideSay(r.say); return;
    }
    await act(r, text, my);
  }

  async function act(r, asked, my) {
    const f = placeById(r.place), moment = normMoment(r.moment), say = r.say || "";
    const arc = readoutLine(r);
    if (r.action === "guard") { card.show({ title: "Let's keep that private", asked, say, arc }); await guideSay(say); scheduleNudge(); return; }
    if (r.action === "ask" && r.ask) { askCard(r, asked, arc); return; }
    if (r.action === "tour") { runTour(r.places, say, { asked, arc }); return; }
    if (f && f.kind === "artifact") { await artifactAnswer(f, r, asked, my); return; }
    if (r.view && !f) globe.flyTo(r.view.lat, r.view.lon, 3.6);
    if (f) { if (f.id !== turn.lastPlace) chime(); globe.showFeature(f); if (r.view) globe.flyTo(r.view.lat, r.view.lon); turn.lastPlace = f.id; }
    const token = card.show({
      title: f ? f.name : "Guide", place: !!f, asked, say, arc, claims: r.claims,
      note: f && f.est ? "Location estimated from the crew's own directions." : "",
    });
    if (r.action !== "play") offerCrew(token, f, moment);
    if (player.active) player.stop(true);
    const spoke = await guideSay(say);
    if (my !== turn.seq) return;
    if (r.action === "play" && moment) { if (!spoke && voice.kidTalking) return; await player.play(moment); return; }
    scheduleNudge();
  }

  /** "▶ Hear the crew" when the server has a kid-safe moment for this place. */
  function offerCrew(token, f, moment) {
    const add = m => m && card.addAction(token, { label: "▶ Hear the crew", hot: true, onClick: () => { stopSpeaking(); player.play(m); } });
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
      label: "▶ Hear " + (v.who || "the crew"), hot: true,
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
    const spoke = await guideSay(r.say || "");
    if (my !== turn.seq) return;
    if (r.action === "play" && moment) { if (!spoke && voice.kidTalking) return; await player.play(moment); return; }
    await storySay(a.story);
    if (my === turn.seq) scheduleNudge();
  }

  /** Tapped a ghost marker: card + story right away, and the Director is asked about it so it stays in charge of what's said. */
  async function onArtifact(a) {
    voice.clearWords();
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
      await guideSay(r.say);
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
      if (missionUI.active) return;
      if (voice.kidTalking || isSpeaking() || player.active) return;
      const n = $("nudge");
      if (!missions.started && !missions.open) { n.textContent = "Try a mission?"; n.onclick = () => { cancelNudge(); missions.openCard(); }; n.hidden = false; return; }
      const ms = await api.moments(null), m = ms.find(x => x.places.some(p => p !== turn.lastPlace && byId[p])) || ms[0];
      if (!m) return;
      n.textContent = `Hear the crew at ${(byId[m.places[0]] || { name: "the Moon" }).name}?`;
      n.onclick = () => { cancelNudge(); player.play(m); }; n.hidden = false;
    }, 8000);
  }

  $("askForm").addEventListener("submit", e => { e.preventDefault(); ask($("q").value); });
  CHIPS.forEach(c => { const b = document.createElement("button"); b.type = "button"; b.textContent = c; b.onclick = () => ask(c); $("chips").append(b); });
  $("nearBtn").onclick = () => globe.flyTo(0, 0, 3.6);
  $("farBtn").onclick = () => globe.flyTo(0, 180, 3.6);
  $("pinsBtn").onclick = e => { e.currentTarget.setAttribute("aria-pressed", globe.togglePins()); };
  $("hwBtn").onclick = e => { const on = globe.toggleHardware(); e.currentTarget.setAttribute("aria-pressed", on); $("hwKey").hidden = !on; };
  // Client tour of every piece of hardware, oldest first (the Director can also start a tour with action "tour").
  $("tourBtn").onclick = () => {
    if (tour.active) { stopSpeaking(); cancelTour(); return; }
    const hw = places.filter(p => p.kind === "artifact").sort((a, b) => String(a.landed).localeCompare(String(b.landed)));
    if (!globe.hardwareOn) $("hwBtn").click();
    runTour(hw.map(a => a.id), `Here is the hardware people left on the Moon. ${hw.length} stops!`);
  };

  // ---------- modes: Mission (the headline) and Cadet (the explorer, as training) ----------
  const PH = { mission: "Or type: shields to 40, send the rover for ice, end shift", cadet: "Or type: show me the rovers left on the Moon" };
  function setMode(mode) {
    const m = mode === "cadet" ? "cadet" : "mission";
    document.body.dataset.mode = m;
    $("modeMission").setAttribute("aria-pressed", m === "mission"); $("modeCadet").setAttribute("aria-pressed", m === "cadet");
    $("q").placeholder = PH[m]; $("mShade").hidden = m !== "mission";
    try { localStorage.setItem("atm-mode", m); } catch (e) { /* private mode */ }
    cancelTour(); cancelNudge();
    if (m === "mission") {
      if (player.active) player.stop(true);
      if (missions.open) $("mClose").click();
      missionUI.enter();
    } else {
      missionUI.exit(); card.hide();
      if (byId.orientale) globe.showFeature(byId.orientale, { dist: 3.3 });
    }
  }
  $("modeMission").onclick = () => setMode("mission");
  $("modeCadet").onclick = () => setMode("cadet");
  let saved = null; try { saved = localStorage.getItem("atm-mode"); } catch (e) { /* none */ }
  setMode(saved || "mission");
}

boot();
