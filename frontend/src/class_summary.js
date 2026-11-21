// Class summary (D7, docs/BRAIN.md §12): every cadet on this computer on one printable page, counts only.
//
// Settings → For grown-ups → Class summary (behind the hold, and the teacher PIN when one is set). One row per cadet,
// in alphabetical order of call sign: never a ranking, nothing sorted by how a cadet is doing, no colours that grade.
// It reads what each cadet's own card in Progress reads: Flight School progress and practice counts (this computer's
// localStorage, prefs.js profiles), the concept reviews (brain_store.js), and the weekly counts and care notes
// (GET /api/brain/class, backend app/brain_counts.py). Never words, never a transcript.
//
// A roll-up across computers (each exports a counts-only file, the teacher imports them, nothing reaches Whissle) is a
// documented follow-up (docs/BRAIN.md §12), not built yet.
import { readCadets, summarize, printSheet } from "./progress.js";
import { brainOf, conceptRows, practice, totals } from "./brain.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || {}) : {};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  title: "Class summary",
  line: "Every cadet on this computer, last 30 days, in call-sign order. Counts only, never words. Not a ranking, and not for grading.",
  print: "Print",
  loading: "Loading the class…",
  none: "No cadets yet.",
  th: ["Cadet", "Lessons", "Steps answered", "First try", "Ideas remembered", "Days practised", "Filtered words (own / heard near)", "Kept private", "Safety notes"],
  newCadet: "New cadet",
  printedOn: d => `Outpost Luna class summary · ${d}`,
  notes: "Safety notes are listed by kind and day on each cadet's card in Progress.",
  roll: "One computer only. Several computers: print each one's summary.",
};

/** One cadet's row (pure). counts: GET /api/brain/class `cadets[id]` or undefined; meta: the course's concepts. */
export function row(cadet, lessons, brain, counts, meta) {
  const s = summarize(cadet, lessons || []), t = totals(practice(brain, lessons || []));
  const cr = conceptRows(brain, meta || {});
  const sf = (counts && counts.safety) || {}, bk = sf.by_kind;
  const own = bk ? ["profanity", "mask"].reduce((n, k) => n + (bk[k].typed || 0) + (bk[k].ptt || 0), 0) : null;
  const near = bk ? ["profanity", "mask"].reduce((n, k) => n + (bk[k].directed || 0) + (bk[k].room || 0), 0) : null;
  return { id: cadet.id, name: cadet.callsign || COPY.newCadet, lessons: `${s.core.done} of ${s.core.of}`, steps: t.steps,
    first: t.steps ? `${t.firstPct}%` : "–", ideas: cr.length ? `${cr.filter(r => r.remembered).length} of ${cr.length}` : "–",
    days: (brain && Array.isArray(brain.days) ? brain.days.length : 0), filtered: own == null ? (sf.filtered != null ? `${sf.filtered}` : "–") : `${own} / ${near}`,
    privacy: sf.privacy != null ? sf.privacy : "–", notes: sf.care || 0 };
}

/** The rows, alphabetical by call sign (a new cadet last), never by a count. Pure. */
export function rows({ cadets = [], lessons = [], brains = {}, counts = {}, meta = {} } = {}) {
  return cadets.map(c => row(c, lessons, brains[c.id], counts[c.id], meta))
    .sort((a, b) => (a.name === COPY.newCadet) - (b.name === COPY.newCadet) || a.name.localeCompare(b.name, undefined, { sensitivity: "base" }) || a.id.localeCompare(b.id));
}

/** The page (pure). */
export function sheetHtml(data = {}, date = "") {
  const rs = rows(data);
  if (!rs.length) return `<p class="set-help">${esc(COPY.none)}</p>`;
  const cell = v => `<td>${esc(v)}</td>`;
  return `<div class="pg-sheet cs-sheet">${date ? `<p class="pg-printed">${esc(COPY.printedOn(date))}</p><p class="pg-practice-only">${esc(COPY.line)}</p>` : ""}
    <div class="tbl pg-tbl"><table class="cs-table"><thead><tr>${COPY.th.map(h => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rs.map(r => `<tr data-cs="${esc(r.id)}"><th scope="row">${esc(r.name)}</th>${[r.lessons, r.steps, r.first, r.ideas, r.days, r.filtered, r.privacy, r.notes].map(cell).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="foot">${esc(COPY.notes)} ${esc(COPY.roll)}</p></div>`;
}

async function getJson(fetchFn, url) { try { const r = await fetchFn(url); return r && r.ok ? await r.json() : null; } catch (e) { return null; } }
/** Everything the page needs, read-only (GETs only). */
export async function loadData({ fetchFn, storage } = {}) {
  const cadets = readCadets(storage);
  const course = await getJson(fetchFn, "/api/academy/course");
  const ids = cadets.map(c => c.id).filter(id => /^p\d{1,2}$/.test(id));
  const cls = ids.length ? await getJson(fetchFn, `/api/brain/class?profiles=${ids.join(",")}`) : null;
  const cm = await getJson(fetchFn, "/api/academy/concepts");
  return { cadets, lessons: (course && course.lessons) || [], brains: Object.fromEntries(cadets.map(c => [c.id, brainOf(c.id, storage)])),
    counts: (cls && cls.cadets) || {}, meta: (cm && cm.concepts) || {} };
}

const section = {
  id: "classsummary", title: COPY.title, grownup: true, first: true,   // right after Progress
  html: () => `<div class="pg-zone"><div class="pg-bar"><p class="set-help">${esc(COPY.line)}</p>
      <button type="button" class="btn" data-cs-print>${esc(COPY.print)}</button></div>
    <div data-cs-view aria-live="polite"><p class="set-help" role="status">${esc(COPY.loading)}</p></div></div>`,
  bind(el, { fetchFn = typeof fetch === "function" ? fetch : null, storage = typeof localStorage !== "undefined" ? localStorage : null } = {}) {
    const view = el.querySelector("[data-cs-view]"), pr = el.querySelector("[data-cs-print]");
    if (!view || !fetchFn) return;
    let data = null, alive = true;
    loadData({ fetchFn, storage }).then(d => { if (!alive) return; data = d; view.innerHTML = sheetHtml(d); });
    if (pr) pr.onclick = () => {
      const date = new Date().toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
      printSheet(sheetHtml(data || { cadets: readCadets(storage) }, date));
    };
    return { destroy() { alive = false; } };
  },
};
if (typeof window !== "undefined") (O.settingsSections = O.settingsSections || []).push(section);
export default section;
