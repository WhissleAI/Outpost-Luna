// [open data] The Library's "Maps" button: whole-globe maps beyond the photo (docs/OPEN_DATA.md). A course's library
// (GET /api/course/library, backend/app/course_library.py) may list `layers`: the Moon's age (USGS Unified Geologic Map,
// CC0) and height (USGS LOLA colour relief, public domain). Picking one swaps the globe's map (globe.setBaseMap), shows
// its legend and credit, and says its line. Leaving the Library puts the photo back, so lessons and missions always
// see the globe they were written for. No layers (an older pack, a dev checkout without the media): no button.

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const LIBRARY_API = "/api/course/library";
const LAYER_URL = /^\/api\/courses\/[a-z][a-z0-9-]{1,23}\/media\/[a-z0-9][a-z0-9_.-]{0,80}\.(?:jpg|png)$/;
const HEX = /^#[0-9a-fA-F]{6}$/;

/** The photo: the body's own map, always first. */
export const PHOTO = Object.freeze({ id: "photo", title: "Photo", url: null, legend: [], say: "" });

/** GET /api/course/library -> [PHOTO, ...layers] the picker lists, or [] (no layers: no button). Pure. */
export function normalizeLayers(raw) {
  const list = (raw && Array.isArray(raw.layers) ? raw.layers : [])
    .filter(l => l && typeof l.id === "string" && l.id !== "photo" && l.title && typeof l.url === "string" && LAYER_URL.test(l.url))
    .map(l => ({
      id: l.id, title: String(l.title), url: l.url, say: String(l.say || ""),
      legend: (Array.isArray(l.legend) ? l.legend : []).filter(x => x && HEX.test(String(x.color)) && x.label)
        .map(x => ({ color: x.color, label: String(x.label), note: String(x.note || "") })),
      credit: [l.credit, l.licence].filter(Boolean).join(" · "),
      source: l.source && l.source.url ? l.source : (l.source_url ? { title: "Map source", url: l.source_url } : null),
      alt: String(l.alt || ""),
    }));
  return list.length ? [PHOTO, ...list] : [];
}

/** The panel's HTML for the layer that is on (its legend, credit and source). Pure. */
export function panelHtml(layers, onId, bodyName = "Moon") {
  const on = layers.find(l => l.id === onId) || layers[0];
  const tabs = layers.map(l => `<button type="button" role="radio" data-layer="${esc(l.id)}" aria-checked="${l.id === on.id}">${esc(l.title)}</button>`).join("");
  const legend = on.legend.length ? `<ul class="ml-legend">${on.legend.map(x =>
    `<li><i style="background:${esc(x.color)}" aria-hidden="true"></i><b>${esc(x.label)}</b>${x.note ? `<small>${esc(x.note)}</small>` : ""}</li>`).join("")}</ul>` : "";
  const body = on.id === "photo"
    ? `<p class="ml-say">The ${esc(bodyName)} as a camera sees it. Pick a map to see what the photo can't show.</p>`
    : `<p class="ml-say">${esc(on.say)}</p>${legend}<p class="ml-credit">${esc(on.credit)}${on.source ? ` · <a href="${esc(on.source.url)}" target="_blank" rel="noopener">Source</a>` : ""}</p>`;
  return `<header class="ml-head"><h2>Maps</h2><button type="button" class="ml-close" aria-label="Close maps">×</button></header>
    <div class="ml-tabs" role="radiogroup" aria-label="Map">${tabs}</div><div class="ml-body" aria-live="polite">${body}</div>`;
}

/**
 * deps: {globe, hudRow, host, say(text), bodyName, fetchFn} -> {ready: Promise<layers>, pick(id), open(), close(), get on}
 */
export function installMapLayers({ globe, hudRow, host, say = () => {}, bodyName = "Moon", fetchFn = u => fetch(u) }) {
  let layers = [], on = "photo", button = null;
  const panel = document.createElement("aside");
  panel.className = "mlayers"; panel.hidden = true; panel.setAttribute("role", "dialog"); panel.setAttribute("aria-label", "Maps");

  function draw() {
    panel.innerHTML = panelHtml(layers, on, bodyName);
    panel.querySelectorAll("[data-layer]").forEach(b => (b.onclick = () => pick(b.dataset.layer, { speak: true })));
    panel.querySelector(".ml-close").onclick = () => close();
  }
  function label() { if (button) { const l = layers.find(x => x.id === on); button.textContent = on === "photo" ? "Maps" : `Map: ${l ? l.title : ""}`; } }
  async function pick(id, { speak = false } = {}) {
    const l = layers.find(x => x.id === id);
    if (!l || !globe.setBaseMap) return false;
    on = l.id; draw(); label();
    document.body.dataset.mapLayer = l.id === "photo" ? "" : l.id;
    const ok = await globe.setBaseMap(l.url);
    if (!ok && l.url) { on = "photo"; draw(); label(); document.body.dataset.mapLayer = ""; return false; }
    if (speak && l.say) say(l.say);
    return true;
  }
  function open() {
    if (!layers.length) return false;
    const rocks = (window.__outpost || {}).rocks; if (rocks && rocks.isOpen) rocks.close();   // one panel on the right at a time
    draw(); panel.hidden = false; button && button.setAttribute("aria-pressed", "true");
    const t = panel.querySelector(`[data-layer="${on}"]`); if (t) t.focus({ preventScroll: true });
    return true;
  }
  function close() { panel.hidden = true; if (button) { button.setAttribute("aria-pressed", "false"); } }

  const ready = Promise.resolve().then(() => fetchFn(LIBRARY_API)).then(r => (r && r.ok ? r.json() : null)).catch(() => null).then(raw => {
    layers = normalizeLayers(raw);
    if (!layers.length || !hudRow || !globe.setBaseMap) return [];
    host.append(panel);
    button = document.createElement("button");
    button.type = "button"; button.id = "mapsBtn"; button.setAttribute("aria-pressed", "false"); button.textContent = "Maps";
    button.onclick = () => (panel.hidden ? open() : close());
    hudRow.append(button);
    // the photo comes back whenever the cadet leaves the Library (lessons and missions are written for it)
    new MutationObserver(() => {
      if (document.body.dataset.mode !== "cadet") { close(); if (on !== "photo") pick("photo"); }
    }).observe(document.body, { attributes: true, attributeFilter: ["data-mode"] });
    addEventListener("click", e => { if (e.target && e.target.id === "rocksBtn") close(); }, true);
    (window.__outpost = window.__outpost || {}).mapLayers = { get layers() { return layers; }, get on() { return on; }, pick, open, close };
    return layers;
  });
  return { ready, pick, open, close, get on() { return on; }, get layers() { return layers; } };
}
