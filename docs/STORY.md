# The story of Outpost Luna, told in the app

Owner: story and onboarding (`fix/story-onboarding`). All copy lives in `frontend/src/story.js` (`TRANSITION`, `PICKER`,
`TOUR`, `NOW`, `HELP`, `DEBRIEF`). Budgets are the ones in `docs/COPY.md`: spoken lines 20 words or fewer, tour beats 12 or
fewer, on-screen lines 12 or fewer, no emoji. `frontend/tests/story.test.js` checks them.

**The problem.** The owner entered the cabin, heard "CAPCOM ▸ Outpost Luna is online at Connecting Ridge. Day one,
Crater Cat." and then didn't know what to do. Each screen worked on its own, but nothing said where you were in the
story, why, or what came next.

**The rule.** At every transition, one short beat is spoken and shown on screen. It says where you are, why, and what's
next. The screen's own button is the next action, so a beat never explains the button. No screen ends without an obvious
next action, and saying "what do I do?" on any screen outside a lesson speaks that screen's next job.

## 1. The arc

| # | Stage | Where | Why | Ends with |
|---|---|---|---|---|
| 0 | **Kid** | Home: pick a call sign | Every crew member has a radio name | Start |
| 1 | **Cadet** | Flight School: the Moon map, one pin per lesson | Learn the Moon from real crew voices and NASA data; each lesson earns a patch | the next lesson |
| 2 | **Check ride** | One solo shift in the cabin at Shackleton Rim | Prove you can run the outpost; CAPCOM only watches | Qualified: the Mission Commander patch |
| 3 | **Commander** | Pick a site, then run Outpost Luna for 10 days | Keep the crew safe, send science home, bring back ice | Finish mission (or the mission ends) |
| 4 | **Debrief** | What happened, in three beats, plus one thing to try | Failure is how you learn; each ending teaches something | **Fly again** (one clear choice; "Pick a new site" is a quiet link) |
| 5 | **Again** | The same site, or another one | Each site is a different puzzle (Sun, Earth, ice) | back to 3 |

`BEATS` (Flight School, Check ride, Command, Debrief) and `ARC_STEP` give the "Step N of 4" eyebrow on the map.

## 2. The transitions

| Transition | Spoken | On screen | Next action |
|---|---|---|---|
| First launch → map | "Copy that, Nova. Welcome to Flight School." · "Each pin on the Moon is a lesson. Earn the patches, then command the outpost." · "Ready for lesson one?" | Map beat: **Step 1 of 4 · Flight School**, "Earn a patch at each pin. Then fly your check ride." | Start on the Next-up card, or "next" |
| Map → lesson | `CAPCOM.lessonHello` + the lesson's story beat ("Radio check. Houston is 384,000 km away. Here we go, Nova."). CAPCOM speaks every beat, so beats are first person or plain statements, never narrator copy ("CAPCOM pulls up a map" became "Let's start with a map of the Moon"), and the only questions are offers the router waits for, then the brief and the question | the lesson card | the step |
| Lesson → patch | "Patch earned: Radio Ready. Nice work, Nova." · "Ready for the next lesson?" | "3 of 7 patches. 4 lessons to go." under the patch | Next: *lesson*, or "next" |
| Patch → map | none (the kid chose the map) | the Next-up card | Start |
| Last lesson → ride | patch line · "Your check ride is next: one solo shift. Pass it to take command." · "Ready for your check ride?" | map beat **Step 2 of 4 · Check ride**, "One solo shift. Pass it and you take command." | Next: Check ride |
| Ride → qualified | "Mission Commander patch earned. You're qualified, Commander Nova." · "Ready to take command?" | "Next: pick a site and run Outpost Luna for 10 days." | Take command |
| Qualified → picker | "Pick a site, Commander Nova. Keep the crew safe for ten days." · "Sun means power. Earth means radio. Pick your trade-off." | sub line "Sun means power. Earth means radio. Pick your trade-off."; a first-timer sees a **Best first pick** tag on Shackleton Rim (preselected) and hears "For a first mission, try Shackleton Rim: Sun all 10 days." | Take command |
| Picker → cabin | "Outpost Luna is online at Shackleton Crater Rim. Day one, Nova." then the **tour** (first mission) or the objective line | the cabin, with the **Now** strip | the glowing control |
| Cabin → debrief | "Mission complete. Nice flying, Nova. Grade B, 512 points." · the storm beat · "*try line* Fly again?" | **What happened** (3 beats) + **Try next** | Fly again |
| Debrief (paused) → cabin | "Paused on day 2. Your outpost is waiting. Back to the cabin?" | the same story; the button is **Resume mission**. Fly again or Pick a new site first asks "Start over? This mission ends, and you begin again at shift 1." (QA-26) | Resume mission |

## 3. The first-mission cabin tour (`frontend/src/mission/tour.js`)

On the first mission, CAPCOM shows the cabin before the first shift. Each beat lights one thing (an outline and a pulse,
never colour alone), turns the camera a little toward it, and on Cadet keeps every other panel dim. The card is small and
docks in the window just under the HUD (day, shift, site, sky readout), so it never covers them; it re-docks as the
camera settles. While it runs the Now strip steps aside. Moving on (Next, skip) stops the beat still being spoken.

**Cadet (full, 12 beats):**

| # | Lights | Line (spoken and shown) |
|---|---|---|
| 1 | the window + Orbit/Site/Rover/Earth | This is your window. Switch views: Orbit, Site, Rover, Earth. |
| 2 | display 1 | Your three screens. First, power: the battery the Sun fills. |
| 3 | display 2 | Life support: the air and water your crew needs. |
| 4 | display 3 | Dose: the radiation your crew has taken. Keep it low. |
| 5 | Power panel (display 1 + the split) | Power panel: pick a system, then press plus or minus. |
| 6 | Habitat | Habitat: heaters, science, and your mission goals. |
| 7 | Rover | Rover: send it for ice, then bring it home. |
| 8 | Radiation | Radiation: shields, and the storm shelter under its cover. |
| 9 | Comm | Comm: call Houston when Earth is in view. |
| 10 | caution & warning lamps | Warning lights. Red means act now. Amber means get ready. |
| 11 | the goals (Habitat) | Your goal: ten safe days. Send science home. Bring back ice. |
| 12 | display 1 + End shift | First job: set power, then press End shift. |

**Commander (2 beats):** "Window up top. Three screens below. Five panels around you." · "Ten safe days, science home,
ice back. First: set power, End shift."

- **Move on:** the Next button, Enter, voice "next" / "yes", a swipe (next) or a thumbs up (yes). While the tour runs it
  has the intent bus first (priority 20), so a swipe never changes the window view mid-tour.
- **Skip:** "skip tour" / "skip" (router `skip_tour`, cabin only; a bare "skip" only while the tour runs), "no", or the
  Skip tour button.
- **Replay:** "show me around" / "give me the tour" (router `cabin_tour`, cabin only), or Settings → Help → **Show me
  around** (outside the cabin it switches to Mission and plays on the next cabin visit).
- **Remembered** per cadet: `localStorage["outpost-tour-done:<call sign>"]` (try/catch). Skipping counts as done.
- **Hands-free:** the screen frame carries `offer: "tour"`, so the kid's "next" right after a beat ends is never taken for
  an echo, and "yes" is not sent to the mission as a confirm.
- After the tour, CAPCOM says the objective once and the first-shift nudge starts (unchanged: one repeat after ~20 s of
  silence, at most twice).

## 4. The "what now" strip (`frontend/src/mission/objective.js`)

A small, quiet pill at the bottom of the window: **NOW** + one line. It is picked from the sim state on every update.
The control it names glows, and on Cadet its panel stays bright while the others dim (a panel with an alarm is never
dimmed). Most urgent first:

| When | Now | Glows |
|---|---|---|
| a storm is hitting, crew outside | Storm hitting. Get the crew into the shelter. | Shelter switch |
| storm, crew sheltered | Crew sheltered. End shift to ride out the storm. | End shift |
| a storm warning | Storm in about 6 hours. Get ready: shields or shelter. | Shields knob (Shelter once shields ≥ 40) |
| low power | Battery low. Turn on night mode, or cut a load. | Night button |
| low air | Air is low. Send the rover for ice. | Rover: Ice |
| rover out, dark before it's back | Rover out. Bring it home before dark. | Rover: Home |
| rover out | Rover out, back in 8 hours. End shift to wait. | End shift |
| sunset ≤ 6 h | Sunset in 4 hours. Turn on night mode before dark. | Night button |
| dark, night mode off | Dark outside. Night mode saves power. | Night button |
| first shift | Set power, then End shift. | End shift |
| ice goal not met, in sunlight | No storm due. Send the rover for ice. | Rover: Ice |
| otherwise | All steady. End shift to move on. | End shift |

"What do I do?", "help", "I'm lost", "what should I do", "what's my job" take one path on every screen (rc/2): the
router's `a11y` intent → the client's a11y `help` command → `window.__outpost.help` (main.js). In the cabin that is
`missionUI.whatNow()`: "Here's your next job." plus the strip's line; the picker and debrief have their own lines. In
Flight School it is guidance's `help()` (the hint ladder in a lesson or the ride, the map and patch lines). The a11y
"what can I do" also answers with the job first in the cabin. A gesture `help` intent reaches the same lines.

## 5. The seat view, less noisy

Before → after: `docs/img/story/before-cabin-1280-dark.jpg` → `docs/img/story/after-objective.jpg`.

- **Seat view shows big numbers and controls only.** Detail rows, the rover route, the comm timeline, the forecast
  list, the goals list, the power split, "Pretend tech" tags, switch state words and the Finish mission button wait
  until a panel is opened (clicking a panel opens it, as before). The three displays show one big number and its bar.
- **Unlit warning lamps are faint** at the seat; lit ones are unchanged.
- **Cadet progressive disclosure:** only the panel the tour or the objective points at is bright.
- **Label hierarchy:** the panel chips (HABITAT, ROVER, RADIATION, COMM, DISPLAYS, SHIFT) are the only labels at the
  seat; the Caution & warning heading shows when the pedestal is opened.
- Fix: a storm warning showed "NaN% sure" (the sim sends `confidence: "likely" | "possible"`). It now says
  "Storm warning · Likely".

## 6. Verify

- `frontend/tests/story.test.js`: copy budgets, tour beats, every objective, the debrief story.
- `backend/tests/test_story_router.py`: help on one path everywhere (lessons included), `cabin_tour`, `skip_tour` cabin-only, echo-safe "next".
- `backend/tools/handsfree_run.py`: the scripted run now takes the cadet tour by voice ("next" × 12, with noise
  mid-way) and asks "what do I do?" in the cabin. It FAILs if the tour isn't finished by voice.
- Screenshots: `docs/img/story/` (each tour beat, the objective strip, the picker, the debrief).

## 7. QA sweep fixes on this branch

QA-02 (CAPCOM speaks as CAPCOM), QA-23 (alert strip no longer covers the clock), QA-24 (Sun up/down, not "Sun −1.1°" at a
lit ridge), QA-25 (Pretend tech tags wherever shields or the greenhouse show), QA-26 (no wiping a paused mission without
asking), QA-27 ("Storm at Earth · Few particles here" for storms without particles), QA-64 (warning copy: "Houston: particles likely
within hours. Forecast: N hours (game)."), QA-69 (buttons start with a verb), QA-73 (the owner's "no
direction" report). Status lines are in `docs/QA.md`.

## 8. Owner's first-timer play of rc/2 (fixed on rc/3)

| Issue | Fix | Check |
|---|---|---|
| Picker ICE column spilled past the card ("6 h away") | "Ice / away" header, values "6 h" / "Here" / "No", wider column | `frontend/tools/picker_select.py` (1440x900, 1280x720) |
| "take command" started Malapert, not the preselected Shackleton Rim | start() flies the row shown checked; hover only highlights; "start the mission" on the picker is take-command | `picker_select.py`, `backend/tests/test_playtest_rc3.py` |
| The tour card covered "Day 1 · Shift 1" and the site | the card docks under the HUD | `frontend/tools/tour_clear.py` (all 12 beats) |
| Silent orders: no readback for "more power to the heaters", a silent first "end shift" | the floor's TTS fetch times out after 8 s (browser voice for that sentence) and a clip that never ends releases the floor; the first-shift nudge and the objective lines are proactive (priority 4: they wait, never cut a readback); any order stops the nudge; the tour hushes its beat when the kid moves on | `frontend/tools/orders_spoken.py` (each readback and report plays to its end) |
| A wrong tap said "Not there." with Mare Imbrium right there | a named place within 5 degrees of its rim (or the client's nearest named place) leads the line: "That's Sea of Rains." | `test_playtest_rc3.py` |
