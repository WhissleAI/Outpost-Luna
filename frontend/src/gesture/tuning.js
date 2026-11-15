// Every gesture tuning constant in one place (docs/GESTURES.md §Tuning). Change numbers here, nowhere else.
// Tuned on synthetic landmarks at 30 fps with jitter, not yet on a panel of real kids' hands at a real webcam: the
// values marked [webcam] are the ones a human with a camera should tune first.

/** The classifier (gesture/classifier.js): poses, holds, cooldowns, swipes, the point cursor, the fist grab, the head. */
export const DEFAULTS = Object.freeze({
  sensitivity: 1,        // 0.6 strict … 1.4 loose (Settings slider)
  handed: "right",       // tie-break when two hands are the same size
  headLook: true,
  phase2: false,         // two-hand zoom (flagged)
  stableFrames: 3,       // a hand must be seen this many frames in a row before it can act
  minHandScore: 0.6,     // below this the hand is not "confidently present" and nothing acts
  minFaceScore: 0.6,     // the same for the face (head look, lean)
  minHandScale: 0.045,   // wrist→middle-knuckle length (normalised); smaller = too far away / someone behind
  palmHoldMs: 500, palmCooldownMs: 1000, palmMaxSpeed: 1.6,    // speed in hand-lengths per second
  thumbHoldMs: 350, thumbCooldownMs: 1200,
  // show N fingers → pick option N (1–4): the same count for fingersFrames frames, held (and the hand still) this long [webcam]
  fingersHoldMs: 500, fingersFrames: 6, fingersCooldownMs: 1000,
  swipeWindowMs: 450, swipeMinDx: 0.2, swipeMinScales: 1.6, swipeCooldownMs: 700, swipeReturnMs: 1200,
  dwellMs: 800, dwellRadius: 0.035, dwellRearm: 0.07,
  pointFilter: { minCutoff: 1.4, beta: 6, dCutoff: 1 },   // One Euro on the cursor: steady when still, quick when moving [webcam]
  pointBox: [0.18, 0.15, 0.82, 0.75],   // the part of the camera image that maps to the whole screen (x0, y0, x1, y1)
  crossCooldownMs: 350,  // after any discrete gesture (stop, yes, no, swipe, select) no OTHER discrete one for this long
  lostMs: 250,           // a hand missing this long ends point / grab
  leanIn: 1.22, leanInExit: 1.12, leanBack: 1.06, leanHoldMs: 400, leanBackHoldMs: 500,
  lookDead: 0.08,
  // ---- the fist grab (spin the Moon / look around the cabin): hysteresis so it never flickers ----
  grabHoldMs: 250,       // a fist held this long (and grabEnterFrames frames) grabs [webcam]
  grabEnterFrames: 4,
  grabReleaseFrames: 3,  // an open hand (3+ fingers out) for this many frames in a row releases
  grabReleaseMs: 300,    // anything else that is not fist-like (2+ fingers out) for this long also releases
  afterGrabQuietMs: 700, // after a release the opening hand never counts as "stop" or a swipe for this long
  // the fist as a joystick: raw offsets that count as "full" before calibration [webcam]
  fistPosRange: 1.0,     // hand-lengths of movement from where the fist grabbed
  fistRollRange: 0.45,   // radians of lean left / right (wrist → middle-knuckle angle in the image), ≈ 26°
  fistPitchRange: 0.5,   // radians of tilt toward / away from the screen (MediaPipe z), ≈ 29°
  fistTwistRange: 0.6,   // radians of twist (doorknob) about the forearm
  fistTiltWeight: 1,     // how much the fist's tilt adds to its position (0 = position only)
  fistFilter: { minCutoff: 1.0, beta: 0.8, dCutoff: 1 },   // One Euro on the stick [webcam]
  spinCal: null,         // the kid's calibration (gesture/calibration.js); null = the defaults above
});

/** Fist-spin rate control (gesture/spin.js): stick → angular speed of the Moon. */
export const SPIN = Object.freeze({
  dead: 0.15,            // radial dead zone of the stick (0..1): small wobbles never spin [webcam]
  expo: 1.6,             // gain curve: speed ∝ ((|stick| − dead) / (1 − dead)) ^ expo, fine near the middle
  maxSpeed: 1.4,         // rad/s at full stick and the default distance (≈ 80°/s: half the Moon in ~2 s) [webcam]
  easeTau: 0.12,         // s: the speed eases toward the target with this time constant
  maxAccel: 5,           // rad/s²: never faster than this (no jolt when the fist jumps)
  releaseCarry: 0.5,     // share of the speed kept when the hand opens (the momentum)
  decayTau: 0.35,        // s: the momentum decays with this time constant
  stopBelow: 0.02,       // rad/s: below this the Moon stops
  refDistance: 3.6,      // camera distance at which maxSpeed applies; closer = slower, so zoomed in stays steerable
  minDistScale: 0.25, maxDistScale: 1.5,
  // twist (doorknob) zooms; pinch (phase 2) and +/- keys zoom too
  twistZoom: true,
  twistDead: 0.35,       // a bigger dead zone than the stick: a twist must be meant [webcam]
  zoomRate: 0.7,         // ln(zoom factor) per second at full twist (≈ 2× a second)
  invert: false,         // false: the surface moves the way the fist moves (like pushing the globe); Settings can flip it
});

/** The first-time fist calibration (gesture/calibration.js). */
export const CALIBRATION = Object.freeze({
  version: 1,
  minRange: 0.35,        // a calibrated direction never needs less than 35 % of the default offset (no hair trigger)
  maxRange: 2.2,         // nor more than 2.2× (a kid who barely moved still reaches full speed, but not with a twitch)
  comfort: 0.85,         // full speed at 85 % of the kid's biggest comfortable tilt
  minMove: 0.3,          // a step counts once the stick moved this far that way (30 % of the default full offset),
                         // so drifting back to the middle after the last step never counts as this one
  stepHoldMs: 450,       // … and held there this long
  stepMaxMs: 3500,       // a step that never gets there keeps the default for that direction
  fistHoldMs: 400,       // "Make a fist. Keep it still.": held this long, moving under fistStill hand-lengths
  fistStill: 0.15,
});
