// Gesture classifier: MediaPipe landmark frames in, gesture events out. Pure (no DOM, no camera), so the tests drive it
// with recorded or synthesised landmark sequences (frontend/tests/fixtures/gestures/*.json). docs/GESTURES.md.
//
// A frame (what engine.js builds from HandLandmarker + FaceDetector results):
//   { t: ms, aspect: width/height,
//     hands: [{ lm: [[x, y, z] × 21], side: "left" | "right", score }],
//     faces: [{ box: { x, y, w, h }, kp: [[x, y] × 6], score }] }
// Coordinates are normalised 0..1 in MIRROR space: the kid's own right is +x, as in the self-view. engine.js mirrors.
// FaceDetector keypoints: 0 right eye, 1 left eye, 2 nose tip, 3 mouth, 4 right ear, 5 left ear.
//
// Events (push() returns the events of that frame, in order):
//   palm_hold · thumbs_up · thumbs_down · swipe_left · swipe_right
//   point {x, y, progress} (cursor 0..1 in screen space, dwell progress 0..1) · point_end · select {x, y}
//   grab_start {x, y, stick} · grab_move {dx, dy, stick: {x, y, z}} · grab_end {how: "open" | "lost" | "other"}
//     stick: the fist as a joystick from where it grabbed (gesture/spin.js), calibrated, One-Euro filtered, -1.5..1.5
//     (x > 0 = the kid's right, y > 0 = down, z = twist). dx / dy: the palm's move since the last frame.
//   head {x, y, lean} (look -1..1, lean = face size / neutral) · lean_in {x, y} · lean_back
//   phase 2 (opts.phase2): zoom {factor} · zoom_end
//
// Robustness (docs/GESTURES.md §Robustness): only the largest (nearest) hand and face count; a hand must be stable for
// `stableFrames` frames before anything fires; finger states use hysteresis; every discrete gesture has a hold time,
// a cooldown and must be released before it fires again; swipes are one step each and the return stroke is ignored;
// after any discrete gesture no other one fires for crossCooldownMs; while the fist holds nothing else fires; the hand
// that opens out of a fist is never a stop or a swipe (afterGrabQuietMs). Every tuning number is in gesture/tuning.js.
import { DEFAULTS } from "./tuning.js";
import { fistReading, rawStick, calibrated, oneEuro } from "./spin.js";
export { DEFAULTS };

const WRIST = 0, THUMB = [1, 2, 3, 4], INDEX = [5, 6, 7, 8], MIDDLE = [9, 10, 11, 12], RING = [13, 14, 15, 16], PINKY = [17, 18, 19, 20];
const FINGERS = [INDEX, MIDDLE, RING, PINKY];


const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const len = v => Math.hypot(v[0], v[1]);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** Landmarks → aspect-corrected 2D points (x scaled by width/height so distances are isotropic). */
function pts(hand, aspect) {
  return hand.lm.map(p => (Array.isArray(p) ? [p[0] * aspect, p[1]] : [p.x * aspect, p.y]));
}
/** Hand length unit: wrist → middle knuckle. */
export const handScale = P => len(sub(P[MIDDLE[0]], P[WRIST]));

/**
 * One frame's static hand pose. `prev` (the last finger states) gives hysteresis.
 * Returns { pose, ext: [thumb, index, middle, ring, pinky], scale, palm: [x, y] (normalised, not aspect-corrected),
 *           thumbDir: "up" | "down" | "side", pinch }.
 */
export function handPose(hand, aspect = 4 / 3, prev = null, sens = 1) {
  const P = pts(hand, aspect), s = handScale(P) || 1e-6, W = P[WRIST];
  void sens;   // kept in the signature; pose geometry does not depend on sensitivity
  // finger: tip distance from the wrist over knuckle distance from the wrist. Straight ≈ 1.9, curled ≈ 1.0.
  const fingerExt = (f, i) => {
    const r = len(sub(P[f[3]], W)) / (len(sub(P[f[0]], W)) || 1e-6);
    const was = prev ? prev[i + 1] : false;
    return was ? r > 1.45 : r > 1.62;   // geometry is fixed; sensitivity changes times and distances only
  };
  const ext = [false, ...FINGERS.map(fingerExt)];
  // thumb: straight (base → tip ≈ the sum of its bones; a thumb wrapped round a fist bends) and long in the image
  const tPath = len(sub(P[THUMB[1]], P[THUMB[0]])) + len(sub(P[THUMB[2]], P[THUMB[1]])) + len(sub(P[THUMB[3]], P[THUMB[2]]));
  const tStraight = len(sub(P[THUMB[3]], P[THUMB[0]])) / (tPath || 1e-6), tLen = len(sub(P[THUMB[3]], P[THUMB[1]])) / s;
  ext[0] = prev && prev[0] ? tStraight > 0.78 && tLen > 0.38 : tStraight > 0.85 && tLen > 0.45;
  const tv = sub(P[THUMB[3]], P[THUMB[1]]), tl = len(tv) || 1e-6;
  const thumbDir = tv[1] < -0.6 * tl ? "up" : tv[1] > 0.6 * tl ? "down" : "side";
  const n4 = ext.slice(1).filter(Boolean).length;
  const up = P[MIDDLE[3]][1] < W[1] - 0.9 * s;    // fingers point up (y grows downwards)
  const spread = len(sub(P[INDEX[3]], P[PINKY[3]])) / s > 0.55;
  const pinch = len(sub(P[THUMB[3]], P[INDEX[3]])) / s < 0.3;
  let pose = "none";
  if (n4 === 4 && ext[0] && up && spread) pose = "palm";
  else if (n4 >= 3) pose = "open";
  else if (ext[1] && !ext[2] && !ext[3] && !ext[4]) pose = "point";
  else if (n4 === 0 && ext[0] && thumbDir === "up" && P[THUMB[3]][1] < Math.min(...FINGERS.map(f => P[f[1]][1]))) pose = "thumbs_up";
  else if (n4 === 0 && ext[0] && thumbDir === "down" && P[THUMB[3]][1] > Math.max(...FINGERS.map(f => P[f[1]][1]))) pose = "thumbs_down";
  else if (n4 === 0) pose = "fist";
  // palm centre: the mean of the wrist and the four knuckles, back in normalised image units
  const C = [WRIST, 5, 9, 13, 17].map(i => P[i]);
  const palm = [C.reduce((a, p) => a + p[0], 0) / 5 / aspect, C.reduce((a, p) => a + p[1], 0) / 5];
  return { pose, ext, scale: s, palm, thumbDir, pinch, tip: [P[INDEX[3]][0] / aspect, P[INDEX[3]][1]] };
}

/** The face that counts: the largest (nearest) one. Never identifies anyone: only box + six points. */
export function primaryFace(faces) {
  if (!faces || !faces.length) return null;
  return faces.reduce((a, f) => (f.box.w * f.box.h > a.box.w * a.box.h ? f : a));
}

export function createGestureClassifier(opts = {}) {
  let cfg = { ...DEFAULTS, ...opts };
  const S = {};
  function reset() {
    Object.assign(S, {
      seen: 0, lastSeenT: -1e9, side: null, ext: null, pose: "none", poseSince: 0, poseFrames: 0,
      hist: [],                         // [{t, x, y, s}] palm centre history (swipe, speed)
      palmFired: false, palmCool: -1e9, stillSince: 0,
      thumbFired: null, thumbCool: -1e9,
      swipeCool: -1e9, lastSwipe: null, lastSwipeT: -1e9,
      pointing: false, cursor: null, dwellAt: null, dwellT: 0, dwellLocked: false,
      grabbing: false, grabFrom: null, grabLostT: null, grabN: null, openFrames: 0, stick: null, quietUntil: -1e9, discreteT: -1e9,
      face: null, neutral: null, faceT: -1e9, look: [0, 0], leaning: false, leanT: null, leanedIn: false, backT: null,
      zoom0: null,
    });
  }
  // One Euro filters: the point cursor (x, y) and the fist stick (x, y, z)
  const F = {};
  const mkFilters = () => {
    F.px = oneEuro(cfg.pointFilter); F.py = oneEuro(cfg.pointFilter);
    F.sx = oneEuro(cfg.fistFilter); F.sy = oneEuro(cfg.fistFilter); F.sz = oneEuro(cfg.fistFilter);
  };
  mkFilters();
  reset();
  /** Discrete gestures share one short cooldown, so one movement never fires two different things. */
  const canFire = t => t - S.discreteT >= cfg.crossCooldownMs;
  const fired = t => { S.discreteT = t; };

  const k = () => clamp(cfg.sensitivity, 0.6, 1.4);
  const holdMul = () => 1 / Math.sqrt(k());

  /** Pick the hand that counts: the largest; the preferred hand wins a near tie. Hands much smaller are other people. */
  function pickHand(hands, aspect) {
    const ok = (hands || []).filter(h => (h.score ?? 1) >= cfg.minHandScore && h.lm && h.lm.length === 21)
      .map(h => ({ h, s: handScale(pts(h, aspect)) })).filter(x => x.s >= cfg.minHandScale);
    if (!ok.length) return { primary: null, all: [] };
    ok.sort((a, b) => b.s - a.s);
    let primary = ok[0];
    if (ok[1] && ok[1].s > ok[0].s * 0.85 && ok[1].h.side === cfg.handed && ok[0].h.side !== cfg.handed) primary = ok[1];
    // a second hand only counts (phase-2 two-hand zoom) when it is about as near as the first
    const all = ok.filter(x => x.s >= primary.s * 0.6).map(x => x.h);
    return { primary: primary.h, all };
  }

  function push(frame) {
    const out = [], t = frame.t, aspect = frame.aspect || 4 / 3;
    const emit = (type, extra) => out.push({ type, t, ...(extra || {}) });
    const { primary, all } = pickHand(frame.hands, aspect);

    // ---------- head (the cabin's look-around and lean) ----------
    if (cfg.headLook) headStep(frame, emit);

    // ---------- hand ----------
    if (!primary) {
      if (t - S.lastSeenT > cfg.lostMs) endHand(emit);
      S.seen = 0;
      return out;
    }
    if (S.side && primary.side && primary.side !== S.side) { endHand(emit); S.seen = 0; S.ext = null; S.hist = []; }
    S.side = primary.side || S.side;
    S.seen++; S.lastSeenT = t;
    const hp = handPose(primary, aspect, S.ext, cfg.sensitivity);
    S.ext = hp.ext;
    if (hp.pose !== S.pose) { S.pose = hp.pose; S.poseSince = t; S.poseFrames = 1; } else S.poseFrames++;
    S.hist.push({ t, x: hp.palm[0], y: hp.palm[1], s: hp.scale, pose: hp.pose });
    while (S.hist.length && t - S.hist[0].t > Math.max(cfg.swipeWindowMs, 300)) S.hist.shift();
    if (speed() > cfg.palmMaxSpeed * k() || S.seen === 1) S.stillSince = t;
    if (S.seen < cfg.stableFrames) return out;     // not stable yet: nothing acts
    const held = t - S.poseSince, stable = S.poseFrames >= 2;

    // release re-arms the one-shot gestures
    if (S.pose !== "palm") S.palmFired = false;
    if (S.pose !== "thumbs_up" && S.pose !== "thumbs_down") S.thumbFired = null;

    // the fist grab first: while it holds, nothing else can fire (a thumb popping out is not a yes)
    grabStep(hp, primary, aspect, t, held, emit);
    if (S.grabbing) return out;

    // swipe: an open hand moving fast sideways. Checked next: a moving palm must never count as a held palm.
    const sw = swipeStep(t, emit);
    if (sw) return out;

    // open palm held still → stop
    if (S.pose === "palm" && stable && !S.palmFired && t >= S.palmCool && t >= S.quietUntil && canFire(t) && Math.min(held, t - S.stillSince) >= cfg.palmHoldMs * holdMul()) {
      S.palmFired = true; S.palmCool = t + cfg.palmCooldownMs; fired(t); emit("palm_hold");
    }

    // thumbs up / down → yes / no
    if ((S.pose === "thumbs_up" || S.pose === "thumbs_down") && stable && S.thumbFired !== S.pose && t >= S.thumbCool && canFire(t) && held >= cfg.thumbHoldMs * holdMul()) {
      S.thumbFired = S.pose; S.thumbCool = t + cfg.thumbCooldownMs; fired(t); emit(S.pose);
    }

    // point + dwell → cursor + select
    pointStep(hp, t, stable, emit);
    // phase 2: both hands pinching → zoom
    if (cfg.phase2) zoomStep(all, aspect, emit);
    return out;
  }

  function speed() {
    const h = S.hist; if (h.length < 2) return 0;
    const a = h[Math.max(0, h.length - 4)], b = h[h.length - 1], dt = (b.t - a.t) / 1000 || 1e-3;
    return Math.hypot(b.x - a.x, b.y - a.y) / (b.s || 1e-3) / dt;
  }

  function swipeStep(t, emit) {
    if (t < S.swipeCool || t < S.quietUntil) return false;
    const h = S.hist.filter(p => t - p.t <= cfg.swipeWindowMs);
    if (h.length < 3) return false;
    // most of the window with an open hand (a swipe is made with a flat hand)
    if (h.filter(p => p.pose === "open" || p.pose === "palm").length < h.length * 0.6) return false;
    const a = h[0], b = h[h.length - 1], dx = b.x - a.x, dy = b.y - a.y;
    let path = 0; for (let i = 1; i < h.length; i++) path += Math.hypot(h[i].x - h[i - 1].x, h[i].y - h[i - 1].y);
    const sMean = h.reduce((q, p) => q + p.s, 0) / h.length;
    const minDx = Math.max(cfg.swipeMinDx, cfg.swipeMinScales * sMean) / k();
    if (Math.abs(dx) < minDx || Math.abs(dx) < 2 * Math.abs(dy) || Math.abs(dx) < 0.75 * path) return false;
    const dir = dx < 0 ? "left" : "right";
    S.hist = []; S.swipeCool = t + cfg.swipeCooldownMs;
    S.palmFired = true; S.palmCool = t + cfg.palmCooldownMs;   // the swipe's end pose is not a "stop"
    // the return stroke (hand coming back the other way) is not a swipe
    if (S.lastSwipe && S.lastSwipe !== dir && t - S.lastSwipeT < cfg.swipeReturnMs) { S.lastSwipeT = t; return true; }
    S.lastSwipe = dir; S.lastSwipeT = t;
    if (!canFire(t)) return true;
    fired(t); emit("swipe_" + dir);
    return true;
  }

  function mapCursor(tip) {
    const [x0, y0, x1, y1] = cfg.pointBox;
    return [clamp((tip[0] - x0) / (x1 - x0), 0, 1), clamp((tip[1] - y0) / (y1 - y0), 0, 1)];
  }
  function pointStep(hp, t, stable, emit) {
    if (S.pose !== "point" || !stable) { if (S.pointing && S.pose !== "point") endPoint(emit); return; }
    const raw = mapCursor(hp.tip);
    if (!S.pointing) { F.px.reset(); F.py.reset(); }
    S.cursor = [clamp(F.px(raw[0], t / 1000), 0, 1), clamp(F.py(raw[1], t / 1000), 0, 1)];
    S.pointing = true;
    const c = S.cursor;
    if (!S.dwellAt || Math.hypot(c[0] - S.dwellAt[0], c[1] - S.dwellAt[1]) > (S.dwellLocked ? cfg.dwellRearm : cfg.dwellRadius * Math.sqrt(k()))) {
      S.dwellAt = c.slice(); S.dwellT = t; S.dwellLocked = false;
    }
    const need = cfg.dwellMs * holdMul();
    const progress = S.dwellLocked ? 0 : clamp((t - S.dwellT) / need, 0, 1);
    emit("point", { x: c[0], y: c[1], progress });
    if (!S.dwellLocked && progress >= 1 && canFire(t)) { S.dwellLocked = true; fired(t); emit("select", { x: S.dwellAt[0], y: S.dwellAt[1] }); }
  }
  function endPoint(emit) { if (!S.pointing) return; S.pointing = false; S.cursor = null; S.dwellAt = null; S.dwellLocked = false; emit("point_end"); }

  // The fist: a joystick with hysteresis. It grabs after a fist held grabHoldMs (and grabEnterFrames frames) and sets
  // the neutral pose there; it stays grabbed while the hand stays fist-like (at most one finger out: a flickering
  // finger or a thumb popping out never lets go); it releases on an open hand for grabReleaseFrames frames in a row,
  // on anything else for grabReleaseMs, or when the hand is gone for lostMs.
  function grabStep(hp, hand, aspect, t, held, emit) {
    const n4 = hp.ext.slice(1).filter(Boolean).length;
    if (!S.grabbing) {
      if (S.pose === "fist" && held >= cfg.grabHoldMs && S.poseFrames >= cfg.grabEnterFrames) {
        if (S.pointing) endPoint(emit);
        S.grabbing = true; S.grabN = fistReading(hand, aspect); S.grabFrom = hp.palm.slice(); S.openFrames = 0; S.grabLostT = null;
        F.sx.reset(); F.sy.reset(); F.sz.reset(); S.stick = { x: 0, y: 0, z: 0 };
        emit("grab_start", { x: hp.palm[0], y: hp.palm[1], stick: { ...S.stick } });
      }
      return;
    }
    if (n4 >= 3) {   // an open hand: release after a few frames (one stray frame is not a release)
      if (++S.openFrames >= cfg.grabReleaseFrames) endGrab(emit, t, "open");
      return;
    }
    S.openFrames = 0;
    if (n4 >= 2) {   // neither fist nor open: hold the last stick a moment, then let go
      if (S.grabLostT == null) S.grabLostT = t;
      if (t - S.grabLostT >= cfg.grabReleaseMs) endGrab(emit, t, "other");
      return;
    }
    S.grabLostT = null;
    const cal = cfg.spinCal, raw = rawStick(fistReading(hand, aspect), S.grabN, cfg, cal ? cal.pitchSign : 1), c = calibrated(raw, cal), ts = t / 1000;
    S.stick = { x: F.sx(c.x, ts), y: F.sy(c.y, ts), z: F.sz(c.z, ts) };
    const dx = hp.palm[0] - S.grabFrom[0], dy = hp.palm[1] - S.grabFrom[1];
    S.grabFrom = hp.palm.slice();
    emit("grab_move", { dx, dy, stick: { ...S.stick } });
  }
  function endGrab(emit, t, how = "lost") {
    if (!S.grabbing) return;
    S.grabbing = false; S.grabFrom = null; S.grabLostT = null; S.grabN = null; S.stick = null; S.openFrames = 0;
    // the hand that opens out of a fist is a release, never a stop or a swipe
    S.palmFired = true; if (t != null) S.quietUntil = t + cfg.afterGrabQuietMs;
    emit("grab_end", { how });
  }

  function endHand(emit) { endPoint(emit); endGrab(emit, S.lastSeenT, "lost"); if (S.zoom0) { S.zoom0 = null; emit("zoom_end"); } S.pose = "none"; S.hist = []; S.side = null; S.palmFired = false; S.thumbFired = null; }

  function zoomStep(all, aspect, emit) {
    if (all.length < 2) { if (S.zoom0) { S.zoom0 = null; emit("zoom_end"); } return; }
    const [a, b] = all.slice(0, 2).map(h => handPose(h, aspect, null, cfg.sensitivity));
    if (!(a.pinch && b.pinch)) { if (S.zoom0) { S.zoom0 = null; emit("zoom_end"); } return; }
    const d = Math.hypot(a.tip[0] - b.tip[0], a.tip[1] - b.tip[1]);
    if (!S.zoom0) { S.zoom0 = d; return; }
    const f = d / S.zoom0;
    if (Math.abs(f - 1) > 0.03) { S.zoom0 = d; emit("zoom", { factor: f }); }
  }

  // ---------- head pose from the face detector's six points ----------
  function headStep(frame, emit) {
    const f = primaryFace(frame.faces);
    S.face = f;
    if (!f || (f.score ?? 1) < cfg.minFaceScore || !f.kp || f.kp.length < 3) return;
    const t = frame.t, eyeR = f.kp[0], eyeL = f.kp[1], nose = f.kp[2];
    const eyeMid = [(eyeR[0] + eyeL[0]) / 2, (eyeR[1] + eyeL[1]) / 2], eyeD = Math.hypot(eyeL[0] - eyeR[0], eyeL[1] - eyeR[1]) || 1e-3;
    const yaw = (nose[0] - eyeMid[0]) / eyeD;                       // ≈ 0 facing the screen, ± when turning
    const cx = f.box.x + f.box.w / 2, cy = f.box.y + f.box.h / 2;
    // a face back after 2 s away (or someone new in the seat) re-anchors the neutral pose instead of reading as a lean
    if (S.neutral && Math.abs(t - S.faceT) > 2000) { S.neutral = null; S.leaning = false; S.leanedIn = false; S.leanT = S.backT = null; }
    S.faceT = t;
    if (!S.neutral) S.neutral = { x: cx, y: cy, w: f.box.w, yaw };
    const N = S.neutral, lean = f.box.w / (N.w || 1e-3);
    // look: head position (parallax) plus a share of the turn, dead zone in the middle
    const rawX = (cx - N.x) / 0.18 + (yaw - N.yaw) * 1.6, rawY = (cy - N.y) / 0.16;
    const dz = v => (Math.abs(v) < cfg.lookDead ? 0 : (v - Math.sign(v) * cfg.lookDead) / (1 - cfg.lookDead));
    const look = [clamp(dz(rawX), -1, 1), clamp(dz(rawY), -1, 1)];
    if (Math.abs(look[0] - S.look[0]) + Math.abs(look[1] - S.look[1]) > 0.01) { S.look = look; emit("head", { x: look[0], y: look[1], lean }); }
    // lean in (held) → open the looked-at panel; lean back to neutral (held) → back to the seat
    const inT = cfg.leanIn / Math.sqrt(k()), exitT = cfg.leanInExit;
    if (!S.leaning && lean > inT) { if (S.leanT == null) S.leanT = t; if (t - S.leanT >= cfg.leanHoldMs * holdMul()) { S.leaning = true; S.leanedIn = true; S.backT = null; emit("lean_in", { x: look[0], y: look[1] }); } }
    else if (!S.leaning) S.leanT = null;
    if (S.leaning && lean < exitT) { S.leaning = false; S.leanT = null; }
    if (S.leanedIn && !S.leaning && lean < cfg.leanBack) {
      if (S.backT == null) S.backT = t;
      if (t - S.backT >= cfg.leanBackHoldMs * holdMul()) { S.leanedIn = false; S.backT = null; emit("lean_back"); }
    } else if (S.leanedIn) S.backT = null;
    // the neutral pose follows slow posture drift (never while leaning)
    if (!S.leaning && !S.leanedIn) { const a = 0.01; N.x += (cx - N.x) * a; N.y += (cy - N.y) * a; N.w += (f.box.w - N.w) * a; N.yaw += (yaw - N.yaw) * a; }
  }

  return {
    push, reset,
    configure(o) { cfg = { ...cfg, ...o }; if ("pointFilter" in o || "fistFilter" in o) mkFilters(); },
    /** Calibration: the current face is the neutral pose (Settings → "Show me your hand"). */
    setNeutral(face) { const f = face || S.face; if (f) { const kp = f.kp; const eyeMid = [(kp[0][0] + kp[1][0]) / 2, (kp[0][1] + kp[1][1]) / 2]; const eyeD = Math.hypot(kp[1][0] - kp[0][0], kp[1][1] - kp[0][1]) || 1e-3; S.neutral = { x: f.box.x + f.box.w / 2, y: f.box.y + f.box.h / 2, w: f.box.w, yaw: (kp[2][0] - eyeMid[0]) / eyeD }; } },
    get config() { return { ...cfg }; },
    get pose() { return S.pose; },
    get state() { return { pose: S.pose, pointing: S.pointing, grabbing: S.grabbing, stick: S.stick ? { ...S.stick } : null, leaning: S.leanedIn, look: S.look.slice(), handSeen: S.seen }; },
  };
}
