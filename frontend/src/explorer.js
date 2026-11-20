// Explorer lessons (course.json `track: "explorer"`, `unlock_after_missions: n`): extra Flight School lessons that open
// after the cadet has flown n missions to the end. The core lessons and the check ride never wait on them. Missions
// flown are counted on this device, per call sign, by mission id (one debrief per mission counts once).
const key = cs => "outpost-missions-flown:" + (cs || "cadet");

function read(storage, cs) {
  try { const a = JSON.parse((storage && storage.getItem(key(cs))) || "[]"); return Array.isArray(a) ? a : []; } catch (e) { return []; }
}

/** How many missions this cadet has flown to the end. */
export function missionsFlown(cs, storage = typeof localStorage !== "undefined" ? localStorage : null) {
  return read(storage, cs).length;
}

/** Count a finished mission (by id, so a re-shown debrief never counts twice). Returns the new total. */
export function markMissionFlown(id, cs, storage = typeof localStorage !== "undefined" ? localStorage : null) {
  const a = read(storage, cs);
  if (id && !a.includes(id)) { a.push(id); try { storage && storage.setItem(key(cs), JSON.stringify(a.slice(-50))); } catch (e) { /* private mode */ } }
  return a.length;
}

export const isExplorer = l => !!(l && l.track === "explorer");
/** Field School (course.json track "field", 0.5): a second track of geology lessons that opens after the check ride. */
export const isField = l => !!(l && l.track === "field");
/** A teacher-written Class lesson (track "class", docs/CURRICULUM.md): always open, never in the core count. */
export const isClass = l => !!(l && l.track === "class");
/** Not a core lesson: an explorer (bonus) lesson, a Field School lesson or a Class lesson. None ever blocks the check ride. */
export const isBonus = l => isExplorer(l) || isField(l) || isClass(l);
/** Is this lesson open to the cadet now? Core lessons always are. An explorer lesson with `unlock_after: "checkride"`
 *  opens once the cadet is qualified (novice playtest 2026-11-16 #22: Apollo's trace step in the first hour); so does
 *  every Field School lesson. */
export const unlocked = (l, flown, qualified = false) => !isBonus(l) || isClass(l) ||
  (l.unlock_after === "checkride" || isField(l) ? !!qualified : flown >= (l.unlock_after_missions || 1));
/** The explorer lessons that opened exactly at `flown` missions (the debrief offers these). */
export const newlyUnlocked = (lessons, flown) => (lessons || []).filter(l => isExplorer(l) && l.unlock_after !== "checkride" && (l.unlock_after_missions || 1) === flown);
/** Core lessons only: "Lesson n of 6" (the check ride, explorer and Field School lessons aren't in that count). */
export const coreLessons = lessons => (lessons || []).filter(l => !l.ride && !isBonus(l));
/** Field School lessons, in course order: "Field School 2 of 4". */
export const fieldLessons = lessons => (lessons || []).filter(isField);
