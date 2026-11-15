// window.__outpost.bargeLog: every reason the app stopped (or refused to stop) its own voice, newest last.
// Each entry: {at, kind, reason, text, energy, ms, playing, dd}
//   kind "stop"      a path that stopped TTS fired (floor.stopGuide / a say replaced / a critical alert took the floor)
//   kind "barge"     the open mic interrupted a line (reason: speech | command | ptt | awaited)
//   kind "held"      open-mic speech heard while a line played that did NOT interrupt it (echo, not_directed, …)
//   kind "resume"    a false interruption: the interrupted sentence was said again
// bargeLog.counts["<kind>:<reason>"] counts them. No imports: floor.js and voice.js both write here.
const MAX = 200;

function store() {
  if (typeof window === "undefined") return null;
  const o = (window.__outpost = window.__outpost || {});
  if (!Array.isArray(o.bargeLog)) { const a = []; a.counts = {}; o.bargeLog = a; }
  return o.bargeLog;
}

export function logBarge(entry) {
  const log = store();
  const e = { at: Date.now(), ...entry };
  if (!log) return e;
  log.push(e); if (log.length > MAX) log.splice(0, log.length - MAX);
  const k = `${e.kind}:${e.reason}`; log.counts[k] = (log.counts[k] || 0) + 1;
  return e;
}

export function bargeCounts() { const log = store(); return log ? { ...log.counts } : {}; }
