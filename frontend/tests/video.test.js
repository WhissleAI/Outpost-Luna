// NASA video (src/media/*, docs/MEDIA.md): the voice commands, labels and embed URL; the floor's media channel; the
// lesson's video step with the overlay mocked (predict → Watch / Skip → the answer the server grades → reveal).
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const C = await import("../src/media/commands.js");
const { createFloor } = await import("../src/floor.js");
const UI = await import("../src/media/video_ui.js");
const R = window.__outpost.stepRenderers;

test("voice while a video plays: only pause / play / skip / stop", () => {
  for (const [t, want] of [["pause", "pause"], ["Pause it, please.", "pause"], ["okay play", "play"], ["resume", "play"],
    ["skip", "skip"], ["next", "skip"], ["stop the video", "stop"], ["Close it", "stop"], ["that's enough", "stop"]]) {
    assert.equal(C.videoCommand(t), want, t);
  }
  for (const t of ["where did apollo 11 land", "pause the mission clock", "play the launch", "stop talking to me", ""]) {
    assert.equal(C.videoCommand(t), null, t);
  }
  assert.equal(C.INTENT_CMD.video_pause, "pause");
  assert.equal(C.INTENT_CMD.time_toggle, "toggle");
});

test("labels, watched, the youtube-nocookie embed", () => {
  assert.equal(C.watchLabel({ duration_s: 118 }), "Watch (2 min)");
  assert.equal(C.watchLabel({ duration_s: 48 }), "Watch (48 sec)");
  assert.equal(C.watchLabel({ duration_s: 67 }), "Watch (1 min)");
  assert.equal(C.watchedEnough(80, 100), true);
  assert.equal(C.watchedEnough(30, 100), false);
  assert.equal(C.watchedEnough(3, 100, true), true);
  const u = new URL(C.youtubeSrc("jdkMHkF7BaA", "http://127.0.0.1:47310"));
  assert.equal(u.origin, "https://www.youtube-nocookie.com");
  assert.equal(u.pathname, "/embed/jdkMHkF7BaA");
  for (const [k, v] of [["rel", "0"], ["cc_load_policy", "1"], ["playsinline", "1"], ["enablejsapi", "1"], ["origin", "http://127.0.0.1:47310"]]) {
    assert.equal(u.searchParams.get(k), v, k);
  }
});

test("a playing video holds the floor as crew (the ear gates and ducks it) and leaves it when it stops", () => {
  const f = createFloor(), seen = [];
  f.on("floor", e => seen.push(e.holder));
  const m = { paused: false, ended: false, level: 1, duck(l) { this.level = l; }, unduck() { this.level = 1; }, text: () => "the Moon's shadow" };
  const detach = f.attachMedia(m);
  assert.equal(f.holder, "crew");
  assert.equal(f.onAir, true);
  assert.match(f.crewText, /shadow/);
  f.duck(0.15); assert.equal(m.level, 0.15);
  f.unduck(); assert.equal(m.level, 1);
  const pb = []; f.on("playback", e => pb.push(e)); f.mediaPlayback("end", "video:psr");
  assert.equal(pb[0].kind, "crew"); assert.equal(pb[0].state, "end");
  m.paused = true; detach();
  assert.equal(f.holder, "none");
  assert.deepEqual(seen, ["crew", "none"]);
});

test("video step words", () => {
  assert.equal(UI.stepWord("watch it"), "watch");
  assert.equal(UI.stepWord("yes"), "watch");
  assert.equal(UI.stepWord("play"), "watch");
  assert.equal(UI.stepWord("skip"), "skip");
  assert.equal(UI.stepWord("no thanks"), "skip");
  assert.equal(UI.stepWord("the feather lands first"), null);
});

// a tiny element stub: the renderer only uses querySelector, textContent, classList, hidden, onclick, focus
function el() {
  const mk = () => ({ textContent: "", hidden: true, onclick: null, isConnected: true, classList: { add(c) { (this.c = this.c || []).push(c); } },
    focus() {}, querySelector(sel) { return sel === "[data-label]" ? (this.label = this.label || mk()) : null; } });
  const nodes = { "[data-watch]": mk(), "[data-skip]": mk(), "[data-note]": mk() };
  return { nodes, querySelector: s => nodes[s] };
}
const tick = () => new Promise(r => setTimeout(r, 0));

test("the lesson's video step: Watch opens the overlay, then sends what was watched; Skip continues", async () => {
  const opened = [];
  UI.deps.getVideo = async id => ({ id, duration_s: 48, credit: "NASA (Apollo 15), via NSSDCA" });
  UI.deps.isAvailable = async () => "cached";
  UI.deps.openVideo = async (id, o) => { opened.push([id, o.context]); return { watched: true, seconds: 47.5 }; };
  const sent = [], state = {};
  const r = R.video({ step: { type: "video", media: "hammer_feather" }, acc: { type: "video", media: "hammer_feather" }, answer: x => sent.push(x), state });
  assert.match(r.html, /data-watch/); assert.match(r.html, /Skip/);
  const e = el(); r.bind(e); await tick();
  assert.equal(e.nodes["[data-watch]"].label.textContent, "Watch (48 sec)");
  assert.equal(e.nodes["[data-note]"].textContent, "Video: NASA (Apollo 15), via NSSDCA");
  await e.nodes["[data-watch]"].onclick();
  assert.deepEqual(opened, [["hammer_feather", "lesson"]]);
  assert.deepEqual(sent, [{ video: { watched: true, seconds: 47.5 } }]);
  // skip (or the voice "skip" through ctx.state) never blocks the lesson
  state.video.skip();
  assert.deepEqual(sent[1], { video: { watched: false, seconds: 0, skipped: true } });
});

test("offline with nothing saved: the button says so, and Watch still continues (the overlay shows the card)", async () => {
  UI.deps.getVideo = async id => ({ id, duration_s: 113, credit: "NASA/Goddard" });
  UI.deps.isAvailable = async () => "offline";
  UI.deps.openVideo = async () => ({ watched: false, seconds: 0, offline: true });
  const sent = [];
  const r = R.video({ acc: { type: "video", media: "impact_flashes" }, answer: x => sent.push(x), state: {} });
  const e = el(); r.bind(e); await tick();
  assert.equal(e.nodes["[data-watch]"].label.textContent, "Needs internet");
  await e.nodes["[data-watch]"].onclick();
  assert.deepEqual(sent, [{ video: { watched: false, seconds: 0, offline: true } }]);
});

test("a locked (answered) step ignores its buttons", async () => {
  UI.deps.getVideo = async () => null; UI.deps.isAvailable = async () => "online";
  let opened = 0; UI.deps.openVideo = async () => { opened++; return { watched: false, seconds: 0 }; };
  const sent = [];
  const r = R.video({ acc: { type: "video", media: "psr" }, answer: x => sent.push(x), state: {}, locked: true });
  const e = el(); r.bind(e); await tick();
  await e.nodes["[data-watch]"].onclick(); e.nodes["[data-skip]"].onclick();
  assert.equal(opened, 0); assert.deepEqual(sent, []);
});
