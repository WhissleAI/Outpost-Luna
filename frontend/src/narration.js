// The narration rule: what a line SAYS can differ from what the screen SHOWS. "mSv" stays "mSv" on screen, but the voice
// says "millisieverts" (a TTS engine reads the unit as the letters "M S V", which a kid can't map to anything, and the
// open mic then hears "m s v" coming back, which no echo check matched).
// Mirrors backend/app/narration.py (the server applies it before every engine: macOS `say`, Windows WinRT / SAPI,
// Deepgram); this copy is for the browser-voice fallback (floor.js speakSynth) and the echo references (barge.js).
// Keep the two tables in step: tests/narration.test.js and backend/tests/test_narration.py check the same cases.

const RULES = [
  [/\b(\d+(?:\.\d+)?)\s*mSv\s*\/\s*h\b/g, "$1 millisieverts an hour"],
  [/\bmSv\s*\/\s*h\b/g, "millisieverts an hour"],
  [/\bgame-mSv\b/g, "game millisieverts"],
  [/\b([Aa])n\s+mSv\b/g, "$1 millisievert"],
  [/\b([Oo]ne|1)\s+mSv\b/g, "$1 millisievert"],
  [/\bmSv\b/g, "millisieverts"],
];

/** The spoken form of a line (unchanged when no rule applies). */
export function spokenForm(text) {
  let t = String(text == null ? "" : text);
  for (const [re, to] of RULES) t = t.replace(re, to);
  return t;
}
