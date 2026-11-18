// node --test tests/  — 0.4 "Real NASA views": the optional nasa_views pack's client (media/nasa_views.js), the
// Library wiring (views_wire.js, media/rocks_tray.js) and the globe's fallbacks. No DOM, no WebGL: pure parts + fakes.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as V from "../src/media/nasa_views.js";
import { trayItem, MODEL_STORY } from "../src/media/rocks_tray.js";
import { ORBITERS, polarCap } from "../src/views_wire.js";

const READY = {
  state: "ready", pack: "nasa_views", credit: V.CREDIT,
  sky: { file: "sky/starmap_4k.jpg", ra0_u: 0.5, ra_increases: "left" },
  models: [{ id: "apollo_lm", file: "models/apollo_lm.glb", title: "Apollo Lunar Module" }, { id: "evil", file: "../../etc/passwd" }],
  rocks: [{ id: "15016", file: "rocks/15016.glb", name: "Vesicular basalt", mission: "Apollo 15", type: "Mare basalt", story: "Lava." }],
  images: [{ id: "earthrise", file: "images/earthrise.jpg", tags: ["earth", "apollo"] }, { id: "earthset", file: "images/earthset.jpg", tags: ["earth", "artemis"] }],
  sdo: { title: "The Sun", frames: [{ file: "sdo/00.jpg", time: "2024-05-14T00:00Z" }, { file: "sdo/01.jpg", time: "2024-05-14T01:30Z" }] },
  names: { file: "names/moon_names.json" },
};
const res = (body, ok = true) => ({ ok, json: async () => body });

test("fileUrl serves only the pack's folders, one plain name each (no traversal)", () => {
  assert.equal(V.fileUrl("images/earthrise.jpg"), "/api/views/file/images/earthrise.jpg");
  assert.equal(V.fileUrl("rocks/15016.glb"), "/api/views/file/rocks/15016.glb");
  for (const bad of ["../x.jpg", "images/../../x", "images/a/b.jpg", "/etc/passwd", "secrets/x.jpg", "", null, "images/.hidden"]) assert.equal(V.fileUrl(bad), null, String(bad));
});

test("normalize: null until ready; urls filled; bad entries dropped; an empty SDO set is null", () => {
  assert.equal(V.normalize({ state: "missing", managed: true }), null);
  assert.equal(V.normalize(null), null);
  const v = V.normalize(READY);
  assert.equal(v.sky.url, "/api/views/file/sky/starmap_4k.jpg");
  assert.deepEqual(v.models.map(m => m.id), ["apollo_lm"]);
  assert.equal(v.rocks[0].url, "/api/views/file/rocks/15016.glb");
  assert.equal(v.sdo.frames.length, 2);
  assert.equal(V.normalize({ ...READY, sdo: { frames: [] } }).sdo, null);
  assert.match(v.credit, /not endorsed by NASA/);
});

test("skyTransform: a sky chart (RA to the left) is flipped for the inside of the sphere; RA 0h at u = 0", () => {
  assert.deepEqual(V.skyTransform({ ra_increases: "left", ra0_u: 0.5 }), { flipX: true, offsetU: 0.5 });
  assert.deepEqual(V.skyTransform({ ra_increases: "right", ra0_u: 0 }), { flipX: false, offsetU: 0 });
  assert.deepEqual(V.skyTransform({ ra_increases: "left", ra0_u: 1.25 }), { flipX: true, offsetU: 0.25 });
  assert.equal(V.skyTransform(null).flipX, true);
});

test("the Apollo LMs (and only they) get the LM model in the Library", () => {
  for (const id of ["apollo11_lm_eagle", "apollo12_lm_intrepid", "apollo14_lm_antares", "apollo15_lm_falcon", "apollo16_lm_orion", "apollo17_lm_challenger"])
    assert.equal(V.modelForArtifact({ id, kind: "artifact" }), "apollo_lm", id);
  for (const id of ["apollo15_lrv", "surveyor1", "change3_lander", "apollo11_lrrr"]) assert.equal(V.modelForArtifact({ id }), null, id);
  const arts = JSON.parse(readFileSync(new URL("../../backend/data/artifacts.json", import.meta.url), "utf8"));
  assert.equal(arts.filter(a => V.modelForArtifact(a)).length, 6);
});

test("onViews: the pack's API answers once it is ready; the page API finds images, SDO frames, rocks", async () => {
  V._reset();
  const answers = [res({ state: "downloading", managed: true }), res(READY)];
  let calls = 0;
  const realSet = globalThis.setTimeout;
  globalThis.setTimeout = (fn) => realSet(fn, 1);          // the 30 s poll, at once
  try {
    V.start(async () => answers[Math.min(calls++, 1)]);
    const v = await new Promise(r => V.onViews(r));
    assert.equal(calls, 2);
    assert.equal(v.images.length, 2);
  } finally { globalThis.setTimeout = realSet; }
  assert.equal(V.image("earthrise").url, "/api/views/file/images/earthrise.jpg");
  assert.deepEqual(V.images("artemis").map(i => i.id), ["earthset"]);
  assert.equal(V.sdoFrames().length, 2);
  assert.equal(V.rocks()[0].id, "15016");
  let late = null; V.onViews(x => { late = x; });
  assert.ok(late, "a late subscriber hears at once");
  V._reset();
});

test("without the pack (a dev checkout, not managed) the client stops asking: today's visuals stay", async () => {
  V._reset();
  let calls = 0, heard = false;
  V.start(async () => { calls++; return res({ state: "missing", managed: false }); });
  V.onViews(() => { heard = true; });
  await new Promise(r => setTimeout(r, 20));
  assert.equal(calls, 1); assert.equal(heard, false); assert.equal(V.getViews(), null);
  V._reset();
  V.start(async () => { throw new TypeError("fetch failed"); });   // backend unreachable: no throw, no views
  await new Promise(r => setTimeout(r, 10));
  assert.equal(V.getViews(), null);
  V._reset();
});

test("the rocks tray: a rock reads name, mission · type · sample id, story, CC0 credit; every model has a line", () => {
  const it = trayItem(V.normalize(READY).rocks[0], "rock");
  assert.equal(it.title, "Vesicular basalt");
  assert.equal(it.sub, "Apollo 15 · Mare basalt · sample 15016");
  assert.match(it.credit, /CC0/);
  for (const id of ["apollo_lm", "hdu", "rassor", "mcc", "lro", "ladee"]) assert.ok(MODEL_STORY[id] && MODEL_STORY[id].length <= 140, id);
  for (const o of ORBITERS) assert.ok(MODEL_STORY[o.id], o.id);
});

test("polarCap: drapes the LOLA relief once site_layers is ready; stops at once without them", async () => {
  const calls = [];
  const globe = { setPolarCap: (url, km) => { calls.push([url, km]); return true; } };
  const nav = layers => async () => res({ layers });
  assert.equal(await polarCap(globe, { fetchImpl: nav({ state: "ready", extent_km: 210, base: { file: "relief.png" } }) }), true);
  assert.deepEqual(calls, [["/api/sites/layers/relief.png", 210]]);
  assert.equal(await polarCap(globe, { fetchImpl: nav({ state: "missing", managed: false }) }), false);
  let n = 0;
  const later = async () => res({ layers: n++ < 2 ? { state: "downloading", managed: true } : { state: "ready", base: { file: "relief.png" } } });
  assert.equal(await polarCap(globe, { fetchImpl: later, waitMs: 1 }), true);
  assert.equal(n, 3);
});

test("the globe keeps the random stars until the real sky has loaded, and every views setter is optional", () => {
  const src = readFileSync(new URL("../src/globe.js", import.meta.url), "utf8");
  assert.match(src, /const starPts = /);
  assert.match(src, /scene\.add\(skyMesh\); starPts\.visible = false; res\(true\);/, "the points hide only once the map is in");
  assert.match(src, /\(\) => res\(false\)\)\);   \/\/ a failed load keeps the random stars/);
  for (const k of ["setSky", "setPolarCap", "setHardwareModels", "setOrbiters"]) assert.match(src, new RegExp(`\\b${k},`));
  // [0.4 part 2] the cabin uses the pack only through mission/cabin_views.js (tests/cabin_views.test.js); the 3D cabin and
  // its CSS never touch it
  const cabin = ["cabin.css", "mission/cockpit.js", "mission/cockpit3d.js"];
  for (const f of cabin) assert.doesNotMatch(readFileSync(new URL("../src/" + f, import.meta.url), "utf8"), /nasa_views|views_wire/, f);
  assert.doesNotMatch(readFileSync(new URL("../src/mission/cabin.js", import.meta.url), "utf8"), /from "\.\.\/media\/nasa_views\.js"|views_wire/);
});
