// A small local fake of docs/MISSION_CONTRACT.md, used only while the backend has no /api/mission/* routes.
// Same shapes as the contract (sites, start, command, advance, debrief, telemetry). Every screen it backs is
// labelled "Sample data" by the UI. The storms are real DONKI events; the numbers are a toy model, not the sim.

const DONKI = "https://kauai.ccmc.gsfc.nasa.gov/DONKI/";
const HORIZONS = "https://ssd.jpl.nasa.gov/horizons/";
const LOLA = "https://pds-geosciences.wustl.edu/missions/lro/lola.htm";
const ARTEMIS = "https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/";

export const SITES = [
  { id: "connecting_ridge", name: "Connecting Ridge (Shackleton rim)", lat: -89.45, lon: -137.3, sunlight_pct: 86, ice: true, earth_visible_pct: 52,
    notes: "Lots of sunlight, and ice in Shackleton next door. Earth hides about half the time.", sources: [{ title: "LRO LOLA illumination maps", url: LOLA }, { title: "NASA: Artemis III candidate regions", url: ARTEMIS }] },
  { id: "malapert", name: "Malapert Massif", lat: -85.99, lon: 2.93, sunlight_pct: 63, ice: false, earth_visible_pct: 95,
    notes: "A tall mountain that almost always sees Earth. Less sun, no ice close by.", sources: [{ title: "NASA: Artemis III candidate regions", url: ARTEMIS }, { title: "JPL Horizons (Earth position)", url: HORIZONS }] },
  { id: "de_gerlache", name: "de Gerlache Rim", lat: -88.67, lon: -68.0, sunlight_pct: 74, ice: true, earth_visible_pct: 68,
    notes: "Good sun and a dark crater with ice. Earth is up two days out of three.", sources: [{ title: "LRO LOLA illumination maps", url: LOLA }, { title: "NASA: Artemis III candidate regions", url: ARTEMIS }] },
];

const STORMS = [
  { name: "Gannon solar storm, May 2024", real_date: "2024-05-10", severity: 3 },
  { name: "X9 solar flare, October 2024", real_date: "2024-10-03", severity: 2 },
  { name: "Halloween storms, October 2003", real_date: "2003-10-28", severity: 3 },
  { name: "Solar storm, September 2017", real_date: "2017-09-10", severity: 2 },
];

const LOADS = ["shields", "life_support", "greenhouse", "science", "rover", "comms", "heaters"];
const SHIFT_H = 6, SHIFTS = 40;
const clamp = (v, a = 0, b = 100) => Math.max(a, Math.min(b, v));
const r1 = v => Math.round(v * 10) / 10;

function rng(seed) { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t ^= t + Math.imul(t ^ (t >>> 7), 61 | t); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

const missions = new Map();

function env(m, t) {
  const s = m.site;
  // Sun: one lunar day is ~708 h; at the pole it skims the horizon. Terrain sets how often it clears it.
  const thr = Math.cos(Math.PI * s.sunlight_pct / 100);
  const sunWave = Math.sin(2 * Math.PI * (t + m.sunPhase) / 708 * 4);   // compressed so a 10-day game sees sunsets
  const sun_elev_deg = r1(1.6 * (sunWave - thr) + 0.2);
  const eThr = Math.cos(Math.PI * s.earth_visible_pct / 100);
  const earth_elev_deg = r1(5 * (Math.sin(2 * Math.PI * (t + m.earthPhase) / 160) - eThr));
  const earth_visible = earth_elev_deg > 0;
  let next = 0;
  if (!earth_visible) { for (let h = 1; h < 200; h++) { const e = 5 * (Math.sin(2 * Math.PI * (t + h + m.earthPhase) / 160) - eThr); if (e > 0) { next = h; break; } } }
  const st = m.storms.find(x => t >= x.t_h && t < x.t_h + x.dur);
  return { sun_elev_deg, in_sun: sun_elev_deg > 0, earth_elev_deg, earth_visible, next_comm_window_h: next, comm_delay_s: 2.6,
    storm: st ? { active: true, name: st.name, source: "DONKI", url: DONKI, severity: st.severity, real_date: st.real_date } : { active: false } };
}

function view(m) {
  const t = m.t, e = env(m, t), alerts = [];
  if (m.power < 25) alerts.push("low_power");
  if (m.dose / m.limit > 0.7 || m.rate > 0.3) alerts.push("dose_rate_high");
  if (m.ls < 25) alerts.push("low_life_support");
  return {
    id: m.id, site: m.site, day: Math.floor(t / 24) + 1, shift: Math.floor((t % 24) / SHIFT_H) + 1, mission_time_h: t,
    over: m.over, outcome: m.outcome, sample: true,
    resources: { power_pct: r1(m.power), life_support_pct: r1(m.ls), dose_msv: r1(m.dose), dose_limit_msv: m.limit, dose_rate_msv_h: Math.round(m.rate * 1000) / 1000 },
    loads: { ...m.loads }, env: e, rover: { ...m.rover }, shelter: m.shelter, alerts, log: m.log.slice(-30), score: Math.round(m.score), roles: m.roles,
  };
}

/** One shift of the toy model. Returns the per-hour samples (for telemetry) and the new events. */
function step(m) {
  const events = [], samples = [], before = env(m, m.t);
  for (let h = 0; h < SHIFT_H; h++) {
    const e = env(m, m.t), L = m.loads;
    const solar = e.in_sun ? 3.2 * m.site.sunlight_pct / 80 : 0;
    const draw = 1.5 + (e.in_sun ? 0 : Math.max(0, 0.8 - L.heaters / 25)) + (m.shelter ? 0.3 : 0) + (m.rover.busy ? 0.35 : 0);
    m.power = clamp(m.power + solar - draw);
    const lsPower = m.power > 0 ? 1 : 0.2;
    m.ls = clamp(m.ls + lsPower * ((L.life_support - 28) * 0.03 + L.greenhouse * 0.012) - 0.18 - (!e.in_sun && L.heaters < 5 ? 0.3 : 0));
    const base = e.storm.active ? 0.25 * e.storm.severity : 0.012;
    m.rate = base * Math.max(0.15, 1 - L.shields / 60) * (m.shelter ? 0.12 : 1) * (m.rover.busy && e.storm.active ? 1.6 : 1);
    m.dose += m.rate;
    if (!m.shelter && m.power > 5) m.score += L.science * 0.08 + (e.earth_visible ? L.comms * 0.04 : 0);
    if (m.rover.busy) {
      m.rover.eta_h = Math.max(0, m.rover.eta_h - 1);
      if (m.rover.eta_h === 0) {
        const t = m.rover.task; m.rover = { busy: false, task: null, eta_h: 0, target: null };
        if (t === "collect_ice") m.ls = clamp(m.ls + (m.site.ice ? 14 : 4));
        if (t === "explore") m.score += 40;
        if (t === "repair_array") m.power = clamp(m.power + 8);
        events.push(ev(m, "rover_back", t === "collect_ice" ? (m.site.ice ? "Rover is back with ice! Life support goes up." : "Rover is back. Not much ice near this site.") : "Rover is back at the outpost."));
      }
    }
    m.t += 1;
    samples.push({ mission_time_h: m.t, power: r1(m.power), life_support: r1(m.ls), dose_msv: r1(m.dose), dose_rate: Math.round(m.rate * 1000) / 1000 });
  }
  const after = env(m, m.t);
  for (const s of m.storms) {
    if (s.t_h > m.t - SHIFT_H && s.t_h <= m.t) events.push(ev(m, "solar_storm", `Solar storm! This is a real one: the ${s.name}. Raise the shields or take shelter.`, s));
    if (s.t_h + s.dur > m.t - SHIFT_H && s.t_h + s.dur <= m.t) events.push(ev(m, "storm_end", "The storm is over. Radiation is back to normal."));
  }
  if (before.in_sun && !after.in_sun) events.push(ev(m, "sunset", "Sunset. The solar panels stop charging. Keep the heaters on."));
  if (!before.in_sun && after.in_sun) events.push(ev(m, "sunrise", "Sunrise! The panels are charging again."));
  if (!before.earth_visible && after.earth_visible) events.push(ev(m, "comm_open", "Earth is up. The comm window is open."));
  if (before.earth_visible && !after.earth_visible) events.push(ev(m, "comm_closed", `Earth has set. Next comm window in about ${after.next_comm_window_h} hours.`));
  if (m.power < 25 && !m.flags.lowPower) { m.flags.lowPower = true; events.push(ev(m, "low_power", "Battery below 25 percent. Turn something down.")); }
  if (m.power >= 35) m.flags.lowPower = false;
  if (m.dose / m.limit > 0.7 && !m.flags.dose) { m.flags.dose = true; events.push(ev(m, "dose_alert", "Crew dose is over 70 percent of the limit. Shelter or shields up!")); }
  if (m.power <= 0) end(m, "fail", "The outpost lost all power.");
  else if (m.ls <= 0) end(m, "fail", "Life support ran out.");
  else if (m.dose >= m.limit) end(m, "fail", "The crew reached the radiation limit and had to go home.");
  else if (m.t >= SHIFT_H * SHIFTS) end(m, "success", "Ten days on the Moon. Mission complete!");
  m.timeline.push({ t_h: m.t, power: r1(m.power), life_support: r1(m.ls), dose_msv: r1(m.dose), events: events.map(e => e.kind) });
  m.log.push(...events.map(e => ({ t_h: e.t_h, text: e.text, kind: "event" })));
  return { samples, events };
}
function ev(m, kind, text, storm) {
  return { t_h: m.t, kind, text, source: storm ? { title: "NASA DONKI", url: DONKI } : null, real_date: storm ? storm.real_date : null };
}
function end(m, outcome, why) { if (m.over) return; m.over = true; m.outcome = outcome; m.why = why; }

/** Rebalance so loads sum to 100 with `to` set to v. */
function setLoad(m, to, v) {
  v = clamp(Math.round(v)); const others = LOADS.filter(k => k !== to), rest = others.reduce((s, k) => s + m.loads[k], 0), left = 100 - v;
  others.forEach(k => { m.loads[k] = rest > 0 ? m.loads[k] * left / rest : left / others.length; });
  m.loads[to] = v;
  // integer fix-up
  others.forEach(k => { m.loads[k] = Math.round(m.loads[k]); });
  const diff = 100 - LOADS.reduce((s, k) => s + m.loads[k], 0);
  const big = others.slice().sort((a, b) => m.loads[b] - m.loads[a])[0]; m.loads[big] += diff;
}

const NAME = { shields: "shields", life_support: "life support", greenhouse: "greenhouse", science: "science", rover: "rover", comms: "comms", heaters: "heaters" };

function apply(m, c) {
  const S = () => view(m);
  if (c.type === "allocate") {
    const cur = m.loads[c.to], a = c.amount || {}, v = a.value ?? 0;
    const target = a.kind === "percent" ? v : a.kind === "delta" ? cur + v : a.kind === "all" ? 100 : a.kind === "half" ? 50 : a.kind === "little" ? cur + 5 : a.kind === "none" ? 0 : cur;
    const risky = target >= 90 || ((c.to === "heaters" || c.to === "life_support") && target <= 0);
    if (risky && !c._confirmed) { m.pending = c; const rb = `Put ${NAME[c.to]} at ${clamp(Math.round(target))} percent? That takes power from everything else.`; return { ok: true, needs_confirm: true, readback: rb, say: rb + " Say yes or no.", events: [] }; }
    setLoad(m, c.to, target);
    const rb = `${cap(NAME[c.to])} at ${m.loads[c.to]} percent.`; m.log.push({ t_h: m.t, text: rb, kind: "command" });
    return { ok: true, readback: rb, say: "Copy. " + rb, events: [] };
  }
  if (c.type === "dispatch") {
    if (c.task === "return") { m.rover = { busy: true, task: "return", eta_h: 2, target: null }; return { ok: true, readback: "Rover coming home.", say: "Copy, rover returning.", events: [] }; }
    if (m.rover.busy) return { ok: false, readback: "Rover is busy.", say: `The rover is still out, back in about ${m.rover.eta_h} hours.`, events: [] };
    const storm = env(m, m.t).storm.active;
    if (storm && !c._confirmed) { m.pending = c; const rb = "Send the rover out during a solar storm? It will take extra radiation."; return { ok: true, needs_confirm: true, readback: rb, say: rb + " Say yes or no.", events: [] }; }
    const eta = c.task === "collect_ice" ? 10 : c.task === "explore" ? 8 : 5;
    m.rover = { busy: true, task: c.task, eta_h: eta, target: c.target || (c.task === "collect_ice" ? "ice" : null) };
    const rb = `Rover going to ${c.task === "collect_ice" ? "collect ice" : c.task === "repair_array" ? "fix a solar panel" : "explore"}. Back in ${eta} hours.`;
    m.log.push({ t_h: m.t, text: rb, kind: "command" });
    return { ok: true, readback: rb, say: "Copy. " + rb, events: [] };
  }
  if (c.type === "shelter") {
    m.shelter = !!c.on; const rb = c.on ? "Crew in the storm shelter. Science is paused." : "Crew out of the shelter.";
    m.log.push({ t_h: m.t, text: rb, kind: "command" }); return { ok: true, readback: rb, say: "Copy. " + rb, events: [] };
  }
  if (c.type === "confirm") { const p = m.pending; m.pending = null; if (!p) return { ok: false, readback: "Nothing to confirm.", say: "There's nothing waiting for a yes.", events: [] }; return apply(m, { ...p, _confirmed: true }); }
  if (c.type === "cancel") { m.pending = null; return { ok: true, readback: "Cancelled.", say: "Okay, cancelled. Nothing changed.", events: [] }; }
  if (c.type === "query") { const s = S(); return { ok: true, readback: statusLine(s), say: statusLine(s), events: [] }; }
  if (c.type === "call_houston") return { ok: true, readback: "Calling Houston…", say: "Houston copies. Keep the crew safe and the lights on.", events: [] };
  if (c.type === "end_shift") return { ok: true, readback: "Ending shift.", say: "", events: [] };
  return { ok: false, readback: "I didn't get that.", say: "Say it again?", events: [] };
}
const cap = s => s[0].toUpperCase() + s.slice(1);
export function statusLine(s) {
  const r = s.resources;
  return `Power ${Math.round(r.power_pct)} percent. Life support ${Math.round(r.life_support_pct)} percent. Dose ${r.dose_msv} of ${r.dose_limit_msv} millisieverts.` + (s.env.storm.active ? " A solar storm is going on." : "");
}

const listeners = new Map();
function emit(id, f) { (listeners.get(id) || []).forEach(fn => fn(f)); }

export const mock = {
  async sites() { return { sites: SITES, sample: true }; },
  async start({ site, seed, roles }) {
    const s = SITES.find(x => x.id === site) || SITES[0], sd = seed ?? Math.floor(Math.random() * 1e9), R = rng(sd);
    const first = 12 + Math.floor(R() * 3) * 6;   // a storm in the first day, so every run meets one
    const pool = STORMS.slice().sort(() => R() - 0.5);
    const m = {
      id: "m-mock-" + sd.toString(36), seed: sd, site: s, t: 0, power: 78, ls: 82, dose: 0, limit: 50, rate: 0.012, over: false, outcome: null,
      loads: { shields: 15, life_support: 30, greenhouse: 15, science: 15, rover: 10, comms: 5, heaters: 10 },
      rover: { busy: false, task: null, eta_h: 0, target: null }, shelter: false, score: 0, roles: roles || [], flags: {}, pending: null,
      sunPhase: R() * 300, earthPhase: R() * 160, log: [{ t_h: 0, text: `Outpost set up at ${s.name}.`, kind: "event" }], timeline: [],
      storms: [{ ...pool[0], t_h: first, dur: 12 + Math.floor(R() * 2) * 6 }, { ...pool[1], t_h: 120 + Math.floor(R() * 80), dur: 12 }],
    };
    m.timeline.push({ t_h: 0, power: m.power, life_support: m.ls, dose_msv: 0, events: [] });
    missions.set(m.id, m); return view(m);
  },
  async get(id) { return view(missions.get(id)); },
  async command(id, command) {
    const m = missions.get(id);
    if (command.type === "end_shift") { const r = await mock.advance(id, 1); return { state: r.state, result: { ok: true, readback: "Shift ended.", say: r.say, events: r.events } }; }
    const result = apply(m, command); return { state: view(m), result };
  },
  async advance(id, shifts = 1) {
    const m = missions.get(id); let events = [], samples = [];
    for (let i = 0; i < shifts && !m.over; i++) { const r = step(m); events = events.concat(r.events); samples = samples.concat(r.samples); }
    // telemetry: replay the shift's hourly samples over ~1.5 s
    samples.forEach((x, i) => setTimeout(() => { const e = env(m, x.mission_time_h); emit(id, { t: "telemetry", ...x, sun_elev_deg: e.sun_elev_deg, earth_elev_deg: e.earth_elev_deg, comm: e.earth_visible ? "open" : "closed", loads: { ...m.loads }, alerts: [] }); }, 250 * i));
    const s = view(m);
    const say = m.over ? m.why : events.length ? events.map(e => e.text).join(" ") : `Day ${s.day}, shift ${s.shift}. ` + statusLine(s);
    return { state: s, events, say };
  },
  async debrief(id) {
    const m = missions.get(id), s = view(m);
    const grade = m.outcome === "fail" ? (m.t > 120 ? "C" : "D") : s.resources.dose_msv < 20 && m.score > 300 ? "A" : "B";
    return {
      score: Math.round(m.score), grade, outcome: m.outcome || "in_progress", why: m.why || "Mission ended early.", timeline: m.timeline, sample: true,
      lessons: [], data_used: [
        { name: "NASA DONKI (space weather database)", url: DONKI, how: "The solar storms are real events, with their real dates." },
        { name: "JPL Horizons", url: HORIZONS, how: "Where the Sun and Earth are in the sky at your site." },
        { name: "LRO LOLA", url: LOLA, how: "How much sunlight each site gets, and where the ice is." },
      ],
    };
  },
  /** Fake WS /ws/mission/{mid}. */
  subscribe(id, fn) { const l = listeners.get(id) || []; l.push(fn); listeners.set(id, l); return () => listeners.set(id, (listeners.get(id) || []).filter(x => x !== fn)); },
};

/** The mock's stand-in for the command layer: a few phrases → Command. Null when it isn't a mission command. */
export function parseCommand(text) {
  const t = text.toLowerCase().replace(/[^a-z0-9% ]+/g, " ").replace(/\s+/g, " ").trim();
  if (/^(yes|yeah|yep|confirm|do it|affirmative)\b/.test(t)) return { type: "confirm" };
  if (/^(no|nope|cancel|never mind|stop)\b/.test(t)) return { type: "cancel" };
  if (/\b(end|next|finish)( the)? shift\b|^next$/.test(t)) return { type: "end_shift" };
  if (/\b(call|talk to|ask) (houston|earth|mission control)\b/.test(t)) return { type: "call_houston", text };
  if (/\b(shelter|hide)\b/.test(t)) return { type: "shelter", on: !/\b(leave|out of|exit|off)\b/.test(t) };
  if (/\brover\b/.test(t) && /\b(ice|water)\b/.test(t)) return { type: "dispatch", vehicle: "rover", task: "collect_ice", target: null };
  if (/\brover\b/.test(t) && /\b(fix|repair)\b/.test(t)) return { type: "dispatch", vehicle: "rover", task: "repair_array", target: null };
  if (/\brover\b/.test(t) && /\b(home|back|return)\b/.test(t)) return { type: "dispatch", vehicle: "rover", task: "return", target: null };
  if (/\b(send|drive)\b.*\brover\b|\brover\b.*\bexplore\b/.test(t)) return { type: "dispatch", vehicle: "rover", task: "explore", target: null };
  const load = /shield/.test(t) ? "shields" : /life support|oxygen|air/.test(t) ? "life_support" : /greenhouse|plants?/.test(t) ? "greenhouse"
    : /science/.test(t) ? "science" : /rover/.test(t) ? "rover" : /comm|radio/.test(t) ? "comms" : /heat/.test(t) ? "heaters" : null;
  if (/\b(how|what|status|check|left)\b/.test(t) && !/\b(put|set|turn|raise|lower|more|less)\b/.test(t)) {
    return { type: "query", what: load === "life_support" ? "life_support" : /power|battery/.test(t) ? "power" : /dose|radiation/.test(t) ? "dose" : /storm/.test(t) ? "storm" : "all" };
  }
  if (load) {
    const n = t.match(/(\d+)/); const v = n ? +n[1] : null;
    if (/\ball\b/.test(t)) return { type: "allocate", to: load, amount: { kind: "all", value: 100 }, from: null };
    if (/\bhalf\b/.test(t)) return { type: "allocate", to: load, amount: { kind: "half", value: 50 }, from: null };
    if (/\b(off|zero|none)\b/.test(t)) return { type: "allocate", to: load, amount: { kind: "none", value: 0 }, from: null };
    if (/\b(down|lower|less|reduce)\b/.test(t)) return { type: "allocate", to: load, amount: { kind: "delta", value: -(v || 10) }, from: null };
    if (v != null && /\b(to|at|set|put)\b/.test(t)) return { type: "allocate", to: load, amount: { kind: "percent", value: v }, from: null };
    if (/\b(up|raise|more|boost|increase|on)\b/.test(t)) return { type: "allocate", to: load, amount: { kind: "delta", value: v || 10 }, from: null };
  }
  return null;
}
