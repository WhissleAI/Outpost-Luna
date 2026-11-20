// Settings → For grown-ups → Course storage (src/course_store_ui.js) and the globe's body radius (src/globe.js).
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const C = await import("../src/courses.js");
const U = await import("../src/course_store_ui.js");

const pack = (o = {}) => ({ id: "archaeology", title: "Course: Archaeology", size: 55e6, version: "1", state: "missing", active: false, blocked: false, ...o });
const acts = r => r.actions.map(a => a.act);

test("the Moon is built in: never Get or Remove", () => {
  C.courseState.active = "moon";
  const r = U.rowOf(null, { moon: true });
  assert.equal(r.sub, "Built in · Playing"); assert.deepEqual(acts(r), []);
  C.courseState.active = "archaeology";
  assert.deepEqual(acts(U.rowOf(null, { moon: true })), ["play"]);
  C.courseState.active = "moon";
});

test("each pack state gets the right actions and plain notes", () => {
  assert.deepEqual(acts(U.rowOf(pack())), ["get"]);
  assert.equal(U.rowOf(pack()).actions[0].label, "Get (55 MB)");
  assert.equal(U.rowOf(pack()).title, "Archaeology");
  assert.deepEqual(acts(U.rowOf(pack({ state: "installed" }))), ["play", "remove"]);
  assert.deepEqual(acts(U.rowOf(pack({ state: "installed", active: true }))), ["remove"]);
  assert.match(U.rowOf(pack({ state: "installed", active: true })).sub, /Playing/);
  assert.equal(U.rowOf(pack({ state: "downloading" })).note, "Downloading…");
  assert.equal(U.rowOf(pack({ state: "queued" })).note, "Waiting to download…");
  const blocked = U.rowOf(pack({ blocked: true }));
  assert.deepEqual(acts(blocked), []); assert.equal(blocked.note, "Off on the school network.");
  const failed = U.rowOf(pack({ state: "failed", reason: "You're offline." }));
  assert.deepEqual(acts(failed), ["get"]); assert.equal(failed.note, "You're offline.");
});

test("the list shows free space and says when there is nothing else", () => {
  const h = U.listHtml({ packs: [pack()], free_bytes: 12e9 });
  assert.match(h, /data-crs-row="moon"/); assert.match(h, /data-crs-act="get" data-id="archaeology"/); assert.match(h, /Free space: 12\.0 GB/);
  assert.match(U.listHtml({ packs: [] }), /No other courses yet/);
});

test("the globe frames places by the body's own radius (the Moon's by default)", async () => {
  const G = await import("../src/globe.js").catch(() => null);
  if (!G) return;   // three.js not loadable under node: covered by globe_body.test.js shape checks
  const f = { km: 300 };
  assert.equal(G.angRadius(f), G.angRadius(f, 1737.4));
  assert.ok(G.angRadius(f, 6371) < G.angRadius(f));
  assert.ok(G.frameDistance({ km: 3000 }, 6371) < G.frameDistance({ km: 3000 }));
});
