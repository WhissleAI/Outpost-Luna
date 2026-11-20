// The campaign on the mission hub (docs/GAMEPLAY.md §16, backend/app/mission/campaign.py): Mission 1, then five
// missions at other real sites, each unlocked by winning the one before. Pure helpers (tests/campaign.test.js); the
// hub, the briefing, the progress strip and the debrief in mission/ui.js, cabin.js and objective.js use them.
// Wins are kept on this device, per call sign, by campaign mission id (outpost-campaign:<call sign>).
import { CAMPAIGN } from "../story.js";

/** The hub's list when the server has none (the sample mode): Mission 1 only, as before the campaign. */
export const FALLBACK = [{ n: 1, id: "first_light", title: "First light", site: null, line: "", danger: "", say: "", goals: [] }];

const key = cs => "outpost-campaign:" + (cs || "cadet");
const store = () => { try { return localStorage; } catch (e) { return null; } };

/** The campaign missions this call sign has won (ids). */
export function wonIds(cs, storage = store()) {
  try { const a = JSON.parse((storage && storage.getItem(key(cs))) || "[]"); return Array.isArray(a) ? a.filter(x => typeof x === "string") : []; } catch (e) { return []; }
}

/** A won mission (survived): remembered once. Returns the ids won. */
export function markWon(id, cs, storage = store()) {
  const a = wonIds(cs, storage);
  if (id && !a.includes(id)) { a.push(id); try { storage && storage.setItem(key(cs), JSON.stringify(a)); } catch (e) { /* private mode */ } }
  return a;
}

/** How many missions are open: Mission 1, and each one after a won mission, in order. */
export function unlockedCount(list, won) {
  const w = new Set(won || []);
  let n = 1;
  while (n < (list || []).length && w.has(list[n - 1].id)) n++;
  return Math.max(1, Math.min(n, (list || []).length || 1));
}

/** The mission the hub offers first: the first open one not won yet, else the last open one. */
export function nextUp(list, won) {
  const open = (list || FALLBACK).slice(0, unlockedCount(list, won));
  const w = new Set(won || []);
  return open.find(m => !w.has(m.id)) || open[open.length - 1];
}

/** A campaign mission (past Mission 1)? Mission 1 keeps its own hub, briefing and checklist. */
export const isCampaign = m => !!(m && m.n > 1);

/** One goal on the progress strip: {name, val, of, p, met, title}. "keep" goals show OK or Missed. */
export function goalBit(g) {
  if (!g) return null;
  if (g.kind === "keep") {
    const ok = !!g.met;
    return { name: g.short, val: ok ? CAMPAIGN.keepOk : CAMPAIGN.keepMissed, of: "", p: ok ? 1 : 0, met: ok, title: `${g.label}: ${ok ? CAMPAIGN.keepOk : CAMPAIGN.keepMissed}` };
  }
  const got = Math.round(+g.got || 0), of = Math.round(+g.goal || 1);
  return { name: g.short, val: got, of, p: Math.max(0, Math.min(1, got / of)), met: !!g.met, title: `${g.label}: ${got} of ${of}` };
}

/** The debrief's checklist lines for the mission's two goals. */
export const goalChecks = goals => (goals || []).map(g => ({ ok: !!g.met, text: g.label }));

/** The briefing's three cards for a campaign mission (Mission 1 keeps BRIEFING.cards). */
export function briefCards(m) {
  return [
    { k: "goal", icon: "shelter", label: CAMPAIGN.goal, text: (m.goals && m.goals[0]) || "" },
    { k: "danger", icon: "storm", label: CAMPAIGN.danger, text: m.danger || "" },
    { k: "bonus", icon: "ice", label: CAMPAIGN.bonus, text: (m.goals && m.goals[1]) || "" },
  ];
}
