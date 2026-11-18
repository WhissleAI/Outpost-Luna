// Guidance for Flight School steps (docs/PLAYTEST.md §Guidance). A 7-year-old who knows nothing about the Moon must
// always see what to do: a step never asks for a place without showing it (or, when the step tests finding it, the
// hint ladder below), no unlabelled dots, a one-line "how this works" the first time a kind of step appears, and every
// miss says what to do next.
//
// The ladder (rungs come from the server, backend/app/academy/guide.py): highlight, then label, then show.
//   0  the prompt + one "do this" line; places the step names but doesn't test (step.show) carry labels; step.ring
//      draws a gold ring. A find-a-place step opens at rung 1: its target already glows (novice playtest #5)
//   1  first miss (or "help"): the target glows (no name) and the globe turns toward it; the terminator line glows
//   2  second miss (or "help" again): the target gets its label; a wrong card is crossed out; the order button
//      glows; the words appear
//   3  "help" a third time: CAPCOM shows it (the camera flies there, the right card glows) and the kid taps it;
//      a third real miss: CAPCOM shows the answer and moves on (routes.py)
// Pure helpers (marks, doLine, intro) are unit-tested in frontend/tests/guide.test.js.

/** The "do this" line under the question, per step type (a step's own `do` wins). ≤ 10 words, docs/COPY.md. */
export const DO = {
  intent: "Tap the glowing ring, or say its name", tap: "Tap the glowing ring, or say its name",
  route: "Tap the glowing places in order: 1, then 2", terminator: "Tap where light turns to dark",
  globe_side: "Drag the Moon to turn it, or tap a side", compare: "Tap a card or a pin, or say its name",
  predict: "Guess first. Any guess is fine", earth_view: "Tap Yes, No or Sometimes, or say it",
  choice: "Tap an answer, or say it", command: "Tap an order, or say it",
  keywords: "Say the order back, or type it", vocab_match: "Tap the meaning, or say it",
  vocab_fill: "Tap the missing word, or say it", vocab_say: "Say the word out loud", vocab_listen: "Listen, then tap the word, or say it",
  video: "Pick a guess. Then tap Watch, or Skip",
  // Field School (0.5): reports that build up over turns
  describe: "Say what you see, or tap the words", sequence: "Say them in order, or tap them",
  rounds: "Tap an answer, or say it",
};
/** A video step with nothing to guess ("Watch the bright part grow"): no "Guess first" (novice playtest #7). */
const DO_VIDEO_PLAIN = "Tap Watch, or Skip";
/** The first time a kind of step appears: one line on how it works (spoken once too). */
export const INTRO = {
  intent: "New: find a place. Tap the glowing ring.", tap: "New: find a place. Tap the glowing ring.",
  route: "New: trace a path. Tap the glowing places in order.", terminator: "New: the Sun lights half the Moon. Find the edge.",
  globe_side: "New: you can spin the Moon. Drag it, or tap a side.", compare: "New: two outposts. Pick one, then see the numbers.",
  predict: "New: a guess. There's no wrong guess here.", earth_view: "New: imagine standing there and looking up.",
  command: "New: give an order. Tap a button, or say it.", keywords: "New: radio practice. Say the order back.",
  video: "New: a NASA video. Guess first, then watch.",
  describe: "New: a crew report. Say what you see, bit by bit.",
  sequence: "New: a readback in order. One at a time is fine.",
  rounds: "New: a few quick rounds, one answer each.",
};
/** [0.3.12] The intro without its "New:" label: the card shows "New" as a chip, and TTS / captions never say "New:". */
export const introText = t => String(t || "").replace(/^\s*New:\s*/i, "").replace(/^./, c => c.toUpperCase());
/** [0.3.12] Predict before watch: where a Try-at-home lesson's "Watch how" videos go. In the Brief (behind its
 *  disclosure) until the first answer is in, then under the first step's feedback; never on the ride. null: none. */
export function prepPlace(L, i, answered) {
  if (!L || !L.prep || L.ride) return null;
  return i === 0 && answered ? "step" : "brief";
}
/** The prep's videos, NASA's first. `nasaOnly` (a core lesson's card): third-party extras ("Not from NASA") stay on the
 *  Try-at-home card, off the core steps. */
export function prepVideos(catalog, prepId, { nasaOnly = false } = {}) {
  return (catalog || []).filter(v => v.prep === prepId && (!nasaOnly || v.nasa !== false))
    .sort((a, b) => (b.nasa !== false) - (a.nasa !== false));
}
/** With the camera on: the same line, saying the gesture (≤ 10 words). `want` fills in the side / answer. */
export const DO_GESTURE = {
  globe_side: w => `Make a fist and turn it, or point at ${w === "near" ? "Near" : "Far"} side`,
  choice: () => "Thumbs up or down, show fingers, or point", earth_view: () => "Thumbs up for yes, down for no, or 3 fingers",
  predict: () => "Show fingers to pick, or point at one", compare: () => "Show fingers to pick, or point at one",
  video: () => "Thumbs up to watch, thumbs down to skip",
};
/** The "do this" line; `gesture`: the camera is on (a step's own `do` still wins). */
export const doLine = (st, { gesture = false } = {}) => {
  if (!st) return "";
  if (st.do) return st.do;
  const kind = (st.accept || {}).type, g = gesture && DO_GESTURE[kind];
  if (kind === "video" && !((st.accept || {}).guess || {}).options) return g ? g() : DO_VIDEO_PLAIN;
  return (g ? g((st.accept || {}).want) : DO[kind]) || "";
};

/** [audit2] "What do I do?" in a step: the do-line, then the hint, unless the hint says the same thing (then the hint
 *  alone). Before, "Drag the Moon to turn it, or tap a side. Tap Far, or drag the Moon around." said it twice. */
export function helpLine(doL, hint) {
  const ws = t => new Set(String(t || "").toLowerCase().replace(/[^a-z ]/g, " ").split(/\s+/).filter(w => w.length > 2));
  const a = ws(doL), b = ws(hint);
  if (!hint) return doL;
  if (!doL) return hint;
  const shared = [...a].filter(w => b.has(w)).length;
  const end = s => String(s).trim().replace(/[.!?]*$/, ".");
  return shared / Math.max(1, Math.min(a.size, b.size)) >= 0.4 ? end(hint) : `${end(doL)} ${end(hint)}`;
}

/** First use of a step type on this device? (localStorage; private mode: always "seen" after the first call) */
const SEEN_KEY = "outpost-seen-steps";
let seenMem = null;
export function firstUse(type, storage = typeof localStorage !== "undefined" ? localStorage : null) {
  if (!INTRO[type]) return false;
  if (type === "tap") type = "intent";   // the same kind of step for a kid (one intro, never "New:" twice: playtest #30)
  if (!seenMem) { try { seenMem = new Set(JSON.parse((storage && storage.getItem(SEEN_KEY)) || "[]")); } catch (e) { seenMem = new Set(); } }
  if (seenMem.has(type)) return false;
  seenMem.add(type);
  try { storage && storage.setItem(SEEN_KEY, JSON.stringify([...seenMem])); } catch (e) { /* private mode */ }
  return true;
}
export function resetSeen() { seenMem = null; }

const short = f => String((f && f.name) || "").split(" (")[0].replace(/^Mare | Basin$/g, "");   // "Orientale", as the prompts say it
const degR = f => Math.max(2.5, ((f && (f.km || f.diameter_km)) || 60) / 2 / 30.3);

/**
 * The marks on the Moon for a step at a rung.
 * @param st     the step (public course.json shape)
 * @param g      {rung, focus:[ids], label:[ids], line_lon, label_line, done, after:[ids]} — the guidance state
 * @param find   id -> {lat, lon, name, km} | null
 * @returns [{id, lat, lon, label?, num?, pulse?, ring?, gold?, r}]
 */
export function marks(st, g, find) {
  const acc = (st && st.accept) || {}, out = [];
  // the step's target carries the word the prompt uses ("Cabeus crater"), not the hardware's name (playtest #6)
  const nameOf = id => (acc.label && (id === acc.place || (acc.also || []).includes(id)) ? acc.label : short(find(id)));
  const line = (lon, label) => {   // the day/night edge as a glowing dotted line, pole to pole, labelled at the middle
    for (let lat = -80; lat <= 80; lat += 4) out.push({ id: "t" + lat, lat, lon, r: 0.7, line: true, pulse: true, label: label && lat === 0 ? "Day meets night" : undefined });
  };
  const add = (id, o) => {   // one mark per place: a later rule adds to it (a shown stop that is also the focus pulses)
    const f = find(id); if (!f) return;
    const had = out.find(m => m.id === id);
    if (had) { had.pulse = had.pulse || o.pulse; had.ring = had.ring || o.ring; had.label = had.label || o.label; return; }
    out.push({ id, lat: f.lat, lon: f.lon, r: degR(f), ...o });
  };
  if (g.done) {   // after the answer: what the step taught, named (e.g. Integrity, halfway along the route)
    (st.show || []).forEach(id => add(id, { label: short(find(id)) }));
    (g.after || []).forEach(id => add(id, { label: short(find(id)), pulse: true }));
    if (acc.type === "terminator" && g.line_lon != null) line(g.line_lon, true);   // "Here it is" points at the line
    if ((acc.type === "intent" || acc.type === "tap") && acc.place) add(acc.place, { ring: true, label: nameOf(acc.place) });
    return out;
  }
  const stops = acc.type === "route" ? acc.stops || [] : [];
  (st.show || []).forEach(id => {
    const k = stops.indexOf(id);
    add(id, { label: short(find(id)), num: k >= 0 ? k + 1 : undefined, pulse: k >= 0 && k === (g.next || 0), ring: true, above: k < 0 });   // a shown place names itself above its ring, clear of answer pins below
  });
  (st.ring || []).forEach(id => add(id, { ring: true, gold: true, pulse: true }));
  if (g.rung >= 1) (g.focus || []).forEach(id => add(id, { ring: true, pulse: true, label: g.rung >= 2 && (g.label || []).includes(id) ? nameOf(id) : undefined }));
  if (g.line_lon != null) line(g.line_lon, g.label_line);
  return out;
}

/** Where the step's first mark is, if the camera should turn to it (it's round the back or near the edge). */
export function needsTurn(m, project) {
  if (!m) return false;
  const p = project(m.lat, m.lon);
  return !p.facing || (p.depth != null && p.depth < 0.45);
}
