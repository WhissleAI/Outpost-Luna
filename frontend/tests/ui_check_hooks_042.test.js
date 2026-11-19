// node --test tests/  — 0.4.2: tools/mission_ui.py reported "the story banner did not show" and "gauges with no visible
// Why? button: ['power']" on every packaged build (0.4.0, 0.4.1) while the cabin was fine. The tool drives the banner and
// the panels through window.__cabinTest, which the app only installs under the dev server or when the page sets
// window.__outpostTest; the tool's seed never set it, so on a built app every hook call was a silent no-op.
// Source checks (no DOM), like cabin_flat.test.js.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");

test("the cabin's test hooks install in a built app when the page sets window.__outpostTest", () => {
  const ui = src("../src/mission/ui.js");
  assert.match(ui, /\(\(import\.meta\.env && import\.meta\.env\.DEV\) \|\| window\.__outpostTest\) && !window\.__cabinTest\) window\.__cabinTest = \{/);
  assert.match(ui, /moment\(title = "On our own"\) \{ if \(cockpit && cockpit\.moment\)/);
  assert.match(ui, /panel\(id\) \{ if \(!cockpit\) return; if \(id\) cockpit\.openPanel\(id\); else cockpit\.seat\(\); \}/);
});

test("mission_ui.py seeds window.__outpostTest and refuses to measure without the hooks", () => {
  const mu = src("../tools/mission_ui.py");
  const seed = mu.slice(mu.indexOf('SEED = """'), mu.indexOf('"""', mu.indexOf('SEED = """') + 10));
  assert.match(seed, /window\.__outpostTest = 1;/, "the seed turns the hooks on, so a packaged build is checked too");
  assert.match(mu, /window\.__cabinTest && window\.__cabinTest\.moment && window\.__cabinTest\.panel/);
  assert.match(mu, /the cabin test hooks are missing \(window\.__cabinTest\)/, "a missing hook is reported as such, not as a product finding");
});

test("the story banner and the Power Why? button are in the cabin (what the tool checks)", () => {
  const cab = src("../src/mission/cabin.js"), css = src("../src/cabin.css");
  // the banner: its own element on the glass, shown by moment(), hidden again after 5.2 s
  assert.match(cab, /<div class="cb-moment" id="cbMoment" hidden aria-hidden="true"><\/div>/);
  assert.match(cab, /el\.hidden = false; slot\(true\); clearMarks\(\);/);
  assert.match(cab, /moment: b => moment\(b\),/);
  // Power: the gauge's head carries the battery Why?, the Panels row the solar-power one (seen with the Displays panel open)
  assert.match(cab, /big\("Power", Math\.round\(r\.power_pct\), "%", r\.power_pct < 25, "battery"\)/);
  assert.match(cab, /const panels = row\(`Panels\$\{whyBtn\("power"\)\}`/);
  assert.match(cab, /const whyBtn = id => `<button type="button" class="cb-whyb" data-why="\$\{id\}" aria-label="Why\? \$\{esc\(WHY\[id\]\)\}"/);
  // a real button, at least 18 px (the HUD rule), bigger on the seat view's gauge heads
  const w = +(css.match(/\.cb-whyb\{[^}]*width:(\d+)px/) || [])[1];
  assert.ok(w >= 18, `the Why? button is ${w}px`);
  assert.match(css, /\.c3\[data-panel="seat"\] \.du-head \.cb-whyb\{width:32px;height:32px\}/);
});
