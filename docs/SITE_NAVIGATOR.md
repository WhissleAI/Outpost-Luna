# Landing-site navigator: "Choose your landing site"

Owner: `feat/site-navigator`. Before a mission the old picker showed five south-pole sites with light trade-off copy
("Sun means power. Earth means radio"). The navigator turns it into a real-data tool built on NASA data we did not use
before: LRO LOLA illumination, Earth visibility, permanent shadow, slope and topography, the LRO Diviner polar
temperatures and ice-stability depth, and JPL Horizons for the longest darkness. Sources and method:
[`backend/data/SOURCES.md`](../backend/data/SOURCES.md).

## What the kid sees

* **The south-pole map** (left): LOLA shaded relief with one NASA layer: **Sunlight** (% of the year), **Slope**
  (degrees), **Ice** (never-sunlit ground, and ground cold enough for ice on the surface) or **Earth view** (% of the
  time). A legend with units and a credit line for the layer and the base map. Pins for our 5 sites (circles) and
  NASA's 9 Artemis III regions (squares), each labelled with its score; labels never overlap each other or the controls.
* **The panel** (right): presets (Balanced, Power first, Ice first, Radio first, Safe landing first) and "Weigh it
  yourself" (4 sliders, 0–3), the 5 sites as a radio group with score, tag and four numbers, the selected site's card
  (sunlight, longest dark, Earth in view, ice, slope, temperature, never-lit ground; each with its range and a source
  link; and **"In your mission"**: Sun and radio days of the 10, the ice run's hours, the steep drive's battery cost),
  and NASA's 9 regions (compare only; Malapert and de Gerlache Rim 2 are our own outposts).
* **Tags**: "On NASA's 2024 Artemis III list" (Malapert, de Gerlache, the 9 regions), "Studied, dropped (NASA's 2022
  list)" (Shackleton Rim = Peak Near Shackleton, Connecting Ridge), "Studied by scientists" (Shackleton floor).
* **Without the layers** (an optional download on 0.3): the globe and its pins stay, a pill says "Map layers
  downloading…", the numbers and sources still show; the map appears when the layers land (polls every 5 s).

## The score

NASA's criteria for the Artemis III regions (George et al., NTRS 20250011660): solar illumination, Direct-to-Earth
radio, terrain safety, PSR access. Each criterion becomes 0..1 on the navigator's own scale, then a weighted mean × 100:

| Criterion | Number | 0 → 1 |
|---|---|---|
| Power | yearly sunlight % | 30 % → 90 % |
| Talk to Earth | Earth in view % | 0 → 100 % |
| Ice nearby | km to surface-stable ice | 15 km → 0 |
| Safe landing | slope at the pad | 15° → 0° |

`backend/app/mission/navigator.py` and `frontend/src/mission/navigator_score.js` implement it identically (same
rounding); `frontend/tests/fixtures/navigator_cases.json` is checked by both test suites.

## Into the mission

The navigator picks the site for Mission 1. Missions 2 to 6 of the campaign fly their own sites (Malapert Massif,
Shackleton Crater Floor, de Gerlache Rim, Connecting Ridge, Shackleton Rim; docs/GAMEPLAY.md §16): a site picked here
always flies Mission 1's way.

Picking a site and taking command flies it on its real numbers, through the sim's existing site parameters
(`sites.json` and `ephemeris_<site>.json`; `docs/MISSION_CONTRACT.md`), never a fork:

* **Power**: each hour the Sun (Horizons) is checked against the LOLA skyline at its azimuth (`sun_terrain_deg`). The
  10-day window changed: Shackleton Rim is dark for the first ~1.5 days of April 2026 (sunlit 73 % of the window, was
  100 %), Connecting Ridge 76 % (was 100 %), de Gerlache 95 % (was 81 %), Malapert 35 % (unchanged).
* **Comms**: Earth against the skyline (`earth_terrain_deg`): Connecting Ridge 14 % (was 43 %), Malapert 71 % (was
  92 %), Shackleton Rim 44 %.
* **Ice run**: `rover_to_ice_h` = distance to surface-stable ice (Diviner) at VIPER's top speed, slower on slopes:
  Rim 7 h (2.9 km), Ridge 16 h (7.0 km), de Gerlache 17 h (7.2 km), Malapert 31 h (12.1 km); the floor has ice on site.
  `rover_slope_power` (+2 / +3 % battery) is the steep drive's cost.
* The Shackleton floor's power comes by the pretend cable from the rim's arrays, which now really go dark (about two
  days at the start). The floor plays that as its day / night: `env.lit` (the arrays see the Sun) drives sunrise /
  sunset / sunset-in-6-hours events ("Sunset on the rim"), the night checklist task and the Power panel's Sun timeline;
  `env.in_sun` (the Sun at the outpost) stays false on the floor. `env.power_sun` mirrors `lit` for the planner.
* Balance (`tools/strategy_sim.py`, 6 seeds × 5 sites, Commander, shift clock): the planner survives 1.00 with
  both goals 0.90 (score 587, min 389); no fixed rule passes 0.33 survival; `tests/test_strategy.py` passes on all three
  clocks. The game is harder than before at the rim and ridge, because their real skylines cast real shadows.

## Every input

| Input | What it does |
|---|---|
| Mouse | Click a row, a pin or a label to pick; click a layer chip (again to turn it off); drag pans the map, the wheel zooms about the cursor; + / − / home buttons |
| Keyboard | The rows are a radio group (↑ ↓); Tab to the map, then arrows pan and + / − zoom; the sliders take ← →; Enter on Take command |
| Controller | D-pad + A as the keyboard; right stick pans the map (`spin`), the triggers zoom (`zoom_rate`) |
| Voice | "show sunlight", "the ice map", "earth view", "hide the layers" (`site_layer`); "which site has the most ice?", "which one is the sunniest", "where can we talk to Earth", "which is flattest", "which site is best" (`site_query`: picks the winner among the flyable sites, turns its layer on, says the number, names a better NASA region if one wins); "ice first", "power first", "make it balanced" (`site_preset`); "pick Malapert" (`pick_site`), "pick Haworth" (shows the region) |
| Gestures | Fist moves the map, pinch and slide zooms it, point at a pin then thumbs up picks it; thumbs up again flies (`gesture/map.js` column `sites`) |

The router (`backend/app/turn_router.py`) reads `site_layer` / `site_query` / `site_preset` on the picker screen only
(`brief`); "what is ice?" stays a question. Director coverage: probes and generator phrases in
`director_model/coverage.py` and `pools_r8.py` (cells `brief|nav:site_layer|site_query|site_preset`).

## Build and assets

* `make site-physics`: fetch (cached in `backend/data/cache/nasa`, ~0.9 GB) → `sites_physics.json` + the engine fields.
  Committed; rerun only to refresh.
* `make site-layers`: the 5 PNGs + `layers.json` + `NOTICE` → `backend/data/cache/site_layers` (served in dev), the
  deterministic `outpost-luna-site-layers.tar` + `site_layers.asset.json` (sha256, size, files), then the raster
  cache is deleted.
* Desktop (0.3, Mac and Windows alike): the optional first-run asset `site_layers` (20.4 MB tar, 7 files) in both
  manifest copies, built by `make site-layers && python3 scripts/asset_pack.py --only site_layers --no-zip`, installed
  under `<assets>/site_layers`, `SITE_LAYERS_DIR` for the backend. The main process fetches optional assets in the
  background; POST `/api/sites/layers/want` also asks for it. Its `url` is null until `scripts/upload_assets.py`
  uploads the tar: until then the map says "Map layers download when you're online" and everything else works.

## Checks

* `backend/tests/test_navigator.py`: loader (every number has a source, unit and basis; physical ranges), tags, scoring
  (shared cases), the API and the layers state, router intents on and off the picker, the engine fields and that a
  started mission's Sun, Earth, windows and ice run follow them.
* `frontend/tests/navigator.test.js`: score parity, criteria, presets, "which site…", formats and spoken lines, intents,
  the gesture column.
* `frontend/tests/e2e/site_navigator_e2e.py`: every input end to end, pick → take command → the mission's numbers, and
  the no-layers state.
* `frontend/tools/mission_ui.py`: the navigator overlap check at 1024–1920 (`--navigator-only` for just this screen).
