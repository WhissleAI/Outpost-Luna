// Outpost Luna desktop: what the renderer may load and which devices it may use. Shared by main.js and the camera
// check harness (desktop/scripts/camera_check/), and unit-tested with fakes (permissions.test.js). No Electron import
// here: the session and systemPreferences are passed in.
"use strict";

/**
 * Offline by construction: the page may load from our backend origin (http + ws), data:, blob:, devtools and file:
 * only; anything else is cancelled at once (logged as "blocked"). Microphone, and the camera for gestures (off until
 * the kid turns it on in Settings; docs/GESTURES.md), are granted to our own origin only. Nothing else (screen
 * capture, geolocation, notifications) for anyone. On macOS the first camera request asks the system
 * (NSCameraUsageDescription in Info.plist).
 */
function lockDownSession(ses, origin, { log = () => {}, platform = process.platform, systemPreferences = null } = {}) {
  const ours = (u) => { try { return new URL(u).origin === origin; } catch { return false; } };
  ses.webRequest.onBeforeRequest((d, cb) => {
    const u = d.url;
    const ok = ours(u) || u.startsWith(origin.replace("http", "ws")) || /^(data|blob|devtools|chrome-extension|file):/.test(u);
    if (!ok) log("blocked", u.slice(0, 160));
    cb({ cancel: !ok });
  });
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

module.exports = { lockDownSession };
