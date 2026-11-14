// Mission Trainer UI: briefing (pick a site), HUD (3 resources, loads, environment, rover, End shift), events,
// CAPCOM card, Houston delay, debrief. Talks to the backend through client.js, or the local mock (labelled "Sample data").
import { createMissionClient } from "./client.js";
import { sayStyle } from "../floor.js";
import { parseCommand } from "./mock.js";
import { createCabin } from "./cabin.js";
import { createTerrainView } from "./terrain.js";
import { callSign, CAPCOM, callbackLine, CALLBACKS, LESSON_STORY, DEBRIEF, FRAMING } from "../story.js";

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
export function createMissionUI({ globe, card, placeById, say, alertSound, onContext = () => {}, askDirector = null, session = null, academy = null }) {
  // `academy` (optional): {badges() → [{id,name,patch,lesson}], has(lessonId) → bool}: Flight School patches carry over.
  // [session hook] `session` (optional): {onStart(state), endShift(state) → true when the session Director handles it}.
  const $ = id => document.getElementById(id);
  const cabinEl = $("mCabin"), panel = $("mPanel"), banner = $("mBanner"), signal = $("mSignal"), debriefEl = $("mDebrief");
  let client = null, sites = [], site = null, state = null, prev = null, roles = new Set(), unsub = null, live = null;
  let screen = "off", pending = null, bannerT = null, siteSeed = null, cockpit = null, logHistory = [];
  // The window's surface views (SITE / ROVER / EARTH) on real LOLA terrain. One WebGL view for the whole session: its
  // host moves into each new cabin. ORBIT is the globe itself.
  let tv = null, tvHost = null, curView = null, surfT = null;
  const reducedMotion = () => document.documentElement.dataset.motion === "reduce" || !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  function surface() {
    if (!tvHost) {
      tvHost = document.createElement("div"); tvHost.className = "tv"; tv = createTerrainView(tvHost, { reduced: reducedMotion });
      window.__cabinViews = { get tv() { return tv; }, get view() { return curView; } };   // test hook (fps, view)
    }
    if (import.meta.env && import.meta.env.DEV && !window.__cabinTest) window.__cabinTest = {   // dev-only: force sim states for screenshots
      storm(on) { if (!state) return; state.env.storm = on ? { active: true, name: "G5 geomagnetic storm", real_date: "10 May 2024", source: "DONKI", severity: 5 } : { active: false };
        state.alerts = on ? ["dose_rate_high"] : []; render(); },
      sky(sun, earth) { if (!state) return; Object.assign(state.env, { sun_elev_deg: sun, in_sun: sun > 0, earth_elev_deg: earth, earth_visible: earth > 0 }); testSky = true; render(); },
      rover(task, eta) { if (!state) return; state.rover = { ...(state.rover || {}), busy: !!task, task, eta_h: eta }; render(); },
    };
    return tv;
  }
  const badges = () => (academy ? academy.badges() : []);
  const learned = lessonId => !!(academy && academy.has(lessonId));

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
  // In the cabin the ask dock and the caption line live in the panel's bottom comm row (never over the window or a
  // display unit); outside it they go back where index.html put them. Same nodes, so #q / #mic / Ask keep working.
  const docked = [];
  function dockIn() {
    [["askbar", "cbAskSlot"], ["captionBar", "cbCapSlot"]].forEach(([id, slot]) => {
      const el = $(id), to = $(slot); if (!el || !to) return;
      if (!docked.some(d => d.el === el)) docked.push({ el, parent: el.parentNode, next: el.nextSibling });
      to.append(el);
    });
  }
  function dockOut() { while (docked.length) { const d = docked.pop(); d.parent.insertBefore(d.el, d.next && d.next.parentNode === d.parent ? d.next : null); } }
  const hideCabin = () => {
    dockOut();
    cabinEl.hidden = true; delete document.body.dataset.cabin; delete document.body.dataset.cabinView; globe.setViewport(null); globe.pause(false);
    clearTimeout(surfT); if (tv) tv.hide(); curView = null;
  };
  /** The window: ORBIT is the NASA globe (LROC colour); SITE / ROVER / EARTH are the LOLA terrain views. Going down
   *  from orbit, the globe dives toward the site first, then the surface view takes over the glass mid-descent. */
  function windowView(v) {
    if (!state) return;
    const s = state.site, from = curView; curView = v; document.body.dataset.cabinView = v;
    const t = surface(); clearTimeout(surfT);
    if (v === "orbit" || !t) { if (t) t.hide(); globe.pause(false); globe.flyTo(-35, s.lon, 3.8); return; }
    const glass = cabinEl.querySelector(".cb-glass"); if (glass && tvHost.parentNode !== glass) glass.prepend(tvHost);
    t.setSite(state.site); syncSurface();
    if (from === "orbit" || from == null) {
      globe.pause(false); globe.flyTo(s.lat, s.lon, 1.35);
      surfT = setTimeout(() => {
        t.setView(v, { from: "orbit" });
        surfT = setTimeout(() => { if (curView !== "orbit") globe.pause(true); }, reducedMotion() ? 0 : 900);
      }, reducedMotion() ? 0 : 900);
    } else { t.setView(v); globe.pause(true); }
  }
  /** Sun, Earth, rover and storm into the surface view, from the same sim numbers as the readouts. */
  let testSky = false;
  function syncSurface(f) {
    if (!tv || !state) return;
    if (testSky) f = null;
    const e = state.env || {};
    tv.setSun(f && f.sun_elev_deg != null ? f.sun_elev_deg : +e.sun_elev_deg || 0, (f && f.mission_time_h) || state.mission_time_h || 0);
    tv.setEarth(f && f.earth_elev_deg != null ? f.earth_elev_deg : +e.earth_elev_deg || 0);
    tv.setRover(state.rover || {}, f && f.mission_time_h != null ? Math.max(0, f.mission_time_h - (state.mission_time_h || 0)) : 0);
    tv.setStorm(!!(e.storm && e.storm.active));
  }
  /** Spoken or typed view changes ("zoom out", "show me the rover", "back to the outpost"). */
  const VIEW_WORDS = [[/\b(zoom out|orbit|whole moon|full moon|go up)\b/, "orbit"], [/\b(rover view|show (me )?the rover|follow the rover|where is the rover|rover cam(era)?)\b/, "rover"],
    [/\b(earth view|show (me )?(the )?earth|where is (the )?earth|look at (the )?earth)\b/, "earth"],
    [/\b(zoom in|outpost view|site view|(back|go) to the (outpost|base|site)|show (me )?the (outpost|base|site))\b/, "site"]];
  function exit() { screen = "off"; hideCabin(); globe.mission.exit(); panel.hidden = true; banner.hidden = true; debriefEl.hidden = true; signal.hidden = true; }

  function briefing() {
    screen = "brief"; debriefEl.hidden = true; banner.hidden = true; panel.hidden = false; hideCabin();
    if (!site) site = sites[0];
    panel.innerHTML = `
      <header class="m-head"><span class="eyebrow">Outpost Luna · Briefing</span>${sampleTag()}</header>
      <h2 class="m-title">Where will you build Outpost Luna, ${esc(callSign.shown())}?</h2>
      <p class="m-sub">${esc(FRAMING.split(". ").slice(1).join(". "))} Sun charges batteries. Ice makes water. You can call home only when Earth is up.</p>
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
      <button type="button" class="m-go" id="mStart">Take command</button>`;
    panel.querySelectorAll(".m-site").forEach(b => b.onclick = () => { site = sites.find(s => s.id === b.dataset.site); previewSite(); briefing(); });
    panel.querySelectorAll(".m-role").forEach(b => b.onclick = () => { const r = b.dataset.role; roles.has(r) ? roles.delete(r) : roles.add(r); b.setAttribute("aria-pressed", roles.has(r)); });
    $("mStart").onclick = () => start();
    previewSite();
    briefCard();
  }
  /** CAPCOM's welcome + lessons from hardware already on the Moon (real artifacts from /api/places). */
  function briefCard() {
    card.show({ title: "CAPCOM", eyebrow: "Briefing" + (client.sample ? " · Sample data" : ""),
      say: CAPCOM.missionBrief(callSign.shown()),
      lessons: lessons().map(l => ({ text: l.text, source: { ...l.source, title: l.name } })) });
  }
  function previewSite() {
    if (!site) return;
    globe.mission.setSite({ ...site, short: site.name.split(" (")[0] }, { dist: 2.5 });
    globe.mission.setSun(1, 0); globe.mission.setEarth(site.earth_visible_pct > 60 ? 3 : -1); globe.mission.setRover(null);
  }

  async function start(seed) {
    siteSeed = seed ?? Math.floor(Math.random() * 1e9);
    state = await client.start({ site: site.id, seed: siteSeed, roles: [...roles] }); prev = null; logHistory = []; reminded.clear(); seen.clear();
    if (unsub) unsub();
    unsub = client.subscribe(state.id, onTelemetry);
    pushContext();
    showHud();
    if (session && !client.sample && session.onStart) session.onStart(state);   // [session hook]
    capcom({ say: CAPCOM.missionStart(callSign.shown(), site.name) }); say(CAPCOM.missionStart(callSign.spoken(), site.name));
  }

  // ---------- cockpit (mission/cockpit.js): the console that replaced the HUD panel ----------
  function showHud() {
    screen = "hud"; debriefEl.hidden = true; panel.hidden = true; cabinEl.hidden = false; document.body.dataset.cabin = "1";
    dockOut();   // createCabin rewrites the cabin's HTML: lift the docked nodes out first
    cockpit = createCabin(cabinEl, {
      badges,
      onCommand: c => run(c),
      onHouston: () => callHouston(),
      onView: v => windowView(v),
      onEndShift: () => endShift(),
      onDebrief: () => showDebrief(),
    });
    dockIn();
    if (client && client.sample) cabinEl.insertAdjacentHTML("afterbegin", sampleTag());
    requestAnimationFrame(() => { const w = cabinEl.querySelector(".cb-glass"), r = w && w.getBoundingClientRect(), sr = cabinEl.getBoundingClientRect();
      if (r && sr.height) globe.setViewport((r.bottom - sr.top) / sr.height); windowView(cockpit.view || "site"); });
    logHistory.forEach(l => cockpit.log(l.who, l.text));
    render();
  }
  function render() {
    if (screen !== "hud" || !state || !cockpit) return;
    const s = state, e = s.env || {}, rv = s.rover || {};
    cockpit.update(s);
    (s.alerts || []).forEach(a => { if (CALLBACKS[a]) { seen.add(a); remind(a); } });
    renderBanner();
    globe.mission.setSun(+e.sun_elev_deg || 0, s.mission_time_h || 0); globe.mission.setEarth(+e.earth_elev_deg || 0);
    const tgt = rv.busy ? TARGETS[rv.task] : null, total = rv.task === "collect_ice" ? 10 : rv.task === "explore" ? 8 : 5;
    globe.mission.setRover(tgt, tgt ? Math.sin(Math.PI * (1 - (rv.eta_h || 0) / total)) : 0);
    syncSurface();
  }
  /** Radio log lines survive re-renders of the cockpit. */
  function radio(who, text) { if (!text) return; logHistory.push({ who, text }); logHistory = logHistory.slice(-12); if (cockpit && screen === "hud") cockpit.log(who, text); }
  /** The Call Houston push button: the real Director in a live mission, the local practice line otherwise. */
  async function callHouston() {
    if (!state) return;
    radio("kid", "Houston, Outpost Luna. Radio check.");
    if (client.sample || !askDirector) { await houston("Houston here. We copy you, Commander. Keep the crew safe and the lights on.", 2600); return; }
    if (cockpit) cockpit.calling(true);
    await askDirector("Call Houston");
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
      if (!state.shelter) {
        banner.insertAdjacentHTML("beforeend", `<span class="m-bact"><button type="button" class="m-bbtn is-hot" data-act="shelter">🏠 Everyone to shelter</button><button type="button" class="m-bbtn" data-act="shields">🛡️ Shields to 40</button></span>`);
        banner.querySelector('[data-act="shelter"]').onclick = () => run({ type: "shelter", on: true });
        banner.querySelector('[data-act="shields"]').onclick = () => run({ type: "allocate", to: "shields", amount: { kind: "percent", value: 40 }, from: null });
      }
    } else banner.hidden = true;
  }

  // ---------- telemetry: bars move between shifts ----------
  function onTelemetry(f) {
    live = f; if (screen !== "hud" || !state) return;
    if (cockpit && !testSky) cockpit.telemetry(f);
    if (f.sun_elev_deg != null) globe.mission.setSun(f.sun_elev_deg, f.mission_time_h || 0);
    if (f.earth_elev_deg != null) globe.mission.setEarth(f.earth_elev_deg);
    syncSurface(f);
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
    if (screen === "hud" && !/^Houston/.test(eyebrow || "")) radio("capcom", line || readback);
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
    if (session && !client.sample && session.endShift && session.endShift(state)) return;   // [session hook]
    if (cockpit) cockpit.busy(true);
    let r;
    try { r = await client.advance(state.id, 1); } catch (e) { capcom({ say: "CAPCOM can't reach the mission server." }); if (cockpit) cockpit.busy(false); return; }
    prev = state; applyState(r.state, true);
    const evs = r.events || [];
    capcom({ say: r.say });
    handleEvents(evs);
    if (cockpit) cockpit.busy(false);
    if (state.over) { showDebrief(); return; }
    say(r.say);
  }

  function applyState(s, keepPrev) { if (!s) return; if (!keepPrev && state) prev = prev || state; state = s; render(); pushContext(); }

  /** A Flight School lesson coming back as a real event: CAPCOM reminds the kid (once per kind per mission). */
  const reminded = new Set();
  function remind(kind) {
    if (reminded.has(kind) || !CALLBACKS[kind]) return null;
    reminded.add(kind); seen.add(kind);
    const line = callbackLine(kind, learned(CALLBACKS[kind].lesson)); radio("capcom", line); return line;
  }
  const seen = new Set();   // lesson concepts that happened this mission (for the debrief)
  function handleEvents(evs) {
    if (!evs.length) return;
    evs.forEach(e => { if (CALLBACKS[e.kind]) seen.add(e.kind); });
    const cbk = evs.map(e => e.kind).find(k => CALLBACKS[k] && !reminded.has(k));
    if (cbk) { const line = remind(cbk); if (line) setTimeout(() => { if (screen === "hud") say(line, { situation: "coach" }); }, 2500); }
    const storm = evs.find(e => e.kind === "solar_storm");
    if (storm) { alertSound(); renderBanner(); return; }
    const alarm = evs.find(e => e.kind === "low_power" || e.kind === "dose_alert");
    if (alarm) { alertSound(); renderBanner({ level: "warn", html: `<b>${alarm.kind === "low_power" ? "⚡ Low power" : "☢ Dose alert"}</b><span>${esc(alarm.text)}</span>` }); return; }
    const comm = evs.find(e => e.kind === "comm_open" || e.kind === "comm_closed");
    if (comm) renderBanner({ level: "info", html: `<b>🌍 ${comm.kind === "comm_open" ? "Comm window open" : "Comm window closed"}</b><span>${esc(comm.text)}</span>` });
  }

  /** Houston: show the signal travelling (each way) and wait the real round trip before speaking. */
  async function houston(line, delayMs = 2600, style = null) {
    const oneWay = (delayMs / 2000).toFixed(1);
    signal.hidden = false; signal.style.setProperty("--trip", delayMs + "ms");
    signal.innerHTML = `<span class="m-sig-moon">Moon</span><span class="m-sig-track"><i></i></span><span class="m-sig-earth">Earth</span><small>Signal travelling to Earth… ${oneWay} s each way</small>`;
    capcom({ say: CAPCOM.houstonCalling, eyebrow: "Houston · radio delay" });
    if (cockpit) cockpit.calling(true);
    await new Promise(r => setTimeout(r, delayMs));
    signal.hidden = true; if (cockpit) cockpit.calling(false);
    capcom({ say: line, eyebrow: "Houston" }); radio("houston", line);
    await say(line, style || { voice: "houston" });   // Houston speaks in its own (Steer) voice
  }

  // ---------- voice ----------
  /** Text the kid said in mission mode. Returns true if handled here (mock command layer). */
  async function handleText(text) {
    if (!state || screen !== "hud") return false;
    radio("kid", text);
    const tl = text.toLowerCase(), vw = VIEW_WORDS.find(([re]) => re.test(tl));
    if (vw && cockpit) { cockpit.setView(vw[1]); return true; }
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
      if (r.state) { applyState(r.state); pending = r.needs_confirm ? r.command : null; capcom({ say: r.say, confirm: !!r.needs_confirm, viaDirector: true }); await say(r.say, sayStyle(r)); }
      else await run(r.command, { spoken: true });
      return true;
    }
    if (r.action === "status") { if (r.state) applyState(r.state); capcom({ say: r.say }); await say(r.say, sayStyle(r)); return true; }
    if (r.action === "houston") { await houston(r.say, +r.delay_ms || 2600, sayStyle(r)); return true; }
    return false;
  }
  // ---------- [session hook] decisions from the session Director (frontend/src/session.js) ----------
  function applyRemote(s) {
    if (!s) return;
    const st0 = state;
    if (st0 && s.env && s.env.storm && s.env.storm.active && !(st0.env.storm && st0.env.storm.active)) handleEvents([{ kind: "solar_storm" }]);
    (s.alerts || []).forEach(a => { if (a === "low_power" || a === "life_support_low") seen.add(a); });
    if (state && s.mission_time_h !== state.mission_time_h) { prev = state; applyState(s, true); } else applyState(s);
    if (s.over) showDebrief();
  }
  function alert(d) {
    const icon = d.level === "critical" ? "☢" : d.level === "warn" ? "⚠" : "🌍";
    if (d.level !== "info") alertSound();
    renderBanner({ level: d.level === "critical" ? "storm" : d.level, html: `<b>${icon} ${d.level === "critical" ? "Alert" : d.level === "warn" ? "Warning" : "Update"}</b><span>${esc(d.text)}</span>` });
  }
  /** A CAPCOM card from a decision: body, chips, and actions whose clicks go back through `send`. */
  function showCard(d, send) {
    const s = state;
    card.show({ title: d.title || "CAPCOM", asked: d.asked || "", say: d.body || "", arc: d.arc || "",
      eyebrow: [d.hint ? "Heads up" : d.nudge ? "Coach" : "", s ? `Day ${s.day} · shift ${s.shift}` : "Mission"].filter(Boolean).join(" · "),
      actions: (d.actions || []).map(a => ({ label: a.label, hot: true, once: true, onClick: () => send(a.send) })) });
  }
  function askConfirm(d, send) {
    pending = { type: "confirm" };
    card.show({ title: "CAPCOM", say: d.text || "Are you sure?", eyebrow: "Confirm",
      actions: [{ label: "Yes", hot: true, once: true, onClick: () => send(d.yes) }, { label: "No", once: true, onClick: () => send(d.no) }] });
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
    screen = "debrief"; panel.hidden = true; banner.hidden = true; hideCabin();
    let d; try { d = await client.debrief(state.id); } catch (e) { d = { score: state.score, grade: "?", timeline: [], lessons: [], data_used: [] }; }
    const ls = (d.lessons && d.lessons.length ? d.lessons.map(l => ({ text: l.text, source: l.source })) : lessons().map(l => ({ text: l.text, source: { ...l.source, title: l.name } })));
    const outcome = d.outcome || state.outcome || (state.over ? "" : "in_progress");
    const head = outcome === "survived" || outcome === "success" ? "Mission complete!" : outcome === "in_progress" || !outcome ? "Mission paused" : "Mission over";
    (d.timeline || []).forEach(t => (t.events || []).forEach(k => { if (CALLBACKS[k]) seen.add(k); }));
    const lessonsSeen = [...new Set([...seen].map(k => CALLBACKS[k].lesson))];
    const learnedHtml = `<section class="m-learned"><span class="eyebrow">${esc(DEBRIEF.learned)}</span>${lessonsSeen.length
      ? `<ul>${lessonsSeen.map(id => { const k = [...seen].find(x => CALLBACKS[x].lesson === id), c = CALLBACKS[k];
          return `<li><span class="m-lpatch${learned(id) ? " is-earned" : ""}" aria-hidden="true">${(LESSON_STORY[id] || {}).patch || "★"}</span><span><b>Lesson ${c.n}</b> ${esc(c.text)}</span></li>`; }).join("")}</ul>`
      : `<p class="m-sub">${esc(DEBRIEF.learnedEmpty)}</p>`}</section>`;
    debriefEl.hidden = false;
    debriefEl.innerHTML = `
      <header class="m-head"><span class="eyebrow">Debrief · ${esc(state.site.name)}</span>${sampleTag()}<button class="x" id="mDbClose" type="button" aria-label="Back to the mission">&times;</button></header>
      <div class="m-db-top">
        <div><h2 class="m-title">${head}</h2><p class="m-sub">${esc(outcome === "in_progress" ? `You stopped on day ${state.day}. You can go back and keep playing.` : d.why || "")}</p></div>
        <div class="m-grade" aria-label="Grade ${esc(d.grade)}"><b>${esc(d.grade)}</b><span>★ ${Math.round(d.score || 0)}</span></div>
      </div>
      ${chart(d.timeline || [], state.resources.dose_limit_msv || 50)}
      ${learnedHtml}
      <p class="m-mars">${esc(DEBRIEF.mars)}</p>
      <div class="m-db-cols">
        <section><span class="eyebrow">Lessons</span><ul>${ls.map(l => `<li>${esc(l.text)} ${src(l.source)}</li>`).join("")}</ul></section>
        <section><span class="eyebrow">Data we used</span><ul>${(d.data_used || []).map(x => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a> ${esc(x.how || "")}</li>`).join("")}</ul></section>
      </div>
      <div class="m-foot"><button type="button" class="m-go" id="mAgain">${esc(DEBRIEF.replay)}</button><button type="button" class="pill" id="mNewSite">${esc(DEBRIEF.another)}</button></div>`;
    $("mAgain").onclick = () => { if (unsub) unsub(); state = null; start(); };
    $("mNewSite").onclick = () => { if (unsub) unsub(); state = null; briefing(); };
    $("mDbClose").onclick = () => { if (state && !state.over) showHud(); else briefing(); };
    wireChart();
    const line = cs => `${head} Nice flying, ${cs}. Your grade is ${d.grade}, with ${Math.round(d.score || 0)} points.`;
    capcom({ say: line(callSign.shown()), eyebrow: "Debrief" }); say(line(callSign.spoken()));
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
    applyRemote, alert, showCard, askConfirm, houston,   // [session hook]
    get active() { return screen !== "off"; },
    get running() { return !!state && screen === "hud"; },
    get sample() { return !!(client && client.sample); },
  };
}
