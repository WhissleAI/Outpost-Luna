// Open Moon data: the optional `moon_views` asset (backend/app/moon_views.py, scripts/moon_views_build.py), the same
// shape as nasa_views (media/nasa_views.js) for media beyond NASA's own pack (docs/MEDIA.md "Moon views"):
//   photos  one real Apollo surface photo per landing site: "Real photo here" on that site's hardware cards
//   layers  "Rock ages": the USGS Unified Geologic Map of the Moon by period, a globe layer with its key
//   models  the Smithsonian's Apollo 11 Command Module Columbia (CC0), in the Moon rocks tray
//   rock_facts  Lunar Sample Compendium facts for the tray's Apollo samples
// Until the pack is installed (or on a build without it) nothing changes: onMoonViews(cb) simply never calls back.

export const MOON_VIEWS_API = "/api/moon-views";
const LICENCES = ["pd", "cc0", "by", "by-sa"];

/** A pack-relative path ("photos/apollo11.jpg") -> the backend url that serves it; anything else -> null. Pure. */
export function fileUrl(rel) {
  const m = /^(photos|layers|models|facts)\/([A-Za-z0-9][A-Za-z0-9_-]{0,80}\.(?:jpg|png|glb|json))$/.exec(String(rel || ""));
  return m ? `${MOON_VIEWS_API}/file/${m[1]}/${m[2]}` : null;
}

/** GET /api/moon-views -> views (urls filled in, only entries with a licence we ship) when ready, else null. Pure. */
export function normalize(raw) {
  if (!raw || raw.state !== "ready") return null;
  const ok = e => e && typeof e === "object" && LICENCES.includes(e.licence_class) && fileUrl(e.file);
  const list = xs => (Array.isArray(xs) ? xs.filter(ok).map(e => ({ ...e, url: fileUrl(e.file) })) : []);
  const layers = list(raw.layers).filter(l => l.bounds && Array.isArray(l.legend) && l.legend.length)
    .map(l => ({ ...l, legend: l.legend.filter(x => x && /^#[0-9a-fA-F]{6}$/.test(String(x.color)) && x.label) }));
  const facts = raw.rock_facts && typeof raw.rock_facts === "object" ? raw.rock_facts : {};
  return { credit: raw.credit || "", photos: list(raw.photos), layers, models: list(raw.models), rockFacts: facts };
}

/** The Apollo landing site a hardware marker belongs to ("apollo11"), or null (an S-IVB impact is not a landing). Pure. */
export function siteOf(a) {
  const m = /^(apollo1[1-7])_/.exec(String((a && a.id) || ""));
  return m && !/_sivb_impact$/.test(a.id) ? m[1] : null;
}

/** The real surface photo for a hardware marker, or null. Pure. */
export const photoFor = (v, a) => (v && siteOf(a) ? v.photos.find(p => p.site === siteOf(a)) || null : null);

/** The card a "Real photo here" action opens: the photo, its caption, NASA's credit and the source page. Pure. */
export function photoEntry(p, a) {
  return { title: p.title, eyebrow: `Real photo · ${(a && a.mission) || p.site.replace("apollo", "Apollo ")}`, say: p.caption, transient: true,
    photo: { src: p.url, alt: p.alt || p.title, credit: `${p.credit} (${p.nasa_id}) · Public domain`, caption: p.title },
    sources: [{ title: "NASA Image Library", url: p.source }] };
}

/** A hardware card's extra actions: "Real photo here" once the pack is in. show(entry) opens a card. Pure-ish. */
export function artifactActions(a, show, v = views) {
  const p = photoFor(v, a);
  return p ? [{ label: "Real photo here", onClick: () => show(photoEntry(p, a)) }] : [];
}

/** Lunar Sample Compendium facts for a rock of the tray ("15016"), or []. Pure. */
export const factsFor = (id, v = views) => ((v && v.rockFacts[String(id)]) || {}).facts || [];

// ------------------------------------------------------------------------------------------------ the live pack
let views = null, started = false, timer = 0;
const subs = new Set();
const POLL_MS = 30000, POLL_MAX = 60;

async function poll(fetchImpl, n = 0) {
  let raw = null;
  try { const r = await fetchImpl(MOON_VIEWS_API); raw = r && r.ok ? await r.json() : null; } catch (e) { raw = null; }
  const v = normalize(raw);
  if (v) { views = v; for (const cb of [...subs]) { try { cb(v); } catch (e) { console.warn("moon_views subscriber", e); } } return; }
  if (raw && (raw.state === "downloading" || raw.managed) && n < POLL_MAX) timer = setTimeout(() => poll(fetchImpl, n + 1), POLL_MS);
}

/** cb(views) once the pack is installed (at once if it already is). -> unsubscribe */
export function onMoonViews(cb, fetchImpl = globalThis.fetch) {
  if (views) { try { cb(views); } catch (e) { console.warn("moon_views subscriber", e); } return () => {}; }
  subs.add(cb);
  if (!started && typeof fetchImpl === "function") { started = true; poll(fetchImpl); }
  return () => subs.delete(cb);
}
export const getMoonViews = () => views;
/** Tests: forget the pack and stop polling. */
export function _reset() { views = null; started = false; clearTimeout(timer); subs.clear(); }
