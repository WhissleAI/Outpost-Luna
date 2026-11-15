// Barge-in policy (docs/SESSION_CONTRACT.md §3 rule 2): when may open-mic speech stop a line we are playing?
//
// Owner bug (Flight School, Radiation step 5): "it gets our silence and stops the tts in between". The line was cut by
// something that was not the kid: our own voice leaking from the speakers back into the mic (TTS read "mSv" as the
// letters "M S V", the ear heard "m s v", and the exact-word echo check missed it), room talk, or noise the ear turned
// into a couple of words. A line now stops only for a real, intentional interruption:
//   1. words, never energy or a turn start alone: >= 2 real words, or one of the short COMMANDS ("stop", "wait", …);
//   2. not an echo: the heard words against what is playing and the last few lines, fuzzy (spelled-out letters
//      collapsed, the spoken form of each line, near-miss spellings): isEcho in floor.js, the router's echo rule;
//   3. directed: Arc's device_directed under the filter's floor is room talk, and a turn Arc never rated (noise, far
//      chatter: the ear sends no device_directed for them) is not for us either (the stop words still work);
//   4. louder than our own voice coming back: ENERGY_FRAMES mic frames over the measured speaker leak (ducked-reference
//      gating, voice.js turnEnergy) and the room. The ear turns our leaked voice into confident nonsense ("Dr. Carla
//      Reyes in the NFC") that no word check can match, and Arc rates it device-directed (it is a voice talking to
//      the device), so energy is the only thing that tells it apart from the kid;
//   5. sustained: >= MIN_SPEECH_MS of speech, and never inside a line's first LINE_GRACE_MS or a sentence's first
//      RESUME_GRACE_MS (held, not dropped: the check runs again when the window ends).
// Space (push-to-talk) bypasses all of this: an explicit action interrupts at once (voice.js).
import { normWords, isFiller, isEcho, BARGE } from "./floor.js";

/** Tuning (measured with frontend/tools/barge_harness.mjs; see docs/HANDSFREE.md "Barge-in"). Tests may change it. */
export const BARGE_TUNING = {
  MIN_WORDS: 2,             // open-mic words needed to interrupt (a COMMAND needs one)
  MIN_SPEECH_MS: 350,       // sustained speech since the ear's turn start (a finished turn counts as sustained)
  LINE_GRACE_MS: 600,       // no barge-in in a line's first 600 ms (the speaker-to-mic echo burst at onset)
  RESUME_GRACE_MS: 300,     // nor in the first 300 ms after a sentence starts or the audio resumes
  ENERGY_ABS_MIN: 0.004,    // mic RMS (0..1) a frame must reach to count as the kid while we play, whatever the room
  ENERGY_LEAK_X: 1.8,       // ... and 1.8x (+5 dB) the leak we expect: our output envelope x the speaker-to-mic coupling
  ENERGY_FLOOR_X: 3.0,      // ... and 3x the room's noise floor (mic level while quiet)
  ENERGY_FRAMES: 4,         // frames (80 ms) above that in the turn's recent window: ~320 ms of speech over our voice
  RECOVER_MS: 1500,         // a barge-in with no actionable turn after this: say the interrupted sentence again
  RECOVER_MAX_MS: 8000,     // never resume a line older than this
};

// Short commands that may interrupt on their own (one or two words). STOP ones also pass the directed check: a kid who
// says "stop" to the app while a sibling talks still gets silence.
const STOP = new Set(["stop", "wait", "pause", "quiet", "be quiet", "never mind", "nevermind", "hold on", "hang on",
  "stop talking", "stop please", "wait please", "stop stop", "wait wait", "shush", "silence", "enough", "cancel",
  "stop it capcom", "okay stop", "ok stop"]);
const NAV = new Set(["skip", "next", "skip it", "skip this", "next one", "next please", "go back", "say again",
  "repeat", "repeat that", "say that again", "go on", "move on"]);
const strip = q => q.replace(/^(?:okay|ok|um|uh|hey|capcom|please) /, "").replace(/ (?:please|capcom|now)$/, "");
const key = text => strip(normWords(text).join(" "));
/** A short command that may interrupt on its own ("stop", "wait", "skip", "next", "be quiet", "never mind"). */
export const isCommand = text => { const q = key(text); return STOP.has(q) || NAV.has(q); };
/** A stop word: interrupts even when Arc rates it as not directed, and never resumes the line. */
export const isStopCommand = text => STOP.has(key(text));
const STOP_WORD = /\b(?:stop|wait|pause|quiet|shush|enough|skip|next|never ?mind|hold on|hang on)\b/;
/** The turn says a stop / skip word anywhere ("… finish. Stop."): after a barge-in the line is not resumed. */
export const saysStop = text => STOP_WORD.test(normWords(text).join(" "));

function filterLevels() {
  const f = typeof window !== "undefined" && window.__outpost && window.__outpost.prefs && window.__outpost.prefs.filter;
  return BARGE[f] || BARGE.normal;
}

/**
 * One open-mic turn heard while a line plays → {act, reason, retryMs}.
 *   act "barge"  interrupt now          "wait"  not yet (more words / the window ends in retryMs)
 *   act "hold"   this turn never interrupts (the caller drops it at the turn end)
 * @param {{text:string, refs?:string[], dd?:number|null, final?:boolean, speechMs?:number, sinceLineMs?:number,
 *          sinceSentenceMs?:number, energy?:{loud:number}|null, rated?:boolean}} o
 *   energy.loud: mic frames over the leak/room need in the turn's window (null: no levels, skip the test)
 *   rated: false when the ear sends Arc metadata but none came for this turn
 */
export function decideBarge({ text, refs = [], dd = null, final = false, speechMs = Infinity, sinceLineMs = Infinity,
  sinceSentenceMs = Infinity, energy = null, rated = true }) {
  const T = BARGE_TUNING;
  const no = reason => ({ act: final ? "hold" : "wait", reason, retryMs: 0 });
  const w = normWords(text);
  if (!w.length) return no("no_words");
  if (isFiller(text)) return no("filler");
  if (isEcho(text, refs)) return no("echo");
  const cmd = isCommand(text), stop = cmd && isStopCommand(text);
  const [lo, hi] = filterLevels();
  if (!cmd) {
    if (w.length < T.MIN_WORDS) return no("too_short");
    if (w.length === 2 && !(dd != null && dd >= hi)) return no("two_words");   // 2 words: a command, or clearly to us
  }
  if (dd != null && dd < lo && !stop) return no("not_directed");
  if (!rated && !stop) return no("not_rated");
  if (energy && energy.loud < T.ENERGY_FRAMES) return no("low_energy");
  const waits = [];
  if (!final && speechMs < T.MIN_SPEECH_MS) waits.push(["short_speech", T.MIN_SPEECH_MS - speechMs]);
  if (sinceLineMs < T.LINE_GRACE_MS) waits.push(["grace_line", T.LINE_GRACE_MS - sinceLineMs]);
  if (sinceSentenceMs < T.RESUME_GRACE_MS) waits.push(["grace_resume", T.RESUME_GRACE_MS - sinceSentenceMs]);
  if (waits.length) {
    const [reason] = waits.reduce((a, b) => (b[1] > a[1] ? b : a));
    return { act: "wait", reason, retryMs: Math.max(1, Math.ceil(Math.max(...waits.map(x => x[1])))) };
  }
  return { act: "barge", reason: cmd ? "command" : "speech", retryMs: 0 };
}

/**
 * Open-mic barge-in while audio plays (§3 rule 2), the timing-free form (tests, the old callers): StartOfTurn, then
 * decideBarge on a finished turn.
 */
export function shouldBargeIn({ started, text, refs, dd }) {
  if (!started) return false;
  return decideBarge({ text, refs, dd, final: true }).act === "barge";
}

/** The mic energy a turn needs while we play: the larger of the absolute floor, leak x LEAK_X and room x FLOOR_X. */
export function energyNeed(leak, room) {
  const T = BARGE_TUNING;
  return Math.max(T.ENERGY_ABS_MIN, (leak || 0) * T.ENERGY_LEAK_X, (room || 0) * T.ENERGY_FLOOR_X);
}
