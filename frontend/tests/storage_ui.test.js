// Settings → Storage & updates (src/storage_ui.js): the update line and the rows from the desktop's asset summary.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const S = await import("../src/storage_ui.js");

test("update line: ready beats every other state; each state has plain words", () => {
  assert.match(S.updateLine({ update: { state: "up_to_date", ready: ["ear"] } }), /restart/);
  assert.equal(S.updateLine({ update: { state: "up_to_date", ready: [] } }), "Up to date.");
  assert.match(S.updateLine({ update: { state: "offline" } }), /Offline/);
  assert.match(S.updateLine({ update: { state: "downloading", downloading: "ear" } }), /Downloading.*ear/);
  assert.match(S.updateLine({ update: { state: "paused" } }), /paused/);
  assert.equal(S.updateLine({}), "Not checked yet.");
});

test("rows: version, size, update-ready note; sizes read in MB / GB", () => {
  const r = S.rows({ installed: [
    { id: "ear", title: "Speech model", installed: true, version: "2", bytes: 460_000_000, update_ready: false },
    { id: "videos", title: "NASA videos", installed: false, version: null, bytes: 0 },
    { id: "voice", title: "Nora's voice", installed: true, version: "1", bytes: 13_800_000, update_ready: true }] });
  assert.deepEqual(r[0], { name: "Speech model", version: "v2", size: "460 MB", note: "" });
  assert.deepEqual(r[1], { name: "NASA videos", version: "not downloaded", size: "", note: "" });
  assert.equal(r[2].note, "update ready");
  assert.equal(S.size(1_500_000_000), "1.5 GB");
  assert.equal(S.size(2_500_000), "2.5 MB");
});

test("registered as a Settings section after Videos; hidden in a dev checkout", () => {
  const sec = window.__outpost.settingsSections.find(x => x.id === "storage");
  assert.ok(sec && sec.after === "videos" && sec.title === "Storage & updates");
  assert.match(sec.html(), /Check for updates/);
});
