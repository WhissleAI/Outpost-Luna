// Find-it missions: one compact card over the globe, one mission at a time. Tap the Moon (or a ghost marker) to answer.
// A mission names its target by place id (f) or, for hardware, by a test on the artifact's own fields (hw), so it only
// appears when the data can back it up.
import { angDist, angRadius } from "./globe.js";
import { icon } from "./assets/icons.js";

const isApollo = n => a => new RegExp("\\bApollo " + n + "\\b", "i").test(a.mission || "");
const M = [
  { hw: a => isApollo(11)(a) && a.hw === "lander", t: "First footprints", clue: "Find the lander that carried the first Moon walkers in 1969." },
  { f: "aristarchus", t: "The yellow cheek", clue: "A crew said this plateau looked yellow. It's on the near side." },
  { hw: a => isApollo(16)(a) && a.hw === "rover", t: "The Moon buggy", clue: "Find the rover two astronauts drove over the highlands in 1972." },
  { f: "orientale", t: "The giant bullseye", clue: "Find the huge ringed target on the edge of the near side." },
  { f: "shackleton", t: "The icy pole", clue: "Find the crater at the very bottom of the Moon where ice hides." },
];

export function createMissions({ globe, placeById, places = [], say, onFound }) {
  const $ = id => document.getElementById(id);
  const card = $("missionCard"), btn = $("missionsBtn");
  let active = 0; const done = new Set();
  const target = m => (m.hw ? places.find(p => p.kind === "artifact" && m.hw(p)) : placeById(m.f)) || null;
  const list = M.map(m => ({ ...m, place: target(m) })).filter(m => m.place);

  function render(result) {
    const m = list[active];
    $("mStep").textContent = `Find ${active + 1} of ${list.length}`;   // [qa] not "Mission": that's the Mission tab
    $("mStars").innerHTML = icon("star", { size: 14 }) + " " + done.size;
    $("mStars").setAttribute("aria-label", `${done.size} of ${list.length} stars`);
    $("mTitle").textContent = m.t; $("mClue").textContent = m.clue;
    card.classList.toggle("is-done", done.has(active));
    $("mResult").textContent = result || (done.has(active) ? "Found it." : "Tap the Moon to answer");
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
  $("mShow").onclick = () => globe.showFeature(list[active].place);

  return {
    get open() { return !card.hidden; },
    openCard: open,
    /** Handle a tap while the card is open. Returns true when it was a mission answer. */
    onTap(p, tapped) {
      if (card.hidden || done.has(active)) return false;
      const f = list[active].place, hw = f.kind === "artifact";
      const hit = hw ? (tapped ? tapped.id === f.id : angDist(p, f) <= 2.5) : angDist(p, f) <= Math.max(angRadius(f) * 1.4, f.est ? 9 : 7);
      if (hit) {
        done.add(active); globe.showFeature(f); onFound(f);
        render(done.size === list.length ? "You found them all." : "Found it.");
        say("You found it. " + f.name + ". " + (hw ? f.story || "" : f.fact));
        return true;
      }
      const n = tapped || globe.nearest(p).f; globe.highlight(n);
      render("That's " + n.name + ". Keep looking."); say("That's " + n.name + ". Keep looking.");
      return true;
    },
    get started() { return done.size > 0; },
  };
}
