// permissions.js with a fake session: camera + mic for our own origin only, the macOS prompt path, offline filter.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { lockDownSession, allowYouTube, isYouTubeHost, YT_REFERER } = require("./permissions");

const ORIGIN = "http://127.0.0.1:47310";
function fakeSession() {
  const s = { webRequest: { onBeforeRequest: (h) => { s.filter = h; }, onBeforeSendHeaders: (h) => { s.headers = h; } }, setPermissionRequestHandler: (h) => { s.req = h; }, setPermissionCheckHandler: (h) => { s.check = h; } };
  return s;
}
const wc = (url = ORIGIN + "/") => ({ getURL: () => url });
const ask = (s, perm, d, w = wc()) => new Promise((res) => s.req(w, perm, res, d));

test("camera and mic: granted to our own origin only", async () => {
  const s = fakeSession(); lockDownSession(s, ORIGIN, { platform: "linux" });
  assert.equal(await ask(s, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["video"] }), true);
  assert.equal(await ask(s, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["audio"] }), true);
  assert.equal(await ask(s, "media", { requestingUrl: "https://evil.example/", mediaTypes: ["video"] }, wc("https://evil.example/")), false);
  assert.equal(await ask(s, "media", { requestingUrl: "http://127.0.0.1:9999/", mediaTypes: ["video"] }), false, "another loopback port");
  assert.equal(await ask(s, "geolocation", { requestingUrl: ORIGIN + "/" }), false);
  assert.equal(await ask(s, "display-capture", { requestingUrl: ORIGIN + "/" }), false);
  assert.equal(await ask(s, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["video", "screen"] }), false, "no screen capture");
});

test("macOS: the first camera request asks the system; the answer is the grant", async () => {
  const calls = [];
  const sp = (status, answer) => ({ getMediaAccessStatus: () => status, askForMediaAccess: (k) => { calls.push(k); return Promise.resolve(answer); } });
  let s = fakeSession(); lockDownSession(s, ORIGIN, { platform: "darwin", systemPreferences: sp("not-determined", false) });
  assert.equal(await ask(s, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["video"] }), false, "kid/parent said no");
  s = fakeSession(); lockDownSession(s, ORIGIN, { platform: "darwin", systemPreferences: sp("not-determined", true) });
  assert.equal(await ask(s, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["video"] }), true);
  assert.deepEqual(calls, ["camera", "camera"]);
  s = fakeSession(); lockDownSession(s, ORIGIN, { platform: "darwin", systemPreferences: sp("granted", true) });
  assert.equal(await ask(s, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["video"] }), true);
  assert.equal(calls.length, 2, "already granted: no second prompt");
  assert.equal(await ask(s, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["audio"] }), true, "mic never asks for the camera");
  assert.equal(calls.length, 2);
});

test("Windows: no system prompt; the privacy switch is logged and the grant is Chromium's", async () => {
  const logs = [], asked = [];
  const sp = { getMediaAccessStatus: (k) => (k === "camera" ? "denied" : "granted"), askForMediaAccess: (k) => { asked.push(k); return Promise.resolve(true); } };
  const s = fakeSession(); lockDownSession(s, ORIGIN, { platform: "win32", systemPreferences: sp, log: (...a) => logs.push(a.join(" ")) });
  assert.equal(await ask(s, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["video"] }), true);
  assert.equal(await ask(s, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["audio"] }), true);
  assert.equal(await ask(s, "media", { requestingUrl: "https://evil.example/", mediaTypes: ["video"] }, wc("https://evil.example/")), false);
  assert.deepEqual(asked, [], "askForMediaAccess is macOS-only");
  assert.ok(logs.includes("windows privacy camera: denied"), logs.join("\n"));
  assert.ok(logs.includes("windows privacy microphone: granted"), logs.join("\n"));
  assert.equal(logs.filter((l) => l.startsWith("windows privacy")).length, 2, "nothing logged for a foreign origin");
  const s2 = fakeSession(); lockDownSession(s2, ORIGIN, { platform: "win32", systemPreferences: { getMediaAccessStatus: () => { throw new Error("n/a"); } } });
  assert.equal(await ask(s2, "media", { requestingUrl: ORIGIN + "/", mediaTypes: ["video"] }), true, "a throwing status check never blocks");
});

test("offline filter: only our origin, ws, data, blob", () => {
  const s = fakeSession(), blocked = []; lockDownSession(s, ORIGIN, { log: (k, u) => blocked.push(u) });
  const go = (url) => { let r; s.filter({ url }, (x) => { r = x; }); return !r.cancel; };
  assert.equal(go(ORIGIN + "/vision/hand_landmarker.task"), true);
  assert.equal(go("ws://127.0.0.1:47310/ws/session"), true);
  assert.equal(go("blob:" + ORIGIN + "/abc"), true);
  assert.equal(go("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision/wasm/x.wasm"), false);
  assert.equal(go("https://storage.googleapis.com/mediapipe-models/x.task"), false);
  assert.equal(blocked.length, 2);
});

test("NASA video: only the YouTube embed and its player traffic, never a YouTube page; NASA hosts stay blocked", () => {
  const s = fakeSession(), blocked = []; lockDownSession(s, ORIGIN, { log: (k, u) => blocked.push(u) });
  const go = (url, resourceType) => { let r; s.filter({ url, resourceType }, (x) => { r = x; }); return !r.cancel; };
  // the embed, as a frame, and what its player loads (measured in Electron 44 against the dev backend)
  assert.equal(go("https://www.youtube-nocookie.com/embed/jdkMHkF7BaA?rel=0&cc_load_policy=1", "subFrame"), true);
  assert.equal(go("https://www.youtube-nocookie.com/s/player/abc/www-embed-player.js", "script"), true);
  assert.equal(go("https://www.youtube.com/iframe_api", "script"), true);
  assert.equal(go("https://i.ytimg.com/vi/jdkMHkF7BaA/hqdefault.jpg", "image"), true);
  assert.equal(go("https://s.ytimg.com/yts/x.js", "script"), true);
  assert.equal(go("https://rr5---sn-n4v7snlr.googlevideo.com/videoplayback?x=1", "xhr"), true);
  assert.equal(go("https://www.gstatic.com/youtube/img/icons/logo.svg", "image"), true);
  assert.equal(go("https://fonts.gstatic.com/s/roboto/v48/x.woff2", "font"), true);
  assert.equal(go("https://yt3.ggpht.com/avatar=s88", "image"), true);
  // never a YouTube page in the window or a frame, never the plain youtube.com player as a frame
  assert.equal(go("https://www.youtube.com/watch?v=jdkMHkF7BaA", "mainFrame"), false);
  assert.equal(go("https://www.youtube.com/watch?v=jdkMHkF7BaA", "subFrame"), false);
  assert.equal(go("https://www.youtube-nocookie.com/", "subFrame"), false);
  assert.equal(go("https://www.youtube-nocookie.com/embed/x", "mainFrame"), false);
  // look-alikes, plain http, other Google hosts and paths
  assert.equal(go("https://evil-googlevideo.com/x", "xhr"), false);
  assert.equal(go("https://www.youtube.com.evil.example/x.js", "script"), false);
  assert.equal(go("http://www.youtube-nocookie.com/embed/x", "subFrame"), false);
  assert.equal(go("https://www.google.com/js/th/x.js", "script"), false);
  assert.equal(go("https://www.gstatic.com/recaptcha/x.js", "script"), false);
  assert.equal(go("https://fonts.gstatic.com/s/other/x.woff2", "font"), false);
  // the renderer never downloads NASA files: the backend does (backend/app/video.py)
  for (const u of ["https://images-assets.nasa.gov/video/x/x~medium.mp4", "https://svs.gsfc.nasa.gov/vis/x.mp4", "https://nssdc.gsfc.nasa.gov/x.mp4", "https://images-api.nasa.gov/search"]) {
    assert.equal(go(u, "media"), false, u);
  }
  assert.ok(blocked.length >= 13);
  assert.equal(allowYouTube("https://i.ytimg.com/x.jpg", "image"), true);
  assert.equal(isYouTubeHost("https://example.com/"), false);
});

test("the YouTube frame never gets the mic or the camera", async () => {
  const s = fakeSession(); lockDownSession(s, ORIGIN, { platform: "linux" });
  const yt = "https://www.youtube-nocookie.com/embed/jdkMHkF7BaA";
  assert.equal(await ask(s, "media", { requestingUrl: yt, mediaTypes: ["audio"] }), false);
  assert.equal(await ask(s, "media", { requestingUrl: yt, mediaTypes: ["video"] }), false);
});

test("Referer fallback: off by default; on, it is sent to YouTube hosts only", () => {
  const s0 = fakeSession(); lockDownSession(s0, ORIGIN, {});
  assert.equal(s0.headers, undefined, "no header rewriting unless asked");
  const s = fakeSession(); lockDownSession(s, ORIGIN, { referer: true });
  const hdr = (url) => { let r; s.headers({ url, requestHeaders: { Accept: "*/*" } }, (x) => { r = x; }); return r.requestHeaders; };
  assert.equal(hdr("https://www.youtube-nocookie.com/embed/x").Referer, YT_REFERER);
  assert.equal(hdr("https://rr1---sn-x.googlevideo.com/videoplayback").Referer, YT_REFERER);
  assert.equal(hdr(ORIGIN + "/api/video/catalog").Referer, undefined);
  assert.equal(hdr("https://images-assets.nasa.gov/x").Referer, undefined);
});
