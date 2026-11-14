// Mission API client (docs/MISSION_CONTRACT.md). Uses the backend when GET /api/mission/sites answers; when it 404s
// (backend not shipped yet) everything runs on the local mock and `sample` is true.
import { mock } from "./mock.js";

async function j(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) { const e = new Error(url + " " + r.status); e.status = r.status; throw e; }
  return r.json();
}
const post = (url, body) => j(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export async function createMissionClient() {
  let real = true, sites;
  try { sites = await j("/api/mission/sites"); }
  catch (e) { real = false; sites = await mock.sites(); }
  if (!real) return { ...mock, sample: true, sites: sites.sites };
  const enc = encodeURIComponent;
  return {
    sample: false, sites: sites.sites,
    start: body => post("/api/mission/start", body),
    get: id => j("/api/mission/" + enc(id)),
    command: (id, command) => post(`/api/mission/${enc(id)}/command`, { command }),
    advance: (id, shifts = 1) => post(`/api/mission/${enc(id)}/advance`, { shifts }),
    /** The live clock: mission hours that passed (docs/GAMEPLAY.md). -> {state, events, live} */
    step: (id, dtH) => post(`/api/mission/${enc(id)}/step`, { dt_h: Math.max(0, Math.min(24, +dtH || 0)) }),
    /** Skip to next event. -> {state, events, say} */
    skip: id => post(`/api/mission/${enc(id)}/skip`, {}),
    debrief: id => j(`/api/mission/${enc(id)}/debrief`),
    /** Earth-up and Sun-up spans over the whole mission ([start_h, end_h]), by the sim's own rule. */
    windows: id => j(`/api/mission/${enc(id)}/windows`),
    /** WS /ws/mission/{mid} telemetry; reconnects with a back-off while subscribed (not for an unknown mission). */
    subscribe(id, fn) {
      let ws = null, stop = false, timer = null, wait = 1000;
      const open = () => {
        if (stop) return;
        try { ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/mission/" + enc(id)); } catch (e) { return; }
        ws.onopen = () => { wait = 1000; };
        ws.onmessage = e => { try { const m = JSON.parse(e.data); if (m && m.t === "telemetry") fn(m); } catch (_) { /* ignore */ } };
        // [qa] 4404 = the server doesn't know this mission (it restarted): stop; otherwise back off up to 15 s
        ws.onclose = e => { if (stop || (e && e.code === 4404)) return; timer = setTimeout(open, wait); wait = Math.min(15000, wait * 2); };
      };
      open();
      return () => { stop = true; clearTimeout(timer); try { ws && ws.close(); } catch (e) { /* closed */ } };
    },
  };
}
