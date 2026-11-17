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
  const r = R.video({ acc: { type: "video", media: "south_pole_shadows" }, answer: x => sent.push(x), state: {} });
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

test("[vidfix] no click handler's closest() can match a state attribute on <body> / <html>", async () => {
  // The owner's stuck screen: main.js marks body[data-video] while a video is up; a11y.js's Help handler did
  // e.target.closest("[data-video]"), so a click anywhere in Settings matched <body> and wrote "Needs internet…" over
  // the whole app. Guard the class: every body/html dataset key the app writes must never be a closest() target.
  const fs = await import("node:fs"), path = await import("node:path");
  const root = new URL("../src/", import.meta.url).pathname, files = [];
  const walk = d => { for (const f of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, f.name); if (f.isDirectory()) walk(p); else if (p.endsWith(".js")) files.push(p); } };
  walk(root);
  const src = files.map(f => [f, fs.readFileSync(f, "utf8")]);
  const kebab = k => k.replace(/[A-Z]/g, c => "-" + c.toLowerCase());
  const keys = new Set();
  for (const [, s] of src) for (const m of s.matchAll(/(?:body|documentElement)\.dataset\.([a-zA-Z]+)\s*=/g)) keys.add(kebab(m[1]));
  assert.ok(keys.has("video") && keys.has("mode"), [...keys].join(","));
  for (const [f, s] of src) for (const m of s.matchAll(/closest\(\s*["'`]([^"'`]*)["'`]/g)) {
    for (const k of keys) assert.ok(!new RegExp(`(^|[\\s,>~+])\\[data-${k}(?=[\\]=~|^$*])`).test(m[1]), `${path.basename(f)}: closest("${m[1]}") can match <body data-${k}>`);
  }
});

test("[vidfix] the overlay: thumbs down closes it; a failed player is not called offline when we are online", async () => {
  assert.equal(C.INTENT_CMD.no, "stop");
  assert.equal(C.INTENT_CMD.stop, "stop");
  assert.notEqual(C.NO_PLAY_LINE, C.OFFLINE_LINE);
  assert.doesNotMatch(C.NO_PLAY_LINE, /internet/i);
});

function fakeTimers() {
  let now = 0, id = 0; const q = new Map();
  return { setTimeout: (f, ms) => { q.set(++id, [now + ms, f]); return id; }, clearTimeout: k => q.delete(k),
    advance(ms) { now += ms; for (const [k, [at, f]] of [...q]) if (at <= now) { q.delete(k); f(); } } };
}

test("[video fix 0.3.11] YouTube watchdog: an embed that takes Play but never plays (the bot card) is caught once", () => {
  const T = fakeTimers(); let stalls = 0;
  const w = C.stallWatch(() => stalls++, { ms: 12000, timers: T });
  w.play(); T.advance(11000); assert.equal(stalls, 0);
  w.state(3); T.advance(2000); assert.equal(stalls, 1, "buffering forever counts as stuck");
  w.play(); T.advance(20000); assert.equal(stalls, 1, "fires once");
});

test("[video fix 0.3.11] YouTube watchdog: playing, or the kid pausing, never trips it", () => {
  const T = fakeTimers(); let stalls = 0;
  const w = C.stallWatch(() => stalls++, { ms: 12000, timers: T });
  w.play(); T.advance(5000); w.state(1); T.advance(60000); assert.equal(stalls, 0);
  w.play(); T.advance(60000); assert.equal(stalls, 0, "once it has played, the watch is over");
  const p = C.stallWatch(() => stalls++, { ms: 12000, timers: T });
  p.play(); T.advance(3000); p.state(2); T.advance(60000); assert.equal(stalls, 0, "paused before it played: disarmed");
  p.play(); T.advance(12000); assert.equal(stalls, 1, "the next Play re-arms it");
  const d = C.stallWatch(() => stalls++, { ms: 12000, timers: T });
  d.play(); d.dispose(); T.advance(60000); assert.equal(stalls, 1, "closed: never fires");
});

test("[video fix 0.3.11] the overlay wires the watchdog, offers the NASA fallback on 'won't play here', retries a file once", async () => {
  const fs = await import("node:fs");
  const s = fs.readFileSync(new URL("../src/media/video.js", import.meta.url), "utf8");
  assert.match(s, /stallWatch\(/);
  assert.match(s, /if \(func === "playVideo"\) watch\.play\(\)/, "every play request arms the watchdog");
  assert.match(s, /watch\.state\(s\)/);
  assert.match(s, /kind !== "offline" \|\| fbCached/, "online: a fallback that streams is offered; offline only a saved one");
  assert.match(s, /retried = true/);
});

test("[videos offline] 'Watch on YouTube': the plain watch page, only for a real video id", () => {
  assert.equal(C.youtubeWatchUrl("osdOQhRhVJg"), "https://www.youtube.com/watch?v=osdOQhRhVJg");
  for (const bad of ["", null, undefined, "short", "osdOQhRhVJg&x=1", "javascript:x", "../../etc/pass"]) assert.equal(C.youtubeWatchUrl(bad), null, String(bad));
  assert.equal(C.WATCH_ON_YOUTUBE, "Watch on YouTube");
});

test("[videos offline] the won't-play card offers YouTube only without a NASA fallback, through the browser (the gate)", async () => {
  const fs = await import("node:fs");
  const s = fs.readFileSync(new URL("../src/media/video.js", import.meta.url), "utf8");
  // only on "won't play here" (online), only for a YouTube entry, never when a NASA file is offered instead
  assert.match(s, /const yt = !fb && kind === "error" && item\.source === "youtube" \? youtubeWatchUrl\(item\.youtube_id\) : null;/);
  // a new window: the desktop's setWindowOpenHandler sends youtube.com through the grown-up gate (desktop/main/gate.js)
  assert.match(s, /window\.open\(yt, "_blank", "noopener"\)/);
  assert.doesNotMatch(s, /location\.href\s*=\s*yt/, "never navigates the app window to YouTube");
});

test("[videos offline] a stale <dialog> close event (the last video's) never closes the next video", async () => {
  const fs = await import("node:fs");
  const s = fs.readFileSync(new URL("../src/media/video.js", import.meta.url), "utf8");
  assert.match(s, /const onClose = \(\) => \{ if \(!dlg\.open\) finish\("closed"\); \};/);
});

test("[videos offline] About → Videos credits: YouTube marked, a third-party pack file always says 'used with permission'", () => {
  assert.equal(UI.creditLine({ credit: "NASA/Goddard", source: "nasa_file" }), "NASA/Goddard");
  assert.equal(UI.creditLine({ credit: "I Play With My Kids · not from NASA", source: "youtube", nasa: false }), "I Play With My Kids · not from NASA · YouTube");
  assert.equal(UI.creditLine({ credit: "Astronomy in Action · used with permission", source: "pack_file", nasa: false }), "Astronomy in Action · used with permission");
  assert.equal(UI.creditLine({ credit: "Astronomy in Action", source: "pack_file", nasa: false }), "Astronomy in Action · used with permission");
  assert.equal(UI.creditLine({ credit: "NASA/JPL-Caltech (JPL Education)", source: "pack_file" }), "NASA/JPL-Caltech (JPL Education)");
});

test("[video fix 0.3.11] a lesson with a Try-at-home task shows its Watch how videos at the start (Oreo, 0.3.10 lost it)", async () => {
  const fs = await import("node:fs");
  const s = fs.readFileSync(new URL("../src/academy/ui.js", import.meta.url), "utf8");
  assert.match(s, /const prepAtStart = firstLook && !!\(L\.prep && !L\.ride\)/);
  assert.match(s, /prepAtStart \? `<div class="a-prep-videos a-prep-start" id="aPrepVideos"/);
  assert.match(s, /if \(prepAtStart\) fillPrepVideos\(L\.prep, \{ where: "lesson" \}\)/);
  // still never a gate: the prep card opens only when asked for
  assert.match(s, /if \(L\.prep && !L\.ride && prep\) \{ showPrep\(\); return; \}/);
});
