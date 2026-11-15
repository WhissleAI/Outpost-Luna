// NASA video for lessons, briefings and debriefs (docs/MEDIA.md).
//
//   import { openVideo, isAvailable } from "./media/video.js";
//   const s = await isAvailable("psr");            // "cached" | "online" | "offline"  (label: "Watch (2 min)" / "Needs internet")
//   const { watched, seconds } = await openVideo("psr", { context: "lesson" });   // resolves when the overlay closes
//
// The catalog (backend/data/video/catalog.json, GET /api/video/catalog) says what each id is:
//   nasa_file  our own <video> player, captions on (WebVTT from the backend), played from the offline cache (or
//              streamed through the backend and cached on its first play)
//   youtube    a youtube-nocookie embed (≥ 480×270, nothing drawn over it; our buttons and the credit sit outside the
//              frame), online only; never cached
// Offline (or not saved yet): a card with the NASA still, "Needs internet. Ask a grown-up to connect." and, when the
// catalog maps one (`fallback`), the cached NASA video instead.
//
// While a video plays it joins the floor's crew channel (floor.attachMedia): the ear is gated and ducked as for crew
// clips, and voice takes only pause / play / skip / stop (commands.js; the router's video screen does the same).
// Keyboard, remote and gamepad: the overlay is a modal <dialog>, so input/spatial.js traps focus in it; Esc / B close
// it; K / the controller's Back button pause and play.
import { floor } from "../floor.js";
import { onIntent } from "../input/intents.js";
import { icon } from "../assets/icons.js";
import { videoCommand, INTENT_CMD, watchLabel, lengthLabel, NEEDS_NET, OFFLINE_LINE, watchedEnough, youtubeSrc } from "./commands.js";

export { videoCommand, watchLabel, lengthLabel, NEEDS_NET, OFFLINE_LINE, watchedEnough, youtubeSrc };

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const YT_ORIGIN = "https://www.youtube-nocookie.com";

// ---------------------------------------------------------------- catalog + availability ----------------------------
let catP = null;
/** The catalog, fetched once (a failure is retried on the next call). */
export function catalog() {
  if (!catP) catP = fetch("/api/video/catalog").then(r => { if (!r.ok) throw new Error("catalog " + r.status); return r.json(); })
    .catch(e => { catP = null; throw e; });
  return catP;
}
export async function getVideo(id) { try { return (await catalog()).find(v => v.id === id) || null; } catch (e) { return null; } }

/** "cached" (plays offline), "online" (needs internet, which we have) or "offline". Never throws. */
export async function isAvailable(id) {
  try {
    const r = await fetch(`/api/video/${encodeURIComponent(id)}/available`);
    if (!r.ok) return "offline";
    const s = (await r.json()).status;
    if (s === "online" && typeof navigator !== "undefined" && navigator.onLine === false) return "offline";
    return s === "cached" || s === "online" ? s : "offline";
  } catch (e) { return "offline"; }
}

/** Every video the catalog lists, for the credits (About → Videos). */
export async function credits() {
  try { return (await catalog()).map(v => ({ id: v.id, title: v.title, credit: v.credit, source: v.source })); } catch (e) { return []; }
}

// ---------------------------------------------------------------- the overlay ----------------------------------------
let cur = null;          // the open video: {v, context, cmd(c), finish(how)}
const watchers = new Set();
const changed = () => watchers.forEach(f => { try { f(cur ? { id: cur.v.id, context: cur.context } : null); } catch (e) { /* */ } });
/** fn(null | {id, context}) when the overlay opens or closes (main.js tells the router the screen changed). */
export function onVideoChange(fn) { watchers.add(fn); return () => watchers.delete(fn); }
export const isOpen = () => !!cur;
export const current = () => (cur ? { id: cur.v.id, context: cur.context } : null);
/** pause | play | toggle | skip | stop on the open video. False when none is open. */
export function command(c) { if (!cur) return false; cur.cmd(c); return true; }
/** A voice / typed turn while the overlay is up: one of the four commands runs, anything else is swallowed. */
export function handleVoice(text) { if (!cur) return false; const c = videoCommand(text); if (c) cur.cmd(c); return true; }

let shell = { stopOthers: () => {} };
let installed = false;
/** main.js: what to silence when a video starts (the guide, a crew clip). Installs the intent handlers once. */
export function initVideo(o = {}) {
  shell = { ...shell, ...o };
  if (installed) return;
  installed = true;
  // first say on every intent while a video is up: its own controls run; other VOICE intents are dropped (keys,
  // gamepad and gestures still move focus and select inside the overlay; Esc / B close it through keys.js)
  onIntent("*", (args, ev) => {
    if (!cur) return false;
    const c = ev.name === "stop" && ev.source !== "voice" ? "pause" : INTENT_CMD[ev.name];   // open palm = pause
    if (c) { cur.cmd(c); return true; }
    return ev.source === "voice";
  }, { priority: 100 });
  try { (window.__outpost = window.__outpost || {}).video = { openVideo, isAvailable, isOpen, current, command, catalog }; } catch (e) { /* */ }
}

function dialogEl() {
  let d = document.getElementById("vidDlg");
  if (d) return d;
  d = document.createElement("dialog");
  d.id = "vidDlg"; d.className = "vid"; d.setAttribute("aria-labelledby", "vidTitle");
  document.body.append(d);
  return d;
}

const fmt = s => { s = Math.max(0, Math.floor(+s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

/**
 * Open the overlay. Resolves {watched, seconds} when it closes (watched: the end, or ≥ 70% of it; seconds: really
 * played). Extra fields: offline (it could not play), skipped (closed with "skip"), error (YouTube's error code).
 * @param {string} id   catalog id
 * @param {{context?: string}} [o]  where it was opened from ("lesson", "briefing", "debrief"…), for logs
 */
export async function openVideo(id, { context = "" } = {}) {
  if (cur) cur.finish("interrupted");
  const v = await getVideo(id);
  const status = v ? await isAvailable(id) : "offline";
  const fb = v && v.fallback ? await getVideo(v.fallback) : null;
  const fbOk = fb ? (await isAvailable(fb.id)) === "cached" : false;
  return new Promise(resolve => run({ v: v || { id, title: "Video", credit: "", duration_s: 0 }, status, fb: fbOk ? fb : null, context, resolve }));
}

function run({ v, status, fb, context, resolve }) {
  shell.stopOthers();
  const dlg = dialogEl(), before = document.activeElement;
  let seconds = 0, ended = false, closed = false, extra = {}, detach = () => {}, started = false;
  let player = null;   // {play(), pause(), toggle(), duck(l), unduck(), dispose(), paused, ended, text()}

  function mount(kind, item) {
    if (player) { player.dispose(); detach(); detach = () => {}; }
    const stage = dlg.querySelector(".vid-stage"), bar = dlg.querySelector(".vid-bar");
    dlg.querySelector("#vidTitle").textContent = item.title;
    dlg.querySelector(".vid-credit").textContent = item.credit ? `Video: ${item.credit}${kind === "youtube" ? " · YouTube" : ""}` : "";
    if (kind === "offline") { player = null; offlineCard(stage, bar, item); return; }
    player = kind === "file" ? filePlayer(stage, bar, item) : youtubePlayer(stage, bar, item);
    detach = floor ? floor.attachMedia({ get paused() { return player ? player.paused : true; }, get ended() { return player ? player.ended : true; },
      duck: l => player && player.duck(l), unduck: () => player && player.unduck(), text: () => (player ? player.text() : "") }) : () => {};
  }

  // ---- our own player: a NASA file ----
  function filePlayer(stage, bar, item) {
    stage.innerHTML = `<video class="vid-video" playsinline preload="auto" ${item.poster_src ? `poster="${esc(item.poster_src)}"` : ""} src="${esc(item.play_url)}">
        ${item.captions_src ? `<track kind="captions" srclang="en" label="English" src="${esc(item.captions_src)}" default>` : ""}</video>
      <p class="vid-wait" hidden>Loading…</p>`;
    bar.innerHTML = `<button type="button" class="btn-primary vid-pp" data-pp aria-label="Pause">${icon("pause")}<span>Pause</span></button>
      <span class="vid-time" aria-hidden="true"><span data-t>0:00</span> / ${fmt(item.duration_s)}</span>
      <span class="vid-track" aria-hidden="true"><i data-prog></i></span>
      ${item.captions_src ? `<button type="button" class="btn vid-cc" data-cc aria-pressed="true">${icon("captions")}<span>Captions</span></button>` : ""}
      <button type="button" class="btn vid-x" data-close>${icon("close")}<span>Close</span></button>`;
    const el = stage.querySelector("video");
    if (appMuted()) el.muted = true;   // the top bar's Mute (mute.js), silent test runs and demos
    const onMute = e => { el.muted = !!(e.detail && e.detail.muted) || !!(window.__outpost && window.__outpost.muteVideos); };
    addEventListener("outpost:mute", onMute);
    const pp = bar.querySelector("[data-pp]"), tEl = bar.querySelector("[data-t]"), prog = bar.querySelector("[data-prog]");
    let last = 0, vol = 1;
    const showCaptions = on => { const t = el.textTracks && el.textTracks[0]; if (t) t.mode = on ? "showing" : "hidden"; const b = bar.querySelector("[data-cc]"); if (b) b.setAttribute("aria-pressed", String(!!on)); };
    el.addEventListener("loadedmetadata", () => showCaptions(true));
    const paint = () => { const p = !el.paused && !el.ended; pp.innerHTML = `${icon(p ? "pause" : "play")}<span>${p ? "Pause" : "Play"}</span>`; pp.setAttribute("aria-label", p ? "Pause" : "Play"); };
    el.addEventListener("timeupdate", () => {
      const t = el.currentTime, d = t - last; last = t;
      if (!el.paused && d > 0 && d < 1.5) seconds += d;
      tEl.textContent = fmt(t); prog.style.width = `${Math.min(100, 100 * t / (el.duration || item.duration_s || 1))}%`;
    });
    el.addEventListener("seeked", () => { last = el.currentTime; });
    el.addEventListener("play", () => { paint(); if (!started) { started = true; if (floor) floor.mediaPlayback("start", "video:" + item.id); } });
    el.addEventListener("pause", paint);
    el.addEventListener("ended", () => { ended = true; paint(); });
    el.addEventListener("error", () => { extra.offline = true; mount("offline", v); });   // not saved and the network went: the card
    el.addEventListener("click", () => (el.paused ? el.play() : el.pause()));
    pp.onclick = () => (el.paused || el.ended ? el.play() : el.pause());
    const cc = bar.querySelector("[data-cc]"); if (cc) cc.onclick = () => showCaptions(cc.getAttribute("aria-pressed") !== "true");
    el.play().catch(() => paint());
    pp.focus({ preventScroll: true });
    return {
      play: () => el.play().catch(() => {}), pause: () => el.pause(), toggle: () => (el.paused ? el.play().catch(() => {}) : el.pause()),
      duck: l => { vol = l; el.volume = l; }, unduck: () => { vol = 1; el.volume = 1; },
      dispose: () => { removeEventListener("outpost:mute", onMute); el.pause(); el.removeAttribute("src"); el.load(); },
      get paused() { return el.paused; }, get ended() { return el.ended; },
      text: () => { const t = el.textTracks && el.textTracks[0], c = t && t.activeCues; return c && c.length ? [...c].map(x => x.text).join(" ") : ""; },
    };
  }

  /** Start muted: the top bar's Mute (prefs.muted, mute.js) or a silent run (window.__outpost.muteVideos). */
  function appMuted() { const O = window.__outpost || {}; return !!(O.muteVideos || (O.prefs && O.prefs.muted)); }

  // ---- the YouTube embed (youtube-nocookie; the IFrame API's postMessage protocol, no extra script in our page) ----
  function youtubePlayer(stage, bar, item) {
    const silent = appMuted();   // the top bar's Mute, silent test runs and demos: start muted
    const src = youtubeSrc(item.youtube_id, location.origin) + (silent ? "&mute=1" : "");
    stage.innerHTML = `<iframe class="vid-yt" src="${esc(src)}" title="${esc(item.title)} (YouTube)" referrerpolicy="strict-origin-when-cross-origin"
      allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>`;
    bar.innerHTML = `<button type="button" class="btn-primary vid-pp" data-pp aria-label="Pause">${icon("pause")}<span>Pause</span></button>
      <span class="vid-time" aria-hidden="true"><span data-t>0:00</span> / ${fmt(item.duration_s)}</span>
      <button type="button" class="btn vid-x" data-close>${icon("close")}<span>Close</span></button>`;
    const fr = stage.querySelector("iframe"), pp = bar.querySelector("[data-pp]"), tEl = bar.querySelector("[data-t]");
    let state = -1, last = 0, ready = false;
    const send = (func, args = []) => { try { fr.contentWindow.postMessage(JSON.stringify({ event: "command", func, args, id: 1, channel: "widget" }), YT_ORIGIN); } catch (e) { /* */ } };
    const paint = () => { const p = state === 1 || state === 3; pp.innerHTML = `${icon(p ? "pause" : "play")}<span>${p ? "Pause" : "Play"}</span>`; pp.setAttribute("aria-label", p ? "Pause" : "Play"); };
    const onMsg = e => {
      if (e.origin !== YT_ORIGIN || e.source !== fr.contentWindow) return;
      let m; try { m = typeof e.data === "string" ? JSON.parse(e.data) : e.data; } catch (x) { return; }
      if (!m || !m.event) return;
      if (m.event === "onReady" || (m.event === "initialDelivery" && !ready)) { ready = true; send("playVideo"); }
      if (m.event === "onError") { extra.error = m.info; dlg.dataset.yterror = String(m.info); }
      const info = m.info && typeof m.info === "object" ? m.info : {};
      const s = m.event === "onStateChange" ? m.info : info.playerState;
      if (typeof s === "number" && s !== state) {
        state = s; paint();
        if (s === 0) ended = true;
        if (s === 1 && !started) { started = true; if (floor) floor.mediaPlayback("start", "video:" + item.id); }
        dlg.dataset.ytstate = String(s);
      }
      if (typeof info.currentTime === "number") {
        const d = info.currentTime - last; last = info.currentTime;
        if (state === 1 && d > 0 && d < 1.5) seconds += d;
        tEl.textContent = fmt(info.currentTime);
      }
    };
    addEventListener("message", onMsg);
    // "listening": the player starts sending its state (onReady, infoDelivery with currentTime / playerState)
    const listen = () => { try { fr.contentWindow.postMessage(JSON.stringify({ event: "listening", id: 1, channel: "widget" }), YT_ORIGIN); } catch (e) { /* */ } };
    fr.addEventListener("load", () => { listen(); setTimeout(listen, 600); setTimeout(listen, 1500); });
    pp.onclick = () => send(state === 1 || state === 3 ? "pauseVideo" : "playVideo");
    pp.focus({ preventScroll: true });
    // the top bar's Mute while the embed plays: the IFrame API's mute / unMute (a silent run stays muted)
    const onYtMute = e => send((e.detail && e.detail.muted) || (window.__outpost && window.__outpost.muteVideos) ? "mute" : "unMute");
    addEventListener("outpost:mute", onYtMute);
    return {
      play: () => send("playVideo"), pause: () => send("pauseVideo"), toggle: () => send(state === 1 || state === 3 ? "pauseVideo" : "playVideo"),
      duck: l => send("setVolume", [Math.round(l * 100)]), unduck: () => send("setVolume", [100]),
      dispose: () => { removeEventListener("message", onMsg); removeEventListener("outpost:mute", onYtMute); fr.src = "about:blank"; },
      get paused() { return state !== 1 && state !== 3; }, get ended() { return state === 0; },
      text: () => "",
    };
  }

  // ---- offline / not saved: the NASA still, the line, and the NASA video we have instead ----
  function offlineCard(stage, bar, item) {
    extra.offline = true;
    const poster = item.poster_src || (fb && fb.poster_src);
    stage.innerHTML = `<div class="vid-off" role="status">
        ${poster ? `<img class="vid-off-img" alt="" src="${esc(poster)}" onerror="this.remove()">` : `<span class="vid-off-ico">${icon("moon", { size: 48 })}</span>`}
        <p class="vid-off-line">${esc(OFFLINE_LINE)}</p></div>`;
    bar.innerHTML = `${fb ? `<button type="button" class="btn-primary" data-fb>${icon("play")}<span>Watch NASA's ${esc(lengthLabel(fb.duration_s))} video instead</span></button>` : ""}
      <button type="button" class="${fb ? "btn" : "btn-primary"} vid-x" data-close>${icon("close")}<span>Close</span></button>`;
    const b = bar.querySelector("[data-fb]");
    if (b) b.onclick = () => { delete extra.offline; extra.fallback = fb.id; mount("file", fb); };
    (b || bar.querySelector("[data-close]")).focus({ preventScroll: true });
  }

  function finish(how) {
    if (closed) return;
    closed = true;
    try { window.__outpost.videoLast = { id: v.id, how, context }; } catch (e) { /* tests, tools: how the last video closed */ }
    if (started && floor) floor.mediaPlayback(how === "ended" || ended ? "end" : "interrupted", "video:" + v.id);
    if (player) player.dispose();
    detach();
    dlg.removeEventListener("close", onClose);
    if (dlg.open) dlg.close();
    dlg.innerHTML = ""; delete dlg.dataset.ytstate; delete dlg.dataset.yterror;
    cur = null; changed();
    try { if (before && before.isConnected) before.focus({ preventScroll: true }); } catch (e) { /* */ }
    const secs = Math.round(seconds * 10) / 10;
    resolve({ watched: watchedEnough(secs, v.duration_s, ended), seconds: secs, ...extra, ...(how === "skip" ? { skipped: true } : {}) });
  }
  const onClose = () => finish("closed");

  dlg.innerHTML = `<div class="vid-box">
      <header class="vid-head"><h2 id="vidTitle"></h2><button type="button" class="x" data-close aria-label="Close video">${icon("close")}</button></header>
      <div class="vid-stage"></div>
      <div class="vid-bar" role="group" aria-label="Video controls"></div>
      <p class="vid-credit"></p></div>`;
  dlg.addEventListener("close", onClose);
  dlg.onclick = e => { if (e.target.closest("[data-close]")) finish("closed"); };
  cur = { v, context, finish,
    cmd(c) {
      if (c === "stop") return finish("closed");
      if (c === "skip") return finish("skip");
      if (!player) return;
      if (c === "pause") player.pause(); else if (c === "play") player.play(); else if (c === "toggle") player.toggle();
    } };
  if (!dlg.open) dlg.showModal();
  const kind = v.source === "youtube" ? (status === "online" ? "youtube" : "offline")
    : status === "cached" || status === "online" ? "file" : "offline";
  mount(kind, v);
  changed();
}
