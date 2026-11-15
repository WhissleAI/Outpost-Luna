# Physics you can see: "Why?" cards, the debrief's numbers, Engineer mode

The mission's sim already modelled power, heat, radiation, life support and the ice run. This work does three things:

- shows that physics in the cabin;
- adds NASA data the game did not use yet;
- adds an Engineer level that works in real units.

The game itself is unchanged. `physics.py` only reads the mission, and `tests/test_strategy.py` still passes.

## Data (`backend/data/physics/`)

`physics.json` is built at build time by `backend/pipeline/physics_data.py`:

```
uv run --with tifffile==2025.5.10 python -m pipeline.physics_data
```

The app never calls NASA. `SOURCES.md` lists every source with its URL, its licence and its use.

- **One table per quantity.** Each site's sunlight, Earth view, slopes, drive to ice and Diviner yearly average and
  maximum temperature come from the landing-site navigator's `backend/data/sites_physics.json`
  (docs/SITE_NAVIGATOR.md). `physics.py` reads them from there (`site_phys()`), so a card, the debrief and the
  navigator always quote the same number. `physics.json` adds only the Diviner night minimum (Williams 2019 seasonal
  maps), sampled at the navigator's spot for each site.
- **Curated.** Published NASA values, each with its location in the source:
  - DSNE regolith properties;
  - BVAD oxygen use;
  - CRaTER quiet and storm doses;
  - LCROSS and LEND water;
  - the Surface Habitat power study;
  - SST cell efficiency;
  - VIPER and the Apollo rover.
- **Bundled.** Both desktop builds ship `backend/data` whole. `build_python.py` and `win_bundle_check.py` also check for `physics.json` by name.

**The outpost model**, game scale:

| Quantity | Value | How it is set |
|---|---|---|
| Battery | 250 kWh | NASA's Surface Habitat array is 10–15 kW. The sim's full-Sun charge is 6 %/h, so a 15 kW array means a 250 kWh battery. That sits inside the habitat's 155–540 kWh survive-the-night range. |
| 1 %/h of battery | 2.5 kW | Follows from the battery size. |
| Panel area | 37 m² | 15 kW at 1361 W/m² with 30% cells. |
| Heater duty | 20% share = 100% duty | Game rule: a 20% heater share means the heaters are always on. |

## "Why?" cards

Each gauge has a small (i) button, seven in all:

| Gauge | Where its (i) is |
|---|---|
| Battery | the PWR display header |
| Solar power | the PWR "Panels" row |
| Life support | the LIFE header |
| Dose | the RAD header |
| Heaters | the Heaters switch and the LIFE row |
| Shields (pretend) | the Shields knob |
| Rover and ice | the Rover panel |

The card's words come from `state.why[gauge]`, written by `physics.why()`. Each card has:

- the physics now, in plain words, with one number;
  - on screen it is at most 2 lines;
  - spoken it is at most 20 words, with numbers and units in words ("41 percent", "minus 208 degrees Celsius").
- the formula in plain text;
- the source.

Engineer adds the equation with its numbers.

Example cards:
- "Panels make 41% now: the Sun sits on the ridge, its disk partly hidden (JPL Horizons)."
- "Dark ground here drops to about −208 °C (LRO Diviner). Heaters stop the water freezing."
- "Storm: radiation 8x normal here. LRO's CRaTER saw real storms thousands of times quiet. Shelter!"

Every way of opening a card ends at the same intent, `why {gauge?}`:

| Input | What it does |
|---|---|
| Tap | the (i) button (a tap works from the seat view too) |
| Keyboard | **I**, for the lit or open panel's gauge |
| Controller | D-pad to the (i), then A |
| Gesture | point and dwell on the (i) |
| Voice | "why is power low?", "how come the dose is rising?", "explain the heaters", or a bare "why?" |

- **The router** (`turn_router.py`) recognises `why` in the cabin only, and `why_gauge()` names the gauge. "Why is the sky black" stays a question for the brain.
- **A bare "why?"** picks a gauge in this order: the lit panel, then the Now job, then the alarm.
- **Director coverage** has the probe "why is power low" (`director_model/coverage.py`, `pools_r8.py`).

## Debrief

The debrief now reads in this order:
1. "What happened" (the story);
2. "What the numbers say": 3 to 5 cause-and-effect lines, each with its source;
3. the grade.

The ledger (`Mission.phys`, filled by `physics.account()`) books, every hour:
- the energy made and used;
- the heaters' share;
- each night;
- each storm's dose with and without the shelter.

Sample lines (Engineer, Shackleton Crater Rim, seed 7, a scripted player that shelters on warnings and uses night mode
when the arrays are dark; it survived with grade B):
- "You sheltered for 24 h in the 31 May 2025 storm: dose 2.7 mSv instead of 10.9 mSv." (NASA DONKI)
- "Your heaters used 7.6 kWh over a 53-hour night; the battery dipped to 75%." (JPL Horizons)
- "Your panels made 1804 kWh; the outpost used 2044 kWh." (JPL Horizons)
- "Ice run done. Polar soil is about 5.6% water, so 100 kg of soil gives about 5.6 kg." (LCROSS)
- "Crew dose 16.7 mSv in game units: about 8.4 mSv of real Moon radiation." (Chang'e 4)

The spoken debrief follows the same order: the story's turning point, its biggest number, the grade, then the offer.

## Engineer level (Settings → Level → Engineer)

Engineer is off by default. It plays Commander's missions: the same storms, the same band, and bit-identical physics (`test_engineer_plays_commanders_game`). Cadet and Commander are unchanged.

- **Gauges in real units:**
  - Battery: kWh and % state of charge;
  - Panels, Load and Net: kW;
  - Heaters: kW and % duty;
  - Outside: K and °C (Diviner);
  - Dose: mSv/h.
- **Decisions:**
  - The night checklist becomes a **power budget**: night mode or full power, each shown with its kW and how many hours the battery lasts. Then comes a **heater duty cycle**: 25, 50 or 75%, with the average kW of each.
  - Save power becomes a choice between two cuts, each shown with the kW it saves.
- **Equations:** every "Why?" card and every debrief line shows its equation with the numbers filled in.

## Tests

- `backend/tests/test_physics.py`:
  - sources;
  - physical ranges;
  - card copy rules;
  - Engineer equals Commander;
  - units;
  - the Engineer choices;
  - the LOLA route hints;
  - the debrief lines;
  - the router intent.
- `frontend/tests/physics.test.js`.
- `frontend/tools/mission_ui.py` now also checks that:
  - every gauge has an (i);
  - no (i) crowds its row;
  - the open card stays on screen, clear of the Now panel, the deck and the view bar, at 1024 to 1920 px.
