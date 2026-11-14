// Outpost Luna: the story, in ONE file. Every line of story copy (beats, CAPCOM lines that use the call sign, lesson
// callbacks during the Mission, debrief copy) lives here so it is easy to edit. No logic beyond tiny templating.
//
// Framing (keep it true): Artemis II flew its crew around the Moon in April 2026. Artemis III, the first landing near
// the south pole, has NOT happened yet. The kid trains at Flight School to help run Outpost Luna, a south-pole base for
// the crews who will come after.

export const CREDIT = "Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA.";

export const FRAMING = "Artemis II flew its crew around the Moon in April 2026. Artemis III, the first landing near the south pole, hasn't happened yet. "
  + "You're training to help run Outpost Luna, a base at the south pole for the crews who come after.";

/** The four beats of the one story, shown on the Academy map and in About. */
export const BEATS = [
  { id: "school", icon: "🎓", title: "Flight School", text: "Learn the Moon with CAPCOM, your mentor." },
  { id: "ride", icon: "🧭", title: "Check ride", text: "Your first solo shift in the cockpit." },
  { id: "mission", icon: "🛰️", title: "Command", text: "Run Outpost Luna for 10 days." },
  { id: "debrief", icon: "📋", title: "Debrief", text: "See what you learned, with real NASA data." },
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
  sub: "Every astronaut has a radio name. CAPCOM will use yours. It stays on this device.",
  type: "Or make one up",
  save: "That's me",
  random: "Surprise me",
};

// ---------- Academy (Flight School) ----------
export const SCHOOL = {
  eyebrow: "Flight School",
  title: c => `Welcome to Flight School, ${c}`,
  titleDone: c => `You're qualified, Commander ${c}!`,
  sub: "Earn a patch in each lesson. Then fly your check ride: your first solo shift at Outpost Luna.",
  subDone: "Replay any lesson, or take command of Outpost Luna.",
  start: "Start lesson",
  go: "Take command of Outpost Luna",
};

/** One short story beat per lesson (shown above CAPCOM's brief) and the patch emoji. Keyed by course.json lesson id. */
export const LESSON_STORY = {
  moon: { patch: "🌙", beat: "Day 1 at Flight School. CAPCOM pulls up a map of the Moon." },
  comms: { patch: "📻", beat: "Radio check! Outpost Luna is 384,000 km from Houston." },
  power: { patch: "☀️", beat: "The outpost lives on sunlight. Let's see where it comes from." },
  radiation: { patch: "🛡️", beat: "Alarm drill! The Sun can throw storms at the Moon." },
  life: { patch: "🧊", beat: "No air, no water on the Moon… or is there ice?" },
  history: { patch: "📜", beat: "Every crew learns from the crews before them." },
  checkride: { patch: "🚀", beat: "Solo shift! You're in the Outpost Luna cockpit. CAPCOM is only watching." },
};

/** CAPCOM's lines that use the call sign (the spoken form is passed in, so a typed name is never read aloud). */
export const CAPCOM = {
  lessonHello: (cs, beat) => `${beat} Ready, ${cs}?`,
  patch: (cs, name) => `Patch earned, ${cs}: ${name}!`,
  qualified: (cs, name) => `Congratulations, Commander ${cs}! You earned the ${name} patch. Outpost Luna is yours.`,
  missionBrief: cs => `Welcome to Outpost Luna, Commander ${cs}. Pick a site, then keep power, life support and radiation safe for ten days.`,
  missionStart: (cs, site) => `Outpost Luna is online at ${site}, ${cs}. Day 1. Check your power levers, then say "end shift".`,
  houstonCalling: "Calling Houston…",
};

// ---------- Mission: lessons come back as events ----------
/** Mission event kind / alert → the Flight School lesson that taught it (course.json id), and CAPCOM's reminder. */
export const CALLBACKS = {
  solar_storm: { lesson: "radiation", n: 4, text: "That's a solar storm, like in Lesson 4. Shields up, or everyone into the shelter." },
  low_power: { lesson: "power", n: 3, text: "Batteries are low. Remember Lesson 3: no Sun means batteries only. Turn down what you don't need." },
  sunset: { lesson: "power", n: 3, text: "The Sun is setting. Remember Lesson 3: give the heaters a little more." },
  life_support_low: { lesson: "life", n: 5, text: "Life support is low. Lesson 5: send the rover for ice." },
  comm_closed: { lesson: "comms", n: 2, text: "Earth just set, so the radio is quiet. Lesson 2: keep your orders short when it's back." },
  dose_alert: { lesson: "radiation", n: 4, text: "Dose is climbing. Lesson 4: shields, or the shelter." },
};
export const callbackLine = (kind, earned) => {
  const c = CALLBACKS[kind]; if (!c) return null;
  return (earned ? `Remember Lesson ${c.n}? ` : `Flight School Lesson ${c.n} covers this. `) + c.text;
};

// ---------- Debrief ----------
export const DEBRIEF = {
  learned: "Flight School in action",
  learnedEmpty: "Play more shifts to see your lessons come back as real events.",
  replay: "Fly it again",
  another: "Try another site",
  mars: "On Mars, Houston would answer 6 to 44 minutes later.",
};
