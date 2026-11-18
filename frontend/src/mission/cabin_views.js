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

/** A frame loop on one <img>: ~2.5 s through the day; Less motion holds the flare frame. -> stop() */
export function loopFrames(img, frames, { reduced = () => false, ms = 140 } = {}) {
  if (!img || !frames || !frames.length) return () => {};
  let i = 0, t = 0, alive = true;
  // preload so the loop never flashes an empty frame
  frames.forEach(f => { const p = new Image(); p.decoding = "async"; p.src = f.url; });
  const tick = () => {
    if (!alive) return;
    const f = reduced() ? stillFrame(frames) : frames[i = (i + 1) % frames.length];
    if (img.getAttribute("src") !== f.url) img.src = f.url;
    const tEl = img.parentNode && img.parentNode.querySelector(".cb-sun-time"); if (tEl) tEl.textContent = frameTime(f.time);
    // a pause on the flare frame, so it reads as the moment of the storm
    t = setTimeout(tick, reduced() ? 2000 : f === stillFrame(frames) ? 900 : ms);
  };
  img.src = (reduced() ? stillFrame(frames) : frames[0]).url; t = setTimeout(tick, ms);
  return () => { alive = false; clearTimeout(t); };
}
