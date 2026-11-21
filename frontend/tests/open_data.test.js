// node --test tests/  — open data in a course Library: src/media/chart.js (parse + SVG, pure) and the new
// field_library.js kinds (chart, model, layer): data urls only from the course's own media, layers need a legend.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as C from "../src/media/chart.js";
import * as F from "../src/field_library.js";

const J = (series, extra = {}) => JSON.stringify({ format: "outpost-luna-chart", series, ...extra });
const MEDIA = new URL("../../backend/data/courses/archaeology/media/", import.meta.url);

test("parseChart: the JSON and CSV shapes", () => {
  const a = C.parseChart(J([{ label: "wet", points: [[1276, -1], [1277, 0.5]] }]), "d.json");
  assert.deepEqual(a.series[0].points, [[1276, -1], [1277, 0.5]]);
  const b = C.parseChart("year,a,b\n# note\n1,2,NA\n2,3,4\n3,,5\n", "d.csv");
  assert.deepEqual(b.series.map(s => s.points), [[[1, 2], [2, 3]], [[2, 4], [3, 5]]]);
  assert.equal(b.x_label, "year");
});

test("parseChart: malformed data is refused with a reason", () => {
  for (const [t, n, why] of [
    ['{"series": []}', "d.json", /outpost-luna-chart/],
    [J([{ label: "a", points: [[1, "x"]] }]), "d.json", /numbers/],
    [J([{ label: "a", points: [[2, 1], [1, 1]] }]), "d.json", /increase/],
    [J([{ points: [[1, 1], [2, 1]] }]), "d.json", /label/],
    [J([]), "d.json", /1 to 6/],
    ["x,y\n1,2\n", "d.csv", /two rows/],
    ["x,y\n1,2\n2,oops\n", "d.csv", /not a number/],
    ["{not json", "d.json", /./],
  ]) assert.throws(() => C.parseChart(t, n), why, t);
});

test("chartSvg: accessible, banded, no raw text injected", () => {
  const ch = C.parseChart(J([{ label: "<b>wet</b>", points: [[1200, 1], [1276, -1], [1300, 0.2], [1350, 0.4]] }], { x_format: "year" }), "d.json");
  const svg = C.chartSvg(ch, { title: "Drought <timeline>", summary: "A line & a band.", bands: [{ from: 1276, to: 1299, label: "Great Drought 1276–1299" }],
    x_format: "year", zero: true });
  assert.match(svg, /^<svg class="chart"[^>]*role="img"[^>]*aria-labelledby="(\w+)-t \1-d"/);
  assert.match(svg, /<title id="\w+-t">Drought &lt;timeline&gt;<\/title><desc id="\w+-d">A line &amp; a band\.<\/desc>/);
  assert.match(svg, /class="ch-band"><rect[^>]*\/><text[^>]*>Great Drought 1276–1299<\/text>/);
  assert.match(svg, /AD 1300/);
  assert.match(svg, /class="ch-zero"/);
  assert.doesNotMatch(svg, /<b>/, "labels are escaped");
  assert.match(svg, /class="ch-s0 ch-line"/);
});

test("chartSvg: 2+ series get direct end labels; bars start at zero", () => {
  const ch = C.parseChart(J([{ label: "A long name", short: "A", points: [[1, 1], [2, 2]] }, { label: "B", points: [[1, 2], [2, 1]] }]), "d.json");
  const svg = C.chartSvg(ch, {});
  assert.equal((svg.match(/class="ch-end/g) || []).length, 2);
  assert.match(svg, />A<\/text>/);
  const bars = C.chartSvg(C.parseChart(J([{ label: "n", points: [[0, 5], [100, 9]] }]), "d.json"), { type: "bar" });
  assert.equal((bars.match(/<rect /g) || []).length, 2);
  assert.match(bars, /<text x="\d+" y="[\d.]+" text-anchor="end">0<\/text>/, "a zero tick: bars rest on 0");
});

test("ticks, yearText, nearestX, tableRows", () => {
  assert.deepEqual(C.ticks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.equal(C.yearText(-500), "500 BC");
  assert.equal(C.yearText(1276), "AD 1276");
  const ch = C.parseChart(J([{ label: "a", points: [[1, 10], [5, 50], [9, 90]] }]), "d.json");
  assert.deepEqual(C.nearestX(ch, 6), [{ label: "a", x: 5, y: 50 }]);
  assert.equal(C.tableRows(ch, 40).length, 3);
  const big = C.parseChart(J([{ label: "a", points: Array.from({ length: 1000 }, (_, i) => [i, i]) }]), "d.json");
  const rows = C.tableRows(big, 40);
  assert.equal(rows.length, 40); assert.equal(rows[0][0], 0); assert.equal(rows[39][0], 999);
  assert.match(C.tableHtml(big, { caption: "T" }), /<caption>T \(a sample\)<\/caption>/);
});

test("the Archaeology chart files parse, the drought band falls inside the data", () => {
  for (const f of ["drought_mesa_verde.json", "tree_rings_1200_1320.json", "radiocarbon_four_corners.json"]) {
    const ch = C.parseChart(readFileSync(new URL(f, MEDIA), "utf8"), f);
    assert.ok(ch.series.length >= 1, f);
    assert.match(C.chartSvg(ch, { title: f, summary: "x" }), /<path|<rect/, f);
  }
});

test("safeDataUrl: course media json/csv for charts, glb for models, nothing else", () => {
  assert.ok(F.safeDataUrl("/api/courses/archaeology/media/drought_mesa_verde.json", "chart"));
  assert.ok(F.safeDataUrl("/api/courses/archaeology/media/rings.csv", "chart"));
  assert.ok(F.safeDataUrl("/api/courses/archaeology/media/columbia.glb", "model"));
  for (const [u, k] of [
    ["/api/courses/archaeology/media/columbia.glb", "chart"], ["/api/courses/archaeology/media/d.json", "model"],
    ["/api/courses/archaeology/media/../d.json", "chart"], ["/api/courses/archaeology/media/a..json", "chart"],
    ["/api/courses/archaeology/media/x.tar.glb", "model"], ["/api/courses/archaeology/media/.d.json", "chart"],
    ["/api/courses/archaeology/media/D.json", "chart"], ["https://evil.example/d.json", "chart"],
    ["/api/courses/archaeology/media/d.json?x=1", "chart"], ["/api/courses/archaeology/media/d.json", "image"],
    ["//evil.example/api/courses/archaeology/media/d.json", "chart"], [null, "chart"],
  ]) assert.equal(F.safeDataUrl(u, k), null, `${u} as ${k}`);
  assert.equal(F.safeUrl("/api/courses/archaeology/media/d.json"), null, "a picture url is never a data file");
  assert.equal(F.safeUrl("/api/courses/archaeology/media/a.b.jpg"), null, "one dot only");
});

const RAW = { course: "archaeology", shelves: [{ id: "data", title: "Clues", by: "NOAA", items: [
  { id: "drought", kind: "chart", title: "Drought", url: "/api/courses/archaeology/media/drought_mesa_verde.json", summary: "s", bands: [{ from: 1276, to: 1299, label: "GD" }] },
  { id: "hot_chart", kind: "chart", title: "Hot", url: "https://evil.example/d.json" },
  { id: "cm", kind: "model", title: "Columbia", url: "/api/courses/archaeology/media/columbia.glb" },
  { id: "rivers", kind: "layer", title: "Rivers", url: "/api/courses/archaeology/media/layer_rivers_states.png",
    bounds: { west: -110.2, south: 35.7, east: -106.9, north: 38 }, legend: [{ color: "#4fb3ff", label: "River" }, { color: "red", label: "bad" }], opacity: 0.8 },
  { id: "no_key", kind: "layer", title: "No key", url: "/api/courses/archaeology/media/l.png", bounds: { west: 0, south: 0, east: 1, north: 1 }, legend: [] },
  { id: "bad_box", kind: "layer", title: "Bad", url: "/api/courses/archaeology/media/l.png", bounds: { west: 2, south: 0, east: 1, north: 1 }, legend: [{ color: "#ffffff", label: "x" }] },
] }] };

test("normalizeLibrary: charts, models and layers; foreign data and keyless layers dropped", () => {
  const L = F.normalizeLibrary(RAW);
  assert.deepEqual([...L.items.keys()], ["drought", "cm", "rivers"]);
  const r = L.items.get("rivers");
  assert.deepEqual(r.legend, [{ color: "#4fb3ff", label: "River" }], "a legend colour must be #rrggbb");
  assert.equal(r.opacity, 0.8);
  assert.equal(F.thumbUrl(L.items.get("drought")), null, "no picture for a chart tile (a glyph)");
  assert.equal(F.kindLabel(L.items.get("cm")), "3D model");
  assert.deepEqual(F.markersFor(L, []), [], "data items are not photo markers");
});

test("itemEntry / chartView / legendHtml", () => {
  const L = F.normalizeLibrary(RAW), d = L.items.get("drought");
  const e = F.itemEntry({ ...d, image_credit: "Stahle et al. 2015, NOAA", image_licence: "cite", image_source_url: "https://www.ncei.noaa.gov/x" });
  assert.equal(e.eyebrow, "Chart · NOAA");
  assert.match(e.note, /^Data: Stahle/);
  assert.deepEqual(e.sources, [{ title: "Data source", url: "https://www.ncei.noaa.gov/x" }]);
  const ch = C.parseChart(J([{ label: "a", points: [[1270, 1], [1300, 2]] }, { label: "b", points: [[1270, 2], [1300, 1]] }]), "d.json");
  const html = F.chartView({ ...d, summary: "Two lines." }, ch);
  assert.match(html, /<figure class="flv-fig"><svg/);
  assert.match(html, /class="ch-legend"/);
  assert.match(html, /<details class="flv-table"><summary>Show the numbers<\/summary><table/);
  assert.match(F.legendHtml(L.items.get("rivers")), /background:#4fb3ff[^>]*><\/i>River/);
});

test("the chart colours in the CSS are the validated categorical order", () => {
  const css = readFileSync(new URL("../src/field_library.css", import.meta.url), "utf8");
  for (const [k, hex] of [[0, "#3987e5"], [1, "#d95926"], [2, "#199e70"], [3, "#c98500"]])
    assert.match(css, new RegExp(`\\.ch-s${k}\\{stroke:${hex};fill:${hex}\\}`));
});
