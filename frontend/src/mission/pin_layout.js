// [QA-61] The site picker's globe pins: where each dot, label and leader line goes, as plain numbers, plus a key that
// changes only when the picture does. mission/ui.js projects the five sites every frame (cheap) but touches the DOM
// only when this key changes, so a still globe costs no style, layout or SVG work.

/** Label rows are this far apart (px). */
export const PIN_ROW = 46;   // [QA-62] 28px labels with 44px hit areas, 2px apart

/**
 * @param {{id: string, x: number, y: number}[]} P  the sites facing the camera, projected to stage pixels
 * @param {number} H        the pin layer's height (px)
 * @param {string} selId    the selected site's id
 * @returns {{rows: {id: string, dot: [number, number], lab: [number, number], sel: boolean}[], lines: string, key: string}}
 */
export function pinLayout(P, H, selId) {
  if (!P.length) return { rows: [], lines: "", key: `-|${selId}` };
  const minX = Math.min(...P.map(o => o.x));
  const col = P.slice().sort((a, b) => a.y - b.y);
  const cy = col.reduce((t, o) => t + o.y, 0) / col.length;
  // label column left of the cluster, centred on it vertically, one row per site, clear of the voice bar (~150px)
  const y0 = Math.max(24, Math.min(cy - (col.length - 1) * PIN_ROW / 2, H - 150 - (col.length - 1) * PIN_ROW)), lx = minX - 64;
  const f = n => n.toFixed(1);
  const rows = col.map((o, k) => ({ id: o.id, dot: [+f(o.x), +f(o.y)], lab: [+f(lx), +f(y0 + k * PIN_ROW)], sel: o.id === selId }));
  const lines = rows.map(r => `<path d="M${f(r.lab[0] + 4)} ${f(r.lab[1])}H${f(r.lab[0] + 24)}L${f(r.dot[0])} ${f(r.dot[1])}"`
    + ` class="${r.sel ? "is-sel" : ""}" data-site="${r.id}"/>`).join("");
  // rounded to 0.1 px (what is drawn), so sub-pixel camera jitter doesn't count as a change
  const key = `${selId}|${rows.map(r => `${r.id}:${r.dot}:${r.lab}`).join(";")}`;
  return { rows, lines, key };
}
