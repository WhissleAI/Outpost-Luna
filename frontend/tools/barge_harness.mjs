// Barge-in harness, stage 2 (SILENT: no audio device is touched; the "speaker" is a fake <audio> that only keeps time).
//
// Replays what the real ear heard (tests/fixtures/barge/*.json, recorded by tools/barge_clips.py through WS /ws/listen)
// into the REAL voice.js + floor.js, in real time, while CAPCOM's line "plays": the per-frame mic levels go to the
// listener's level() and the ear's words / turn / arc messages to its message(), at the times the ear sent them.
// Then it reports whether the line was cut, when, and whether it was finished (or said again after a false barge-in).
//
//   node tools/barge_harness.mjs                         # every fixture, this checkout's src/ (after)
//   node tools/barge_harness.mjs --src /tmp/before/src   # the same against another copy of src/ (before)
//   node tools/barge_harness.mjs --one tests/fixtures/barge/os_stop.json --src src   (one case, JSON out)
import { readFileSync, readdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONT = path.resolve(HERE, "..");
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };

const OPTIONS = ["A radiation dose", "A kind of rocket", "Moon soil"];
const FEEDBACK = "Correct. One mSv is about 10 chest x-rays.";

async function runOne(file, src) {
  const fx = JSON.parse(readFileSync(file, "utf8"));
  // ---- a tiny DOM + browser surface (what voice.js and floor.js touch), as in tests/voice_gate.test.js ----
  const el = () => { const cls = new Set(); return { classList: { add: (...c) => c.forEach(x => cls.add(x)), remove: (...c) => c.forEach(x => cls.delete(x)), toggle: (c, on) => (on ?? !cls.has(c)) ? cls.add(c) : cls.delete(c), contains: c => cls.has(c) },
    style: { setProperty() {} }, setAttribute() {}, insertBefore() {}, append() {}, textContent: "", title: "", hidden: false, lastElementChild: { textContent: "" } }; };
  const els = {};
  globalThis.window = globalThis;
  globalThis.document = { getElementById: id => (els[id] = els[id] || el()), createElement: () => el(), activeElement: null };
  const events = [];
  globalThis.addEventListener = () => {}; globalThis.removeEventListener = () => {};
  globalThis.dispatchEvent = e => { events.push({ type: e.type, detail: e.detail }); return true; };
  globalThis.CustomEvent = class { constructor(type, o = {}) { this.type = type; this.detail = o.detail; } };
  // The speaker: each sentence's clip lasts its share of the line's real length (fixture line_s / warm_s).
  const durOf = new Map(); let blobN = 0;
  const lineLen = t => (t === fx.warm ? fx.warm_s : fx.line_s);
  const full = [fx.warm, fx.line, FEEDBACK];
  globalThis.fetch = async url => {
    const text = new URL(url, "http://x").searchParams.get("text") || "";
    const owner = full.find(f => f && f.includes(text)) || text;
    const share = text.length / Math.max(1, owner.length);
    const d = owner === text || !full.includes(owner) ? (lineLen(owner) || text.split(" ").length * 0.33) : lineLen(owner) * share;
    return { status: 200, ok: true, blob: async () => ({ d, text, owner }), headers: { get: () => "" } };
  };
  URL.createObjectURL = b => { const u = "blob:" + ++blobN; durOf.set(u, (b && b.d) || 1); return u; };
  URL.revokeObjectURL = () => {};
  globalThis.Audio = class {
    constructor() { this.paused = true; this.duration = NaN; this._t = 0; }
    setAttribute() {} removeAttribute() {} load() {}
    set src(u) { this._src = u; this.duration = durOf.get(u) || 1; } get src() { return this._src; }
    get currentTime() { return this.paused || !this._at ? 0 : (performance.now() - this._at) / 1000; }
    play() { this.paused = false; this._at = performance.now(); clearTimeout(this._t); setTimeout(() => this.onplaying && this.onplaying(), 0);
      this._t = setTimeout(() => { this.paused = true; this.onended && this.onended(); }, this.duration * 1000); return Promise.resolve(); }
    pause() { this.paused = true; clearTimeout(this._t); }
  };
  const { createFloor } = await import(pathToFileURL(path.join(src, "floor.js")).href);
  const { createVoice } = await import(pathToFileURL(path.join(src, "voice.js")).href);
  if (process.env.BARGE_TUNE) {   // tuning sweeps: BARGE_TUNE='{"ENERGY_LEAK_X":1.6}'
    try { Object.assign((await import(pathToFileURL(path.join(src, "barge.js")).href)).BARGE_TUNING, JSON.parse(process.env.BARGE_TUNE)); } catch (e) { /* before: no barge.js */ }
  }

  const t0 = performance.now(), wall0 = Date.now(), now = () => Math.round(performance.now() - t0);
  let frame = { screen: "lesson", step_type: "choice", step_options: OPTIONS, lesson_id: "radiation", step: 4 };
  // the app decodes the TTS clip it plays into an envelope (floor.js envelopeOf); here: the clean line's 80 ms RMS
  const envelope = blob => {
    const env = blob.owner === fx.line ? fx.line_env : blob.owner === fx.warm ? fx.warm_env : null;
    if (!env) return null;
    const a = Math.max(0, blob.owner.indexOf(blob.text)) / blob.owner.length, n = blob.text.length / blob.owner.length;
    return Float32Array.from(env.slice(Math.round(a * env.length), Math.round((a + n) * env.length)));
  };
  const floor = createFloor({ envelope });
  let lastTrace = "";
  if (process.env.BARGE_TRACE) globalThis.__bargeTrace = x => { const k = x.d.act + ":" + x.d.reason + ":" + (x.en ? x.en.loud : "-");
    if (k !== lastTrace) { lastTrace = k; console.error(now(), k, JSON.stringify(x.text), x.en && { c: x.en.coupling && +x.en.coupling.toFixed(3), turn: +x.en.turn.toFixed(3) }, x.dd); } };
  const res = { name: fx.name, kind: fx.kind, expect: fx.expect, stops: [], turns: [], resumed: 0, lineDone: false, cut: null, answered: false, nav: false };
  const plays = new Map();
  floor.on("playback", e => {
    if (e.state === "start") plays.set(e.id, e.text || "");
    else if (e.kind === "guide" && e.state === "end" && (plays.get(e.id) || "").endsWith(fx.line.split(/(?<=[.?!])\s+/).pop()) && now() >= fx.line_at * 1000) res.lineDone = true;
  });
  const stopGuide = floor.stopGuide;
  floor.stopGuide = (...a) => {
    const busy = floor.guideBusy && floor.guideText === fx.line;
    if (busy && res.cut == null) res.cut = now();
    if (busy) res.stops.push({ at: now(), reason: a[0] || "(none)" });
    return stopGuide(...a);
  };
  const resume = floor.resumeInterrupted;
  if (resume) floor.resumeInterrupted = (...a) => { res.resumed++; return resume(...a); };
  let ear = null;
  createVoice({
    onTurn: async text => {
      res.turns.push({ at: now(), text });
      const q = text.toLowerCase();
      // the app's side, simplified: an answer is graded and CAPCOM says so; "next" / "map" navigate; stop words: quiet
      if (/radiation|dose/.test(q)) { res.answered = true; floor.say(FEEDBACK, { voice: "capcom" }); }
      else if (/\b(next|map)\b/.test(q)) { res.nav = true; frame = { screen: "map" }; }
    },
    onBargeIn() {}, onKidDone() {}, onEmotion() {},
    screen: () => frame, floor,
    createListener: on => { ear = on; return { start: async () => false, stop() {}, send() {} }; },
  });
  const at = (ms, fn) => setTimeout(fn, Math.max(0, ms - (performance.now() - t0)));
  ear.message({ t: "ready" });
  at(fx.warm_at * 1000, () => floor.say(fx.warm, { voice: "capcom" }));
  at(fx.line_at * 1000, () => { res.lineSay = floor.say(fx.line, { voice: "capcom" }); });
  fx.levels.forEach((r, k) => at((k + 1) * fx.frame_ms, () => ear.level && ear.level(r)));
  let prev = 0;   // the ear's order is the order it sent them (a slow decode call can stamp a message a little late)
  for (const m of fx.ear) { prev = Math.max(prev, m.ms); at(prev, () => { const { ms, ...msg } = m; ear.message(msg); }); }
  const end = Math.max(fx.levels.length * fx.frame_ms, (fx.line_at + fx.line_s) * 1000) + 5000;
  await new Promise(r => at(end, r));
  const onset = fx.onset_s != null ? fx.onset_s * 1000 : null;
  res.onsetMs = onset;
  res.latencyMs = res.cut != null && onset != null ? res.cut - onset : null;
  // the ear's own latency for the same words (first message after the onset carrying one of the spoken words)
  if (onset != null && fx.said) {
    const keys = String(fx.said).toLowerCase().match(/[a-z]+/g).filter(w => w.length > 2);
    const hit = fx.ear.find(m => m.ms >= onset && m.text && keys.some(k => m.text.toLowerCase().includes(k)));
    res.earMs = hit ? hit.ms - onset : null;
  }
  const BL = globalThis.__outpost && globalThis.__outpost.bargeLog;
  res.log = BL ? { counts: { ...BL.counts }, entries: BL.map(e => ({ ...e, at: e.at - wall0 })) } : null;
  res.bargeEvents = events.filter(e => e.type === "outpost:barge").length;
  delete res.lineSay;
  return res;
}

function verdict(r) {
  // a cut before the kid spoke was the echo / noise, not the kid: for a command case that is a failure too
  const early = r.cut != null && r.onsetMs != null && r.cut < r.onsetMs - 100;
  const barged = r.cut != null && !early;
  if (early) return "FAIL";
  if (r.expect === "no_barge") return !barged && r.lineDone ? "PASS" : "FAIL";
  if (r.expect === "barge_answer") return barged && r.answered ? "PASS" : "FAIL";
  return barged && r.latencyMs != null && r.latencyMs <= 1200 ? "PASS" : "FAIL";
}

if (arg("--one")) {
  const r = await runOne(arg("--one"), path.resolve(arg("--src", path.join(FRONT, "src"))));
  process.stdout.write(JSON.stringify(r) + "\n");
  process.exit(0);
} else {
  const src = path.resolve(arg("--src", path.join(FRONT, "src")));
  const dir = path.join(FRONT, "tests/fixtures/barge");
  const files = readdirSync(dir).filter(f => f.endsWith(".json")).sort().map(f => path.join(dir, f));
  const par = +arg("--par", 4), out = [];
  let i = 0;
  const work = async () => { while (i < files.length) { const f = files[i++];
    const txt = await new Promise(res => { const p = spawn("nice", ["-n", "10", process.execPath, fileURLToPath(import.meta.url), "--one", f, "--src", src]);
      let o = ""; p.stdout.on("data", d => { o += d; }); p.stderr.on("data", d => { process.stderr.write(d); }); p.on("close", () => res(o)); });
    try { out.push(JSON.parse(txt.trim().split("\n").pop())); } catch (e) { out.push({ name: path.basename(f), error: txt.slice(0, 300) }); } } };
  await Promise.all(Array.from({ length: par }, work));
  out.sort((a, b) => (a.kind || "").localeCompare(b.kind || "") || a.name.localeCompare(b.name));
  for (const r of out) r.verdict = r.error ? "ERROR" : verdict(r);
  if (process.argv.includes("--json")) process.stdout.write(JSON.stringify(out, null, 1) + "\n");
  else for (const r of out) console.log([r.verdict.padEnd(5), (r.kind || "").padEnd(8), r.name.padEnd(28), "cut=" + (r.cut ?? "-"), "lat=" + (r.latencyMs ?? "-"), "ear=" + (r.earMs ?? "-"),
    "done=" + r.lineDone, "resumed=" + r.resumed, "answered=" + r.answered, JSON.stringify(r.log && r.log.counts)].join(" "));
}
