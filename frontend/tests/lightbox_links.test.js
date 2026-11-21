// [0.5.6] owner playtest 0.5.5: the picture viewer (media/lightbox.js), links that never dead-click (links.js) and the
// course's documents (field_library.js normalizeDocs).
import test from "node:test";
import assert from "node:assert/strict";
import { clampPan, zoomAt, fitBox } from "../src/media/lightbox.js";
import { linkKind, linkKey, docItems, COPY } from "../src/links.js";
import { normalizeDocs, normalizeLibrary } from "../src/field_library.js";

const RACK = "https://www.nps.gov/subjects/archeology/upload/RackArtifactsVisitors_508.pdf";
const DOC = { id: "nps_rack_artifacts", url: RACK, title: "What If I Find an Artifact?", by: "NPS Archeology Program",
  credit: "National Park Service, Archeology Program (NPS photos)", licence: "Public domain (US Government work, 17 U.S.C. 105)",
  pages: [{ url: "/api/courses/archaeology/media/nps_rack_artifacts_p1.jpg", alt: "Page 1" }, { url: "/api/courses/archaeology/media/nps_rack_artifacts_p2.jpg", alt: "Page 2" }] };
const ORIGIN = "http://127.0.0.1:47310";

test("fitBox: the content is as big as the view allows, keeping its shape", () => {
  assert.deepEqual(fitBox({ w: 1200, h: 600 }, 4 / 9), { w: 267, h: 600 });     // a tall rack card page
  assert.deepEqual(fitBox({ w: 1200, h: 600 }, 1.4), { w: 840, h: 600 });       // the lidar map
  assert.deepEqual(fitBox({ w: 600, h: 900 }, 1.4), { w: 600, h: 429 });
});

test("zoomAt keeps the point under the pointer still, within 1x-6x", () => {
  const z = zoomAt({ s: 1, tx: 100, ty: 50 }, 2, 300, 250);
  assert.equal(z.s, 2);
  // the content point under (300, 250) before: ((300-100)/1, (250-50)/1) = (200, 200); after: (300-tx)/2 = 200
  assert.equal((300 - z.tx) / z.s, 200); assert.equal((250 - z.ty) / z.s, 200);
  assert.equal(zoomAt({ s: 1, tx: 0, ty: 0 }, 50, 0, 0).s, 6);
  assert.equal(zoomAt({ s: 2, tx: 0, ty: 0 }, 0.1, 0, 0).s, 1);
});

test("clampPan: never dragged off into empty space; smaller than the view, it is centred", () => {
  const view = { w: 1000, h: 600 }, box = { w: 800, h: 600 };
  assert.deepEqual(clampPan({ s: 1, tx: 500, ty: 300 }, view, box), { s: 1, tx: 100, ty: 0 });
  const z = clampPan({ s: 2, tx: 400, ty: -2000 }, view, box);   // 1600 x 1200 content
  assert.equal(z.tx, 0); assert.equal(z.ty, -600);
});

test("links: a document the pack keeps opens here, the rest of the web in the browser", () => {
  assert.equal(linkKind(RACK, [DOC], ORIGIN).kind, "doc");
  assert.equal(linkKind(RACK + "#page=2", [DOC], ORIGIN).kind, "doc", "a fragment is the same document");
  assert.equal(linkKind("https://www.nps.gov/meve/index.htm", [DOC], ORIGIN).kind, "web");
  assert.equal(linkKind(ORIGIN + "/api/x", [DOC], ORIGIN).kind, "ours");
  assert.equal(linkKind("javascript:alert(1)", [DOC], ORIGIN).kind, "none");
  assert.equal(linkKind("", [DOC], ORIGIN).kind, "none");
  assert.equal(linkKey(RACK + "#x"), RACK);
  assert.match(COPY.web, /browser/); assert.match(COPY.here, /here/);
});

test("docItems: one viewer page per document page, titled and credited", () => {
  const it = docItems(DOC);
  assert.equal(it.length, 2);
  assert.equal(it[1].src, DOC.pages[1].url);
  assert.equal(it[1].caption, "What If I Find an Artifact?, page 2 of 2");
  assert.equal(it[0].credit, "National Park Service, Archeology Program (NPS photos) · Public domain");
});

test("normalizeDocs: only https documents whose pages are the course's own media", () => {
  const d = normalizeDocs([DOC, { ...DOC, id: "x", url: "http://evil.example/a.pdf" },
    { ...DOC, id: "y", pages: [{ url: "https://evil.example/p.jpg" }] }, null, { id: "z" }]);
  assert.deepEqual(d.map(x => x.id), ["nps_rack_artifacts"]);
  const lib = normalizeLibrary({ shelves: [{ id: "s", items: [{ id: "a", kind: "place", title: "A" }] }], docs: [DOC] });
  assert.equal(lib.docs.length, 1);
  assert.deepEqual(normalizeLibrary({ shelves: [{ id: "s", items: [{ id: "a", kind: "place", title: "A" }] }] }).docs, []);
});
