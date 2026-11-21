// node --test tests/  — [courses] a non-Moon course's Library (src/field_library.js): GET /api/course/library ->
// shelves, markers, place cards, chips. Pure parts only (no DOM, no WebGL), plus source checks that the Moon is untouched.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as F from "../src/field_library.js";

const RAW = {
  course: "archaeology", title: "Field Library", intro: "Real NASA views.", home: { lat: 37, lon: -108.6, dist: 1.08 },
  tour: { title: "Site tour", intro: "Six places.", stops: ["mesa_verde", "hovenweep"] }, featured: ["mv_landsat", "nope", "v_lidar"],
  chips: [{ label: "Tour the sites", do: "tour" }, { label: "Mesa Verde from orbit", do: "item:mv_landsat" }, { label: "bad", do: "rm -rf" }],
  overlays: [{ file: "region.jpg", url: "/api/courses/archaeology/media/four_corners_region.jpg", bounds: { west: -110.2, south: 35.7, east: -106.9, north: 38 } },
             { file: "x.jpg", url: "https://evil.example/x.jpg", bounds: { west: 0, south: 0, east: 1, north: 1 } }],
  shelves: [
    { id: "orbit", title: "Earth from orbit", by: "NASA", items: [
      { id: "mv_landsat", kind: "image", title: "Mesa Verde from Landsat 8", caption: "15 August 2016.", place: "mesa_verde", lat: 37.18, lon: -108.49,
        url: "/api/courses/archaeology/media/four_corners.jpg", image_credit: "NASA Earth Observatory", image_licence: "Public domain (US Government work)",
        image_alt: "Satellite view", image_source_url: "https://science.nasa.gov/x", source: { title: "NASA media", url: "https://www.nasa.gov/m" } },
      { id: "iss_san_juan", kind: "image", title: "Astronaut photo: the San Juan River", lat: 36.79, lon: -109.18,
        url: "/api/courses/archaeology/media/iss_pastora_san_juan.jpg", image_credit: "NASA", image_licence: "Public domain" },
      { id: "hot", kind: "image", title: "Hot-linked", lat: 1, lon: 1, url: "https://images-assets.nasa.gov/x.jpg" },
    ] },
    { id: "sites", title: "Mesa Verde sites", by: "National Park Service", items: [
      { id: "cliff_palace", kind: "image", title: "Cliff Palace", place: "mesa_verde", url: "/api/courses/archaeology/media/photo_cliff_palace.jpg", image_credit: "NPS" },
    ] },
    { id: "watch", title: "Watch", by: "NASA", items: [
      { id: "v_lidar", kind: "video", video: "arch_lidar_space", title: "Lidar", duration_s: 223, poster: "/api/video/arch_lidar_space/poster" },
      { id: "junk", kind: "song" },
    ] },
    { id: "empty", title: "Nothing", items: [] },
  ],
};
const PLACES = [
  { id: "mesa_verde", name: "Mesa Verde National Park", lat: 37.18, lon: -108.49, fact: "Nearly 5,000 sites.", source: "https://www.nps.gov/meve/" },
  { id: "hovenweep", name: "Hovenweep National Monument", lat: 37.38, lon: -109.07, fact: "Stone towers." },
  { id: "lm", name: "Eagle", kind: "artifact", lat: 0.67, lon: 23.47 },
];

test("normalizeLibrary: shelves and items, only our own media urls, unknown kinds and empty shelves dropped", () => {
  const L = F.normalizeLibrary(RAW);
  assert.deepEqual(L.shelves.map(s => s.id), ["orbit", "sites", "watch"]);
  assert.equal(L.items.get("hot").url, null, "a hot-linked picture is never drawn (CSP, school networks)");
  assert.equal(L.items.get("junk"), undefined);
  assert.equal(L.items.get("v_lidar").poster, "/api/video/arch_lidar_space/poster");
  assert.equal(L.overlays.length, 1, "an overlay from another origin is dropped");
  assert.equal(L.items.get("cliff_palace").by, "National Park Service");
  assert.deepEqual(L.featured, ["mv_landsat", "v_lidar"], "the ribbon's picks: known items only");
});

test("normalizeLibrary: no library (the Moon, an older pack) -> null: the screen keeps today's Library", () => {
  assert.equal(F.normalizeLibrary(null), null);
  assert.equal(F.normalizeLibrary({ course: "moon", shelves: [] }), null);
  assert.equal(F.normalizeLibrary({ shelves: [{ id: "x", title: "X", items: [{ id: "a", kind: "nope" }] }] }), null);
});

test("safeUrl: course media and video posters only", () => {
  assert.ok(F.safeUrl("/api/courses/archaeology/media/four_corners.jpg"));
  assert.ok(F.safeUrl("/api/video/arch_lidar_space/poster"));
  for (const u of ["https://images-assets.nasa.gov/a.jpg", "/api/courses/archaeology/media/../x.jpg", "/api/courses/archaeology/media/a.svg", "javascript:alert(1)", null])
    assert.equal(F.safeUrl(u), null, String(u));
});

test("markersFor: every place (not hardware), plus pictures with their own lat/lon", () => {
  const m = F.markersFor(F.normalizeLibrary(RAW), PLACES);
  assert.deepEqual(m.map(x => x.id), ["place:mesa_verde", "place:hovenweep", "item:iss_san_juan", "item:hot"]);
  assert.equal(m[0].label, "Mesa Verde National Park");
  assert.equal(m[2].kind, "view");
  assert.deepEqual(F.markersFor(null, PLACES).map(x => x.id), ["place:mesa_verde", "place:hovenweep"]);
});

test("placeEntry: the place's real photo, its credit and sources; steps through its photos", () => {
  const L = F.normalizeLibrary(RAW);
  const e = F.placeEntry(PLACES[0], L);
  assert.equal(e.title, "Mesa Verde National Park");
  assert.equal(e.say, "Nearly 5,000 sites.");
  assert.equal(e.photo.src, "/api/courses/archaeology/media/four_corners.jpg");
  assert.equal(e.photo.credit, "NASA Earth Observatory · Public domain (US Government work)");
  assert.match(e.eyebrow, /Real photo 1 of 2/);
  assert.deepEqual(e.sources.map(s => s.title), ["NASA media", "Photo source", "Place source"]);
  assert.equal(F.placeEntry(PLACES[0], L, 1).photo.src, "/api/courses/archaeology/media/photo_cliff_palace.jpg");
  assert.equal(F.placeEntry(PLACES[0], L, 2).photo.src, "/api/courses/archaeology/media/four_corners.jpg", "wraps round");
  const h = F.placeEntry(PLACES[1], L);
  assert.equal(h.photo, undefined, "no photo: just the place line");
});

test("itemEntry + chips + lengths", () => {
  const L = F.normalizeLibrary(RAW);
  const e = F.itemEntry(L.items.get("iss_san_juan"));
  assert.equal(e.eyebrow, "Real photo · NASA");
  assert.equal(e.photo.credit, "NASA · Public domain");
  assert.deepEqual(RAW.chips.map(F.chipAction), [{ type: "tour" }, { type: "item", id: "mv_landsat" }, null]);
  assert.equal(F.lengthText(34), "34 s");
  assert.equal(F.lengthText(223), "4 min");
  assert.equal(F.lengthText(0), "");
});

test("the Moon is untouched: main.js installs the course Library only off the Moon; globe extras are opt-in", () => {
  const main = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
  assert.match(main, /const fieldLib = onMoon \? null : installFieldLibrary\(/);
  assert.match(main, /if \(onMoon\) CHIPS\.forEach/);
  const globe = readFileSync(new URL("../src/globe.js", import.meta.url), "utf8");
  for (const f of ["setOverlay", "setMarkers", "setMoonContext"]) assert.match(globe, new RegExp(`function ${f}\\(`));
  assert.doesNotMatch(main.slice(0, main.indexOf("const fieldLib")), /setOverlay|setMarkers|setMoonContext/);
});
