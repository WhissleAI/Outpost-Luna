// Mission Trainer UI: briefing (pick a site), HUD (3 resources, loads, environment, rover, End shift), events,
// CAPCOM card, Houston delay, debrief. Talks to the backend through client.js, or the local mock (labelled "Sample data").
import { createMissionClient } from "./client.js";
import { parseCommand } from "./mock.js";

const LOADS = [["shields", "Shields"], ["life_support", "Life support"], ["greenhouse", "Greenhouse"], ["science", "Science"],
  ["rover", "Rover"], ["comms", "Comms"], ["heaters", "Heaters"]];
const LOAD_HELP = { shields: "Blocks radiation", life_support: "Makes air and water", greenhouse: "Plants make oxygen", science: "Earns points",
  rover: "Drives the rover", comms: "Talks to Earth", heaters: "Keeps things warm at night" };
const ROLES = [["power", "Power"], ["life", "Life support"], ["comms", "Comms"]];
const TASK = { collect_ice: "collecting ice", explore: "exploring", repair_array: "fixing a solar panel", return: "driving home" };
// Ice and explore targets near the south pole (real places: Shackleton crater, Cabeus where LCROSS found water).
const TARGETS = { collect_ice: { lat: -89.67, lon: 129.78, name: "Shackleton" }, explore: { lat: -84.68, lon: -48.7, name: "Cabeus" }, repair_array: null, return: null };
// Lessons from hardware already on the Moon: the artifact id, and what it teaches an outpost commander.
const LESSONS = [
  ["surveyor3", "Machines can last. Apollo 12 took Surveyor 3's camera home after 2½ years, to see what space does to hardware."],
  ["lcross_centaur_impact", "Ice hides in the dark. LCROSS hit Cabeus crater near the south pole and found water in the dust cloud."],
  ["apollo15_lrv", "Don't drive too far. Apollo 15's rover went 27.8 km but stayed within 5 km of the lander, so the crew could walk back."],
];

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = v => Math.max(0, Math.min(100, +v || 0));
const src = s => s && s.url ? `<a class="chip-src" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title || new URL(s.url).hostname)}</a>` : "";

/**
 * @param {object} o
 * @param {object} o.globe   globe.js instance (uses .mission)
 * @param {object} o.card    card.js instance (becomes CAPCOM)
 * @param {(id:string)=>object} o.placeById
 * @param {(text:string)=>Promise} o.say     speak as CAPCOM
 * @param {()=>void} o.alertSound
 * @param {(frame:object)=>void} o.onContext  forward a context frame to the listen socket
 */
export function createMissionUI({ globe, card, placeById, say, alertSound, onContext = () => {}, askDirector = null }) {
  const $ = id => document.getElementById(id);
  const panel = $("mPanel"), banner = $("mBanner"), signal = $("mSignal"), debriefEl = $("mDebrief");
  let client = null, sites = [], site = null, state = null, prev = null, roles = new Set(), unsub = null, live = null;
  let screen = "off", pending = null, bannerT = null, siteSeed = null;

  const shortName = n => n.split(" (")[0].replace(/ rocket impact site| impact site/, "");
  const lessons = () => LESSONS.map(([id, text]) => { const a = placeById(id); return a ? { text, name: shortName(a.name), source: (a.sources || [])[0] } : null; }).filter(Boolean);
  const sampleTag = () => client && client.sample ? `<span class="m-sample" title="The mission server isn't running yet; this is a local practice model.">Sample data</span>` : "";

  // ---------- briefing ----------
  async function enter() {
    globe.mission.enter();
    if (!client) {
      panel.hidden = false; panel.innerHTML = `<p class="m-wait">Loading mission sites…</p>`;
      client = await createMissionClient(); sites = client.sites || [];
    }
    if (state && !state.over) { showHud(); return; }
    briefing();
  }
  function exit() { screen = "off"; globe.mission.exit(); panel.hidden = true; banner.hidden = true; debriefEl.hidden = true; signal.hidden = true; }

  function briefing() {
    screen = "brief"; debriefEl.hidden = true; banner.hidden = true; panel.hidden = false;
    if (!site) site = sites[0];
    panel.innerHTML = `
      <header class="m-head"><span class="eyebrow">Briefing</span>${sampleTag()}</header>
      <h2 class="m-title">Pick your outpost</h2>
      <p class="m-sub">Sun charges batteries. Ice makes water. You can call home only when Earth is up.</p>
      <div class="m-sites" role="radiogroup" aria-label="Outpost site">${sites.map(s => `
        <button type="button" class="m-site" role="radio" data-site="${esc(s.id)}" aria-checked="${s === site}">
          <b>${esc(s.name)}</b>
          <span class="m-facts"><span title="How much of the time the Sun shines here">☀ ${Math.round(s.sunlight_pct)}% sun</span>
            <span>${s.ice ? "❄ Ice nearby" : "No ice nearby"}</span><span title="How much of the time Earth is above the horizon">🌍 Earth ${Math.round(s.earth_visible_pct)}%</span></span>
        </button>`).join("")}
      </div>
      <p class="m-note">${esc(site && site.notes || "")}</p>
      <div class="m-srcrow">${(site && site.sources || []).map(src).join("")}</div>
      <section class="m-roles"><span class="eyebrow">Team roles (optional)</span>
        <div>${ROLES.map(([id, n]) => `<button type="button" class="m-role" data-role="${id}" aria-pressed="${roles.has(id)}">${n}</button>`).join("")}</div></section>
      <button type="button" class="m-go" id="mStart">Start mission</button>`;
    panel.querySelectorAll(".m-site").forEach(b => b.onclick = () => { site = sites.find(s => s.id === b.dataset.site); previewSite(); briefing(); });
    panel.querySelectorAll(".m-role").forEach(b => b.onclick = () => { const r = b.dataset.role; roles.has(r) ? roles.delete(r) : roles.add(r); b.setAttribute("aria-pressed", roles.has(r)); });
    $("mStart").onclick = () => start();
    previewSite();
    briefCard();
  }
  /** CAPCOM's welcome + lessons from hardware already on the Moon (real artifacts from /api/places). */
  function briefCard() {
    card.show({ title: "CAPCOM", eyebrow: "Briefing" + (client.sample ? " · Sample data" : ""),
      say: "Welcome, Commander. Pick a site, then keep power, life support and radiation safe for ten days.",
      lessons: lessons().map(l => ({ text: l.text, source: { ...l.source, title: l.name } })) });
  }
  function previewSite() {
    if (!site) return;
    globe.mission.setSite({ ...site, short: site.name.split(" (")[0] }, { dist: 2.5 });
    globe.mission.setSun(1, 0); globe.mission.setEarth(site.earth_visible_pct > 60 ? 3 : -1); globe.mission.setRover(null);
  }

  async function start(seed) {
    siteSeed = seed ?? Math.floor(Math.random() * 1e9);
    state = await client.start({ site: site.id, seed: siteSeed, roles: [...roles] }); prev = null;
    if (unsub) unsub();
    unsub = client.subscribe(state.id, onTelemetry);
    pushContext();
    showHud();
    const line = `Mission started at ${site.name}. Day 1. Check your power split, then say "end shift".`;
    capcom({ say: line }); say(line);
  }

  // ---------- HUD ----------
  function estimate(s) {   // client-side "next shift" preview of the current choices (a rough model; the server decides)
    const r = s.resources, L = s.loads, e = s.env, sun = s.site && s.site.sunlight_pct || 75;
    const solar = e.in_sun ? 3.2 * sun / 80 : 0, draw = 1.5 + (e.in_sun ? 0 : Math.max(0, .8 - L.heaters / 25)) + (s.shelter ? .3 : 0) + (s.rover && s.rover.busy ? .35 : 0);
    const base = e.storm && e.storm.active ? .25 * (e.storm.severity || 2) : .012;
    const rate = base * Math.max(.15, 1 - L.shields / 60) * (s.shelter ? .12 : 1);
    return { power: pct(r.power_pct + 6 * (solar - draw)), life: pct(r.life_support_pct + 6 * ((L.life_support - 28) * .03 + L.greenhouse * .012 - .18)), dose: r.dose_msv + 6 * rate };
  }
  const arrow = (now, before) => before == null ? "" : now > before + .4 ? "↑" : now < before - .4 ? "↓" : "→";

  function showHud() {
    screen = "hud"; debriefEl.hidden = true; panel.hidden = false;
    panel.innerHTML = `
      <header class="m-head"><span class="eyebrow" id="mClock"></span>${sampleTag()}<span class="m-score" id="mScore"></span></header>
      <div class="m-bars">
        ${bar("power", "Power", "Battery charge")}
        ${bar("life", "Life support", "Air and water left")}
        ${bar("dose", "Dose", "Radiation")}
        <p class="m-unit"><b>mSv</b>: how we measure radiation dose. Stay under the limit. <span id="mRate"></span></p>
      </div>
      <section class="m-loads" aria-label="Power split"><header><span class="eyebrow">Power split</span><small id="mSum"></small></header>
        ${LOADS.map(([k, n]) => `<div class="m-load" data-k="${k}"><span class="m-ln" title="${esc(LOAD_HELP[k])}">${n}</span>
          <button type="button" class="m-pm" data-d="-5" aria-label="Less ${n}">−</button>
          <span class="m-lv"><i></i><b></b></span>
          <button type="button" class="m-pm" data-d="5" aria-label="More ${n}">+</button></div>`).join("")}
      </section>
      <section class="m-env" id="mEnv" aria-live="polite"></section>
      <section class="m-rover"><span id="mRover"></span>
        <div class="m-rbtns"><button type="button" class="pill" data-task="collect_ice">Get ice</button><button type="button" class="pill" data-task="explore">Explore</button>
        <button type="button" class="pill" id="mShelter" aria-pressed="false">Shelter</button></div></section>
      <div class="m-foot"><button type="button" class="m-go" id="mEnd">End shift</button><button type="button" class="pill" id="mStop">Debrief</button></div>`;
    panel.querySelectorAll(".m-pm").forEach(b => b.onclick = () => {
      const k = b.closest(".m-load").dataset.k; run({ type: "allocate", to: k, amount: { kind: "delta", value: +b.dataset.d }, from: null });
    });
    panel.querySelectorAll("[data-task]").forEach(b => b.onclick = () => run({ type: "dispatch", vehicle: "rover", task: b.dataset.task, target: null }));
    $("mShelter").onclick = () => run({ type: "shelter", on: !state.shelter });
    $("mEnd").onclick = () => endShift();
    $("mStop").onclick = () => showDebrief();
    render();
  }
  function bar(id, name, help) {
    return `<div class="m-bar" id="mb-${id}"><div class="m-bl"><b>${name}</b><span class="m-help">${help}</span><span class="m-tr" aria-hidden="true"></span><span class="m-val"></span><small class="m-nx"></small></div>
      <div class="m-track"><i class="m-fill"></i><i class="m-next" title="Next shift (estimate)"></i></div></div>`;
  }
  function setBar(id, value, max, before, next, fmt) {
    const el = $("mb-" + id); if (!el) return;
    const w = pct(value / max * 100);
    el.querySelector(".m-fill").style.width = w + "%";
    el.querySelector(".m-next").style.left = pct(next / max * 100) + "%";
    el.querySelector(".m-val").textContent = fmt(value);
    const a = arrow(value, before); el.querySelector(".m-tr").textContent = a;
    el.querySelector(".m-nx").textContent = `next ≈ ${fmt(next).replace(/ \/.*/, "")}`;
    const bad = id === "dose" ? value / max > .7 : value < 25; el.classList.toggle("is-alert", bad);
  }
  function renderBars(r, live) {
    const s = state, nx = estimate(s), p = prev && prev.resources;
    const lim = r.dose_limit_msv || s.resources.dose_limit_msv || 50;
    setBar("power", r.power_pct, 100, p && p.power_pct, nx.power, v => Math.round(v) + "%");
    setBar("life", r.life_support_pct, 100, p && p.life_support_pct, nx.life, v => Math.round(v) + "%");
    setBar("dose", r.dose_msv, lim, p && p.dose_msv, nx.dose, v => `${(+v).toFixed(1)} / ${lim} mSv`);
    const rt = $("mRate"); if (rt) rt.textContent = `Now +${(+(live ? live.dose_rate : r.dose_rate_msv_h) || 0).toFixed(2)} mSv each hour.`;
  }
  function render() {
    if (screen !== "hud" || !state) return;
    const s = state;
    $("mClock").textContent = `Day ${s.day}/10 · Shift ${s.shift}/4`;
    $("mScore").textContent = `★ ${s.score || 0}`;
    renderBars(s.resources);
    let sum = 0;
    LOADS.forEach(([k]) => { const v = Math.round(s.loads[k] || 0); sum += v; const row = panel.querySelector(`.m-load[data-k="${k}"]`); row.querySelector("i").style.width = v + "%"; row.querySelector("b").textContent = v + "%"; });
    $("mSum").textContent = sum + "% of power used";
    const e = s.env || {};
    $("mEnv").innerHTML = `
      <span class="m-chip ${e.in_sun ? "is-on" : ""}">${e.in_sun ? "☀ Sun up" : "☾ Sun down"} <small>${(+e.sun_elev_deg || 0).toFixed(1)}°</small></span>
      <span class="m-chip ${e.earth_visible ? "is-on" : ""}" title="Radio takes ${((e.comm_delay_s || 2.6) / 2).toFixed(1)} s each way">${e.earth_visible ? "🌍 Earth up · comms open" : `🌍 Earth hidden · comms in ${e.next_comm_window_h ?? "?"} h`}</span>`;
    const rv = s.rover || {};
    $("mRover").innerHTML = `<b>Rover</b> ${rv.busy ? `${TASK[rv.task] || rv.task}, back in ${rv.eta_h} h` : "parked at the outpost"}`;
    panel.querySelectorAll("[data-task]").forEach(b => { b.disabled = !!rv.busy; });
    $("mShelter").setAttribute("aria-pressed", !!s.shelter); $("mShelter").textContent = s.shelter ? "Leave shelter" : "Shelter";
    renderBanner();
    // globe
    globe.mission.setSun(+e.sun_elev_deg || 0, s.mission_time_h || 0); globe.mission.setEarth(+e.earth_elev_deg || 0);
    const tgt = rv.busy ? TARGETS[rv.task] : null, total = rv.task === "collect_ice" ? 10 : rv.task === "explore" ? 8 : 5;
    globe.mission.setRover(tgt, tgt ? Math.sin(Math.PI * (1 - (rv.eta_h || 0) / total) / 1) * 1 : 0);
  }
  function renderBanner(transient) {
    const st = state && state.env && state.env.storm;
    clearTimeout(bannerT);
    if (transient) {
      banner.className = "m-banner is-" + transient.level; banner.hidden = false; banner.innerHTML = transient.html;
      bannerT = setTimeout(() => renderBanner(), 6000); return;
    }
    if (st && st.active) {
      banner.className = "m-banner is-storm"; banner.hidden = false;
      banner.innerHTML = `<b>☀ Solar storm</b><span>${esc(st.name)}${st.real_date ? ` · real event, ${esc(st.real_date)}` : ""}</span>${src({ title: "Source: NASA " + (st.source || "DONKI"), url: st.url || "https://kauai.ccmc.gsfc.nasa.gov/DONKI/" })}`;
    } else banner.hidden = true;
  }

  // ---------- telemetry: bars move between shifts ----------
  function onTelemetry(f) {
    live = f; if (screen !== "hud" || !state) return;
    renderBars({ power_pct: f.power, life_support_pct: f.life_support, dose_msv: f.dose_msv, dose_limit_msv: state.resources.dose_limit_msv }, f);
    if (f.sun_elev_deg != null) globe.mission.setSun(f.sun_elev_deg, f.mission_time_h || 0);
    if (f.earth_elev_deg != null) globe.mission.setEarth(f.earth_elev_deg);
  }

  // ---------- commands, events, CAPCOM ----------
  function capcom({ say: line, readback, confirm, eyebrow, viaDirector = false } = {}) {
    const s = state;
    // A confirmation the Director is holding (e.g. another officer must agree) is answered through the Director;
    // one the sim asked for directly goes to the sim.
    const answer = yes => (viaDirector && askDirector) ? askDirector(yes ? "yes" : "no") : run({ type: yes ? "confirm" : "cancel" });
    const actions = confirm ? [
      { label: "Yes", hot: true, once: true, onClick: () => answer(true) },
      { label: "No", once: true, onClick: () => answer(false) }] : [];
    card.show({ title: "CAPCOM", eyebrow: eyebrow || [s ? `Day ${s.day} · shift ${s.shift}` : "Mission", client && client.sample ? "Sample data" : ""].filter(Boolean).join(" · "),
      say: line || readback || "", actions });
  }

  async function run(command, { spoken } = {}) {
    if (!state) return;
    if (command.type === "end_shift") return endShift();
    let r;
    try { r = await client.command(state.id, command); } catch (e) { capcom({ say: "CAPCOM can't reach the mission server." }); return; }
    applyState(r.state);
    const res = r.result || {};
    pending = res.needs_confirm ? command : null;
    capcom({ say: res.say || res.readback, confirm: !!res.needs_confirm });
    handleEvents(res.events || []);
    if (spoken || res.needs_confirm || command.type === "query" || !res.ok) await say(res.say || res.readback);
    if (r.state && r.state.over) showDebrief();
  }

  async function endShift() {
    if (!state || state.over) return;
    const btn = $("mEnd"); if (btn) btn.disabled = true;
    let r;
    try { r = await client.advance(state.id, 1); } catch (e) { capcom({ say: "CAPCOM can't reach the mission server." }); if (btn) btn.disabled = false; return; }
    prev = state; applyState(r.state, true);
    const evs = r.events || [];
    capcom({ say: r.say });
    handleEvents(evs);
    const b2 = $("mEnd"); if (b2) b2.disabled = false;
    if (state.over) { showDebrief(); return; }
    say(r.say);
  }

  function applyState(s, keepPrev) { if (!s) return; if (!keepPrev && state) prev = prev || state; state = s; render(); pushContext(); }

  function handleEvents(evs) {
    if (!evs.length) return;
    const storm = evs.find(e => e.kind === "solar_storm");
    if (storm) { alertSound(); renderBanner(); return; }
    const alarm = evs.find(e => e.kind === "low_power" || e.kind === "dose_alert");
    if (alarm) { alertSound(); renderBanner({ level: "warn", html: `<b>${alarm.kind === "low_power" ? "⚡ Low power" : "☢ Dose alert"}</b><span>${esc(alarm.text)}</span>` }); return; }
    const comm = evs.find(e => e.kind === "comm_open" || e.kind === "comm_closed");
    if (comm) renderBanner({ level: "info", html: `<b>🌍 ${comm.kind === "comm_open" ? "Comm window open" : "Comm window closed"}</b><span>${esc(comm.text)}</span>` });
  }

  /** Houston: show the signal travelling (each way) and wait the real round trip before speaking. */
  async function houston(line, delayMs = 2600) {
    const oneWay = (delayMs / 2000).toFixed(1);
    signal.hidden = false; signal.style.setProperty("--trip", delayMs + "ms");
    signal.innerHTML = `<span class="m-sig-moon">Moon</span><span class="m-sig-track"><i></i></span><span class="m-sig-earth">Earth</span><small>Signal travelling to Earth… ${oneWay} s each way</small>`;
    capcom({ say: "Calling Houston…", eyebrow: "Houston · radio delay" });
    await new Promise(r => setTimeout(r, delayMs));
    signal.hidden = true;
    capcom({ say: line, eyebrow: "Houston" });
    await say(line);
  }

  // ---------- voice ----------
  /** Text the kid said in mission mode. Returns true if handled here (mock command layer). */
  async function handleText(text) {
    if (!state || screen !== "hud") return false;
    if (!client.sample) return false;          // the real Director parses commands
    const c = parseCommand(text); if (!c) return false;
    if (c.type === "call_houston") { await houston("Houston here. We copy you, Commander. Keep the crew safe and the lights on.", 2600); return true; }
    if (c.type === "end_shift") { await endShift(); return true; }
    await run(c, { spoken: true }); return true;
  }
  /** A Director answer with a mission action. Returns true if handled. */
  async function handleDirector(r) {
    if (!r || !state) return false;
    if (r.action === "command" && r.command) {
      // Assumption: if the Director already applied it, it returns state; otherwise we post it to the sim.
      if (r.state) { applyState(r.state); pending = r.needs_confirm ? r.command : null; capcom({ say: r.say, confirm: !!r.needs_confirm, viaDirector: true }); await say(r.say); }
      else await run(r.command, { spoken: true });
      return true;
    }
    if (r.action === "status") { if (r.state) applyState(r.state); capcom({ say: r.say }); await say(r.say); return true; }
    if (r.action === "houston") { await houston(r.say, +r.delay_ms || 2600); return true; }
    return false;
  }
  function context() { return state ? { id: state.id, role: roles.size === 1 ? [...roles][0] : null } : null; }
  function pushContext() {
    if (!state) return;
    const r = state.resources;
    onContext({ t: "context", mission: { id: state.id, day: state.day, shift: state.shift, power_pct: r.power_pct, life_support_pct: r.life_support_pct,
      dose_msv: r.dose_msv, storm: !!(state.env.storm && state.env.storm.active), rover_busy: !!(state.rover && state.rover.busy), awaiting_confirm: !!pending },
    names: ["CAPCOM", "Houston", state.site && state.site.name, "Shackleton", "Cabeus"].filter(Boolean),
    terms: ["shields", "life support", "greenhouse", "science", "rover", "comms", "heaters", "end shift", "shelter", "solar storm", "millisievert"] });
  }

  // ---------- debrief ----------
  async function showDebrief() {
    if (!state) return;
    screen = "debrief"; panel.hidden = true; banner.hidden = true;
    let d; try { d = await client.debrief(state.id); } catch (e) { d = { score: state.score, grade: "?", timeline: [], lessons: [], data_used: [] }; }
    const ls = (d.lessons && d.lessons.length ? d.lessons.map(l => ({ text: l.text, source: l.source })) : lessons().map(l => ({ text: l.text, source: { ...l.source, title: l.name } })));
    const outcome = d.outcome || state.outcome || (state.over ? "" : "in_progress");
    const head = outcome === "success" ? "Mission complete!" : outcome === "fail" ? "Mission over" : "Mission paused";
    debriefEl.hidden = false;
    debriefEl.innerHTML = `
      <header class="m-head"><span class="eyebrow">Debrief · ${esc(state.site.name)}</span>${sampleTag()}<button class="x" id="mDbClose" type="button" aria-label="Back to the mission">&times;</button></header>
      <div class="m-db-top">
        <div><h2 class="m-title">${head}</h2><p class="m-sub">${esc(outcome === "in_progress" ? `You stopped on day ${state.day}. You can go back and keep playing.` : d.why || "")}</p></div>
        <div class="m-grade" aria-label="Grade ${esc(d.grade)}"><b>${esc(d.grade)}</b><span>★ ${Math.round(d.score || 0)}</span></div>
      </div>
      ${chart(d.timeline || [], state.resources.dose_limit_msv || 50)}
      <div class="m-db-cols">
        <section><span class="eyebrow">Lessons</span><ul>${ls.map(l => `<li>${esc(l.text)} ${src(l.source)}</li>`).join("")}</ul></section>
        <section><span class="eyebrow">Data we used</span><ul>${(d.data_used || []).map(x => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a> ${esc(x.how || "")}</li>`).join("")}</ul></section>
      </div>
      <div class="m-foot"><button type="button" class="m-go" id="mAgain">Try a different strategy</button><button type="button" class="pill" id="mNewSite">Pick another site</button></div>`;
    $("mAgain").onclick = () => { if (unsub) unsub(); state = null; start(); };
    $("mNewSite").onclick = () => { if (unsub) unsub(); state = null; briefing(); };
    $("mDbClose").onclick = () => { if (state && !state.over) showHud(); else briefing(); };
    wireChart();
    const line = `${head} Your grade is ${d.grade}, with ${Math.round(d.score || 0)} points.`;
    capcom({ say: line, eyebrow: "Debrief" }); say(line);
  }

  /** Line chart: power %, life support %, dose as % of the limit (one 0–100 axis), with event markers. */
  function chart(tl, lim) {
    if (tl.length < 2) return `<p class="m-sub">Play a shift or two to see your timeline.</p>`;
    const W = 640, H = 170, L = 34, Rm = 8, T = 10, B = 22, t0 = tl[0].t_h, t1 = tl[tl.length - 1].t_h || 1;
    const x = t => L + (t - t0) / ((t1 - t0) || 1) * (W - L - Rm), y = v => T + (1 - pct(v) / 100) * (H - T - B);
    const series = [["power", "Power", d => d.power], ["life", "Life support", d => d.life_support], ["dose", "Dose (% of limit)", d => d.dose_msv / lim * 100]];
    const lines = series.map(([k, , f]) => `<polyline class="c-${k}" points="${tl.map(d => x(d.t_h).toFixed(1) + "," + y(f(d)).toFixed(1)).join(" ")}"/>`).join("");
    const grid = [0, 50, 100].map(v => `<line class="c-grid" x1="${L}" x2="${W - Rm}" y1="${y(v)}" y2="${y(v)}"/><text class="c-ax" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`).join("");
    const days = []; for (let h = Math.ceil(t0 / 24) * 24; h <= t1; h += 24) days.push(`<text class="c-ax" x="${x(h)}" y="${H - 6}" text-anchor="middle">Day ${h / 24 + 1}</text>`);
    const marks = tl.filter(d => (d.events || []).length).map(d => { const k = d.events.includes("solar_storm") ? "storm" : d.events.some(e => e === "low_power" || e === "dose_alert") ? "warn" : "info";
      return k === "info" ? "" : `<g class="c-ev is-${k}"><line x1="${x(d.t_h)}" x2="${x(d.t_h)}" y1="${T}" y2="${H - B}"/><text x="${x(d.t_h) + 3}" y="${T + 9}">${k === "storm" ? "☀ storm" : "⚠"}</text></g>`; }).join("");
    const last = tl[tl.length - 1];
    // direct labels at the line ends, nudged apart so they never collide
    const ly = series.map(([k, n, f]) => ({ n: n.split(" (")[0], y: Math.max(T + 10, y(f(last)) - 5) })).sort((a, b) => a.y - b.y);
    ly.forEach((l, i) => { if (i && l.y - ly[i - 1].y < 13) l.y = ly[i - 1].y + 13; });
    const labels = ly.map(l => `<text class="c-lab" x="${W - Rm - 2}" y="${l.y.toFixed(1)}" text-anchor="end">${l.n}</text>`).join("");
    window.__mChart = { tl, x, series, lim, L, W, Rm };
    return `<figure class="m-chart"><figcaption><span class="eyebrow">Your 3 resources</span>
      <span class="m-legend">${series.map(([k, n]) => `<span><i class="c-${k}"></i>${n}</span>`).join("")}<span><i class="c-storm"></i>Solar storm</span></span></figcaption>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Timeline of power, life support and radiation dose">${grid}${days.join("")}${marks}${lines}${labels}
      <line class="c-cross" id="cCross" y1="${T}" y2="${H - B}" x1="0" x2="0" visibility="hidden"/></svg><div class="c-tip" id="cTip" hidden></div></figure>`;
  }
  function wireChart() {
    const svg = debriefEl.querySelector(".m-chart svg"), tip = $("cTip"), cross = $("cCross"), c = window.__mChart; if (!svg || !c) return;
    svg.addEventListener("pointermove", e => {
      const r = svg.getBoundingClientRect(), vx = (e.clientX - r.left) / r.width * c.W;
      let best = c.tl[0]; c.tl.forEach(d => { if (Math.abs(c.x(d.t_h) - vx) < Math.abs(c.x(best.t_h) - vx)) best = d; });
      cross.setAttribute("x1", c.x(best.t_h)); cross.setAttribute("x2", c.x(best.t_h)); cross.setAttribute("visibility", "visible");
      tip.hidden = false; tip.style.left = (c.x(best.t_h) / c.W * 100) + "%";
      tip.innerHTML = `<b>Day ${Math.floor(best.t_h / 24) + 1}, hour ${best.t_h % 24}</b>` + c.series.map(([k, n, f]) => `<span><i class="c-${k}"></i>${n.split(" (")[0]} ${k === "dose" ? (+best.dose_msv).toFixed(1) + " mSv" : Math.round(f(best)) + "%"}</span>`).join("")
        + ((best.events || []).length ? `<span>${esc(best.events.join(", ").replace(/_/g, " "))}</span>` : "");
    });
    svg.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });
  }

  return {
    enter, exit, handleText, handleDirector, context,
    get active() { return screen !== "off"; },
    get running() { return !!state && screen === "hud"; },
    get sample() { return !!(client && client.sample); },
  };
}
