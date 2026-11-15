// The voice pack's line inventory, frontend half (docs/VOICE_PACK.md). Run by backend/tools/voice_pack_lines.py
// (`make voice-pack-lines`); not part of the app bundle.
//
//   node frontend/tools/voice_lines.mjs [backend_says.json]  ->  JSON on stdout: {units: [...], live: [...]}
//
// Every fixed line the frontend speaks, composed exactly as the app composes it (story.js copy, the Flight School
// course, the cabin tour, the Now strip, debrief beats), plus the backend's fixed lines (the JSON file the Python half
// writes). Each `say` is then split into the units the floor really requests from /api/tts (floor.js sayLines: one
// request per sentence, short fragments folded into the next one), because the voice pack is looked up per request.
// Placeholders with a small finite set of values (the preset call signs, the five sites, hour counts, warp factors)
// are expanded; anything open-ended stays live and is listed in `live` with the reason.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as S from "../src/story.js";
import { INTRO, doLine, helpLine } from "../src/academy/guide.js";
import { sayLines } from "../src/floor.js";
import { WARPS } from "../src/mission/clock.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = p => readFileSync(path.join(ROOT, p), "utf8");
const course = JSON.parse(read("backend/data/academy/course.json"));
const sitesRaw = JSON.parse(read("backend/data/mission/sites.json"));
const SITES = (Array.isArray(sitesRaw) ? sitesRaw : sitesRaw.sites || []).map(s => String(s.name || "").split(" (")[0]).filter(Boolean);

const says = [];   // {lines: string[], source, role}
const live = [];   // {source, text, reason}
const add = (lines, source, role = "capcom") => {
  const ls = (Array.isArray(lines) ? lines : [lines]).filter(t => t && String(t).trim());
  if (ls.length) says.push({ lines: ls, source, role });
};
const keepLive = (source, text, reason) => live.push({ source, text, reason });

// The call signs CAPCOM may say aloud (story.js callSign.spoken: a typed name is never spoken), plus the fallbacks the
// code passes ("Cadet", "cadet", "Commander").
const CS = [...S.CALLSIGNS, "Cadet", "Commander"];
const HOURS = Array.from({ length: 12 }, (_, k) => k + 1);   // hour counts the cabin strip reads out
const STORY = "frontend/src/story.js";
const AUI = "frontend/src/academy/ui.js", MUI = "frontend/src/mission/ui.js";

// ---------------------------------------------------------------- code literals the UI speaks (checked against the source)
const CODE = [
  [AUI, "Pick a call sign, then tap Start."], [AUI, "Tap Take command to run the outpost."],
  [AUI, "Tap a patch to fly a lesson again."], [AUI, "Tap Next for the next lesson, or Map."], [AUI, "Tap Next, or say next."],
  [MUI, "Clock running."],
];
for (const [f, t] of CODE) {
  if (!read(f).includes(t)) throw new Error(`voice_lines: "${t}" is no longer in ${f}: update frontend/tools/voice_lines.mjs`);
  add(t, f);
}

// ---------------------------------------------------------------- Flight School (academy/ui.js), CAPCOM's voice
add(S.CALLSIGN_COPY.say, STORY); add(S.CALLSIGN_COPY.typed, STORY); add(S.CALLSIGN_COPY.pick, STORY);
for (const cs of CS) add(S.CALLSIGN_COPY.saved(cs), STORY);
for (const cs of [...S.CALLSIGNS, "Cadet"]) add([`Copy that, ${cs}. Welcome to Flight School.`, S.TRANSITION.firstMap.say, S.OFFER.firstLesson], AUI);
Object.values(S.HELP).forEach(t => add(t, STORY));
const lessons = course.lessons || [];
for (const L of lessons) {
  const beat = (S.LESSON_STORY[L.id] || {}).beat || "";
  const first = L.steps[0], intro = INTRO[first.accept.type];
  for (const cs of [...S.CALLSIGNS, "cadet"]) add([S.CAPCOM.lessonHello(cs, beat), L.brief, first.prompt, ...(intro && !L.ride ? [intro] : [])], AUI);
  add(L.brief, "backend/data/academy/course.json");
  L.steps.forEach((st, k) => {
    const vocab = st.accept.type.startsWith("vocab_");
    const it = INTRO[st.accept.type];
    if (k > 0) add(it && !L.ride ? [st.prompt, it] : st.prompt, "backend/data/academy/course.json");
    add(st.prompt, "backend/data/academy/course.json");   // "say that again" / a repeat
    if (vocab) keepLive("backend/data/academy/course.json", `${L.id} step ${k + 1} (${st.accept.type}) replies`, "vocabulary lines are slowed and stressed on purpose (situation vocab): always live");
    // "next" before the answer: SCHOOL.answerFirst + the help line
    add(`${S.SCHOOL.answerFirst} ${helpLine(doLine(st), st.hint)}`, AUI);
    add(helpLine(doLine(st), st.hint), AUI);   // "what do I do?" in a step
    // an "after" crew clip: CAPCOM only acknowledges (ui.js answer(): the first <= 3-word sentence of the line)
    const c = st.clip || (k === 0 ? L.clip : null);
    if (c && c.when === "after" && !vocab) {
      for (const line of [st.success, st.reveal].filter(Boolean)) {
        const ack = (String(line).match(/^\s*([^.!?]{1,24}[.!?])/) || [])[1];
        if (ack && ack.trim().split(/\s+/).length <= 3) add(ack.trim(), AUI);
      }
    }
  });
}
Object.values(INTRO).forEach(t => add(t, "frontend/src/academy/guide.js"));
// the patch / qualified line + the story beat + the offer (showBadge)
const plain = lessons.filter(l => !l.ride);
for (const cs of [...S.CALLSIGNS, "cadet", "Commander"]) {
  plain.forEach((L, k) => {
    const nx = lessons[k + 1];
    add([S.CAPCOM.patch(cs, L.badge.name), ...(nx && nx.ride ? [S.TRANSITION.toRide.say] : []), nx ? (nx.ride ? S.OFFER.ride : S.OFFER.nextLesson) : S.OFFER.nextLesson], AUI);
    add(S.CAPCOM.patch(cs, L.badge.name), AUI);
  });
  lessons.filter(l => l.ride).forEach(L => add([S.CAPCOM.qualified(cs, L.badge.name), S.OFFER.mission], AUI));
}
Object.values(S.OFFER).forEach(t => add(t, STORY));
// the map's help: "Tap <button> to begin <lesson>."
for (const L of lessons) for (const cta of ["Start lesson", "Continue", "Replay", S.SCHOOL.ride]) add(S.SCHOOL.mapHelp(cta, L.title, !!L.ride), AUI);

// ---------------------------------------------------------------- Mission (mission/ui.js), CAPCOM's voice
for (const cs of [...S.CALLSIGNS, "Cadet"]) { add(S.GATE.say(cs), STORY); add(S.GATE.doneSay(cs), STORY); }
add(S.GATE.doneSub, STORY);
for (const cs of [...S.CALLSIGNS, "Commander"]) for (const rank of ["Commander", "Cadet"]) {
  add([S.CAPCOM.missionBrief(cs, rank), S.PICKER.why, S.PICKER.recLine], MUI);
}
add(S.PICKER.why, STORY); add(S.PICKER.recLine, STORY);
for (const site of SITES) {
  add(`${site}. Good choice. Say take command when you're ready.`, MUI);
  add(`${site}.`, MUI);
  for (const cs of [...S.CALLSIGNS, "Commander"]) add(S.CAPCOM.missionStart(cs, site), MUI);
}
add(S.CAPCOM.firstShift, STORY);
for (const b of [...S.TOUR.cadet, ...S.TOUR.commander]) add(b.text, STORY);
// the Now strip: spoken for "what do I do?" (NOW.ask + the text), as a nudge, or as the objective after the hello
add(S.NOW.ask, STORY);
for (const [k, v] of Object.entries(S.NOW)) {
  if (typeof v === "string" && !/Btn$|^label$|Title$/.test(k)) add(v, STORY);
}
add(S.NOW.warning(null), STORY);
for (const h of HOURS) { add(S.NOW.warning(h), STORY); add(S.NOW.roverOut(h), STORY); add(S.NOW.sunset(h), STORY); add(S.NOW.driving(h), STORY); }
keepLive(STORY, "NOW.taskDone(task)", "said only as a card line (the task title is the sim's): covered by the task titles when spoken");
// clock lines
for (const w of WARPS.filter(w => w > 1)) add(`Clock running, ${w} times.`, MUI);
for (const w of WARPS) add(`Time warp, ${w} times.`, MUI);
// lessons coming back as events (callbackLine)
for (const kind of Object.keys(S.CALLBACKS)) for (const earned of [true, false]) add(S.callbackLine(kind, earned), STORY);
// debrief beats: the story, the try line and the offer (the grade line has open numbers: live)
for (const site of [...SITES, "the outpost"]) for (let d = 1; d <= 10; d++) add(S.DEBRIEF.start(site, d), STORY);
for (let n = 1; n <= 4; n++) { add(S.DEBRIEF.stormSafe(n), STORY); add(S.DEBRIEF.stormHurt(n), STORY); }
for (const k of ["noStorm", "goalsBoth", "goalsScience", "goalsIce", "goalsNone", "endWon", "endLost", "wipeAsk", "tryDefault", "tryNewSite"]) add(S.DEBRIEF[k], STORY);
for (const t of [S.DEBRIEF.tryDefault, S.DEBRIEF.tryNewSite]) add(`${t} ${S.OFFER.flyAgain}`, MUI);
for (let d = 1; d <= 10; d++) add(`${S.DEBRIEF.endPaused(d)} ${S.OFFER.resume}`, MUI);
keepLive(STORY, "DEBRIEF.grade / gradeOver (\"Nice flying, <cs>. Grade <g>, <points> points.\")", "the score is an open number");
keepLive(MUI, "\"Houston here. We copy you, <rank>. …\" and every Houston answer", "Houston keeps its own role voice (live)");

// ---------------------------------------------------------------- the Library (missions.js), the guide's voice
const clues = [...read("frontend/src/missions.js").matchAll(/clue: "([^"]+)"/g)].map(m => m[1]);
clues.forEach(t => add(t, "frontend/src/missions.js", "guide"));
keepLive("frontend/src/missions.js", "\"You found it. <place>. <fact or story>\" / \"That's <place>. Keep looking.\"", "place facts and hardware stories are long, data-driven and spoken in the story voice for hardware");
keepLive("frontend/src/main.js", "\"That spot is <lat>° …\"", "coordinates are open numbers");

// ---------------------------------------------------------------- the backend's fixed lines (backend/tools/voice_pack_lines.py)
const extra = process.argv[2] ? JSON.parse(readFileSync(process.argv[2], "utf8")) : { says: [], live: [] };
for (const s of extra.says || []) add(s.lines, s.source, s.role || "capcom");
for (const l of extra.live || []) live.push(l);

// ---------------------------------------------------------------- split into the requests the floor makes
const units = [];
for (const s of says) for (const text of sayLines(s.lines)) units.push({ text, source: s.source, role: s.role });
process.stdout.write(JSON.stringify({ units, live, says: says.length }));
