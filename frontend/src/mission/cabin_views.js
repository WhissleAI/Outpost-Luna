// The cabin's real NASA views (0.4 part 2, docs/MEDIA.md "NASA views"): the Earth inset in the Earth view and the real
// Sun (SDO) in the storm alert and on the Radiation console. Everything here is optional: without the nasa_views pack
// the cabin keeps today's visuals (the plain Earth note, the storm icon). The pure parts are tested in node
// (tests/cabin_views.test.js); the DOM parts only build strings and swap <img> sources.
import { onViews, image, sdoFrames, sdoInfo } from "../media/nasa_views.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const SUN_CREDIT = "The actual Sun, 14 May 2024";
export const SUN_SOURCE = "NASA/SDO";

/**
 * What the Earth view says when Earth is below the horizon (Horizons elevations from the sim, the same numbers as the
 * readouts). -> {day, line, arrow: "up" | "down", trend: "rising" | "setting" | "low", el, photo: "earthrise" | "earthset"}
 * or null while Earth is up.
 *   env:    state.env ({earth_visible, earth_elev_deg, next_comm_window_h})
 *   timeH:  mission time (h)
 *   prevEl: the last elevation seen (null at first): the trend
 */
export function earthBelow(env, timeH, prevEl = null) {
  const e = env || {};
  if (e.earth_visible) return null;
  const t = +timeH || 0, h = e.next_comm_window_h, el = e.earth_elev_deg == null ? null : +e.earth_elev_deg;
  const day = h != null ? Math.floor((t + h) / 24) + 1 : null, today = Math.floor(t / 24) + 1;
  const never = day == null || day > 10;
  const line = never ? "Earth won't rise again this mission." : day === today ? "Earth rises later today." : `Earth rises Day ${day}.`;
  const d = el != null && prevEl != null ? el - prevEl : 0;
  const trend = d > 0.005 ? "rising" : d < -0.005 ? "setting" : never ? "low" : "rising";
  // Earthrise (Apollo 8) while it will rise again this mission; Earthset (Artemis II) once it won't come back
  return { day: never ? null : day, line, arrow: trend === "setting" ? "down" : "up", trend, el, photo: never ? "earthset" : "earthrise" };
}

/** The elevation line under the inset: "2.4° below the horizon · rising". */
export function elevLine(info) {
  if (!info || info.el == null) return "";
  return `${Math.abs(info.el).toFixed(1)}° below the horizon${info.trend === "low" ? "" : ` · ${info.trend}`}`;
}

const FLARE_MIN = 16 * 60 + 51;   // the X8.7 flare peaked at 16:51 UTC
/** The SDO frame to hold under Less motion: the one nearest the X8.7 flare (16:51 UTC), else the middle frame. Pure. */
export function stillFrame(frames) {
  if (!frames || !frames.length) return null;
  const mins = f => { const m = /T(\d{2}):(\d{2})/.exec(f.time || ""); return m ? +m[1] * 60 + +m[2] : null; };
  const near = frames.filter(f => mins(f) != null).sort((a, b) => Math.abs(mins(a) - FLARE_MIN) - Math.abs(mins(b) - FLARE_MIN))[0];
  return near || frames[Math.floor(frames.length / 2)];
}

/** "16:55 UTC" for a frame's time (shown small under the loop; the date is in the credit line). Pure. */
export function frameTime(t) {
  const m = /T(\d{2}):(\d{2})/.exec(String(t || ""));
  return m ? `${m[1]}:${m[2]} UTC` : "";
}

/** The Earth inset's HTML (photo, line, arrow, elevation, credit). `photo` is an image() entry or null (no pack). */
export function earthInsetHtml(info, photo, icon) {
  const arrow = `<span class="cb-ei-arrow is-${info.arrow}" aria-hidden="true">${icon(info.arrow === "down" ? "trend-down" : "trend-up", 18)}</span>`;
  const el = elevLine(info);
  if (!photo) return `${icon("earth", 18)}<span><b>Earth is below the horizon.</b> ${esc(info.line.replace(/^Earth /, "It "))}</span>`;
  return `<img class="cb-ei-img is-${esc(info.photo)}" src="${esc(photo.url)}" alt="${esc(photo.title || "Earth over the Moon's horizon")}" decoding="async">
    <span class="cb-ei-t"><b>${esc(info.line)}</b>${el ? `<span class="cb-ei-el">${arrow}${esc(el)}</span>` : ""}
    <small class="cb-ei-c">${esc(photo.title || "")}${photo.credit ? ` · ${esc(photo.credit)}` : ""}</small></span>`;
}

/** cb(views) once the pack is ready; the cabin repaints. Returns the unsubscribe (dispose). */
export const whenViews = cb => onViews(cb);
export const earthPhoto = id => image(id);
export const sun = () => { const f = sdoFrames(); return f.length ? { frames: f, info: sdoInfo() } : null; };

// ---------------- [0.4 cabin 2] the Sun you can recognise ----------------
// The SDO frames are AIA 131 Å: a dim teal disc on black (median ~35/255; the flare frame is exposed down further). At
// 50-90 px in the cabin that read as a "dark teal blob". Each frame is drawn once into a small canvas, its brightness
// stretched to the lit pixels (1st…99.7th percentile) and mapped onto a gold ramp (the colour people know the Sun by;
// AIA colours are false colours anyway, docs/MEDIA.md). The whole disc stays in view, limb and all, so AR 13664 and
// its X8.7 flare at the west limb are visible; a ring marks the region.

/** AR 13664 in the pack's frames (fraction of the frame, x from the left, y from the top): the brightest spot on every
 *  frame, at the west limb, where the X8.7 flare went off (measured on sdo/00-17.jpg). */
export const FLARE_XY = [0.865, 0.615];
/** The disc's centre and radius (fraction of the frame): the canvas crops to the disc plus a little corona. */
export const DISC = { cx: 0.5, cy: 0.497, r: 0.43 };

const RAMP = [[0, [0, 0, 0]], [0.18, [70, 10, 0]], [0.45, [214, 82, 10]], [0.72, [255, 170, 48]], [0.9, [255, 226, 140]], [1, [255, 255, 236]]];
/** The gold ramp: 0..1 -> [r, g, b] (black, deep red, orange, gold, white-hot). Pure. */
export function sunTone(v) {
  const x = Math.max(0, Math.min(1, +v || 0));
  for (let i = 1; i < RAMP.length; i++) {
    const [b, cb] = RAMP[i]; if (x > b) continue;
    const [a, ca] = RAMP[i - 1], t = (x - a) / (b - a || 1);
    return ca.map((c, k) => Math.round(c + (cb[k] - c) * t));
  }
  return RAMP[RAMP.length - 1][1].slice();
}

/** The contrast stretch: [lo, hi] luminance (0-255) at the 1st and 99.7th percentile of the pixels above `floor` (the
 *  black sky does not count). hist: 256 counts. Pure. */
export function stretchBounds(hist, floor = 8) {
  let n = 0; for (let i = floor; i < 256; i++) n += hist[i];
  if (!n) return [0, 255];
  const at = q => { let c = 0; for (let i = floor; i < 256; i++) { c += hist[i]; if (c >= q * n) return i; } return 255; };
  const lo = at(0.01), hi = Math.max(lo + 16, at(0.997));
  return [lo, Math.min(255, hi)];
}

/** Recolour RGBA pixels in place: luminance, stretched, a gentle gamma, the gold ramp. -> the same array. Pure. */
export function toneSun(px) {
  const hist = new Array(256).fill(0), Y = new Uint8Array(px.length / 4);
  for (let i = 0, j = 0; i < px.length; i += 4, j++) { const y = Math.round(0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]); Y[j] = y; hist[y]++; }
  const [lo, hi] = stretchBounds(hist), lut = [];
  for (let y = 0; y < 256; y++) lut[y] = sunTone(Math.pow(Math.max(0, Math.min(1, (y - lo) / (hi - lo))), 0.85));
  for (let i = 0, j = 0; i < px.length; i += 4, j++) { const c = lut[Y[j]]; px[i] = c[0]; px[i + 1] = c[1]; px[i + 2] = c[2]; px[i + 3] = 255; }
  return px;
}

const SUN_PX = 320;            // each prepared frame: 320 px square (sharp at the console's largest size, cheap to draw)
const ready = new Map();       // url -> Promise<canvas | null>, shared by the storm strip and the Radiation console
/** One frame, loaded, decoded, cropped to the disc and toned. Resolves null when it can't load (the loop skips it). */
export function prepareFrame(url) {
  if (ready.has(url)) return ready.get(url);
  const p = new Promise(res => {
    if (typeof Image === "undefined" || typeof document === "undefined") { res(null); return; }
    const im = new Image(); im.decoding = "async";
    im.onload = () => {
      try {
        const c = document.createElement("canvas"); c.width = c.height = SUN_PX;
        const g = c.getContext("2d", { willReadFrequently: true }), W = im.naturalWidth, H = im.naturalHeight, r = DISC.r * 1.12;
        g.drawImage(im, (DISC.cx - r) * W, (DISC.cy - r) * H, 2 * r * W, 2 * r * H, 0, 0, SUN_PX, SUN_PX);
        try { const d = g.getImageData(0, 0, SUN_PX, SUN_PX); toneSun(d.data); g.putImageData(d, 0, 0); }
        catch (e) { c.dataset.raw = "1"; }   // a cross-origin frame can't be read: the raw frame, brightened by CSS
        res(c);
      } catch (e) { res(null); }
    };
    im.onerror = () => res(null);
    im.src = url;
  });
  ready.set(url, p);
  return p;
}
/** Warm the frames before a storm needs them: the flare frame first (the one shown first), then the rest in order. */
export function preloadSun(frames) {
  if (!frames || !frames.length) return Promise.resolve([]);
  const first = stillFrame(frames);
  return prepareFrame(first.url).then(() => Promise.all(frames.map(f => prepareFrame(f.url))));
}
/** Where the flare ring sits on a crop of the disc (fractions of the canvas). Pure. */
export function flareOnCanvas() {
  const r = DISC.r * 1.12;
  return [(FLARE_XY[0] - (DISC.cx - r)) / (2 * r), (FLARE_XY[1] - (DISC.cy - r)) / (2 * r)];
}
/** The order the loop plays: from the flare frame onward, round the day, so the first thing seen is the storm's Sun
 *  (never the dark first frame of the day). Pure. */
export function playOrder(frames) {
  if (!frames || !frames.length) return [];
  const k = Math.max(0, frames.indexOf(stillFrame(frames)));
  return frames.slice(k).concat(frames.slice(0, k));
}

/** A frame loop on one <canvas>: ~2.5 s through the day from the flare frame, pausing on it; Less motion holds the
 *  flare frame. A frame that isn't ready yet is skipped (the last one stays up), so it never flashes dark. -> stop() */
export function loopFrames(cv, frames, { reduced = () => false, ms = 140 } = {}) {
  if (!cv || !frames || !frames.length) return () => {};
  const order = playOrder(frames), still = order[0], g = cv.getContext && cv.getContext("2d");
  let i = 0, t = 0, alive = true;
  const fig = cv.closest ? cv.closest(".cb-sunmon, .cb-al-sun") : null;
  const show = f => prepareFrame(f.url).then(c => {
    if (!alive || !c || !g) return false;
    g.clearRect(0, 0, cv.width, cv.height); g.drawImage(c, 0, 0, cv.width, cv.height);
    cv.classList.toggle("is-raw", !!c.dataset.raw); cv.classList.add("is-ready");
    if (fig) { const tEl = fig.querySelector(".cb-sun-time"); if (tEl) tEl.textContent = frameTime(f.time);
      fig.classList.toggle("is-flare", !!f.flare || f === still); }
    return true;
  });
  const tick = () => {
    if (!alive) return;
    const f = reduced() ? still : order[i = (i + 1) % order.length];
    show(f).finally(() => { if (alive) t = setTimeout(tick, reduced() ? 2000 : f === still ? 1400 : ms); });
  };
  preloadSun(frames);
  show(still).finally(() => { if (alive) t = setTimeout(tick, 1400); });
  return () => { alive = false; clearTimeout(t); };
}
