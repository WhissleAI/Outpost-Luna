// Flight School (the Academy) UI: home (call sign + Start) → course map (a flight path of patches + one "Next up" card)
// → lesson (CAPCOM's brief, 2–4 steps with voice/type/tap answers, hints after 2 misses) → patch earned. Lesson 8, the
// check ride, is the cadet's first solo shift in a simplified Outpost Luna cockpit (mission/cockpit.js, mode "mini") on
// the real mission simulator; passing it qualifies the cadet for Mission mode. Grading is server-side
// (POST /api/academy/attempt); progress and the call sign stay on this device. Story copy lives in ../story.js; the few
// UI labels below (UI) are listed in docs/UX_ROUNDS.md for the copy owner.
//
// Steps render through a registry, STEP_RENDERERS[accept.type] = {html(step, ctx) → string, wire?(el, ctx)}, exported
// and attached to window.__outpost.stepRenderers so other modules can register new step types without editing this file.
import "../school.css";
import { academyApi, progress } from "./client.js";
import { sayStyle } from "../floor.js";
import { createCabin } from "../mission/cabin.js";   // [ride] the check ride sits in the real cabin
import { icon, patch } from "../assets/icons.js";
import { APP_TAGLINE } from "../brand.js";
import { SCHOOL, LESSON_STORY, CAPCOM, OFFER, CALLSIGNS, CALLSIGN_COPY, CREDIT, callSign, TRACKS, LESSON_BLURB } from "../story.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const src = s => s && s.url ? `<a class="chip-src" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : "";
const NEXT_WORDS = /^(next|next one|continue|go on|ok|okay|ready|let s go|lets go|start|yes)\b/;
/** UI labels (not story copy). Copy requests: docs/UX_ROUNDS.md. */
const UI = {
  begin: "Start", start: SCHOOL.start, cont: SCHOOL.continue, replay2: "Replay", next: "Next", map: "Map", replay: "Hear it again", facts: "NASA facts", brief: "Brief",
  nextUp: SCHOOL.next, lesson: (n, of) => `Lesson ${n} of ${of}`, step: (n, of) => `Step ${n} of ${of}`, min: SCHOOL.minutes,
  patches: SCHOOL.progress, qualified: "Qualified", retry: "Fly it again", shuffle: CALLSIGN_COPY.random,
  callsign: CALLSIGN_COPY.edit, ride: "Check ride", patchEarned: "Patch earned", commander: SCHOOL.go,
};
/** Where each lesson sits on the Moon, when course.json doesn't say (a lesson's `place`: {name, lat, lon} or a place
 *  id from /api/places wins). The route runs from the near side down to the south-pole outpost, where the check ride
 *  (and then the Mission) happens. Close stops are pushed apart on screen by the globe (route layer). */
const LESSON_PLACE = {
  moon: { name: "Sea of Rains", lat: 32.8, lon: -15.6 },
  comms: { name: "Tranquility Base", lat: 0.67, lon: 23.47 },
  words: { name: "Aristarchus Plateau", lat: 26, lon: -51 },
  history: { name: "Surveyor 3 · Apollo 12", lat: -3.02, lon: -23.42 },
  power: { name: "Malapert Massif", lat: -85.98, lon: -1.67 },
  radiation: { name: "de Gerlache Rim", lat: -88.71, lon: -68.7 },
  life: { name: "Cabeus · LCROSS", lat: -84.68, lon: -48.73 },
  checkride: { name: "Outpost Luna · Connecting Ridge", lat: -89.44, lon: -141.8 },
};
/** How to answer, per step type: one short line under the question (the dock shows the voice state). */
const HOW = { intent: "Say it, or tap the Moon", tap: "Tap the Moon, or say it", command: "Tap an order, or say it",
  keywords: "Say it back, or type it", choice: "" };
/** Cockpit orders a kid can tap on a command step (each is sent as the words, so voice and tap grade the same way). */
const ORDERS = [["heater", "Heaters up", "more power to the heaters"], ["shield", "Shields up", "more power to the shields"],
  ["shelter", "Into the shelter", "everyone into the shelter"], ["leave", "Leave the shelter", "leave the shelter"], ["rover", "Rover: get ice", "send the rover for ice"]];

/** The step registry. ctx: {L, i, answer(input, btn), esc, clip, done} */
export const STEP_RENDERERS = {
  choice: {
    html: (st) => `<div class="a-choices">${st.accept.options.map((o, k) => `<button type="button" class="a-choice" data-c="${esc(o.id)}"><span class="a-key" aria-hidden="true">${"ABCD"[k]}</span><span>${esc(o.label)}</span></button>`).join("")}</div>`,
    wire: (el, ctx) => el.querySelectorAll(".a-choice").forEach(b => b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)),
  },
  keywords: { html: () => "" },
  tap: { html: () => "" },
  intent: { html: () => "" },
  command: {
    html: () => `<div class="a-orders" role="group" aria-label="Orders">${ORDERS.map(([ico, label, words]) => `<button type="button" class="a-order" data-say="${esc(words)}">${icon(ico, { size: 18 })}<span>${esc(label)}</span></button>`).join("")}</div>`,
    wire: (el, ctx) => el.querySelectorAll(".a-order").forEach(b => b.onclick = () => ctx.answer({ text: b.dataset.say }, b)),
  },
};
try {   // share one registry: keep anything registered before this module loaded (e.g. academy/vocab.js)
  const O = (window.__outpost = window.__outpost || {});
  Object.keys(O.stepRenderers || {}).forEach(k => { if (!(k in STEP_RENDERERS)) STEP_RENDERERS[k] = O.stepRenderers[k]; });
  O.stepRenderers = STEP_RENDERERS;
} catch (e) { /* no window (tests) */ }

/**
 * @param {object} o
 * @param {object} o.globe       globe.js instance
 * @param {(id:string)=>object} o.placeById
 * @param {(text:string, style?)=>Promise} o.say    speak as CAPCOM
 * @param {object} o.player      crew player (lesson clips)
 * @param {()=>void} o.alertSound
 * @param {()=>void} o.goMission  switch to Mission mode (site briefing)
 * @param {(p:object)=>void} o.onProgress  progress changed (badges / qualified)
 */
export function createAcademyUI({ globe, placeById, say, player, alertSound = () => {}, stop = () => {}, goMission = () => {}, openLibrary = () => {}, onProgress = () => {} }) {
  const panel = document.getElementById("aPanel");
  let course = null, prog = progress.load(), view = "off", L = null, i = 0, misses = 0, waitingNext = false, busy = false;
  let ride = null, rideSite = null, feedback = null, rideEl = null, rideCk = null, nagged = false;
  const ui = {
    active: false, enter, exit, handleText, onTap, onArtifact, get progress() { return prog; },
    screen, nav, answerText,   // hands-free: the session routes every turn (backend/app/turn_router.py)
    /** Earned patches, for the Mission cockpit: [{id, name, patch (inline SVG), lesson}] */
    badges: () => lessons().filter(l => has(l.badge.id)).map(l => ({ id: l.badge.id, name: l.badge.name, lesson: l.id, patch: patch(l.id, { size: 22 }) })),
    has: lessonId => { const l = lessons().find(x => x.id === lessonId); return !!(l && has(l.badge.id)); },
  };

  const lessons = () => (course ? course.lessons : []);
  const has = id => prog.badges.includes(id);
  const nextLesson = () => lessons().find(l => !has(l.badge.id)) || null;
  const speakLine = (t, r) => { if (t) say(t, sayStyle(r)); };   // r: the attempt response; its say.style steers
  /** Panel layout for this view. The Moon is always the backdrop: home and map are overlays on it, lesson / patch /
   *  ride are glass cards. The route pins live only on the map; the place dots only on steps that ask for a tap. */
  function setLayout(kind) {
    panel.className = "apanel is-" + kind;
    document.body.dataset.aview = kind;
    if (kind !== "map") { globe.route.clear(); globe.setViewport(null); }
    globe.setDecor(false);
  }

  async function enter() {
    ui.active = true; panel.hidden = false;
    if (!course) {
      setLayout("map"); panel.innerHTML = `<p class="a-wait">Loading Flight School…</p>`;
      try { course = await academyApi.course(); }
      catch (e) { panel.innerHTML = `<p class="a-wait is-error"><b>Can&rsquo;t reach Flight School</b><span>Close the app and open it again.</span></p>`; return; }
    }
    if (!ui.active) return;
    showMap();
  }
  function exit() { ui.active = false; view = "off"; panel.hidden = true; endRide(); leaveCatalog(); globe.route.clear(); globe.setViewport(null); }

  // ---------- home: what this is, a call sign, one Start ----------
  const shuffled = () => [...CALLSIGNS].sort(() => Math.random() - .5);
  let csDeck = shuffled();
  function showCallSign(back, reshuffled) {
    view = "callsign"; setLayout("home"); if (!reshuffled) globe.flyTo(-20, 10, 3.2);
    const cur = callSign.get(), pick = (!reshuffled && cur) || csDeck[0];
    panel.innerHTML = `
      <div class="h-wrap">
        <div class="h-copy">
          <p class="eyebrow">${esc(APP_TAGLINE)}</p>
          <h1 class="h-title">${esc(SCHOOL.hero)}<br>${esc(SCHOOL.hero2)}</h1>
        </div>
        <form class="h-form" id="aCsForm">
          <label class="h-label" for="aCsIn">${esc(CALLSIGN_COPY.title)}</label>
          <div class="h-field">
            <input id="aCsIn" maxlength="18" autocomplete="off" value="${esc(pick)}" aria-describedby="aCsHelp">
            <button type="button" class="btn-icon" id="aCsRand" aria-label="${esc(UI.shuffle)}" title="${esc(UI.shuffle)}">${icon("random")}</button>
          </div>
          <div class="h-chips" role="group" aria-label="${esc(CALLSIGN_COPY.title)}">${csDeck.slice(0, 3).map(c => `<button type="button" class="chip a-csb" aria-pressed="${c === pick}" data-cs="${esc(c)}">${esc(c)}</button>`).join("")}</div>
          <p class="sr-only" id="aCsHelp">${esc(CALLSIGN_COPY.sub)}</p>
          <button type="submit" class="btn-primary h-start" id="aCsGo">${esc(back ? CALLSIGN_COPY.save : UI.begin)}${icon("chevron-right")}</button>
        </form>
        <p class="h-credit">${esc(CREDIT)}</p>
      </div>`;
    const input = panel.querySelector("#aCsIn");
    const done = v => { if (!callSign.set(v)) { input.focus(); return; } const cs = callSign.spoken("Cadet"); say(`Copy that, ${cs}. Welcome to Flight School.`, { situation: "badge" }); back ? back() : showMap(true); };
    const select = v => { input.value = v; panel.querySelectorAll(".a-csb").forEach(b => b.setAttribute("aria-pressed", b.dataset.cs === v)); };
    panel.querySelectorAll(".a-csb").forEach(b => b.onclick = () => select(b.dataset.cs));
    input.addEventListener("input", () => select(input.value));
    panel.querySelector("#aCsForm").onsubmit = e => { e.preventDefault(); done(input.value); };
    // Shuffle deals six new call signs and suggests the first ("surprise me" by voice picks one and goes: handleText).
    panel.querySelector("#aCsRand").onclick = () => { csDeck = shuffled(); showCallSign(back, true); panel.querySelector("#aCsRand").focus(); };
    if (!back && !reshuffled) say(CALLSIGN_COPY.say, { situation: "lesson_brief" });
  }

  // ---------- course map = the Moon: each lesson is a pin on a real place, the route ends at the south-pole outpost ----------
  function trackOf(id) { const t = TRACKS.find(t => t.lessons.includes(id)); return t ? t.id : "foundations"; }
  /** Lessons in the order the map shows them (track by track), so the numbers read 1, 2, 3… along the route. */
  const shownOrder = () => { const ls = lessons(); return TRACKS.flatMap(t => ls.filter(l => trackOf(l.id) === t.id)).concat(ls.filter(l => !TRACKS.some(t => trackOf(l.id) === t.id))); };
  let mapSel = null;   // the pin the cadet tapped (null = the next lesson)
  /** A lesson's place on the Moon: course data first, then the fallback table. */
  function placeOf(l) {
    const p = l && l.place;
    if (p && typeof p === "object" && p.lat != null) return { name: p.name || "", lat: +p.lat, lon: +p.lon };
    if (typeof p === "string") { const f = placeById(p); if (f) return { name: f.name.split(" (")[0], lat: f.lat, lon: f.lon }; }
    return (l && LESSON_PLACE[l.id]) || LESSON_PLACE.moon;
  }
  function showMap(quiet) {
    if (!callSign.get()) return showCallSign();
    view = "map"; L = null; endRide(); setLayout("map");
    const ls = shownOrder(), nx = nextLesson(), n = ls.filter(l => has(l.badge.id)).length, cs = callSign.shown();
    const sel = (mapSel && ls.find(l => l.id === mapSel)) || nx;
    // the whole route in view, the Moon lifted above the Next-up card and the voice strip
    const H = panel.clientHeight || innerHeight; globe.setViewport(Math.max(.55, (H - 250) / H));
    // face the next stop (a polar one turns the south pole toward the cadet); the done legs stay in view
    // a polar next stop zooms to a ~35° field round the pole so the polar pins spread out; anywhere else, the whole Moon
    if (!quiet || !mapSel) { const c = placeOf(sel || ls[0]); const polar = Math.abs(c.lat) > 70; globe.flyTo(polar ? Math.sign(c.lat) * 89 : c.lat, c.lon, polar ? 1.8 : 4.2, polar ? 88 : 75); }
    // pins: earned patch art for done lessons, a grey outline for the rest; the next one is bigger and labelled
    const stops = ls.map((l, k) => {
      const done = has(l.badge.id), next = nx && nx.id === l.id, at = placeOf(l);
      const b = document.createElement("button"); b.type = "button";
      b.className = `pin a-lcard${done ? " is-done" : ""}${next ? " is-next" : ""}${sel && sel.id === l.id ? " is-sel" : ""}`;
      b.dataset.l = l.id;
      b.setAttribute("aria-label", `${k + 1}. ${l.title}${done ? `, ${l.badge.name} patch earned` : next ? ", next up" : ""}. ${at.name}`);
      b.innerHTML = `<span class="pin-badge">${patch(l.id, { earned: done, size: next ? 64 : 44 })}</span><span class="pin-label"><b>${k + 1}</b>${esc(l.title)}</span>`;
      b.onclick = () => { if (sel && sel.id === l.id) { openLesson(l.id); return; } mapSel = l.id; showMap(true); globe.flyTo(at.lat, at.lon, 2.6); };
      return { id: l.id, lat: at.lat, lon: at.lon, el: b };
    });
    globe.route.set(stops, n);
    const k = sel ? ls.indexOf(sel) : -1, selDone = sel && has(sel.badge.id), at = sel && placeOf(sel);
    const cta = !sel ? "" : selDone ? UI.replay2 : sel === nx && n > 0 ? UI.cont : UI.start;
    const card = prog.qualified && (!mapSel || !sel)
      ? `<div class="mp-card"><span class="mp-patch">${patch("checkride", { earned: true, size: 64 })}</span>
          <div class="mp-copy"><p class="eyebrow">${esc(UI.qualified)}</p><h2>${esc(SCHOOL.titleDone(cs))}</h2></div>
          <button type="button" class="btn-primary" id="aGoMission">${esc(UI.commander)}${icon("chevron-right")}</button></div>`
      : sel ? `<div class="mp-card"><span class="mp-patch">${patch(sel.id, { earned: selDone, size: 64 })}</span>
          <div class="mp-copy"><p class="eyebrow">${esc(sel === nx ? UI.nextUp : UI.lesson(k + 1, ls.length))}${at && at.name ? ` · ${esc(at.name)}` : ""}</p>
            <h2>${esc(sel.title)}</h2><p class="mp-sub">${esc(LESSON_BLURB[sel.id] || sel.brief)}</p></div>
          <button type="button" class="btn-primary" id="aStart" data-l="${esc(sel.id)}">${esc(cta)}${icon("chevron-right")}</button></div>` : "";
    panel.innerHTML = `
      <header class="mp-top">
        <h1 class="mp-title">${esc(SCHOOL.eyebrow)}</h1>
        <span class="mp-count" aria-label="${esc(UI.patches(n, ls.length))}">${n}<small>/${ls.length}</small></span>
        <button type="button" class="chip a-csedit" id="aCsEdit" title="${esc(UI.callsign)}">${icon("astronaut", { size: 16 })}${esc(cs)}</button>
      </header>
      ${card}
      <p class="mp-credit">${esc(CREDIT)}</p>`;
    panel.querySelector("#aCsEdit").onclick = () => showCallSign(() => showMap(true));
    const go = panel.querySelector("#aGoMission"); if (go) go.onclick = () => goMission();
    const st = panel.querySelector("#aStart"); if (st) st.onclick = () => openLesson(st.dataset.l);
  }
  function leaveCatalog() { mapSel = null; delete document.body.dataset.aview; }

  // ---------- lesson ----------
  async function openLesson(id) {
    L = lessons().find(l => l.id === id); if (!L) return;
    view = "lesson"; i = 0; misses = 0; waitingNext = false; feedback = null; nagged = false; leaveCatalog();
    endRide();
    if (L.ride) {
      try { ride = await academyApi.ride(); } catch (e) { ride = null; }
      await showRideSite();
    } else if (L.globe) {
      const f = L.globe.place && placeById(L.globe.place);
      if (f) globe.showFeature(f, { dist: L.globe.dist }); else if (L.globe.lat != null) globe.flyTo(L.globe.lat, L.globe.lon, L.globe.dist || 3.6);
    } else { const at = placeOf(L); globe.flyTo(at.lat, at.lon, 2.6); }
    render();
    const beat = (LESSON_STORY[L.id] || {}).beat || "";
    // Three short lines, not one long one (the spoken limit is about 20 words a line): hello, the brief, the question.
    const id0 = L.id, still = () => view === "lesson" && L && L.id === id0 && i === 0;
    Promise.resolve(say(CAPCOM.lessonHello(callSign.spoken("cadet"), beat), { situation: "lesson_brief" }))
      .then(() => still() && say(L.brief, { situation: "lesson_brief" }))
      .then(() => still() && !waitingNext && say(L.steps[0].prompt, { situation: "lesson_brief" }));
    if (L.steps[0].alert) alertSound();
  }

  /** The question as shown. A fill-the-blank prompt that quotes its own sentence shows only its lead-in ("Fill the
   *  blank"), because the step draws the sentence itself, with the blank (the full prompt is still spoken). */
  function promptOf(st) {
    const a = st.accept || {}, p = String(st.prompt || "");
    if (a.type === "vocab_fill" && a.sentence && p.includes(a.sentence.slice(0, 16)) && p.includes(":")) return p.split(":")[0].trim();
    return p;
  }
  function render() {
    if (view !== "lesson" || !L) return;
    const st = L.steps[i], k = shownOrder().indexOf(L), acc = st.accept;
    const clip = st.clip || (i === 0 ? L.clip : null);
    setLayout(L.ride ? "ride" : "lesson");
    if (!waitingNext && (acc.type === "tap" || acc.type === "intent")) globe.setDecor(true);   // the place dots help a tap
    const ctx = { L, i, answer, esc, clip, done: waitingNext };
    // Registry entries are either {html(step, ctx), wire?(el, ctx)} or, for modules like academy/vocab.js,
    // a factory fn({step, acc, answer, esc, say, playCrew, captions}) → {html, bind(el)}.
    const A11 = typeof window !== "undefined" && window.__outpost && window.__outpost.a11y;
    const E = STEP_RENDERERS[acc.type];
    const R = typeof E === "function"
      ? (o => ({ html: () => o.html, wire: el => o.bind && o.bind(el) }))(E({ step: st, acc, answer, esc, say: (t, style) => say(t, style), playCrew: m => player.play(m), captions: A11 ? A11.settings.captions : true }))
      : (E || { html: () => "" });
    const firstLook = i === 0 && !waitingNext && !feedback;
    const how = HOW[acc.type];
    const fb = feedback ? `<div class="a-feedback is-${feedback.kind}" id="aFeedback" role="status">${feedback.kind === "ok" ? icon("check", { size: 18 }) : ""}<p>${esc(feedback.text)}</p></div>` : `<div class="a-feedback" id="aFeedback" role="status"></div>`;
    panel.innerHTML = `
      <header class="a-head m-head">
        <button type="button" class="btn-quiet a-back" id="aBack" aria-label="Back to the map">${icon("chevron-left", { size: 18 })}${esc(UI.map)}</button>
        <span class="eyebrow sr-only">${esc(L.ride ? UI.ride : UI.lesson(k + 1, lessons().length))}</span>
        <span class="a-steps" role="img" aria-label="${esc(UI.step(i + 1, L.steps.length))}">${L.steps.map((_, j) => `<i class="${j < i || (j === i && waitingNext) ? "is-done" : j === i ? "is-now" : ""}"></i>`).join("")}</span>
      </header>
      <div class="a-body">
        <div class="a-title"><span class="a-patch">${patch(L.id, { earned: has(L.badge.id), size: 44 })}</span><h2 class="m-title">${esc(L.title)}</h2>
          ${L.ride && !firstLook ? "" : `<button type="button" class="btn-quiet a-brief-btn" id="aBriefBtn" aria-expanded="false" aria-controls="aBrief">${icon("info", { size: 16 })}${esc(UI.brief)}</button>`}</div>
        ${L.ride && !firstLook ? "" : `<div class="a-brief" id="aBrief" hidden>
          <p>${esc(L.brief)}</p>
          <div class="a-row"><button type="button" class="btn-quiet" id="aReplay">${icon("speaker", { size: 16 })}${esc(UI.replay)}</button>
            ${L.library ? `<button type="button" class="btn-quiet" id="aLib">${icon("library", { size: 16 })}${esc(L.library.label)}</button>` : ""}
            ${L.facts && L.facts.length ? `<details class="a-facts"><summary>${esc(UI.facts)} (${L.facts.length})</summary><ul>${L.facts.map(f => `<li>${esc(f.text)} ${src(f.source)}</li>`).join("")}</ul></details>` : ""}</div></div>`}
        <section class="a-step${st.alert ? " is-alert" : ""}" aria-live="polite">
          ${st.alert ? `<p class="a-alert">${icon("warning", { size: 16 })}<span>Alert</span></p>` : ""}
          <p class="a-prompt">${esc(promptOf(st))}</p>
          ${how && !waitingNext ? `<p class="a-how">${esc(how)}</p>` : ""}
          ${clip ? `<button type="button" class="btn a-clip" id="aClip">${icon("play", { size: 16 })}Hear ${esc(clip.who)}</button>` : ""}
          <div class="a-input" id="aInput">${waitingNext ? "" : R.html(st, ctx)}</div>
          ${fb}
          ${feedback && feedback.hint ? `<p class="a-hint">${icon("info", { size: 16 })}<span>${esc(feedback.hint)}</span></p>` : ""}
        </section>
        ${ride ? `<div id="aRideSlot"></div>` : ""}
      </div>
      <footer class="a-foot">${waitingNext ? `<button type="button" class="btn-primary" id="aNext">${esc(UI.next)}${icon("chevron-right")}</button>` : ""}</footer>`;
    panel.querySelector("#aBack").onclick = () => { stop(); showMap(); };
    const bb = panel.querySelector("#aBriefBtn");
    if (bb) bb.onclick = () => { const b = panel.querySelector("#aBrief"), open = b.hidden; b.hidden = !open; bb.setAttribute("aria-expanded", open); };
    const rp = panel.querySelector("#aReplay"); if (rp) rp.onclick = () => say(L.brief);
    const lib = panel.querySelector("#aLib"); if (lib) lib.onclick = () => openLibrary(L.library.place);
    const cb = panel.querySelector("#aClip");
    if (cb) cb.onclick = () => player.play({ clip_id: clip.clip_id, t0: clip.t0, t1: clip.t1, speaker: clip.who, places: [], jargon: [] });
    if (!waitingNext && R.wire) R.wire(panel.querySelector("#aInput"), ctx);
    const slot = panel.querySelector("#aRideSlot"); if (slot && rideEl) { slot.replaceWith(rideEl); if (ride.state) rideCk.update(ride.state); }
    if (ride && rideCk) { if (ride.state) rideCk.update(ride.state); setTimeout(rideCue, 400); }   // [ride]
    const nb = panel.querySelector("#aNext"); if (nb) { nb.onclick = next; nb.focus({ preventScroll: true }); }
  }

  async function answer(input, btn) {
    if (busy || view !== "lesson" || waitingNext) return false;
    busy = true; if (btn) btn.classList.add("is-busy");
    let r;
    try { r = await academyApi.attempt({ lesson_id: L.id, step: i, input, misses, ride_id: ride && ride.ride_id }); }
    catch (e) { busy = false; feedback = { kind: "retry", text: "I can't reach CAPCOM right now. Try again." }; render(); return true; }
    busy = false;
    if (r.state && ride) { ride.state = r.state; syncRideGlobe(); }
    if (ride && r.events && r.events.length) ride.events = r.events;
    if (r.status === "passed" || r.status === "missed" || r.status === "done") {
      if (L.ride) return rideStep(r);
      feedback = { kind: "ok", text: r.say };
      const acc = L.steps[i].accept;
      if (acc.type === "intent" || acc.type === "tap") { const f = placeById(acc.place); if (f) globe.showFeature(f); }
      if (r.badge) { award(r.badge); speakLine(r.say, r); setTimeout(() => showBadge(r.badge), 900); waitingNext = true; render(); return true; }
      waitingNext = true; render(); speakLine(r.say, r);
      return true;
    }
    misses++;
    feedback = { kind: "retry", text: r.status === "hint" ? L.steps[i].fail : r.say, hint: r.hint };
    render();
    const again = btn && panel.querySelector(btn.dataset.c ? `.a-choice[data-c="${btn.dataset.c}"]` : `.a-order[data-say="${btn.dataset.say}"]`);
    if (again) again.classList.add("is-wrong");
    speakLine(r.say, r);
    return true;
  }

  function next() {
    if (!waitingNext) return;
    if (i + 1 >= L.steps.length) { showMap(); return; }   // never a dead end
    waitingNext = false; feedback = null; misses = 0; nagged = false; i++;
    render(); speakLine(L.steps[i].prompt);
    if (L.steps[i].alert) alertSound();
  }

  // ---------- check ride: the first solo shift, in a simplified cockpit ----------
  /** [ride] a cabin control → the same words as the order buttons, graded by the same path */
  const RIDE_WORDS = c => c.type === "allocate" ? `more power to the ${String(c.to).replace("_", " ")}` : c.type === "shelter" ? (c.on ? "everyone into the shelter" : "leave the shelter")
    : c.type === "dispatch" ? (c.task === "collect_ice" ? "send the rover for ice" : c.task === "return" ? "bring the rover home" : `send the rover to ${c.task}`) : null;
  async function showRideSite() {
    if (!rideSite) {
      try { const s = await (await fetch("/api/mission/sites")).json(); rideSite = s.sites.find(x => x.id === L.ride.site); } catch (e) { rideSite = null; }
    }
    // [ride] the cabin, full stage behind the lesson card; its controls answer the step like the order buttons do
    rideEl = null; if (rideCk && rideCk.dispose) rideCk.dispose();
    let host = document.getElementById("aRideCabin");
    if (!host) { host = document.createElement("section"); host.id = "aRideCabin"; host.className = "m-cabin a-ridecabin"; host.setAttribute("aria-label", "Check ride cabin"); panel.parentNode.insertBefore(host, panel); }
    host.hidden = false; document.body.dataset.ride = "1";
    rideCk = createCabin(host, { mode: "ride", terrain: true, site: rideSite, onCommand: c => { const t = RIDE_WORDS(c); if (t) answer({ text: t }); }, onEndShift() {}, onHouston() {}, onDebrief() {} });
    if (ride && ride.state) rideCk.update(ride.state);
    setTimeout(rideCue, 400);
    if (!rideSite) return;
    globe.mission.enter();
    globe.mission.setSite({ ...rideSite, short: rideSite.name.split(" (")[0] }, { dist: 2.2 });
    syncRideGlobe();
  }
  function syncRideGlobe() {
    if (!ride || !ride.state) return;
    if (rideCk) { rideCk.update(ride.state); rideCue(); }
    if (!rideSite) return;
    const e = ride.state.env;
    globe.mission.setSun(e.sun_elev_deg, ride.state.mission_time_h); globe.mission.setEarth(e.earth_elev_deg);
  }
  function endRide() { if (ride) { ride = null; globe.mission.exit(); } rideEl = null; if (rideCk && rideCk.dispose) rideCk.dispose(); rideCk = null;
    const h = document.getElementById("aRideCabin"); if (h) { h.hidden = true; h.innerHTML = ""; } delete document.body.dataset.ride; }
  /** [ride] the step's expected order lights its control in the cabin, one at a time */
  function rideCue() {
    if (!rideCk || !rideCk.cue || !L || !L.steps[i]) return;
    const x = (L.steps[i].accept || {}).expect || {};
    rideCk.cue(x.type === "allocate" ? (x.to === "shields" ? "shields" : `load:${x.to}`) : x.type === "shelter" ? "shelter" : x.type === "dispatch" ? `rover:${x.task}` : null);
  }
  function rideStep(r) {
    if (r.status === "done") {
      feedback = { kind: r.passed ? "ok" : "retry", text: r.say };
      if (r.passed && r.badge) { award(r.badge, true); waitingNext = true; render(); speakLine(r.say, r); setTimeout(() => showBadge(r.badge, true), 1200); return true; }
      waitingNext = false; render(); speakLine(r.say, r);
      const inp = panel.querySelector("#aInput"); inp.innerHTML = `<button type="button" class="btn-primary" id="aRetry">${icon("retry")}${esc(UI.retry)}</button>`;
      panel.querySelector("#aRetry").onclick = () => openLesson(L.id);
      return true;
    }
    feedback = { kind: r.status === "passed" ? "ok" : "retry", text: r.say + (r.sim_say ? " " + r.sim_say : "") };
    waitingNext = true; misses = 0; render(); speakLine(r.say, r);
    return true;
  }

  // ---------- patches ----------
  function award(badge, qualifies) {
    if (!prog.badges.includes(badge.id)) prog.badges.push(badge.id);
    if (qualifies) prog.qualified = true;
    progress.save(prog); onProgress(prog);
  }
  function showBadge(badge, commander) {
    if (view !== "lesson") return;
    view = "badge"; setLayout("badge");
    const nx = nextLesson(), cs = callSign.shown();
    panel.innerHTML = `
      <div class="a-badge" role="status">
        <span class="a-bigpatch">${patch(L.id, { earned: true, size: 168 })}</span>
        <p class="eyebrow">${esc(commander ? UI.qualified : UI.patchEarned)}</p>
        <h2 class="m-title">${esc(badge.name)}</h2>
        <p class="a-badge-sub">${commander ? esc(cs) : esc(L.title)}</p>
        <div class="a-actions">
          ${commander ? `<button type="button" class="btn-primary" id="aGoMission">${esc(UI.commander)}${icon("chevron-right")}</button>`
            : nx ? `<button type="button" class="btn-primary" id="aNextLesson">${esc(UI.next)}: ${esc(nx.ride ? UI.ride : nx.title)}${icon("chevron-right")}</button>` : ""}
          <button type="button" class="btn-quiet" id="aMap">${icon("map", { size: 16 })}${esc(UI.map)}</button>
        </div>
      </div>`;
    // Hands-free: one short offer, spoken once with the patch line; "yes" / "next" takes it (screen().offer).
    const offer = commander ? OFFER.mission : nx ? (nx.ride ? OFFER.ride : OFFER.nextLesson) : "";
    Promise.resolve(say(commander ? CAPCOM.qualified(callSign.spoken(), badge.name) : CAPCOM.patch(callSign.spoken("cadet"), badge.name), { situation: "badge" }))
      .then(() => { if (offer && view === "badge") say(offer, { situation: "badge" }); });
    const g = panel.querySelector("#aGoMission"); if (g) g.onclick = () => goMission();
    const n = panel.querySelector("#aNextLesson"); if (n) n.onclick = () => openLesson(nx.id);
    panel.querySelector("#aMap").onclick = () => showMap();
    (g || n || panel.querySelector("#aMap")).focus({ preventScroll: true });
  }

  // ---------- hands-free (the session's router decides; these run what it decided) ----------
  /** What the router needs to know about this screen. */
  function screen() {
    if (!ui.active) return null;
    if (view === "callsign") return { screen: "callsign" };
    if (view === "map") { const nx = nextLesson(); return { screen: "map", offer: prog.qualified ? "mission" : nx ? "next_lesson" : null }; }
    if (view === "badge") { const nx = nextLesson(); return { screen: "patch", offer: prog.qualified ? "mission" : nx ? "next_lesson" : null }; }
    if (view !== "lesson" || !L) return { screen: "map" };
    if (waitingNext) return { screen: "lesson_done", offer: "next_step" };
    const acc = L.steps[i].accept;
    return { screen: L.ride ? "ride" : "lesson", step_type: acc.type, step_options: (acc.options || []).map(o => o.label) };
  }
  /** A navigation intent. True when the Academy ran it. */
  function nav(intent, arg) {
    if (!ui.active) return false;
    if (view === "callsign") return false;
    const nx = nextLesson();
    if (intent === "lesson") { if (lessons().some(l => l.id === arg)) { stop(); openLesson(arg); return true; } return false; }
    if (intent === "map" || (intent === "back" && view !== "map")) { stop(); showMap(); return true; }
    if (intent === "repeat_step" && view === "lesson" && L) { speakLine(L.steps[i].prompt); return true; }
    if (["next", "start", "accept_offer"].includes(intent)) {
      if (view === "lesson" && waitingNext) { next(); return true; }
      if (view === "lesson" && intent === "start") return true;          // already in a lesson: nothing to start
      if (view === "badge" || view === "map") {
        if (prog.qualified && (view === "badge" || !nx || arg === "mission")) { goMission(); return true; }
        if (nx) { openLesson(nx.id); return true; }
      }
      return false;
    }
    if (intent === "decline_offer") return true;    // stay here, quietly
    return false;
  }
  /** The router's "answer": the current step's answer (or a call sign). */
  function answerText(text) { return handleText(text); }

  // ---------- inputs from the rest of the app ----------
  /** A typed or spoken turn. True when the Academy used it. */
  async function handleText(text) {
    if (!ui.active) return false;
    const t = text.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
    if (view === "callsign") {
      const hit = CALLSIGNS.find(c => t.includes(c.toLowerCase()));
      if (hit) { callSign.set(hit); say(`Copy that, ${hit}. Welcome to Flight School.`, { situation: "badge" }); showMap(true); return true; }
      if (/surprise|random|any|you pick|pick for me/.test(t)) { const c = CALLSIGNS[Math.floor(Math.random() * CALLSIGNS.length)]; callSign.set(c); say(`Copy that, ${c}. Welcome to Flight School.`, { situation: "badge" }); showMap(true); return true; }
      say("Pick one from the list, like Nova or Comet."); return true;
    }
    if (view === "badge" || view === "map") {
      if (NEXT_WORDS.test(t)) { const nx = nextLesson(); if (prog.qualified && (view === "badge" || !nx)) goMission(); else if (nx) openLesson(nx.id); return true; }
      return false;
    }
    if (view !== "lesson") return false;
    if (waitingNext) { if (NEXT_WORDS.test(t)) next(); else if (!nagged) { nagged = true; speakLine(OFFER.nextStep); } return true; }
    // tap steps: naming the place counts too (hands-free, and kids who can't tap); the server grades it
    return answer({ text });
  }
  /** A tap on the globe (lat/lon). True when the Academy used it. */
  function onTap(p) {
    if (!ui.active || view !== "lesson" || waitingNext || L.ride) return ui.active;
    const acc = L.steps[i].accept;
    if (acc.type !== "tap" && acc.type !== "intent") return true;
    const { f, d } = globe.nearest(p);
    answer({ tap: { lat: p.lat, lon: p.lon, ...(f && d < 12 ? { place: f.id } : {}) } });
    return true;
  }
  function onArtifact(a) {
    if (!ui.active) return false;
    if (view === "lesson" && !waitingNext && !L.ride && ["tap", "intent"].includes(L.steps[i].accept.type)) answer({ tap: { place: a.id, lat: a.lat, lon: a.lon } });
    return true;
  }

  return ui;
}
