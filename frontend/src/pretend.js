// "Pretend tech" (docs/ACCURACY_AUDIT.md): invented hardware is labelled, honestly and quietly. Active radiation
// shields, the greenhouse, the rim-to-floor cable are game things; real protection is mass (walls, water, regolith).
//
// The mark is a small amber sparkle right after the label. It is not a dashed box: it never changes a button's height,
// never crosses its border and never wraps by itself (it is glued to the label's last word). It carries the words for
// screen readers and a tooltip. The first time a kid picks something marked this way, the guide says why, once, and
// the caption shows it (PRETEND_EXPLAIN).
import { PRETEND_TECH, PRETEND_TECH_TIP, PRETEND_EXPLAIN } from "./story.js";
import { icon } from "./assets/icons.js";

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const SEEN_KEY = "outpost-pretend-explained";   // outpost-*: cleared by Settings → Reset

/** The mark alone (HTML). */
export const pretendMark = (tip = PRETEND_TECH_TIP) =>
  `<span class="pt-mark" role="img" aria-label="${esc(PRETEND_TECH)}: ${esc(tip)}" title="${esc(PRETEND_TECH)}. ${esc(tip)}">${icon("sparkle", { size: 14, strokeWidth: 2.2 })}</span>`;

/** A plain-text label with the mark glued to its last word (HTML): "Shields up" → "Shields <nobr>up✦</nobr>". */
export function pretendLabel(label, tip) {
  const t = String(label ?? "").trim(), i = t.lastIndexOf(" ");
  const head = i < 0 ? "" : t.slice(0, i + 1), last = i < 0 ? t : t.slice(i + 1);
  return `${esc(head)}<span class="pt-glue">${esc(last)}${pretendMark(tip)}</span>`;
}

/** The first pick of anything marked pretend: say why, once per cadet (Reset clears it). */
export function installPretendExplain({ speak = () => {}, caption = () => {}, store = typeof localStorage !== "undefined" ? localStorage : null, doc = document } = {}) {
  const seen = () => { try { return !!(store && store.getItem(SEEN_KEY)); } catch (e) { return true; } };
  doc.addEventListener("click", e => {
    const b = e.target && e.target.closest && e.target.closest("button, [role=option]");
    if (!b || !b.querySelector(".pt-mark") || seen()) return;
    try { store && store.setItem(SEEN_KEY, "1"); } catch (x) { /* private mode */ }
    // after the answer's own line has started, never over it
    setTimeout(() => { caption(PRETEND_EXPLAIN); speak(PRETEND_EXPLAIN); }, 1800);
  }, true);
}
