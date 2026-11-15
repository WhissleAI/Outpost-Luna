# Mission gameplay: the live clock, tasks and the story

Owner: `feat/mission-gameplay`. The owner played the first Cadet mission at Malapert Massif and wrote: *"as a user i am
lost again... it should be simulated in time... and in between that too, we should keep a user busy with some actual
tasks."* The NOW strip kept saying "Set power, then End shift." after they changed the shield power.

The mission used to be turn-based: set loads, press End shift, read a report. Now the mission time runs, short real
jobs fill the long waits, and the story moves through beats.

| Before | After |
|---|---|
| End shift jumps 6 hours | A live clock: about 12 s of real time per sim hour at 1x, with Pause, 1x/2x/4x warp and **Skip ahead** (to the next event). End shift stays as "End shift early". |
| The NOW strip is a static line from the state | The **Now task card**: task, step, progress (2 of 3), time left, the lesson that helps, readouts and the button that does the step. It reacts to every action ("Shields up. Good."). |
| Long things (rover runs, storms, 132 h comm gaps) just pass | Each one is a task with a countdown, or a skip ("Rover driving. Back in 7 hours." with **Skip ahead** lit) |
| No arc | Story beats with a CAPCOM line, a window moment and an objective; progress always on; a mission log |

## 1. The stuck objective (fixed first)

`nowCard(state, clock)` (`frontend/src/mission/objective.js`) is driven by the sim state plus what the kid did:

- The sim counts orders in `State.acted` (`{allocate: n, ...}`). The first job (`first_power`, a gameplay task) is
  "Shields up to 30", but **any** power change completes it, and the sim answers `ack: "Power set. Good."`.
- The card then says "Power set. Now press Play to start the clock." (Play glows), and once time runs, the next live
  task.
- `State.ack {t_h, text, n}` carries the latest acknowledgement. The card shows it for about 4 s, and CAPCOM says it
  once.
- Tests: `backend/tests/test_gameplay.py::test_first_job_reacts_to_any_power_change`, `frontend/tests/story.test.js`.

## 2. The live clock

**Sim** (`backend/app/mission/sim.py`): one hourly tick (`_tick`) is the only place mission time moves. The three ways
to move time all share it:

| API | What it does |
|---|---|
| `sim.step(m, dt_h)` / `POST /api/mission/{id}/step {dt_h}` | Any fraction of an hour (≤ 24). The physics ticks at each whole hour, so the result never depends on how time was sliced. Returns `{state, events, live}`, where `live` is the telemetry frame at the fractional hour (Sun, Earth, bars, rover between hours). |
| `sim.skip_to_event(m)` / `POST /api/mission/{id}/skip` | Run until a `SKIP_STOPS` event (storm warning, storm, storm end, sunset in 6 h, sunset, sunrise, comm open or closed, low power, rover back, failure, a new task, a story beat), for at most 24 h. It never reads the schedule: it runs the hours and stops. |
| `sim.advance(m, n)` / End shift | Run to the next shift boundary: "end shift early". |

New sim event `sunset_soon` fires 6 h before a Horizons sunset (`SUNSET_NOTICE_H`). This is where the night checklist
starts.

**Client** (`frontend/src/mission/clock.js`): `HOUR_MS = 12000`. A shift is 72 s of clock. With its tasks, a shift
takes about 2–4 minutes of play. The clock posts the hours that passed about once a second.

- Controls in the window's top bar: **Play/Pause**, **1x 2x 4x**, **Skip ahead**. A held state shows its reason
  ("Paused for the tour", "Paused: your call").
- **Auto-hold** (`held()` in `mission/ui.js`): the tour, a pending yes/no, a task choice (`State.task.decision`), a
  CAPCOM offer card with live buttons (for up to 30 s), a Cadet offer, the app hidden (`document.hidden`), and any
  screen but the cabin.
- **Warp drops to 1x** when something happens (a storm, a warning, sunset, Earthrise or Earthset, the rover back, a
  beat), as in a console game.
- The mission starts paused. The first jobs are to set power and press Play.
- What moves with the clock: the clock reads `Day 2 · 14:15` and the shift; the Sun and Earth elevations (terrain
  lighting via `tv.setSun` / `setEarth`); the rover along its route (`setRover` with the fractional hour); the resource
  bars (from the `live` frame).

**Strategy guarantees** (`docs/LEARNING_DESIGN.md` §6): stepping a shift in quarter-hour frames is bit-identical to
`advance()`. `test_live_clock_is_the_same_game_as_shifts` checks this, and the old turn loop gives exactly the old
results. `tools/strategy_sim.py --clock shift|live|event` plays every policy under the turn loop, the live clock
(acting at any hour) and skip-to-event. `tests/test_strategy.py` asserts every guarantee under all three:

| Clock (10 seeds × 5 sites) | planner surv / score | best fixed rule score | always_shelter goals | idle surv (Commander) |
|---|---|---|---|---|
| live, Commander | 1.00 / 660 | 407 (reactive) · fixed max 359 (rover_spam) | 0.00 | 0.40 |
| live, Cadet | 1.00 / 680 | 380 (rover_spam) | 0.00 | — |
| event, Commander | 1.00 / 627 | 370 (always_shelter) | 0.00 | 0.40 |
| event, Cadet | 1.00 / 589 | 380 (rover_spam) | 0.00 | — |

The policies never touch a task. Task rewards are small (+2 science per sample or logged reading, a few per mission),
and the kid only gets them by pressing. Only the kid's own play can earn them, so no fixed rule gains from them.

## 3. Tasks (`backend/app/mission/gameplay.py`)

Tasks come from the sim state and the goals, never at random. Each step is one of four kinds:

- **order**: a real sim command. Its `done` re-checks the state, so a voice order, a panel tap, the card's button, a
  key or a gesture all count.
- **choice**: the clock holds while the kid picks.
- **press**: the kid presses the step's button to do it.
- **wait**: the rover is driving, or the storm isn't close yet. **Skip ahead** glows.

| Task | Comes from | Steps (Cadet / Commander) | NASA basis | Lesson |
|---|---|---|---|---|
| Set your power | arrival | Shields up (any power change counts) | — | 4 Power |
| Storm prep | a `storm_warning` | Rover home → (Cmdr: shields to 40) → crew into the shelter, which opens **6 h before** a likely storm; a "possible" storm is a choice: Shelter now / Wait and watch. Countdown = the forecast. | DONKI SEP forecasts; Orion's shelter is good for about a day | 5 Radiation |
| Storm! Shelter the crew | a particle storm hits, crew outside | Rover home → shelter | DONKI | 5 |
| All clear: crew out | shelter, no storm, no warning | Crew out of the shelter | (always_shelter fails the goals) | 5 |
| Night power-down | `sunset_soon`, or dark with night mode off | Night mode on → heaters to 10 → (long night ≥ 48 h, e.g. Malapert: air system to 45) → rover home before dark. Countdown = sunset. | Horizons sunset; landers hibernate (Chang'e 4) | 4 |
| Sunrise: wake the outpost | Sun up, night mode on | Night mode off | Horizons | 4 |
| Save power (Cmdr) | battery < 20% | Science down to 5 (or night mode) | — | 4 |
| Life support check | air < 55% | Cadet: air system to 40, else send the rover for ice; Cmdr: choice Recycler up / Ice run | LCROSS ice | 6 Air, water and ice |
| Comm window | Earth up with science waiting | Radio to 10 (downlink) → call Houston. Countdown = Earth sets. | Horizons Earth elevation; 1.3 s each way | 3 Radio |
| Ice run (rover drive) | ice goal open, calm, rover parked | Cadet: send the rover. Cmdr: pick a route on the **LOLA slope map** (Ridge: flat, +2 h, −2% battery; Crater slope: −2 h, +3% battery). Then **steer past the boulders** (left/right; the slope-map hint names the flatter side; right saves 1 h, wrong costs 1 h, no answer = the rover finds its own way). Then the rover comes back with ice. Readouts: ETA, battery, dose rate. | LRO LOLA slopes plan real traverses (VIPER) | 6 |
| Fix the solar array (Cmdr) | the micrometeorite failure | Check the array → send the rover → test the power | — | 4 |
| Take a sample / Read the radiation sensor | nothing else to do (every 8 h; Cadet ≤ 4, Cmdr ≤ 6) | Sample (+2 science). Cmdr alternates: read the sensor, then log it Normal / High (+2 if right; quiet Sun < 0.1 mSv/h) | Chang'e 4 LND baseline | 1 Moon / 5 |

Cadet gets fewer, simpler tasks with big buttons (no repair, no low-power task, no sensor quiz, no route choice).
Commander gets the trade-offs. A task with a deadline that passes is logged as missed. A storm prep the storm overtakes
becomes "Storm! Shelter the crew". Only the highest-priority open task shows. `tasks_waiting` counts the rest.

**State fields** (additive): `task {id, kind, title, lesson {id, n, title}, panel, level, steps [{id, kind, label, done,
ready, target, cmd?, options?, hint?, wait?}], step, done_count, total, time_left_h, readouts, decision, say}`,
`tasks_waiting`, `ack`, `acted`, `clock {mission_time_h, frac, hours_total, shift_ends_in_h}`, `story`, `mission_log`,
`progress {day, days_done, days_total, science_sent, science_goal, ice, ice_goal}`, and `env.comm_closes_in_h`.

**Commands** (additive): `{"type": "skip"}`; `{"type": "task", "task", "step", "choice?"}` for a press or a choice;
dispatch takes `"route": "ridge" | "slope"` for an ice run.

## 4. Story and pacing

| Beat | When | CAPCOM (≤ 20 words) | Window moment |
|---|---|---|---|
| Arrival | start | Outpost Luna is online. Set your power, then start the clock. | — |
| Settling in | hour 2 | Systems steady. The clock is running. Your jobs show on the Now card. | site |
| On our own | Earth down for 12 h or more | Earth is below the horizon. No radio until it rises. We're on our own. | Earth view |
| First sunset | the first sunset | Sunset. The long dark starts. Night mode keeps the lights on. | dusk tint |
| Storm forecast | the first warning | Houston sees a storm coming. Get ready before it hits. | storm glow |
| Solar storm | the first particle storm | Storm's here! Particles are hitting the outpost. Keep the crew sheltered. | storm glow |
| All clear | that storm ends | Storm's over. Crew out of the shelter. Back to work. | calm |
| Earthrise | Earth back after the gap | Earthrise! Houston can hear us again. Send the science home. | Earth view, blue tint |
| Ice home | first ice delivered | Rover's home with ice. Water and air for the crew. | rover view, rover lights |
| Last downlink | day 9+ with Earth up | Last days. Send every bit of science home. | Earthrise tint |
| Mission complete | survived | Day ten done. The crew made it. Time for your debrief. | — |

- Each beat shows its title and objective over the glass for about 5 s. The view turns to the Earth or the rover for
  6 s, but only from the seat's site view.
- The beat goes into the **mission log**, the Log button on the progress strip. The log also gets each finished task
  ("Ice run complete. Life support up."), each missed one, and each good call.
- The session Director speaks the beats with no sim line of their own (`SPOKEN_BEATS`). Without a session the cabin
  speaks them.
- **Progress is always on**: days survived, science sent (of 120) and ice (of 1), each with a bar.
- **No dead air**: after about 20 s with a job waiting and nothing done, CAPCOM names the job ("Storm prep. Next: Crew
  into the shelter"), at most twice per job. Any order, tap, clock control or word restarts the wait.

## 5. The Now task card

The card shows the task title, the step, step dots ("2 of 3"), the time left (`6 h left`, amber under 2 h), a "Lesson 5
helps here" chip, readouts, the ack, and the buttons. The first button is the hot one and carries `data-intent="yes"`.
The step's control glows on its panel too. On Cadet only that panel stays bright. When nothing is urgent the card says
"All steady. Time warp?" and offers **Time warp 4x** and **Skip ahead**. When the kid has paused the clock it says
"Clock paused. Press Play when you're ready."

## 6. Every input

| Action | Voice | Tap | Keys | Controller | Gesture |
|---|---|---|---|---|---|
| Do the Now step | "yes", "do it", or the order itself | the card's button, or the glowing control | **T** or **Y** | A on the focused button | thumbs up (the card's `data-intent="yes"`), point + dwell |
| Pick a choice | its name ("left", "ridge", "shelter now"; router `task_choice`) | the option | **1–4** | D-pad + A | point + dwell |
| Pause / run | "pause the clock", "start the clock", "resume" | Play/Pause | **K** | View / Share | open palm pauses (and stops speech) |
| Time warp | "time warp four", "normal time" | 1x 2x 4x | **W** | LT / L2 | — |
| Skip to next event | "skip to next event", "skip ahead", "fast forward" | Skip ahead | **E** | RT / R2 | — |
| End shift early | "end shift" | End shift early (pedestal) | — | — | — |

The router adds the cabin-only intents `skip_event`, `time_pause`, `time_resume`, `time_warp {1|2|4}` and
`task_choice` (`backend/app/turn_router.py`). The screen frame carries `offer: "task"` and the choice labels as
`step_options`, so a "yes" is never taken for an echo or a sim confirm.

## 7. Verify

- `backend/tests/test_gameplay.py`: the first job, step/skip/end-early, sunset notice, the API, storm prep, the
  possible-storm decision, the ice run (route, steer, return), samples, the Malapert long night, Cadet < Commander task
  count, copy budgets, and a careful player surviving every site with the full arc.
- `backend/tests/test_strategy.py`: every guarantee × {shift, live, event} clocks, plus bit-identical shifts.
- `frontend/tests/gameplay.test.js`: clock timing, warp, holds, the card model, keys, controller, router intents.
- `frontend/tools/play_mission.py`: a novice plays the whole first mission from the screen only. It logs, per moment,
  what to do, whether it was obvious (a visible, uncovered hot button or glow) and whether the app reacted.
  Screenshots and logs go to `docs/img/gameplay/`.
- `backend/tools/handsfree_run.py`: the voice run now starts the clock, does the card's jobs by "yes" or by naming a
  choice, says "time warp four", "skip to next event" ×3, "pause the clock" and "end shift".

## 8. Round 2: novice playthroughs (fix/gameplay-r2)

Three full first missions were played from the screen only (`frontend/tools/play_mission.py`): Cadet at 1280×720, Cadet at 1440×900, and Commander at 1280×720. Each reached the debrief, and every press got a reaction. Where a kid would get lost, and the fix:

| Where | What a kid would hit | Fix |
|---|---|---|
| Storm prep, waiting for the shelter | The card said "Shelter 6 hours before it hits. Keep working till then." A 7-year-old can't work out when that is, and Skip ahead jumped past it. | The card counts down ("Shelter opens in 4 h. Keep working, or skip ahead."). When the step opens, a `task` event fires with `phase: "ready"`, which stops a skip and drops the time warp to 1×. |
| After a storm | A held CAPCOM "Go to shelter / Set shields to 40" offer arrived hours of sim time late (held on the voice floor for up to 30 s at 4× warp), while the card said "Crew out of the shelter". | The session drops held storm decisions when no storm or warning is on (`Session._overtaken`). The cabin drops a stale storm or night-mode offer (`staleOffer`). |
| Commander life support check | "Recycler up" set 40% when the recycler was already at 40%. It did nothing, and the check came back every 12 h, four times. | The option is a real raise ("Recycler to 50%"). Past 60% only the ice run is offered. |
| An ice run open when a storm came | "Send the rover for ice" during the storm, then a risky-order confirm hidden behind an open panel | The ice run waits out storms and warnings. A Cadet offer returns the seat view once answered. The Now card shows a pending yes/no first. |

## 9. The cabin layout (fix/mission-ui-polish)

The owner played at 1440×879 and found four problems:
- The Now card floated over the windshield and the gauges ("this covered everything").
- Its text collided with the clock strip, and "1x" and "Skip ahead" showed twice.
- The Steer left/right choice had one ring round both buttons ("like i can't control").
- Monospace and sans fonts were mixed.

**Layout.** The glass carries only what belongs to the view: the alert strip, the view tabs (top-right), the rover
pill and the story moments. A story banner ("Day 1 / On our own") has the glass's centre to itself, and the rover pill
steps aside while it shows. The sky readout ("Sun up · Earth below") sits in the deck after the clock, because the
bottom of the glass is behind the consoles. During a storm, Up from the seat goes straight to the alert strip's main
action ("Shelter the crew"). The cabin has two fixed places:
1. **The deck**: one overhead bar with the clock (Day, time, shift and site), the clock state (a lamp and its word:
   Running 2× / Paused / On hold: your choice), Pause/Play, the speed, Skip ahead, the goals (days, science, ice) and
   the mission log. Each control is shown once. The Now panel never repeats a deck control: it lights the deck's
   button and names its key ("Skip ahead is in the clock bar (E)").
2. **The Now panel**: a side display docked on the left wall, under the deck, clear of the windshield and the gauges.
   It has a title, the step, step dots, the countdown, "Lesson N helps here", read-outs and the buttons. A choice puts
   each option on its own numbered button and says what to say ("Say “left” or “right”, or press 1 or 2."). It fits
   itself to the wall above the Habitat console by dropping details in three levels (read-outs and hint, then the meta
   row, then everything but the step and its buttons). It folds to one line (⌃), and that is remembered.

- When a panel is open, the Now panel keeps its step and buttons and drops the rest.
- On a wide window the glass's alert strip starts where the Now panel ends.
- Paused dims the glass a little, and the clock digits stop glowing.

**Type.** Sans for words, tabular figures for numbers; mono only on the instrument read-outs.

**Mute** (top bar, right after Settings): every sound off (voice, chimes, crew clips, media, YouTube embeds), captions
and text kept, mic untouched. The state persists in prefs. Keys: Shift+M (M is the mic). Voice: "mute" / "unmute".

**Checks**
- `frontend/tools/mission_ui.py` is the overlap test. At 1280×720, 1440×879, 1440×900, 1920×1080 and 1024×640 it
  drives the app to the owner's moment (the Steer choice, with a fixed storm schedule). It then asserts:
  - no two HUD elements intersect, including inside the deck;
  - the deck and the Now panel are clear of the windshield centre, the gauges and the consoles;
  - nothing is clipped or off-screen;
  - every control is shown once;
  - no window text (tabs, rover pill, alert strip, story banner) is covered by a 3D console; the check runs again with
    a story banner forced on;
  - the top bar has the Mute button next to Settings and no overlaps.

  Screenshots go to `docs/img/mission-ui/`.
- `frontend/tools/choice_card.py` checks the choice card by mouse (hover and click), keyboard (one ring on one button,
  the arrow moves, Enter presses, the card doesn't rebuild under focus), the number key, a controller (D-pad + A) and
  voice ("right").
- Every Playwright tool imports `frontend/tools/silent.py`, so runs are muted (audio-output flags plus a muting init
  script, with the app's Mute on) and headless.
