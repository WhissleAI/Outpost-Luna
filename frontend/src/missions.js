// Find-it missions: one compact card over the globe, one mission at a time. Tap the Moon to answer.
import { angDist, angRadius } from "./globe.js";

const M = [
  { f: "aristarchus", t: "The yellow cheek", clue: "The crew said one plateau looked like a yellow, snow-capped mountain. Can you find it on the near side?" },
  { f: "tranquillitatis", t: "First footprints", clue: "Find the dark sea where people first walked on the Moon in 1969." },
  { f: "orientale", t: "The giant bullseye", clue: "Find the huge target with rings, right on the edge between the near and far side." },
  { f: "integrity", t: "A crater named after a spaceship", clue: "Start at Orientale. Go straight up to Ohm. Tap halfway between them." },
  { f: "shackleton", t: "Where astronauts go next", clue: "Find the place at the very bottom of the Moon where ice might hide." },
];

export function createMissions({ globe, placeById, say, onFound }) {
  const $ = id => document.getElementById(id);
  const card = $("missionCard"), btn = $("missionsBtn");
  let active = 0; const done = new Set();
  const list = M.filter(m => placeById(m.f));

  function render(result) {
    const m = list[active];
    $("mStep").textContent = `Mission ${active + 1} of ${list.length}`;
    $("mStars").textContent = "★ " + done.size;
    $("mStars").setAttribute("aria-label", `${done.size} of ${list.length} stars`);
    $("mTitle").textContent = m.t; $("mClue").textContent = m.clue;
    card.classList.toggle("is-done", done.has(active));
    $("mResult").textContent = result || (done.has(active) ? "Found it! ★" : "Tap the Moon to answer");
  }
  function open() { card.hidden = false; btn.setAttribute("aria-pressed", "true"); render(); say(list[active].clue); }
  function close() { card.hidden = true; btn.setAttribute("aria-pressed", "false"); }
  function next() {
    let n = list.findIndex((_, i) => i > active && !done.has(i));
    if (n < 0) n = list.findIndex(((_, i) => !done.has(i)));
    active = n >= 0 ? n : (active + 1) % list.length;
    render(); say(list[active].clue);
  }

  btn.onclick = () => (card.hidden ? open() : close());
  $("mClose").onclick = close;
  $("mNext").onclick = next;
  $("mShow").onclick = () => globe.showFeature(placeById(list[active].f));

  return {
    get open() { return !card.hidden; },
    openCard: open,
    /** Handle a tap while the card is open. Returns true when it was a mission answer. */
    onTap(p) {
      if (card.hidden || done.has(active)) return false;
      const f = placeById(list[active].f), tol = Math.max(angRadius(f) * 1.4, f.est ? 9 : 7);
      if (angDist(p, f) <= tol) {
        done.add(active); globe.showFeature(f); onFound(f);
        render(done.size === list.length ? "All missions done! ★★★" : "Found it! ★");
        say("You found it! " + f.name + ". " + f.fact);
        return true;
      }
      const n = globe.nearest(p).f; globe.highlight(n);
      render("That's " + n.name + ". Keep looking!"); say("That's " + n.name + ". Keep looking!");
      return true;
    },
    get started() { return done.size > 0; },
  };
}
