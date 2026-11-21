// NASA video for lessons, briefings and debriefs (docs/MEDIA.md).
//
//   import { openVideo, isAvailable } from "./media/video.js";
//   const s = await isAvailable("psr");            // "cached" | "online" | "offline"  (label: "Watch (2 min)" / "Needs internet")
//   const { watched, seconds } = await openVideo("psr", { context: "lesson" });   // resolves when the overlay closes
//
// The catalog (backend/data/video/catalog.json, GET /api/video/catalog) says what each id is:
//   nasa_file  our own <video> player, captions on (WebVTT from the backend), played from the offline cache (or
//              streamed through the backend and cached on its first play)
//   pack_file  the same player, from the desktop's video pack only (a NASA re-encode, or a video used with permission)
//   youtube    a youtube-nocookie embed (≥ 480×270, nothing drawn over it; our buttons and the credit sit outside the
//              frame), online only; never cached. When it won't play and has no NASA fallback, the card offers
//              "Watch on YouTube" (the system browser, behind the desktop's grown-up gate)
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
import { videoCommand, INTENT_CMD, watchLabel, lengthLabel, NEEDS_NET, OFFLINE_LINE, needsNet, offlineLine, NO_PLAY_LINE, NO_PLAY_LESSON, watchedEnough, youtubeSrc, youtubeWatchUrl, WATCH_ON_YOUTUBE, stallWatch, YT_STALL_MS, DOWNLOADING, DOWNLOADING_LINE } from "./commands.js";

export { videoCommand, watchLabel, lengthLabel, NEEDS_NET, OFFLINE_LINE, needsNet, offlineLine, NO_PLAY_LINE, watchedEnough, youtubeSrc, youtubeWatchUrl, WATCH_ON_YOUTUBE, DOWNLOADING, DOWNLOADING_LINE };

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

/** "cached" (plays offline), "online" (needs internet, which we have), "offline", or "downloading" (a course's own
 *  video on its way after a course switch: it plays once saved, never streams meanwhile). Never throws. */
export async function isAvailable(id) {
  try {
    const r = await fetch(`/api/video/${encodeURIComponent(id)}/available`);
    if (!r.ok) return "offline";
    const s = (await r.json()).status;
    if (s === "online" && typeof navigator !== "undefined" && navigator.onLine === false) return "offline";
    return s === "cached" || s === "online" || s === "downloading" ? s : "offline";
  } catch (e) { return "offline"; }
}
export const DOWNLOAD_POLL_MS = 2000;

/**
 * After the player failed: is that because we are offline ("offline") or something else ("error": the embed refused,
 * an unknown id, a backend hiccup)? navigator.onLine first, then one quick backend check. Never throws.
 */
export async function diagnose(id) {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return "offline";
  try {
    const ac = typeof AbortController !== "undefined" ? new AbortController() : null;
    const t = ac ? setTimeout(() => ac.abort(), 4000) : 0;
    const r = await fetch(`/api/video/${encodeURIComponent(id)}/available`, ac ? { signal: ac.signal } : {});
    clearTimeout(t);
    if (!r.ok) return "error";
    return (await r.json()).status === "offline" ? "offline" : "error";
  } catch (e) { return "error"; }
}

/** Every video the catalog lists, for the credits (About → Videos). */
export async function credits() {
  try { return (await catalog()).map(v => ({ id: v.id, title: v.title, credit: v.credit, source: v.source, nasa: v.nasa })); } catch (e) { return []; }
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
    // open palm = pause; thumbs down ("No thanks") = close, so a gesture can always get out of the overlay
    // [flows] a thumbs up (or Enter / "yes") on a paused video plays it again (the map's "continue" gesture)
    const c = ev.name === "stop" && ev.source !== "voice" ? "pause" : ev.name === "no" && ev.source === "voice" ? null
      : ev.name === "yes" && ev.source !== "voice" ? (cur.paused ? "play" : null) : INTENT_CMD[ev.name];
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
  // [video fix 0.3.11] the fallback is offered when it can play now: saved, or (on the "won't play here" card, which
  // only shows while we are online) streamed and saved on its first play
  const fbStatus = fb ? await isAvailable(fb.id) : "offline";
  return new Promise(resolve => run({ v: v || { id, title: "Video", credit: "", duration_s: 0, missing: true }, status, fb: fbStatus !== "offline" ? fb : null, fbCached: fbStatus === "cached", context, resolve }));
}

function run({ v, status, fb: fbAll, fbCached = true, context, resolve }) {
  shell.stopOthers();
  const dlg = dialogEl(), before = document.activeElement;
  let seconds = 0, ended = false, closed = false, extra = {}, detach = () => {}, started = false;
  let player = null;   // {play(), pause(), toggle(), duck(l), unduck(), dispose(), paused, ended, text()}

  function mount(kind, item) {
    if (player) { player.dispose(); detach(); detach = () => {}; }
    const stage = dlg.querySelector(".vid-stage"), bar = dlg.querySelector(".vid-bar");
    dlg.querySelector("#vidTitle").textContent = item.title;
    dlg.querySelector(".vid-credit").textContent = item.credit ? `Video: ${item.credit}${kind === "youtube" ? " · YouTube" : ""}` : "";
    if (kind === "offline" || kind === "error") { player = null; offlineCard(stage, bar, item, kind); return; }
    if (kind === "downloading") { player = null; downloadingCard(stage, bar, item); return; }
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
    // not saved and the network went: the card. [video fix 0.3.11] One quiet retry first when nothing has played yet:
    // the first play of a NASA file is cached in the background, so a second ask a moment later usually plays it.
    let retried = false;
    el.addEventListener("error", () => {
      if (closed || !player || player.el !== el) return;
      if (!retried && !started) {
        retried = true;
        setTimeout(() => { if (closed || !player || player.el !== el) return; el.src = item.play_url + (item.play_url.includes("?") ? "&" : "?") + "retry=1"; el.load(); el.play().catch(() => paint()); }, 1500);
        return;
      }
      failed(item.id);
    });
    el.addEventListener("click", () => (el.paused ? el.play() : el.pause()));
    pp.onclick = () => (el.paused || el.ended ? el.play() : el.pause());
    const cc = bar.querySelector("[data-cc]"); if (cc) cc.onclick = () => showCaptions(cc.getAttribute("aria-pressed") !== "true");
    el.play().catch(() => paint());
    pp.focus({ preventScroll: true });
    return { el,
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
    let state = -1, last = 0, ready = false, heard = false;
    // the frame never answered (no network, or blocked): after a while, ask what is wrong and show the right card
    const quiet = setTimeout(() => { if (!heard) failed(item.id, { onlyOffline: true }); }, 15000);
    // [video fix 0.3.11] the embed answered but never plays (YouTube's "confirm you're not a bot" card, no onError):
    // after YT_STALL_MS from a play request, "This video won't play here" with the NASA fallback
    const watch = stallWatch(() => {
      if (closed || player !== self) return;
      extra.error = extra.error || "stalled"; dlg.dataset.yterror = "stalled";
      failed(item.id);
    });
    watch.play(YT_STALL_MS + 8000);   // from mount: the frame's own load, then onReady's playVideo re-arms it
    const send0 = (func, args = []) => { try { fr.contentWindow.postMessage(JSON.stringify({ event: "command", func, args, id: 1, channel: "widget" }), YT_ORIGIN); } catch (e) { /* */ } };
    const send = (func, args = []) => { if (func === "playVideo") watch.play(); send0(func, args); };
    const paint = () => { const p = state === 1 || state === 3; pp.innerHTML = `${icon(p ? "pause" : "play")}<span>${p ? "Pause" : "Play"}</span>`; pp.setAttribute("aria-label", p ? "Pause" : "Play"); };
    const onMsg = e => {
      if (e.origin !== YT_ORIGIN || e.source !== fr.contentWindow) return;
      let m; try { m = typeof e.data === "string" ? JSON.parse(e.data) : e.data; } catch (x) { return; }
      if (!m || !m.event) return;
      if (m.event === "onReady" || (m.event === "initialDelivery" && !ready)) { ready = true; send("playVideo"); }
      heard = true;
      if (m.event === "onError") { extra.error = m.info; dlg.dataset.yterror = String(m.info); if (state !== 1) failed(item.id); return; }
      const info = m.info && typeof m.info === "object" ? m.info : {};
      const s = m.event === "onStateChange" ? m.info : info.playerState;
      if (typeof s === "number" && s !== state) {
        state = s; paint(); watch.state(s);
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
    const self = {
      play: () => send("playVideo"), pause: () => send("pauseVideo"), toggle: () => send(state === 1 || state === 3 ? "pauseVideo" : "playVideo"),
      duck: l => send("setVolume", [Math.round(l * 100)]), unduck: () => send("setVolume", [100]),
      dispose: () => { clearTimeout(quiet); watch.dispose(); removeEventListener("message", onMsg); removeEventListener("outpost:mute", onYtMute); fr.src = "about:blank"; },
      get paused() { return state !== 1 && state !== 3; }, get ended() { return state === 0; },
      text: () => "",
    };
    return self;
  }

  /** The player failed: the offline card only when we really are offline, else "This video won't play here". */
  function failed(id, { onlyOffline = false } = {}) {
    const p = player;
    diagnose(id).then(why => {
      if (closed || player !== p) return;   // closed, or something else mounted meanwhile
      if (onlyOffline && why !== "offline") return;
      mount(why, v);
    });
  }

  // ---- offline / not saved (or won't play): the NASA still, the line, and the NASA video we have instead ----
  function offlineCard(stage, bar, item, kind = "offline") {
    if (!stage || !bar) return;   // never write anywhere but inside our own overlay
    if (kind === "offline") extra.offline = true; else { delete extra.offline; extra.failed = true; }
    dlg.dataset.card = kind;
    // offline, only a saved fallback can play; "won't play here" (we are online) may stream it
    const fb = fbAll && (kind !== "offline" || fbCached) && fbAll.id !== item.id ? fbAll : null;
    const poster = item.poster_src || (fbAll && fbAll.poster_src);
    stage.innerHTML = `<div class="vid-off" role="status">
        ${poster ? `<img class="vid-off-img" alt="" src="${esc(poster)}">` : `<span class="vid-off-ico">${icon("moon", { size: 48 })}</span>`}
        <p class="vid-off-line">${esc(kind === "offline" ? offlineLine() : NO_PLAY_LINE)}${context === "lesson" ? ` ${esc(NO_PLAY_LESSON)}` : ""}</p></div>`;
    const img = stage.querySelector(".vid-off-img");   // no inline onerror: the app's CSP allows no inline script
    if (img) img.onerror = () => img.remove();
    // [videos offline] a YouTube video that won't play here (the bot card, an embed error) and has no NASA file to offer
    // instead: "Watch on YouTube" opens the youtube.com page in the system browser, where a signed-in grown-up usually
    // passes the bot check. The desktop shell opens it only after the grown-up gate's 3-second hold (gate.js).
    const yt = !fb && kind === "error" && item.source === "youtube" ? youtubeWatchUrl(item.youtube_id) : null;
    bar.innerHTML = `${fb ? `<button type="button" class="btn-primary" data-fb>${icon("play")}<span>Watch NASA's ${esc(lengthLabel(fb.duration_s))} video instead</span></button>` : ""}
      ${yt ? `<button type="button" class="btn-primary" data-yt>${icon("external")}<span>${esc(WATCH_ON_YOUTUBE)}</span></button>` : ""}
      <button type="button" class="${fb || yt ? "btn" : "btn-primary"} vid-x" data-close>${icon("close")}<span>Close</span></button>`;
    const b = bar.querySelector("[data-fb]");
    if (b) b.onclick = () => { delete extra.offline; delete dlg.dataset.card; extra.fallback = fb.id; mount("file", fb); };
    const y = bar.querySelector("[data-yt]");
    if (y) y.onclick = () => { extra.youtube = true; try { window.open(yt, "_blank", "noopener"); } catch (e) { /* */ } };
    (b || y || bar.querySelector("[data-close]")).focus({ preventScroll: true });
  }

  // ---- [course switch] still downloading: the NASA still, a calm line, and it plays by itself once it is saved ----
  function downloadingCard(stage, bar, item) {
    if (!stage || !bar) return;
    dlg.dataset.card = "downloading";
    stage.innerHTML = `<div class="vid-off vid-dl" role="status">
        ${item.poster_src ? `<img class="vid-off-img" alt="" src="${esc(item.poster_src)}">` : `<span class="vid-off-ico">${icon("moon", { size: 48 })}</span>`}
        <p class="vid-off-line">${esc(DOWNLOADING_LINE)}</p></div>`;
    const img = stage.querySelector(".vid-off-img");
    if (img) img.onerror = () => img.remove();
    bar.innerHTML = `<button type="button" class="btn-primary vid-x" data-close>${icon("close")}<span>Close</span></button>`;
    bar.querySelector("[data-close]").focus({ preventScroll: true });
    const tick = async () => {
      if (closed || dlg.dataset.card !== "downloading") return;
      const s = await isAvailable(item.id);
      if (closed || dlg.dataset.card !== "downloading") return;
      if (s === "cached") { delete dlg.dataset.card; mount("file", item); return; }
      if (s !== "downloading") { mount("offline", item); return; }   // the download stopped (offline): say so plainly
      setTimeout(tick, DOWNLOAD_POLL_MS);
    };
    setTimeout(tick, DOWNLOAD_POLL_MS);
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
    dlg.innerHTML = ""; delete dlg.dataset.ytstate; delete dlg.dataset.yterror; delete dlg.dataset.card;
    cur = null; changed();
    try { if (before && before.isConnected) before.focus({ preventScroll: true }); } catch (e) { /* */ }
    const secs = Math.round(seconds * 10) / 10;
    resolve({ watched: watchedEnough(secs, v.duration_s, ended), seconds: secs, ...extra, ...(how === "skip" ? { skipped: true } : {}) });
  }
  // [videos offline] <dialog>'s "close" event is queued, not fired in close(): when one video closes and the next opens
  // within a few ms (the catalog cached, the file local), the OLD close event lands after the new showModal() and
  // closed the new video at once (caught by the release check's video sweep). A close event while the dialog is open
  // again is that stale one: ignored.
  const onClose = () => { if (!dlg.open) finish("closed"); };

  dlg.innerHTML = `<div class="vid-box">
      <header class="vid-head"><h2 id="vidTitle"></h2><button type="button" class="x" data-close aria-label="Close video">${icon("close")}</button></header>
      <div class="vid-stage"></div>
      <div class="vid-bar" role="group" aria-label="Video controls"></div>
      <p class="vid-credit"></p></div>`;
  dlg.addEventListener("close", onClose);
  dlg.onclick = e => { if (e.target.closest("[data-close]")) finish("closed"); };
  cur = { v, context, finish, get paused() { return !!(player && player.paused); },
    cmd(c) {
      if (c === "stop") return finish("closed");
      if (c === "skip") return finish("skip");
      if (!player) return;
      if (c === "pause") player.pause(); else if (c === "play") player.play(); else if (c === "toggle") player.toggle();
    } };
  // [robustness] one sheet at a time: Settings and the gestures calibration are plain elements and would sit under the
  // dialog's top layer, inert; they close themselves on this event
  try { dispatchEvent(new CustomEvent("outpost:modal-open", { detail: { kind: "video" } })); } catch (e) { /* */ }
  if (!dlg.open) dlg.showModal();
  const kind = v.missing ? "error" : v.source === "youtube" ? (status === "online" ? "youtube" : "offline")
    : status === "cached" || status === "online" ? "file" : status === "downloading" ? "downloading" : "offline";
  mount(kind, v);
  changed();
}
