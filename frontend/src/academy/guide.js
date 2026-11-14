// Guidance for Flight School steps (docs/PLAYTEST.md §Guidance). A 7-year-old who knows nothing about the Moon must
// always see what to do: a step never asks for a place without showing it (or, when the step tests finding it, the
// hint ladder below), no unlabelled dots, a one-line "how this works" the first time a kind of step appears, and every
// miss says what to do next.
//
// The ladder (rungs come from the server, backend/app/academy/guide.py):
//   0  the prompt + one "do this" line; places the step names but doesn't test (step.show) carry labels; step.ring
//      draws a gold ring
//   1  first miss: the target glows (no name) and the globe turns toward it; the terminator line glows
//   2  second miss: the target gets its label; a wrong card is crossed out; the order button glows; the words appear
//   3  third miss: CAPCOM shows the answer and moves on (routes.py)
// Pure helpers (marks, doLine, intro) are unit-tested in frontend/tests/guide.test.js.

/** The "do this" line under the question, per step type (a step's own `do` wins). ≤ 10 words, docs/COPY.md. */
export const DO = {
  intent: "Tap it on the Moon, or say its name", tap: "Tap it on the Moon, or say its name",
  route: "Tap the glowing places in order: 1, then 2", terminator: "Tap where light turns to dark",
  globe_side: "Drag the Moon to turn it, or tap a side", compare: "Tap a card or a pin, or say its name",
  predict: "Guess first. Any guess is fine", earth_view: "Tap Yes, No or Sometimes, or say it",
  choice: "Tap an answer, or say it", command: "Tap an order, or say it",
  keywords: "Say the order back, or type it", vocab_match: "Tap the meaning, or say it",
  vocab_fill: "Tap the missing word, or say it", vocab_say: "Say the word out loud", vocab_listen: "Listen, then tap the word, or say it",
};
/** The first time a kind of step appears: one line on how it works (spoken once too). */
export const INTRO = {
  intent: "New: find a place. Tap it on the Moon.", tap: "New: find a place. Tap it on the Moon.",
  route: "New: trace a path. Tap the glowing places in order.", terminator: "New: the Sun lights half the Moon. Find the edge.",
  globe_side: "New: you can spin the Moon. Drag it, or tap a side.", compare: "New: two outposts. Pick one, then see the numbers.",
  predict: "New: a guess. There's no wrong guess here.", earth_view: "New: imagine standing there and looking up.",
  command: "New: give an order. Tap a button, or say it.", keywords: "New: radio practice. Say the order back.",
};
export const doLine = st => (st && (st.do || DO[(st.accept || {}).type])) || "";

/** First use of a step type on this device? (localStorage; private mode: always "seen" after the first call) */
const SEEN_KEY = "outpost-seen-steps";
let seenMem = null;
export function firstUse(type, storage = typeof localStorage !== "undefined" ? localStorage : null) {
  if (!INTRO[type]) return false;
  if (!seenMem) { try { seenMem = new Set(JSON.parse((storage && storage.getItem(SEEN_KEY)) || "[]")); } catch (e) { seenMem = new Set(); } }
  if (seenMem.has(type)) return false;
  seenMem.add(type);
  try { storage && storage.setItem(SEEN_KEY, JSON.stringify([...seenMem])); } catch (e) { /* private mode */ }
  return true;
}
export function resetSeen() { seenMem = null; }

const short = f => String((f && f.name) || "").split(" (")[0].replace(/^Mare /, "");   // "Orientale", as the prompts say it
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
  const add = (id, o) => {   // one mark per place: a later rule adds to it (a shown stop that is also the focus pulses)
    const f = find(id); if (!f) return;
    const had = out.find(m => m.id === id);
    if (had) { had.pulse = had.pulse || o.pulse; had.ring = had.ring || o.ring; had.label = had.label || o.label; return; }
    out.push({ id, lat: f.lat, lon: f.lon, r: degR(f), ...o });
  };
  if (g.done) {   // after the answer: what the step taught, named (e.g. Integrity, halfway along the route)
    (st.show || []).forEach(id => add(id, { label: short(find(id)) }));
    (g.after || []).forEach(id => add(id, { label: short(find(id)), pulse: true }));
    return out;
  }
  const stops = acc.type === "route" ? acc.stops || [] : [];
  (st.show || []).forEach(id => {
    const k = stops.indexOf(id);
    add(id, { label: short(find(id)), num: k >= 0 ? k + 1 : undefined, pulse: k >= 0 && k === (g.next || 0), ring: true });
  });
  (st.ring || []).forEach(id => add(id, { ring: true, gold: true, pulse: true }));
  if (g.rung >= 1) (g.focus || []).forEach(id => add(id, { ring: true, pulse: true, label: g.rung >= 2 && (g.label || []).includes(id) ? short(find(id)) : undefined }));
  if (g.line_lon != null) {
    for (let lat = -60; lat <= 60; lat += 15) out.push({ id: "t" + lat, lat, lon: g.line_lon, r: 1.6, ring: true, pulse: true, label: g.label_line && lat === 0 ? "Day meets night" : undefined });
  }
  return out;
}

/** Where the step's first mark is, if the camera should turn to it (it's round the back or near the edge). */
export function needsTurn(m, project) {
  if (!m) return false;
  const p = project(m.lat, m.lon);
  return !p.facing || (p.depth != null && p.depth < 0.45);
}
