// Mission Trainer UI: briefing (pick a site), HUD (3 resources, loads, environment, rover, End shift), events,
// CAPCOM card, Houston delay, debrief. Talks to the backend through client.js, or the local mock (labelled "Sample data").
import { pretendLabel } from "../pretend.js";   // the "pretend tech" mark
import { createMissionClient } from "./client.js";
import { registerFlow, flowLog, pauseCaption } from "../flows.js";   // [flows] pause / resume
import { sayStyle, stopSpeaking } from "../floor.js";
import { parseCommand } from "./mock.js";
import { createCabin } from "./cabin.js";
import { systemWord } from "./systems.js";   // the Systems drawer's voice words (docs/GAMEPLAY.md §17)
import { createTerrainView } from "./terrain.js";
import "./mission.css";
import { icon } from "../assets/icons.js";
const ic = (n, size = 14) => icon(n, { size });
import { callSign, CAPCOM, callbackLine, callbackTakeaway, CALLBACKS, DEBRIEF, OFFER, PICKER, HELP, PRETEND_TECH, PRETEND_TECH_TIP, GATE, NOW, HUB, BRIEFING, CAMPAIGN, rideReady } from "../story.js";
import * as CM from "./campaign.js";   // [campaign] Missions 2+ on the hub (docs/GAMEPLAY.md §16)
import { nowCard, nowSpoken, nudgeLine, debriefStory, houstonRelay } from "./objective.js";
import { createTour } from "./tour.js";
import { createCoach, coachDone } from "./coach.js";
import { createMissionClock } from "./clock.js";
import { radioBeep } from "../sound.js";
import { buzz, momentOf } from "../haptics.js";
import { createNavigator } from "./navigator.js";   // the landing-site navigator (docs/SITE_NAVIGATOR.md)
import { pinLayout } from "./pin_layout.js";   // [QA-61] the picker pins redraw only when the picture changes



/** Story beats CAPCOM says from the client when no session Director is connected (the session says them otherwise). */
const SPOKEN_BEATS = new Set(["settle", "comm_gap", "first_dark", "ice_return", "final_downlink"]);
/** Events that end a time warp (like a console game: something happened, back to 1x). */
const WARP_STOPS = new Set(["solar_storm", "storm_warning", "storm_end", "sunset", "sunset_soon", "sunrise", "comm_open", "comm_closed",
  "low_power", "rover_back", "failure", "shelter_limit", "beat", "task"]);
/** A story beat's window moment: the view that shows it best, for a few seconds (only from the seat's site view). */
const MOMENT_VIEW = { earthrise: "earth", rover_lights: "rover", earthset: "earth" };

const LOADS = [["shields", "Shields"], ["life_support", "Life support"], ["greenhouse", "Greenhouse"], ["science", "Science"],
  ["rover", "Rover"], ["comms", "Comms"], ["heaters", "Heaters"]];
const LOAD_HELP = { shields: "Blocks radiation", life_support: "Makes air and water", greenhouse: "Plants make oxygen", science: "Earns points",
  rover: "Drives the rover", comms: "Talks to Earth", heaters: "Keeps things warm at night" };
const TASK = { collect_ice: "collecting ice", explore: "exploring", repair_array: "fixing a solar panel", return: "driving home" };
// Ice and explore targets near the south pole (real places: Shackleton crater, Cabeus where LCROSS found water).
const TARGETS = { collect_ice: { lat: -89.67, lon: 129.78, name: "Shackleton" }, explore: { lat: -84.68, lon: -48.7, name: "Cabeus" }, repair_array: null, return: null };
// Lessons from hardware already on the Moon: the artifact id, and what it teaches an outpost commander.
const LESSONS = [
  ["surveyor3", "Machines can last. Apollo 12 took Surveyor 3's camera home after 2½ years, to see what space does to hardware."],
  ["lcross_centaur_impact", "Ice hides in the dark. LCROSS hit Cabeus crater near the south pole and found water in the dust cloud."],
  ["apollo15_lrv", "Don't drive too far. Apollo 15's rover went 27.8 km but stayed within 5 km of the lander, so the crew could walk back."],
];

/** [0.4] The Mission picker's camera: top-down on the south pole (lon 0 = the Earth side at the top of the screen). */
export const PICK_VIEW = { lat: -89, lon: 0, dist: 1.3, band: .62 };
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
export function createMissionUI({ globe, card, placeById, say: say0, alertSound, onContext = () => {}, askDirector = null, session = null, academy = null }) {
  // [rc] Screen generation (QA-19/20): exit() bumps it. Every async continuation (a loading picker, an order reply,
  // Houston's delayed answer, the end of a shift) captures it first and stops if the kid left Mission meanwhile, so
  // nothing from Mission (picker, CAPCOM card, Houston's voice) ever shows or speaks over another mode.
  let gen = 0;
  const alive = g => g === gen && screen !== "off";
  const say = (...a) => (screen === "off" ? Promise.resolve(false) : say0(...a));   // Mission never speaks while away
  // `academy` (optional): {badges() → [{id,name,patch,lesson}], has(lessonId) → bool}: Flight School patches carry over.
  // [session hook] `session` (optional): {onStart(state), endShift(state) → true when the session Director handles it}.
  const $ = id => document.getElementById(id);
  const cabinEl = $("mCabin"), panel = $("mPanel"), banner = $("mBanner"), signal = $("mSignal"), debriefEl = $("mDebrief");
  let client = null, sites = [], site = null, state = null, prev = null, roles = new Set(), unsub = null, live = null;
  let campaignList = CM.FALLBACK, cm = null;   // [campaign] the missions, and the one on the hub
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
    if (((import.meta.env && import.meta.env.DEV) || window.__outpostTest) && !window.__cabinTest) window.__cabinTest = {   // dev (or a test run that sets window.__outpostTest): force sim states
      // a forced storm holds across state updates (the live clock steps the sim every second; a plain write was lost)
      storm(on) { if (!state) return; testForce = on ? { storm: { active: true, name: "Real solar particle storm, 2024-05-09 (huge auroras on Earth)", real_date: "2024-05-09", source: "DONKI", severity: 3, sep: true } } : null;
        state.env.storm = on ? testForce.storm : { active: false }; state.alerts = on ? ["dose_rate_high"] : []; render(); },
      sky(sun, earth) { if (!state) return; Object.assign(state.env, { sun_elev_deg: sun, in_sun: sun > 0, earth_elev_deg: earth, earth_visible: earth > 0 }); testSky = true; render(); },
      rover(task, eta) { if (!state) return; state.rover = { ...(state.rover || {}), busy: !!task, task, eta_h: eta }; render(); },
      shelter(on) { if (!state) return; state.shelter = !!on; render(); },
      power(pct) { if (!state) return; state.resources.power_pct = pct; state.alerts = pct < 25 ? ["low_power"] : []; render(); if (pct < 25) renderBanner({ level: "caution", title: "Low power", text: `Battery at ${pct}%. Turn down what you don't need.` }); },
      warning(lead, conf) { if (!state) return; state.env.storm = { active: false }; state.env.storm_warning = lead == null ? null : { lead_h: lead, confidence: conf, real_date: "10 May 2024", source: "DONKI" }; render(); },
      comm(open) { if (!state) return; renderBanner({ level: "info", title: open ? "Earth in view" : "Earth set", text: open ? "You can call Houston." : "No radio until Earth rises." }); },
      confirm(text) { capcom({ say: text || "Send the rover out during a solar storm? Say yes or no.", confirm: true }); },
      busy(on) { if (cockpit) cockpit.busy(!!on); },
      cadet(on) { try { localStorage.setItem("outpost-tier", on ? "cadet" : "commander"); } catch (e) { /* blocked */ } },
      offer() { showCard({ title: "CAPCOM", body: "A solar storm is coming. Shelter now, or wait a shift?", actions: [{ label: "Shelter now", send: "shelter" }, { label: "Wait a shift", send: "end shift" }] }, () => {}); },
      quality(q) { if (cockpit) cockpit.setQuality(q); },
      ride(target = "heaters") { if (!state) return; const host = document.createElement("section"); host.className = "m-cabin"; host.style.zIndex = 9;
        document.getElementById("stage").append(host); const r = createCabin(host, { mode: "ride", onCommand: c => console.log("ride order", JSON.stringify(c)) });
        r.update(state); setTimeout(() => r.cue(target), 300); window.__ride = r; },
      panel(id) { if (!cockpit) return; if (id) cockpit.openPanel(id); else cockpit.seat(); },
      calling() { if (cockpit) cockpit.calling(true, 2600); },
      // [wave 5] the feedback moments for screenshots (tools/systems_shots.py): a chapter card, the objective-done pulse
      chapter(stars = { safe: true, powered: true, science: true }) { const count = Object.values(stars).filter(Boolean).length;
        showChapter({ n: 2, of: 5, title: "The long night", days: [3, 4], stars, count, capcom: count === 3 ? "Perfect shift, crew." : "Good shift. Keep the science moving.", last: false }); },
      pulse() { return cockpit && cockpit.pulse ? cockpit.pulse().length : 0; },
      // a story moment on the glass (tools/mission_ui.py checks it never sits on the rover pill, the tabs or the Now panel)
      moment(title = "On our own") { if (cockpit && cockpit.moment) cockpit.moment({ title, visual: "earthset", objective: "No radio for now. Keep the crew safe.", t_h: (state && state.mission_time_h) || 0 }); },
      debrief(outcome, extra = {}) { if (!state) return; fakeDebrief = fakeDb(outcome, extra); if (outcome !== "in_progress") { state.over = true; state.outcome = outcome; } showDebrief(); },
    };
    return tv;
  }
  let fakeDebrief = null, windows = null, testForce = null;   // testForce: dev-only (window.__cabinTest.storm)   // dev-only: a debrief payload for screenshots of every outcome
  function fakeDb(outcome, extra) {
    const tl = []; for (let i = 1; i <= 40; i++) { const st = i >= 14 && i <= 16;
      tl.push({ t_h: i * 6, power: Math.max(5, 100 - (outcome === "failed" ? i * 2.4 : i * .4) - (st ? 8 : 0)), life_support: Math.max(4, 80 - (outcome === "failed" ? i * 1.9 : i * .3)),
        dose_msv: i * (outcome === "failed" ? 1.1 : .5) + (st ? 6 : 0), events: st ? ["solar_storm"] : [] }); }
    return { outcome, grade: outcome === "survived" ? "A" : "D", score: outcome === "survived" ? 412 : 96, why: outcome === "survived" ? "The crew made it through all 10 days." : "Life support ran out on day 7.",
      timeline: outcome === "survived" ? tl : tl.slice(0, 28), lessons: [{ text: "On 2017-09-07 the Sun really produced a G4 storm.", source: { title: "DONKI 2017-09-07", url: "https://kauai.ccmc.gsfc.nasa.gov/DONKI/" } },
        { text: "Chang'e 4 measured 1369 microsieverts per day on the Moon's surface: about 2.6 times the dose inside the Space Station.", source: { title: "Zhang et al. 2020", url: "https://doi.org/10.1126/sciadv.aaz1334" } }],
      data_used: [{ name: "JPL Horizons", url: "https://ssd.jpl.nasa.gov/horizons/" }], ...extra };
  }
  const badges = () => (academy ? academy.badges() : []);
  /** Qualified (the check ride passed) -> Commander; before that the kid is a Cadet, and Mission offers a practice shift. */
  const qualified = () => !academy || !academy.qualified || !!academy.qualified();
  const rank = () => (qualified() ? "Commander" : "Cadet");
  let practice = false;   // this mission is the unqualified cadet's practice shift (one shift, Shackleton Rim, Cadet band)
  const PRACTICE_H = 6;
  const learned = lessonId => !!(academy && academy.has(lessonId));

  const shortName = n => n.split(" (")[0].replace(/ rocket impact site| impact site/, "");
  const lessons = () => LESSONS.map(([id, text]) => { const a = placeById(id); return a ? { text, name: shortName(a.name), source: (a.sources || [])[0] } : null; }).filter(Boolean);
  const sampleTag = () => client && client.sample ? `<span class="m-sample" title="The mission server isn't running yet; this is a local practice model.">Sample data</span>` : "";
  /** Visual + screen-reader alert through the a11y module (screen-edge flash, vibration, assertive live region). */
  const a11yAlert = text => { try { const a = window.__outpost && window.__outpost.a11y; if (a && a.visualAlert) a.visualAlert(text); } catch (e) { /* a11y not loaded */ } };
  const srcLink = (s, label) => s && s.url ? `<a class="mx-src" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(label || s.title || new URL(s.url).hostname)}</a>` : "";
  /** A takeaway: one sentence, at most 20 words (cut at a clause if longer; the source link carries the detail). */
  const takeaway = t => { let x = firstSentence(t).replace(/\s*\([^)]*\)/g, ""); const w = x.split(/\s+/); if (w.length <= 20) return x;
    const cut = x.slice(0, x.split(/\s+/).slice(0, 20).join(" ").length), m = cut.match(/^(.{30,}?)[:;,](?=\s)(?!.*[:;,]\s)/) || cut.match(/^(.{30,})[:;,—](?=\s)/);
    return (m ? m[1] : w.slice(0, 18).join(" ")).replace(/[,;:]$/, "") + (m ? "." : "…"); };
  const firstSentence = t => { const m = String(t || "").match(/^.*?[.!?](?=\s|$)/); return (m ? m[0] : String(t || "")).trim(); };

  // ---------- briefing ----------
  let entered = false;
  async function enter() {
    const g = ++gen; entered = true;
    globe.mission.enter();
    if (!client) {
      panel.hidden = false; panel.innerHTML = `<p class="m-wait">Loading mission sites…</p>`;
      const c = await createMissionClient();
      client = client || c; sites = client.sites || [];
      if (client.campaign) { try { const r = await client.campaign(); if (r && Array.isArray(r.missions) && r.missions.length) campaignList = r.missions; } catch (e) { /* Mission 1 only */ } }
      if (!client.sample) await nv.load();   // real NASA numbers per site + map layers (falls back to the plain picker)
      if (g !== gen || !entered) return;   // QA-19: left Mission while the sites loaded: no picker over another mode
    }
    if (state && !state.over) {
      // [QA-66] the sim can move while we're away (the API, another window): take the server's state first, so a mission
      // it already finished opens on its debrief, not on a stale Day 1 HUD
      const fresh = await freshState(state.id);
      if (g !== gen || !entered) return;
      if (fresh) { prev = state; applyState(fresh, true); }
      if (state.over) { mclock.pause(); showDebrief(); return; }
      if (!unsub) unsub = client.subscribe(state.id, onTelemetry); showHud(); return; }   // [qa] telemetry again
    hub();
  }
  /** [QA-66] The server's current state for this mission, or null (sample data, offline, or a mission it no longer has). */
  async function freshState(id) {
    if (!client || client.sample || typeof client.get !== "function") return null;
    try { const s = await client.get(id); return s && s.id === id ? s : null; } catch (e) { return null; }
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
    cabinEl.hidden = true; delete document.body.dataset.cabin; delete document.body.dataset.cabinView; globe.setViewport(null); globe.pause(false); coach.stop();
    clearTimeout(surfT); if (tv) tv.hide(); curView = null; mclock.detach(); nudge.stop();
    if (cockpit && cockpit.dispose) { cockpit.dispose(); cockpit = null; }   // stop the 3D cabin's render loop
  };
  /** The window: ORBIT is the NASA globe (LROC colour); SITE / ROVER / EARTH are the LOLA terrain views. Going down
   *  from orbit, the globe dives toward the site first, then the surface view takes over the glass mid-descent. */
  function windowView(v) {
    if (!state) return;
    if (v === curView && tv && tvHost && tvHost.isConnected) return;   // the view already showing: no re-flight
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
  /** Spoken or typed panel words ("open the power panel", "habitat panel", "comm panel", "back to my seat"). */
  const PANEL_WORDS = [[/\b(power|display|displays|main) (panel|displays?)\b|\bopen (the )?power\b/, "power"], [/\b(habitat|hab|shelter) panel\b|\bopen (the )?(habitat|hab)\b/, "habitat"],
    [/\b(comm|comms|radio|houston) panel\b|\bopen (the )?comms?\b/, "comm"], [/\brover panel\b/, "rover"], [/\b(radiation|shield|shields|storm) panel\b/, "radiation"], [/\b(back to (my |the )?seat|close (the )?panel|seat view)\b|^back$/, "seat"]];
  function panelWord(text) {
    const tl = String(text || "").toLowerCase().trim(), m = PANEL_WORDS.find(([re]) => re.test(tl)); if (!m || !cockpit) return false;
    if (m[1] === "seat") { if (cockpit.systemsOpen) cockpit.systems(false); if (cockpit.is3d) cockpit.seat(); return true; }
    if (openSystemFor(m[1])) return true;
    if (!cockpit.is3d) return false;
    cockpit.openPanel(m[1]); return true;
  }
  /** [systems] A console's name ("the power panel") opens its drawer panel when this level has it; the 3D console
   *  otherwise (a Cadet's Comm and Habitat stay in the cabin's art, the Now card's button still does their job). */
  const SYS_OF_PANEL = { power: "power", displays: "power", radiation: "radiation", rover: "rover", habitat: "life", comm: "radio" };
  function openSystemFor(panelId) {
    const id = SYS_OF_PANEL[panelId]; if (!id || !cockpit || !cockpit.systems || !(cockpit.systemsList || []).includes(id)) return false;
    return cockpit.systems(true, id);
  }
  /** "show power", "next panel", "systems", "close systems", LB / RB, [ / ], the Systems key's words. */
  function systemsAct(arg) {
    if (screen !== "hud" || !cockpit || !cockpit.systems || tour.active) return false;
    if (cockpit.menuOpen || cockpit.chapterOpen) return false;
    nudge.heard();
    // keys or a controller: focus goes into the drawer (and back to the Systems key when it closes); voice and a
    // pointer leave focus where it is
    const focus = ["keys", "pad"].includes(document.documentElement.dataset.input), o = { focus };
    if (arg === "close") return cockpit.systems(false, null, o);
    if (arg === "next" || arg === "prev") return cockpit.systemsStep(arg === "next" ? 1 : -1, o);
    if (arg === "toggle") return cockpit.systemsOpen ? cockpit.systems(false, null, o) : cockpit.systems(true, null, o);
    if (cockpit.systems(true, arg || null, o)) return true;
    // a panel this level leaves out ("show the radio" as a Cadet): its 3D console, as before the drawer
    const con = { radio: "comm", life: "habitat" }[arg];
    if (con && cockpit.is3d) { cockpit.openPanel(con); return true; }
    return false;
  }
  function exit() { nv.hide(); coach.stop(); if (tour.active) tour.end(false); gen++; entered = false; screen = "off"; if (unsub) { unsub(); unsub = null; } /* [qa] no telemetry stream while away */ hideCabin(); globe.mission.exit(); panel.hidden = true; panel.classList.remove("mx-brief"); banner.hidden = true; debriefEl.hidden = true; signal.hidden = true; }

  /** The site picker (Moon-first): the five real sites as labelled pins on the south pole, a glass panel with the same
   *  sites as a table (radio group; the keyboard and screen-reader path), one primary action. Sun and Earth are the share
   *  of time in view during the mission's own 10-day window (JPL Horizons), the same numbers the sim and debrief use. */
  /** NASA's list of nine Artemis candidate landing regions (Oct 2024): two of our sites are on it; the others are sites
   *  that scientists study. The backend can send `nasa_candidate`; until then this table (docs/ACCURACY_AUDIT.md). */
  const NASA_CANDIDATE = new Set(["malapert_massif", "de_gerlache_rim"]);
  const siteTag = s => s.status_label || ((s.status ? s.status === "nasa_2024" : (s.nasa_candidate ?? NASA_CANDIDATE.has(s.id))) ? "NASA candidate region" : "Studied by scientists");
  // [qa] the day counts come from JPL Horizons (the sim's window), not from the site's first source (the IAU Gazetteer)
  const HORIZONS = { title: "JPL Horizons", url: "https://ssd.jpl.nasa.gov/horizons/" };
  const iceLabel = s => s.ice ? "ice nearby" : s.rover_to_ice_h ? `ice a ${s.rover_to_ice_h}-hour drive away` : "no ice nearby";
  const sunPct = s => Math.round(s.window_sunlit_pct ?? s.sunlight_pct);
  /** "Sun on your mission: N of 10 days" (window_sun_days from the learning design; derived from the window % until it lands). */
  const sunDays = s => s.window_sun_days ?? Math.round((s.window_sunlit_pct ?? s.sunlight_pct) / 10);
  const earthDays = s => s.window_earth_days ?? Math.round(s.earth_visible_pct / 10);
  /** [0.4.1] half days in plain words: 4.5 -> "4½" (never "4.5 of 10 days") */
  const dd = d => (Number.isInteger(+d) ? String(d) : `${Math.floor(+d)}½`);
  /** A first-timer (no mission flown yet on this cadet) sees the recommended pick. */
  let firstPick = false, briefSpoken = false;
  /** [0.3.12] "Fly the check ride", and before the core lessons are done the line that says when it opens
   *  ("Unlocks after 6 lessons (2/6)"); academy.goRide() then opens the next lesson instead of dropping the cadet on
   *  the map with no reason (main.js). */
  function rideButton(cls, id) {
    const c = academy && academy.rideStatus ? academy.rideStatus() : null, locked = !!c && !rideReady(c);
    const line = locked ? GATE.rideLocked(c.n, c.of) : "";
    const btn = `<button type="button" class="${cls}${locked ? " is-locked" : ""}" id="${id}"${locked ? ` aria-describedby="${id}L"` : ""}>${esc(GATE.ride)}</button>`;
    return locked ? `<span class="mx-ridewrap">${btn}<span class="mx-lock" id="${id}L">${esc(line)}</span></span>` : btn;
  }
  /** Before the check ride: the path, and one practice shift (never the site picker or "Commander"). */
  function gate() {
    const fresh = screen !== "gate";
    screen = "gate"; debriefEl.hidden = true; banner.hidden = true; panel.hidden = false; hideCabin(); card.hide(); if (tour.active) tour.end(false);
    panel.classList.remove("mx-hub", "mx-plan"); panel.classList.add("mx-brief");
    panel.innerHTML = `
      <header class="mx-head"><span class="eyebrow">${esc(GATE.eyebrow)}</span>${sampleTag()}</header>
      <h2 class="mx-title">${esc(GATE.title)}</h2>
      <p class="mx-sub">${esc(GATE.sub)}</p>
      <button type="button" class="mx-go" id="mPractice">${esc(GATE.practice)}</button>
      ${rideButton("mx-link", "mRide")}`;
    $("mPractice").onclick = () => startPractice();
    $("mRide").onclick = () => academy && academy.goRide && academy.goRide();
    site = sites.find(s => s.id === PICKER.recommended) || sites[0]; previewSite();
    if (fresh) Promise.resolve(say(GATE.say(callSign.spoken("Cadet")))).catch(() => {});
    requestAnimationFrame(() => { const b = $("mPractice"); if (b) b.focus({ preventScroll: true }); });
  }
  function startPractice() { practice = true; site = sites.find(s => s.id === PICKER.recommended) || sites[0]; start(undefined, { practice: true }); }
  /** The practice shift is over: a short end card (not a graded debrief), the check ride first. */
  function practiceDone() {
    if (!practice || screen !== "hud") return;
    const where = (state && state.site && state.site.name) || "";
    practice = false; mclock.pause(); screen = "practice_done"; hideCabin(); card.hide();
    if (unsub) { unsub(); unsub = null; } state = null;   // a practice never continues as a real mission
    debriefEl.hidden = false; debriefEl.classList.add("mx-debrief");
    debriefEl.innerHTML = `<header class="mx-head"><span class="eyebrow">${esc(GATE.tag)} · ${esc(where)}</span></header>
      <div class="mx-db-top"><div><h2 class="mx-title">${esc(GATE.doneTitle)}</h2><p class="mx-sub">${esc(GATE.doneSub)}</p></div></div>
      <div class="mx-foot">${rideButton("mx-go", "mRide2")}<button type="button" class="mx-link" id="mPracticeAgain">${esc(GATE.again)}</button></div>`;
    $("mRide2").onclick = () => academy && academy.goRide && academy.goRide();
    $("mPracticeAgain").onclick = () => startPractice();
    Promise.resolve(say(GATE.doneSay(callSign.spoken("Cadet")))).catch(() => {});
  }
  function picker() {
    if (!qualified()) { gate(); return; }
    const fresh = screen !== "brief";
    screen = "brief"; debriefEl.hidden = true; panel.classList.remove("mx-hub", "mx-plan"); banner.hidden = true; panel.hidden = false; hideCabin(); card.hide(); if (tour.active) tour.end(false);
    firstPick = !firstDone();
    if (!site) site = (firstPick && sites.find(s => s.id === PICKER.recommended)) || sites[0];
    // the transition beat: where you are (Command), why the choice matters; spoken once per visit
    // one say through the line queue: no async chain to outlive the screen (rc-polish's screen generations)
    if (fresh) Promise.resolve(say([PICKER.why, ...(firstPick ? [PICKER.recLine] : [])])).catch(() => {});   // [polish 4] the hub said hello
    if (nv.ready && sites.every(s => nv.place(s.id))) {   // the navigator: map, layers, numbers with sources, weights
      nv.render({ site, firstPick, recommended: PICKER.recommended, recTag: PICKER.recTag });
      previewSite(); if (!nv.mapShown) pins(pickSite); else if (pinEl) pinEl.hidden = true;
      offerContinue();
      return;
    }
    const src0 = site && (site.sources || [])[0];
    panel.classList.add("mx-brief");
    panel.innerHTML = `
      <header class="mx-head"><span class="eyebrow">Briefing</span>${sampleTag()}</header>
      <h2 class="mx-title">${esc(PICKER.title)}</h2>
      <p class="mx-sub">${esc(PICKER.why)}</p>
      <p class="mx-do">Tap a site to compare. Then tap Take command.</p>
      <div class="mx-sites" role="radiogroup" aria-label="Outpost site">
        <div class="mx-cols" aria-hidden="true"><span></span><span>${ic("sun")}Sun</span><span>${ic("earth")}Earth</span><span>${ic("ice")}Ice<small>away</small></span></div>
        ${sites.map(s => `
        <button type="button" class="mx-site" role="radio" data-site="${esc(s.id)}" aria-checked="${s === site}" tabindex="${s === site ? 0 : -1}"
          aria-label="${esc(s.name)}: Sun on ${dd(sunDays(s))} of 10 days, Earth in view on ${dd(earthDays(s))} of 10 days, ${iceLabel(s)}">
          <b>${esc(s.name)}${firstPick && s.id === PICKER.recommended ? `<em class="mx-rectag">${esc(PICKER.recTag)}</em>` : ""}<em class="mx-tag2">${siteTag(s)}</em>${s === site && s.sunlight_pct != null ? `<small>${s.power_from ? `Power by cable from the ${pretendLabel("rim")}` : `About ${Math.round(s.sunlight_pct)}% sunlight (yearly average)`}</small>` : ""}</b>
          <span class="mx-v${sunDays(s) >= 8 ? " is-best" : ""}">${dd(sunDays(s))}<small>/10</small></span>
          <span class="mx-v${earthDays(s) >= 8 ? " is-best" : ""}">${dd(earthDays(s))}<small>/10</small></span>
          <span class="mx-v${s.ice ? " is-best" : ""}">${s.ice ? "Here" : s.rover_to_ice_h ? `${s.rover_to_ice_h}<small> h</small>` : "No"}</span>
        </button>`).join("")}
      </div>
      <p class="mx-srcline">Sun and Earth: days in view during your 10 days · ${srcLink(HORIZONS, "JPL Horizons")}</p>
      <button type="button" class="mx-go" id="mStart">${esc(PICKER.go)}</button>`;
    offerContinue();
    const pick = id => { site = sites.find(s => s.id === id); previewSite(); picker(); const n = panel.querySelector(`[data-site="${CSS.escape(site.id)}"]`); if (n) n.focus(); };
    panel.querySelectorAll(".mx-site").forEach(b => {
      b.onclick = () => pick(b.dataset.site);
      b.onpointerenter = () => hot(b.dataset.site, true); b.onpointerleave = () => hot(b.dataset.site, false);
    });
    panel.querySelector(".mx-sites").addEventListener("keydown", e => {
      // [keys] Up/Down walk the rows; past the first / last row the arrow leaves the list (spatial focus, docs/KEYBOARD.md)
      const d = { ArrowDown: 1, ArrowUp: -1 }[e.key]; if (!d) return;
      const k = sites.indexOf(site) + d; if (k < 0 || k >= sites.length) return;
      e.preventDefault(); e.stopPropagation();
      pick(sites[k].id);
    });
    $("mStart").onclick = () => toPlan();
    previewSite(); pins(pick);
  }
  /** One pick path for the picker's rows, its pins and the navigator's map: select, preview, re-render, keep focus. */
  function pickSite(id) {
    const s = sites.find(x => x.id === id); if (!s) return;
    site = s; previewSite(); picker();
    const n = panel.querySelector(`[data-site="${CSS.escape(site.id)}"]`); if (n) n.focus({ preventScroll: true });
  }
  const nv = createNavigator({
    panel, say: t => say(t), onPick: id => pickSite(id), onStart: () => toPlan(), active: () => screen === "brief",
    missionText: id => { const s = sites.find(x => x.id === id); if (!s) return "";
      const parts = [`Sun ${dd(sunDays(s))} of 10 days`, `talk to Earth ${dd(earthDays(s))} of 10 days`,
        s.ice ? "ice right here" : s.rover_to_ice_h ? `ice a ${s.rover_to_ice_h}-hour drive each way` : ""];
      if (s.rover_slope_power) parts.push(`steep drive +${s.rover_slope_power}% battery`);
      return parts.filter(Boolean).join(" · ") + "."; },
    // [playtest 15] the Cadet briefing: three bars and three short lines per site, in mission days (the hub's words)
    simple: () => levelNow() === "cadet",
    kidLines: id => { const s = sites.find(x => x.id === id); if (!s) return [];
      const sd = sunDays(s), ed = earthDays(s), ih = s.ice ? 0 : (s.rover_to_ice_h || 0);
      return [{ icon: "sun", p: sd / 10, short: `Sun ${dd(sd)}/10`, text: `Sun for power: ${dd(sd)} of 10 days` },
        { icon: "earth", p: ed / 10, short: `Earth ${dd(ed)}/10`, text: ed > 0 ? `Talk to Earth: ${dd(ed)} of 10 days` : "No talking to Earth this mission" },
        { icon: "ice", p: 1 - Math.min(1, ih / 12), short: s.ice ? "Ice here" : `Ice ${ih} h`, text: s.ice ? "Ice right here" : `Ice: a ${ih}-hour drive` }]; },
  });
  try { (window.__outpost = window.__outpost || {}).navigator = nv; } catch (e) { /* */ }   // tests/e2e/site_navigator_e2e.py
  /** Row and pin: hovering either lights both. */
  function hot(id, on) {
    document.querySelectorAll(`.mx-pin[data-site="${CSS.escape(id)}"], .mx-dot[data-site="${CSS.escape(id)}"], .mx-site[data-site="${CSS.escape(id)}"]`).forEach(n => n.classList.toggle("is-hot", on));
  }
  /** Pins on the pole + their labels in a column beside the cluster, joined by leader lines (four of the five sites are
   *  within 2° of the pole, so labels next to the dots would overlap at any distance the camera allows). */
  let pinEl = null, pinRaf = 0;
  function pins(pick) {
    if (!globe.project) return;
    if (!pinEl) { pinEl = document.createElement("div"); pinEl.className = "mx-pins"; pinEl.setAttribute("aria-hidden", "true"); panel.parentNode.insertBefore(pinEl, panel); }
    pinEl.innerHTML = `<svg class="mx-leads"></svg>` + sites.map(s => `<i class="mx-dot${s === site ? " is-sel" : ""}" data-site="${esc(s.id)}"></i>
      <button type="button" tabindex="-1" class="mx-pin${s === site ? " is-sel" : ""}" data-site="${esc(s.id)}">${esc(s.name.split(" (")[0])}</button>`).join("");
    pinEl.querySelectorAll(".mx-pin").forEach(b => {
      b.onclick = () => pick(b.dataset.site);
      b.onpointerenter = () => hot(b.dataset.site, true); b.onpointerleave = () => hot(b.dataset.site, false);
    });
    pinEl.hidden = false; cancelAnimationFrame(pinRaf);
    // [QA-61] look the nodes up once, and write only when the picture changes (camera move, resize, a new pick):
    // a still globe used to cost an SVG rebuild, 10 querySelector calls and a forced layout every frame
    const svg = pinEl.querySelector(".mx-leads"), els = new Map();
    pinEl.querySelectorAll("[data-site]").forEach(n => { const e = els.get(n.dataset.site) || {}; e[n.tagName === "I" ? "dot" : "lab"] = n; els.set(n.dataset.site, e); });
    let lastKey = "";
    const tick = () => {
      if (screen !== "brief" || pinEl.hidden) { pinEl.hidden = true; pinRaf = 0; return; }
      const P = [];
      for (const s of sites) { const p = globe.project(s.lat, s.lon); if (p.facing) P.push({ id: s.id, x: p.x, y: p.y }); }
      const L = pinLayout(P, pinEl.clientHeight || innerHeight, site && site.id);
      if (L.key !== lastKey) {
        lastKey = L.key;
        for (const r of L.rows) {
          const e = els.get(r.id); if (!e || !e.dot || !e.lab) continue;
          e.dot.style.transform = `translate(${r.dot[0]}px,${r.dot[1]}px)`;
          e.lab.style.transform = `translate(calc(${r.lab[0]}px - 100%),${r.lab[1]}px)`;
        }
        svg.innerHTML = L.lines;
      }
      pinRaf = requestAnimationFrame(tick);
    };
    tick();
  }
  function previewSite() {
    if (!site) return;
    globe.mission.setSite({ ...site, short: site.name.split(" (")[0] }, { dist: 2.0, clamp: false });
    globe.mission.setSun(1, 0); globe.mission.setEarth(site.earth_visible_pct > 60 ? 3 : -1); globe.mission.setRover(null);
    // frame the whole south-pole region (all five sites), not just the picked one; the band lifts the pole off the strip.
    // [0.4] straight down on the pole ({clamp: false}, docs/MEDIA.md): the LOLA relief (site_layers) reads sharp and
    // flat, the five pins spread out instead of stacking on the slanted limb
    // the pole sits in the middle of the free area: lifted off the voice bar, left of the side panel
    const sr = panel.parentNode && panel.parentNode.getBoundingClientRect(), pr = !panel.hidden && panel.getBoundingClientRect();
    const xs = sr && pr && pr.width && sr.width ? Math.max(0, Math.min(.25, (sr.right - pr.left) / 2 / sr.width)) : 0;
    globe.setViewport(window.__pickBand || PICK_VIEW.band, xs); globe.flyTo(PICK_VIEW.lat, PICK_VIEW.lon, window.__pickDist || PICK_VIEW.dist, { clamp: false });
  }

  // ---------- [polish 4] the Mission hub and the 3-card briefing (docs/MISSION_POLISH_SPEC.md, wave 4) ----------
  // Mission tab -> hub (one card: the mission, its site, Start; the navigator is one press away) -> briefing (Goal,
  // Danger, Bonus; Take command) -> the cabin. The NASA video is a chip on the hub (mission_learning.js), never a yes / no.
  const missionNo = () => (cm && cm.n) || 1;   // [campaign] the mission's number in the campaign
  const won = () => CM.wonIds(callSign.get());
  const openCount = () => CM.unlockedCount(campaignList, won());
  /** [campaign] the mission on the hub: the one picked, while it is open; else the next one up */
  function pickMission(m) {
    const open = campaignList.slice(0, openCount());
    cm = (m && open.find(x => x.id === m.id)) || (cm && open.find(x => x.id === cm.id)) || CM.nextUp(campaignList, won());
    if (CM.isCampaign(cm)) site = sites.find(s => s.id === cm.site) || site;
    return cm;
  }
  /** [campaign] the mission strip: 1 to 6, the locked ones dimmed with a lock (shown once the campaign has a list) */
  function stripHtml() {
    if (campaignList.length < 2) return "";
    const n = openCount(), w = new Set(won());
    return `<nav class="mx-camp" aria-label="${esc(CAMPAIGN.strip)}">${campaignList.map((m, i) => {
      const locked = i >= n, cur = cm && m.id === cm.id;
      return `<button type="button" class="mx-campb${cur ? " is-on" : ""}${w.has(m.id) ? " is-won" : ""}" data-cm="${esc(m.id)}" ${locked ? "disabled" : ""}
        aria-pressed="${cur ? "true" : "false"}" aria-label="${esc(locked ? CAMPAIGN.locked(m.n) : CAMPAIGN.pick(m.n, m.title) + (w.has(m.id) ? `, ${CAMPAIGN.won}` : ""))}" title="${esc(locked ? CAMPAIGN.locked(m.n) : m.title)}">${locked ? ic("lock", 14) : w.has(m.id) ? ic("check", 14) : ""}<span>${m.n}</span></button>`;
    }).join("")}</nav>`;
  }
  /** [campaign] LB / RB on the hub: another open mission (with only Mission 1 open: another site, as before) */
  function stepMission(d) {
    const open = campaignList.slice(0, openCount());
    if (open.length < 2) return false;
    const i = Math.max(0, open.findIndex(x => cm && x.id === cm.id));
    pickMission(open[(i + d + open.length) % open.length]);
    if (!CM.isCampaign(cm)) site = sites.find(s => s.id === PICKER.recommended) || site;
    hub(); return true;
  }
  // [0.4.1] plain words: "Talk to Earth 4½ of 10 days", "Ice: a 7-hour drive" (were "Radio 4.5 of 10 days", "Ice 7 h away")
  const hubFacts = s => [["sun", `Sun ${dd(sunDays(s))} of 10 days`], ["earth", `Talk to Earth ${dd(earthDays(s))} of 10 days`],
    ["ice", s.ice ? "Ice right here" : s.rover_to_ice_h ? `Ice: a ${s.rover_to_ice_h}-hour drive` : "No ice nearby"]]
    .map(([i, t]) => `<span>${ic(i, 16)}${esc(t)}</span>`).join("");
  function hub() {
    if (!qualified()) { gate(); return; }
    const fresh = screen !== "hub";
    nv.hide(); if (pinEl) pinEl.hidden = true;
    screen = "hub"; debriefEl.hidden = true; banner.hidden = true; panel.hidden = false; hideCabin(); card.hide(); if (tour.active) tour.end(false);
    firstPick = !firstDone();
    pickMission();
    if (!site) site = sites.find(s => s.id === PICKER.recommended) || sites[0];
    if (!site) return;
    const nm = site.name.split(" (")[0], rec = site.id === PICKER.recommended, camp = CM.isCampaign(cm);
    panel.classList.remove("nv", "mx-plan"); panel.classList.add("mx-brief", "mx-hub"); panel.style.maxHeight = "";
    // [campaign] Missions 2+: the mission's title over its site, and its own one-line briefing; the site is the mission's
    panel.innerHTML = `
      <header class="mx-head"><span class="eyebrow">${esc(HUB.eyebrow(missionNo()))}</span>${sampleTag()}</header>
      ${stripHtml()}
      <div class="mx-hubcard">
        <h2 class="mx-title">${esc(camp ? cm.title : nm)}</h2>
        <p class="mx-hubrec${camp ? " is-site" : ""}">${camp ? `${ic("site", 14)}${esc(nm)}` : rec ? `${ic("star", 14)}${esc(HUB.rec)}` : esc(siteTag(site))}</p>
        ${camp ? `<p class="mx-hubline">${esc(cm.line)}</p>` : ""}
        <p class="mx-hubfacts">${hubFacts(site)}</p>
        ${camp ? "" : `<p class="mx-hubwhat" id="mHubWhatT" hidden>${esc(HUB.whatLine)}</p>`}
      </div>
      <button type="button" class="mx-go" id="mStart"><span>${esc(HUB.start)}</span></button>
      ${camp ? "" : `<div class="mx-hubrow">
        <button type="button" class="mx-btn" id="mHubSite">${ic("map", 16)}<span>${esc(HUB.choose)}</span></button>
        <button type="button" class="mx-btn" id="mHubWhat" aria-expanded="false" aria-controls="mHubWhatT">${ic("info", 16)}<span>${esc(HUB.what)}</span></button>
      </div>`}`;
    $("mStart").onclick = () => toPlan();
    if ($("mHubSite")) $("mHubSite").onclick = () => picker();
    if ($("mHubWhat")) $("mHubWhat").onclick = () => hubWhat();
    panel.querySelectorAll("[data-cm]").forEach(b => { b.onclick = () => { const m = campaignList.find(x => x.id === b.dataset.cm); if (!m || b.disabled) return;
      pickMission(m); if (!CM.isCampaign(cm)) site = sites.find(s => s.id === PICKER.recommended) || site; hub(); const f = panel.querySelector(`[data-cm="${m.id}"]`); if (f) f.focus({ preventScroll: true });
      Promise.resolve(say(CM.isCampaign(cm) ? cm.line : HUB.whatLine)).catch(() => {}); }; });
    previewSite();
    offerContinue();
    if (fresh && !briefSpoken) { briefSpoken = true; Promise.resolve(say(camp ? CAMPAIGN.say(callSign.spoken(), cm.n, cm.title, nm) : HUB.say(callSign.spoken(), nm))).catch(() => {}); }
    try { dispatchEvent(new CustomEvent("outpost:mission-hub")); } catch (e) { /* old browsers */ }   // mission_learning.js adds the video chip
  }
  function hubWhat() {
    if (CM.isCampaign(cm)) { Promise.resolve(say(cm.line)).catch(() => {}); return true; }   // [campaign] its own line
    const t = $("mHubWhatT"), b = $("mHubWhat"); if (!t || !b) return false;
    t.hidden = false; b.setAttribute("aria-expanded", "true");
    Promise.resolve(say(HUB.whatLine)).catch(() => {});
    return true;
  }
  /** The briefing: three cards and Take command (from the hub's Start or the navigator's Start). */
  function toPlan() {
    if (!qualified()) { gate(); return; }
    if (screen === "brief") { const checked = panel.querySelector('.mx-site[aria-checked="true"]'); if (checked) site = sites.find(s => s.id === checked.dataset.site) || site; }
    if (!site) return;
    nv.hide(); if (pinEl) pinEl.hidden = true;
    screen = "plan"; debriefEl.hidden = true; banner.hidden = true; panel.hidden = false; card.hide();
    const nm = site.name.split(" (")[0], camp = CM.isCampaign(cm) && cm.site === site.id;
    if (!camp && CM.isCampaign(cm)) cm = campaignList[0];   // a site picked in the navigator flies Mission 1's way
    panel.classList.remove("nv", "mx-hub"); panel.classList.add("mx-brief", "mx-plan"); panel.style.maxHeight = "";
    panel.innerHTML = `
      <header class="mx-head"><span class="eyebrow">${esc(BRIEFING.eyebrow)} · ${esc(nm)}</span>${sampleTag()}</header>
      <h2 class="mx-title">${esc(camp ? CAMPAIGN.pick(cm.n, cm.title) : BRIEFING.title)}</h2>
      <ol class="mx-cards">${(camp ? CM.briefCards(cm) : BRIEFING.cards).map(c => `<li class="mx-card is-${c.k}"><span class="mx-card-i">${ic(c.icon, 22)}</span><b>${esc(c.label)}</b><span class="mx-card-t">${esc(c.text)}</span></li>`).join("")}</ol>
      <button type="button" class="mx-go" id="mBriefGo"><span>${esc(BRIEFING.go)}</span></button>
      <button type="button" class="mx-link" id="mBriefBack">${esc(BRIEFING.back)}</button>`;
    $("mBriefGo").onclick = () => start();
    $("mBriefBack").onclick = () => hub();
    previewSite();
    Promise.resolve(say(camp ? cm.say : BRIEFING.say)).catch(() => {});
  }

  let starting = false;
  async function start(seed, { practice: isPractice = false } = {}) {
    if (!isPractice) practice = false;
    // [qa] QA-54: one mission per press (a double click, or a click while saying "take command"); a failed start says so
    if (starting) return; starting = true;
    document.querySelectorAll("#mStart, #mBriefGo, #mAgain").forEach(b => { b.disabled = true; });
    // dev-only: tools/*.py may fix the storm schedule (window.__missionSeed) so a check reaches the same moment
    siteSeed = seed ?? ((import.meta.env && import.meta.env.DEV && window.__missionSeed != null) ? +window.__missionSeed : Math.floor(Math.random() * 1e9));
    // Settings → level (prefs, from the first request), else the stored tier; Cadet/Commander bands in the sim
    const level = isPractice ? "cadet" : (window.__outpost && window.__outpost.prefs && window.__outpost.prefs.level) || tier();
    let st = null;
    const g = gen;
    // the row the kid sees selected is the one that flies (QA rc/2: "take command" started another site): the picker's
    // checked row wins over any stale `site`; hover only highlights (hot()), it never selects
    const checked = !isPractice && screen === "brief" && panel.querySelector('.mx-site[aria-checked="true"]');
    if (checked) site = sites.find(s => s.id === checked.dataset.site) || site;
    window.__outpost && (window.__outpost.missionSite = site && site.id);   // tools/picker_select.py reads it
    const cmId = !isPractice && CM.isCampaign(cm) && cm.site === site.id ? cm.id : null;   // [campaign]
    try { st = await client.start({ site: site.id, seed: siteSeed, roles: [...roles], level, ...(cmId ? { campaign: cmId } : {}), ...(isPractice ? { practice: true } : {}) }); } catch (e) { st = null; }
    starting = false;
    document.querySelectorAll("#mStart, #mBriefGo, #mAgain").forEach(b => { b.disabled = false; });
    if (!alive(g)) return;   // left Mission while it started (even if the kid is back on a new screen generation)
    if (!st) { capcom({ say: "Can't reach the mission server. Try again." }); return; }
    enterMission(st, level);
  }
  /** A mission state from the server (a new one, or the auto-save): wire the clock, telemetry and the cabin. */
  function enterMission(st, level, resumed = false) {
    chaptersSeen = ((st.chapter && st.chapter.done) || []).length;
    state = st; prev = null; logHistory = []; reminded.clear(); seen.clear();
    offer = null; pending = null; decisionAt = 0;   // [polish 3] a new mission never inherits the last one's question
    mclock.detach(); mclock = newClock(); lastTask = st.task ? st.task.id : null; lastAck = st.ack ? st.ack.n : 0; beatsSeen = new Set((st.story && st.story.reached) || []);
    if (unsub) unsub();
    unsub = client.subscribe(state.id, onTelemetry);
    pushContext();
    showHud();
    if (session && !client.sample && session.onStart) session.onStart(state);   // [session hook]
    windows = null; if (client.windows) client.windows(state.id).then(w => { windows = w; if (cockpit && cockpit.setWindows) cockpit.setWindows(w); }).catch(() => {});
    if (resumed) {   // [polish 2] Continue: back where the chapter saved; the clock waits for Play
      const c = st.chapter || {}, line = `Welcome back. Day ${st.day}, chapter ${c.n || 1}: ${c.title || ""}.`.replace(/: \.$/, ".");
      capcom({ say: line }); Promise.resolve(say(line)).catch(() => {}); nudge.arm(); briefSpoken = false; return;
    }
    capcom({ say: CAPCOM.missionStart(callSign.shown(), site.name) });
    const first = !firstDone();
    // never wait on the voice for the next step: a slow or silent TTS must not leave the kid in a cabin with no guide
    // One say through the floor's line queue (rc-polish): the hello and the objective play as one on-air span, so the
    // ear's hard mute covers the whole run. The card shows at once; it never waits on the voice.
    const hello = CAPCOM.missionStart(callSign.spoken(), site.name);
    const ob = cardNow();   // [polish 3] the job is on the Now card; CAPCOM's radio log doesn't repeat it
    Promise.resolve(say(ob ? [hello, ob.text] : hello)).catch(() => {});
    nudge.arm();
    // [polish 4] first mission: teach by doing, one prompt at a time beside its control (coach.js), not a 12-step
    // tour (the tour stays in Settings -> Help, "Show me around")
    if (!coachDone(callSign.get())) coach.start();
    if (first) markFirstDone();
    briefSpoken = false;
  }

  /** [polish 2] The hub offers the chapter auto-save (the server keeps one): Continue, or pick a site for a new one. */
  function offerContinue() {
    // [polish 4] Quit to hub with the mission still in memory: Resume goes straight back to its cabin
    const live = !!(state && !state.over && !practice);
    if (!client || (!client.saved && !live) || (state && !state.over && !live)) return;
    const g = gen;
    const saved = live ? Promise.resolve({ saved: { day: state.day, site_name: state.site.name, chapter: ((state.chapter && state.chapter.done) || []).length, live: true } }) : client.saved();
    saved.then(r => {
      if (!alive(g) || (screen !== "brief" && screen !== "hub") || !r || !r.saved) return;
      const v = r.saved; panel.querySelectorAll(".mx-continue").forEach(n => n.remove());
      panel.insertAdjacentHTML("afterbegin", `<div class="mx-continue" role="group" aria-label="Saved mission">
        <span>${ic("check")}<b>Resume ${v.mission_n > 1 ? `Mission ${v.mission_n}, ` : ""}Day ${v.day} at ${esc(v.site_name.split(" (")[0])}</b><small>Saved automatically · Chapter ${Math.min(5, v.chapter + 1)} of 5</small></span>
        <button type="button" class="mx-go" id="mContinue" aria-label="Resume day ${v.day} at ${esc(v.site_name.split(" (")[0])}">Resume</button></div>`);
      const go = panel.querySelector("#mStart"); if (go && !/new/i.test(go.textContent)) go.textContent = "New mission";
      panel.querySelector("#mContinue").onclick = () => (v.live && state && !state.over ? showHud() : resumeSaved());
    }).catch(() => {});
  }
  async function resumeSaved() {
    if (starting || !client.resume) return;
    starting = true; const g = gen; let st = null;
    try { st = await client.resume(); } catch (e) { st = null; }
    starting = false;
    if (!alive(g)) return;
    if (!st) { capcom({ say: "That saved mission can't be opened. Pick a site to start a new one." }); return; }
    site = sites.find(s => s.id === (st.site && st.site.id)) || site;
    cm = campaignList.find(x => st.campaign && x.id === st.campaign.id) || cm;   // [campaign]
    enterMission(st, null, true);
  }

  // ---------- first mission: one "how to play" line, repeated only after ~20 s of silence with no order (max twice) ----------
  const firstKey = () => "outpost-first-mission:" + (callSign.get() || "cadet");
  const firstDone = () => { try { return localStorage.getItem(firstKey()) === "1"; } catch (e) { return false; } };
  const markFirstDone = () => { try { localStorage.setItem(firstKey(), "1"); } catch (e) { /* private mode */ } };
  // No dead air (docs/GAMEPLAY.md §4): ~20 s with nothing done while a job waits -> CAPCOM names the job, at most
  // twice per job. Any order, tap, clock control or word from the kid restarts the silence.
  // [0.6] Hesitation (docs/GAMEPLAY.md §14.3): a heard turn with fillers or a long pause (the session's `hes` flag on
  // `heard`) brings that nudge now instead of in 20 s, once per job, if the turn didn't do the job (HES_MS later the
  // card is the same). It is one of the job's two nudges, never an extra one, and never says why it came early.
  const NUDGE_MS = 20000, HES_MS = 1500;
  const nudge = { t: null, h: null, left: 0, key: "", early: new Set(),
    arm(key = "") { this.key = key; this.left = 2; this.wait(); },
    wait() { clearTimeout(this.t); if (this.left <= 0) return; this.t = setTimeout(() => {
      if (screen !== "hud" || !state || tour.active || pending) { this.wait(); return; }
      const c = cardNow(); if (!c || !(c.buttons || []).length || c.key === "steady") return;
      this.left--; this.speak(c);
      this.wait(); }, NUDGE_MS); },
    speak(c) { const line = c.offer ? c.text : nudgeLine(state, mclock.state); if (line) { radio("capcom", line); say(line, null, { priority: 4 }); } },
    heard() { if (this.left > 0) this.wait(); },   // the kid spoke or acted: the silence starts again
    soon() {
      const c0 = screen === "hud" && state && !tour.active && !pending ? cardNow() : null;
      if (!c0 || !(c0.buttons || []).length || c0.key === "steady" || this.left <= 0 || this.early.has(c0.key)) return false;
      this.early.add(c0.key); clearTimeout(this.h);
      this.h = setTimeout(() => {
        if (screen !== "hud" || !state || tour.active || pending || this.left <= 0) return;
        const c = cardNow(); if (!c || c.key !== c0.key) return;   // the turn did the job (or the job changed)
        this.left--; this.speak(c); this.wait();
      }, HES_MS);
      return true;
    },
    stop() { clearTimeout(this.t); clearTimeout(this.h); this.left = 0; } };

  // ---------- the live mission clock (mission/clock.js) ----------
  let lastProg = null;   // [wave 5] {task, done}: the Now card's step count, for the done pulse
  let lastTask = null, lastAck = 0, ackShown = null, ackUntil = 0, beatsSeen = new Set(), decisionAt = 0, stepping = null;
  // ---------- [polish 3] one instruction at a time (docs/MISSION_POLISH_SPEC.md, problem 3) ----------
  // Every question CAPCOM asks in the cabin (a yes / no, the Director's offer) is the Now card: never a second card in
  // the window, a pair of buttons on a console, or buttons on the alert strip. `offer` is that question while it waits.
  //   {confirm, title, text, actions: [{label, onClick}], panel, at, n}
  let offer = null, offerN = 0;
  const OFFER_MS = 30000;   // an offer (not a yes / no) holds the clock this long, then the sim's own job comes back
  function setOffer(o) {
    offer = o ? { ...o, at: Date.now(), n: ++offerN } : null;
    decisionAt = o ? Date.now() : 0;
    if (o) nudge.arm("offer:" + offerN);
    renderCard();
  }
  const offerLive = () => !!offer && (offer.confirm || (Date.now() - offer.at < OFFER_MS && !staleOffer(offer.d || {})));
  /** The Now card: CAPCOM's question while one waits, otherwise the sim's job (objective.js nowCard). */
  function cardNow() {
    if (!state || state.over) return null;
    const base = nowCard(state, mclock.state);
    if (offer && !offerLive()) offer = null;
    if (offer && !offer.confirm && base && base.choice) offer = null;   // the sim's own decision wins; the offer repeated it
    if (!offer) return base;
    const yn = l => (/^yes\b/i.test(l) ? "yes" : /^no\b/i.test(l) ? "no" : null);
    return { key: `offer:${offer.n}`, title: offer.title || NOW.confirmTitle, text: offer.text || NOW.confirm, target: "task", panel: offer.panel || null,
      level: offer.level || "caution", progress: null, left_h: base && base.left_h != null ? base.left_h : null, lesson: null, readouts: [],
      choice: true, offer: true, kind: "offer", buttons: offer.actions.map((a, i) => ({ label: a.label, offer: i, intent: yn(a.label) })) };
  }
  /** Why time must wait right now (docs/GAMEPLAY.md §2), or null. */
  function held() {
    if (screen !== "hud" || !state) return "away";
    if (state.over) return "over";
    if (tour.active) return "tour";
    if (pending || (offer && offer.confirm)) return "confirm";
    if (state.task && state.task.decision) return "choice";
    if (offer && offerLive()) return "decision";
    if (document.hidden) return "hidden";
    // [playtest 17] Settings, About or a video over the cabin: time waits (a storm never passes behind a menu)
    if (document.querySelector(".a11y-panel:not([hidden]), dialog[open]")) return "settings";
    return null;
  }
  const AUTO_MS = 3500;   // [polish a] how long a wait-only card shows before time fast-forwards by itself
  let autoT = 0, autoKey = "";   // declared before renderCard can run (no temporal dead zone at start-up)
  // dev-only: tools/play_mission.py may run the clock faster (window.__hourMs); the shipped app always uses HOUR_MS
  const hourMs = () => (import.meta.env && import.meta.env.DEV && +window.__hourMs) || 0;
  const newClock = () => createMissionClock({
    post: dt => stepClock(dt), held, hourMs,
    onChange: c => { if (cockpit && cockpit.clock) cockpit.clock(c); if (c.running || c.held) renderCard(); },
  });
  let mclock = newClock();
  async function stepClock(dt) {
    if (!state || !client || screen !== "hud" || !client.step) return;
    const g = gen, id = state.id;
    const p = client.step(id, dt); stepping = p;
    let r; try { r = await p; } finally { if (stepping === p) stepping = null; }
    if (!alive(g) || !state || state.id !== id) return;
    applyLive(r);
  }
  /** A clock step, a skip or an end-shift came back: the new state, its events, the frame between whole hours. */
  function applyLive(r) {
    if (!r || !r.state) return;
    prev = state; applyState(r.state, true);
    const evs = r.events || [];
    if (evs.some(e => WARP_STOPS.has(e.kind))) mclock.dropWarp();
    handleEvents(evs); story(evs);
    if (r.live && cockpit) { cockpit.frame(r.live); cockpit.telemetry(r.live); onTelemetry(r.live); }
    if (state.over) { mclock.pause(); showDebrief(); }
    else if (practice && (state.mission_time_h || 0) >= PRACTICE_H) practiceDone();
  }
  /** Story beats: the window's moment, the mission log, and (with no session Director) CAPCOM's line. */
  function story(evs) {
    evs.filter(e => e.kind === "beat" && !beatsSeen.has(e.beat)).forEach(e => {
      beatsSeen.add(e.beat);
      if (cockpit && cockpit.moment) cockpit.moment({ title: e.title, visual: e.visual, objective: e.objective, t_h: e.t_h });
      const v = MOMENT_VIEW[e.visual];
      if (v && cockpit && cockpit.view === "site" && !(cockpit.panel)) { cockpit.setView(v); setTimeout(() => { if (cockpit && cockpit.view === v) cockpit.setView("site"); }, 6500); }
      if (e.beat !== "arrival") radio("capcom", e.text);
      if (SPOKEN_BEATS.has(e.beat) && !(session && session.live && session.live())) say(e.text, null, { priority: 4 });
    });
  }
  /** The clock's controls (the cabin's buttons, keys, voice, gestures): play / pause, warp, skip. */
  function clockAction(a, arg) {
    if (screen !== "hud" || !state || state.over) return false;
    nudge.heard();
    if (a === "toggle") { mclock.toggle(); if (mclock.started && !mclock.paused) say(mclock.warp > 1 ? `Clock running, ${mclock.warp} times.` : "Clock running.", null, { priority: 4 }); }
    else if (a === "play") mclock.play();
    else if (a === "pause") mclock.pause();
    else if (a === "warp") { const w = mclock.setWarp(arg); if (!mclock.started || mclock.paused) mclock.play(); say(`Time warp, ${w} times.`, null, { priority: 4 }); }
    else if (a === "skip") { coach.did("time"); skipEvent(); return true; }
    else if (a === "ff") { const on = arg === true || arg === "on"; if (on) coach.did("time"); if (on && (!mclock.started || mclock.paused)) mclock.play(); mclock.hold(on); }
    if (cockpit && cockpit.clock) cockpit.clock(mclock.state);
    renderCard();
    return true;
  }
  // ---------- [polish 2] the pause menu, the chapter card, Restart shift (docs/MISSION_POLISH_SPEC.md) ----------
  let menuWas = false, chapterWas = false, chapterRec = null, chaptersSeen = 0;
  /** Esc at the seat, Start, voice "pause", the deck's Menu: the clock holds and the menu opens (again: it closes). */
  function openMenu() {
    if (screen !== "hud" || !state || state.over || !cockpit || !cockpit.menu || tour.active) return false;
    if (cockpit.chapterOpen) return false;
    if (cockpit.menuOpen) return closeMenu(true);
    nudge.heard(); coach.did("menu");
    menuWas = mclock.started && !mclock.paused;
    mclock.hold(false); mclock.pause();
    const c = (state.chapter || {}), t = state.mission_time_h || 0;
    cockpit.menu(true, { eye: `Day ${state.day} of 10${c.n ? ` · Chapter ${c.n} of ${c.of}: ${c.title}` : ""}`,
      shift: `Back to day ${Math.floor(t / 24) + 1}, shift ${Math.floor((t % 24) / 6) + 1}` });
    cockpit.clock(mclock.state);
    return true;
  }
  function closeMenu(resume = true) {
    if (!cockpit || !cockpit.menuOpen) return false;
    cockpit.menu(false);
    if (resume && menuWas) mclock.play();
    menuWas = false;
    cockpit.clock(mclock.state); renderCard();
    return true;
  }
  function menuAction(a, v) {
    if (a === "open") return openMenu();
    if (a === "resume") return closeMenu(true);
    if (a === "speed") { mclock.setWarp(+v); menuWas = true; cockpit.clock(mclock.state); return true; }   // picking a speed means "run at it"
    if (a === "restart") return restartShift();
    if (a === "end_shift") { closeMenu(true); endShift(); return true; }   // [0.4.1] moved off the console into the Menu
    if (a === "settings") { closeMenu(false); const A = window.__outpost && window.__outpost.a11y; if (A && A.open) A.open(true); return true; }
    if (a === "quit") { closeMenu(false); mclock.pause(); hub(); return true; }   // [polish 4] the real hub: Resume Day N (the save), or a new mission
    return false;
  }
  /** Back to the start of this shift: the server replays the mission's own inputs up to it (same storms, same tasks). */
  async function restartShift() {
    if (screen !== "hud" || !state || state.over || !client || !client.restartShift) return false;
    if (stepping) { try { await stepping; } catch (e) { /* reported below */ } }
    const g = gen; let r;
    try { await mclock.flush(); r = await client.restartShift(state.id); }
    catch (e) { if (alive(g)) capcom({ say: "CAPCOM can't reach the mission server." }); return true; }
    if (!alive(g)) return true;
    closeMenu(false); mclock.reset(); mclock.dropWarp();
    chaptersSeen = ((r.state.chapter && r.state.chapter.done) || []).length;
    prev = null; applyState(r.state, true);
    if (!mclock.started || mclock.paused) mclock.play();
    if (r.say) { capcom({ say: r.say }); say(r.say, null, { priority: 4 }); }
    renderCard();
    return true;
  }
  /** A chapter ended (the sim's "chapter" event, auto-saved on the server): stars, CAPCOM's line, Continue. */
  function showChapter(rec) {
    if (!cockpit || !cockpit.chapter) return;
    if (cockpit.menuOpen) closeMenu(false);
    chapterRec = rec; chapterWas = mclock.started && !mclock.paused;
    mclock.hold(false); mclock.pause(); cockpit.clock(mclock.state);
    cockpit.chapter(rec);
    radio("capcom", rec.capcom);
    say(`Chapter ${rec.n} done. ${rec.count} of 3 stars. ${rec.capcom}`, null, { priority: 4 });
  }
  function chapterGo() {
    if (!cockpit || !cockpit.chapterOpen) return false;
    const rec = chapterRec; cockpit.chapter(null); chapterRec = null;
    if (rec && rec.last) { showDebrief(); return true; }
    if (chapterWas || !mclock.started) mclock.play();
    chapterWas = false; cockpit.clock(mclock.state); renderCard();
    return true;
  }

  /** Skip to next event: the sim runs until something happens (at most a day), then the clock carries on. */
  async function skipEvent() {
    if (!state || state.over) return;
    // a clock step in flight: wait for it, never drop the press (a slow PC is posting steps most of the time)
    if (stepping) { try { await stepping; } catch (e) { /* the skip below reports a dead server */ } }
    if (!state || state.over) return;
    nudge.stop();
    if (cockpit) cockpit.busy(true);
    const g = gen; let r;
    try { await mclock.flush(); r = client.skip ? await client.skip(state.id) : await client.advance(state.id, 1); }
    catch (e) { if (alive(g)) capcom({ say: "CAPCOM can't reach the mission server." }); if (cockpit) cockpit.busy(false); return; }
    if (cockpit) cockpit.busy(false);
    if (!alive(g)) return;
    mclock.reset(); if (!mclock.started) mclock.play();
    applyLive(r);
    if (r.say && state && !state.over) { capcom({ say: r.say }); say(r.say); }
  }
  /** A button on the Now card: an order, a task press / choice, or a clock action. */
  function taskButton(b) {
    if (!b) return false;
    nudge.heard(); coach.did("now");
    if (b.offer != null) {   // [polish 3] CAPCOM's question on the Now card: answer it once, then the sim's job is back
      const o = offer; if (!o) return false;
      const a = o.actions[b.offer]; offer = null; decisionAt = 0;
      if (a && a.onClick) a.onClick();
      renderCard(); return true;
    }
    if (b.clock) return clockAction(b.clock === "warp" ? "warp" : b.clock, b.clock === "warp" ? 4 : undefined);
    if (b.cmd) { run(b.cmd); return true; }
    if (b.task) { run(b.task); return true; }
    return false;
  }
  /** "Do it" (Y, T, thumbs up, "yes" to the card's offer): the card's first button. */
  function doTaskStep() { const c = state && cardNow(); if (!c || !(c.buttons || []).length || c.choice) return false; return taskButton(c.buttons[0]); }
  /** "left", "the ridge", "shelter now": the card's choice that names it. */
  function pickChoice(label) {
    const c = state && cardNow(); if (!c || !c.choice) return false;
    const l = String(label || "").toLowerCase(), b = c.buttons.find(x => x.label.toLowerCase() === l) || (!c.free && c.buttons.find(x => l && x.label.toLowerCase().includes(l)));
    if (b) return taskButton(b);
    // [0.5 field] a describe / readback step: the words themselves go to the task ("a big round rock", "bag fourteen")
    if (c.free && l.trim() && c.step && c.task) { nudge.heard(); coach.did("now"); run({ type: "task", task: c.task, step: c.step.id, text: String(label) }); return true; }
    return false;
  }
  /** The Now card + the glow on its control + (Cadet) the one bright panel + the ack and the new-task line. */
  function renderCard() {
    if (!cockpit || !state || screen !== "hud") return;
    const c = tour.active ? null : cardNow();
    let done = false;
    if (state.ack && state.ack.n !== lastAck) {   // "Shields up. Good.": shown on the card, said once
      lastAck = state.ack.n; ackShown = state.ack.text; ackUntil = Date.now() + 4500; done = true;
      if (!tour.active) { radio("capcom", ackShown); say(ackShown, null, { priority: 4 }); }
    }
    const ack = Date.now() < ackUntil ? ackShown : null;
    if (cockpit.card) cockpit.card(c, { ack, cadet: levelNow() === "cadet" }); else if (cockpit.objective) cockpit.objective(c);
    if (tour.active) return;
    // [wave 5] an objective done (the sim's ack, or one more step of the same job): the Now card and its control pulse
    const pg = c && c.progress && c.task ? { task: c.task, done: c.progress.done } : null;
    if (!done && pg && lastProg && pg.task === lastProg.task && pg.done > lastProg.done) done = true;
    lastProg = pg || (c && c.task ? lastProg : null);
    if (done && cockpit.pulse) cockpit.pulse();
    cockpit.point(c ? c.target : null);
    cockpit.focus(c && levelNow() === "cadet" ? c.panel : null);
    const t = state.task;
    if (t && t.id !== lastTask) {   // a new job: its line once (the sim event's own line covers storms and windows)
      lastTask = t.id; if (t.say) { radio("capcom", t.say); say(t.say, null, { priority: 4 }); }
      nudge.arm(t.id);
    } else if (!t) lastTask = null;
    if (c && c.key !== lastObj) { lastObj = c.key; if ((c.buttons || []).length) nudge.arm(c.key); }
    autoPace(c);
  }
  // [polish a] auto-pace: a card that only waits (the crew sheltered, the rover driving, all steady) fast-forwards by
  // itself after AUTO_MS, instead of asking for "Skip ahead" / "Time warp" again and again. It never fires while the
  // clock is paused or held (a decision, a card, the tour) and restarts its wait whenever the card changes.
  function autoPace(c) {
    const ok = !!(c && c.auto && !tour.active && state && !state.over && mclock.started && !mclock.paused && !mclock.held);
    const k = ok ? c.key : "";
    if (k === autoKey && (autoT || !ok)) return;
    clearTimeout(autoT); autoT = 0; autoKey = k;
    if (!ok) return;
    autoT = setTimeout(() => {
      autoT = 0;
      const now = !tour.active && state && !state.over && screen === "hud" ? cardNow() : null;
      if (now && now.auto && now.key === autoKey && mclock.started && !mclock.paused && !mclock.held) { autoKey = ""; skipEvent(); }
    }, AUTO_MS);
  }

  // ---------- first-mission cabin tour (tour.js) ----------
  const tour = createTour({ host: cabinEl.parentNode || document.body, cockpit: () => cockpit, say: t => say(t), hush: () => stopSpeaking("mission_tour_hush"), callsign: () => callSign.get(),
    log: (event, source) => flowLog({ flow: "cabin_tour", event, source: source || "flow", step: tour ? tour.index : -1 }),
    onEnd: () => { if (screen !== "hud" || !state) return; lastObj = ""; render(); const ob = cardNow(); if (ob) say(ob.text, null, { priority: 4 }); nudge.arm(); } });
  // [polish 4] the first mission's in-place prompts (coach.js): "time" waits until the clock runs by itself
  const coach = createCoach({ host: cabinEl, callsign: () => callSign.get(),
    ready: id => !tour.active && screen === "hud" && !(cockpit && (cockpit.menuOpen || cockpit.chapterOpen)) && (id !== "time" || (mclock.started && !mclock.paused)),
    log: (event, step) => flowLog({ flow: "mission_coach", event, source: "flow", step: step || "" }) });
  /** Settings -> Help "Show me around", or "show me around" by voice: replay the tour in the cabin. */
  function replayTour() { if (screen !== "hud" || !cockpit) return false; nudge.stop(); coach.stop(); tour.start(band(levelNow())); return true; }
  addEventListener("outpost:tour", () => { if (!replayTour()) { try { localStorage.removeItem("outpost-tour-done:" + (callSign.get() || "cadet")); } catch (e) { /* blocked */ } } });
  const levelNow = () => (window.__outpost && window.__outpost.prefs && window.__outpost.prefs.level) || tier();
  /** Engineer flies Commander's band (the same missions, in real units): the tour and the hints follow the band. */
  const band = l => (l === "engineer" ? "commander" : l);
  /** "What do I do?": one spoken line for this screen (the cabin's comes from the objective). */
  function whatNow() {
    if (screen === "hud") { const c = state ? cardNow() : null; return c ? (c.offer ? c.text : nowSpoken(state, mclock.state)) : null; }
    if (screen === "brief") return HELP.picker;
    if (screen === "hub") return HELP.hub;
    if (screen === "plan") return HELP.briefing;
    if (screen === "gate") return GATE.say(callSign.spoken("Cadet"));
    if (screen === "practice_done") return GATE.doneSub;
    if (screen === "debrief") return HELP.debrief;
    return null;
  }
  /** The objective strip, the glow on its control and (Cadet) the one bright panel. Quiet while the tour runs. */
  let lastObj = "";
  function paintObjective() { renderCard(); }

  // ---------- cockpit (mission/cockpit.js): the console that replaced the HUD panel ----------
  function showHud() {
    nv.hide();
    screen = "hud"; debriefEl.hidden = true; panel.hidden = true; cabinEl.hidden = false; document.body.dataset.cabin = "1";
    dockOut();   // createCabin rewrites the cabin's HTML: lift the docked nodes out first
    if (cockpit && cockpit.dispose) cockpit.dispose();
    cockpit = createCabin(cabinEl, {
      badges,
      onCommand: c => run(c),
      onHouston: () => callHouston(),
      onView: v => windowView(v),
      onEndShift: () => endShift(),
      onDebrief: () => showDebrief(),
      onClock: a => { const [k, v] = String(a).split(":"); clockAction(k, v); },
      onMenu: (a, v) => menuAction(a, v),
      onChapter: () => chapterGo(),
      onTask: b => taskButton(b),
      onWhy: c => sayWhy(c),
      level: () => levelNow(),
      onSystems: () => {},
    });
    mclock.attach(); cockpit.clock(mclock.state);
    dockIn();
    // the Sample / Practice tags ride in the deck (at the bottom right they sat on the voice bar)
    const deckEl = cabinEl.querySelector(".cb-deck .cb-clock");
    if (client && client.sample) (deckEl ? deckEl.insertAdjacentHTML("afterend", sampleTag()) : cabinEl.insertAdjacentHTML("afterbegin", sampleTag()));
    if (practice) { const tag = `<span class="m-sample m-practice" title="${esc(GATE.sub)}">${esc(GATE.tag)}</span>`; deckEl ? deckEl.insertAdjacentHTML("afterend", tag) : cabinEl.insertAdjacentHTML("afterbegin", tag); }
    requestAnimationFrame(() => { const w = cabinEl.querySelector(".cb-hole") || cabinEl.querySelector(".cb-glass"), r = w && w.getBoundingClientRect(), sr = cabinEl.getBoundingClientRect();
      if (r && sr.height) globe.setViewport((r.bottom - sr.top) / sr.height); windowView(cockpit.view || "site"); });
    logHistory.forEach(l => cockpit.log(l.who, l.text));
    if (cockpit.missionLog) cockpit.missionLog(state && state.mission_log);
    if (windows && cockpit.setWindows) cockpit.setWindows(windows);
    render();
  }
  function render() {
    if (screen !== "hud" || !state || !cockpit) return;
    const s = state, e = s.env || {}, rv = s.rover || {};
    cockpit.update(s);
    if (cockpit.missionLog) cockpit.missionLog(s.mission_log);
    paintObjective();
    (s.alerts || []).forEach(a => { if (CALLBACKS[a]) { seen.add(a); remind(a); } });
    renderBanner();
    globe.mission.setSun(+e.sun_elev_deg || 0, s.mission_time_h || 0); globe.mission.setEarth(+e.earth_elev_deg || 0);
    const tgt = rv.busy ? TARGETS[rv.task] : null, total = rv.task === "collect_ice" ? 10 : rv.task === "explore" ? 8 : 5;
    globe.mission.setRover(tgt, tgt ? Math.sin(Math.PI * (1 - (rv.eta_h || 0) / total)) : 0);
    syncSurface();
  }
  // ---------- "Why?" cards (docs/PHYSICS.md): the physics behind a gauge, one number, its source ----------
  /** The gauge a bare "why?" (or the I key) is about: the lit panel, then the Now job, then what is alarming. */
  const PANEL_GAUGE = { power: "battery", displays: "battery", habitat: "life_support", radiation: "dose", rover: "rover", comm: "power" };
  const TASK_GAUGE = { storm_prep: "dose", storm_hit: "dose", all_clear: "dose", night_prep: "heaters", sunrise: "power", low_power: "battery",
    life_check: "life_support", ice_run: "rover", repair: "power", first_power: "shields", comm_window: "battery", science: "dose" };
  function whyGauge() {
    if (cockpit && cockpit.systemsGauge) return cockpit.systemsGauge;   // [systems] the drawer's panel (or its focused (i))
    const lit = cockpit && (cockpit.highlighted || (cockpit.panel && cockpit.panel !== "seat" ? cockpit.panel : null));
    if (lit && PANEL_GAUGE[lit]) return PANEL_GAUGE[lit];
    const t = state && state.task; if (t && TASK_GAUGE[t.kind]) return TASK_GAUGE[t.kind];
    const a = (state && state.alerts) || [];
    if (a.some(x => /dose|storm/.test(x))) return "dose";
    if (a.includes("low_power")) return "battery";
    if (a.includes("life_support_low")) return "life_support";
    return "power";
  }
  /** CAPCOM reads the card (<= 20 words, numbers with their units); the caption shows the on-screen form. */
  function sayWhy(c) { if (!c) return; radio("capcom", c.text); Promise.resolve(say(c.say)).catch(() => {}); }
  function openWhy(gauge, from) {
    if (screen !== "hud" || !cockpit || !cockpit.why) return false;
    const c = cockpit.why(gauge || whyGauge(), from); if (!c) return false;
    sayWhy(c); return true;
  }
  /** Radio log lines survive re-renders of the cockpit. */
  function radio(who, text) { if (!text) return; if (who === "kid") nudge.heard(); logHistory.push({ who, text }); logHistory = logHistory.slice(-12);
    // [polish 3] CAPCOM and the Now card never repeat each other on screen: a line that is the card's own words goes to
    // the radio log only (the caption line keeps what is new)
    const c = who === "capcom" && screen === "hud" && state && !tour.active ? cardNow() : null;
    const flat = t => String(t || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
    if (cockpit && screen === "hud") cockpit.log(who, text, !!(c && flat(c.text) && flat(text).endsWith(flat(c.text))));
  }
  /** The Call Houston push button: the real Director in a live mission, the local practice line otherwise. */
  async function callHouston() {
    if (!state) return;
    radio("kid", "Houston, Outpost Luna. Radio check.");
    if (client.sample || !askDirector) { await houston(`Houston here. We copy you, ${rank()}. Keep the crew safe and the lights on.`, 2600); return; }
    if (cockpit) cockpit.calling(true);
    await askDirector("Call Houston");
  }
  /** Alerts in the cabin: the storm strip comes from the state (cabin.js); short warnings go through here. */
  function renderBanner(transient) {
    banner.hidden = true;
    if (transient && cockpit && screen === "hud") cockpit.alert(transient);
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
    if (screen === "off") return;   // the CAPCOM card belongs to Mission (QA-20)
    const s = state;
    // A confirmation the Director is holding (e.g. another officer must agree) is answered through the Director;
    // one the sim asked for directly goes to the sim.
    const answer = yes => (viaDirector && askDirector) ? askDirector(yes ? "yes" : "no") : run({ type: yes ? "confirm" : "cancel" });
    const actions = confirm ? [
      { label: "Yes", hot: true, once: true, onClick: () => answer(true) },
      { label: "No", once: true, onClick: () => answer(false) }] : [];
    if (confirm && screen === "hud") {   // [polish 3] the yes / no is the Now card (the window shows no second card)
      setOffer({ confirm: true, title: NOW.confirmTitle, text: line || readback || NOW.confirm, level: "caution", panel: panelFor({}, line || readback),
        actions: [{ label: "Yes", onClick: () => answer(true) }, { label: "No", onClick: () => answer(false) }] });
      radio("capcom", line || readback); return;
    }
    if (confirm) decisionAt = Date.now();
    card.show({ title: "CAPCOM", eyebrow: eyebrow || [s ? `Day ${s.day} · shift ${s.shift}` : "Mission", client && client.sample ? "Sample data" : ""].filter(Boolean).join(" · "),
      say: line || readback || "", actions });
    if (screen === "hud" && !/^Houston/.test(eyebrow || "")) radio("capcom", line || readback);
  }

  async function run(command, { spoken } = {}) {
    if (!state) return;
    nudge.heard(); decisionAt = 0; offer = null;   // any order answers (or overrides) CAPCOM's question
    coach.did("now");
    if (command.type === "end_shift") return endShift();
    if (command.type === "skip") return skipEvent();
    let r;
    const g = gen;
    try { r = await client.command(state.id, command); } catch (e) { if (alive(g)) capcom({ say: "CAPCOM can't reach the mission server." }); return; }
    if (!alive(g)) { if (r && r.state) state = r.state; return; }   // QA-20: left Mission while the order ran
    applyState(r.state);
    const res = r.result || {};
    pending = res.needs_confirm ? command : null;
    // [playtest 3] time plays itself after an order: a resumed mission's clock (ready, never started) starts on the
    // kid's first order too, not only a new mission's (applyState covers hour 0)
    if (res.ok !== false && !res.needs_confirm && screen === "hud" && state && !state.over && !mclock.started && !tour.active) mclock.play();
    capcom({ say: res.say || res.readback, confirm: !!res.needs_confirm });
    handleEvents(res.events || []);
    if (spoken || res.needs_confirm || command.type === "query" || !res.ok) await say(res.say || res.readback);
    if (alive(g) && r.state && r.state.over) showDebrief();
  }

  async function endShift() {
    if (!state || state.over) return;
    nudge.stop();
    if (session && !client.sample && session.endShift && session.endShift(state)) return;   // [session hook]
    if (cockpit) cockpit.busy(true);
    let r;
    const g = gen;
    try { r = await client.advance(state.id, 1); } catch (e) { if (alive(g)) capcom({ say: "CAPCOM can't reach the mission server." }); if (cockpit) cockpit.busy(false); return; }
    if (!alive(g)) { if (r && r.state) { prev = state; state = r.state; } return; }   // QA-20: the shift ended while away
    prev = state; applyState(r.state, true);
    const evs = r.events || [];
    mclock.reset(); if (!mclock.started) mclock.play();
    capcom({ say: r.say });
    handleEvents(evs); story(evs);
    if (cockpit) cockpit.busy(false);
    if (practice && !state.over && (state.mission_time_h || 0) >= PRACTICE_H) { practiceDone(); return; }
    if (state.over) { showDebrief(); return; }
    say(r.say);
  }

  function applyState(s, keepPrev) { if (!s) return;
    { // [polish 2] a chapter just ended (on any path: the clock, a skip, an order, an end-shift, the session): its card
      const done = (s.chapter && s.chapter.done) || [];
      if (done.length > chaptersSeen) { const rec = done[done.length - 1]; chaptersSeen = done.length;
        if (!s.over && !practice) setTimeout(() => { if (screen === "hud" && state && !state.over) showChapter(rec); }, 0); } } if (testForce && s.env) { s.env.storm = testForce.storm; s.alerts = [...new Set([...(s.alerts || []), "dose_rate_high"])]; }
    if (!keepPrev && state) prev = prev || state; state = s;
    // [polish wave 2] time plays itself: the first order of the mission starts the clock (no separate "press Play" job)
    if (screen === "hud" && !mclock.started && !tour.active && !s.over && (s.mission_time_h || 0) === 0 && s.acted && s.acted.allocate) mclock.play();
    render(); pushContext(); }

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
    feel(evs);
    evs.forEach(e => { if (CALLBACKS[e.kind]) seen.add(e.kind); });
    const cbk = evs.map(e => e.kind).find(k => CALLBACKS[k] && !reminded.has(k));
    if (cbk) { const line = remind(cbk); if (line) setTimeout(() => { if (screen === "hud") say(line, { situation: "coach" }); }, 2500); }
    const storm = evs.find(e => e.kind === "solar_storm");
    if (storm) { alertSound(); stormAlert(); return; }
    const alarm = evs.find(e => e.kind === "low_power" || e.kind === "dose_alert");
    if (alarm) { alertSound(); const t = alarm.kind === "low_power" ? "Low power" : "High dose"; renderBanner({ level: alarm.kind === "low_power" ? "caution" : "warn", title: t, text: alarm.text }); a11yAlert(`${t}. ${alarm.text || ""}`); return; }
    const comm = evs.find(e => e.kind === "comm_open" || e.kind === "comm_closed");
    if (comm) renderBanner({ level: "info", title: comm.kind === "comm_open" ? "Earth in view" : "Earth set", text: comm.text });
  }

  /** [0.6] Haptics (haptics.js): the controller's rumble / the tablet's vibration with the moments the cabin already
   *  shows and sounds: storm warning (short; the alert strip), storm hit (long; the alarm), the boulder field (bump; the
   *  steer card), rover home (two taps; CAPCOM's line). Settings "Vibrate for alerts" and "Less motion" apply. */
  function feel(evs) { const k = momentOf(evs); if (k) { try { buzz(k); } catch (e) { /* no haptics here */ } } }
  function stormAlert() {
    const st = state && state.env && state.env.storm;
    a11yAlert(`Solar storm${st && st.real_date ? `, a real event from ${st.real_date}` : ""}. Take shelter or raise the shields.`);
  }
  /** Houston: show the signal travelling (each way) and wait the real round trip before speaking. */
  async function houston(line, delayMs = 2600, style = null) {
    const oneWay = (delayMs / 2000).toFixed(1);
    void oneWay;
    const g = gen;
    if (!alive(g)) return;
    capcom({ say: CAPCOM.houstonCalling, eyebrow: "Houston · radio delay" });
    if (cockpit) cockpit.calling(true, delayMs);
    await new Promise(r => setTimeout(r, delayMs));
    if (cockpit) cockpit.calling(false);
    if (!alive(g)) return;   // QA-20: Houston never answers over another mode
    capcom({ say: line, eyebrow: "Houston" }); radio("houston", line);
    // Owner decision: one voice in the app, so CAPCOM relays Houston ("Houston says: ..."), after a radio beep. The card's
    // eyebrow and the radio log still say Houston, so it is clear where the message came from.
    try { radioBeep(); } catch (e) { /* no Web Audio */ }
    await new Promise(r => setTimeout(r, 300));
    if (!alive(g)) return;
    await say(houstonRelay(line), style && style.voice === "houston" ? { ...style, voice: "capcom" } : style);
  }

  // ---------- voice ----------
  /** Text the kid said in mission mode. Returns true if handled here (mock command layer). */
  async function handleText(text) {
    if (!state || screen !== "hud") return false;
    // no session (the /api/ask fallback): the tour and "what do I do?" still work by voice and typing
    const w = String(text).toLowerCase().replace(/[^a-z ]/g, "").trim();
    if (tour.active && /^(next|yes|ok|okay|go on|got it)$/.test(w)) { tour.next(); return true; }
    if (tour.active && /^(skip|skip (the )?tour|no)$/.test(w)) { tour.end(false); return true; }
    if (/^(show me around|give me the tour)$/.test(w)) return replayTour();
    if (/^(help|what do i do( now| next)?|what should i do|im lost|i am lost)$/.test(w)) return nav("help");
    if (/^(skip|jump)( ahead| forward| to (the )?next( event| thing| job)?)$|^fast forward$|^next event$/.test(w)) { radio("kid", text); await skipEvent(); return true; }
    // [polish 2] "pause" opens the pause menu (it holds the clock); "pause the clock" only holds it
    if (/^(pause|pause( the)? game|pause it|time out|menu|(open )?(the )?(pause )?menu)$/.test(w)) { radio("kid", text); return openMenu("voice"); }
    if (/^(pause|stop|freeze|hold)( the)?( clock| time| game)?$|^pause it$|^time out$/.test(w) && w !== "stop") { radio("kid", text); return clockAction("pause"); }
    if (/^((start|resume|run|unpause)( the)? (clock|time)|resume|unpause|play)$/.test(w)) { radio("kid", text); if (cockpit && cockpit.menuOpen) return closeMenu(true); return clockAction("play"); }
    if (/^restart( the)? shift$/.test(w)) { radio("kid", text); return restartShift(); }
    { const m = w.match(/^(time ?warp|warp)( speed)?( (one|two|four|1|2|4))?( x| times)?$/); if (m) { radio("kid", text); return clockAction("warp", { one: 1, two: 2, four: 4 }[m[4]] || (m[4] ? +m[4] : undefined)); } }
    if (/^(do it|go|ok do it|lets do it)$/.test(w) && doTaskStep()) { radio("kid", text); return true; }
    if (/^(center|centre|recenter|recentre|look forward|look ahead|face forward|(center|centre|reset) (the )?view)$/.test(w) && cockpit && cockpit.recenter) { cockpit.recenter(); return true; }
    { const c = cardNow();   // a choice: the option the words name ("left", "the ridge", "shelter now")
      if (c && c.choice && w && w.split(" ").length <= 4) {
        const hit = c.buttons.filter(b => { const lw = b.label.toLowerCase(); return w.split(" ").some(x => x.length > 2 && lw.split(/[^a-z]+/).includes(x) &&
          !c.buttons.every(o => o.label.toLowerCase().split(/[^a-z]+/).includes(x))); });
        if (hit.length === 1) { radio("kid", text); taskButton(hit[0]); return true; } } }
    radio("kid", text);
    { const sw = systemWord(text); if (sw) return systemsAct(sw.close ? "close" : sw.step ? (sw.step > 0 ? "next" : "prev") : sw.open) !== false; }
    if (panelWord(text)) return true;
    const tl = text.toLowerCase(), vw = VIEW_WORDS.find(([re]) => re.test(tl));
    if (vw && cockpit) { cockpit.setView(vw[1]); return true; }
    if (!client.sample) return false;          // the real Director parses commands
    const c = parseCommand(text); if (!c) return false;
    if (c.type === "call_houston") { await houston(`Houston here. We copy you, ${rank()}. Keep the crew safe and the lights on.`, 2600); return true; }
    if (c.type === "end_shift") { await endShift(); return true; }
    await run(c, { spoken: true }); return true;
  }
  /** A Director answer with a mission action. Returns true if handled. */
  async function handleDirector(r) {
    if (!r || !state || screen === "off") return false;   // a Director reply that lands after the kid left Mission
    if (r.action === "command" && r.command) {
      nudge.stop();
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
    if (state && s.mission_time_h !== state.mission_time_h) nudge.heard();   // a shift ended through the session Director
    // any order applied through the session Director (loads, shelter, rover, night mode) stops the first-shift nudge
    if (state && (JSON.stringify(s.loads) !== JSON.stringify(state.loads) || s.shelter !== state.shelter || s.power_save !== state.power_save
      || JSON.stringify(s.rover) !== JSON.stringify(state.rover))) { nudge.heard(); decisionAt = 0; if (offer && !offer.confirm) offer = null; }
    const st0 = state;
    if (st0 && s.env && s.env.storm && s.env.storm.active && !(st0.env.storm && st0.env.storm.active)) handleEvents([{ kind: "solar_storm" }]);
    (s.alerts || []).forEach(a => { if (a === "low_power" || a === "life_support_low") seen.add(a); });
    if (state && s.mission_time_h !== state.mission_time_h) { prev = state; applyState(s, true); } else applyState(s);
    if (s.over) showDebrief();
  }
  function alert(d) {
    if (screen !== "hud") return;   // alerts belong to the cabin; never over the briefing or the debrief
    if (d.level !== "info") { alertSound(); a11yAlert(d.text); }
    renderBanner({ level: d.level === "critical" ? "warn" : d.level === "warn" ? "caution" : "info", title: d.level === "critical" ? "Alert" : d.level === "warn" ? "Caution" : "Update", text: d.text });
  }
  /** A CAPCOM card from a decision: body, chips, and actions whose clicks go back through `send`. */
  /** Cadet (7–9) or Commander (10–12): Settings / the learning design's difficulty band. Commander is the default. */
  const tier = () => { try { if (localStorage.getItem("outpost-tier") === "cadet") return "cadet"; return (JSON.parse(localStorage.getItem("outpost-prefs") || "{}").level === "cadet") ? "cadet" : "commander"; } catch (e) { return "commander"; } };
  /** Which panel an offer belongs to (the Director may name it: d.panel). */
  const PANEL_OF = [[/shelter|storm|shield|radiation|dose/i, "radiation"], [/rover|ice|explore|repair/i, "rover"], [/houston|radio|comm|earth/i, "comm"],
    [/heater|greenhouse|life support|air/i, "habitat"], [/power|battery|science|sunset|night/i, "power"]];
  const panelFor = (d, text) => d.panel || (PANEL_OF.find(([re]) => re.test(text || "")) || [])[1] || null;
  /** An offer the live clock has already overtaken (held on the voice floor while time ran): a storm offer with no storm
   *  and no warning any more, a night-mode offer with night mode on. Showing it would contradict the Now card. */
  function staleOffer(d) {
    const s = state; if (!s || !(d.actions || []).length) return false;
    const e = s.env || {}, text = [d.title, d.body, ...(d.chips || []), ...(d.actions || []).map(a => a.label)].join(" ");
    if (/storm|shelter|shields/i.test(text) && !(e.storm && e.storm.active) && !(e.warning || e.storm_warning)) return true;
    if (/night mode/i.test(text) && s.power_save) return true;
    return false;
  }
  /** [playtest 16] An offer's storm orders the crew has already carried out (in the shelter; shields at 40 or more). */
  const doneAction = a => { const s = state || {}, l = String((a && a.label) || "");
    return (/shelter/i.test(l) && !/out|leave/i.test(l) && !!s.shelter) || (/shields/i.test(l) && (!!s.shelter || ((s.loads || {}).shields || 0) >= 40)); };
  function showCard(d, send) {
    const s = state;
    if (staleOffer(d)) return;   // the moment passed while the clock ran; the Now card has the current job
    if ((d.actions || []).length && screen === "hud" && /storm|shelter|shields/i.test([d.title, d.body, ...(d.chips || [])].join(" "))) {
      // [playtest 16] never ask for what's done: drop the done orders; all done (or only "wait" left) -> "You're ready"
      const left = d.actions.filter(a => !doneAction(a));
      if (left.length < d.actions.length) {
        if (!left.some(a => /shelter|shields/i.test(a.label))) { radio("capcom", NOW.stormReady); return; }
        d = { ...d, actions: left };
      }
    }
    if ((d.actions || []).length && screen === "hud") {   // [polish 3] an offer in the cabin is the Now card, nothing else
      const text = d.body || d.asked || "";
      // the title names the event (the Director's first chip: "Solar storm"), the text is its line, the buttons its choices
      const title = (d.chips || []).find(x => typeof x === "string" && x) || (d.title && d.title !== "CAPCOM" ? d.title : NOW.confirmTitle);
      setOffer({ d, title, text, panel: panelFor(d, [d.title, text].join(" ")),
        level: /storm|shelter|radiation|dose/i.test(text) ? "warn" : "caution", actions: d.actions.map(a => ({ label: a.label, onClick: () => send(a.send) })) });
      if (text) radio("capcom", text);
      return;
    }
    if ((d.actions || []).length) decisionAt = Date.now();   // an offer is a decision: the clock waits (up to 30 s)
    card.show({ title: d.title || "CAPCOM", asked: d.asked || "", say: d.body || "", arc: d.arc || "",
      eyebrow: [d.hint ? "Heads up" : d.nudge ? "Coach" : "", s ? `Day ${s.day} · shift ${s.shift}` : "Mission"].filter(Boolean).join(" · "),
      actions: (d.actions || []).map(a => ({ label: a.label, hot: true, once: true, onClick: () => send(a.send) })) });
  }
  function askConfirm(d, send) {
    pending = { type: "confirm" }; decisionAt = Date.now();
    if (screen === "hud") {   // [polish 3] the Now card asks it
      setOffer({ confirm: true, d, title: NOW.confirmTitle, text: d.text || "Are you sure?", panel: panelFor(d, d.text),
        actions: [{ label: "Yes", onClick: () => { pending = null; send(d.yes); } }, { label: "No", onClick: () => { pending = null; send(d.no); } }] });
      return;
    }
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
  /** One headline, a shift-by-shift chart, up to three takeaways with sources, then Fly again / Another site. */
  let debriefKey = "";
  async function showDebrief() {
    if (!state) return;
    // [qa] one debrief per outcome: telemetry and the order reply can both report "over"; don't re-fetch and re-speak
    const key = `${state.id}:${state.over ? "over" : state.day}`;
    if (screen === "debrief" && key === debriefKey && !fakeDebrief) return;
    debriefKey = key;
    screen = "debrief"; panel.hidden = true; banner.hidden = true; hideCabin(); card.hide();
    // [qa] a loading line while it's fetched (no blank screen), and a real error state with Retry (no "Grade ?")
    debriefEl.hidden = false; debriefEl.classList.add("mx-debrief");
    debriefEl.innerHTML = `<p class="mx-empty" role="status">Loading your debrief…</p>`;
    let d; if (fakeDebrief) { d = fakeDebrief; fakeDebrief = null; } else try { d = await client.debrief(state.id); } catch (e) { d = null; }
    if (screen !== "debrief" || !state) return;   // [qa] left while it loaded
    if (!d) {
      debriefKey = "";
      debriefEl.innerHTML = `<header class="mx-head"><span class="eyebrow">Debrief · ${esc(state.site.name)}</span></header>
        <div class="mx-db-top"><div><h2 class="mx-title">Debrief not ready</h2><p class="mx-sub">Couldn't load it. Try again.</p></div></div>
        <div class="mx-foot"><button type="button" class="mx-go" id="mDbRetry">Try again</button><button type="button" class="mx-btn" id="mNewSite">${esc(DEBRIEF.another)}</button></div>`;
      $("mDbRetry").onclick = () => showDebrief();
      $("mNewSite").onclick = () => { if (unsub) unsub(); unsub = null; state = null; picker(); };
      return;
    }
    const outcome = d.outcome || state.outcome || (state.over ? "" : "in_progress");
    const paused = outcome === "in_progress" || !outcome;
    const won = outcome === "survived" || outcome === "success";
    const head = won ? "Mission complete" : paused ? "Mission paused" : "Mission over";
    // [campaign] a win opens the next mission (kept per call sign); the debrief says which, under the result
    const cmNow = campaignList.find(x => state.campaign && x.id === state.campaign.id), before = openCount();
    if (won && cmNow && !practice) CM.markWon(cmNow.id, callSign.get());
    const opened = won && openCount() > before ? campaignList[openCount() - 1] : null;
    const sub = paused ? `Day ${state.day} of 10. Your outpost is waiting.` : [firstSentence(d.why), opened ? CAMPAIGN.unlocked(opened.n, opened.title) : ""].filter(Boolean).join(" ");
    (d.timeline || []).forEach(t => (t.events || []).forEach(k => { if (CALLBACKS[k]) seen.add(k); }));
    // takeaways: the debrief's own lessons first (each with its source), then Flight School lessons that came back
    // [qa] at most two data lessons, so a Flight School callback or the "Next time" tip still gets a slot of the three
    const tks = (d.lessons || []).filter(l => l && l.text && !/Artemis III/i.test(l.text)).slice(0, 2).map(l => ({ text: takeaway(l.text), source: l.source }));
    [...new Set([...seen].map(k => CALLBACKS[k].lesson))].forEach(id => { const k = [...seen].find(x => CALLBACKS[x].lesson === id); tks.push({ text: takeaway(callbackTakeaway(k)), source: null, lesson: CALLBACKS[k].n }); });   // [QA-65] a whole sentence, not "Battery's low."
    const story = debriefStory(d, state);   // the mission as a story: three beats, what to try next, one clear choice
    if (!tks.length) lessons().forEach(l => tks.push({ text: takeaway(l.text), source: { ...l.source, title: l.name } }));
    // [qa] "DONKI 2017-09-04T23:52:00-SEP-001 (NASA CCMC)" → "NASA DONKI, 2017-09-04"; a colon in a time is not a break
    const srcLabel = s => { const t = String((s && s.title) || "").trim(); if (!t) return "Source";
      const dk = t.match(/^DONKI\s+(\d{4}-\d{2}-\d{2})/); if (dk) return `NASA DONKI, ${dk[1]}`;
      return t.split(/[,(]|:\s/)[0].trim() || "Source"; };
    // [physics] story first, then the numbers behind it (cause -> effect, with sources), then the grade
    const nums = (d.numbers || []).filter(n => n && n.text).slice(0, 5), eng = !!(d.engineer || state.engineer);
    // [polish 4] stars first (big), then the grade; one primary (Next mission when won, else Fly again) that is always
    // on screen: the foot sits under the hero, the story / numbers / chart scroll in the body (never the buttons)
    const stars = d.stars != null ? Math.max(0, Math.min(3, +d.stars || 0)) : null;
    const starsHtml = stars != null && !paused ? `<p class="mx-bigstars" role="img" aria-label="${esc(DEBRIEF.starsLabel(stars))}">${[0, 1, 2].map(k => `<span class="${k < stars ? "is-on" : ""}" style="--i:${k}">${ic("star", 40)}</span>`).join("")}</p>` : "";
    const scoreHtml = `<dl class="mx-score">${paused ? "" : `<div><dt>Grade</dt><dd class="mx-grade">${esc(d.grade)}</dd></div>`}<div><dt>Score</dt><dd>${Math.round(d.score || 0)}</dd></div></dl>`;
    const primary = paused ? "resume" : won ? "next" : "again";
    const btn = (id, cls, label) => `<button type="button" class="${cls}" id="${id}">${esc(label)}</button>`;
    const foot = paused ? btn("mAgain", "mx-go", DEBRIEF.resume) + btn("mNewSite", "mx-link", DEBRIEF.choiceNew)
      : won ? btn("mNext", "mx-go", DEBRIEF.next) + btn("mAgain", "mx-btn", DEBRIEF.choiceAgain)
        : btn("mAgain", "mx-go", DEBRIEF.choiceAgain) + btn("mNext", "mx-btn", DEBRIEF.next);
    debriefEl.hidden = false; debriefEl.classList.add("mx-debrief");
    debriefEl.dataset.primary = primary;
    debriefEl.innerHTML = `
      <header class="mx-head"><span class="eyebrow">Debrief · ${esc(state.site.name)}</span>${sampleTag()}
        <button class="mx-x" id="mDbClose" type="button" aria-label="${esc(DEBRIEF.close)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button></header>
      <div class="mx-db-top mx-db-hero">
        ${starsHtml}
        <div class="mx-db-head"><h2 class="mx-title">${head}</h2>${sub ? `<p class="mx-sub">${esc(sub)}</p>` : ""}</div>
        ${scoreHtml}
      </div>
      <div class="mx-foot">${foot}
        ${nums.length ? `<button type="button" class="mx-link" id="mNums">${esc(DEBRIEF.numbers)}</button>` : ""}</div>
      <div class="mx-db-body">
        <section class="mx-story" aria-label="${esc(DEBRIEF.storyTitle)}"><h3>${esc(DEBRIEF.storyTitle)}</h3>
          <ul class="mx-checks">${story.checks.map(c => `<li class="${c.ok ? "is-ok" : "is-no"}"><span class="mx-ck" aria-hidden="true">${ic(c.ok ? "check" : "close", 18)}</span><span class="sr-only">${c.ok ? "Done: " : "Not yet: "}</span>${esc(c.text)}</li>`).join("")}</ul>
          <p class="mx-try"><b>${esc(DEBRIEF.tryTitle)}</b> ${esc(story.tryLine)}</p></section>
        <details class="mx-grown" id="mxGrown"><summary>${esc(DEBRIEF.grownups)}</summary>
        ${nums.length ? `<section class="mx-nums" id="mxNums" tabindex="-1" aria-label="${esc(DEBRIEF.numbersTitle)}"><h3>${esc(DEBRIEF.numbersTitle)}</h3>
          <ul>${nums.map(n => `<li><span>${esc(n.text)}${eng && n.eq ? `<code class="mx-eq">${esc(n.eq)}</code>` : ""}</span>${n.source ? srcLink(n.source, srcLabel(n.source)) : ""}</li>`).join("")}</ul></section>` : ""}
        ${chart(d.timeline || [], state.resources.dose_limit_msv || 50)}
        ${breakdown(d)}
        ${nums.length ? "" : `<ul class="mx-tks">${tks.slice(0, 3).map(t => `<li><span>${esc(t.text)}</span>${t.source ? srcLink(t.source, srcLabel(t.source)) : t.lesson ? `<span class="mx-tag">Lesson ${t.lesson}</span>` : t.next ? `<span class="mx-tag">Next time</span>` : ""}</li>`).join("")}</ul>`}
        ${(d.data_used || []).length ? `<details class="mx-data"><summary>Data used</summary><ul>${d.data_used.map(x => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a></li>`).join("")}</ul></details>` : ""}
        </details>
      </div>`;
    $("mAgain").onclick = () => { if (paused && state && !state.over) { showHud(); return; } if (unsub) unsub(); state = null; start(); };
    if ($("mNext")) $("mNext").onclick = () => nextMission();
    if ($("mNewSite")) $("mNewSite").onclick = () => leaveMission(() => { if (unsub) unsub(); state = null; picker(); });
    if ($("mNums")) $("mNums").onclick = () => { const g = $("mxGrown"); if (g) g.open = true; const n = $("mxNums"); if (n) { n.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" }); n.focus({ preventScroll: true }); } };
    $("mDbClose").onclick = () => { if (state && !state.over) showHud(); else hub(); };
    wireChart();
    requestAnimationFrame(() => { const h = debriefEl.querySelector(".mx-title"); if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); } });
    // [qa] no "Nice flying" on a failed mission
    const line = cs => paused ? `${head}.` : `${head}. ${(won ? DEBRIEF.grade : DEBRIEF.gradeOver || DEBRIEF.grade)(cs, d.grade, Math.round(d.score || 0))}`;
    // Hands-free: one short offer, spoken once; "fly again" / "yes" takes it (screen().offer). A typed name is never spoken.
    // QA-21: every failure reply already ends "… Mission over." (the order reply or the shift line, just spoken):
    // the debrief doesn't say it again, it goes straight to the grade.
    const T = (window.__outpost && window.__outpost.transcript) || [];
    const saidOver = T.slice(-4).some(e => e.who !== "kid" && Date.now() - (e.t || 0) < 20000 && /\bmission over\b/i.test(e.text || ""));
    const spoken = cs => (head === "Mission over" && saidOver && !paused) ? line(cs).replace(/^Mission over\.\s*/, "") : line(cs);
    // three short lines: the result, the story's turning point, then what to try and the one offer
    radio("capcom", line(callSign.shown()));
    // story first: the turning point and its biggest number, then the grade, then what to try and the one offer
    const top = !paused && nums.length && nums[0].say ? [nums[0].say] : [];
    Promise.resolve(say(paused ? [spoken(callSign.spoken()), `${story.end} ${OFFER.resume}`]
      : nums.length ? [story.beats[1], ...top, spoken(callSign.spoken()), `${story.tryLine} ${won ? OFFER.nextMission : OFFER.flyAgain}`]
        : [spoken(callSign.spoken()), story.beats[1], `${story.tryLine} ${won ? OFFER.nextMission : OFFER.flyAgain}`])).catch(() => {});   // one on-air span
  }

  /** QA-26: a paused mission is never wiped by accident. Fly again / a new site from a paused debrief asks first. */
  function leaveMission(go) {
    if (!(state && !state.over)) { go(); return; }
    const box = debriefEl.querySelector(".mx-foot"); if (!box) { go(); return; }
    box.querySelectorAll(".mx-wipe").forEach(n => n.remove());
    const w = document.createElement("div"); w.className = "mx-wipe"; w.setAttribute("role", "alertdialog"); w.setAttribute("aria-label", DEBRIEF.wipeAsk);
    w.innerHTML = `<p>${esc(DEBRIEF.wipeAsk)}</p><button type="button" class="mx-btn" data-w="no">${esc(DEBRIEF.wipeNo)}</button><button type="button" class="mx-link" data-w="yes">${esc(DEBRIEF.wipeYes)}</button>`;
    box.prepend(w); pendingWipe = go;
    w.querySelector('[data-w="no"]').onclick = () => { pendingWipe = null; w.remove(); };
    w.querySelector('[data-w="yes"]').onclick = () => { pendingWipe = null; w.remove(); go(); };
    w.querySelector('[data-w="no"]').focus({ preventScroll: true });
    say(DEBRIEF.wipeAsk);
  }
  let pendingWipe = null;
  /** [polish 4] Next mission: [campaign] the next mission in the campaign (just opened by this win), on the hub; after the
   *  last one, or without a campaign, the next site in the list. */
  function nextMission() {
    const go = () => { if (unsub) unsub(); unsub = null; const cur = state && state.site ? state.site.id : site && site.id;
      const curCm = state && state.campaign ? state.campaign.id : cm && cm.id; state = null;
      const ci = campaignList.findIndex(x => x.id === curCm), nx = ci >= 0 ? campaignList[ci + 1] : null;
      if (nx && openCount() > ci + 1) { pickMission(nx); hub(); return; }
      cm = campaignList[0];
      const i = sites.findIndex(x => x.id === cur); site = sites.length ? sites[(i + 1) % sites.length] : site; hub(); };
    leaveMission(go); return true;
  }

  /** Score breakdown, when the debrief sends one (the game redesign): [{label, points}] or {label: points}. */
  function breakdown(d) {
    const b = d.score_breakdown || d.breakdown; if (!b) return "";
    const rows = Array.isArray(b) ? b.map(r => [r.label || r.name, r.points ?? r.value]) : Object.entries(b);
    if (!rows.length) return "";
    return `<ul class="mx-break" aria-label="How you scored">${rows.map(([n, v]) => `<li><span>${esc(n)}</span><b>${+v > 0 ? "+" : ""}${Math.round(+v || 0)}</b></li>`).join("")}</ul>`;
  }
  /** Shift-by-shift lines: power %, life support %, dose as % of the limit (one 0-100 axis); storm shifts shaded. */
  function chart(tl, lim) {
    if (tl.length < 2) return `<p class="mx-empty">Fly a few shifts to see your chart.</p>`;
    const W = 720, H = 200, L = 36, R = 88, T = 8, B = 24, n = tl.length;
    const x = i => L + i / (n - 1) * (W - L - R), y = v => T + (1 - pct(v) / 100) * (H - T - B);
    const series = [["power", "Power", d => d.power], ["life", "Life support", d => d.life_support], ["dose", "Dose", d => d.dose_msv / lim * 100]];
    const grid = [0, 50, 100].map(v => `<line class="c-grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="c-ax" x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`).join("");
    const step = (W - L - R) / (n - 1);
    // storm shifts: a band per shift, clipped to the plot (never past the first or last point)
    // [qa] every shift a storm was on (storm_active), not only the one it started in; a point is a shift's END, so the
    // band runs from the previous point to this one
    const storms = tl.map((d, i) => { if (!(d.storm_active || (d.events || []).includes("solar_storm") || (d.events || []).includes("dose_alert"))) return "";
      const x0 = Math.max(L, i ? x(i - 1) : x(i) - step / 2), x1 = Math.min(W - R, x(i));
      return `<rect class="c-storm" x="${x0.toFixed(1)}" y="${T}" width="${(x1 - x0).toFixed(1)}" height="${H - T - B}"/>`; }).join("");
    const dayOf = th => Math.max(1, Math.floor((th - 1) / 24) + 1);   // [qa] never "Day 0" (the sample timeline starts at t=0)
    const days = []; tl.forEach((d, i) => { if (i === 0 || dayOf(d.t_h) !== dayOf(tl[i - 1].t_h)) days.push(`<text class="c-ax" x="${x(i)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : "middle"}">Day ${dayOf(d.t_h)}</text>`); });
    const lines = series.map(([k, , f]) => `<polyline class="c-${k}" points="${tl.map((d, i) => x(i).toFixed(1) + "," + y(f(d)).toFixed(1)).join(" ")}"/>`).join("");
    const last = tl[n - 1];
    const ly = series.map(([k, nm, f]) => ({ k, n: nm, y: y(f(last)) + 4 })).sort((a, b) => a.y - b.y);
    ly.forEach((l, i) => { if (i && l.y - ly[i - 1].y < 14) l.y = ly[i - 1].y + 14; });
    // [qa] labels pushed past the bottom (all three lines ending near 0) move back up instead of vanishing
    for (let i = ly.length - 1, max = H - B; i >= 0; i--) { if (ly[i].y > max) ly[i].y = max; max = ly[i].y - 14; }
    const labels = ly.map(l => `<text class="c-lab c-${l.k}-t" x="${W - R + 8}" y="${l.y.toFixed(1)}">${l.n}</text>`).join("");
    window.__mChart = { tl, x, series, lim, L, W, R };
    const hasStorm = storms.length > 0;
    return `<figure class="mx-chart"><figcaption class="sr-only">Power, life support and radiation dose, shift by shift${hasStorm ? ". Shaded shifts had a solar storm or a dose alert" : ""}.</figcaption>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Power, life support and dose, shift by shift">${storms}${grid}${days.join("")}${lines}${labels}
      <line class="c-cross" id="cCross" y1="${T}" y2="${H - B}" x1="0" x2="0" visibility="hidden"/></svg>
      <p class="mx-key">${hasStorm ? `<i></i>Storm or high dose · ` : ""}Dose is a % of the ${lim} mSv limit</p><div class="c-tip" id="cTip" hidden></div></figure>`;
  }
  function wireChart() {
    const svg = debriefEl.querySelector(".mx-chart svg"), tip = $("cTip"), cross = $("cCross"), c = window.__mChart; if (!svg || !c) return;
    svg.addEventListener("pointermove", e => {
      const r = svg.getBoundingClientRect(), vx = (e.clientX - r.left) / r.width * c.W;
      let bi = 0; c.tl.forEach((d, i) => { if (Math.abs(c.x(i) - vx) < Math.abs(c.x(bi) - vx)) bi = i; });
      const best = c.tl[bi];
      cross.setAttribute("x1", c.x(bi)); cross.setAttribute("x2", c.x(bi)); cross.setAttribute("visibility", "visible");
      tip.hidden = false; tip.style.left = (c.x(bi) / c.W * 100) + "%";
      tip.innerHTML = `<b>Day ${Math.max(1, Math.floor((best.t_h - 1) / 24) + 1)} · shift ${Math.max(1, Math.floor(((best.t_h - 1) % 24) / 6) + 1)}</b>` + c.series.map(([k, n, f]) => `<span><i class="c-${k}"></i>${n} ${k === "dose" ? (+best.dose_msv).toFixed(1) + " mSv" : Math.round(f(best)) + "%"}</span>`).join("");
    });
    svg.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });
  }

  // ---------- hands-free (the session's router decides; these run what it decided) ----------
  function screenFrame() {
    if (screen === "off") return null;
    if (screen === "hud") {
      if (tour.active) return { screen: "cabin", offer: "tour" };
      const c = state && !pending ? cardNow() : null;
      // a job on the Now card is an offer: "yes" / "do it" presses its button; a choice's words pick it
      if (c && (c.buttons || []).length && (c.progress || (c.offer && !c.buttons.some(b => b.intent)))) return { screen: "cabin", offer: "task", step_options: c.choice ? c.buttons.map(b => b.label) : [], ...(c.free ? { step_type: c.free } : {}) };
      return { screen: "cabin" };
    }
    if (screen === "debrief") return { screen: "debrief", offer: pendingWipe ? "confirm_wipe" : "fly_again" };
    if (screen === "gate") return { screen: "brief", offer: "practice" };
    if (screen === "practice_done") return { screen: "debrief", offer: "practice_done" };
    return { screen: "brief", offer: "take_command" };
  }
  /** A navigation intent. True when Mission ran it. */
  function nav(intent, arg) {
    if (screen === "off") return false;
    // the tour: next / yes moves on, skip ends it, "show me around" replays it
    if (tour.active && ["next", "accept_offer", "yes", "start"].includes(intent)) { tour.next(); return true; }
    if (tour.active && (intent === "skip_tour" || intent === "decline_offer")) { tour.end(false); return true; }
    if (intent === "cabin_tour") return replayTour();
    if (intent === "recenter" && screen === "hud" && cockpit && cockpit.recenter) { cockpit.recenter(); return true; }
    if (screen === "hud" && !tour.active && cockpit && cockpit.chapterOpen) {   // [polish 2] the chapter card owns yes / next
      if (["accept_offer", "yes", "next", "start"].includes(intent)) return chapterGo();
      if (intent === "debrief") { cockpit.chapter(null); showDebrief(); return true; }
    }
    if (screen === "hud" && !tour.active && cockpit && cockpit.menuOpen && ["accept_offer", "yes", "start"].includes(intent)) return closeMenu(true);
    if (screen === "hud" && !tour.active) {
      if (intent === "pause_menu") return openMenu();
      if (intent === "skip_event") { skipEvent(); return true; }
      if (intent === "time_pause") return clockAction("pause");
      if (intent === "time_resume") return clockAction("play");
      if (intent === "time_warp") return clockAction("warp", arg || undefined);
      if (intent === "task_choice") return pickChoice(arg);
      if (intent === "why") return openWhy(arg, "voice");
      if (["accept_offer", "yes"].includes(intent) && !pending && doTaskStep()) return true;
    }
    if (intent === "help") { const t = whatNow(); if (!t) return false; if (screen === "hud") radio("capcom", t); say(t); return true; }
    if (intent === "systems") return systemsAct(arg);
    if (intent === "back" && screen === "hud" && cockpit && cockpit.systemsOpen) return cockpit.systems(false);
    const pn = { panel_power: "power", panel_habitat: "habitat", panel_comm: "comm", panel_rover: "rover", panel_radiation: "radiation", panel_back: "seat" }[intent];
    if (pn && screen === "hud" && cockpit && pn === "seat" && cockpit.systemsOpen) { cockpit.systems(false); if (cockpit.is3d) cockpit.seat(); return true; }
    if (pn && screen === "hud" && pn !== "seat" && openSystemFor(pn)) return true;   // [systems] the drawer's panel, when the level has it
    if (pn) { if (screen === "hud" && cockpit && cockpit.is3d) { pn === "seat" ? cockpit.seat() : cockpit.openPanel(pn); return true; } return false; }
    const vw = { view_orbit: "orbit", view_rover: "rover", view_site: "site" }[intent];
    if (vw) { if (screen === "hud" && cockpit) { cockpit.setView(vw); return true; } return false; }
    if (screen === "brief" && nv.nav(intent, arg)) return true;   // map layers, "which site has the most ice?", weights, regions
    if (intent === "pick_site" && ["brief", "debrief", "hub", "plan"].includes(screen)) {
      const s = sites.find(x => x.id === arg); if (!s) return false;
      if (unsub && screen === "debrief") { unsub(); unsub = null; state = null; }
      const onHub = screen === "hub" || screen === "plan";
      site = s; previewSite(); if (onHub) hub(); else picker(); say(`${s.name.split(" (")[0]}. Good choice. Say start when you're ready.`); return true;
    }
    // [polish 4] hub -> briefing -> cabin: "start" / "take command" / "yes" moves one screen on; back goes to the hub
    if (screen === "hub" && (intent === "next" || intent === "prev")) { if (!stepMission(intent === "next" ? 1 : -1)) stepSite(intent === "next" ? 1 : -1); return true; }   // LB / RB: another mission (or site)
    if ((screen === "brief" || screen === "hub") && ["take_command", "start", "next", "accept_offer", "yes"].includes(intent)) { toPlan(); return true; }
    if (screen === "plan" && ["take_command", "start", "next", "accept_offer", "yes"].includes(intent)) { start(); return true; }
    if (screen === "hub" && intent === "new_site") { picker(); return true; }
    if ((screen === "plan" || screen === "brief") && intent === "back") { hub(); return true; }
    if (screen === "gate" && ["start", "next", "accept_offer", "yes"].includes(intent)) { startPractice(); return true; }
    if (screen === "gate" && intent === "take_command") { say(GATE.say(callSign.spoken("Cadet"))); return true; }   // not yet: the path, again
    if (screen === "practice_done" && ["accept_offer", "yes", "start", "next"].includes(intent)) { if (academy && academy.goRide) academy.goRide(); return true; }
    if (screen === "practice_done" && intent === "fly_again") { startPractice(); return true; }
    if (screen === "debrief" && pendingWipe && ["accept_offer", "yes"].includes(intent)) { const g = pendingWipe; pendingWipe = null; debriefEl.querySelectorAll(".mx-wipe").forEach(n => n.remove()); g(); return true; }
    if (screen === "debrief" && pendingWipe && intent === "decline_offer") { pendingWipe = null; debriefEl.querySelectorAll(".mx-wipe").forEach(n => n.remove()); return true; }
    if (screen === "debrief" && intent === "accept_offer" && state && !state.over) { showHud(); return true; }   // paused: the offer is "resume"
    if (screen === "debrief" && (intent === "next_mission" || (intent === "accept_offer" && debriefEl.dataset.primary === "next"))) return nextMission();
    if (screen === "debrief" && ["fly_again", "accept_offer", "start"].includes(intent)) { leaveMission(() => { if (unsub) unsub(); state = null; start(); }); return true; }
    if (screen === "debrief" && intent === "new_site") { leaveMission(() => { if (unsub) unsub(); state = null; picker(); }); return true; }
    if (screen === "debrief" && intent === "back") { if (state && !state.over) showHud(); else hub(); return true; }
    if (screen === "hud" && (intent === "debrief" || intent === "fly_again")) { showDebrief(); return true; }
    if (intent === "decline_offer") return true;
    return false;
  }

  /** One path for every input (router nav, taps, the gestures bus): intent names match the router's where they exist.
   *  Returns true when the cabin ran it. Works with the camera off; gestures only add another way in. */
  function intent(name, arg) {
    if (screen !== "hud" || !cockpit) return nav(name, arg);
    switch (name) {
      case "look": cockpit.look && cockpit.look(arg && arg.dx, arg && arg.dy); return true;
      case "recenter": if (cockpit.recenter) cockpit.recenter(); return true;
      case "highlight_panel": cockpit.highlightPanel && cockpit.highlightPanel(arg); return true;
      case "panel_next": cockpit.nextPanel && cockpit.nextPanel(); return true;
      case "panel_prev": cockpit.prevPanel && cockpit.prevPanel(); return true;
      case "panel_open": { const id = arg || cockpit.highlighted; if (!id) return false; cockpit.openPanel(id); return true; }
      case "view_next": case "view_prev": { const order = ["orbit", "site", "rover", "earth"], i = order.indexOf(cockpit.view);
        cockpit.setView(order[(i + (name === "view_next" ? 1 : -1) + order.length) % order.length]); return true; }
      case "confirm": case "cancel": {   // [polish 3] Y / N answer the Now card's yes / no (the sim's, or one the Director holds)
        if (offer && offer.confirm) { const c = cardNow(), b = c && c.buttons.find(x => x.intent === (name === "confirm" ? "yes" : "no")); if (b) return taskButton(b); }
        if (pending) { run({ type: name }); return true; } return false; }
      case "task_step": return doTaskStep();
      case "time_toggle": return clockAction("toggle");
      case "time_warp": return clockAction("warp", arg && arg.warp);
      case "skip_event": if (cockpit.menuOpen || cockpit.chapterOpen) return true; skipEvent(); return true;
      case "pause_menu": return openMenu();
      case "time_ff": return clockAction("ff", !!(arg && arg.on));
      case "why": return openWhy(arg && (arg.gauge || arg.arg), "key");
      case "systems": return systemsAct(arg && typeof arg === "object" ? arg.arg : arg);
      default: return nav(name, arg);
    }
  }

  // ---------- the shared intent bus (frontend/src/input/intents.js, feat/gestures): voice, keys and gestures reach the
  // mission through the same handlers. Soft dependency: until the bus is merged, nothing registers (no build error).
  const busMods = import.meta.glob("../input/intents.js");
  // The cabin's look / panels / next-prev / yes-no reach missionUI.intent() through the shell's defaults
  // (input/defaults.js, priority 0) and router decisions through shellNav → nav(). Here (priority 10) only what the
  // defaults don't cover: the site picker's next / prev / yes, the debrief's yes, and direct Houston / end shift.
  // [polish 2] hold F to fast-forward (keyup lets go); a held key's repeats are ignored, and typing never triggers it
  if (typeof window !== "undefined") {
    const typing = t => !!(t && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName)));
    let fHeld = false;
    addEventListener("keydown", e => {
      if (e.key !== "f" && e.key !== "F") return;
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey || typing(e.target) || screen !== "hud" || !state || state.over) return;
      if (cockpit && (cockpit.menuOpen || cockpit.chapterOpen)) return;
      fHeld = true; clockAction("ff", true);
    }, true);   // capture: the shell's key layer stops letters it doesn't map from bubbling
    const letGo = () => { if (fHeld) { fHeld = false; clockAction("ff", false); } };
    addEventListener("keyup", e => { if (e.key === "f" || e.key === "F") letGo(); }, true);
    addEventListener("blur", letGo);
  }
  const onBus = {
    next: () => (screen === "brief" || screen === "hub") ? ((screen === "hub" && stepMission(1)) || stepSite(1), true) : false,
    prev: () => (screen === "brief" || screen === "hub") ? ((screen === "hub" && stepMission(-1)) || stepSite(-1), true) : false,
    new_site: () => screen === "hub" ? (picker(), true) : false,
    yes: () => (screen === "brief" || screen === "hub") ? (toPlan(), true) : screen === "plan" ? (start(), true) : screen === "gate" ? (startPractice(), true) : screen === "debrief" ? (debriefEl.dataset.primary === "next" && !pendingWipe ? nextMission() : nav("fly_again")) : false,
    call_houston: () => screen === "hud" ? (callHouston(), true) : false,
    end_shift: () => screen === "hud" && !(state && state.over) ? (endShift(), true) : false,
    task_step: () => screen === "hud" ? intent("task_step") === true : false,
    time_toggle: () => screen === "hud" ? clockAction("toggle") : false,
    time_warp: a => screen === "hud" ? clockAction("warp", a && a.warp) : false,
    skip_event: () => screen === "hud" && !(state && state.over) ? ((cockpit && (cockpit.menuOpen || cockpit.chapterOpen)) || skipEvent(), true) : false,
    pause_menu: () => openMenu(),
    time_ff: a => screen === "hud" ? clockAction("ff", !!(a && a.on)) : false,
    // [polish 2] Esc / B at the seat (nothing else open: keys.js "back" passed it on) opens the pause menu; with the
    // menu or a chapter card up it closes it
    back: (a, ev) => {
      if (screen === "plan" || screen === "brief") { hub(); return true; }   // [polish 4] Esc / B: back to the hub
      if (screen !== "hud" || !cockpit || tour.active) return false;
      if (cockpit.chapterOpen) return chapterGo();
      if (cockpit.menuOpen) return closeMenu(true);
      if (cockpit.whyOpen && ev && ["keyboard", "gamepad"].includes(ev.source)) { cockpit.whyClose(); return true; }   // B: the Why card first
      if (cockpit.systemsOpen) return cockpit.systems(false, null, { focus: true });   // [systems] Esc / B closes the drawer first
      return ev && ["keyboard", "gamepad"].includes(ev.source) ? openMenu() : false;
    },
    why: (a, ev) => screen === "hud" ? openWhy(a && (a.gauge || a.arg), ev && ev.source === "voice" ? "voice" : "key") : false,   // "why is power low?", the I key
    // an open palm (stop) also holds the clock; it never consumes the intent (speech still stops)
    stop: () => { if (screen === "hud" && mclock.running) clockAction("pause"); return false; },
  };
  // the tour beats every other handler while it runs (a swipe, a thumbs up or "next" never changes the view mid-tour)
  const onTour = { next: () => tour.next(), yes: () => tour.next(), accept_offer: () => tour.next(), skip_tour: () => tour.end(false), decline_offer: () => tour.end(false) };
  const loadBus = busMods["../input/intents.js"];
  if (loadBus) loadBus().then(m => {
    Object.entries(onBus).forEach(([n, fn]) => m.onIntent(n, (a, ev) => fn(a, ev) === true, { priority: 10 }));
    Object.entries(onTour).forEach(([n, fn]) => m.onIntent(n, () => (tour.active ? fn() === true : false), { priority: 20 }));
    ["skip_tour", "cabin_tour", "help"].forEach(n => m.onIntent(n, a => nav(n, a && a.arg) === true, { priority: 10 }));
    // "what can I do" (the a11y path) in the cabin answers with the job first
    m.onIntent("a11y", a => { const t = String((a && a.text) || "").toLowerCase().replace(/[^a-z ]/g, "").trim();
      if (screen !== "hud" || !/^(what can i (do|say)|help me|what are my options|options)$/.test(t)) return false; return nav("help") === true; }, { priority: 10 });
  }).catch(() => {});
  // [flows] the cabin tour, a paused mission clock and a paused mission's debrief: pause / resume for every device
  const fl = (flow, event, source) => flowLog({ flow, event, source });
  registerFlow({ name: "cabin_tour", rank: 20,   // tour.js logs each step itself (its buttons and Enter too)
    active: () => tour.active, paused: () => tour.paused,
    pause: src => tour.pause(pauseCaption(src), src), resume: src => tour.resume(src),
    next: src => tour.next(src), prev: src => tour.prev(src), repeat: src => tour.resume(src),
    close: src => tour.end(false, src) });
  registerFlow({ name: "mission_clock", rank: 40, keys: false,
    active: () => screen === "hud" && !tour.active && !!state && !state.over && mclock.started && mclock.paused, paused: () => true,
    pause: () => true, resume: src => { fl("mission_clock", "resume", src);
      if (cockpit && cockpit.chapterOpen) return chapterGo();   // [polish 2] "continue" on a chapter card / the menu
      if (cockpit && cockpit.menuOpen) return closeMenu(true);
      return clockAction("play") !== false; } });
  registerFlow({ name: "mission_paused", rank: 40, keys: false,
    active: () => (screen === "debrief" || screen === "hub") && !!state && !state.over && !practice && !pendingWipe, paused: () => true,   // a wipe confirm owns yes
    pause: () => true, resume: src => { fl("mission_paused", "resume", src); showHud(); return true; } });
  // next / prev on the picker moves the selection: say the new site so a hands-free kid knows what "take command" will fly
  function stepSite(d) { if (!sites.length) return; site = sites[(sites.indexOf(site) + d + sites.length) % sites.length]; previewSite(); if (screen === "hub") hub(); else picker();
    Promise.resolve(say(site.name.split(" (")[0] + ".")).catch(() => {}); }

  return {
    screen: screenFrame, nav, intent, radioKid: t => radio("kid", t), whatNow, get touring() { return tour.active; },
    hesitant: () => nudge.soon(),   // [0.6] the session's `heard.hes`: the job's next nudge now (once per job)
    enter, exit, handleText, handleDirector, context,
    applyRemote, alert, showCard, askConfirm, houston,   // [session hook]
    get active() { return screen !== "off"; },
    get running() { return !!state && screen === "hud"; },
    get sample() { return !!(client && client.sample); },
    get pending() { return !!pending || !!(offer && offer.confirm); },   // [keys] N is "no" while an order waits for a yes / no
    get highlighted() { return cockpit && cockpit.highlighted || null; },   // [keys] O opens the lit panel
    /** The live clock and the Now card (tools/*.py read these: what the kid sees, never the sim's hidden schedule). */
    get clock() { return mclock.state; },
    get card() { return state && screen === "hud" ? cardNow() : null; },
    /** The 3D camera's pose (tools/mission_ui.py: it must spring back to the seat). */
    get camera() { return cockpit && cockpit.pose ? cockpit.pose : null; },
    clockAction, skipEvent,
  };
}
