// Mission Trainer UI: briefing (pick a site), HUD (3 resources, loads, environment, rover, End shift), events,
// CAPCOM card, Houston delay, debrief. Talks to the backend through client.js, or the local mock (labelled "Sample data").
import { createMissionClient } from "./client.js";
import { sayStyle } from "../floor.js";
import { parseCommand } from "./mock.js";
import { createCabin } from "./cabin.js";
import { createTerrainView } from "./terrain.js";
import "./mission.css";
import { icon } from "../assets/icons.js";
const ic = (n, size = 14) => icon(n, { size });
import { callSign, CAPCOM, callbackLine, CALLBACKS, DEBRIEF, OFFER, PICKER, HELP, PRETEND_TECH, PRETEND_TECH_TIP } from "../story.js";
import { nowObjective, nowSpoken, debriefStory } from "./objective.js";
import { createTour, tourDone } from "./tour.js";

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
      storm(on) { if (!state) return; state.env.storm = on ? { active: true, name: "Real solar particle storm, 2024-05-09 (huge auroras on Earth, G5)", real_date: "2024-05-09", source: "DONKI", severity: 3, sep: true } : { active: false };
        state.alerts = on ? ["dose_rate_high"] : []; render(); },
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
      panel(id) { if (!cockpit) return; if (id) cockpit.openPanel(id); else cockpit.seat(); cockpit.offer && cockpit.offer(null); },
      calling() { if (cockpit) cockpit.calling(true, 2600); },
      debrief(outcome, extra = {}) { if (!state) return; fakeDebrief = fakeDb(outcome, extra); if (outcome !== "in_progress") { state.over = true; state.outcome = outcome; } showDebrief(); },
    };
    return tv;
  }
  let fakeDebrief = null, windows = null;   // dev-only: a debrief payload for screenshots of every outcome
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
      if (g !== gen || !entered) return;   // QA-19: left Mission while the sites loaded: no picker over another mode
    }
    if (state && !state.over) { if (!unsub) unsub = client.subscribe(state.id, onTelemetry); showHud(); return; }   // [qa] telemetry again
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
    const tl = String(text || "").toLowerCase().trim(), m = PANEL_WORDS.find(([re]) => re.test(tl)); if (!m || !cockpit || !cockpit.is3d) return false;
    if (m[1] === "seat") cockpit.seat(); else cockpit.openPanel(m[1]); return true;
  }
  function exit() { if (tour.active) tour.end(false); gen++; entered = false; screen = "off"; if (unsub) { unsub(); unsub = null; } /* [qa] no telemetry stream while away */ hideCabin(); globe.mission.exit(); panel.hidden = true; panel.classList.remove("mx-brief"); banner.hidden = true; debriefEl.hidden = true; signal.hidden = true; }

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
  /** A first-timer (no mission flown yet on this cadet) sees the recommended pick. */
  let firstPick = false, briefSpoken = false;
  function briefing() {
    const fresh = screen !== "brief";
    screen = "brief"; debriefEl.hidden = true; banner.hidden = true; panel.hidden = false; hideCabin(); card.hide(); if (tour.active) tour.end(false);
    firstPick = !firstDone();
    if (!site) site = (firstPick && sites.find(s => s.id === PICKER.recommended)) || sites[0];
    // the transition beat: where you are (Command), why the choice matters; spoken once per visit
    // one say through the line queue: no async chain to outlive the screen (rc-polish's screen generations)
    if (fresh && !briefSpoken) { briefSpoken = true; Promise.resolve(say([CAPCOM.missionBrief(callSign.spoken()), PICKER.why, ...(firstPick ? [PICKER.recLine] : [])])).catch(() => {}); }
    const src0 = site && (site.sources || [])[0];
    panel.classList.add("mx-brief");
    panel.innerHTML = `
      <header class="mx-head"><span class="eyebrow">Briefing</span>${sampleTag()}</header>
      <h2 class="mx-title">${esc(PICKER.title)}</h2>
      <p class="mx-sub">${esc(PICKER.why)}</p>
      <p class="mx-do">Tap a site to compare. Then tap Take command.</p>
      <div class="mx-sites" role="radiogroup" aria-label="Outpost site">
        <div class="mx-cols" aria-hidden="true"><span></span><span>${ic("sun")}Sun</span><span>${ic("earth")}Earth</span><span>${ic("ice")}Ice</span></div>
        ${sites.map(s => `
        <button type="button" class="mx-site" role="radio" data-site="${esc(s.id)}" aria-checked="${s === site}" tabindex="${s === site ? 0 : -1}"
          aria-label="${esc(s.name)}: Sun on ${sunDays(s)} of 10 days, Earth in view on ${earthDays(s)} of 10 days, ${iceLabel(s)}">
          <b>${esc(s.name)}${firstPick && s.id === PICKER.recommended ? `<em class="mx-rectag">${esc(PICKER.recTag)}</em>` : ""}<em class="mx-tag2">${siteTag(s)}</em>${s === site && s.sunlight_pct != null ? `<small>${s.power_from ? `Power by cable from the rim <span class="mx-pretend" title="${esc(PRETEND_TECH_TIP)}">${esc(PRETEND_TECH)}</span>` : `About ${Math.round(s.sunlight_pct)}% sunlight (yearly average)`}</small>` : ""}</b>
          <span class="mx-v${sunDays(s) >= 8 ? " is-best" : ""}">${sunDays(s)}<small>/10</small></span>
          <span class="mx-v${earthDays(s) >= 8 ? " is-best" : ""}">${earthDays(s)}<small>/10</small></span>
          <span class="mx-v${s.ice ? " is-best" : ""}">${s.ice ? "Yes" : s.rover_to_ice_h ? `${s.rover_to_ice_h}<small> h away</small>` : "No"}</span>
        </button>`).join("")}
      </div>
      <p class="mx-srcline">Sun and Earth: days in view during your 10 days · ${srcLink(HORIZONS, "JPL Horizons")}</p>
      <button type="button" class="mx-go" id="mStart">Take command</button>`;
    const pick = id => { site = sites.find(s => s.id === id); previewSite(); briefing(); const n = panel.querySelector(`[data-site="${CSS.escape(site.id)}"]`); if (n) n.focus(); };
    panel.querySelectorAll(".mx-site").forEach(b => {
      b.onclick = () => pick(b.dataset.site);
      b.onpointerenter = () => hot(b.dataset.site, true); b.onpointerleave = () => hot(b.dataset.site, false);
    });
    panel.querySelector(".mx-sites").addEventListener("keydown", e => {
      const d = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key]; if (!d) return; e.preventDefault(); e.stopPropagation();
      pick(sites[(sites.indexOf(site) + d + sites.length) % sites.length].id);
    });
    $("mStart").onclick = () => start();
    previewSite(); pins(pick);
  }
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
    const svg = pinEl.querySelector(".mx-leads");
    const tick = () => {
      if (screen !== "brief") { pinEl.hidden = true; return; }
      const P = sites.map(s => ({ s, p: globe.project(s.lat, s.lon) })).filter(o => o.p.facing);
      const minX = Math.min(...P.map(o => o.p.x)), LH = 34;
      const col = P.slice().sort((a, b) => a.p.y - b.p.y);
      // label column left of the cluster, centred on it vertically, one row per site
      const H = pinEl.clientHeight || innerHeight, cy = col.reduce((t, o) => t + o.p.y, 0) / (col.length || 1);
      // keep the label column clear of the voice bar (bottom ~150px of the stage)
      const y0 = Math.max(24, Math.min(cy - (col.length - 1) * LH / 2, H - 150 - (col.length - 1) * LH)), lx = minX - 64;
      let lines = "";
      col.forEach((o, k) => {
        const id = CSS.escape(o.s.id), dot = pinEl.querySelector(`.mx-dot[data-site="${id}"]`), lab = pinEl.querySelector(`.mx-pin[data-site="${id}"]`);
        const ly = y0 + k * LH;
        dot.style.transform = `translate(${o.p.x.toFixed(1)}px,${o.p.y.toFixed(1)}px)`;
        lab.style.transform = `translate(calc(${lx.toFixed(1)}px - 100%),${ly.toFixed(1)}px)`;
        lines += `<path d="M${(lx + 4).toFixed(1)} ${ly.toFixed(1)}H${(lx + 24).toFixed(1)}L${o.p.x.toFixed(1)} ${o.p.y.toFixed(1)}" class="${o.s === site ? "is-sel" : ""}" data-site="${esc(o.s.id)}"/>`;
      });
      svg.innerHTML = lines;
      pinRaf = requestAnimationFrame(tick);
    };
    tick();
  }
  function previewSite() {
    if (!site) return;
    globe.mission.setSite({ ...site, short: site.name.split(" (")[0] }, { dist: 2.0 });
    globe.mission.setSun(1, 0); globe.mission.setEarth(site.earth_visible_pct > 60 ? 3 : -1); globe.mission.setRover(null);
    // frame the whole south-pole region (all five sites), not just the picked one; the band lifts the pole off the strip
    globe.setViewport(window.__pickBand || .3); globe.flyTo(-88.6, -40, window.__pickDist || 1.45);
  }

  let starting = false;
  async function start(seed) {
    // [qa] QA-54: one mission per press (a double click, or a click while saying "take command"); a failed start says so
    if (starting) return; starting = true;
    document.querySelectorAll("#mStart, #mAgain").forEach(b => { b.disabled = true; });
    siteSeed = seed ?? Math.floor(Math.random() * 1e9);
    // Settings → level (prefs, from the first request), else the stored tier; Cadet/Commander bands in the sim
    const level = (window.__outpost && window.__outpost.prefs && window.__outpost.prefs.level) || tier();
    let st = null;
    const g = gen;
    try { st = await client.start({ site: site.id, seed: siteSeed, roles: [...roles], level }); } catch (e) { st = null; }
    starting = false;
    document.querySelectorAll("#mStart, #mAgain").forEach(b => { b.disabled = false; });
    if (!alive(g)) return;   // left Mission while it started (even if the kid is back on a new screen generation)
    if (!st) { capcom({ say: "Can't reach the mission server. Try again." }); return; }
    state = st; prev = null; logHistory = []; reminded.clear(); seen.clear();
    if (unsub) unsub();
    unsub = client.subscribe(state.id, onTelemetry);
    pushContext();
    showHud();
    if (session && !client.sample && session.onStart) session.onStart(state);   // [session hook]
    windows = null; if (client.windows) client.windows(state.id).then(w => { windows = w; if (cockpit && cockpit.setWindows) cockpit.setWindows(w); }).catch(() => {});
    capcom({ say: CAPCOM.missionStart(callSign.shown(), site.name) });
    const first = !firstDone(), touring = !tourDone(callSign.get());
    // never wait on the voice for the next step: a slow or silent TTS must not leave the kid in a cabin with no guide
    // One say through the floor's line queue (rc-polish): the hello and the first tour beat (or the objective) play as
    // one on-air span, so the ear's hard mute covers the whole run. The card shows at once; it never waits on the voice.
    const hello = CAPCOM.missionStart(callSign.spoken(), site.name);
    if (touring) tour.start(level, { lead: hello });         // first mission: CAPCOM shows the cabin first
    else {
      const ob = nowObjective(state);
      if (ob) capcom({ say: ob.text });                       // the objective on the strip too
      Promise.resolve(say(ob ? [hello, ob.text] : hello)).catch(() => {});
      if (first) nudge.arm();
    }
    if (first) markFirstDone();
    briefSpoken = false;
  }

  // ---------- first mission: one "how to play" line, repeated only after ~20 s of silence with no order (max twice) ----------
  const firstKey = () => "outpost-first-mission:" + (callSign.get() || "cadet");
  const firstDone = () => { try { return localStorage.getItem(firstKey()) === "1"; } catch (e) { return false; } };
  const markFirstDone = () => { try { localStorage.setItem(firstKey(), "1"); } catch (e) { /* private mode */ } };
  const nudge = { t: null, left: 0,
    arm() { this.left = 2; this.wait(); },
    wait() { clearTimeout(this.t); if (this.left <= 0) return; this.t = setTimeout(() => { if (screen !== "hud" || !state) return; this.left--; say(CAPCOM.firstShift); this.wait(); }, 20000); },
    heard() { if (this.left > 0) this.wait(); },   // the kid spoke: the silence starts again
    stop() { clearTimeout(this.t); this.left = 0; } };

  // ---------- first-mission cabin tour (tour.js) ----------
  const tour = createTour({ host: cabinEl.parentNode || document.body, cockpit: () => cockpit, say: t => say(t), callsign: () => callSign.get(),
    onEnd: () => { if (screen !== "hud" || !state) return; lastObj = ""; render(); const ob = nowObjective(state); if (ob) say(ob.text); nudge.arm(); } });
  /** Settings -> Help "Show me around", or "show me around" by voice: replay the tour in the cabin. */
  function replayTour() { if (screen !== "hud" || !cockpit) return false; nudge.stop(); tour.start(levelNow()); return true; }
  addEventListener("outpost:tour", () => { if (!replayTour()) { try { localStorage.removeItem("outpost-tour-done:" + (callSign.get() || "cadet")); } catch (e) { /* blocked */ } } });
  const levelNow = () => (window.__outpost && window.__outpost.prefs && window.__outpost.prefs.level) || tier();
  /** "What do I do?": one spoken line for this screen (the cabin's comes from the objective). */
  function whatNow() {
    if (screen === "hud") return state ? nowSpoken(state) : null;
    if (screen === "brief") return HELP.picker;
    if (screen === "debrief") return HELP.debrief;
    return null;
  }
  /** The objective strip, the glow on its control and (Cadet) the one bright panel. Quiet while the tour runs. */
  let lastObj = "";
  function paintObjective() {
    if (!cockpit || !cockpit.objective) return;
    const ob = nowObjective(state);
    cockpit.objective(ob);
    if (tour.active) return;
    const key = ob ? ob.key + ":" + ob.target : "";
    cockpit.point(ob ? ob.target : null);
    cockpit.focus(ob && levelNow() === "cadet" ? ob.panel : null);
    lastObj = key;
  }

  // ---------- cockpit (mission/cockpit.js): the console that replaced the HUD panel ----------
  function showHud() {
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
    });
    dockIn();
    if (client && client.sample) cabinEl.insertAdjacentHTML("afterbegin", sampleTag());
    requestAnimationFrame(() => { const w = cabinEl.querySelector(".cb-hole") || cabinEl.querySelector(".cb-glass"), r = w && w.getBoundingClientRect(), sr = cabinEl.getBoundingClientRect();
      if (r && sr.height) globe.setViewport((r.bottom - sr.top) / sr.height); windowView(cockpit.view || "site"); });
    logHistory.forEach(l => cockpit.log(l.who, l.text));
    if (windows && cockpit.setWindows) cockpit.setWindows(windows);
    render();
  }
  function render() {
    if (screen !== "hud" || !state || !cockpit) return;
    const s = state, e = s.env || {}, rv = s.rover || {};
    cockpit.update(s);
    paintObjective();
    (s.alerts || []).forEach(a => { if (CALLBACKS[a]) { seen.add(a); remind(a); } });
    renderBanner();
    globe.mission.setSun(+e.sun_elev_deg || 0, s.mission_time_h || 0); globe.mission.setEarth(+e.earth_elev_deg || 0);
    const tgt = rv.busy ? TARGETS[rv.task] : null, total = rv.task === "collect_ice" ? 10 : rv.task === "explore" ? 8 : 5;
    globe.mission.setRover(tgt, tgt ? Math.sin(Math.PI * (1 - (rv.eta_h || 0) / total)) : 0);
    syncSurface();
  }
  /** Radio log lines survive re-renders of the cockpit. */
  function radio(who, text) { if (!text) return; if (who === "kid") nudge.heard(); logHistory.push({ who, text }); logHistory = logHistory.slice(-12); if (cockpit && screen === "hud") cockpit.log(who, text); }
  /** The Call Houston push button: the real Director in a live mission, the local practice line otherwise. */
  async function callHouston() {
    if (!state) return;
    radio("kid", "Houston, Outpost Luna. Radio check.");
    if (client.sample || !askDirector) { await houston("Houston here. We copy you, Commander. Keep the crew safe and the lights on.", 2600); return; }
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
    if (confirm) cadetOffer({}, line || readback, [{ label: "Yes", onClick: () => answer(true) }, { label: "No", onClick: () => answer(false) }]);
    card.show({ title: "CAPCOM", eyebrow: eyebrow || [s ? `Day ${s.day} · shift ${s.shift}` : "Mission", client && client.sample ? "Sample data" : ""].filter(Boolean).join(" · "),
      say: line || readback || "", actions });
    if (screen === "hud" && !/^Houston/.test(eyebrow || "")) radio("capcom", line || readback);
  }

  async function run(command, { spoken } = {}) {
    if (!state) return;
    nudge.stop();
    if (command.type === "end_shift") return endShift();
    let r;
    const g = gen;
    try { r = await client.command(state.id, command); } catch (e) { if (alive(g)) capcom({ say: "CAPCOM can't reach the mission server." }); return; }
    if (!alive(g)) { if (r && r.state) state = r.state; return; }   // QA-20: left Mission while the order ran
    applyState(r.state);
    const res = r.result || {};
    pending = res.needs_confirm ? command : null;
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
    if (storm) { alertSound(); stormAlert(); return; }
    const alarm = evs.find(e => e.kind === "low_power" || e.kind === "dose_alert");
    if (alarm) { alertSound(); const t = alarm.kind === "low_power" ? "Low power" : "High dose"; renderBanner({ level: alarm.kind === "low_power" ? "caution" : "warn", title: t, text: alarm.text }); a11yAlert(`${t}. ${alarm.text || ""}`); return; }
    const comm = evs.find(e => e.kind === "comm_open" || e.kind === "comm_closed");
    if (comm) renderBanner({ level: "info", title: comm.kind === "comm_open" ? "Earth in view" : "Earth set", text: comm.text });
  }

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
    await say(line, style || { voice: "houston" });   // Houston speaks in its own (Steer) voice
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
    radio("kid", text);
    if (panelWord(text)) return true;
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
    if (state && s.mission_time_h !== state.mission_time_h) nudge.stop();   // a shift ended through the session Director
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
  function cadetOffer(d, text, actions) {
    if (tier() !== "cadet" || !cockpit || !cockpit.offer || screen !== "hud") return;
    const pid = panelFor(d, text); if (pid) cockpit.offer(pid, actions);
  }
  function showCard(d, send) {
    const s = state;
    card.show({ title: d.title || "CAPCOM", asked: d.asked || "", say: d.body || "", arc: d.arc || "",
      eyebrow: [d.hint ? "Heads up" : d.nudge ? "Coach" : "", s ? `Day ${s.day} · shift ${s.shift}` : "Mission"].filter(Boolean).join(" · "),
      actions: (d.actions || []).map(a => ({ label: a.label, hot: true, once: true, onClick: () => send(a.send) })) });
    if ((d.actions || []).length) cadetOffer(d, [d.title, d.body, d.asked].join(" "), d.actions.map(a => ({ label: a.label, onClick: () => send(a.send) })));
  }
  function askConfirm(d, send) {
    pending = { type: "confirm" };
    card.show({ title: "CAPCOM", say: d.text || "Are you sure?", eyebrow: "Confirm",
      actions: [{ label: "Yes", hot: true, once: true, onClick: () => send(d.yes) }, { label: "No", once: true, onClick: () => send(d.no) }] });
    cadetOffer(d, d.text, [{ label: "Yes", onClick: () => send(d.yes) }, { label: "No", onClick: () => send(d.no) }]);
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
      $("mNewSite").onclick = () => { if (unsub) unsub(); unsub = null; state = null; briefing(); };
      return;
    }
    const outcome = d.outcome || state.outcome || (state.over ? "" : "in_progress");
    const paused = outcome === "in_progress" || !outcome;
    const won = outcome === "survived" || outcome === "success";
    const head = won ? "Mission complete" : paused ? "Mission paused" : "Mission over";
    const sub = paused ? `Day ${state.day} of 10. Your outpost is waiting.` : firstSentence(d.why);
    (d.timeline || []).forEach(t => (t.events || []).forEach(k => { if (CALLBACKS[k]) seen.add(k); }));
    // takeaways: the debrief's own lessons first (each with its source), then Flight School lessons that came back
    // [qa] at most two data lessons, so a Flight School callback or the "Next time" tip still gets a slot of the three
    const tks = (d.lessons || []).filter(l => l && l.text && !/Artemis III/i.test(l.text)).slice(0, 2).map(l => ({ text: takeaway(l.text), source: l.source }));
    [...new Set([...seen].map(k => CALLBACKS[k].lesson))].forEach(id => { const k = [...seen].find(x => CALLBACKS[x].lesson === id); tks.push({ text: takeaway(CALLBACKS[k].text), source: null, lesson: CALLBACKS[k].n }); });
    const story = debriefStory(d, state);   // the mission as a story: three beats, what to try next, one clear choice
    if (!tks.length) lessons().forEach(l => tks.push({ text: takeaway(l.text), source: { ...l.source, title: l.name } }));
    // [qa] "DONKI 2017-09-04T23:52:00-SEP-001 (NASA CCMC)" → "NASA DONKI, 2017-09-04"; a colon in a time is not a break
    const srcLabel = s => { const t = String((s && s.title) || "").trim(); if (!t) return "Source";
      const dk = t.match(/^DONKI\s+(\d{4}-\d{2}-\d{2})/); if (dk) return `NASA DONKI, ${dk[1]}`;
      return t.split(/[,(]|:\s/)[0].trim() || "Source"; };
    debriefEl.hidden = false; debriefEl.classList.add("mx-debrief");
    debriefEl.innerHTML = `
      <header class="mx-head"><span class="eyebrow">Debrief · ${esc(state.site.name)}</span>${sampleTag()}
        <button class="mx-x" id="mDbClose" type="button" aria-label="${esc(DEBRIEF.close)}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg></button></header>
      <div class="mx-db-top">
        <div><h2 class="mx-title">${head}</h2>${sub ? `<p class="mx-sub">${esc(sub)}</p>` : ""}</div>
        <dl class="mx-score">${paused ? "" : `<div><dt>Grade</dt><dd class="mx-grade">${esc(d.grade)}</dd></div>`}<div><dt>Score</dt><dd>${Math.round(d.score || 0)}</dd></div>${d.stars != null ? `<div><dt>Stars</dt><dd class="mx-stars" aria-label="${d.stars} of 3 stars">${[0, 1, 2].map(k => `<span class="${k < d.stars ? "is-on" : ""}">${ic("star", 20)}</span>`).join("")}</dd></div>` : ""}</dl>
        ${breakdown(d)}
      </div>
      <section class="mx-story" aria-label="${esc(DEBRIEF.storyTitle)}"><h3>${esc(DEBRIEF.storyTitle)}</h3>
        <ol>${story.beats.map(b => `<li>${esc(b)}</li>`).join("")}</ol>
        <p class="mx-try"><b>${esc(DEBRIEF.tryTitle)}</b> ${esc(story.tryLine)}</p></section>
      ${chart(d.timeline || [], state.resources.dose_limit_msv || 50)}
      <ul class="mx-tks">${tks.slice(0, 3).map(t => `<li><span>${esc(t.text)}</span>${t.source ? srcLink(t.source, srcLabel(t.source)) : t.lesson ? `<span class="mx-tag">Lesson ${t.lesson}</span>` : t.next ? `<span class="mx-tag">Next time</span>` : ""}</li>`).join("")}</ul>
      <div class="mx-foot">
        <button type="button" class="mx-go" id="mAgain">${esc(paused ? DEBRIEF.resume : DEBRIEF.choiceAgain)}</button>
        <button type="button" class="mx-link" id="mNewSite">${esc(DEBRIEF.choiceNew)}</button>
        ${(d.data_used || []).length ? `<details class="mx-data"><summary>Data used</summary><ul>${d.data_used.map(x => `<li><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a></li>`).join("")}</ul></details>` : ""}
      </div>`;
    $("mAgain").onclick = () => { if (paused && state && !state.over) { showHud(); return; } if (unsub) unsub(); state = null; start(); };
    $("mNewSite").onclick = () => leaveMission(() => { if (unsub) unsub(); state = null; briefing(); });
    $("mDbClose").onclick = () => { if (state && !state.over) showHud(); else briefing(); };
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
    Promise.resolve(say([spoken(callSign.spoken()), ...(paused ? [] : [story.beats[1]]),
      paused ? `${story.end} ${OFFER.resume}` : `${story.tryLine} ${OFFER.flyAgain}`])).catch(() => {});   // one on-air span
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
    if (screen === "hud") return tour.active ? { screen: "cabin", offer: "tour" } : { screen: "cabin" };
    if (screen === "debrief") return { screen: "debrief", offer: pendingWipe ? "confirm_wipe" : "fly_again" };
    return { screen: "brief", offer: "take_command" };
  }
  /** A navigation intent. True when Mission ran it. */
  function nav(intent, arg) {
    if (screen === "off") return false;
    // the tour: next / yes moves on, skip ends it, "show me around" replays it
    if (tour.active && ["next", "accept_offer", "yes", "start"].includes(intent)) { tour.next(); return true; }
    if (tour.active && (intent === "skip_tour" || intent === "decline_offer")) { tour.end(false); return true; }
    if (intent === "cabin_tour") return replayTour();
    if (intent === "help") { const t = whatNow(); if (!t) return false; if (screen === "hud") radio("capcom", t); say(t); return true; }
    const pn = { panel_power: "power", panel_habitat: "habitat", panel_comm: "comm", panel_rover: "rover", panel_radiation: "radiation", panel_back: "seat" }[intent];
    if (pn) { if (screen === "hud" && cockpit && cockpit.is3d) { pn === "seat" ? cockpit.seat() : cockpit.openPanel(pn); return true; } return false; }
    const vw = { view_orbit: "orbit", view_rover: "rover", view_site: "site" }[intent];
    if (vw) { if (screen === "hud" && cockpit) { cockpit.setView(vw); return true; } return false; }
    if (intent === "pick_site" && (screen === "brief" || screen === "debrief")) {
      const s = sites.find(x => x.id === arg); if (!s) return false;
      if (unsub && screen === "debrief") { unsub(); unsub = null; state = null; }
      site = s; previewSite(); briefing(); say(`${s.name.split(" (")[0]}. Good choice. Say take command when you're ready.`); return true;
    }
    if (screen === "brief" && ["take_command", "start", "next", "accept_offer"].includes(intent)) { start(); return true; }
    if (screen === "debrief" && pendingWipe && ["accept_offer", "yes"].includes(intent)) { const g = pendingWipe; pendingWipe = null; debriefEl.querySelectorAll(".mx-wipe").forEach(n => n.remove()); g(); return true; }
    if (screen === "debrief" && pendingWipe && intent === "decline_offer") { pendingWipe = null; debriefEl.querySelectorAll(".mx-wipe").forEach(n => n.remove()); return true; }
    if (screen === "debrief" && intent === "accept_offer" && state && !state.over) { showHud(); return true; }   // paused: the offer is "resume"
    if (screen === "debrief" && ["fly_again", "accept_offer", "start"].includes(intent)) { leaveMission(() => { if (unsub) unsub(); state = null; start(); }); return true; }
    if (screen === "debrief" && intent === "new_site") { leaveMission(() => { if (unsub) unsub(); state = null; briefing(); }); return true; }
    if (screen === "debrief" && intent === "back") { if (state && !state.over) showHud(); else briefing(); return true; }
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
      case "highlight_panel": cockpit.highlightPanel && cockpit.highlightPanel(arg); return true;
      case "panel_next": cockpit.nextPanel && cockpit.nextPanel(); return true;
      case "panel_prev": cockpit.prevPanel && cockpit.prevPanel(); return true;
      case "panel_open": { const id = arg || cockpit.highlighted; if (!id) return false; cockpit.openPanel(id); return true; }
      case "view_next": case "view_prev": { const order = ["orbit", "site", "rover", "earth"], i = order.indexOf(cockpit.view);
        cockpit.setView(order[(i + (name === "view_next" ? 1 : -1) + order.length) % order.length]); return true; }
      case "confirm": case "cancel": if (pending) { run({ type: name }); return true; } return false;
      default: return nav(name, arg);
    }
  }

  // ---------- the shared intent bus (frontend/src/input/intents.js, feat/gestures): voice, keys and gestures reach the
  // mission through the same handlers. Soft dependency: until the bus is merged, nothing registers (no build error).
  const busMods = import.meta.glob("../input/intents.js");
  // The cabin's look / panels / next-prev / yes-no reach missionUI.intent() through the shell's defaults
  // (input/defaults.js, priority 0) and router decisions through shellNav → nav(). Here (priority 10) only what the
  // defaults don't cover: the site picker's next / prev / yes, the debrief's yes, and direct Houston / end shift.
  const onBus = {
    next: () => screen === "brief" ? (stepSite(1), true) : false,
    prev: () => screen === "brief" ? (stepSite(-1), true) : false,
    yes: () => screen === "brief" ? (start(), true) : screen === "debrief" ? nav("fly_again") : false,
    call_houston: () => screen === "hud" ? (callHouston(), true) : false,
    end_shift: () => screen === "hud" && !(state && state.over) ? (endShift(), true) : false,
  };
  // the tour beats every other handler while it runs (a swipe, a thumbs up or "next" never changes the view mid-tour)
  const onTour = { next: () => tour.next(), yes: () => tour.next(), accept_offer: () => tour.next(), skip_tour: () => tour.end(false), decline_offer: () => tour.end(false) };
  const loadBus = busMods["../input/intents.js"];
  if (loadBus) loadBus().then(m => {
    Object.entries(onBus).forEach(([n, fn]) => m.onIntent(n, a => fn(a) === true, { priority: 10 }));
    Object.entries(onTour).forEach(([n, fn]) => m.onIntent(n, () => (tour.active ? fn() === true : false), { priority: 20 }));
    ["skip_tour", "cabin_tour", "help"].forEach(n => m.onIntent(n, a => nav(n, a && a.arg) === true, { priority: 10 }));
    // "what can I do" (the a11y path) in the cabin answers with the job first
    m.onIntent("a11y", a => { const t = String((a && a.text) || "").toLowerCase().replace(/[^a-z ]/g, "").trim();
      if (screen !== "hud" || !/^(what can i (do|say)|help me|what are my options|options)$/.test(t)) return false; return nav("help") === true; }, { priority: 10 });
  }).catch(() => {});
  function stepSite(d) { if (!sites.length) return; site = sites[(sites.indexOf(site) + d + sites.length) % sites.length]; previewSite(); briefing(); }

  return {
    screen: screenFrame, nav, intent, radioKid: t => radio("kid", t), whatNow, get touring() { return tour.active; },
    enter, exit, handleText, handleDirector, context,
    applyRemote, alert, showCard, askConfirm, houston,   // [session hook]
    get active() { return screen !== "off"; },
    get running() { return !!state && screen === "hud"; },
    get sample() { return !!(client && client.sample); },
  };
}
