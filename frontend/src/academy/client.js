// Academy API client + on-device progress (localStorage, no names: a kids' app). See backend/app/academy/routes.py.
async function j(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) { const e = new Error(url + " " + r.status); e.status = r.status; throw e; }
  return r.json();
}
const post = (url, body) => j(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

export const academyApi = {
  course: () => j("/api/academy/course"),
  /** {lesson_id, step, input:{text?|tap?|choice?}, misses, ride_id?} → {status, say, next_step?, badge?, hint?, state?, decisions} */
  attempt: body => post("/api/academy/attempt", body),
  ride: () => post("/api/academy/ride"),
  /** The kid asked for help: {lesson_id, step, rung (1 highlight, 2 label, 3 show), got?} → the ladder's next rung,
   *  no miss counted: {status: "help", rung, say, focus?, label?, eliminate?, cue?, answer?, phrase?, line_lon?, show?} */
  hint: body => post("/api/academy/hint", body),
};

const KEY = "atm-academy";
const blank = () => ({ badges: [], qualified: false });

export const progress = {
  load() {
    try { const p = JSON.parse(localStorage.getItem(KEY) || "null"); return p && Array.isArray(p.badges) ? { ...blank(), ...p } : blank(); }
    catch (e) { return blank(); }
  },
  save(p) { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (e) { /* private mode: progress lasts this visit */ } },
  reset() { try { localStorage.removeItem(KEY); } catch (e) { /* none */ } },
};
