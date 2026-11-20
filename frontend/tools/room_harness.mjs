// Room-state harness (docs/HANDSFREE.md "Room state"): feeds the estimator (src/room.js) streams of 80 ms mic levels and
// per-turn messages, and reports per scenario: when it entered busy / loud, switches in a calm room, flapping, recovery.
//   node frontend/tools/room_harness.mjs            the table
//   node frontend/tools/room_harness.mjs --json     raw results
// Levels are real where the repo has them: the mic hiss floor and the six recorded room-noise beds (cabin / cafe / room)
// of tests/fixtures/barge (tools/barge_clips.py, 80 ms RMS of the mic chain), and the kid command clips' speech frames
// from the same set (SLURP / Mac voices at -22 dBFS). Babble at a given SNR is synthetic: that kid level minus the SNR,
// with talker-to-talker fluctuation (log-normal, sigma 0.35, the recorded beds' p20 / p50 ≈ 0.75). Seeded: deterministic.
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createRoom } from "../src/room.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIX = join(HERE, "..", "tests", "fixtures", "barge");
const FRAME = 80;

function rng(seed) { let a = seed >>> 0; return () => { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
const gauss = r => Math.sqrt(-2 * Math.log(r() || 1e-9)) * Math.cos(2 * Math.PI * r());

function loadFixtures() {
  const beds = [], speech = [];
  let hiss = 0.0012;
  try {
    for (const f of readdirSync(FIX)) {
      const d = JSON.parse(readFileSync(join(FIX, f), "utf8"));
      if (!Array.isArray(d.levels)) continue;
      if (d.kind === "noise") beds.push({ name: d.name, levels: d.levels });
      if (d.kind === "silence") hiss = d.levels.slice().sort((a, b) => a - b)[d.levels.length >> 1];
      if (d.kind === "command" && !/aec/.test(d.name)) speech.push(...d.levels.filter(x => x > 0.01));
    }
  } catch (e) { /* no fixtures: synthetic only */ }
  return { beds, speech: speech.length ? speech : [0.03, 0.04, 0.05, 0.02], hiss };
}
export const FIXTURES = loadFixtures();
const KID_DB = -22, db = x => 10 ** (x / 20);

/** A scenario: dur seconds; bed(t, r) → noise RMS; kid turns, chatter turns, fails; playing(t) → our audio audible. */
export function runScenario(sc, { tuning } = {}) {
  const r = rng(sc.seed || 1);
  let now = 0;
  const changes = [];
  const room = createRoom({ now: () => now, tuning, onChange: (s, p) => changes.push({ t: now / 1000, from: p.state, to: s.state, mode: s.mode, fromMode: p.mode }) });
  const turns = (sc.turns || []).slice().sort((a, b) => a.t - b.t);
  let ti = 0, kidUntil = -1;
  for (now = 0; now <= sc.dur * 1000; now += FRAME) {
    const t = now / 1000;
    while (ti < turns.length && turns[ti].t <= t) {
      const u = turns[ti++];
      if (u.speak) kidUntil = t + u.speak;                        // the kid's speech frames for this long
      const lo = u.lo ?? (room.filter("normal") === "strict" ? 0.65 : 0.5);
      if (u.held) room.held(u.held); else room.turn({ ...u, lo });
    }
    let rms = sc.bed(t, r);
    if (t < kidUntil) rms = Math.hypot(rms, FIXTURES.speech[Math.floor(r() * FIXTURES.speech.length)]);
    if (sc.burst && t >= sc.burst[0] && t < sc.burst[0] + sc.burst[1]) rms = Math.hypot(rms, sc.burst[2]);
    const playing = sc.playing ? sc.playing(t) : false;
    if (playing) rms = Math.hypot(rms, 0.03 * (0.5 + r()));       // our leak: skipped by the estimator
    room.frame(rms, { playing });
    if (Math.round(now) % 1000 === 0) room.tick();
  }
  const first = s => { const c = changes.find(x => x.to === s); return c ? +(c.t - (sc.from || 0)).toFixed(1) : null; };
  const firstMode = m => { const c = changes.find(x => x.mode === m); return c ? +(c.t - (sc.from || 0)).toFixed(1) : null; };
  // flapping: a state left and re-entered within 20 s
  let flaps = 0;
  for (let i = 2; i < changes.length; i++) if (changes[i].to === changes[i - 2].to && changes[i].to !== changes[i - 1].to && changes[i].t - changes[i - 2].t < 20) flaps++;
  const calmAt = sc.calmFrom != null ? changes.filter(c => c.to === "calm" && c.t >= sc.calmFrom).map(c => +(c.t - sc.calmFrom).toFixed(1))[0] ?? null : null;
  return { name: sc.name, switches: changes.filter(c => c.from !== c.to).length, busy: first("busy"), loud: first("loud"), hold: firstMode("hold"),
    offer: firstMode("offer"), type: firstMode("type"), recover: calmAt, flaps, end: room.state, endMode: room.mode, changes };
}

// ---- noise beds ----
const hissBed = (t, r) => Math.abs(FIXTURES.hiss * (1 + 0.05 * gauss(r)));
const recBed = i => {
  const b = FIXTURES.beds[i % Math.max(1, FIXTURES.beds.length)];
  return b ? (t => b.levels[Math.floor(t * 1000 / FRAME) % b.levels.length]) : ((t, r) => 0.024 * Math.exp(0.3 * gauss(r)));
};
const babble = snr => (t, r) => Math.hypot(FIXTURES.hiss, db(KID_DB - snr) * Math.exp(0.35 * gauss(r)));
const between = (a, b, inner, outer) => (t, r) => (t >= a && t < b ? inner(t, r) : outer(t, r));

// ---- turns ----
/** A kid talking to the app every `every` s: directed (dd ~0.85), the router takes it. */
const kidTurns = (dur, every, r, { from = 4, to = dur, dd = 0.85, outcome = "answer" } = {}) => {
  const out = []; for (let t = from + r() * every; t < to; t += every * (0.7 + 0.6 * r())) out.push({ t, text: "turn " + Math.round(t), outcome, dd, speak: 1.4, uconf: 0.8, snr: 6 });
  return out;
};
/** Room talk the open mic picks up: Arc rates it under the floor, the router ignores it. */
const chatterTurns = (from, to, every, r, reason = "not_directed") => {
  const out = []; for (let t = from + r() * every; t < to; t += every * (0.7 + 0.6 * r())) out.push({ t, text: "chat " + Math.round(t), outcome: "ignore", reason, dd: 0.25 + 0.2 * r(), uconf: 0.6 });
  return out;
};

export function scenarios() {
  const R = rng(42), S = [];
  const add = s => S.push({ seed: S.length + 1, ...s });
  add({ name: "quiet, kid talks (5 min)", dur: 300, bed: hissBed, turns: kidTurns(300, 8, R), playing: t => t % 12 < 5, expect: { switches: 0 } });
  add({ name: "quiet, kid's long answers", dur: 180, bed: hissBed, turns: kidTurns(180, 4.5, R).map(u => ({ ...u, speak: 2.6 })), expect: { switches: 0 } });
  add({ name: "quiet, a grown-up remark /40 s", dur: 300, bed: hissBed, turns: [...kidTurns(300, 10, R), ...chatterTurns(10, 300, 40, R)], expect: { switches: 0 } });
  add({ name: "quiet, one loud cheer (1.5 s)", dur: 120, bed: hissBed, burst: [40, 1.5, 0.25], turns: kidTurns(120, 9, R), expect: { switches: 0 } });
  add({ name: "quiet, door slams x3 in 20 s", dur: 120, bed: (t, r) => (t >= 30 && t < 50 && (t % 7) < 0.6 ? 0.3 : hissBed(t, r)), turns: kidTurns(120, 9, R), expect: { switches: 0 } });
  FIXTURES.beds.forEach((b, i) => add({ name: `recorded bed ${b.name}`, dur: 120, bed: recBed(i), turns: kidTurns(120, 8, R), expect: { busy: "<=10" } }));
  [25, 20, 15, 10, 5, 0].forEach(snr => add({ name: `babble SNR ${snr} dB`, dur: 120, bed: babble(snr), turns: kidTurns(120, 8, R) }));
  add({ name: "2 kids chatting near the mic (quiet floor)", dur: 120, bed: hissBed, turns: [...kidTurns(120, 15, R), ...chatterTurns(5, 120, 5, R)], expect: { busy: "<=30", hold: "<=40" } });
  add({ name: "busy bed + chatter turns", dur: 120, bed: babble(15), turns: [...kidTurns(120, 12, R), ...chatterTurns(5, 120, 6, R, "crew_talk")], expect: { hold: "<=40" } });
  add({ name: "voice keeps failing (Didn't catch that)", dur: 120, bed: babble(8), turns: [...Array(12)].map((_, i) => ({ t: 6 + i * 8, text: "fail " + i, outcome: "ignore", notice: true, dd: 0.8 })), expect: { loud: "<=40", type: "<=70" } });
  add({ name: "loud room (SNR 0) then quiet", dur: 240, bed: between(0, 90, babble(0), hissBed), calmFrom: 90, turns: kidTurns(240, 8, R) });
  add({ name: "classroom babble 60 s then quiet", dur: 200, bed: between(0, 60, babble(10), hissBed), calmFrom: 60, turns: kidTurns(200, 8, R), expect: { recover: "<=30" } });
  add({ name: "chatter spell 60 s then quiet", dur: 200, bed: hissBed, calmFrom: 60, turns: [...kidTurns(200, 12, R), ...chatterTurns(0, 60, 5, R)], expect: { recover: "<=45" } });
  add({ name: "floor wobbling at the busy edge", dur: 300, bed: (t, r) => Math.hypot(FIXTURES.hiss, (0.0125 + 0.006 * Math.sin(t / 9)) * Math.exp(0.2 * gauss(r))), turns: kidTurns(300, 8, R), expect: { flaps: 0 } });
  add({ name: "floor swinging across both edges", dur: 300, bed: (t, r) => Math.hypot(FIXTURES.hiss, (0.012 + 0.01 * Math.sin(t / 12)) * Math.exp(0.2 * gauss(r))), turns: kidTurns(300, 8, R), expect: { flaps: 0 } });
  add({ name: "busy bed, our audio playing a lot", dur: 120, bed: babble(10), playing: t => t % 10 < 7, turns: kidTurns(120, 8, R), expect: { busy: "<=25" } });
  return S;
}

function check(res, exp = {}) {
  const bad = [];
  for (const [k, v] of Object.entries(exp)) {
    const got = res[k];
    if (typeof v === "number" && got !== v) bad.push(`${k}=${got} (want ${v})`);
    if (typeof v === "string" && v.startsWith("<=") && !(got != null && got <= +v.slice(2))) bad.push(`${k}=${got} (want ${v})`);
  }
  if (res.flaps) bad.push(`flaps=${res.flaps}`);
  return bad;
}

export function runAll(opts) { return scenarios().map(sc => { const r = runScenario(sc, opts); return { ...r, problems: check(r, sc.expect) }; }); }

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const rows = runAll();
  if (process.argv.includes("--json")) { console.log(JSON.stringify(rows.map(({ changes, ...r }) => r), null, 1)); process.exit(0); }
  const f = v => (v == null ? "-" : String(v));
  console.log("| scenario | busy at s | loud at s | hold at s | offer / type at s | switches | flaps | recover s | end | ok |");
  console.log("|---|---|---|---|---|---|---|---|---|---|");
  for (const r of rows) console.log(`| ${r.name} | ${f(r.busy)} | ${f(r.loud)} | ${f(r.hold)} | ${f(r.offer)} / ${f(r.type)} | ${r.switches} | ${r.flaps} | ${f(r.recover)} | ${r.end}/${r.endMode} | ${r.problems.length ? r.problems.join("; ") : "yes"} |`);
  process.exit(rows.some(r => r.problems.length) ? 1 : 0);
}
