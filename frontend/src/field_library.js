// [courses] The course Library on a non-Moon globe (docs/COURSES.md "Course library"). The Moon's Library is its
// hardware, crew audio and the NASA views pack; another course brings its own: GET /api/course/library
// (backend/app/course_library.py) lists shelves of real pictures (NASA Earth views, NPS site photos, USGS lidar), the
// course's NASA videos (its videos.json, played by media/video.js), places, a regional picture draped on the globe,
// a site tour and the askbar chips. Archaeology: NASA's Earth from orbit blended with Mesa Verde, and the Moon as context.
//
// Pure helpers first (tests/field_library.test.js), then installFieldLibrary(), which main.js calls on a non-Moon globe.
// Nothing here runs on the Moon, and a course without a library (or an older pack without one) keeps today's screen.

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const LIBRARY_API = "/api/course/library";
const MEDIA_URL = /^\/api\/(courses\/[a-z][a-z0-9-]{1,23}\/media\/[a-z0-9][a-z0-9_.-]{0,80}\.(?:jpg|png)|video\/[a-z0-9_]{2,40}\/poster)$/;

/** Only our own origin's course media and video posters (the app's CSP and school networks: nothing hot-linked). */
export const safeUrl = u => (typeof u === "string" && MEDIA_URL.test(u) ? u : null);

/** GET /api/course/library -> the library the screen draws, or null (no library: keep today's Library). Pure. */
export function normalizeLibrary(raw) {
  if (!raw || !Array.isArray(raw.shelves) || !raw.shelves.length) return null;
  const items = new Map();
  const shelves = raw.shelves.map(sh => ({
    id: String(sh.id), title: String(sh.title || ""), by: String(sh.by || ""),
    items: (sh.items || []).filter(it => it && it.id && ["image", "video", "place"].includes(it.kind)).map(it => {
      const o = { ...it, shelf: String(sh.id), by: String(sh.by || ""), url: safeUrl(it.url), poster: safeUrl(it.poster) };
      items.set(o.id, o);
      return o;
    }),
  })).filter(sh => sh.items.length);
  if (!shelves.length) return null;
  const overlays = (raw.overlays || []).map(o => ({ ...o, url: safeUrl(o.url) })).filter(o => o.url && o.bounds);
  return { course: raw.course, title: raw.title || "Library", intro: raw.intro || "", home: raw.home || null,
           tour: raw.tour && Array.isArray(raw.tour.stops) ? raw.tour : null, chips: raw.chips || [], overlays, shelves, items,
           featured: Array.isArray(raw.featured) ? raw.featured.filter(id => items.has(id)) : [],
           moon: raw.moon && raw.moon.say ? raw.moon : null };
}

/** One credit line for a picture: "NASA (…) · Public domain (US Government work)". Pure. */
export const imageCredit = it => [it.image_credit, it.image_licence].filter(Boolean).join(" · ");

/** "4 min" / "34 s". Pure. */
export const lengthText = s => (!(s > 0) ? "" : s < 60 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`);

/** The globe's markers: every gazetteer place, plus each library picture with its own lat/lon (not a place's). Pure. */
export function markersFor(lib, places) {
  const out = (places || []).filter(p => p && p.kind !== "artifact" && Number.isFinite(p.lat) && Number.isFinite(p.lon))
    .map(p => ({ id: "place:" + p.id, place: p.id, lat: p.lat, lon: p.lon, label: p.name, kind: "place", aria: `${p.name}. Hear about it` }));
  if (!lib) return out;
  for (const it of lib.items.values()) {
    if (it.place || !Number.isFinite(it.lat) || !Number.isFinite(it.lon) || it.kind !== "image") continue;
    out.push({ id: "item:" + it.id, item: it.id, lat: it.lat, lon: it.lon, label: it.title, kind: "view", aria: `${it.title}. A real photo from orbit` });
  }
  return out;
}

/** The pictures of a place (its photo first), in shelf order. Pure. */
export const picturesOf = (lib, placeId) => (lib ? [...lib.items.values()].filter(it => it.kind === "image" && it.url && it.place === placeId) : []);

/** A chip's action: {type: "tour"} | {type: "item", id} | null. Pure. */
export function chipAction(c) {
  const d = String((c && c.do) || "");
  if (d === "tour") return { type: "tour" };
  if (d.startsWith("item:") && d.length > 5) return { type: "item", id: d.slice(5) };
  return null;
}

/** The Library's place card, with the place's first real photo and its credit and sources. Pure. */
export function placeEntry(f, lib, k = 0) {
  const pics = picturesOf(lib, f.id), pic = pics.length ? pics[((k % pics.length) + pics.length) % pics.length] : null;
  const e = { title: f.name, place: true, say: f.fact || "" };
  if (pic) {
    e.photo = { src: pic.url, alt: pic.image_alt || pic.title, credit: imageCredit(pic), caption: pic.title };
    e.sources = [pic.source, pic.image_source_url ? { title: "Photo source", url: pic.image_source_url } : null].filter(x => x && x.url);
    e.eyebrow = pics.length > 1 ? `Real photo ${((k % pics.length) + pics.length) % pics.length + 1} of ${pics.length} · ${pic.by}` : `Real photo · ${pic.by}`;
  }
  if (f.source && !(e.sources || []).some(s => s.url === f.source)) (e.sources = e.sources || []).push({ title: "Place source", url: f.source });
  return e;
}

/** The card for a library item (a picture or a place item). Pure. */
export function itemEntry(it, placeById = () => null) {
  const p = it.place ? placeById(it.place) : null;
  const e = { title: it.title || (p && p.name) || "", place: !!p, say: it.caption || (p && p.fact) || "",
              eyebrow: [it.kind === "image" ? "Real photo" : "", it.by].filter(Boolean).join(" · ") };
  if (it.kind === "image" && it.url) e.photo = { src: it.url, alt: it.image_alt || it.title, credit: imageCredit(it), caption: it.image_title || it.title };
  e.sources = [it.source, it.image_source_url ? { title: "Photo source", url: it.image_source_url } : null].filter(x => x && x.url);
  return e;
}

// ------------------------------------------------------------------------------------------------ the screen
/**
 * Install the Library for a non-Moon course. deps: {stage, chipsEl, globe, card, places, placeById, say, openVideo,
 * runTour(ids, intro, {title}), goLibrary(), mapUrl (the globe's own map), fetchFn}. -> {ready: Promise<lib|null>, enter(), placeEntry(f), openItem(id),
 * tour(), get lib}
 */
export function installFieldLibrary({ stage, chipsEl, globe, card, places, placeById, say = () => {}, openVideo, runTour, goLibrary = () => {}, mapUrl = "", fetchFn = (u) => fetch(u) }) {
  let lib = null;
  const pageOf = new Map();   // place id -> which of its photos the card shows (More photos steps through them)
  const panel = document.createElement("aside");
  panel.className = "flib"; panel.setAttribute("aria-label", "Library"); panel.hidden = true;
  const ribbon = document.createElement("div");
  ribbon.className = "flib-ribbon"; ribbon.hidden = true;

  function fly(it) {
    const p = it.place ? placeById(it.place) : null;
    if (p) globe.flyTo(p.lat, p.lon, 1.1);
    else if (Number.isFinite(it.lat) && Number.isFinite(it.lon)) globe.flyTo(it.lat, it.lon, 1.16);
    else if (lib.overlays.some(o => o.url === it.url) && lib.home) globe.flyTo(lib.home.lat, lib.home.lon, lib.home.dist || 1.1);   // the draped region
    else if (mapUrl && it.url === mapUrl) globe.flyTo(30, -100, 3.4);   // the globe's own map: the whole globe
  }
  function openItem(id) {
    const it = lib && lib.items.get(id); if (!it) return false;
    if (it.kind === "video") { if (openVideo) openVideo(it.video, { context: "library" }); return true; }
    fly(it);
    if (it.kind === "place") { const p = placeById(it.place); if (p) openPlace(p, it.caption); return true; }
    card.show({ ...itemEntry(it, placeById), actions: actionsFor(it) });
    say(it.caption || it.title);
    return true;
  }
  function actionsFor(it) {
    const out = [];
    const p = it.place ? placeById(it.place) : null;
    if (p) out.push({ label: `About ${p.name}`, onClick: () => openPlace(p) });
    return out;
  }
  function openPlace(f, line) {
    const k = pageOf.get(f.id) || 0, e = placeEntry(f, lib, k), n = picturesOf(lib, f.id).length;
    if (line) e.say = line;
    const acts = [];
    if (n > 1) acts.push({ label: "Next photo", hot: true, onClick: () => { pageOf.set(f.id, k + 1); openPlace(f); } });
    card.show({ ...e, actions: acts });
    say(e.say);
    return true;
  }
  function tour() {
    if (!lib || !lib.tour || !runTour) return false;
    runTour(lib.tour.stops, lib.tour.intro || "", { title: lib.tour.title || "Tour" });
    return true;
  }

  function thumb(it) {
    const img = it.kind === "video" ? it.poster : it.url;
    const meta = it.kind === "video" ? `Video · ${lengthText(it.duration_s)}` : it.kind === "place" ? "Place" : it.by;
    return `<li><button type="button" class="flib-item k-${esc(it.kind)}" data-item="${esc(it.id)}">
      <span class="flib-thumb">${img ? `<img src="${esc(img)}" alt="" loading="lazy" decoding="async">` : ""}${it.kind === "video" ? '<i class="flib-play" aria-hidden="true"></i>' : ""}</span>
      <span class="flib-txt"><b>${esc(it.title || "")}</b><small>${esc(meta)}</small></span></button></li>`;
  }
  let shelfOn = null;
  function draw() {
    if (!lib) return;
    const sh = lib.shelves.find(s => s.id === shelfOn) || lib.shelves[0]; shelfOn = sh.id;
    panel.innerHTML = `<header><h2>${esc(lib.title)}</h2><p>${esc(lib.intro)}</p></header>
      <div class="flib-tabs" role="tablist" aria-label="Shelves">${lib.shelves.map(s =>
        `<button type="button" role="tab" data-shelf="${esc(s.id)}" aria-selected="${s.id === sh.id}">${esc(s.title)}</button>`).join("")}</div>
      <p class="flib-by">${sh.by ? `From ${esc(sh.by)}` : ""}</p>
      <ul class="flib-grid" role="tabpanel">${sh.items.map(thumb).join("")}</ul>`;
    panel.querySelectorAll("[data-shelf]").forEach(b => (b.onclick = () => { shelfOn = b.dataset.shelf; draw(); const t = panel.querySelector(`[data-shelf="${shelfOn}"]`); if (t) t.focus(); }));
    panel.querySelectorAll("[data-item]").forEach(b => (b.onclick = () => openItem(b.dataset.item)));
    panel.querySelectorAll("img").forEach(i => (i.onerror = () => { i.remove(); }));
  }
  function drawRibbon() {
    const pick = lib.featured.map(id => lib.items.get(id)).filter(it => it && (it.url || it.poster));
    const list = (pick.length >= 3 ? pick : [...lib.items.values()].filter(it => it.url || it.poster).slice(0, 4));
    ribbon.innerHTML = `<p class="flib-rb-h"><b>Real views</b><span>${esc([...new Set(lib.shelves.map(s => s.by).filter(Boolean))].slice(0, 3).join(" · "))}</span></p>
      <div class="flib-rb-row">${list.map(it => `<button type="button" class="flib-rb-item" data-item="${esc(it.id)}" title="${esc(it.title)}">
        <img src="${esc(it.kind === "video" ? it.poster : it.url)}" alt="${esc(it.title)}" loading="lazy" decoding="async">${it.kind === "video" ? '<i class="flib-play" aria-hidden="true"></i>' : ""}</button>`).join("")}</div>
      <button type="button" class="flib-rb-open" data-open>Open the ${esc(lib.title)}</button>`;
    ribbon.querySelectorAll("[data-item]").forEach(b => (b.onclick = () => { const id = b.dataset.item, it = lib.items.get(id);
      if (it && it.kind === "video") { openItem(id); return; } goLibrary(); setTimeout(() => openItem(id), 350); }));
    ribbon.querySelector("[data-open]").onclick = () => goLibrary();
    ribbon.hidden = false;
  }
  function drawChips() {
    if (!chipsEl) return;
    chipsEl.querySelectorAll(".flib-chip").forEach(b => b.remove());
    lib.chips.forEach(c => {
      const a = chipAction(c); if (!a) return;
      const b = document.createElement("button"); b.type = "button"; b.className = "flib-chip"; b.textContent = c.label;
      b.onclick = () => (a.type === "tour" ? tour() : openItem(a.id));
      chipsEl.append(b);
    });
  }
  function onMarker(m) {
    if (m.place) { const p = placeById(m.place); if (p) { globe.flyTo(p.lat, p.lon, Math.min(globe.distance || 1.2, 1.3)); openPlace(p); } }
    else if (m.item) openItem(m.item);
  }
  function moonCard() {
    const mo = (lib && lib.moon) || {}, v = mo.item ? lib.items.get(mo.item) : null, p = mo.place ? placeById(mo.place) : null;
    card.show({ title: "The Moon", eyebrow: "Seen from Earth · not to scale", say: mo.say || "",
      note: "Drawn close for the picture. It is really about 30 Earths away.",
      actions: [...(p ? [{ label: mo.place_label || p.name, hot: true, onClick: () => { globe.flyTo(p.lat, p.lon, 1.1); openPlace(p); } }] : []),
                ...(v ? [{ label: `Watch: ${v.title}`, onClick: () => openItem(v.id) }] : [])] });
  }

  stage.append(panel, ribbon);
  const ready = Promise.resolve().then(() => fetchFn(LIBRARY_API)).then(r => (r && r.ok ? r.json() : null)).catch(() => null).then(raw => {
    lib = normalizeLibrary(raw);
    if (!lib) return null;
    lib.overlays.forEach(o => globe.setOverlay && globe.setOverlay(o));
    if (globe.setMarkers) globe.setMarkers(markersFor(lib, places), onMarker);
    if (lib.moon && globe.setMoonContext) globe.setMoonContext({ onPick: () => { if (document.body.dataset.mode === "cadet") moonCard(); } });
    draw(); drawRibbon(); drawChips();
    panel.hidden = false;
    document.body.dataset.flib = "1";
    if (typeof window !== "undefined") (window.__outpost = window.__outpost || {}).fieldLibrary = { get lib() { return lib; }, openItem, tour };
    return lib;
  });

  return {
    ready,
    get lib() { return lib; },
    /** Arriving in the Library: the region, close, with its real picture draped and the places named. */
    enter() { if (!lib) return false; const h = lib.home || {}; if (Number.isFinite(h.lat)) globe.flyTo(h.lat, h.lon, h.dist || 1.2); return true; },
    placeEntry: (f, k) => placeEntry(f, lib, k), openPlace, openItem, tour, moonCard,
  };
}
