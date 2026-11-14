// Outpost Luna: the story, in ONE file. Every line of story copy (beats, CAPCOM lines that use the call sign, lesson
// callbacks during the Mission, debrief copy, spoken offers) lives here so it is easy to edit. No logic beyond tiny
// templating. Voice, tone and word budgets: docs/COPY.md. Tests: backend/tests/test_copy.py (no emoji, spoken <= 20 words).
//
// Framing (keep it true): Artemis II flew its crew around the Moon in April 2026. Artemis III, the first landing near
// the south pole, has NOT happened yet. The kid trains at Flight School to help run Outpost Luna, a south-pole base for
// the crews who will come after.

export const CREDIT = "Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA.";

/** Three short sentences. mission/ui.js shows everything after the first ". " as a sub line. */
export const FRAMING = "Artemis II flew around the Moon in April 2026. Artemis III hasn't landed yet. Train now for the crews who will.";

/** The four beats of the one story, shown on the Academy map and in About. */
export const BEATS = [
  { id: "school", title: "Flight School", text: "Learn the Moon with CAPCOM." },
  { id: "ride", title: "Check ride", text: "Fly your first solo shift." },
  { id: "mission", title: "Command", text: "Run Outpost Luna for 10 days." },
  { id: "debrief", title: "Debrief", text: "See what you learned." },
];

// ---------- call sign (stored on this device only; never sent to the server) ----------
/** Playful, non-identifying call signs. Only these are ever SPOKEN aloud (a typed one is shown, not spoken). */
export const CALLSIGNS = ["Comet", "Nova", "Rocket", "Orbit", "Moon Moth", "Crater Cat", "Star Hopper", "Sky Otter", "Pulsar", "Moonbeam", "Rover Fox", "Stardust"];
const CS_KEY = "outpost-callsign";
export const callSign = {
  get() { try { return (localStorage.getItem(CS_KEY) || "").slice(0, 18); } catch (e) { return ""; } },
  set(v) { const s = String(v || "").replace(/[^\p{L}\p{N} '-]/gu, "").trim().slice(0, 18); try { localStorage.setItem(CS_KEY, s); } catch (e) { /* private mode */ } dispatchEvent(new CustomEvent("outpost:callsign", { detail: s })); return s; },
  /** What to show: the call sign, or "Cadet". */
  shown() { return this.get() || "Cadet"; },
  /** What CAPCOM may SAY aloud: only a preset call sign (a typed one might be a real name, so it stays on screen). */
  spoken(fallback = "Commander") { const s = this.get(); return CALLSIGNS.includes(s) ? s : fallback; },
};
export const CALLSIGN_COPY = {
  title: "Pick your call sign",
  sub: "Your radio name. It stays on this device.",
  type: "Or make one up",
  save: "Use it",
  random: "Pick for me",
  edit: "Change call sign",
  /** Spoken once when the picker opens. */
  say: "Every crew member has a radio name. Pick yours.",
};

// ---------- Academy (Flight School): a course catalog in tracks ----------
/** Tracks group course.json lesson ids. A lesson id not listed here (e.g. a new vocabulary lesson) joins Foundations. */
export const TRACKS = [
  { id: "foundations", title: "Foundations", lessons: ["moon", "comms", "vocab", "words"] },
  { id: "systems", title: "Outpost systems", lessons: ["power", "radiation", "life"] },
  { id: "field", title: "Field skills", lessons: ["rover", "history"] },
  { id: "qual", title: "Qualification", lessons: ["checkride"] },
];
/** One line per lesson for its catalog card (keyed by course.json id). 12 words or fewer. */
export const LESSON_BLURB = {
  moon: "Near side, far side, and Shackleton crater at the pole.",
  comms: "Copy, roger, say again. Talk like the Artemis II crew.",
  power: "Sunlight, batteries, and Malapert's long polar night.",
  radiation: "Measure radiation. Ride out the real May 2024 storm.",
  life: "Air, water, and the ice LCROSS found.",
  history: "What Apollo left behind for the next crews.",
  words: "Albedo, regolith, terminator: words the crew really used.",
  checkride: "Two days at Shackleton Rim. Your first solo shift.",
};
export const WHY_TITLE = "Why this matters";
export const WHY = "Artemis crews will land near the south pole. Train on NASA data.";
export const MENTOR = {
  role: "Your mentor",
  first: cs => `Welcome, ${cs}. Let's start with the Moon itself.`,
  more: (cs, n, next) => `${n} patch${n === 1 ? "" : "es"} earned, ${cs}. Next: ${next}.`,
  ride: cs => `Every lesson done, ${cs}. Time for your check ride.`,
  done: cs => `You're qualified, Commander ${cs}. Outpost Luna is yours.`,
  voice: "Or hold Space and say “next”.",
};
export const SCHOOL = {
  eyebrow: "Flight School",
  hero: "Artemis III hasn't landed yet.",
  hero2: "Train for the crew that will.",
  title: c => `Welcome, ${c}`,
  titleDone: c => `Qualified, Commander ${c}`,
  sub: "Earn a patch for each lesson. Then take command.",
  subDone: "Replay a lesson, or take command.",
  start: "Start lesson",
  continue: "Continue",
  ride: "Fly check ride",
  go: "Take command",
  next: "Next up",
  solo: "Solo shift",
  shelf: "Your patches",
  notYet: "Not earned yet",
  progress: (n, total) => `${n} of ${total} patches`,
  minutes: m => `${m} min`,
  track: (k, title) => `Track ${k} · ${title}`,
  earned: name => `${name} patch`,
};

/** One short story beat per lesson (shown above CAPCOM's brief, and spoken before it). Keyed by course.json lesson id.
 *  Patches are drawn by the art set (no emoji here). */
export const LESSON_STORY = {
  moon: { beat: "Day one. CAPCOM pulls up a map of the Moon." },
  comms: { beat: "Radio check. Houston is 384,000 km away." },
  power: { beat: "The outpost runs on sunlight." },
  radiation: { beat: "Storm drill. The Sun can throw storms at the Moon." },
  life: { beat: "No air, no rivers. But is there ice?" },
  history: { beat: "Every crew learns from the crews before." },
  words: { beat: "A new world needs new words." },
  checkride: { beat: "Solo shift. CAPCOM is only watching." },
};

/** CAPCOM's lines that use the call sign (the spoken form is passed in, so a typed name is never read aloud). */
export const CAPCOM = {
  lessonHello: (cs, beat) => `${beat} Ready, ${cs}?`,
  patch: (cs, name) => `Patch earned: ${name}. Nice work, ${cs}.`,
  qualified: (cs, name) => `${name} patch earned. You're qualified, Commander ${cs}.`,
  missionBrief: cs => `Pick a site, Commander ${cs}. Keep the crew safe for ten days.`,
  missionStart: (cs, site) => `Outpost Luna is online at ${site}. Day one, ${cs}.`,
  houstonCalling: "Calling Houston…",
};

/** Spoken offers: said once, as a question. "yes" / "next" takes them (the router's accept_offer). */
export const OFFER = {
  nextLesson: "Ready for the next lesson?",
  ride: "Ready for your check ride?",
  mission: "Ready to take command?",
  flyAgain: "Fly again?",
  nextStep: "Ready for the next one?",
};

// ---------- Mission: lessons come back as events ----------
/** Mission event kind / alert → the Flight School lesson that taught it (course.json id), and CAPCOM's reminder. */
export const CALLBACKS = {
  solar_storm: { lesson: "radiation", n: 4, text: "Solar storm. Shields up, or crew to the shelter." },
  low_power: { lesson: "power", n: 3, text: "Battery's low. Turn down what you don't need." },
  sunset: { lesson: "power", n: 3, text: "Sunset. Give the heaters a little more." },
  life_support_low: { lesson: "life", n: 5, text: "Life support is low. The rover can fetch ice." },
  comm_closed: { lesson: "comms", n: 2, text: "Earth has set. No radio until it rises." },
  dose_alert: { lesson: "radiation", n: 4, text: "Dose is climbing. Shields, or the shelter." },
};
export const callbackLine = (kind, earned) => {
  const c = CALLBACKS[kind]; if (!c) return null;
  return (earned ? `Remember Lesson ${c.n}? ` : `Lesson ${c.n} covers this. `) + c.text;
};

// ---------- Debrief ----------
export const DEBRIEF = {
  learned: "Lessons in action",
  learnedEmpty: "Fly more shifts to see your lessons in action.",
  replay: "Fly again",
  another: "New site",
  close: "Back",
  mars: "On Mars, Houston would answer 6 to 44 minutes later.",
  /** On screen and spoken (pass callSign.spoken() when speaking). */
  grade: (cs, g, pts) => `Nice flying, ${cs}. Grade ${g}, ${pts} points.`,
};
