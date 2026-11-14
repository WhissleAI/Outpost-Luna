// Flight School (the Academy) UI: call sign → mission-patch path → lesson (story beat, CAPCOM brief, 2–4 steps with
// voice/type/tap answers, hints after 2 misses) → patch stamped. Lesson 7, the check ride, is the cadet's first solo
// shift in a simplified Outpost Luna cockpit (mission/cockpit.js, mode "mini") on the real mission simulator; passing
// it qualifies the cadet for Mission mode. Grading is server-side (POST /api/academy/attempt); progress and the call
// sign stay on this device. Story copy lives in ../story.js.
//
// Steps render through a registry, STEP_RENDERERS[accept.type] = {html(step, ctx) → string, wire?(el, ctx)}, exported
// and attached to window.__outpost.stepRenderers so other modules can register new step types without editing this file.
import { academyApi, progress } from "./client.js";
import { sayStyle } from "../floor.js";
import { createCockpit } from "../mission/cockpit.js";
import { SCHOOL, LESSON_STORY, CAPCOM, CALLSIGNS, CALLSIGN_COPY, CREDIT, callSign, TRACKS, LESSON_BLURB, WHY, MENTOR } from "../story.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const src = s => s && s.url ? `<a class="chip-src" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : "";
const NEXT_WORDS = /^(next|next one|continue|go on|ok|okay|ready|let s go|lets go|start|yes)\b/;
const HOW = { intent: "Say it, type it below, or tap the Moon", tap: "Tap the Moon", command: "Tap an order, or say it",
  keywords: "Say your readback, or type it below", choice: "Tap an answer, or say it" };
/** Cockpit orders a kid can tap on a command step (each is sent as the words, so voice and tap grade the same way). */
const ORDERS = [["🔥", "Heaters up", "more power to the heaters"], ["🛡️", "Shields up", "more power to the shields"],
  ["🏠", "Into the shelter", "everyone into the shelter"], ["🚪", "Leave the shelter", "leave the shelter"], ["🧊", "Rover: get ice", "send the rover for ice"]];

/** The step registry. ctx: {L, i, answer(input, btn), esc, clip, done} */
export const STEP_RENDERERS = {
  choice: {
    html: (st) => `<div class="a-choices">${st.accept.options.map((o, k) => `<button type="button" class="a-choice" data-c="${esc(o.id)}"><span class="a-key" aria-hidden="true">${"ABCD"[k]}</span>${esc(o.label)}</button>`).join("")}</div>`,
    wire: (el, ctx) => el.querySelectorAll(".a-choice").forEach(b => b.onclick = () => ctx.answer({ choice: b.dataset.c }, b)),
  },
  keywords: {
    html: () => `<p class="a-tapme"><span aria-hidden="true">🎙️</span> Hold Space and read it back, or type it below</p>`,
  },
  tap: { html: () => `<p class="a-tapme"><span aria-hidden="true">👆</span> Tap the Moon</p>` },
  intent: { html: () => "" },
  command: {
    html: () => `<div class="a-orders" role="group" aria-label="Orders">${ORDERS.map(([ico, label, words]) => `<button type="button" class="a-order" data-say="${esc(words)}"><span aria-hidden="true">${ico}</span>${esc(label)}</button>`).join("")}</div>`,
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
  let ride = null, rideSite = null, feedback = null, rideEl = null, rideCk = null;
  const ui = {
    active: false, enter, exit, handleText, onTap, onArtifact, get progress() { return prog; },
    /** Earned patches, for the Mission cockpit: [{id, name, patch, lesson}] */
    badges: () => lessons().filter(l => has(l.badge.id)).map(l => ({ id: l.badge.id, name: l.badge.name, lesson: l.id, patch: (LESSON_STORY[l.id] || {}).patch || l.badge.glyph })),
    has: lessonId => { const l = lessons().find(x => x.id === lessonId); return !!(l && has(l.badge.id)); },
  };

  const lessons = () => (course ? course.lessons : []);
  const has = id => prog.badges.includes(id);
  const nextLesson = () => lessons().find(l => !has(l.badge.id)) || null;
  const speakLine = (t, r) => { if (t) say(t, sayStyle(r)); };   // r: the attempt response; its say.style steers
  const patchOf = l => (LESSON_STORY[l.id] || {}).patch || l.badge.glyph;
  const todo = t => `<p class="a-todo" aria-live="polite"><span aria-hidden="true">👉</span> ${t}</p>`;

  async function enter() {
    ui.active = true; panel.hidden = false;
    if (!course) {
      panel.innerHTML = `<p class="m-wait">Loading Flight School…</p>`;
      try { course = await academyApi.course(); }
      catch (e) { panel.innerHTML = `<p class="m-wait">Can't reach Flight School. Start everything with <code>make dev</code>.</p>`; return; }
    }
    if (!ui.active) return;
    showMap();
  }
  function exit() { ui.active = false; view = "off"; panel.hidden = true; endRide(); leaveCatalog(); }

  // ---------- call sign ----------
  function showCallSign(back) {
    view = "callsign"; leaveCatalog();
    const cur = callSign.get();
    panel.innerHTML = `
      <header class="m-head"><span class="eyebrow">${esc(SCHOOL.eyebrow)}</span></header>
      <div class="a-cs-hero" aria-hidden="true">🧑‍🚀</div>
      <h2 class="m-title">${esc(CALLSIGN_COPY.title)}</h2>
      <p class="m-sub">${esc(CALLSIGN_COPY.sub)}</p>
      <div class="a-cs" role="group" aria-label="Call signs">${CALLSIGNS.map(c => `<button type="button" class="a-csb" aria-pressed="${c === cur}" data-cs="${esc(c)}">${esc(c)}</button>`).join("")}</div>
      <form class="a-csform" id="aCsForm"><label class="sr-only" for="aCsIn">${esc(CALLSIGN_COPY.type)}</label>
        <input id="aCsIn" maxlength="18" autocomplete="off" placeholder="${esc(CALLSIGN_COPY.type)}" value="${CALLSIGNS.includes(cur) ? "" : esc(cur)}">
        <button type="submit" class="pill">${esc(CALLSIGN_COPY.save)}</button></form>
      <button type="button" class="pill" id="aCsRand">🎲 ${esc(CALLSIGN_COPY.random)}</button>
      ${todo("Tap a call sign, or say one, like “call me Nova”.")}`;
    const done = v => { if (!callSign.set(v)) return; const cs = callSign.spoken("Cadet"); say(`Copy that, ${cs}. Welcome to Flight School.`, { situation: "badge" }); back ? back() : showMap(true); };
    panel.querySelectorAll(".a-csb").forEach(b => b.onclick = () => done(b.dataset.cs));
    panel.querySelector("#aCsForm").onsubmit = e => { e.preventDefault(); done(panel.querySelector("#aCsIn").value); };
    panel.querySelector("#aCsRand").onclick = () => done(CALLSIGNS[Math.floor(Math.random() * CALLSIGNS.length)]);
    if (!back) say("Every astronaut has a call sign. Pick yours!", { situation: "lesson_brief" });
  }

  // ---------- course map: a catalog of tracks (full stage), CAPCOM mentor card, patch shelf ----------
  function trackOf(id) { const t = TRACKS.find(t => t.lessons.includes(id)); return t ? t.id : "foundations"; }
  function showMap(quiet) {
    if (!callSign.get()) return showCallSign();
    view = "map"; L = null; endRide(); globe.flyTo(0, 0, 3.6);
    const ls = lessons(), nx = nextLesson(), n = ls.filter(l => has(l.badge.id)).length, cs = callSign.shown();
    panel.classList.add("is-catalog"); panel.classList.remove("is-ride"); document.body.dataset.aview = "map";
    const mentor = prog.qualified ? MENTOR.done(cs) : !n ? MENTOR.first(cs) : nx && nx.ride ? MENTOR.ride(cs) : MENTOR.more(cs, n, nx ? nx.title : "");
    const card = (l) => {
      const k = ls.indexOf(l), done = has(l.badge.id), next = nx && nx.id === l.id;
      return `<button type="button" class="a-lcard${done ? " is-done" : ""}${next ? " is-next" : ""}${l.ride ? " is-ride" : ""}" data-l="${esc(l.id)}">
        <span class="a-lhead"><span class="a-patch" aria-hidden="true"><span>${patchOf(l)}</span>${done ? `<i class="a-stamp">✓</i>` : ""}</span>
          <span class="a-nt"><b>${k + 1} · ${esc(l.title)}</b><small>${l.minutes} min${l.ride ? " · solo shift" : ""}</small></span></span>
        <span class="a-blurb">${esc(LESSON_BLURB[l.id] || l.brief)}</span>
        ${done ? `<span class="a-tag is-done">✓ ${esc(l.badge.name)} patch</span>` : next ? `<span class="a-tag is-next">Next up</span>` : ""}
      </button>`;
    };
    const tracks = TRACKS.map(t => ({ ...t, items: ls.filter(l => trackOf(l.id) === t.id) })).filter(t => t.items.length);
    panel.innerHTML = `
      <div class="a-cat">
        <div class="a-main">
          <p class="eyebrow">${esc(SCHOOL.eyebrow)} · Cadet ${esc(cs)}</p>
          <h2 class="a-hero">${esc(SCHOOL.hero)}<br>${esc(SCHOOL.hero2)}</h2>
          <p class="m-sub">${esc(prog.qualified ? SCHOOL.subDone : SCHOOL.sub)}</p>
          <div class="a-prog"><span class="a-bar"><i style="width:${ls.length ? n / ls.length * 100 : 0}%"></i></span><span>${n} of ${ls.length} patches</span></div>
          <div class="a-tracks">${tracks.map((t, k) => `<section class="a-track${t.items.length < 2 ? " is-half" : ""}"><h3>${t.id === "qual" ? "" : `Track ${k + 1} · `}${esc(t.title)}</h3><div class="a-cards">${t.items.map(card).join("")}</div></section>`).join("")}</div>
        </div>
        <aside class="a-side">
          <section class="a-mentor"><header><span class="a-avatar" aria-hidden="true">CC</span><span><b>CAPCOM</b><small>${esc(MENTOR.role)}</small></span>
            <button type="button" class="a-csedit" id="aCsEdit" title="Change your call sign">🧑‍🚀 ${esc(cs)}</button></header>
            <p>“${esc(mentor)}”</p>
            ${prog.qualified ? `<button type="button" class="m-go" id="aGoMission">🛰️ ${esc(SCHOOL.go)}</button>`
              : nx ? `<button type="button" class="m-go" id="aStart">${nx.ride ? "🚀 Fly your check ride" : `${n ? "Continue" : "Start"}: ${esc(nx.title)}`}</button>` : ""}
            <small class="a-voice">${esc(MENTOR.voice)}</small></section>
          <section class="a-shelf"><h3>Your patches</h3><div>${ls.map(l => `<span class="a-patch${has(l.badge.id) ? " is-earned" : ""}" title="${esc(l.badge.name)}${has(l.badge.id) ? "" : " (not yet)"}"><span>${has(l.badge.id) ? patchOf(l) : ""}</span></span>`).join("")}</div></section>
          <section class="a-why"><h3>Why this matters</h3><p>${esc(WHY)}</p><p class="a-credit">${esc(CREDIT)}</p></section>
        </aside>
      </div>`;
    panel.querySelectorAll(".a-lcard").forEach(b => b.onclick = () => openLesson(b.dataset.l));
    panel.querySelector("#aCsEdit").onclick = () => showCallSign(() => showMap(true));
    const go = panel.querySelector("#aGoMission"); if (go) go.onclick = () => goMission();
    const st = panel.querySelector("#aStart"); if (st) st.onclick = () => openLesson(nx.id);
    if (!quiet && view === "map") { /* the mentor line is read on the button press; the map stays quiet */ }
  }
  function leaveCatalog() { panel.classList.remove("is-catalog"); delete document.body.dataset.aview; }

  // ---------- lesson ----------
  async function openLesson(id) {
    L = lessons().find(l => l.id === id); if (!L) return;
    view = "lesson"; i = 0; misses = 0; waitingNext = false; feedback = null; leaveCatalog();
    endRide();
    if (L.ride) {
      try { ride = await academyApi.ride(); } catch (e) { ride = null; }
      await showRideSite();
    } else if (L.globe) {
      const f = L.globe.place && placeById(L.globe.place);
      if (f) globe.showFeature(f, { dist: L.globe.dist }); else if (L.globe.lat != null) globe.flyTo(L.globe.lat, L.globe.lon, L.globe.dist || 3.6);
    }
    render();
    const beat = (LESSON_STORY[L.id] || {}).beat || "";
    say(`${CAPCOM.lessonHello(callSign.spoken("cadet"), beat)} ${L.brief} ${L.steps[0].prompt}`, { situation: "lesson_brief" });
    if (L.steps[0].alert) alertSound();
  }

  function render() {
    if (view !== "lesson" || !L) return;
    const st = L.steps[i], k = lessons().indexOf(L), acc = st.accept;
    const clip = st.clip || (i === 0 ? L.clip : null);
    panel.classList.toggle("is-ride", !!L.ride);
    const ctx = { L, i, answer, esc, clip, done: waitingNext };
    // Registry entries are either {html(step, ctx), wire?(el, ctx)} or, for modules like academy/vocab.js,
    // a factory fn({step, acc, answer, esc, say, playCrew, captions}) → {html, bind(el)}.
    const A11 = typeof window !== "undefined" && window.__outpost && window.__outpost.a11y;
    const E = STEP_RENDERERS[acc.type];
    const R = typeof E === "function"
      ? (o => ({ html: () => o.html, wire: el => o.bind && o.bind(el) }))(E({ step: st, acc, answer, esc, say: (t, style) => say(t, style), playCrew: m => player.play(m), captions: A11 ? A11.settings.captions : true }))
      : (E || { html: () => "" });
    const story = LESSON_STORY[L.id] || {};
    panel.innerHTML = `
      <header class="m-head"><button type="button" class="a-back" id="aBack" aria-label="Back to the patch map">‹ Map</button>
        <span class="eyebrow">${L.ride ? "Check ride · solo shift" : `Lesson ${k + 1} of ${lessons().length}`}</span>
        <span class="a-dots" role="img" aria-label="Step ${i + 1} of ${L.steps.length}">${L.steps.map((_, j) => `<i class="${j < i || (j === i && waitingNext) ? "is-done" : j === i ? "is-now" : ""}"></i>`).join("")}</span></header>
      <div class="a-title"><span class="a-patch is-sm" aria-hidden="true"><span>${patchOf(L)}</span></span><h2 class="m-title">${esc(L.title)}</h2></div>
      ${L.ride && (i > 0 || waitingNext || feedback) ? "" : `<section class="a-brief"><p class="a-beat">${esc(story.beat || "")}</p>
        <div class="a-bubble"><span class="a-who">CAPCOM</span><p>${esc(L.brief)}</p></div>
        <span class="a-row"><button type="button" class="pill" id="aReplay">🔊 Hear it again</button>
        ${L.library ? `<button type="button" class="pill" id="aLib">${esc(L.library.label)}</button>` : ""}
        <details class="a-facts"><summary>NASA facts (${L.facts.length})</summary>
        <ul>${L.facts.map(f => `<li>${esc(f.text)} ${src(f.source)}</li>`).join("")}</ul></details></span></section>`}
      <section class="a-step${st.alert ? " is-alert" : ""}" aria-live="polite">
        <p class="a-prompt">${st.alert ? `<span class="a-alarm" aria-hidden="true">🚨</span> ` : ""}${esc(st.prompt)}</p>
        ${clip ? `<button type="button" class="pill hot a-clip" id="aClip">▶ Hear ${esc(clip.who)}</button>` : ""}
        <div class="a-input" id="aInput">${waitingNext ? "" : R.html(st, ctx)}</div>
        <p class="a-feedback${feedback ? " is-" + feedback.kind : ""}" id="aFeedback">${feedback ? (feedback.kind === "ok" ? "✅ " : "") + esc(feedback.text) : ""}</p>
        ${feedback && feedback.hint ? `<p class="a-hint"><b>Hint</b> ${esc(feedback.hint)}</p>` : ""}
        ${waitingNext ? `<button type="button" class="m-go" id="aNext">Next ›</button>` : ""}
      </section>
      ${ride ? `<div id="aRideSlot"></div>` : ""}
      ${todo(waitingNext ? "Tap Next, or say “next”." : esc(HOW[acc.type] || "Answer CAPCOM: say it, or type it below."))}`;
    panel.querySelector("#aBack").onclick = () => { stop(); showMap(); };
    const rp = panel.querySelector("#aReplay"); if (rp) rp.onclick = () => say(L.brief);
    const lib = panel.querySelector("#aLib"); if (lib) lib.onclick = () => openLibrary(L.library.place);
    const cb = panel.querySelector("#aClip");
    if (cb) cb.onclick = () => player.play({ clip_id: clip.clip_id, t0: clip.t0, t1: clip.t1, speaker: clip.who, places: [], jargon: [] });
    if (!waitingNext && R.wire) R.wire(panel.querySelector("#aInput"), ctx);
    const slot = panel.querySelector("#aRideSlot"); if (slot && rideEl) { slot.replaceWith(rideEl); if (ride.state) rideCk.update(ride.state); }
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
    waitingNext = false; feedback = null; misses = 0; i++;
    render(); speakLine(L.steps[i].prompt);
    if (L.steps[i].alert) alertSound();
  }

  // ---------- check ride: the first solo shift, in a simplified cockpit ----------
  async function showRideSite() {
    if (!rideSite) {
      try { const s = await (await fetch("/api/mission/sites")).json(); rideSite = s.sites.find(x => x.id === L.ride.site); } catch (e) { rideSite = null; }
    }
    rideEl = document.createElement("section"); rideEl.className = "a-ride"; rideEl.setAttribute("aria-label", "Check ride cockpit");
    rideCk = createCockpit(rideEl, { mode: "mini" });
    if (ride && ride.state) rideCk.update(ride.state);
    if (!rideSite) return;
    globe.mission.enter();
    globe.mission.setSite({ ...rideSite, short: rideSite.name.split(" (")[0] }, { dist: 2.2 });
    syncRideGlobe();
  }
  function syncRideGlobe() {
    if (!ride || !ride.state) return;
    if (rideCk) rideCk.update(ride.state);
    if (!rideSite) return;
    const e = ride.state.env;
    globe.mission.setSun(e.sun_elev_deg, ride.state.mission_time_h); globe.mission.setEarth(e.earth_elev_deg);
  }
  function endRide() { if (ride) { ride = null; globe.mission.exit(); } rideEl = null; rideCk = null; }
  function rideStep(r) {
    if (r.status === "done") {
      feedback = { kind: r.passed ? "ok" : "retry", text: r.say };
      if (r.passed && r.badge) { award(r.badge, true); waitingNext = true; render(); speakLine(r.say, r); setTimeout(() => showBadge(r.badge, true), 1200); return true; }
      waitingNext = false; render(); speakLine(r.say, r);
      const inp = panel.querySelector("#aInput"); inp.innerHTML = `<button type="button" class="m-go" id="aRetry">🔁 Fly the check ride again</button>`;
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
    view = "badge";
    const nx = nextLesson(), cs = callSign.shown();
    panel.innerHTML = `
      <div class="a-badge" role="status">
        <div class="a-burst" aria-hidden="true">${Array.from({ length: 12 }, (_, k) => `<i style="--k:${k}"></i>`).join("")}</div>
        <div class="a-patch is-big" aria-hidden="true"><span>${patchOf(L)}</span><i class="a-stamp">✓</i></div>
        <p class="eyebrow">${commander ? "Qualified" : "Patch earned"}</p>
        <h2 class="m-title">${esc(badge.name)}</h2>
        <p class="m-sub">${commander ? `You flew your first solo shift, ${esc(cs)}. Outpost Luna is ready for its commander.` : `Nice work, ${esc(cs)}. You finished “${esc(L.title)}”.`}</p>
        <div class="a-actions">
          ${commander ? `<button type="button" class="m-go" id="aGoMission">🛰️ ${esc(SCHOOL.go)}</button>`
            : nx ? `<button type="button" class="m-go" id="aNextLesson">${nx.ride ? "🚀 Fly your check ride" : `Next: ${esc(nx.title)}`}</button>` : ""}
          <button type="button" class="pill" id="aMap">Patch map</button>
        </div>
        ${todo("Say “next”, or tap the button.")}
      </div>`;
    say(commander ? CAPCOM.qualified(callSign.spoken(), badge.name) : CAPCOM.patch(callSign.spoken("cadet"), badge.name), { situation: "badge" });
    const g = panel.querySelector("#aGoMission"); if (g) g.onclick = () => goMission();
    const n = panel.querySelector("#aNextLesson"); if (n) n.onclick = () => openLesson(nx.id);
    panel.querySelector("#aMap").onclick = () => showMap();
    (g || n || panel.querySelector("#aMap")).focus({ preventScroll: true });
  }

  // ---------- inputs from the rest of the app ----------
  /** A typed or spoken turn. True when the Academy used it. */
  async function handleText(text) {
    if (!ui.active) return false;
    const t = text.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
    if (view === "callsign") {
      const hit = CALLSIGNS.find(c => t.includes(c.toLowerCase()));
      if (hit) { callSign.set(hit); say(`Copy that, ${hit}. Welcome to Flight School.`, { situation: "badge" }); showMap(true); return true; }
      if (/surprise|random|any|you pick|pick for me/.test(t)) { panel.querySelector("#aCsRand").click(); return true; }
      say("Pick one from the list, like Nova or Comet."); return true;
    }
    if (view === "badge" || view === "map") {
      if (NEXT_WORDS.test(t)) { const nx = nextLesson(); if (prog.qualified && (view === "badge" || !nx)) goMission(); else if (nx) openLesson(nx.id); return true; }
      return false;
    }
    if (view !== "lesson") return false;
    if (waitingNext) { if (NEXT_WORDS.test(t)) next(); else speakLine("Say next, or tap Next."); return true; }
    if (L.steps[i].accept.type === "tap") { feedback = { kind: "retry", text: "For this one, tap the Moon." }; render(); return true; }
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
