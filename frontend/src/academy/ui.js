// Junior Astronaut Academy UI: course map → lesson (CAPCOM brief, one step at a time, voice/type/tap answers, hints
// after 2 misses) → badge moment. Lesson 7 is a check ride on the real mission simulator; passing it qualifies the
// cadet for Mission mode. Grading is server-side (POST /api/academy/attempt); progress stays on this device.
import { academyApi, progress } from "./client.js";
import { sayStyle } from "../floor.js";
import { APP_NAME } from "../brand.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const src = s => s && s.url ? `<a class="chip-src" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : "";
const pct = v => Math.max(0, Math.min(100, +v || 0));
const NEXT_WORDS = /^(next|next one|continue|go on|ok|okay|ready|let s go|lets go)\b/;
const HOW = { intent: "Say it, type it below, or tap the Moon", tap: "Tap the Moon", command: "Give the order: say it or type it below",
  keywords: "Say your readback, or type it below", choice: "Tap an answer, or say it" };

/**
 * @param {object} o
 * @param {object} o.globe       globe.js instance
 * @param {(id:string)=>object} o.placeById
 * @param {(text:string)=>Promise} o.say    speak as CAPCOM
 * @param {object} o.player      crew player (lesson clips)
 * @param {()=>void} o.alertSound
 * @param {()=>void} o.goMission  switch to Mission mode (site briefing)
 * @param {(p:object)=>void} o.onProgress  progress changed (badges / qualified)
 */
export function createAcademyUI({ globe, placeById, say, player, alertSound = () => {}, stop = () => {}, goMission = () => {}, openLibrary = () => {}, onProgress = () => {} }) {
  const panel = document.getElementById("aPanel");
  let course = null, prog = progress.load(), view = "off", L = null, i = 0, misses = 0, waitingNext = false, busy = false;
  let ride = null, rideSite = null, feedback = null;
  const ui = { active: false, enter, exit, handleText, onTap, onArtifact, get progress() { return prog; } };

  const lessons = () => (course ? course.lessons : []);
  const has = id => prog.badges.includes(id);
  const nextLesson = () => lessons().find(l => !has(l.badge.id)) || null;
  const speakLine = (t, r) => { if (t) say(t, sayStyle(r)); };   // r: the attempt response; its say.style steers

  async function enter() {
    ui.active = true; panel.hidden = false;
    if (!course) {
      panel.innerHTML = `<p class="m-wait">Loading the Academy…</p>`;
      try { course = await academyApi.course(); }
      catch (e) { panel.innerHTML = `<p class="m-wait">Can't reach the Academy server. Start everything with <code>make dev</code>.</p>`; return; }
    }
    if (!ui.active) return;
    showMap();
  }
  function exit() {
    ui.active = false; view = "off"; panel.hidden = true; endRide();
  }

  // ---------- course map ----------
  function showMap() {
    view = "map"; L = null; endRide(); globe.flyTo(0, 0, 3.6);
    const nx = nextLesson(), n = prog.badges.filter(b => lessons().some(l => l.badge.id === b)).length;
    panel.innerHTML = `
      <header class="m-head"><span class="eyebrow">${esc(APP_NAME)} Academy</span><span class="a-count">${n} of ${lessons().length} badges</span></header>
      <h2 class="m-title">${prog.qualified ? "You're qualified, Commander!" : "Train for the Moon"}</h2>
      <p class="m-sub">${prog.qualified ? "Replay any lesson, or start your first mission." : "Artemis III plans to land near the Moon's south pole. Train for it here: short lessons with CAPCOM, then a check ride to command the outpost."}</p>
      <ol class="a-path">${lessons().map((l, k) => {
        const done = has(l.badge.id), next = nx && nx.id === l.id;
        return `<li><button type="button" class="a-node${done ? " is-done" : ""}${next ? " is-next" : ""}" data-l="${esc(l.id)}">
          <span class="a-medal" aria-hidden="true">${done ? esc(l.badge.glyph) : k + 1}</span>
          <span class="a-nt"><b>${esc(l.title)}</b><small>${done ? "Badge: " + esc(l.badge.name) : next ? "Next up · " + l.minutes + " min" : l.minutes + " min"}</small></span>
          ${l.ride ? `<span class="a-final">Final</span>` : ""}</button></li>`;
      }).join("")}</ol>
      ${prog.qualified ? `<button type="button" class="m-go" id="aGoMission">Ready for your first mission</button>`
        : nx ? `<button type="button" class="m-go" id="aStart">${prog.badges.length ? "Continue" : "Start training"}: ${esc(nx.title)}</button>` : ""}
      <p class="a-credit">Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA.</p>`;
    panel.querySelectorAll(".a-node").forEach(b => b.onclick = () => openLesson(b.dataset.l));
    const go = panel.querySelector("#aGoMission"); if (go) go.onclick = () => goMission();
    const st = panel.querySelector("#aStart"); if (st) st.onclick = () => openLesson(nx.id);
  }

  // ---------- lesson ----------
  async function openLesson(id) {
    L = lessons().find(l => l.id === id); if (!L) return;
    view = "lesson"; i = 0; misses = 0; waitingNext = false; feedback = null;
    endRide();
    if (L.ride) {
      try { ride = await academyApi.ride(); } catch (e) { ride = null; }
      await showRideSite();
    } else if (L.globe) {
      const f = L.globe.place && placeById(L.globe.place);
      if (f) globe.showFeature(f, { dist: L.globe.dist }); else if (L.globe.lat != null) globe.flyTo(L.globe.lat, L.globe.lon, L.globe.dist || 3.6);
    }
    render();
    say(`${L.brief} ${L.steps[0].prompt}`, { situation: "lesson_brief" });
    if (L.steps[0].alert) alertSound();
  }

  function render() {
    if (view !== "lesson" || !L) return;
    const st = L.steps[i], k = lessons().indexOf(L), acc = st.accept;
    const clip = st.clip || (i === 0 ? L.clip : null);
    // ---- [a11y/vocab] step renderers registered by other modules (academy/vocab.js): window.__outpost.stepRenderers ----
    const RF = typeof window !== "undefined" && window.__outpost && window.__outpost.stepRenderers && window.__outpost.stepRenderers[acc.type];
    const A11 = typeof window !== "undefined" && window.__outpost && window.__outpost.a11y;
    const R = RF ? RF({ step: st, acc, answer, esc, say: (t, style) => say(t, style), playCrew: m => player.play(m), captions: A11 ? A11.settings.captions : true }) : null;
    // ---- end [a11y/vocab] ----
    panel.innerHTML = `
      <header class="m-head"><button type="button" class="a-back" id="aBack" aria-label="Back to the course map">‹ Course</button>
        <span class="eyebrow">Lesson ${k + 1} of ${lessons().length}</span>
        <span class="a-dots" aria-label="Step ${i + 1} of ${L.steps.length}">${L.steps.map((_, j) => `<i class="${j < i || (j === i && waitingNext) ? "is-done" : j === i ? "is-now" : ""}"></i>`).join("")}</span></header>
      <h2 class="m-title">${esc(L.title)}</h2>
      <section class="a-brief"><span class="a-who">CAPCOM</span><p>${esc(L.brief)}</p>
        <span class="a-row"><button type="button" class="pill" id="aReplay">Hear it again</button>
        ${L.library ? `<button type="button" class="pill" id="aLib">${esc(L.library.label)}</button>` : ""}</span></section>
      <details class="a-facts"><summary>Real NASA facts (${L.facts.length})</summary>
        <ul>${L.facts.map(f => `<li>${esc(f.text)} ${src(f.source)}</li>`).join("")}</ul></details>
      ${ride ? rideHud() : ""}
      <section class="a-step${st.alert ? " is-alert" : ""}" aria-live="polite">
        <p class="a-prompt">${esc(st.prompt)}</p>
        ${clip ? `<button type="button" class="pill hot a-clip" id="aClip">▶ Hear ${esc(clip.who)}</button>` : ""}
        ${R ? R.html : acc.type === "choice" ? `<div class="a-choices">${acc.options.map(o => `<button type="button" class="a-choice" data-c="${esc(o.id)}">${esc(o.label)}</button>`).join("")}</div>`
          : `<p class="a-how">${esc(HOW[acc.type] || "")}</p>`}
        <p class="a-feedback${feedback ? " is-" + feedback.kind : ""}" id="aFeedback">${feedback ? esc(feedback.text) : ""}</p>
        ${feedback && feedback.hint ? `<p class="a-hint"><b>Hint</b> ${esc(feedback.hint)}</p>` : ""}
        ${waitingNext ? `<button type="button" class="m-go" id="aNext">Next</button>` : ""}
      </section>`;
    panel.querySelector("#aBack").onclick = () => { stop(); showMap(); };
    panel.querySelector("#aReplay").onclick = () => say(L.brief);
    const lib = panel.querySelector("#aLib"); if (lib) lib.onclick = () => openLibrary(L.library.place);
    const cb = panel.querySelector("#aClip");
    if (cb) cb.onclick = () => player.play({ clip_id: clip.clip_id, t0: clip.t0, t1: clip.t1, speaker: clip.who, places: [], jargon: [] });
    panel.querySelectorAll(".a-choice").forEach(b => b.onclick = () => answer({ choice: b.dataset.c }, b));
    const nb = panel.querySelector("#aNext"); if (nb) { nb.onclick = next; nb.focus({ preventScroll: true }); }
    if (R && R.bind) R.bind(panel.querySelector(".a-step"));   // [a11y/vocab]
  }

  async function answer(input, btn) {
    if (busy || view !== "lesson" || waitingNext) return false;
    busy = true;
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
      if (r.badge) { award(r.badge); speakLine(r.say, r); setTimeout(() => showBadge(r.badge), 900); return true; }
      waitingNext = true; render(); speakLine(r.say, r);
      return true;
    }
    misses++;
    if (btn) btn.classList.add("is-wrong");
    feedback = { kind: "retry", text: r.status === "hint" ? L.steps[i].fail : r.say, hint: r.hint };
    render(); speakLine(r.say, r);
    return true;
  }

  function next() {
    if (!waitingNext) return;
    waitingNext = false; feedback = null; misses = 0; i++;
    render(); speakLine(L.steps[i].prompt);
    if (L.steps[i].alert) alertSound();
  }

  // ---------- check ride ----------
  async function showRideSite() {
    if (!rideSite) {
      try { const s = await (await fetch("/api/mission/sites")).json(); rideSite = s.sites.find(x => x.id === L.ride.site); } catch (e) { rideSite = null; }
    }
    if (!rideSite) return;
    globe.mission.enter();
    globe.mission.setSite({ ...rideSite, short: rideSite.name.split(" (")[0] }, { dist: 2.2 });
    syncRideGlobe();
  }
  function syncRideGlobe() {
    if (!ride || !ride.state || !rideSite) return;
    const e = ride.state.env;
    globe.mission.setSun(e.sun_elev_deg, ride.state.mission_time_h); globe.mission.setEarth(e.earth_elev_deg);
  }
  function endRide() { if (ride) { ride = null; globe.mission.exit(); } }
  function rideHud() {
    const s = ride.state; if (!s) return "";
    const r = s.resources, storm = s.env.storm && s.env.storm.active;
    const bar = (id, name, v, max, txt) => `<div class="m-bar" id="mb-${id}"><div class="m-bl"><b>${name}</b><span class="m-help"></span><span class="m-val">${txt}</span></div>
      <div class="m-track"><i class="m-fill" style="width:${pct(v / max * 100)}%"></i></div></div>`;
    const ev = (ride.events || []).slice(-2);
    return `<section class="a-ride"><div class="a-ride-top"><b>Day ${s.day}, shift ${s.shift}</b>
        <span>${s.shelter ? "In the shelter" : s.env.in_sun ? "Sun up" : "Dark"}${storm ? " · <em>Solar storm</em>" : ""}</span></div>
      <div class="m-bars">${bar("power", "Power", r.power_pct, 100, Math.round(r.power_pct) + "%")}${bar("life", "Life support", r.life_support_pct, 100, Math.round(r.life_support_pct) + "%")}
        ${bar("dose", "Dose", r.dose_msv, r.dose_limit_msv, r.dose_msv.toFixed(1) + " / " + r.dose_limit_msv + " mSv")}</div>
      ${ev.length ? `<ul class="a-events">${ev.map(e => `<li>${esc(e.text)} ${src(e.source)}</li>`).join("")}</ul>` : ""}</section>`;
  }
  function rideStep(r) {
    if (r.status === "done") {
      feedback = { kind: r.passed ? "ok" : "retry", text: r.say };
      if (r.passed && r.badge) { award(r.badge, true); render(); speakLine(r.say, r); setTimeout(() => showBadge(r.badge, true), 1200); return true; }
      waitingNext = false; render(); speakLine(r.say, r);
      const sec = panel.querySelector(".a-step");
      sec.insertAdjacentHTML("beforeend", `<button type="button" class="m-go" id="aRetry">Try the check ride again</button>`);
      panel.querySelector("#aRetry").onclick = () => openLesson(L.id);
      return true;
    }
    feedback = { kind: r.status === "passed" ? "ok" : "retry", text: r.say + (r.sim_say ? " " + r.sim_say : "") };
    waitingNext = true; misses = 0; render(); speakLine(r.say, r);
    return true;
  }

  // ---------- badges ----------
  function award(badge, qualifies) {
    if (!prog.badges.includes(badge.id)) prog.badges.push(badge.id);
    if (qualifies) prog.qualified = true;
    progress.save(prog); onProgress(prog);
  }
  function showBadge(badge, commander) {
    if (view !== "lesson") return;
    view = "badge";
    const nx = nextLesson();
    panel.innerHTML = `
      <div class="a-badge" role="status">
        <div class="a-burst" aria-hidden="true">${Array.from({ length: 12 }, (_, k) => `<i style="--k:${k}"></i>`).join("")}</div>
        <div class="a-medal is-big" aria-hidden="true">${esc(badge.glyph)}</div>
        <p class="eyebrow">Badge earned</p>
        <h2 class="m-title">${esc(badge.name)}</h2>
        <p class="m-sub">${commander ? "You passed the check ride. Mission mode is unlocked: you're qualified to command the outpost." : `You finished “${esc(L.title)}”.`}</p>
        <div class="a-actions">
          ${commander ? `<button type="button" class="m-go" id="aGoMission">Ready for your first mission</button>`
            : nx ? `<button type="button" class="m-go" id="aNextLesson">Next: ${esc(nx.title)}</button>` : ""}
          <button type="button" class="pill" id="aMap">Course map</button>
        </div>
      </div>`;
    say(commander ? `Congratulations, Commander! You earned the ${badge.name} badge.` : `Badge earned: ${badge.name}!`, { situation: "badge" });
    const g = panel.querySelector("#aGoMission"); if (g) g.onclick = () => goMission();
    const n = panel.querySelector("#aNextLesson"); if (n) n.onclick = () => openLesson(nx.id);
    panel.querySelector("#aMap").onclick = showMap;
    (g || n || panel.querySelector("#aMap")).focus({ preventScroll: true });
  }

  // ---------- inputs from the rest of the app ----------
  /** A typed or spoken turn. True when the Academy used it. */
  async function handleText(text) {
    if (!ui.active) return false;
    const t = text.toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
    if (view === "badge" || view === "map") {
      if (NEXT_WORDS.test(t)) { const nx = nextLesson(); if (prog.qualified && view === "badge") goMission(); else if (nx) openLesson(nx.id); return true; }
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
