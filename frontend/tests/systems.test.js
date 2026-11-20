// The Systems drawer (mission/systems.js, docs/GAMEPLAY.md §17) and the wave-5 feedback (the done pulse, the chapter
// card's cue): level disclosure, the Now card's target to a panel and a control, LB / RB stepping, the voice words,
// the same orders as the 3D consoles, the panels' HTML, and the wiring in keys, the controller, the cabin and Mission.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SYSTEMS, systemsFor, numbersFor, systemOfTarget, controlSel, stepSystem, systemWord, commandFor, panelHtml } from "../src/mission/systems.js";
import { keyAction, helpRows } from "../src/input/keys.js";
import { starCueNotes, STAR_MS } from "../src/sound.js";

const src = p => readFileSync(new URL(p, import.meta.url), "utf8");
const ids = l => systemsFor(l).map(s => s.id);
const S = (o = {}) => ({
  resources: { power_pct: 72, life_support_pct: 64, dose_msv: 3.2, dose_limit_msv: 50, dose_rate_msv_h: 0.04, ...(o.resources || {}) },
  env: { in_sun: true, next_sun_change_h: 30, earth_visible: true, comm_delay_s: 2.6, ...(o.env || {}) },
  loads: { shields: 30, life_support: 25, greenhouse: 10, science: 15, rover: 5, comms: 5, heaters: 10, ...(o.loads || {}) },
  rover: { busy: false, battery_pct: 90, ...(o.rover || {}) }, shelter: false, power_save: false, ice_runs: 0,
  why: { battery: { title: "Battery", text: "t", formula: "charge = sun - load", eng: "4.1 kW in - 3.2 kW out = +0.9 kW" } }, ...o.top });

test("level disclosure: Cadet 3 panels, Commander 5, Engineer 5 with the numbers", () => {
  assert.deepEqual(ids("cadet"), ["power", "radiation", "rover"]);
  assert.deepEqual(ids("commander"), ["power", "radiation", "rover", "life", "radio"]);
  assert.deepEqual(ids("engineer"), ids("commander"));
  assert.deepEqual(ids("nonsense"), ids("commander"), "an unknown level flies Commander");
  assert.equal(numbersFor("engineer"), true); assert.equal(numbersFor("commander"), false); assert.equal(numbersFor("cadet"), false);
  assert.equal(SYSTEMS.length, 5);
  for (const s of SYSTEMS) assert.ok(s.name && s.icon, s.id);
});

test("the Now card's target maps to its panel and control, never to a panel the level hides", () => {
  assert.equal(systemOfTarget("shields", "cadet"), "radiation");
  assert.equal(systemOfTarget("shelter", "cadet"), "radiation");
  assert.equal(systemOfTarget("night", "cadet"), "power");
  assert.equal(systemOfTarget("load:heaters", "commander"), "power");
  assert.equal(systemOfTarget("rover:collect_ice", "cadet"), "rover");
  assert.equal(systemOfTarget("houston", "commander"), "radio");
  assert.equal(systemOfTarget("houston", "cadet"), null, "a Cadet's Call Houston: the Now card's button is enough");
  for (const t of ["play", "skip", "warp", "task", "end_shift", null, ""]) assert.equal(systemOfTarget(t, "commander"), null, String(t));
  assert.equal(controlSel("shields", "cadet"), '[data-target="shields"]');
  assert.equal(controlSel("rover:return", "commander"), '[data-target="rover:return"]');
  assert.equal(controlSel("heaters", "cadet"), '[data-target="heaters"]');
  assert.equal(controlSel("heaters", "commander"), '[data-target="load:heaters"]', "Commander's split has the heaters row");
  assert.equal(controlSel("load:science", "cadet"), '[data-target="science"]', "Cadet's Science switch stands for the load");
  assert.equal(controlSel("load:comms", "cadet"), null);
  assert.equal(controlSel("houston", "cadet"), null);
});

test("every target the drawer lights is a control its panel really draws", () => {
  const s = S();
  const cases = [["cadet", "shields"], ["cadet", "shelter"], ["cadet", "night"], ["cadet", "heaters"], ["cadet", "load:science"], ["cadet", "rover:collect_ice"],
    ["commander", "load:heaters"], ["commander", "heaters"], ["commander", "houston"], ["engineer", "rover:explore"], ["engineer", "night"]];
  for (const [lv, t] of cases) {
    const html = panelHtml(systemOfTarget(t, lv), s, { level: lv });
    const want = controlSel(t, lv).match(/"(.+)"/)[1];
    assert.ok(html.includes(`data-target="${want}"`), `${lv} ${t} -> ${want}`);
  }
});

test("LB / RB step the panels and wrap; from a closed drawer RB starts at the first, LB at the last", () => {
  const l = ids("cadet");
  assert.equal(stepSystem(l, "power", 1), "radiation");
  assert.equal(stepSystem(l, "rover", 1), "power");
  assert.equal(stepSystem(l, "power", -1), "rover");
  assert.equal(stepSystem(l, null, 1), "power");
  assert.equal(stepSystem(l, null, -1), "rover");
  assert.equal(stepSystem(l, "radio", 1), "power", "a panel the level dropped restarts the list");
  assert.equal(stepSystem([], "power", 1), null);
});

test("voice: show power, next panel, systems, close; 'show me the rover' stays the window view", () => {
  assert.deepEqual(systemWord("show power"), { open: "power" });
  assert.deepEqual(systemWord("Show me the radiation"), { open: "radiation" });
  assert.deepEqual(systemWord("show the shields"), { open: "radiation" });
  assert.deepEqual(systemWord("open life support"), { open: "life" });
  assert.deepEqual(systemWord("the radio panel"), { open: "radio" });
  assert.deepEqual(systemWord("rover panel"), { open: "rover" });
  assert.deepEqual(systemWord("open the rover"), { open: "rover" });
  assert.deepEqual(systemWord("show the rover panel"), { open: "rover" });
  assert.equal(systemWord("show me the rover"), null);
  assert.deepEqual(systemWord("systems"), { open: null });
  assert.deepEqual(systemWord("show systems"), { open: null });
  assert.deepEqual(systemWord("next panel"), { step: 1 });
  assert.deepEqual(systemWord("previous panel"), { step: -1 });
  assert.deepEqual(systemWord("close systems"), { close: true });
  assert.deepEqual(systemWord("hide the drawer"), { close: true });
  for (const w of ["shields to 40", "send the rover for ice", "next", "power", "what is power", "back to my seat", ""]) assert.equal(systemWord(w), null, w);
});

test("the drawer's controls send the same orders as the 3D consoles", () => {
  const s = S();
  assert.deepEqual(commandFor("shields", { d: "10" }, s), { type: "allocate", to: "shields", amount: { kind: "percent", value: 40 }, from: null });
  assert.deepEqual(commandFor("shields", { d: "10" }, S({ loads: { shields: 60 } })).amount.value, 60, "capped at 60, like the knob");
  assert.deepEqual(commandFor("shields", { d: "-10" }, S({ loads: { shields: 0 } })).amount.value, 0);
  assert.deepEqual(commandFor("shelter", {}, s), { type: "shelter", on: true });
  assert.deepEqual(commandFor("night", {}, s), { type: "power_save", on: true });
  assert.deepEqual(commandFor("switch", { sw: "heaters" }, S({ loads: { heaters: 0 } })), { type: "allocate", to: "heaters", amount: { kind: "percent", value: 15 }, from: null });
  assert.equal(commandFor("switch", { sw: "heaters" }, s).amount.value, 0, "heaters at 10 are on: the switch turns them off");
  assert.deepEqual(commandFor("switch", { sw: "science" }, s), { type: "allocate", to: "science", amount: { kind: "percent", value: 0 }, from: null });
  assert.deepEqual(commandFor("load", { k: "comms", d: "-5" }, s), { type: "allocate", to: "comms", amount: { kind: "delta", value: -5 }, from: null });
  assert.deepEqual(commandFor("rover", { task: "collect_ice" }, s), { type: "dispatch", vehicle: "rover", task: "collect_ice", target: null });
  assert.equal(commandFor("houston", {}, s), null, "Call Houston is its own callback");
  assert.equal(commandFor("shields", { d: "10" }, null), null);
  // the console's own orders (cabin.js), so a change there shows up here
  const cabin = src("../src/mission/cabin.js");
  assert.match(cabin, /type: "dispatch", vehicle: "rover", task: b\.dataset\.task, target: null/);
  assert.match(cabin, /type: "power_save", on: !st\.power_save/);
  assert.match(cabin, /value: clamp\(Math\.round\(\(\(st\.loads\.shields \|\| 0\) \+ d\) \/ 10\) \* 10, 0, 60\)/);
});

test("panels: Cadet has switches, Commander the power split, Engineer the units and an equation", () => {
  const s = S({ top: { units: { battery_kwh: 41, solar_kw: 4.1, load_kw: 3.2, net_kw: 0.9, heater_kw: 1.2, heater_duty_pct: 40, outside_k: 120, outside_c: -153, lit_pct: 80 } } });
  const cadet = panelHtml("power", s, { level: "cadet" }), cmd = panelHtml("power", s, { level: "commander" }), eng = panelHtml("power", s, { level: "engineer" });
  assert.ok(cadet.includes('data-sw="heaters"') && cadet.includes('data-sw="science"') && !cadet.includes("sys-split"));
  assert.ok(cmd.includes("sys-split") && !cmd.includes('data-sw="heaters"') && !cmd.includes(" kW"));
  assert.ok(eng.includes(" kWh") && eng.includes("kW") && eng.includes('class="sys-eq"') && eng.includes("+0.9 kW"));
  assert.ok(panelHtml("radiation", s, { level: "engineer" }).includes("mSv"));
  assert.ok(!panelHtml("radiation", s, { level: "cadet" }).includes("mSv"), "plain words below Engineer (0.4.1)");
  const rv = panelHtml("rover", S({ rover: { busy: true, task: "collect_ice", eta_h: 4 } }), { level: "cadet" });
  assert.match(rv, /data-task="collect_ice"[^>]*aria-pressed="true"[^>]*disabled/);
  assert.match(rv, /data-task="return"[^>]*aria-pressed="false"(?![^>]*disabled)/);
  assert.match(panelHtml("radio", s, { level: "commander", log: [{ who: "CAPCOM", text: "Copy." }] }), /Call Houston[\s\S]*Copy\./);
  assert.match(panelHtml("radio", s, { level: "commander", calling: true }), /disabled>[\s\S]*Signal travelling/);
  assert.match(panelHtml("life", s, { level: "commander" }), /Life support[\s\S]*Greenhouse[\s\S]*Heaters/);
  assert.equal(panelHtml("power", null), "");
  // every gauge's (i) is a Why card the cabin knows (cabin.js WHY)
  const cabinWhy = ["power", "battery", "life_support", "dose", "heaters", "shields", "rover"];
  for (const id of ["power", "radiation", "rover", "life"]) for (const m of panelHtml(id, s, { level: "commander" }).matchAll(/data-why="([a-z_]+)"/g)) assert.ok(cabinWhy.includes(m[1]), m[1]);
});

test("keys [ and ] are the drawer's LB / RB, and never clash with another key", () => {
  assert.deepEqual(keyAction({ key: "]" }), { intent: "systems", args: { arg: "next" } });
  assert.deepEqual(keyAction({ key: "[" }), { intent: "systems", args: { arg: "prev" } });
  assert.deepEqual(keyAction({ key: "ü", code: "BracketLeft" }), { intent: "systems", args: { arg: "prev" } }, "a German layout's [ key");
  assert.equal(keyAction({ key: "]" }, { typing: true }), null, "typing a bracket in a field types it");
  assert.equal(keyAction({ key: "]", ctrl: true }), null);
  assert.equal(keyAction({ key: "]", repeat: true }), null, "a held key steps once");
  const rows = helpRows("cabin_seat").flatMap(g => g.rows);
  assert.ok(rows.some(([k, v]) => k === "[ or ]" && /Systems/.test(v)));
  assert.ok(helpRows("cabin_seat", { pad: true }).flatMap(g => g.rows).some(([k, v]) => k === "LB or RB" && /Systems/.test(v)));
});

test("the controller: LB / RB step the drawer in the cabin; Y with it open is the gauge's Why card", () => {
  const gp = src("../src/input/gamepad.js");
  assert.match(gp, /\(a\.intent === "prev" \|\| a\.intent === "next"\) && inCabin\(\) && emitIntent\("systems"/);
  assert.match(gp, /a\.intent === "help" && inCabin\(\)[\s\S]{0,80}emitIntent\("why", \{ gauge: g \}/);
  assert.ok(src("../src/input/defaults.js").includes('"why", "systems"'), "the router's systems intent reaches Mission");
});

test("Mission wiring: Esc closes the drawer first, panel names open the drawer, the I key explains its gauge", () => {
  const ui = src("../src/mission/ui.js");
  assert.match(ui, /if \(cockpit\.systemsOpen\) return cockpit\.systems\(false, null, \{ focus: true \}\);[\s\S]{0,120}openMenu\(\)/);
  assert.match(ui, /if \(intent === "systems"\) return systemsAct\(arg\);/);
  assert.match(ui, /openSystemFor\(pn\)/);
  assert.match(ui, /if \(cockpit && cockpit\.systemsGauge\) return cockpit\.systemsGauge;/);
  assert.match(ui, /level: \(\) => levelNow\(\)/);
  // the drawer never holds the clock: held() has no drawer reason
  const held = ui.slice(ui.indexOf("function held()"), ui.indexOf("const AUTO_MS"));
  assert.ok(!/systems/i.test(held));
  // the spatial scope: the drawer, the Now card and the window keys
  assert.match(src("../src/input/spatial.js"), /id: "systems", roots: \[sys, shown\("#mCabin \.cb-now"\), shown\("#mCabin \.cb-viewbar"\), shown\("#mCabin \.cb-why"\)\]/);
});

test("the cabin: a 3D console opened closes the drawer; the drawer's labels are >= 20 px", () => {
  const cabin = src("../src/mission/cabin.js"), css = src("../src/cabin.css");
  assert.match(cabin, /if \(id && sys\) sys\.close\(\)/);
  assert.match(css, /\.m-cabin\{--sys-label:20px;/);
  const block = css.slice(css.indexOf("[systems] the Systems drawer"), css.indexOf("[wave 5] feedback"));
  for (const m of block.matchAll(/font-size:(\d+(?:\.\d+)?)px/g)) assert.ok(+m[1] >= 20, `font-size ${m[1]}px in the drawer`);
  for (const m of block.matchAll(/font:\s*\d+\s+(\d+)px/g)) assert.ok(+m[1] >= 20, `font ${m[1]}px in the drawer`);
});

test("wave 5: the done pulse marks the Now card and the control (colour only with less motion)", () => {
  const cabin = src("../src/mission/cabin.js"), css = src("../src/cabin.css"), ui = src("../src/mission/ui.js");
  assert.match(cabin, /marks\.forEach\(n => \{ void n\.offsetWidth; n\.dataset\.done = "1"; \}\)/);
  assert.match(ui, /if \(done && cockpit\.pulse\) cockpit\.pulse\(\);/);
  // less motion: a still colour while the mark is on (a11y.css cuts every animation to 0.01 ms there), never a move
  const red = css.match(/html\[data-motion="reduce"\] \.m-cabin \.cb>\.cb-now\[data-done\],html\[data-motion="reduce"\] \.m-cabin \[data-done\]:not\(\.cb-now\)\{([^}]*)\}/);
  assert.ok(red, "a reduced-motion rule for the pulse");
  assert.match(red[1], /animation:none;transform:none;/);
  assert.match(red[1], /box-shadow:0 0 0 3px var\(--color-phosphor\)/);
  assert.match(cabin, /pulseT = setTimeout\(\(\) => marks\.forEach\(n => delete n\.dataset\.done\), 1300\)/);
});

test("wave 5: the chapter cue plays one note per star on the beat the stars land", () => {
  assert.deepEqual(starCueNotes(1).map(n => n.at), [STAR_MS[0] / 1000]);
  assert.equal(starCueNotes(2).length, 2);
  assert.equal(starCueNotes(3).length, 5, "three stars end on a chord");
  assert.equal(starCueNotes(0).length, 1, "no star still has a soft note");
  const hz = starCueNotes(3).slice(0, 3).map(n => n.hz); assert.ok(hz[0] < hz[1] && hz[1] < hz[2], "rising");
  assert.ok(STAR_MS.every((ms, i) => ms === 450 * i + 450), "the same beat as cabin.css (--i * 450ms + 450ms)");
  assert.match(src("../src/cabin.css"), /animation-delay:calc\(var\(--i, 0\) \* 450ms \+ 450ms\)/);
  const snd = src("../src/sound.js"); const fn = snd.slice(snd.indexOf("export function starCue("));
  assert.match(fn.slice(0, 200), /if \(!L\.master\) return \[\];/, "Mute (and the muted test runs) play nothing");
});
