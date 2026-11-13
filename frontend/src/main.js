// Wiring only: load places, build the modules, route asks / taps / voice turns between them.
import "./styles.css";
import { api, normMoment } from "./api.js";
import { createGlobe } from "./globe.js";
import { createCard, readoutLine } from "./card.js";
import { createPlayer } from "./player.js";
import { createVoice } from "./voice.js";
import { createMissions } from "./missions.js";
import { initAbout } from "./about.js";
import { chime, speak, stopSpeaking, isSpeaking } from "./sound.js";

const $ = id => document.getElementById(id);
const CHIPS = ["Where did Apollo 11 land?", "Show me the giant bullseye", "What did the astronauts say about the yellow part?",
  "Show me the far side", "Where will astronauts land next?", "Which crater did the crew name after their spaceship?"];

async function boot() {
  initAbout();
  let places;
  try { places = await api.places(); }
  catch (e) { $("loading").textContent = "Can't reach the backend. Start everything with `make dev`."; return; }
  const byId = Object.fromEntries(places.map(f => [f.id, f]));
  const placeById = id => byId[id] || null;

  const turn = { lastPlace: null, emotion: null, seq: 0 };
  const card = createCard();
  const globe = createGlobe({ stage: $("stage"), label: $("label"), loading: $("loading"), places, onTap });
  const player = createPlayer({
    api, globe, placeById, isKidTalking: () => voice.kidTalking,
    onPlace: id => { turn.lastPlace = id; }, onEnd: scheduleNudge,
  });
  const voice = createVoice({
    onTurn: text => ask(text),
    onBargeIn: () => { cancelNudge(); if (isSpeaking()) stopSpeaking(); player.duck(); },
    onKidDone: () => player.unduck(),
    onEmotion: label => { turn.emotion = label; },
  });
  const missions = createMissions({ globe, placeById, say: t => guideSay(t), onFound: f => { turn.lastPlace = f.id; } });

  /** The guide speaks (card text is the caption). Never over crew audio: the moment ends first. */
  async function guideSay(text, { keepCrew } = {}) {
    if (!text) return false;
    if (!keepCrew && player.active) player.stop(true);
    voice.show("speaking");
    const ok = await speak(text);
    voice.show("idle");
    return ok;
  }

  const context = () => {
    const c = {};
    if (turn.lastPlace) c.last_place = turn.lastPlace;
    if (turn.emotion) c.emotion = turn.emotion;
    const p = player.playing; if (p) c.playing = p;
    return c;
  };

  async function ask(raw) {
    const text = (raw || "").trim(); if (!text) return;
    const my = ++turn.seq; cancelNudge();
    $("q").value = ""; voice.show("thinking");
    let r;
    try { r = await api.ask(text, context()); }
    catch (e) {
      if (my === turn.seq) { card.show({ title: "Hmm", asked: text, say: "I can't reach my brain right now. Is the backend running?" }); voice.show("idle"); }
      return;
    }
    for (let w = 0; voice.kidTalking && w < 100; w++) await new Promise(res => setTimeout(res, 100));   // WAIT
    if (my !== turn.seq) return;
    await act(r, text, my);
  }

  async function act(r, asked, my) {
    const f = placeById(r.place), moment = normMoment(r.moment), say = r.say || "";
    const arc = readoutLine(r);
    if (r.action === "guard") { card.show({ title: "Let's keep that private", asked, say, arc }); await guideSay(say); scheduleNudge(); return; }
    if (r.action === "ask" && r.ask) { askCard(r, asked, arc); return; }
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

  function onTap(p) {
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
  $("pinsBtn").onclick = e => { const on = globe.togglePins(); e.currentTarget.textContent = on ? "Hide pins" : "Show pins"; e.currentTarget.setAttribute("aria-pressed", on); };

  // open on the crew's view of Orientale
  if (byId.orientale) globe.showFeature(byId.orientale, { dist: 3.3 });
}

boot();
