// permissions.js with a fake session: camera + mic for our own origin only, the macOS prompt path, offline filter.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { lockDownSession } = require("./permissions");

const ORIGIN = "http://127.0.0.1:47310";
function fakeSession() {
  const s = { webRequest: { onBeforeRequest: (h) => { s.filter = h; } }, setPermissionRequestHandler: (h) => { s.req = h; }, setPermissionCheckHandler: (h) => { s.check = h; } };
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
