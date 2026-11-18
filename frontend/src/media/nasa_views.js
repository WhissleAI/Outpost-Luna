// Real NASA views (0.4): the optional `nasa_views` asset, for any screen (docs/MEDIA.md "NASA views").
//
// The pack (scripts/nasa_views_build.py) is an optional first-run asset: the desktop app downloads it in the background
// after the UI is up, and the backend serves it (GET /api/views + /api/views/file/<folder>/<name>, backend/app/nasa_views.py).
// Until it is installed — or on a build without it — every screen keeps today's visuals: callers ask `onViews(cb)` and
// simply never hear back.
//
//   onViews(cb)            cb(views) once the pack is installed (at once if it already is); returns an unsubscribe
//   getViews()             the current views or null (no network)
//   image(id) / images(tag)   Earthrise, Earthset, Artemis geology training… -> {id, url, title, caption, credit, …}
//   sdoFrames()            the 14 May 2024 storm (AR 13664) as [{url, time}] + its credit (sdoInfo())
//   model(id) / rocks()    3D models and the six Apollo samples, each with its GLB url
//   loadModel(url)         a THREE.Group from a GLB (meshopt-compressed), cached; lazy-loads the loader
//
// The cabin (a later step) wires Earthrise / Earthset and the SDO frames through image() / sdoFrames(); nothing here
// touches it. window.__outpost.views exposes the same API for the playtest tools.

export const VIEWS_API = "/api/views";
export const CREDIT = "Uses NASA open data and 3D models (NASA 3D Resources; NASA/Astromaterials 3D, CC0; USGS Astrogeology); not endorsed by NASA.";

/** A pack-relative path ("images/earthrise.jpg") -> the backend URL that serves it. Anything else -> null. */
export function fileUrl(rel) {
  const m = /^(sky|models|rocks|images|sdo|names)\/([A-Za-z0-9_-][A-Za-z0-9_.-]*)$/.exec(String(rel || ""));
  return m ? `${VIEWS_API}/file/${m[1]}/${encodeURIComponent(m[2])}` : null;
}

/** The GET /api/views answer -> views (urls filled in) when the pack is ready, else null. Pure (tested). */
export function normalize(raw) {
  if (!raw || raw.state !== "ready") return null;
  const withUrl = e => (e && typeof e === "object" && fileUrl(e.file) ? { ...e, url: fileUrl(e.file) } : null);
  const list = xs => (Array.isArray(xs) ? xs.map(withUrl).filter(Boolean) : []);
  const sdo = raw.sdo && Array.isArray(raw.sdo.frames) ? { ...raw.sdo, frames: list(raw.sdo.frames) } : null;
  return {
    credit: raw.credit || CREDIT,
    sky: withUrl(raw.sky),
    models: list(raw.models),
    rocks: list(raw.rocks),
    images: list(raw.images),
    sdo: sdo && sdo.frames.length ? sdo : null,
    names: withUrl(raw.names),
  };
}

/**
 * The star map's orientation on a sky sphere seen from INSIDE (three.js BackSide). A sky chart drawn as seen from
 * Earth (RA increasing to the left) would read mirrored on the inside of a sphere, so it is flipped back.
 * -> {flipX, offsetU}: offsetU puts RA 0h at u = 0 of the sphere. Pure (tested).
 */
export function skyTransform(sky) {
  const flipX = !sky || sky.ra_increases !== "right";
  const ra0 = sky && Number.isFinite(+sky.ra0_u) ? +sky.ra0_u : 0.5;
  return { flipX, offsetU: ((ra0 % 1) + 1) % 1 };
}

/** Which 3D model stands in for a Library hardware marker (null = keep the diamond). Apollo LMs get the LM. */
export function modelForArtifact(a) {
  if (!a) return null;
  return /^apollo1[1-7]_lm_/.test(String(a.id || "")) ? "apollo_lm" : null;
}

// ------------------------------------------------------------------------------------------------ the live pack
let views = null, started = false, timer = 0;
const subs = new Set();
const POLL_MS = 30000, POLL_MAX = 60;   // a download in progress: look again every 30 s, for up to 30 min

function publish(v) {
  views = v;
  for (const cb of [...subs]) { try { cb(v); } catch (e) { console.warn("nasa_views subscriber", e); } }
}

async function poll(fetchImpl, n = 0) {
  let raw = null;
  try { const r = await fetchImpl(VIEWS_API); raw = r && r.ok ? await r.json() : null; } catch (e) { raw = null; }
  const v = normalize(raw);
  if (v) { publish(v); return; }
  // the desktop downloads it after the UI is up (managed): keep looking; a dev checkout without the pack: stop
  const again = raw && (raw.state === "downloading" || raw.managed) && n < POLL_MAX;
  if (again) timer = setTimeout(() => poll(fetchImpl, n + 1), POLL_MS);
}

/** Start looking for the pack (idempotent). fetchImpl for tests. */
export function start(fetchImpl = globalThis.fetch) {
  if (started || typeof fetchImpl !== "function") return;
  started = true;
  poll(fetchImpl);
}

/** cb(views) once the pack is installed (at once if it already is). -> unsubscribe */
export function onViews(cb) {
  if (views) { try { cb(views); } catch (e) { console.warn("nasa_views subscriber", e); } return () => {}; }
  subs.add(cb); start();
  return () => subs.delete(cb);
}

export const getViews = () => views;
export const image = id => (views && views.images.find(i => i.id === id)) || null;
export const images = tag => (views ? views.images.filter(i => !tag || (i.tags || []).includes(tag)) : []);
export const sdoFrames = () => (views && views.sdo ? views.sdo.frames : []);
export const sdoInfo = () => (views && views.sdo) || null;
export const model = id => (views && views.models.find(m => m.id === id)) || null;
export const rocks = () => (views ? views.rocks : []);

/** Tests: forget the pack and stop polling. */
export function _reset() { views = null; started = false; clearTimeout(timer); subs.clear(); }

// ------------------------------------------------------------------------------------------------ GLB loading
let loaderP = null;
const glbCache = new Map();
async function loader() {
  if (!loaderP) loaderP = (async () => {
    const [{ GLTFLoader }, { MeshoptDecoder }] = await Promise.all([
      import("three/examples/jsm/loaders/GLTFLoader.js"), import("three/examples/jsm/libs/meshopt_decoder.module.js")]);
    const l = new GLTFLoader(); l.setMeshoptDecoder(MeshoptDecoder); return l;
  })();
  return loaderP;
}
/** A GLB -> its scene (THREE.Group). The same url loads once; every caller gets its own clone. */
export async function loadModel(url) {
  if (!glbCache.has(url)) glbCache.set(url, loader().then(l => l.loadAsync(url)).then(g => g.scene)
    .catch(e => { glbCache.delete(url); throw e; }));
  return (await glbCache.get(url)).clone(true);
}

if (typeof window !== "undefined") {
  (window.__outpost = window.__outpost || {}).views = { onViews, getViews, image, images, sdoFrames, sdoInfo, model, rocks, loadModel };
}
