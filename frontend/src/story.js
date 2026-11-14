// Outpost Luna: the story, in ONE file. Every line of story copy (beats, CAPCOM lines that use the call sign, lesson
// callbacks during the Mission, debrief copy, spoken offers) lives here so it is easy to edit. No logic beyond tiny
// templating. Voice, tone and word budgets: docs/COPY.md. Tests: backend/tests/test_copy.py (no emoji, spoken <= 20 words).
//
// Framing (keep it true; docs/ACCURACY_AUDIT.md #1): Artemis II flew its crew around the Moon in April 2026. Since
// NASA's 2026-02-27 restructure, Artemis III (2027) is a crewed test flight in Earth orbit, with no landing. The first
// crewed landing is planned for Artemis IV (2028), and NASA has not confirmed its site. No crew has landed at the
// south pole. The kid trains at Flight School to help run Outpost Luna, a south-pole base for the crews who will come.

export const CREDIT = "Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA.";

/** Honest sourcing line (About, Debrief). Never claim that everything comes from NASA (docs/COPY.md, Accuracy). */
export const SOURCES_LINE = "Built on NASA open data, plus a few science papers. Some outpost tech is pretend, and we label it.";

/** Tag for game-only hardware (powered radiation shields, greenhouse, rim-to-floor cable, rim relay). Tooltip: 10 words. */
export const PRETEND_TECH = "Pretend tech";
export const PRETEND_TECH_TIP = "Made up for the game. Real crews don't have this.";

/** The May 2024 storm, told truthfully: Earth saw a magnetic storm (auroras); the Moon's hazard is the particles. */
export const STORM = {
  name: "Solar particle storm",
  /** QA-27: a storm with few particles (sep: false) is named by what it is at the Moon */
  weak: "Storm at Earth",
  weakText: "Few particles here",
  may2024: "Based on the real May 2024 storm. It gave Earth huge auroras.",
};

/** Three short sentences. mission/ui.js shows everything after the first ". " as a sub line. */
export const FRAMING = "Artemis II flew around the Moon in April 2026. No crew has landed at the south pole yet. Train now for the crews who will.";

/** The four beats of the one story, shown on the Academy map and in About. */
export const BEATS = [
  { id: "school", title: "Flight School", text: "Learn the Moon with CAPCOM." },
  { id: "ride", title: "Check ride", text: "Fly your first solo shift." },
  { id: "mission", title: "Command", text: "Run Outpost Luna for 10 days." },
  { id: "debrief", title: "Debrief", text: "See what you learned." },
];

// ---------- The story arc (docs/STORY.md) ----------
// Kid -> cadet in Flight School -> qualified (check ride) -> commander of Outpost Luna for 10 days -> debrief -> fly
// again, or try another site. At every transition one short beat says where you are, why, and what's next: spoken
// (`say`, 20 words or fewer) and on screen (`where` eyebrow + `line`, 12 words or fewer). The screen's own button is the
// next action, so a beat never explains the button.
/** Where the kid is on the arc: index into BEATS (0 school, 1 ride, 2 command, 3 debrief). */
export const ARC_STEP = (k, n = BEATS.length) => `Step ${k + 1} of ${n}`;
export const TRANSITION = {
  /** first launch -> map (after the call sign) */
  firstMap: {
    where: "Flight School", line: "Earn a patch at each pin. Then fly your check ride.",
    say: "Each pin on the Moon is a lesson. Earn the patches, then command the outpost.",
  },
  /** map -> lesson: lessonHello (LESSON_STORY beats) carries it. */
  /** lesson -> patch: the sub line under the patch name. */
  patchProgress: (n, total) => `${n} of ${total} patches. ${total - n === 1 ? "One lesson to go." : total - n > 1 ? `${total - n} lessons to go.` : ""}`.trim(),
  /** last lesson -> ride */
  toRide: {
    where: "Check ride", line: "One solo shift. Pass it and you take command.",
    say: "Your check ride is next: one solo shift. Pass it to take command.",
  },
  /** ride -> qualified -> Mission */
  qualified: {
    line: "Next: pick a site and run Outpost Luna for 10 days.",
  },
  /** picker (first time in) */
  picker: {
    where: "Command", line: "Sun means power. Earth means radio. Pick your trade-off.",
  },
  /** picker -> cabin: missionStart, then the tour (first mission) or the objective line. */
  /** cabin -> debrief: DEBRIEF.story. debrief -> again: OFFER.flyAgain. */
};

/** The site picker: why the choice matters, and the first-timer's pick (the check ride flew there). */
export const PICKER = {
  title: "Pick your outpost site",
  why: "Sun means power. Earth means radio. Pick your trade-off.",
  recommended: "shackleton_rim",
  recTag: "Best first pick",
  recLine: "For a first mission, try Shackleton Rim: Sun all 10 days.",
};

// ---------- First mission: CAPCOM's cabin tour (mission/tour.js) ----------
// Each beat is 12 words or fewer, spoken and shown with a Next button. "next", Enter, a swipe or a thumbs up moves on;
// "skip tour" ends it; "show me around" (or Settings -> Help) replays it. `show` is what the cabin lights up:
// view:<id> | du:<0-2> | panel:<id> | lamps | goals | start. Cadet hears the full tour, Commander the short one.
export const TOUR = {
  title: "Cabin tour",
  next: "Next",
  done: "Got it",
  skip: "Skip tour",
  replay: "Show me around",
  step: (n, of) => `${n} of ${of}`,
  cadet: [
    { show: "window", text: "This is your window. Switch views: Orbit, Site, Rover, Earth." },
    { show: "du:0", text: "Your three screens. First, power: the battery the Sun fills." },
    { show: "du:1", text: "Life support: the air and water your crew needs." },
    { show: "du:2", text: "Dose: the radiation your crew has taken. Keep it low." },
    { show: "panel:power", text: "Power panel: pick a system, then press plus or minus." },
    { show: "panel:habitat", text: "Habitat: heaters, science, and your mission goals." },
    { show: "panel:rover", text: "Rover: send it for ice, then bring it home." },
    { show: "panel:radiation", text: "Radiation: shields, and the storm shelter under its cover." },
    { show: "panel:comm", text: "Comm: call Houston when Earth is in view." },
    { show: "lamps", text: "Warning lights. Red means act now. Amber means get ready." },
    { show: "goals", text: "Your goal: ten safe days. Send science home. Bring back ice." },
    { show: "start", text: "First job: raise the shields. Then press Play to start time." },
  ],
  commander: [
    { show: "window", text: "Window up top. Three screens below. Five panels around you." },
    { show: "start", text: "Ten safe days, science home, ice back. Set power, then Play." },
  ],
};

// ---------- The cabin's "what now" strip (mission/objective.js picks one) ----------
/** Each line: on screen after "Now:" (12 words or fewer) and spoken for "what do I do?". */
export const NOW = {
  label: "Now",
  firstShift: "Set power: raise the shields.",
  startClock: "Power set. Now press Play to start the clock.",
  stormHit: "Storm hitting. Get the crew into the shelter.",
  weakStorm: "Storm at Earth, few particles here. Keep working.",
  sheltered: "Crew sheltered. Skip ahead to ride out the storm.",
  warning: h => (h != null ? `Storm forecast: about ${h} hours to get ready. Shields or shelter.` : "Storm coming. Get ready: shields or shelter."),
  lowPower: "Battery low. Turn on night mode, or cut a load.",
  lowAir: "Air is low. Send the rover for ice.",
  roverDark: "Rover out. Bring it home before dark.",
  roverOut: h => `Rover out, back in ${h} hours. Skip ahead to wait.`,
  sunset: h => `Sunset in ${h} hours. Turn on night mode before dark.`,
  dark: "Dark outside. Night mode saves power.",
  ice: "No storm due. Send the rover for ice.",
  steady: "All steady. Time warp?",
  steadyFast: "All steady at 4x. Skip to the next event?",
  confirmTitle: "CAPCOM asks",
  confirm: "CAPCOM needs a yes or no.",
  paused: "Clock paused. Press Play when you're ready.",
  driving: h => `Rover driving. Back in ${h} hours.`,
  repairing: "Rover fixing the array. Skip ahead to wait.",
  waiting: "Not yet. Skip ahead, or watch the clock.",
  taskDone: t => `${t}: done.`,
  /** the ~20 s nudge (spoken; 20 words or fewer with the task's step) */
  nudge: (task, step) => `${task}. Next: ${step}`,
  /** the card's clock buttons (QA-69: a verb first) */
  playBtn: "Start the clock",
  skipBtn: "Skip ahead",
  warpBtn: "Time warp 4x",
  /** "Lesson 5 helps here" (the lesson's patch title is the tooltip) */
  lessonHelps: n => `Lesson ${n} helps here`,
  /** said before the line when the kid asks "what do I do?" */
  ask: "Here's your next job.",
};

/** "What do I do?" on the other screens (the router's `help`, outside lessons). Spoken; 20 words or fewer. */
export const HELP = {
  map: "Press Start on the lesson card, or say next. Each lesson earns a patch.",
  mapQualified: "You're qualified. Say take command to run the outpost.",
  patch: "Say next for the next lesson, or press Map to look around.",
  picker: "Pick a site from the list, then say take command.",
  debrief: "Say fly again to try this site again, or new site.",
  library: "Tap a place on the Moon, or ask a question.",
  callsign: "Pick a call sign, then press Start.",
};

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
  /** [audit2] Start with an empty field (on screen, under the field). */
  empty: "Type a call sign, or tap one.",
  /** [audit2] a name typed in the voice bar went into the field. */
  typed: "Got it. Tap Start to use it.",
  pick: "Pick one from the list, like Nova or Comet.",
  /** [audit2] after changing the call sign from the map (was "Welcome to Flight School." again). */
  saved: cs => `Copy that, ${cs}. Call sign saved.`,
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
  power: "Sunlight, batteries, and Malapert's long dark spell.",
  radiation: "Measure radiation. Ride out a solar particle storm.",
  life: "Air, water, and the ice LCROSS found.",
  history: "What Apollo left behind for the next crews.",
  words: "Albedo, regolith, terminator: words the crew really used.",
  checkride: "Two days at Shackleton Rim. Your first solo shift.",
};
export const WHY_TITLE = "Why this matters";
export const WHY = "The first crew landing is planned for Artemis IV, in 2028.";
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
  hero: "Nobody's landed at the pole yet.",
  hero2: "Train for the crews who will.",
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
  /** [audit2] "next" said before the step is answered (spoken before the step's hint). */
  answerFirst: "Answer this one first.",
  /** [audit2] the map's beat after the first patch (was blank: a returning cadet saw no "where am I"). */
  progressLine: (n, of, next) => `${n} of ${of} lessons done. Next: ${next}.`,
  /** [audit2] "What do I do?" on the map names the button the card really shows. */
  mapHelp: (cta, title, ride) => (ride ? `Tap ${cta}. One solo shift, then you take command.` : `Tap ${cta} to begin ${title}.`),
};

/** One short story beat per lesson (shown above CAPCOM's brief, and spoken before it). Keyed by course.json lesson id.
 *  CAPCOM says them, so they are first person or plain statements (never narrator copy, never a question it won't wait for).
 *  Patches are drawn by the art set (no emoji here). */
export const LESSON_STORY = {
  moon: { beat: "Day one. Let's start with a map of the Moon." },
  comms: { beat: "Radio check. Houston is 384,000 km away." },
  power: { beat: "The outpost runs on sunlight." },
  radiation: { beat: "Storm drill. The Sun can throw storms at the Moon." },
  life: { beat: "No air, no rivers. Let's go looking for ice." },
  history: { beat: "Every crew learns from the crews before." },
  words: { beat: "A new world needs new words." },
  checkride: { beat: "Solo shift. I'm only watching this time." },
};

/** CAPCOM's lines that use the call sign (the spoken form is passed in, so a typed name is never read aloud). */
export const CAPCOM = {
  lessonHello: (cs, beat) => `${beat} Here we go, ${cs}.`,
  patch: (cs, name) => `Patch earned: ${name}. Nice work, ${cs}.`,
  qualified: (cs, name) => `${name} patch earned. You're qualified, Commander ${cs}.`,
  missionBrief: (cs, rank = "Commander") => `Pick a site, ${rank} ${cs}. Keep the crew safe for ten days.`,
  missionStart: (cs, site) => `Outpost Luna is online at ${site}. Day one, ${cs}.`,
  /** First mission only: said once after missionStart, then again only after a silence (no order yet). */
  firstShift: "Raise the shields, then start the clock.",
  houstonCalling: "Calling Houston…",
};

/** Check-ride result card (on screen, not spoken). The backend sends the same line as `fact`. */
export const RIDE = {
  mars: "On Mars, Houston would answer 6 to 44 minutes later.",
};

/** The Mission tab before the check ride (state-driven: Flight School's `qualified`). A cadet isn't a commander yet: the
 *  tab explains the path and offers one practice shift at Shackleton Rim (real sim, Cadet band, doesn't count). */
export const GATE = {
  eyebrow: "Command · Cadet",
  title: "Pass your check ride to take command.",
  sub: "Try one practice shift first. It doesn't count.",
  practice: "Try a practice shift",
  ride: "Fly the check ride",
  say: cs => `${cs}, pass your check ride to take command. Want to try a practice shift?`,
  tag: "Practice",
  doneTitle: "Practice shift done",
  doneSub: "Nice work. Pass your check ride to take command.",
  doneSay: cs => `Practice shift done, ${cs}. Pass your check ride to take command.`,
  again: "Practice again",
};

/** Spoken offers: said once, as a question. "yes" / "next" takes them (the router's accept_offer). */
export const OFFER = {
  nextLesson: "Ready for the next lesson?",
  ride: "Ready for your check ride?",
  mission: "Ready to take command?",
  flyAgain: "Fly again?",
  resume: "Back to the cabin?",
  firstLesson: "Ready for lesson one?",
  nextStep: "Ready for the next one?",
};

// ---------- Mission: lessons come back as events ----------
/** Mission event kind / alert → the Flight School lesson that taught it (course.json id), and CAPCOM's reminder. */
export const CALLBACKS = {
  solar_storm: { lesson: "radiation", n: 4, text: "Solar particle storm. Shields up, or crew to the shelter." },
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
  /** The story of the mission in three beats (mission/objective.js debriefStory picks them from the debrief). */
  storyTitle: "What happened",
  tryTitle: "Try next",
  start: (site, days) => `You ran ${site} for ${days} day${days === 1 ? "" : "s"}.`,
  stormSafe: n => `${n === 1 ? "A real solar storm hit" : `${n} real solar storms hit`}. Your crew stayed safe.`,
  stormHurt: n => `${n === 1 ? "A real solar storm hit" : `${n} real solar storms hit`}. Your crew took a big dose.`,
  noStorm: "The Sun stayed quiet this time.",
  goalsBoth: "You sent science home and brought back ice.",
  goalsScience: "You sent science home. No ice run yet.",
  goalsIce: "You brought back ice. Science still waiting.",
  goalsNone: "No science home and no ice yet.",
  endWon: "All ten days done. The crew is home safe.",
  endPaused: d => `Paused on day ${d}. Your outpost is waiting.`,
  endLost: "The mission ended early.",
  /** The one clear choice at the end (the primary button) and its spoken offer. */
  choiceAgain: "Fly again",
  choiceNew: "Pick a new site",
  resume: "Resume mission",
  /** QA-26: leaving a paused mission asks first */
  wipeAsk: "Start over? This mission ends, and you begin again at shift 1.",
  wipeYes: "Start over",
  wipeNo: "Keep my mission",
  tryDefault: "Next time, watch the warning lights and act early.",
  tryNewSite: "Next, try a site with a long night, like Malapert.",
  gradeOver: (cs, g, pts) => `Grade ${g}, ${pts} points. Let's learn from it, ${cs}.`,   // [qa] a failed mission isn't "nice flying"
};
