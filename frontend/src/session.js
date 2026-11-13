// Session Director client (docs/SESSION_CONTRACT.md): one socket, WS /ws/session. Sends hello / ui / typed / playback;
// receives typed decisions and dispatches them to the app's modules through `handlers`.
//
// Ordering: visual decisions (card, hud, alert, fly, highlight, floor, lesson) apply at once. Speech (say, play) is one
// voice at a time, in priority order (0 first), then arrival. A decision with `after` waits until that id is done.
// `cancel` drops unplayed decisions and stops the one playing if it is listed (barge-in, newer turn).

const VISUAL = new Set(["card", "hud", "alert", "fly", "highlight", "floor", "lesson", "ask_confirm"]);
const SPEECH = new Set(["say", "play"]);

function sessionId() {
  const k = "atm-session-id";
  try { const v = sessionStorage.getItem(k); if (v) return v; } catch (e) { /* private mode */ }
  const id = "s-" + Math.random().toString(36).slice(2, 10);
  try { sessionStorage.setItem(k, id); } catch (e) { /* private mode */ }
  return id;
}

/**
 * @param {object} o
 * @param {object} o.handlers  {say(d)→Promise, play(d)→Promise, stop(), card, hud, alert, fly, highlight, ask_confirm, lesson, floor}
 * @param {boolean} [o.reportsPlayback]  true when a floor manager reports playback events itself
 * @param {()=>void} [o.onClose]
 */
export function createSession({ handlers, reportsPlayback = false, onClose = () => {} }) {
  const id = sessionId();
  let ws = null, connected = false, lastHello = null;
  const done = new Set(), cancelled = new Set();
  const waiting = new Map();          // after-id -> [decisions]
  let queue = [], current = null, seq = 0;
  const log = [];                     // last 100 decisions received (debugging: window.__atmSession.log)

  const url = () => (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/session";
  const send = (m) => { if (ws && ws.readyState === 1) { ws.send(JSON.stringify({ ts: Date.now(), ...m })); return true; } return false; };

  function connect(timeoutMs = 3000) {
    return new Promise(res => {
      try { ws = new WebSocket(url()); } catch (e) { return res(false); }
      const t = setTimeout(() => { if (!connected) { try { ws.close(); } catch (e) { /* */ } res(false); } }, timeoutMs);
      ws.onopen = () => send(lastHello || { t: "hello", session: id, mode: "mission" });
      ws.onmessage = ev => {
        let d; try { d = JSON.parse(ev.data); } catch (e) { return; }
        if (d.t === "ready") { connected = true; clearTimeout(t); res(true); return; }
        if (d.t === "error") { console.warn("session:", d.message); return; }
        log.push({ t: d.t, id: d.id, priority: d.priority, after: d.after, text: d.text || d.body || d.level, at: Date.now() }); log.splice(0, log.length - 100);
        receive(d);
      };
      ws.onclose = () => { const was = connected; connected = false; clearTimeout(t); if (!was) res(false); else onClose(); };
      ws.onerror = () => {};
    });
  }

  function finish(did) {
    if (!did || done.has(did)) return;
    done.add(did);
    const deps = waiting.get(did); waiting.delete(did);
    (deps || []).forEach(receive);
  }

  function receive(d) {
    if (d.t === "cancel") return cancel(d.ids || []);
    if (cancelled.has(d.id)) return;
    if (d.after && !done.has(d.after)) {
      if (cancelled.has(d.after)) { cancelled.add(d.id); return; }
      const w = waiting.get(d.after) || []; w.push(d); waiting.set(d.after, w); return;
    }
    if (VISUAL.has(d.t)) {
      try { const h = handlers[d.t]; if (h) h(d); } catch (e) { console.warn("session handler", d.t, e); }
      finish(d.id); return;
    }
    if (SPEECH.has(d.t)) {
      queue.push({ d, n: seq++ });
      queue.sort((a, b) => (a.d.priority ?? 3) - (b.d.priority ?? 3) || a.n - b.n);
      pump(); return;
    }
    finish(d.id);   // unknown decision types: ignored (clients ignore unknown fields/types)
  }

  async function pump() {
    if (current || !queue.length) return;
    const { d } = queue.shift();
    if (cancelled.has(d.id)) { pump(); return; }
    const kind = d.t === "play" ? "crew" : "guide";
    current = d;
    if (!reportsPlayback) send({ t: "playback", kind, state: "start", id: d.id });
    let interrupted = false;
    try { await (handlers[d.t] ? handlers[d.t](d) : null); } catch (e) { interrupted = true; }
    if (cancelled.has(d.id)) interrupted = true;
    if (!reportsPlayback) send({ t: "playback", kind, state: interrupted ? "interrupted" : "end", id: d.id });
    current = null;
    if (!interrupted) finish(d.id);
    else cancelDeps(d.id);
    pump();
  }

  function cancelDeps(did) {
    const deps = waiting.get(did) || []; waiting.delete(did);
    deps.forEach(x => { cancelled.add(x.id); cancelDeps(x.id); });
  }

  function cancel(ids) {
    ids.forEach(i => { cancelled.add(i); cancelDeps(i); });
    queue = queue.filter(q => !cancelled.has(q.d.id));
    if (current && cancelled.has(current.id) && handlers.stop) handlers.stop(current);
  }

  const api = {
    id, connect, log,
    get connected() { return connected; },
    get busy() { return !!current || queue.length > 0; },
    hello(o = {}) { lastHello = { t: "hello", session: id, ...o }; return send(lastHello); },
    typed(text, source) { return send({ t: "typed", text, ...(source ? { source } : {}) }); },
    ui(event, extra = {}) { return send({ t: "ui", event, ...extra }); },
    playback(e) { return send({ t: "playback", ...e }); },
    /** A card/confirm action's `send` payload ({t:"typed",text} or {t:"ui",…}). */
    sendRaw(m) { return m && m.t ? send(m) : false; },
    /** Local cancel of everything unplayed (e.g. the kid pressed Space before the server's cancel arrives). */
    dropAll() { cancel([...(current ? [current.id] : []), ...queue.map(q => q.d.id)]); },
    close() { try { ws && ws.close(); } catch (e) { /* */ } },
  };
  try { window.__atmSession = api; } catch (e) { /* no window */ }
  return api;
}
