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
  if (!real) return { sample: true, sites: sites.sites, ...mock };
  const enc = encodeURIComponent;
  return {
    sample: false, sites: sites.sites,
    start: body => post("/api/mission/start", body),
    get: id => j("/api/mission/" + enc(id)),
    command: (id, command) => post(`/api/mission/${enc(id)}/command`, { command }),
    advance: (id, shifts = 1) => post(`/api/mission/${enc(id)}/advance`, { shifts }),
    debrief: id => j(`/api/mission/${enc(id)}/debrief`),
    /** WS /ws/mission/{mid} telemetry; reconnects once a second while subscribed. */
    subscribe(id, fn) {
      let ws = null, stop = false, timer = null;
      const open = () => {
        if (stop) return;
        try { ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/mission/" + enc(id)); } catch (e) { return; }
        ws.onmessage = e => { try { const m = JSON.parse(e.data); if (m && m.t === "telemetry") fn(m); } catch (_) { /* ignore */ } };
        ws.onclose = () => { if (!stop) timer = setTimeout(open, 1000); };
      };
      open();
      return () => { stop = true; clearTimeout(timer); try { ws && ws.close(); } catch (e) { /* closed */ } };
    },
  };
}
