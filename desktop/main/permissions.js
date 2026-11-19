// Outpost Luna desktop: what the renderer may load and which devices it may use. Shared by main.js and the camera
// check harness (desktop/scripts/camera_check/), and unit-tested with fakes (permissions.test.js). No Electron import
// here: the session and systemPreferences are passed in.
"use strict";
const NP = require("./netpolicy");   // School network mode (docs/SCHOOL_IT.md)

// NASA video (docs/MEDIA.md): the one way off our origin. A youtube-nocookie embed (the only frame we let in) and the
// player traffic it needs; never a YouTube page as the main window or a frame. NASA files are NOT here: the backend
// downloads them (backend/app/video.py) and the page plays them from our own origin, so the renderer never talks to NASA.
const YT_FRAME = "www.youtube-nocookie.com";
const YT_HOSTS = new Set([YT_FRAME, "www.youtube.com", "s.ytimg.com", "i.ytimg.com"]);
const YT_REFERER = "https://ai.whissle.outpostluna/";

// The player's own art, by path only (measured in Electron 44, desktop/main/permissions.test.js): the YouTube logo and
// control icons, its Roboto font, and the channel avatar. Without them the video still plays, but unbranded.
const YT_ASSETS = [["www.gstatic.com", "/youtube/"], ["ssl.gstatic.com", "/docs/picker/images/youtube_"], ["fonts.gstatic.com", "/s/i/youtube_"], ["fonts.gstatic.com", "/s/roboto/"],
  ["yt3.ggpht.com", "/"]];

// [video fix 0.3.11] The embed's BotGuard (anti-abuse attestation) script: https://www.google.com/js/th/<hash>.js. When it
// is blocked, YouTube answers with "Sign in to confirm you're not a bot" and never plays (measured in Electron 44.10,
// 2026-11-17; no IFrame API error is sent). Allowed by path and only as a script: never a page, a frame or anything
// else on www.google.com.
// Its answer goes to Google's Web Anti-Abuse service (jnn-pa.googleapis.com/$rpc/google.internal.waa.v1.Waa/Create and
// GenerateIT), allowed by path and only as xhr / fetch.
const YT_BOTGUARD = ["www.google.com", "/js/th/"];
const YT_WAA = ["jnn-pa.googleapis.com", "/$rpc/google.internal.waa.v1.Waa/"];
function isBotGuard(u) { return hostOf(u) === YT_BOTGUARD[0] && pathOf(u).startsWith(YT_BOTGUARD[1]) && /\.js$/.test(pathOf(u)); }
function isWaa(u) { return hostOf(u) === YT_WAA[0] && pathOf(u).startsWith(YT_WAA[1]); }

function hostOf(u) { try { const x = new URL(u); return x.protocol === "https:" ? x.hostname : ""; } catch { return ""; } }
function pathOf(u) { try { return new URL(u).pathname; } catch { return ""; } }
/** A YouTube player host (the embed, its scripts and images, and the video bytes on *.googlevideo.com). */
function isYouTubeHost(u) {
  const h = hostOf(u);
  return YT_HOSTS.has(h) || /^[a-z0-9-]+\.googlevideo\.com$/.test(h) || YT_ASSETS.some(([ah, p]) => ah === h && pathOf(u).startsWith(p));
}
/**
 * May the page load this YouTube URL? The embed itself only as a frame (https://www.youtube-nocookie.com/embed/…);
 * everything else from those hosts only as a sub-resource (script, image, xhr, media…), never as a page or a frame,
 * so a click inside the player can never turn the app into YouTube (links open behind the grown-up gate instead).
 */
function allowYouTube(u, resourceType) {
  if (isBotGuard(u)) return resourceType === "script";
  if (isWaa(u)) return resourceType === "xhr" || resourceType === "fetch";
  if (!isYouTubeHost(u)) return false;
  if (resourceType === "mainFrame") return false;
  if (resourceType === "subFrame") return hostOf(u) === YT_FRAME && pathOf(u).startsWith("/embed/");
  return true;
}

/**
 * Offline by construction: the page may load from our backend origin (http + ws), data:, blob:, devtools and file:
 * only, plus the YouTube embed's traffic (allowYouTube) when a NASA video plays online; anything else is cancelled at
 * once (logged as "blocked"). Offline, the YouTube requests simply fail and the page shows its "Needs internet" card.
 * Microphone, and the camera for gestures (off until the kid turns it on in Settings; docs/GESTURES.md), are granted
 * to our own origin only (never to the YouTube frame). Nothing else (screen capture, geolocation, notifications) for
 * anyone. On macOS the first camera request asks the system (NSCameraUsageDescription in Info.plist).
 * `referer`: send Referer: https://ai.whissle.outpostluna/ to YouTube hosts only (its player refuses to play with no
 * Referer, error 153); off when the loopback origin is accepted as it is.
 */
function lockDownSession(ses, origin, { log = () => {}, platform = process.platform, systemPreferences = null, referer = false,
  policy = null, csp = null } = {}) {
  const ours = (u) => { try { return new URL(u).origin === origin; } catch { return false; } };
  const ourWs = origin.replace("http", "ws");
  ses.webRequest.onBeforeRequest((d, cb) => {
    const u = d.url;
    const local = ours(u) || u === ourWs || u.startsWith(ourWs + "/") || /^(data|blob|devtools|chrome-extension|file):/.test(u);
    let ok = local || allowYouTube(u, d.resourceType);
    // School network mode (netpolicy.js, docs/SCHOOL_IT.md): off our origin, only the hosts an IT admin allowed
    if (ok && !local && policy && !NP.urlAllowed(u, policy())) {
      ok = false;
      log("blocked (school network)", (d.resourceType ? d.resourceType + " " : "") + u.slice(0, 160));
    } else if (!ok) log("blocked", (d.resourceType ? d.resourceType + " " : "") + u.slice(0, 160));
    cb({ cancel: !ok });
  });
  // The page's Content-Security-Policy (hardening.js csp): on every response from our origin, whatever the server sent
  if (csp && ses.webRequest.onHeadersReceived) {
    ses.webRequest.onHeadersReceived((d, cb) => {
      if (!ours(d.url)) return cb({ responseHeaders: d.responseHeaders });
      const h = {};
      for (const [k, v] of Object.entries(d.responseHeaders || {})) if (k.toLowerCase() !== "content-security-policy") h[k] = v;
      h["Content-Security-Policy"] = [csp];
      cb({ responseHeaders: h });
    });
  }
  if (referer && ses.webRequest.onBeforeSendHeaders) {
    ses.webRequest.onBeforeSendHeaders((d, cb) => {
      if (!isYouTubeHost(d.url)) return cb({ requestHeaders: d.requestHeaders });
      cb({ requestHeaders: { ...d.requestHeaders, Referer: YT_REFERER } });
    });
  }
  ses.setPermissionRequestHandler((wc, perm, cb, d = {}) => {
    const okMedia = perm === "media" && ours(d.requestingUrl || wc.getURL()) && (d.mediaTypes || ["audio"]).every((t) => t === "audio" || t === "video");
    if (okMedia && (d.mediaTypes || []).includes("video")) log("camera requested");
    // macOS: the system camera prompt comes from here, the first time only
    if (okMedia && platform === "darwin" && systemPreferences && (d.mediaTypes || []).includes("video") && systemPreferences.getMediaAccessStatus("camera") !== "granted") {
      systemPreferences.askForMediaAccess("camera").then((granted) => { log("camera access", granted ? "granted" : "denied"); cb(granted); }, () => cb(false));
      return;
    }
    // Windows: no per-app prompt. Settings → Privacy & security → Camera / Microphone can switch access off for every
    // desktop app; getUserMedia then fails in the page, which says "blocked". Log what Windows reports, so a log from a
    // tester shows the switch was off (main.log "windows privacy camera: denied"). The grant itself stays Chromium's:
    // the status Windows reports for desktop apps is not reliable enough to refuse on (it can follow the Store-apps switch).
    if (okMedia && platform === "win32" && systemPreferences && systemPreferences.getMediaAccessStatus) {
      for (const t of d.mediaTypes || ["audio"]) {
        const kind = t === "video" ? "camera" : "microphone";
        try { log(`windows privacy ${kind}:`, systemPreferences.getMediaAccessStatus(kind)); } catch { /* older Windows */ }
      }
    }
    cb(okMedia || (perm === "fullscreen" && ours(wc.getURL())) || (perm === "clipboard-sanitized-write" && ours(wc.getURL())));
  });
  ses.setPermissionCheckHandler((wc, perm, reqOrigin) => (perm === "media" || perm === "fullscreen") && reqOrigin === origin);
}

module.exports = { lockDownSession, allowYouTube, isYouTubeHost, YT_REFERER };
