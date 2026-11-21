// node --test tests/  — open Moon data (src/media/moon_views.js, the optional moon_views pack): urls, licences, the
// "Real photo here" action on Apollo hardware, the Rock ages key, Columbia and sample facts in the tray.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as M from "../src/media/moon_views.js";
import { trayItem, MODEL_SHORT } from "../src/media/rocks_tray.js";
import { layerKeyHtml } from "../src/views_wire.js";

const READY = {
  state: "ready", credit: "Uses open Moon data",
  photos: [
    { id: "apollo11", site: "apollo11", file: "photos/apollo11.jpg", title: "Buzz Aldrin walks near Eagle", caption: "Aldrin by the leg.",
      nasa_id: "as11-40-5903", credit: "NASA", source: "https://images.nasa.gov/details/as11-40-5903", licence_class: "pd", alt: "Aldrin" },
    { id: "apollo12", site: "apollo12", file: "photos/apollo12.jpg", title: "Two spacecraft", licence_class: "by-nc", source: "https://x" },
    { id: "evil", site: "apollo14", file: "../secret.jpg", licence_class: "pd" },
  ],
  layers: [{ id: "rock_ages", file: "layers/rock_ages.png", title: "Rock ages", licence_class: "cc0", bounds: { west: -180, south: -90, east: 180, north: 90 },
    legend: [{ color: "#cde2fb", label: "Copernican" }, { color: "javascript:x", label: "bad" }], note: "Approximate.", credit: "USGS <Astrogeology>",
    source: "https://astrogeology.usgs.gov/x", opacity: 0.62 }],
  models: [{ id: "columbia", file: "models/columbia.glb", title: "Apollo 11 Command Module Columbia", story: "Came home.", licence_class: "cc0",
    credit: "Smithsonian NASM (CC0)", source: "https://airandspace.si.edu/x", size: [3.6, 3.1, 3.9] }],
  rock_facts: { 15016: { facts: ["It weighs 923.7 grams."], licence_class: "pd" } },
};

test("fileUrl: pack files only, one flat name with one dot", () => {
  assert.equal(M.fileUrl("photos/apollo11.jpg"), "/api/moon-views/file/photos/apollo11.jpg");
  assert.equal(M.fileUrl("models/columbia.glb"), "/api/moon-views/file/models/columbia.glb");
  for (const bad of ["../x.jpg", "photos/../x.jpg", "photos/a.b.jpg", "sky/x.jpg", "photos/x.svg", "photos/.x.jpg", null])
    assert.equal(M.fileUrl(bad), null, String(bad));
});

test("normalize: not ready -> null; entries without a licence we ship, or a bad path, are dropped", () => {
  assert.equal(M.normalize({ state: "missing" }), null);
  const v = M.normalize(READY);
  assert.deepEqual(v.photos.map(p => p.id), ["apollo11"], "by-nc and a path escape never reach the screen");
  assert.equal(v.layers[0].legend.length, 1, "a legend colour must be #rrggbb");
  assert.equal(v.models[0].url, "/api/moon-views/file/models/columbia.glb");
});

test("siteOf / photoFor / artifactActions: a real photo on every Apollo landing's hardware, not on S-IVB impacts", () => {
  const v = M.normalize(READY);
  assert.equal(M.siteOf({ id: "apollo11_lm_eagle" }), "apollo11");
  assert.equal(M.siteOf({ id: "apollo11_lrrr" }), "apollo11");
  assert.equal(M.siteOf({ id: "apollo14_sivb_impact" }), null);
  assert.equal(M.siteOf({ id: "luna2_impact" }), null);
  assert.equal(M.photoFor(v, { id: "apollo11_lm_eagle" }).nasa_id, "as11-40-5903");
  assert.equal(M.photoFor(v, { id: "apollo12_lm_intrepid" }), null, "its photo was dropped (licence)");
  let shown = null;
  const acts = M.artifactActions({ id: "apollo11_lm_eagle", mission: "Apollo 11" }, e => (shown = e), v);
  assert.deepEqual(acts.map(a => a.label), ["Real photo here"]);
  acts[0].onClick();
  assert.equal(shown.photo.src, "/api/moon-views/file/photos/apollo11.jpg");
  assert.match(shown.photo.credit, /^NASA \(as11-40-5903\) · Public domain$/);
  assert.equal(shown.eyebrow, "Real photo · Apollo 11");
  assert.deepEqual(M.artifactActions({ id: "apollo11_lm_eagle" }, () => {}, null), [], "no pack: the card is as before");
});

test("rock facts reach the tray; Columbia has a short name", () => {
  const v = M.normalize(READY);
  assert.deepEqual(M.factsFor("15016", v), ["It weighs 923.7 grams."]);
  assert.deepEqual(M.factsFor("99999", v), []);
  const it = trayItem({ id: "15016", name: "Seatbelt basalt", url: "/x.glb" }, "rock", M.factsFor("15016", v));
  assert.deepEqual(it.facts, ["It weighs 923.7 grams."]);
  assert.equal(MODEL_SHORT.columbia, "Columbia");
  assert.deepEqual(trayItem({ id: "15016" }, "rock").facts, [], "without the pack: no facts");
});

test("layerKeyHtml: the key, note and credit, escaped", () => {
  const h = layerKeyHtml(M.normalize(READY).layers[0]);
  assert.match(h, /background:#cde2fb[^>]*><\/i>Copernican/);
  assert.match(h, /USGS &lt;Astrogeology&gt;/);
  assert.match(h, /class="ml-note">Approximate\./);
});

test("main.js puts the photo action on hardware cards; the Moon only wires the layer (views_wire)", () => {
  const main = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
  assert.match(main, /actions: \[\.\.\.voiceActions\(a\), \.\.\.moonPhotoActions\(a, e => card\.show\(e\)\)/);
  assert.match(main, /if \(onMoon\) wireViews\(/);
});
