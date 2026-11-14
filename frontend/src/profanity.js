// Offline profanity mask for every piece of kid text the app shows (the voice bar's "Heard:", captions, the transcript,
// the answer card's "you asked"). The backstop behind Arc Tagger's safety tags (backend/app/safety.py mirrors this
// list): the tagger missed "shit shit oh" in the owner's room (docs/ARC_FEEDBACK.md), so the word list always runs.
// A masked word keeps its first letter: "shit" -> "s***". Pure, no DOM: tests/profanity.test.js.

/** Whole words (lower case, apostrophes dropped). Lunar names stay: "Hell" is a real crater, so "hell" is not here. */
const EXACT = new Set(("ass asses asshole assholes arse arsehole bastard bastards bitch bitches bitchy bollocks boner " +
  "bullshit cock cocks crap crappy cum cunt cunts damn damned damnit dammit dick dicks dickhead dildo douche douchebag " +
  "fag fags faggot faggots goddamn goddamnit horseshit jackass jerkoff motherfucker motherfuckers motherfucking nigga " +
  "niggas nigger niggers piss pissed pisses pissing porn prick pricks pussy pussies retard retarded scrotum shag slut " +
  "sluts smartass tit tits titty twat twats wank wanker wankers whore whores wtf stfu").split(" "));
/** Stems that are rude wherever they appear in a word ("motherfucking", "dipshit", "fuckin"). */
const STEMS = /(fuck|fuk|fck|shit|sh1t|wank|bitch|nigg)/;

const norm = w => w.toLowerCase().replace(/['’]/g, "");
/** Is this one word rude? */
export function isProfane(word) {
  const w = norm(String(word || ""));
  if (!w) return false;
  return EXACT.has(w) || STEMS.test(w);
}
/** Does the text contain a rude word? */
export function hasProfanity(text) {
  return (String(text || "").match(/[A-Za-z0-9'’]+/g) || []).some(isProfane);
}
/** The text with every rude word masked to its first letter plus "***". Everything else is untouched. */
export function maskProfanity(text) {
  return String(text ?? "").replace(/[A-Za-z0-9'’]+/g, w => (isProfane(w) ? w[0] + "***" : w));
}
/** Mask every word of the text (a turn Arc Tagger flagged as toxic or inappropriate: the words aren't for show). */
export function maskAll(text) {
  return String(text ?? "").replace(/[A-Za-z0-9'’]+/g, w => w[0] + "***");
}
