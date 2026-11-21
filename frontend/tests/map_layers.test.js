// node --test tests/  — [open data] the Library's Maps (src/map_layers.js, docs/OPEN_DATA.md): GET /api/course/library
// `layers` -> the picker list, the panel's legend and credit; the photo always first; nothing hot-linked; the globe's
// setBaseMap is opt-in and the photo comes back when the cadet leaves the Library.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as M from "../src/map_layers.js";

const RAW = {
  course: "moon", shelves: [],
  layers: [
    { id: "age", title: "Age", url: "/api/courses/moon/media/moon_age.jpg", say: "Colours show how old the ground is.",
      credit: "USGS Astrogeology Science Center", licence: "CC0", source: { title: "Unified Geologic Map", url: "https://astrogeology.usgs.gov/x" },
      legend: [{ color: "#7848a0", label: "Pre-Nectarian", note: "oldest" }, { color: "purple", label: "bad colour" }, { color: "#ffecaa", label: "Copernican" }] },
    { id: "height", title: "Height", url: "/api/courses/moon/media/moon_height.jpg", say: "Purple low, red high.", credit: "USGS", licence: "Public domain",
      source_url: "https://astrogeology.usgs.gov/y", legend: [] },
    { id: "hot", title: "Hot-linked", url: "https://example.com/x.jpg" },
    { id: "photo", title: "Fake photo", url: "/api/courses/moon/media/x.jpg" },
  ],
};

test("normalizeLayers: the photo first, then the course's own layers; hot links and bad colours dropped", () => {
  const L = M.normalizeLayers(RAW);
  assert.deepEqual(L.map(l => l.id), ["photo", "age", "height"]);
  assert.equal(L[0], M.PHOTO);
  assert.deepEqual(L[1].legend.map(x => x.label), ["Pre-Nectarian", "Copernican"]);
  assert.equal(L[1].credit, "USGS Astrogeology Science Center · CC0");
  assert.equal(L[2].source.url, "https://astrogeology.usgs.gov/y", "a credit's source_url stands in for a missing source");
  assert.deepEqual(M.normalizeLayers({ shelves: [] }), [], "no layers: no button");
  assert.deepEqual(M.normalizeLayers(null), []);
});

test("panelHtml: tabs, the legend and the credit of the layer that is on; the photo explains itself", () => {
  const L = M.normalizeLayers(RAW);
  const age = M.panelHtml(L, "age");
  assert.match(age, /role="radio" data-layer="age" aria-checked="true"/);
  assert.match(age, /role="radio" data-layer="photo" aria-checked="false"/);
  assert.match(age, /background:#7848a0/);
  assert.match(age, /Pre-Nectarian<\/b><small>oldest<\/small>/);
  assert.match(age, /USGS Astrogeology Science Center · CC0 · <a href="https:\/\/astrogeology.usgs.gov\/x"/);
  const photo = M.panelHtml(L, "photo", "Moon");
  assert.match(photo, /The Moon as a camera sees it/);
  assert.doesNotMatch(photo, /ml-legend/);
  assert.match(M.panelHtml(L, "nope"), /data-layer="photo" aria-checked="true"/, "an unknown id falls back to the photo");
  assert.doesNotMatch(M.panelHtml([M.PHOTO, { ...L[1], say: "<b>x</b>" }], "age"), /<b>x<\/b>/, "escaped");
});

test("wiring: main.js installs Maps on every course; globe.setBaseMap restores the body's own map", () => {
  const main = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
  assert.match(main, /installMapLayers\(\{ globe, hudRow: \$\("tourBtn"\)\.parentElement/);
  const globe = readFileSync(new URL("../src/globe.js", import.meta.url), "utf8");
  assert.match(globe, /function setBaseMap\(url\)/);
  assert.match(globe, /moon\.material\.map = tex;/, "null puts the body's own map back");
  const src = readFileSync(new URL("../src/map_layers.js", import.meta.url), "utf8");
  assert.match(src, /document\.body\.dataset\.mode !== "cadet"\) \{ close\(\); if \(on !== "photo"\) pick\("photo"\)/,
    "leaving the Library brings the photo back (lessons and missions are written for it)");
});
