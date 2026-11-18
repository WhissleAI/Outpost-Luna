// The Library's "Moon rocks" tray (0.4, nasa_views pack): six real Apollo samples in 3D (NASA/Astromaterials 3D, CC0)
// plus the NASA 3D Resources hardware, one at a time in a small turntable viewer: drag to turn, name, story, credit.
// Built only once the pack is installed (main.js onViews); without it the Library is exactly as before.
import { createTurntable } from "./turntable.js";

/** One tray entry from a rock or a model of the index. Pure (tested). */
export function trayItem(e, kind) {
  if (kind === "rock") {
    const sub = [e.mission, e.type].filter(Boolean).join(" · ");
    return { id: "rock:" + e.id, kind, url: e.url, title: e.name || `Sample ${e.id}`, sub: sub + (e.id ? ` · sample ${e.id}` : ""),
      story: e.story || "", credit: e.credit || "NASA/Astromaterials 3D (CC0)", source: e.source || "https://ares.jsc.nasa.gov/astromaterials3d/" };
  }
  const full = e.title || e.id, short = MODEL_SHORT[e.id] || full;
  return { id: "model:" + e.id, kind, url: e.url, title: short, chip: short, sub: short !== full ? full : "NASA 3D model", story: e.story || "",
    credit: e.credit || "NASA 3D Resources", source: e.source || "https://science.nasa.gov/3d-resources/" };
}

/** Chip and heading names for the hardware models (the index titles spell out the acronyms: those become the subline). */
export const MODEL_SHORT = { apollo_lm: "Lunar Module", hdu: "Habitat", rassor: "RASSOR digger", mcc: "Mission Control", lro: "LRO", ladee: "LADEE" };

/** Short lines for the hardware models (the index has titles; the tray says what each one is). */
export const MODEL_STORY = {
  apollo_lm: "The Apollo Lunar Module carried two astronauts from lunar orbit to the surface and back. Six landed, 1969 to 1972.",
  hdu: "NASA's Habitat Demonstration Unit: a test home for crews on the Moon or Mars, tried out in the Arizona desert.",
  rassor: "RASSOR is a NASA digging robot. Its two drums spin the opposite way, so it can dig in low gravity without sliding.",
  mcc: "Mission Control in Houston: the room where flight controllers watch over every crew in space.",
  lro: "The Lunar Reconnaissance Orbiter has mapped the Moon since 2009. Its laser measured the south pole's hills and craters.",
  ladee: "LADEE studied the Moon's thin dust and gas in 2013 and 2014, then ended its mission by crashing on the far side.",
};

export function createRocksTray({ host, views, onOpen = () => {}, onClose = () => {} }) {
  const items = [...(views.rocks || []).map(r => trayItem(r, "rock")),
    ...(views.models || []).map(m => trayItem({ ...m, story: MODEL_STORY[m.id] || "" }, "model"))];
  const el = document.createElement("aside");
  el.className = "rocks"; el.hidden = true; el.setAttribute("role", "dialog"); el.setAttribute("aria-label", "Moon rocks and NASA models");
  el.innerHTML = `<header class="rk-head"><h2>Moon rocks</h2><button type="button" class="rk-close" aria-label="Close Moon rocks">×</button></header>
    <div class="rk-view"><canvas aria-hidden="true"></canvas><p class="rk-hint">Drag to turn</p><p class="rk-wait" hidden>Loading…</p></div>
    <div class="rk-body"><p class="rk-sub"></p><h3 class="rk-title"></h3><p class="rk-story"></p>
      <p class="rk-credit"><a target="_blank" rel="noopener"></a></p></div>
    <div class="rk-list" role="listbox" aria-label="Rocks and models"></div>`;
  host.append(el);
  const $ = q => el.querySelector(q);
  const list = $(".rk-list");
  const groups = [["rock", "Apollo samples"], ["model", "NASA hardware"]];
  for (const [kind, label] of groups) {
    const its = items.filter(i => i.kind === kind);
    if (!its.length) continue;
    const g = document.createElement("div"); g.className = "rk-group"; g.setAttribute("role", "group"); g.setAttribute("aria-label", label);
    g.innerHTML = `<span class="rk-glabel">${label}</span>`;
    its.forEach(it => {
      const b = document.createElement("button"); b.type = "button"; b.className = "rk-item"; b.setAttribute("role", "option");
      b.dataset.id = it.id; b.textContent = it.chip || it.title;
      b.onclick = () => show(it.id);
      g.append(b);
    });
    list.append(g);
  }

  // the turntable (media/turntable.js, shared with the Field School rock step), drawn only while the tray is open
  let tt = null, seq = 0;
  const initGL = () => { if (!tt) tt = createTurntable($("canvas")); };
  const loop = { start: () => tt && tt.start(), stop: () => tt && tt.stop() };

  async function show(id) {
    const it = items.find(i => i.id === id) || items[0];
    if (!it) return;
    list.querySelectorAll(".rk-item").forEach(b => b.setAttribute("aria-selected", String(b.dataset.id === it.id)));
    $(".rk-title").textContent = it.title; $(".rk-sub").textContent = it.sub; $(".rk-story").textContent = it.story;
    const a = $(".rk-credit a"); a.textContent = it.credit; a.href = it.source;
    $("h2").textContent = it.kind === "rock" ? "Moon rocks" : "NASA models";
    const my = ++seq, wait = $(".rk-wait");
    wait.hidden = false; wait.textContent = "Loading…";
    initGL();
    try {
      const shown = await tt.show(it.url);
      if (my === seq && shown) wait.hidden = true;
    } catch (e) {
      if (my === seq) wait.textContent = "This model didn't load.";
    }
  }

  function open(id) {
    if (!items.length) return;
    initGL(); el.hidden = false; loop.start();
    if (id) show(id); else if (!tt.hasModel) show(items[0].id);
    onOpen();
    $(".rk-close").focus({ preventScroll: true });
  }
  function close() { if (el.hidden) return; el.hidden = true; loop.stop(); onClose(); }
  $(".rk-close").onclick = close;
  el.addEventListener("keydown", e => {
    if (e.key === "Escape") { e.stopPropagation(); close(); }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const bs = [...list.querySelectorAll(".rk-item")], i = bs.findIndex(b => b.getAttribute("aria-selected") === "true");
      const n = bs[(i + (e.key === "ArrowDown" ? 1 : bs.length - 1)) % bs.length];
      if (n) { e.preventDefault(); n.focus(); show(n.dataset.id); }
    }
  });
  if (typeof ResizeObserver !== "undefined") new ResizeObserver(() => { if (tt && !el.hidden) tt.size(); }).observe(el);
  return { open, close, show, get isOpen() { return !el.hidden; }, items };
}
