// 0.4 "Real NASA views" on the globe and in the Library (not the cabin: it wires media/nasa_views.js itself later).
//   - the real star sky (SVS Deep Star Maps 2020) instead of 1,400 random points
//   - the Apollo Lunar Module standing at the six Apollo landing sites; LRO and LADEE circling the Moon (Library only)
//   - the "Moon rocks" tray in the Library toolbar: six Apollo samples + the NASA hardware models, in 3D
//   - a sharp south pole: the site navigator's LOLA relief (the site_layers asset) draped over the globe's polar texels
// Every piece waits for its optional asset; without it nothing changes.
import { onViews, skyTransform, modelForArtifact, loadModel } from "./media/nasa_views.js";
import { createRocksTray } from "./media/rocks_tray.js";

/** Orbiters shown in the Library (not to scale; LADEE is labelled with its years: it ended in 2014). */
export const ORBITERS = [
  { id: "lro", label: "LRO", incl: 90, alt: 0.1, period: 70, phase: 0.15 },
  { id: "ladee", label: "LADEE · 2013–14", incl: 157, alt: 0.065, period: 52, phase: 0.6 },
];

export function wireViews({ globe, stage, hudRow, log = console.warn }) {
  const out = { tray: null, button: null };
  onViews(async v => {
    if (v.sky) globe.setSky(v.sky.url, skyTransform(v.sky));
    const byId = Object.fromEntries(v.models.map(m => [m.id, m]));
    try {
      if (byId.apollo_lm) {
        const lm = await loadModel(byId.apollo_lm.url);
        globe.setHardwareModels(a => (modelForArtifact(a) === "apollo_lm" ? lm.clone(true) : null));
      }
      const orb = [];
      for (const o of ORBITERS) if (byId[o.id]) orb.push({ ...o, obj: await loadModel(byId[o.id].url) });
      if (orb.length) globe.setOrbiters(orb);
    } catch (e) { log("nasa_views: a model didn't load", e); }
    if ((v.rocks.length || v.models.length) && hudRow && !out.button) {
      const b = document.createElement("button");
      b.type = "button"; b.id = "rocksBtn"; b.setAttribute("aria-pressed", "false"); b.textContent = "Moon rocks";
      hudRow.append(b);
      const tray = createRocksTray({ host: stage, views: v,
        onOpen: () => b.setAttribute("aria-pressed", "true"), onClose: () => { b.setAttribute("aria-pressed", "false"); b.focus({ preventScroll: true }); } });
      b.onclick = () => (tray.isOpen ? tray.close() : tray.open());
      // the tray belongs to the Library: leaving it closes the tray
      new MutationObserver(() => { if (document.body.dataset.mode !== "cadet" && tray.isOpen) tray.close(); })
        .observe(document.body, { attributes: true, attributeFilter: ["data-mode"] });
      out.tray = tray; out.button = b;
      (window.__outpost = window.__outpost || {}).rocks = tray;
    }
  });
  polarCap(globe);
  return out;
}

/** The south pole's LOLA relief, once the site navigator's map layers are installed (polls while they download). */
export async function polarCap(globe, { fetchImpl = globalThis.fetch, tries = 30, waitMs = 60000 } = {}) {
  for (let i = 0; i < tries; i++) {
    let L = null;
    try { const r = await fetchImpl("/api/sites/navigator"); L = r && r.ok ? (await r.json()).layers : null; } catch (e) { L = null; }
    if (L && L.state === "ready" && L.base && L.base.file) return globe.setPolarCap("/api/sites/layers/" + L.base.file, L.extent_km || 210);
    if (!L || !(L.state === "downloading" || L.managed)) return false;   // a dev checkout without the layers: stop asking
    await new Promise(res => setTimeout(res, waitMs));
  }
  return false;
}
