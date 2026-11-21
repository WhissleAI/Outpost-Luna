// [courses] Small open-data charts for a course Library (field_library.js `chart` items): a time series from a JSON or
// CSV file in the course pack, drawn as an accessible inline SVG (line or bar) with annotated bands ("Great Drought
// 1276–1299"). No chart library: the data are small (a few hundred to ~1,300 points) and the look is ours.
//
//   parseChart(text, name)        -> {series: [{label, points: [[x, y], ...]}], x_label?, y_label?, bands?} (throws)
//   chartSvg(chart, opts)         -> an SVG string: role="img", <title> + <desc> (the item's summary), axes, bands, a
//                                    legend for 2+ series with direct end labels, so identity is never colour alone
//   tableRows(chart, max)         -> a sampled table (the "Show the numbers" view)
//   nearestX(chart, x)            -> the values at the nearest x of every series (the hover read-out)
//   yearText(x)                   -> "AD 1276" / "500 BC"
//
// The backend checks the same two shapes when it validates a library (backend/app/course_library.py parse_chart).
// Colours are classes (.ch-s0…s3, field_library.css): the categorical order blue, orange, aqua, yellow, validated
// for the dark glass panel (dataviz validator: CVD worst adjacent ΔE 8.4, contrast >= 3:1).

export const CHART_FORMAT = "outpost-luna-chart";
const MAX_SERIES = 6, MAX_POINTS = 5000;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = v => (typeof v === "boolean" || v === null || v === "" ? NaN : Number(v));

/** A chart file's text -> the chart. Throws an Error with a plain reason on anything malformed. Pure. */
export function parseChart(text, name = "chart.json") {
  let out;
  if (/\.csv$/i.test(name)) {
    const rows = String(text || "").trim().split(/\r?\n/).filter(r => r.trim() && !r.startsWith("#")).map(r => r.split(","));
    if (rows.length < 3 || rows[0].length < 2) throw new Error("a chart CSV needs a header and at least two rows");
    const head = rows[0].map(h => h.trim());
    const series = head.slice(1).map(label => ({ label, points: [] }));
    for (const r of rows.slice(1)) {
      const x = num(r[0]);
      if (!Number.isFinite(x)) throw new Error(`x "${r[0]}" is not a number`);
      series.forEach((s, k) => {
        const c = (r[k + 1] || "").trim();
        if (c === "" || c === "NA") return;
        const y = num(c);
        if (!Number.isFinite(y)) throw new Error(`"${c}" is not a number`);
        s.points.push([x, y]);
      });
    }
    out = { series, x_label: head[0] };
  } else {
    const d = typeof text === "string" ? JSON.parse(text) : text;
    if (!d || d.format !== CHART_FORMAT || !Array.isArray(d.series)) throw new Error(`a chart JSON must be "${CHART_FORMAT}"`);
    for (const s of d.series)
      if (!s || !Array.isArray(s.points) || !s.points.every(p => Array.isArray(p) && p.length === 2 && Number.isFinite(num(p[0])) && Number.isFinite(num(p[1]))))
        throw new Error("every series needs points [[x, y], …] of numbers");
    out = { ...d, series: d.series.map(s => ({ ...s, points: s.points.map(p => [num(p[0]), num(p[1])]) })) };
  }
  if (out.series.length < 1 || out.series.length > MAX_SERIES) throw new Error("a chart has 1 to 6 series");
  for (const s of out.series) {
    if (!s.label) throw new Error("every series needs a label");
    if (s.points.length < 2 || s.points.length > MAX_POINTS) throw new Error(`series "${s.label}": 2 to ${MAX_POINTS} points`);
    for (let i = 1; i < s.points.length; i++) if (!(s.points[i][0] > s.points[i - 1][0])) throw new Error(`series "${s.label}": x must increase`);
  }
  return out;
}

/** "AD 1276", "500 BC" (x as a calendar year, 0 = 1 BC is never used by the packs). Pure. */
export const yearText = x => (x < 0 ? `${Math.round(-x)} BC` : `AD ${Math.max(1, Math.round(x))}`);   // there is no year 0

/** A series' colour slot: context series (`faint`) are neutral grey (-1) and take no slot; the others count 0, 1, 2… Pure. */
export function colourIndex(series, i) {
  if (series[i] && series[i].faint) return -1;
  return series.slice(0, i).filter(s => !s.faint).length;
}

/** Round tick steps (1, 2, 5 × 10^n) covering [a, b] with about n ticks. Pure. */
export function ticks(a, b, n = 5) {
  if (!(b > a)) return [a];
  const raw = (b - a) / Math.max(1, n), p = 10 ** Math.floor(Math.log10(raw)), m = raw / p;
  const step = (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
  const out = [];
  for (let v = Math.ceil(a / step) * step; v <= b + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

function extent(chart, bands) {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const s of chart.series) for (const [x, y] of s.points) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  if (y0 > 0 && chart.type === "bar") y0 = 0;   // bars start at zero
  if (y0 === y1) { y0 -= 1; y1 += 1; }
  const pad = (y1 - y0) * 0.06;
  return { x0, x1, y0: y0 === 0 ? 0 : y0 - pad, y1: y1 + pad, bands: (bands || []).filter(b => b.to > x0 && b.from < x1) };
}

const fmtX = (chart, v) => (chart.x_format === "year" ? yearText(v) : String(Math.round(v * 100) / 100));
const fmtY = v => (Math.abs(v) >= 100 ? String(Math.round(v)) : String(Math.round(v * 100) / 100));

/**
 * The chart as an SVG string. opts: {width, height, type: "line" | "bar", bands: [{from, to, label}], x_label, y_label,
 * title, summary, x_format: "year" | "number", zero: true (a 0 line, e.g. wetter / drier)}. Pure (tested).
 */
export function chartSvg(chart, opts = {}) {
  const c = { ...chart, ...opts, type: opts.type || chart.type || "line", x_format: opts.x_format || chart.x_format || "number" };
  const W = opts.width || 640, H = opts.height || 300, many = c.series.filter(s => !s.faint).length > 1;
  const L = 52, R = many ? 96 : 16, T = 22, B = 40;
  const e = extent(c, opts.bands || chart.bands), pw = W - L - R, ph = H - T - B;
  const bar = c.type === "bar";
  const bw = bar ? pw / Math.max(1, c.series[0].points.length) : 0;
  const sx = x => L + (bar ? bw / 2 : 0) + (x - e.x0) / ((e.x1 - e.x0) || 1) * (pw - bw);
  const sy = y => T + (1 - (y - e.y0) / (e.y1 - e.y0)) * ph;
  const id = "ch" + Math.abs([...String(c.title || "")].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) | 0, 7)).toString(36);
  const out = [`<svg class="chart" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-labelledby="${id}-t ${id}-d" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">`,
    `<title id="${id}-t">${esc(c.title || "Chart")}</title><desc id="${id}-d">${esc(c.summary || "")}</desc>`];
  // bands first (behind the data), each named on the chart itself
  for (const b of e.bands) {
    const a = Math.max(L, sx(b.from) - bw / 2), z = Math.min(L + pw, sx(b.to) + bw / 2);
    out.push(`<g class="ch-band"><rect x="${a.toFixed(1)}" y="${T}" width="${Math.max(2, z - a).toFixed(1)}" height="${ph}"/>`,
      `<text x="${((a + z) / 2).toFixed(1)}" y="${T - 6}" text-anchor="middle">${esc(b.label)}</text></g>`);
  }
  // grid + axes (recessive)
  const yt = ticks(e.y0, e.y1, 4), xt = ticks(e.x0, e.x1, Math.max(3, Math.round(pw / 110)));
  out.push(`<g class="ch-grid">${yt.map(v => `<line x1="${L}" x2="${L + pw}" y1="${sy(v).toFixed(1)}" y2="${sy(v).toFixed(1)}"/>`).join("")}</g>`);
  if (opts.zero && e.y0 < 0 && e.y1 > 0) out.push(`<line class="ch-zero" x1="${L}" x2="${L + pw}" y1="${sy(0).toFixed(1)}" y2="${sy(0).toFixed(1)}"/>`);
  out.push(`<g class="ch-axis">${yt.map(v => `<text x="${L - 6}" y="${(sy(v) + 4).toFixed(1)}" text-anchor="end">${esc(fmtY(v))}</text>`).join("")}`,
    `${xt.map(v => `<text x="${sx(v).toFixed(1)}" y="${T + ph + 16}" text-anchor="middle">${esc(fmtX(c, v))}</text>`).join("")}`,
    `<line x1="${L}" x2="${L + pw}" y1="${T + ph}" y2="${T + ph}"/></g>`);
  if (c.x_label) out.push(`<text class="ch-label" x="${L + pw / 2}" y="${H - 4}" text-anchor="middle">${esc(c.x_label)}</text>`);
  if (c.y_label) out.push(`<text class="ch-label" transform="translate(12 ${T + ph / 2}) rotate(-90)" text-anchor="middle">${esc(c.y_label)}</text>`);
  // the data
  const ends = [];
  c.series.forEach((s, i) => {
    const k = colourIndex(c.series, i), cls = k < 0 ? "ch-faint" : `ch-s${k}`;
    if (bar) {
      const g = Math.max(0.5, Math.min(2, bw * 0.15));   // the 2px surface gap between bars, narrower on dense charts
      out.push(`<g class="${cls} ch-bars">${s.points.map(([x, y]) => {
        const y0 = sy(Math.max(e.y0, Math.min(0, y))), y1 = sy(Math.max(0, y)), h = Math.max(y0 - y1, y ? 1 : 0);
        return `<rect x="${(sx(x) - bw / 2 + g / 2).toFixed(1)}" y="${y1.toFixed(1)}" width="${Math.max(0.5, bw - g).toFixed(1)}" height="${h.toFixed(1)}" rx="${bw > 8 ? 2 : 0}"/>`;
      }).join("")}</g>`);
    } else {
      const d = s.points.map(([x, y], i) => `${i ? "L" : "M"}${sx(x).toFixed(1)} ${sy(y).toFixed(1)}`).join("");
      out.push(`<path class="${cls} ch-line" d="${d}"/>`);
    }
    if (many && k >= 0) {   // direct end label: identity by name, not colour alone (context series: the legend names it)
      const [x, y] = s.points[s.points.length - 1];
      ends.push({ k, x: sx(x) + 6, y: sy(y) + 4, text: s.short || s.label });
    }
  });
  // end labels never overlap: in y order, each at least 13 px below the one above
  ends.sort((a, b) => a.y - b.y).forEach((l, i, all) => { if (i && l.y - all[i - 1].y < 13) l.y = all[i - 1].y + 13; });
  ends.forEach(l => out.push(`<text class="ch-end ch-t${l.k}" x="${l.x.toFixed(1)}" y="${l.y.toFixed(1)}">${esc(l.text)}</text>`));
  out.push(`<line class="ch-cross" x1="0" x2="0" y1="${T}" y2="${T + ph}" visibility="hidden"/>`, "</svg>");
  return out.join("");
}

/** The plot's x for a pointer at fraction f (0..1) of the SVG width, with the same layout as chartSvg. Pure. */
export function xAt(chart, f, opts = {}) {
  const W = opts.width || 640, L = 52, R = chart.series.filter(s => !s.faint).length > 1 ? 96 : 16;
  const e = extent(chart, []), px = Math.max(0, Math.min(1, (f * W - L) / (W - L - R)));
  return e.x0 + px * (e.x1 - e.x0);
}

/** Every series' value at the x nearest to `x`: [{label, x, y}] (the hover read-out). Pure. */
export function nearestX(chart, x) {
  return chart.series.map(s => {
    let best = s.points[0];
    for (const p of s.points) if (Math.abs(p[0] - x) < Math.abs(best[0] - x)) best = p;
    return { label: s.label, x: best[0], y: best[1] };
  });
}

/** Up to `max` evenly spaced rows [x, y1, y2, …] for the table view (every row when the chart is small). Pure. */
export function tableRows(chart, max = 40) {
  const xs = [...new Set(chart.series.flatMap(s => s.points.map(p => p[0])))].sort((a, b) => a - b);
  const pick = xs.length <= max ? xs : Array.from({ length: max }, (_, i) => xs[Math.round(i * (xs.length - 1) / (max - 1))]);
  const at = chart.series.map(s => new Map(s.points));
  return pick.map(x => [x, ...at.map(m => (m.has(x) ? m.get(x) : null))]);
}

/** The table view as HTML (a <table> with a caption), sampled to `max` rows. Pure. */
export function tableHtml(chart, opts = {}) {
  const rows = tableRows(chart, opts.max || 40), fx = v => fmtX({ x_format: opts.x_format || chart.x_format }, v);
  return `<table class="ch-table"><caption>${esc(opts.caption || "The numbers")}${rows.length < tableRows(chart, 1e9).length ? " (a sample)" : ""}</caption>
    <thead><tr><th scope="col">${esc(opts.x_label || chart.x_label || "x")}</th>${chart.series.map(s => `<th scope="col">${esc(s.label)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map(r => `<tr><th scope="row">${esc(fx(r[0]))}</th>${r.slice(1).map(v => `<td>${v === null ? "–" : esc(fmtY(v))}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
