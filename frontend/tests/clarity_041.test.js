// node --test tests/  — 0.4.1 group B, cockpit clarity (docs/GAMEPLAY.md §14.4): Look ahead, End shift early in the
// Menu (keyboard: Esc, then the arrows), plain words for science / Earth days / the ice drive / the dose, and a voice-bar
// state word that is never truncated. Source checks (no DOM), like cabin_flat.test.js.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");

test("Look ahead, not Center view (the button, its tooltip and the keys sheet)", () => {
  const cab = src("../src/mission/cabin.js"), keys = src("../src/input/keys.js");
  assert.match(cab, /<span>Look ahead<\/span>/);
  assert.match(cab, /title="Look ahead \(R\)"/);
  assert.doesNotMatch(cab, /<span>Center view<\/span>/);
  assert.match(keys, /\["R", "Look ahead"\]/);
});

test("End shift early lives in the Menu (off the console by the master alarm); the ride keeps its own", () => {
  const cab = src("../src/mission/cabin.js"), ui = src("../src/mission/ui.js"), keys = src("../src/input/keys.js");
  const menu = cab.slice(cab.indexOf('id="cbMenu"'), cab.indexOf('id="cbChapter"'));
  assert.match(menu, /data-m="end_shift" id="cbEnd"[^>]*>.*End shift early/);
  const ped = cab.slice(cab.indexOf('class="cb-plate cb-ped"'), cab.indexOf('id="cbDb"'));
  assert.match(ped, /o\.mode === "ride" \?/, "the pedestal's End shift is the check ride's only");
  assert.match(ui, /a === "end_shift"\) \{ closeMenu\(true\); endShift\(\);/);
  assert.match(keys, /Pause menu: speed, restart or end the shift, settings/);
});

test("plain words: science home, Earth days in halves, the ice drive, the dose with mSv in the tooltip", () => {
  const cab = src("../src/mission/cabin.js"), ui = src("../src/mission/ui.js");
  assert.match(cab, /Science<span class="pg-home"> home<\/span>/);   // "home" drops under 1600 px so the strip fits (cabin.css)
  assert.match(cab, /to send<\/span><\/small>/);
  assert.doesNotMatch(cab, /pg-ab-l"> on board/);
  assert.match(ui, /`\$\{Math\.floor\(\+d\)\}½`/);
  assert.match(ui, /Talk to Earth \$\{dd\(earthDays\(s\)\)\} of 10 days/);
  assert.match(ui, /Ice: a \$\{s\.rover_to_ice_h\}-hour drive/);
  assert.doesNotMatch(ui, /h away`/);
  assert.match(cab, /title="\$\{perH \? "Millisieverts \(mSv\) an hour"/);
  assert.doesNotMatch(cab, /irow\("Rate", `\$\{\(\+r\.dose_rate_msv_h \|\| 0\)\.toFixed\(2\)\} mSv\/h`\)/);
});

test("the voice bar's state word is never cut: the field and the hint give way first", () => {
  const css = src("../src/styles.css"), cab = src("../src/cabin.css");
  assert.match(css, /\.listen\{flex:none;[^}]*min-width:156px/);
  assert.doesNotMatch(css, /\.listen-state\{min-width:0;overflow:hidden;text-overflow:ellipsis\}/);
  assert.match(css, /\.hint\{flex:0 1 auto;min-width:0;overflow:hidden/);
  assert.match(cab, /\.cb-askslot \.listen\{flex:none;/);
  assert.doesNotMatch(cab, /\.cb-askslot \.listen\{[^}]*max-width:40%/);
  assert.match(cab, /\.cb-askslot \.listen-state\{flex:none;/);
});

test("the key-hint chip sits beside a card header's control, never over the card's subtitle (patches card, 1440×900)", () => {
  const keys = src("../src/input/keys.js");
  assert.match(keys, /a\.closest\("\[role=dialog\] header"\) && r\.left - w - 6 >= 4\) \{ x = r\.left - w - 6;/);
});
