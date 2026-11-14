// node --test tests/  — the cabin window's bundled terrain: every mission site has its three LOLA tiles + meta,
// the tiles are the shape the client decodes, and the window code never reaches for the network (offline installer).
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";

const root = new URL("../", import.meta.url);
const read = p => readFileSync(new URL(p, root));
const sites = JSON.parse(read("../backend/data/mission/sites.json")).sites;

test("every mission site has context/site/rover tiles and meta that match sites.json", () => {
  const index = JSON.parse(read("public/terrain/index.json"));
  assert.match(index.credit, /not endorsed by NASA/);
  for (const s of sites) {
    const meta = JSON.parse(read(`public/terrain/${s.id}/meta.json`));
    assert.equal(meta.lat, s.lat); assert.equal(meta.lon, s.lon);
    for (const lv of ["context", "site", "rover"]) {
      const m = meta.levels[lv], png = read(`public/terrain/${s.id}/${lv}.png`);
      assert.equal(png.toString("latin1", 1, 4), "PNG");
      assert.equal(png.readUInt32BE(16), m.px); assert.equal(png.readUInt32BE(20), m.px);
      assert.equal(png[24], 8); assert.equal(png[25], 2, `${s.id}/${lv}: 8-bit RGB (height packed in R,G)`);
      assert.ok(m.dn_max - m.dn_min <= 65535 && m.dn_scale_m === 0.5);
      assert.ok(Math.abs(m.center_x_m - m.site_x_m) < m.m_per_px && Math.abs(m.center_y_m - m.site_y_m) < m.m_per_px, "tile centred on the site");
    }
    assert.ok(meta.levels.context.m_per_px > meta.levels.site.m_per_px && meta.levels.site.m_per_px > meta.levels.rover.m_per_px);
  }
  assert.ok(existsSync(new URL("public/terrain/earth.jpg", root)));
});

test("window views fetch only bundled files (no network at runtime)", () => {
  for (const f of ["src/mission/terrain.js", "src/mission/cabin.js", "src/cabin.css"]) {
    const src = read(f).toString().replace(/\/\/.*$/gm, "");
    assert.doesNotMatch(src, /https?:\/\/(?!www\.w3\.org\/2000\/svg)/, `${f} must not reference a remote URL`);
  }
  assert.match(read("src/mission/terrain.js").toString(), /\/terrain\/\$\{site\.id\}\/meta\.json/);
});
