# Outpost Luna: learning and game design (v3)

2026-11-13 · Owner: learning/game design (`feat/learning-v3`) · Status: **phase 2 built** (§10 says what shipped and what changed from the phase 1 design).
Inputs: `docs/ADVISOR_BRIEF.md`, `docs/HANDSFREE.md`, `docs/VOCABULARY.md`, `docs/COPY.md` (`feat/copy-v3`),
`backend/data/academy/course.json`, `backend/app/mission/sim.py`, and the data in `backend/data/`.

**The problem in one line.** Today Flight School is a quiz: 31 steps, and 28 of them are `choice`, `keywords`, `command` or vocab
drills on a text panel; only 3 ask the kid to touch the Moon. Crew audio plays in 3 of the 31 steps. The mission can be
"won" by never leaving the storm shelter.

**The fix in one line.** Every lesson becomes a short Moon adventure on the globe: hook with a real crew voice, have the kid
*predict*, *move the Moon* to check, reveal the real NASA number, and earn a patch that gives a real tool in the
mission. The mission is retuned so that reading the data beats every fixed rule.

---

## 1. Learning goals

Each goal is checked twice: once in a lesson (L1–L7, CR = check ride) and once in the mission, where it changes a decision.

| # | A kid leaves able to… | NASA STEM theme | Taught in | Used in mission | Real data in this repo |
|---|---|---|---|---|---|
| G1 | Say that the Moon keeps one face to Earth, and that the far side is not dark | Moon motion, tidal locking | L1 | Picking a site: why the Earth-facing side can talk to Houston | `glossary.json` (far side), `places.json` (lon), new `learning/concepts.json` (NASA Moon facts) |
| G2 | Point to where day meets night (the terminator) and explain that it moves | Light and shadow, phases | L3 | Sunrise/sunset events; the cockpit's Sun strip | Horizons `sun_elev_deg`; globe Sun direction; Glover clip |
| G3 | Explain why the Sun stays low at the south pole, so sunlight depends on height and place | Sunlight at the poles | L3 | Site choice; power planning | `mission/sites.json` (Bussey 2010 %), Horizons ephemerides |
| G4 | Plan for the dark: store energy, power down, keep heaters on | Engineering trade-offs, energy | L3 | Malapert's 157-hour night; night mode | `ephemeris_malapert_massif.json` (`longest_dark_h` calc) |
| G5 | Say why there is ice in craters that never see the Sun, and how NASA found it | Water, the south pole | L5 | Rover ice runs; Shackleton Floor site | LCROSS (`artifacts.json`, NSSDCA), M3/Chandrayaan-1 source in `sites.json` |
| G6 | Say that the Moon has no magnetic field or thick air, so solar particles reach the ground; regolith stops them | Radiation, space weather | L4 | Storm warnings, shelter, shields | `radiation.json` (Chang'e 4 LND, NTRS regolith), `donki_events.json` |
| G7 | Act on a warning *before* the hit, and weigh a forecast's confidence | How missions make decisions | L4, CR | Storm warnings with lead time and confidence | DONKI SEP/CME records |
| G8 | Explain that radio needs Earth in the sky (or a relay), and that it takes about 1.3 s each way | Communication | L2 | Comm windows; sending science home; Houston forecasts | Horizons `earth_elev_deg`; `capcom.MOON_ROUND_TRIP_MS` |
| G9 | Use radio words: copy, roger, say again, and a readback | Teamwork, procedures | L2 | Every order (the Director reads back) | Artemis II "loud and clear" audio |
| G10 | Tell the story Apollo → Artemis II → Artemis III, in order, with one thing each taught the next | History of exploration | L6 | Debrief "what a real crew did" lines | `artifacts.json` (NSSDCA), crew clips (Lovell, Duke, Apollo 13 record) |
| G11 | Describe a place with crew words (mare, albedo, basin, ejecta, earthrise, regolith) | Observation, vocabulary | L7, in context in all | The cabin labels and CAPCOM's lines | `glossary.json` + the crew clip where each word is said |

Standards hooks for teachers: NGSS 1-ESS1-1 (patterns of Sun and Moon), 5-ESS1-2 (day/night, shadows), MS-ESS1-1
(Moon phases), MS-ETS1-1/-2 (design under constraints). Field School (§12) adds MS-ESS1-3 (scale and properties of
features: describing size, shape, brightness) and HS-ESS1-6 (planetary surfaces and rocks as evidence for early history:
impacts, lava, superposition, sample ages). We cite them; we don't claim alignment review.

## 2. Pedagogy: what we do and why

| Principle | What it means for 7–12 | How Outpost Luna does it | Source |
|---|---|---|---|
| Retrieval beats re-reading | Recalling something fixes it better than hearing it again | No "fact slides". Facts come *after* a guess or an action, as the reveal. The NASA facts stay in the disclosure for teachers | Roediger & Karpicke 2006, *Psych. Science* 17(3) |
| Predict → observe → explain | A wrong guess you check yourself teaches more than a told answer | New `predict` step: the kid commits ("Will the Sun set at Malapert?"), the globe or the data shows it, and CAPCOM explains in one line. **A prediction is never marked wrong**: it is "your guess" vs "the data" | White & Gunstone 1992, *Probing Understanding*; NASA STEM "Predict, observe, explain" activity format |
| Show, then ask | Young kids need to see a thing before they can name it | Every find or tap step first flies the globe or plays the crew; the question follows | Mayer, multimedia learning (signalling, temporal contiguity) |
| Short loops | Attention at 7–9 is short; finishing feels good | 3–5 minutes per lesson, 4–5 steps, about 40 s per step; a patch at the end of each | Cognitive load theory (Sweller); NASA STEM classroom activity lengths |
| Immediate, concrete feedback | "Correct" teaches less than "Yes: 157 hours, more than 6 days of night" | The success line carries the number or the fact. After 3 misses, CAPCOM **shows** the answer on the globe and moves on (no dead ends) | Hattie & Timperley 2007, feedback |
| Spacing and callbacks | Meeting an idea again later makes it stick | The mission calls back each lesson at the moment it matters: "Remember Malapert's long night? Sunset is in 6 hours." | Cepeda et al. 2006, spacing effect |
| Agency | Kids learn more when choices are theirs | Predictions, route choices, site choice, and a mission where there is no single correct script | Self-determination theory (Deci & Ryan) |
| Real over invented | Real voices and real dates feel important | Every hook is a real Artemis II recording; every number has a NASA (or cited peer-reviewed) source | Challenge brief; `docs/ADVISOR_BRIEF.md` |
| Low reading load | Many 7-year-olds can't read the panel | Everything spoken; captions on; options numbered for "option 2"; prompts ≤ 90 characters (`docs/COPY.md`) | `docs/ACCESSIBILITY.md` |

## 3. The globe as the teaching surface

Eight verbs. Each is a step type (graded on the server) or a globe directive (a camera move with no grading). The globe
does the motion first, then the step waits for the kid.

| Verb | By voice | By tap or keyboard | What the globe does | Graded by | Kind |
|---|---|---|---|---|---|
| **V1 Find a place** | Name it: "Aristarchus", "where Apollo 11 landed" (gazetteer aliases) | Tap it; Tab cycles the pins, Enter picks | Flies to it and rings it after the answer; on a miss, pulses a hint ring around the right area | existing `intent` / `tap` (gazetteer match, or tap within `radius_deg`) | existing |
| **V2 Turn the Moon** (near/far side) | "show me the far side", "turn it around", "the side we see" | Drag to rotate, or tap the **Near / Far** toggle; keyboard ← → rotates 30° | Animates a half-turn; a small Earth marker shows which way Earth is | new `globe_side` {want: near\|far}: the voice side word, the toggle, or the camera's centre longitude (far: \|lon\| > 110°, near: \|lon\| < 70°) | new |
| **V3 Follow the sunlight** (terminator) | "the terminator", "where day meets night", or name a place on the line | Tap on the line | Sets the Sun direction (a sub-solar longitude); the line is the real day/night edge; optional slow sweep to show it move | new `terminator` {sun_lon, tol_deg}: tap within `tol_deg` of the great circle 90° from the sub-solar point; or the word "terminator"; or a named place within `tol_deg` of the line | new |
| **V4 Compare two sites** | Name one: "Malapert", "the rim" | Tap one of the two lit cards (or pins) | Shows both sites, each with a data chip (sunlight %, Earth-up %, distance to ice) **after** the answer | new `compare` {places:[a,b], answer, metric}: tap/choice id or the spoken name; options carry `place` | new |
| **V5 Trace a route** | Say the stops in order: "Orientale, then Ohm" | Tap the stops in order (each tap draws the next leg) | Draws the leg as each stop is hit; the finished line is the reveal (e.g. Integrity crater halfway) | new `route` {stops:[ids], ordered}: stops matched in order from taps, or gazetteer hits in the words in order; partial credit lists the next stop | new |
| **V6 Zoom from orbit to the site** | "zoom in", "land", "go" | Tap **Zoom**, or the site | Orbit view → south-pole view → site, in 3 short moves | not graded (directive `globe.do: "zoom"`) | directive |
| **V7 Spot the difference** | Say what changed ("the shadow moved", "the dark spot") or option 2 | Tap an option | Shows the same view twice (two Sun angles, or near side vs far side) | existing `choice` + directive `globe.do: "pair"` | directive + choice |
| **V8 Earth-in-view check** | "yes", "no", "sometimes" | Tap Yes / No / Sometimes | Puts a little astronaut at the place and shows Earth's direction (above or below the horizon) | new `earth_view` {place, answer}: answer is computed from the place's longitude, not typed in: near side (\|lon\| < 80°) yes, far side (\|lon\| > 100°) no, limb and poles "sometimes" (libration) | new |

Pole view: `globe.flyTo` clamps latitude to ±75°, so the south pole can't be seen from above. V1/V6 at the pole need a
**`globe.poleView("south")`** (camera over the pole, up = toward lon 0). V3 needs **`globe.setSunDir(lat, lon)`** in
explorer mode (today the Sun is fixed at 10°N 40°W). Both are small additions to `frontend/src/globe.js` (§9).

## 4. Real crew clips as story beats

All ids are from `backend/data/clips_manifest.json`; times are the Moment cuts in `data/index/clips.json`
(`app/moments.py`), all `kid_safe`. Speakers are named only where the clip says who is speaking or is a named message;
otherwise it is "an Artemis II astronaut".

| Lesson | Role | Clip id | t0–t1 (s) | Who | What the kid hears → what they do |
|---|---|---|---|---|---|
| L1 Moon | hook | `hansen` | 0.0–24.9 | Jeremy Hansen | Finding Neil Armstrong in an encyclopedia → "Let's find where he landed" |
| L1 Moon | reward | `orientale-basin-ejecta-extent` | 1.1–22.4 | Artemis II astronaut | "Orientale is the primary feature of the far side" → after turning to the far side |
| L2 Radio | hook | `loud-and-clear` | 0.4–21.3 | Crew and Houston | "Houston, we have you loud and clear… Houston copies all" (already used) |
| L3 Sun | hook | `features-along-terminator` | 47.3–54.5 | Victor Glover (names himself at 1.1 s) | "The terminator is just unreal" → find the terminator |
| L3 Sun | reward | `aristarchus-plateau-imaging-mare` | 145.0–169.4 | Artemis II astronaut | "Get the terminator real quick… just ridiculous" |
| L4 Storms | hook | `observing-pulsating-streamers-suns` | 0.0–22.6 | Artemis II astronaut | The Sun's glow "pulsing" during the eclipse → "The Sun is restless" |
| L5 Ice | hook | `impact-flashes-observing-moons` | 0.6–22.2 | Christina Koch (names herself) | Watching for impact flashes → "In 2009 NASA made an impact on purpose" |
| L6 Apollo | hook | `lovell` | 4.6–26.0 | Jim Lovell | "Welcome to my old neighborhood… Apollo 8" (already used; fix caption names, §7) |
| L6 Apollo | route | `naming` | 40.5–54.9 | Artemis II crew | "Look at Orientale… draw a line straight up to Ohm… an unnamed crater… Integrity" → trace the route |
| L6 Apollo | reveal | `apollo13-record` | 0.5–25.0 | Houston CAPCOM | Apollo 13's 1970 distance record → Artemis II passes it |
| L6 Apollo | question | `duke` | 5.6–21.3 | Charlie Duke | "John Young and I landed… in 1972" (already used) |
| L7 Words | hook | `aristarchus` | 25.4–44.0 | Artemis II astronaut | "Very high albedo… hummocky" → find Aristarchus, then the word |
| L7 Words | word | `crew-reacts-joyfully-earth` | 0.5–20.6 | Artemis II crew | "That is the Earth… poking out from behind the Moon" → earthrise |
| L7 Words | word | `vavilov-crater-central-peaks` | 11.8–23.9 | Christina Koch | "It has a central peak" (optional 5th step) |
| CR | pass | `good-burn` | 0.6–8.4 | Crew | "Integrity looks like a good burn" → patch |
| Mission | start | `full-send` | 23.1–31.9 | Crew | "Go for launch. Full send." → outpost online |
| Mission | comm window opens | `crew-reacts-joyfully-earth` | 0.5–20.6 | Artemis II crew | Earth rising = radio is back (the real reason comm windows exist) |
| Mission | comm window closes | `observing-earthset` | 9.4–33.0 | Victor Glover | "We're going to see Earthset" = no radio until it rises |
| Mission | survived | `splashdown` | 0.9–24.9 | Houston | "Splashdown confirmed" → the debrief |

Rules: a clip plays at most once per lesson, ≤ 25 s, is skippable ("skip"), always captioned, and its transcript is the
caption. Clips never carry an answer the kid hasn't been asked yet.

## 5. Lesson redesign

> **Shipped version (v4, §11):** 6 core lessons, then the check ride: `moon`, `phases`, `power`, `comms`,
> `radiation`, `life`, `checkride`. Two explorer lessons, `gravity` and `history`, unlock after missions 1 and 2.
> 9 patches in all. Phase 2 shipped 6 lessons and the ride. The `words` lesson is gone and its words are woven in (product owner, §9.4). Each
> lesson has a `place` pin. The authored source is `backend/tools/build_course.py`, and §10.2 lists the changes from
> the drafts below.

Seven lessons plus the check ride (8 patches, as today). **Lesson ids and patch ids stay** (progress, tests, routing).
Titles are copy-v3's. Each lesson: hook (clip or question) → 4–5 steps, no two in a row of the same type → a real-data
reveal → patch. Wording below is draft; the copy agent owns final wording (`docs/COPY.md` §3 budgets).

Step-type key: **find** (`intent`/`tap`), **side**, **term**(inator), **cmp**, **route**, **earth**, **predict**, **choice**,
**cmd**, **read**(back, `keywords`), **vocab_***. A step marked † replays the same globe view as the reveal.

### L1 `moon` · Know your Moon · patch Moon Scout · ~4 min
Hook: `hansen` 0–24.9 s. Brief: "The Moon always shows Earth the same face. Let's explore both sides."

| # | Type | Globe | Prompt (draft) | Answer | Real-data reveal (success line) | Source |
|---|---|---|---|---|---|---|
| 1 | find | near side, lit | Find where Apollo 11 landed. | `tranquillitatis` (aliases: Armstrong, first landing) | "Copy. The Sea of Tranquility, July 20, 1969. A mare: a plain of old lava." | NSSDCA Apollo 11; `facts.json` |
| 2 | earth | astronaut at Tranquility | Standing here, can you see Earth? | yes (computed: lon 23°) | "Yes. Earth hangs in the same spot in the sky." | NASA Moon facts (tidal locking) |
| 3 | predict | — | Do we ever see the far side from Earth? | Never / Only at full Moon / Every month → *Never* | "Never. The Moon turns once for each trip around Earth." | NASA Science: Moon (tidal locking) |
| 4 | side | half-turn | Turn the Moon to show the far side. | far | Clip `orientale-basin-ejecta-extent` 1.1–22.4. "The far side gets sunlight too. It's just turned away." | IAU; glossary "far side" |
| 5 | find † | `poleView("south")`, zoom | Now find the south pole, inside the gold ring. | `shackleton` | "Roger. Shackleton, 21 km wide. Our outpost goes here." | IAU Gazetteer 5450 |

### L2 `comms` · Talk on the radio · patch Radio Ready · ~4 min
Hook: `loud-and-clear` 0.4–21.3 s. Brief: "Radio is noisy. Short words and readbacks keep everyone safe."

| # | Type | Globe | Prompt (draft) | Answer | Reveal | Source |
|---|---|---|---|---|---|---|
| 1 | choice | — | What does "copy" mean on the radio? | I heard you | "Copy means I heard you." | Artemis II audio |
| 2 | read | — | CAPCOM: "Commander, set the shields to 40 percent." Read it back. | shields + 40 | "Good readback." | — |
| 3 | predict | Earth–Moon line | How long does your voice take to reach Earth? | About 1 second / 1 minute / 1 hour → *1 s* | "About 1.3 seconds each way, at the speed of light." | 384,400 km ÷ c (NASA Moon facts) |
| 4 | cmp | rim and Malapert | Which outpost can talk to Houston more? | `malapert_massif` | "Malapert. Earth was up 93% of our April window; the rim, 45%." | JPL Horizons (`sites.json`) |
| 5 | read | — | The radio crackled. Ask CAPCOM to repeat. | say again | "Copy. Say again." | — |

### L3 `power` · Power from the Sun · patch Sun Tracker · ~5 min
Hook: `features-along-terminator` 47.3–54.5 s. Brief: "Solar panels need sunlight. At the pole, the Sun skims the horizon."

| # | Type | Globe | Prompt (draft) | Answer | Reveal | Source |
|---|---|---|---|---|---|---|
| 1 | term | Sun set to a quarter phase | Tap the line where day meets night. | within 8° of the terminator, or "terminator" | "That's the terminator. It sweeps around once a month." | Glossary; 29.5-day lunar day |
| 2 | predict | pole view, Sun low | At the south pole, how high does the Sun climb? | Overhead / Just above the horizon / Never rises → *just above* | "It stayed within about one degree of the horizon all April window." | JPL Horizons ephemeris |
| 3 | cmp | rim and Malapert, Sun chips | Which site stayed sunny for our 10 days? | `shackleton_rim` | "The rim. Malapert had sun only 35% of the time." | Horizons (`window_sunlit_pct`); Bussey 2010 for the long-term 86% / 73% |
| 4 | cmd | Malapert, Sun sinking | Night is coming. Move power to the heaters so the pipes don't freeze. | allocate heaters, more | "Copy. Malapert's night lasted 157 hours." | `longest_dark_h` calc |
| 5 | vocab_listen (optional) | — | Which word: the line between day and night? | terminator | in context, after step 1 | crew clip |

Reward clip: `aristarchus-plateau-imaging-mare` 145.0–169.4 s.

### L4 `radiation` · Radiation and storms · patch Storm Watcher · ~4 min
Hook: `observing-pulsating-streamers-suns` 0–22.6 s. Brief: "The Sun sometimes throws out fast particles. On the Moon, nothing stops them."

| # | Type | Globe | Prompt (draft) | Answer | Reveal | Source |
|---|---|---|---|---|---|---|
| 1 | predict | Earth with field lines vs Moon | Earth has a magnetic shield and thick air. Does the Moon? | Yes / No → *No* | "No. Solar particles reach the ground." | `radiation.json` (Zhang 2020); NASA "Why space radiation matters" |
| 2 | choice | — | Houston says particles may arrive in 6 hours. When do you shelter? | Now / When it hits / Never → *Now* | "Right. Get ready before the storm hits." | DONKI (flare → SEP lead) |
| 3 | cmd (alert) | — | ALERT! The real storm of May 2024 is here. Your order? | shelter on | "Shelter. Soil overhead stops most storm particles." | NTRS 19890004839; DONKI |
| 4 | choice | — | What does mSv measure? | radiation dose | "A dose. One mSv is about 10 chest x-rays." | NASA "Why space radiation matters" |

Copy note: "the May 2024 storm" is a solar particle event that **also** caused a G5 storm at Earth. Don't call it "G5 at the outpost" (§7).

### L5 `life` · Air, water and ice · patch Ice Hunter · ~4 min
Hook: `impact-flashes-observing-moons` 0.6–22.2 s. Brief: "Water is heavy to launch. Ice on the Moon can become water and air."

| # | Type | Globe | Prompt (draft) | Answer | Reveal | Source |
|---|---|---|---|---|---|---|
| 1 | predict | — | Why would NASA crash a rocket into a dark crater? | To dig up hidden ice / To test brakes / To make a crater for fun → *ice* | "To see what was buried. LCROSS found water." | NSSDCA LCROSS |
| 2 | find † | `poleView`, LCROSS marker | Find where the LCROSS rocket hit. | `lcross_centaur_impact` (also `lcross_impact`) | "Cabeus crater, 2009." | `artifacts.json` |
| 3 | cmp | rim and Malapert to Shackleton | Which outpost is closer to the ice in Shackleton? | `shackleton_rim` | "The rim: about 10 km. Malapert: about 130 km." | computed from `sites.json` + IAU (calc `dist_km`) |
| 4 | cmd | rover path drawn | Life support is low. Send the rover for ice. | dispatch collect_ice | "Rover rolling. Ice means water and oxygen." | — |

### L6 `history` · Lessons from Apollo · patch Historian · ~5 min
Hook: `lovell` 4.6–26.0 s. Brief: "Every mission teaches the next one. Follow the crews."

| # | Type | Globe | Prompt (draft) | Answer | Reveal | Source |
|---|---|---|---|---|---|---|
| 1 | route | far side | The crew named a crater. Trace it: Orientale, then up to Ohm. | stops [`orientale`, `ohm`] | Plays `naming` 40.5–54.9; rings Integrity halfway. "They proposed the name Integrity." | Crew audio; name not IAU-approved yet |
| 2 | choice | flies to Surveyor 3 | What did Apollo 12 take home from Surveyor 3? | its camera | "Its camera, to see how parts aged on the Moon." | NSSDCA Surveyor 3 |
| 3 | predict | — | Apollo 13 went farther from Earth than anyone. Did Artemis II beat it? | Yes / No → *Yes* | Plays `apollo13-record` 0.5–25.0. "Yes, in April 2026." | Artemis II audio |
| 4 | choice (clip) | flies to Apollo 16 | Listen to Charlie Duke. Who landed with him? | John Young | "John Young. They drove 26.7 km." | NSSDCA LRV |

### L7 `words` · Space words · patch Word Explorer · ~4 min
The words lesson stops being a drill: each word comes from a crew clip and a place on the globe.

| # | Type | Globe | Prompt (draft) | Answer | Reveal | Source |
|---|---|---|---|---|---|---|
| 1 | find | near side | The crew saw a very bright spot. Find Aristarchus. | `aristarchus` | Clip `aristarchus` 25.4–44.0 | Crew audio; IAU |
| 2 | vocab_match | stays on Aristarchus | What does "albedo" mean? | how bright a surface is | "Aristarchus has a high albedo." | glossary + clip |
| 3 | find (tap) | near side | Tap a dark mare. | any of `imbrium`, `tranquillitatis`, `crisium`, `humorum` | "Dark lava plains, low albedo." | IAU |
| 4 | vocab_fill | Earth rising over the limb (V8 visual) | Earth comes up over the Moon's edge: an ____. | earthrise | Clip `crew-reacts-joyfully-earth` 0.5–20.6 | crew audio |
| 5 | vocab_say | — | Say it back: regolith. | regolith | "The dusty soil your shelter is buried under." | glossary |

### CR `checkride` · Check ride · patch Mission Commander · ~5 min
Keep the 4 orders; fix the facts and add one decision with uncertainty.

| # | Type | Change |
|---|---|---|
| 0 | predict (new) | "Earth is below your horizon. Can Houston warn you about storms?" → No (no relay yet). Reveal: "So we start when Earth is up." |
| 1 | cmd | "Houston sees a flare. Particles likely in 6 hours." → shields more (or shelter now: **both pass**; the debrief notes the trade) |
| 2 | cmd (alert) | Shelter on. The storm is the real May 2024 solar particle event |
| 3 | cmd | Leave the shelter |
| 4 | cmd | Rover for ice |

Ride fix: the ride starts at mission hour 138 at Shackleton Rim, when Earth is up (Horizons), so Houston *can* warn. Today
it starts at hour 0, when Earth is below the horizon and a Houston warning is physically impossible without a relay.

### Course-wide rules
- 3 misses → CAPCOM shows the answer (globe flies and rings it, or the right option lights) and the step passes as `shown` (no star). Today a kid can loop forever on a hint.
- Patch stars: ★ per step passed without a hint. Predictions don't cost stars.
- Vocab in context: every first use of a glossary word gets a ≤ 6-word gloss in the success line (`docs/COPY.md`), and the word is tap-to-define in captions.

## 6. Mission game design

### 6.1 The loop today
40 shifts of 6 h. Each shift: set the power split (7 loads, always sums to 100), optional orders (shelter, rover ice /
repair / explore, call Houston), then "end shift". Battery: solar (Horizons Sun at the site) + 1%/h backup − draw.
Life support: recycler + greenhouse − crew use, freeze loss in the dark. Dose: Chang'e 4 baseline ×2 (game) × storm
multiplier × shields × shelter × EVA. 2–3 real DONKI storms per run at seeded times; one array failure. Science
collected, scored ×1.5 only when sent home in a comm window. Score = 500 for surviving (else pro-rata) + science − 8/mSv.

### 6.2 Strategy simulation (before tuning)
`backend/tools/strategy_sim.py` plays fixed policies through the real `sim.py`. Policies see only what a kid sees (State,
events, Houston's replies), never the hidden storm schedule. 5 sites × 30 seeds = 150 missions each.

| Policy | What it does | Survived | Mean score (grade) | Mean dose (game mSv) | Fails |
|---|---|---|---|---|---|
| planner | listens for warnings, calls Houston in comm windows, shelters early, banks science home | 0.80 | 745 (A) | 25.9 | Malapert: power out 20/30, life support 10 |
| reactive | shelters only when a storm is already hitting; fixes alarms | 0.80 | 507 (C) | 20.0 | Malapert: power out 30/30 |
| idle | never gives an order; "end shift" ×40 | 0.35 | 373 (D) | 36.3 | power out 87, dose 11 |
| **always_shelter** | lives in the shelter for 10 days | **1.00** | 370 (D) | 16.2 | none |
| rover_spam | rover out whenever free | 0.02 | 286 | 43.0 | dose 90, power 57 |
| science_max | all power to science | 0.00 | 230 | 17.6 | life support 150 |
| shields_max | all power to shields | 0.00 | 53 | 8.8 | life support 150 |
| comms_max | all power to the radio (the cheapest load) | 0.00 | 17 | 17.6 | life support 150 |

By site (survival): planner 1.00 everywhere except **Malapert 0.00**; always_shelter 1.00 everywhere.

### 6.3 Dominant and degenerate play found

| # | Problem | Evidence | Why it's bad for learning |
|---|---|---|---|
| D1 | **Always shelter** is the only strategy that never loses, and the only one that survives Malapert | 150/150 survived | A 7-year-old's goal is "don't lose". The safest play teaches "hide forever", the opposite of a mission |
| D2 | The shelter doubles as a free **hibernate** button (draw ×0.3 for everything) | always_shelter never runs low on power | Mixes up two real ideas: a radiation shelter and powering down for the night |
| D3 | **Malapert is unwinnable** by any active play (157 h night) | planner 0/30 | The best data lesson in the game (Horizons night) has no correct answer except D1 |
| D4 | Power can't be cut: the split always sums to 100, so the low-power advice "cut some loads" does nothing | draw only moves between 2.3 and 5.3 %/h by reweighting | The game says one thing and does another |
| D5 | **Spam end shift** survives the sunny sites | idle 0.87 at Shackleton Rim and Connecting Ridge | Rewards not playing |
| D6 | Houston's forecast is exact ("a storm in about 37 hours") and always right | `_execute` call_houston reads the hidden schedule | No uncertainty to reason about; no reason to weigh a warning |
| D7 | Storm "warnings" use the same event kind as the hit (`solar_storm`) | `_hour_events` | UI and Director can't tell "prepare" from "act now" |
| D8 | Non-SEP storms hit as hard as SEP ones (G4 without particles = ×3) | `donki_events.json` mapping on Kp | Wrong physics (§7) and no false alarms |
| D9 | Storm slots overlap (96–170 and 150–216) | `new_mission` | Two storms can stack; feels random, not readable |
| D10 | Survival is 500 of ~750 points; reasoning earns little | score formula | Grinding to day 10 beats thinking |

### 6.4 Tuning (phase 2)

| # | Change | Real basis | Trade-off it creates |
|---|---|---|---|
| T1 | **Storm strength from particles, not Earth's storm scale.** SEP + CME ≥ 1500 km/s ×6; SEP ×3; no SEP ×1.2 | On the Moon only energetic particles matter; G/Kp measure Earth's magnetic field | Some warnings turn out mild: a real false alarm |
| T2 | **Warnings as forecasts.** New event `storm_warning` at start − lead, with `confidence` (high if SEP, low if not) and `lead_h` (6–12 h). Delivered only when Earth is up (or a relay is on, §6.5). Houston's call says "likely / possible storm in the next day or two", not an exact hour | DONKI flare → SEP onset; NOAA forecasts are probabilities | Shelter early (lose science) or wait for more data (risk dose) |
| T3 | **Night mode** (new command `power_save` {on}): draw ×0.5, science and greenhouse stop, heaters must stay ≥ 10 % | Landers hibernate through the lunar night (e.g. Chang'e 4/Yutu-2); NASA FSP exists because of the night | Malapert becomes winnable by *planning* for sunset; it costs science |
| T4 | **The shelter is for storms.** Shelter draw ×0.8 (life support and heat still run; lights, science, rover off); greenhouse output halved | A small buried shelter isn't a hibernation mode | D1/D2 lose their free power |
| T5 | **Mission objectives.** Survive + send home ≥ 120 science + finish ≥ 1 ice run. Outcome `survived` stays; debrief adds `objectives:{science, ice}`. Grade caps at C if an objective is missed | NASA missions are judged on objectives, not just a safe return | Hiding is safe but fails the mission; spamming risks the crew |
| T6 | **Score rewards reasoning.** 300 survival + up to 300 objectives + "good calls" +40 each (sheltered before a storm's hit, night mode before sunset, science sent in a window, ice run with no storm due), − 6 per game-mSv above the quiet baseline | — | Preparing early is worth more than grinding |
| T7 | **Storm spacing.** Slots 18–80, 100–150, 170–216; ≥ 24 h apart | — | Each storm is readable on its own |
| T8 | Low-power advice made true: "Try night mode, or wait for the Sun" | — | Fixes D4 without breaking the 100 % split contract |

Shipped values differ from the drafts above. Storms ×8 / ×4 / ×1.25 lasting 24 / 18 / 12 h. Night mode ×0.35 with
the greenhouse at half. The shelter is capped at 24 h, then 12 h of rest (Orion's shelter). A particle-sensor alarm
fires a few hours ahead when no forecast came. See `docs/MISSION_CONTRACT.md` "learning design v3".

Acceptance targets after tuning (asserted in `tests/test_strategy.py`):
1. planner survives ≥ 0.9 at **every** site and has the top mean score.
2. No fixed policy (idle, always_shelter, shields/science/comms max, rover_spam) reaches grade B on average.
3. always_shelter misses the science objective in ≥ 95 % of runs.
4. idle survives < 0.5 overall on Commander.
5. Each degenerate policy fails for a different reason, so each debrief teaches something different.

### 6.4b Strategy simulation after tuning
`backend/tools/strategy_sim.py`, 5 sites × 30 seeds = 150 missions per policy and band. The policies read only the
State, the events and Houston's replies. "Goals" is the share of runs that met both goals (science home and an ice
run).

| Policy | Before: survived / mean score | **Commander** after: survived / goals / score | **Cadet** after: survived / goals / score | Main way it fails |
|---|---|---|---|---|
| planner (reads the data: likely warnings, night mode before sunset, Houston in windows) | 0.80 / 745 (fails all of Malapert) | **1.00 / 0.69 / 646** (A 55, B 47, C 48) | **1.00 / 0.68 / 668** | none |
| cautious (shelters on every warning, even "possible") | — | 1.00 / 0.69 / 640 | 1.00 / 0.68 / 658 | false alarms cost a little science |
| reactive (shelters only when hit) | 0.80 / 507 | 0.79 / 0.00 / 399 | 0.80 / 0.00 / 399 | power out at Malapert; extra dose |
| rover_spam | 0.02 / 286 | 0.20 / 0.73 / 350 | 0.09 / 1.00 / 365 | dose limit (driving into storms) |
| **always_shelter** | **1.00 / 370** | **0.68 / 0.00 / 340** | 0.80 / 0.00 / 357 | goals never met; power out at Malapert |
| idle (spam end shift) | 0.35 / 373 | 0.38 / 0.00 / 303 | 0.80 / 0.00 / 324 | power out; no goals |
| shields_max / science_max / comms_max | 0.00 / 53 / 230 / 17 | 0.00 / 74 / 45 / 45 | 0.00 / 74 / 33 / 33 | life support out |

What changed:
- **Always shelter** was the only rule that never lost (D1). Now it never meets a goal and loses at Malapert.
- **Malapert** couldn't be won by any active play (D3). Now the planner survives it 30/30, using night mode before the 157 h dark spell.
- **Idle** is down to D/F grades.
- **Reading the data** beats the best fixed rule by about 290 points (Commander) and is the only policy with A grades.
- **Cautious and planner** end up about level: acting on every warning only costs a little science, so heeding a forecast is never a trap.

`tests/test_strategy.py` enforces all of this on every test run:
- the planner survives at least 90% at every site, in both bands;
- the planner beats the best fixed rule by at least 150 points;
- no fixed rule averages a B, and at most 20% of a fixed rule's runs get an A;
- always_shelter meets the goals in 5% of runs or fewer;
- idle survives less than 50% on Commander;
- the fixed rules fail for at least 3 different reasons;
- no policy reads the hidden storm schedule.

### 6.5 Difficulty bands

| | Cadet (7–9) | Commander (10–12) |
|---|---|---|
| Storms | 2, both with particles (no false alarms) | 2–3, including one low-confidence warning |
| Warnings | Always delivered (a relay satellite, stated as a future NASA plan), 12 h lead | Only when Earth is up, 6 h lead |
| Array failure | none | one, seeded |
| Loads shown | 4 (shields, life support, heaters, science); the rest are fixed | all 7 |
| Director | Offers each decision as two options: "Shelter now, or wait a shift?" | Reports events; offers only on alarms |
| Dose display | A meter (0–100 % of the mission limit) | game mSv with the real-mSv conversion in the debrief |

### 6.6 Replayability: real geometry per site (April 2026 window, Horizons)

| Site | Sun in the window | Earth (radio) | Distance to Shackleton ice | Its puzzle |
|---|---|---|---|---|
| Shackleton Rim | up all 10 days | down until hour 132 | ~10 km | No warnings for 5 days: go in cautious or bank science early |
| Connecting Ridge | up all 10 days | down until hour 135 | ~20 km | Same, with a longer ice drive |
| de Gerlache Rim | sets at hour 196 | up from hour 118 | ~49 km | Late sunset: plan night mode for the last 2 days |
| Malapert Massif | sets at hour 84, dark for the rest (157 h) | up from hour 18 | ~129 km | Best radio, longest night: power planning |
| Shackleton Floor | never (power by cable from the rim, 50 %) | via the rim relay | 0 km | Ice at hand, power-starved: careful splits |

Seeds pick different real DONKI events (15 in the catalogue, 2017–2025) and times, so each run is a different real storm
season. The debrief names the real date of each.

### 6.7 Failure as learning: the debrief
Each lose reason gets one "what really happened" line from data plus one "try" line:

| Outcome | Data line | Try line |
|---|---|---|
| dose_limit | "On {date}, the Sun really released particles at {speed} km/s (DONKI). Your crew took {x} mSv in it." | "Shelter when Houston warns, not when it hits." |
| power_out | "At {site} the Sun set at hour {h} and stayed down {n} hours (Horizons)." | "Turn on night mode before sunset." |
| life_support_out | "Life support needs power for the recycler, or ice." | "Send the rover for ice when no storm is due." |
| survived, objective missed | "Your crew was safe but sent home {s} of 120 science." | "Come out of the shelter when the storm ends." |

### 6.8 Lessons pay off in the mission
Each patch unlocks one real tool in the cockpit (owned by the mission UX agent):

| Patch | Unlocks | Mission callback line (Director) |
|---|---|---|
| Moon Scout | Site map with the near-side/far-side shading | "Malapert faces Earth. Remember the near side?" |
| Radio Ready | Comm-window timeline | "Earth rises in 6 hours. Then you can call Houston." |
| Sun Tracker | Sunrise/sunset strip from Horizons | "Sunset in 6 hours, like Malapert's long night. Night mode?" |
| Storm Watcher | Warning confidence chip | "Houston: storm likely. You learned this: shelter early?" |
| Ice Hunter | Rover route to the ice on the globe | "Ice run? No storm is due." |
| Historian | Debrief "a real crew did this" lines | — |
| Word Explorer | Tap-to-define labels in the cabin | — |

### 6.9 The hands-free Director
- Narrates events in ≤ 20-word lines, then makes one offer (`docs/HANDSFREE.md`: an offer is spoken once).
- Offers a choice, never makes it: "Houston sees a flare. Shelter now, or wait?" Yes/no and both names work.
- Callbacks fire once per mission per lesson; Cadet hears all of them, Commander only on alarms.
- Never auto-ends a shift; "end shift" is always the kid's. Silence > 30 s on the first shift → one nudge (`CAPCOM.firstShift`).
  *Live clock (docs/GAMEPLAY.md):* time now runs on its own, and the kid pauses, warps or skips it. Shifts still close
  only at their boundary (or "end shift early"). The nudge is now per Now-card job: ~20 s of silence, at most twice.

### 6.10 The cabin: five panels
The mission UX agent is building a 3D cabin with panels the kid can open. Every mechanic above lives on exactly one
panel, so the kid learns where to look. The Director names the panel in its offer, and the panel that needs attention
lights up: a glow plus an icon, never colour alone.

| Panel | What it shows | Orders on it (each one also works by voice with the panel closed) | It lights up when | Patch tool it gains |
|---|---|---|---|---|
| **Power** | Battery, Sun strip (sunrise/sunset from Horizons), the power split | allocate loads, night mode on/off | `low_power`; sunset ≤ 6 h away | Sun Tracker: sunset countdown |
| **Comm** | Earth's elevation, comm-window timeline, science waiting to go home, Houston log | call Houston, more power to the radio | comm window opens/closes; `storm_warning` received | Radio Ready: window timeline |
| **Habitat** | Life support, greenhouse, heaters, the mission objectives | heaters / life support / greenhouse power | `life_support_low`; heaters < 10 % in the dark | Word Explorer: tap-to-define labels |
| **Rover** | Rover status and ETA, route on the globe, ice runs done | rover: ice, repair, explore, return | `array_damaged`; rover back | Ice Hunter: ice route and distance |
| **Radiation** | Dose meter (game mSv, or % for Cadet), dose rate, shields share, the warning chip with its confidence and lead time | shields power, shelter on/off | `storm_warning`; `solar_storm`; `dose_near_limit` | Storm Watcher: confidence chip |

Rules:
- **Hands-free first.** "Open the power panel" opens it, but no order needs a panel open. A blind kid plays the whole mission by voice, and "what's on this panel?" reads it.
- **One alarm, one panel.** Each alert kind maps to one panel (table above), so "where's the problem?" always has one answer.
- **Cadet:** when the Director makes an offer, the right panel opens with the two choices as big buttons. **Commander:** panels stay closed until the kid opens them.
- The State needs no new fields for panels. The mapping is a client table from alert and event kinds to panels, owned by the mission UX agent. Phase 2 adds `power_save`, `objectives` and `storm_warning` (§9.2).

## 7. NASA correctness checklist

The research agent on `feat/artemis-ref` is writing `docs/ARTEMIS_REFERENCE.md` (sourced facts) and
`docs/ACCURACY_AUDIT.md` (a claim-by-claim audit). When they land, this section will point to those docs for sources and
keep only what the learning design changes. Rows below that overlap the audit will be merged into it, not repeated
here. The branch wasn't on origin when this section was written.

### 7.1 Corrections found in the current course, sim and UI

Phase 2 fixed C1–C9, C11, C12 and C14 in the files this design owns, together with the `docs/ACCURACY_AUDIT.md` items:
- the Artemis IV timeline;
- the NASA 2024 landing regions;
- ISS 523 µSv/day;
- the Orion shelter;
- pretend-tech flags;
- LCROSS;
- the SPA width.

`backend/tests/test_learning.py` locks them. Still open, in other owners' files: C10 (the Lovell caption) and C13
(`mission/ui.js`).

| # | Where | Today | Problem | Fix |
|---|---|---|---|---|
| C1 | `donki_events.json` mapping; check ride; L4 | Storm strength from Kp/G-scale; "the real G5 storm… hitting the outpost" | G-scale and Kp measure Earth's magnetic field; the Moon has none. Dose on the Moon comes from solar energetic particles (SEP) | Map strength on SEP + CME speed (T1). Say "the May 2024 solar particle event (it caused a G5 storm at Earth)" |
| C2 | Check ride step 1 | "Houston sees an active region…" at hour 0, Shackleton Rim | Earth is below the horizon until hour 132 (Horizons): no radio without a relay | Start the ride at hour 138, or say "your radiation monitor" |
| C3 | L4 fact; debrief | "1369 µSv/day, about 2.6 times the ISS" | `radiation.json` holds ISS = 731 µSv/day, which is 1.9×. The 2.6 in Zhang 2020 compares a different ISS figure | Quote the paper's sentence exactly, or say "about 2 times" from our two numbers |
| C4 | Cockpit dose readout | "dose 14.2 / 50 mSv" | Game doses are ×2 and the 50 mSv limit is a game limit; shown as real mSv | Label "game mSv" (or a meter for Cadet); the real-mSv conversion stays in the debrief |
| C5 | Shields load | "Powered shields (water walls pumped…)" | No NASA design uses powered radiation shields; it's a game idea (`radiation.json` says so) | Debrief and the glossary card say "game idea"; never in a NASA-fact line |
| C6 | Sites cards; L2 | "Earth is above the horizon about 93% of the time" (Malapert) | 93 % is our 10-day April window, not a long-term average | Same rule as sun % (§7.4): "Radio with Earth: 9 of 10 days" |
| C7 | Site picker vs debrief (**known bug**) | Picker: "Shackleton Rim ☀ 86% sun" (`sunlight_pct`). Debrief: "Sun was up 100% of these 10 days" (`window_sunlit_pct`) | Two different numbers under one label. 86 % is a long-term, terrain-aware average (Bussey 2010); 100 % is our 10-day April 2026 window from Horizons, with smooth ground and a calibrated horizon. The sim uses the window number | One meaning for sun %, defined in §7.4 |
| C8 | Comm windows | Radio only when Earth is in the sky | True for a direct link; NASA plans lunar relay satellites | One line in L2 and the debrief: "Without a relay satellite…" |
| C9 | `artifacts.json` LCROSS | "2000 kg Centaur" | NASA's LCROSS figure is about 2,300 kg (2,305 kg). **To verify** against NSSDCA 2009-031B before changing | Correct the number in the data file, with the source |
| C10 | Lovell clip caption | "Frank Foreman and Bill Andrews" | ASR error: Frank Borman and Bill Anders | Caption override for `lovell` |
| C11 | `places.json` Integrity, Carroll | Shown as craters | Crew-proposed names, not IAU-approved; the positions are estimated | Keep the "est." tag; L6 says "proposed" |
| C12 | `sim.py` | Comment "crew uses 0.8 %/h"; value 1.0 | Comment drift | Fix the comment |
| C13 | `mission/ui.js` dev storm | severity 5 | Scale is 1–3 | Use 3 |
| C14 | `places.json` Tranquility | 180 km pin; `facts.json` says 873 km | The pin is the Apollo 11 site, not the mare | Name the pin "Tranquility Base" for find steps, or use 873 km |

### 7.2 Claims the new design adds (each needs source, value, check)

| Claim | Value | Source | Check |
|---|---|---|---|
| Moon keeps one face to Earth | rotation = orbit, 27.3 d | NASA Science: Moon | `learning/concepts.json` + `content.check()` number test |
| Lunar day (sunrise to sunrise) | 29.5 Earth days | NASA Science: Moon phases | same |
| Light time Earth–Moon | 1.3 s (384,400 km) | NASA Moon facts | calc `light_s` |
| We see about 59 % of the surface over time (libration) | 59 % | NASA Science: libration | same |
| Sun within ~1° of the horizon at the rim (April 2026) | max −0.81° geometric, above the site's horizon of −1.31° | JPL Horizons | calc `max_sun_elev` |
| Rim–Shackleton ice ≈ 10 km; Malapert ≈ 129 km | great-circle | `sites.json`, IAU 5450 | calc `dist_km` |
| Malapert night 157 h | Horizons | existing calc `longest_dark_h` | existing |
| Earth up 93 % / 45 % in the window | Horizons | `sites.json` | existing number test |
| Apollo 13 record 248,655 statute miles (1970) | clip transcript | Artemis II audio | quoted, not restated |
| Landers hibernate in the lunar night | Chang'e 4 / Yutu-2 | NASA Science feature on Chang'e 4 (**to source**) | must have a URL before T3 ships copy |

### 7.3 Standing rules
- Every number on screen or in speech traces to a repo data file with a `{title,url}` (`content.check()` enforces this for lessons; phase 2 extends it to the new step `reveal` fields).
- "Game idea" is said wherever a mechanic is invented (shields, ×2 dose, 50 mSv limit, cable power, rover times).
- Artemis timeline: Artemis II flew around the Moon in April 2026; Artemis III has not landed; no date is given for it.
- Never "NASA's outpost", "NASA says you…", or a NASA logo. Credit line: "Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA."

### 7.4 One meaning for "sun %" (and "Earth %")

**Decision:** anywhere in the app, the sun number means **the sunlight on your mission**: the share of the 10-day April 2026
window when the Sun is above the site's horizon in the sim (`window_sunlit_pct`, from JPL Horizons). It is the number
that actually drives power in the game, so the picker, the cockpit and the debrief all show the same thing. The long-term
figure (`sunlight_pct`, Bussey 2010, which includes terrain) appears only as a second, labelled line on the site card
and in the debrief. The same rule applies to Earth (radio).

| Where | Kid label (primary) | Secondary line (site card "More" and the debrief only) |
|---|---|---|
| Site picker chip | ☀ **Sun on your mission: 10 of 10 days** | — |
| Site card | same | "Over a whole year, this spot gets sun about 86 % of the time. Mountains and craters block it sometimes." (Bussey 2010) |
| Debrief | "The Sun was up 10 of your 10 days." | the year figure, plus "Our sim treats the ground as smooth, so real shadows are missing." |
| Radio chip | 📡 **Radio with Earth: 4½ of 10 days** | "Without a relay satellite, you can only talk when Earth is in your sky." |

The label is in **days, rounded to the half day**, because "days" is concrete for a 7-year-old and "%" isn't. Read aloud
it becomes "Sun on your mission: ten of ten days". Values for each site (from `sites.json` and the ephemerides; phase 2
adds them to the API as `window_sun_days` and `window_earth_days`):

| Site | Sun on your mission | Radio with Earth | Over a year (Bussey 2010) |
|---|---|---|---|
| Shackleton Rim | 10 of 10 days | 4½ of 10 days | about 86 % |
| Connecting Ridge | 10 of 10 days | 4½ of 10 days | about 82 % |
| de Gerlache Rim | 8 of 10 days | 5 of 10 days | about 81 % |
| Malapert Massif | 3½ of 10 days | 9 of 10 days | about 73 % |
| Shackleton Floor | 0 of 10 days (power by cable from the rim) | through the rim relay, 4½ of 10 days | 0 % |

Owners: the API fields and the debrief text are mine (phase 2). The picker chip is the mission UX agent's. The wording
is the copy agent's.

## 8. Accessibility and hands-free

| Step type | Voice only | Tap / keyboard only | Captions / no audio |
|---|---|---|---|
| find | name the place (gazetteer aliases) | tap; Tab through pins, Enter | prompt on screen; clip transcript captioned |
| side | "far side", "turn it around" | Near/Far toggle; ← → | the toggle shows the current side |
| term | "terminator" or a place on the line | tap the line; or Tab to "the line" focus target | the line is drawn with a dashed overlay, not by shading alone |
| cmp | say a site name | tap a card; options numbered | data chips are text |
| route | stops in order, in one turn or several | tap stops; Tab through pins | each leg announced: "Orientale. Next: Ohm." |
| earth | yes / no / sometimes | three buttons | Earth marker labelled "Earth above / below the horizon" |
| predict | say an option or "option 2" | tap | reveal is text plus speech |
| clips | "skip", "say that again" | ▶ / skip buttons | full transcript caption |

- No step has a time limit. The check-ride "the world doesn't wait" rule is the only pressure, and it's off for Cadet.
- Every globe directive has an audio description line ("Turning the Moon to the far side").
- The 3-miss "show me" rule means no kid gets stuck, whatever the input.
- The hands-free router: the new types are answer turns in a lesson step (`turn_router`: `answer`). The NLU for `side`, `route` and `earth` is word lists in the grader; no new router outcome.

## 9. Scope and plan

### 9.1 Build now (phase 2) vs later

| Now | Later |
|---|---|
| New accept types `predict`, `globe_side`, `terminator`, `compare`, `route`, `earth_view` in `grade.py` + `content.check()`, with tests | Sweep animation of the terminator through a month |
| `course.json` v3 (on `feat/copy-v3`'s copy), new `data/learning/concepts.json` with sourced facts and calcs | Teacher view / NGSS export |
| 3-miss "shown" pass in `routes.py` | Sign-language video |
| Sim T1–T8 with `difficulty`, `tests/test_strategy.py`, and before/after tables here | A Mars epilogue |
| `frontend/src/academy/globe_steps.js`: minimal renderers for the 6 new types | Polished renderers (UX lead) |
| Additive `globe.js`: `poleView(pole)`, `setSunDir(lat, lon)`, `centerLatLon()` | — |
| `tools/handsfree_run.py` script for the new lessons | Real-kid playtest (advisor ask) |

### 9.2 Contracts

Step (backend, `course.json`), additive fields:
```json
{"prompt": "...", "hint": "...", "success": "...", "fail": "...",
 "globe": {"do": "fly|side|pole|sun|zoom|pair|earth|route", "place": "id", "side": "near|far", "sun_lon": -90,
           "places": ["a", "b"], "dist": 2.4},
 "clip": {"clip_id": "naming", "t0": 40.54, "t1": 54.85, "who": "Artemis II crew", "when": "before|after"},
 "reveal": {"text": "...", "source": {"title": "...", "url": "..."}, "from": ["mission/sites.json"], "calc": {...}},
 "accept": {"type": "predict|globe_side|terminator|compare|route|earth_view", "...": "..."}}
```

| accept.type | Author fields | Public (client) fields | Client sends | Server returns (extra) |
|---|---|---|---|---|
| `predict` | `options[{id,label,say}]`, `answer` | options | `{choice}` or `{text}` | always `passed`; `correct: bool`, `guess` |
| `globe_side` | `want` | `want` | `{choice:"near"\|"far"}`, `{view:{lat,lon}}`, or `{text}` | `side` |
| `terminator` | `sun_lon`, `tol_deg` | `sun_lon` | `{tap:{lat,lon}}` or `{text}` | `off_deg` |
| `compare` | `places[2]`, `answer`, `metric` | `places`, `metric` | `{choice}`, `{tap}`, or `{text}` | `choice`, `data:{a:..., b:...}` |
| `route` | `stops[]`, `ordered` | `stops` count + `places` to show | `{taps:[...]}` or `{text}` (one turn or cumulative) | `got:[ids]`, `next` |
| `earth_view` | `place` (answer computed) | `place` | `{choice:"yes"\|"no"\|"sometimes"}` or `{text}` | `answer`, `earth_elev` |

Renderer contract (unchanged, `window.__outpost.stepRenderers[type]`): a factory `({step, acc, answer, say, playCrew, esc, captions, globe}) → {html, bind(el)}`. Phase 2 adds `globe` to the context (one line in `academy/ui.js`, flagged for the UX lead).

Sim (`docs/MISSION_CONTRACT.md`, additive): `new_mission(..., difficulty="commander"|"cadet")`; command `{"type":"power_save","on":bool}`; event kind `storm_warning` with `confidence` and `lead_h`; State `power_save`, `objectives`; debrief `objectives`, `good_calls[]`.

### 9.3 Who owns what

| Piece | Owner | Branch |
|---|---|---|
| This design; `course.json` content; graders; sim tuning; strategy sim; `globe_steps.js` minimal renderers; handsfree script | learning designer | `feat/learning-v3` |
| Academy screens, `stepRenderers` registry, final renderers, adding `globe` to ctx, `globe.js` additions review | UX lead | `feat/ux-v3` |
| Cockpit: night mode control, warning chip, objectives, patch-unlocked tools | mission UX agent | `feat/ux-mission` |
| Final wording of every prompt/success/fail/hint/brief | copy agent | `feat/copy-v3` |
| Mission NLU phrases for night mode ("night mode", "power save", "hibernate") | learning designer (with tests) | `feat/learning-v3` |

### 9.4 Decisions (product owner, after the phase 1 review)
1. **Night mode:** one new order, by voice and on the Power panel. Shipped (`power_save`).
2. **Cadet scoring:** surviving is the success (grade B); the goals are bonus stars (both goals: A). Commander's goals count toward the grade.
3. **Relay satellite:** Cadet only, labelled as future ("a relay satellite like the ones NASA plans"). Commander keeps the real blackout when Earth is down.
4. **Space words:** woven into the lessons. No separate vocab lesson; the `words` patch is retired.

## 10. What shipped (phase 2)

### 10.1 Files
| Area | Files |
|---|---|
| Lessons | `backend/data/academy/course.json` (generated by `backend/tools/build_course.py`), `backend/data/learning/concepts.json` (sourced facts) |
| Grading | `backend/app/academy/grade.py` (`GLOBE_TYPES`), `content.py` (public view and checks: options, places, clip lengths, pins, no two of a type in a row), `routes.py` (predict reveal, shown after 3 misses, `view`/`taps` inputs) |
| Mission | `backend/app/mission/sim.py`, `nlu.py` (night mode), `capcom.py`, `registry.py`, `routes.py` (`difficulty`), `backend/app/session.py` (warning and near-miss lines, shelter limit, night-mode nudge), `backend/app/academy/ride.py` (starts at hour 138, when Earth is up) |
| Data accuracy | `donki_events.json` (keyed on SEP, deduplicated to 13), `sites.json` (2024 list status, sun/Earth bases, pretend-tech flags), `radiation.json` (ISS 523, Orion shelter, pretend tech), `places.json` (SPA width, Artemis IV aliases), `facts.json` and `artifacts.json` (LCROSS) |
| Client | `frontend/src/globe.js` (`poleView`, `setSunDir`, `centerLatLon`), `frontend/src/academy/globe_steps.js` (6 renderers), `academy/ui.js` and `main.js` (4 lines marked `[learning-v3]`) |
| Tests | `backend/tests/test_learning.py` (graders, course shape, clips, map order, accuracy locks), `test_strategy.py`, `frontend/tests/globe_steps.test.js`, plus updates to the academy, vocab, router, session and mission tests |
| Tools | `backend/tools/strategy_sim.py`, `tools/handsfree_run.py` (says the new step types) |

### 10.2 Changes from the §5 drafts
- **Lesson order follows the map** (UX lead's data-driven Moon map): Tranquility (`moon`) → Surveyor 3 (`history`) → Malapert (`comms`) → Shackleton (`power`) → de Gerlache (`radiation`) → Cabeus (`life`) → Shackleton Rim (`checkride`). Near side first, then the pole, with no jump back to the equator. `test_map_order_has_no_long_jumps_back` checks this.
- **Space words:**
  - mare moves to `history` (Apollo 11 landed on a mare);
  - terminator is the `power` globe step itself;
  - regolith is in `life`;
  - earthrise is the mission's comm-window clip.
- **Comms readback** uses the heaters, not the pretend-tech shields.
- **Check ride:** the shields order is replaced by "Ask Houston about space weather" (a comm-window decision). It opens with a predict step: "Earth is up. Can you call Houston?"
- **Storm prompt:** "particles likely within an hour" (Orion's HERA warning), not a 6-hour particle warning.

### 10.3 Client contract as shipped
- The attempt input adds `view: {lat, lon}` (globe_side) and `taps: [...]` (route).
- After 3 misses the reply is `status: "passed"` with `shown: true` and `shown_answer` (`{choice}`, `{place}`, `{stops}`, `{side}` or `{sun_lon}`). It starts "Here it is.", and the UI should highlight that answer.
- A predict reply always passes, with `correct` and `guess`. The `say` is `success` for the right guess, or the step's `reveal` line otherwise.
- `compare` replies add `data: {site_id: {sun_days, earth_days, sun_year_pct, ice_km}}` for the cards.
- A renderer factory may return `onTap(p)`. `academy/ui.js` sends Moon taps to it for non-tap steps.

### 10.4 Asks for other owners
| Owner | Ask |
|---|---|
| UX lead (`feat/ux-v3`) | Review the 4 `[learning-v3]` lines in `academy/ui.js` and `main.js`, and the 3 `globe.js` additions. Restyle `globe_steps.js` or replace it, keeping the contract. Show `shown_answer` and the `compare` data chips. Turn the lesson `clip` with `when: "after"` into an auto-play after the pass. |
| Mission UX (`feat/ux-mission`) | Play the §4 mission clips on `comm_open`, `comm_closed`, mission start and survived. Power panel: night mode switch and `env.next_sun_change_h` strip. Radiation panel: `env.warning` chip (confidence, ETA, by). Habitat panel: `objectives`. Label every `pretend_tech` item "pretend tech". `shelter_ready_in_h` on the shelter control. Site picker: `window_sun_days`/`window_earth_days` ("of 10 days"), plus `status_label`. |
| Copy agent (`feat/copy-v3`) | Polish the new prompt, reveal and success lines in `tools/build_course.py` (they meet the `docs/COPY.md` budgets: `test_copy.py` passes). Check the new sim lines: `storm_warning`, near miss, `shelter_limit`, night mode. |
| Art agent | The `words` patch (Word Explorer, glyph V) is retired; `course.json` lists it in `retired_badges` for back-compat. 7 patches remain. |

### 6.11 Under the live clock (feat/mission-gameplay)
Mission time now runs (docs/GAMEPLAY.md). The sim ticks hourly in every mode, so a shift stepped in real-time frames is
bit-identical to the old turn. `tools/strategy_sim.py --clock live|event` lets each policy act at any hour, or at
each "skip to next event" stop. `tests/test_strategy.py` re-asserts every §6.4b guarantee under the shift, live and
event clocks. At 10 seeds × 5 sites:

| Clock | planner survived / score | best fixed rule score | always_shelter goals |
|---|---|---|---|
| live, Commander | 1.00 / 660 | 359 | 0.00 |
| live, Cadet | 1.00 / 680 | 380 | 0.00 |
| event, Commander | 1.00 / 627 | 370 | 0.00 |
| event, Cadet | 1.00 / 589 | 380 | 0.00 |

Tasks (storm prep, night power-down, ice run...) are guided checklists over the same orders. Their only extra rewards
are small and need the kid's own press (+2 science for a sample or a correctly logged sensor reading). So no fixed
policy gains from them, and the no-dominant-strategy result stands.

## 11. Learning v1: Moon basics, NASA video and Mission prep (`feat/learning-v1`)

Source: the owner-approved "NASA Moon Learning & Media Plan" v1, then a narration review and the owner's lesson
structure (via the coordinator, 2026-11-14). The video player, downloads and the Electron allow-list are built
separately (`feat/media-v1`, `frontend/src/media/video.js`); this branch only calls it. `mission/ui.js` belongs to the
mission-UI branch: the mission-side beats here live in `frontend/src/mission_learning.js`, installed from `main.js`.

### 11.1 Structure: 6 core lessons, the check ride, 2 explorer lessons

Course order (data-driven, `tools/build_course.py` ORDER): `moon` → `phases` → `power` → `comms` → `radiation` →
`life` → (`gravity`, `history`) → `checkride`. Each lesson has `track` (`core` | `explorer`); explorer lessons carry
`unlock_after_missions` (gravity 1, Apollo 2). The map shows a locked explorer pin and "Unlocks after your first
mission"; the cadet's next lesson skips locked ones, so the check ride follows `life`. "Lesson n of 6" counts core
lessons only; the patch total counts all 9. Missions flown are counted per call sign on the device
(`frontend/src/explorer.js`, by mission id), and the debrief offers a lesson the mission just unlocked ("Open it").
Mission lesson numbers ("Lesson 5 helps here") come from the course (`gameplay.LESSON_NO`, core only); `story.js`
CALLBACKS are checked against them. Every lesson has 5 steps or fewer.

### 11.2 The new lessons

| Lesson | Patch | NGSS | Steps |
|---|---|---|---|
| `phases` Phases and eclipses (pin: Sea of Rains), core | Moon Watcher | 1-ESS1-1, MS-ESS1-1 | predict (why the shape changes) → video `phases_loop` → terminator (the course's one terminator step) → predict "What did the Moon block?" + the corona clip `observing-pulsating-streamers-suns` 27.5–50.8 s → video `lunar_eclipse` ("Yes, Earth's shadow. Phases happen without it."). Hook: `moon-during-eclipse-rare` 65.8–83.3 s ("a black ball in front of us"). |
| `gravity` Moon gravity and dust (pin: Apollo 15, Hadley), explorer after mission 1 | Moonwalker | 5-PS2-1 | predict (feather or hammer) → video `hammer_feather` → choice ("Your backpack feels like 30 kilos here.") → video `lunar_dust` → vocab_say "regolith" |

### 11.3 Video steps

The step, its renderer, the player and the catalog are media-v1's (docs/MEDIA.md): `{"type": "video", "media", "say",
"reveal"}`, which `content.video_step()` fills out (prompt = say, `accept: {type: "video", media}`, success = reveal).
`content.check()` requires the media id in `backend/data/video/catalog.json`; `content.VIDEO_MEDIA` (cached NASA files
vs YouTube-only) is read from that catalog, not kept as a second list. A video step never blocks: watched, skipped and
offline all pass, the reveal is said either way, and words that aren't watch or skip are ignored (never a miss).
Screens outside the lesson step (patch screen, Help, the mission beats) call `frontend/src/media/video.js`
(`isAvailable`, `openVideo`, `watchLabel`) directly. Hooks in existing lessons: `moon` far-side video (it carries the far-side guess); `radiation` opens with
`moon_weather` (the CRaTER fact is in its facts); `life` opens with `psr`, and `water_extraction` is an optional video on
its patch screen (`lesson.patch_video`), never a step.

### 11.4 Mission prep

`lesson.prep = {id, title, steps (<= 3 spoken lines), grown_up, source}`; checked by `content.check_prep`. The last
line ends "Tell me when it's ready." and no line says "done" (the open mic would hear it back; the button still says
Done). Offered by itself the first time a lesson opens, then from the lesson's card on the map; never mid-lesson. Done
by voice, a thumbs-up (the Done button is `data-intent="yes"`) or a tap; Skip always works. The NASA activity is
credited in `source`, never on screen.

| Lesson | Task | Grown-up | Source |
|---|---|---|---|
| moon | Crater drop (flour, cocoa, marble) | yes | JPL Education: Make a Moon Crater |
| phases | Oreo phases | no | NASA Space Place: Oreo Moon phases |
| gravity | Feather and coin (paper ball vs flat paper) | no | NSSDCA: Apollo 15 hammer-feather drop |
| power | Low Sun at the pole (lamp on the floor, ball on a chair) | yes | NASA SVS 5229 Moon Essentials: Seasons |
| radiation | Ray shield (flashlight through a book, then foil) | no | NASA STEM: Ray Shielding Activity |
| life | Make regolith (crushed cracker) | no | NASA: Making Regolith (educator PDF) |

### 11.5 Story beats and copy

- First mission only, on "Take command": "NASA plans a real base near here. Ours is pretend. Let's run it." with
  `moon_base_6mo`, offered only when the saved copy is on this computer (it is a pinned download, so it starts at once,
  offline too); otherwise the mission just starts. Watch or Skip. Settings → Help replays it.
- Debrief "Learn more" (`frontend/src/learn_more.js`): `dose_limit` → `moon_weather` (a local NASA file; `solar_eruptions` left the catalog with "videos offline", docs/MEDIA.md),
  `power_out` → a fact card, `life_support_out` → `water_extraction`, `survived` → `meet_crew`; a fact card whenever the
  video can't play.
- Credits: "Outpost Luna is a pretend outpost for learning. NASA's real Moon Base plans: nasa.gov/moon-base." beside the
  not-endorsed line (home, map, About).
- Narration: briefs set up a question without answering it; spoken numbers are easy to say ("over 250 thousand
  miles", "30 kilos"); spoken "Artemis two"; "a dark plain of old lava, called a mare"; regolith is "the Moon's dusty
  soil"; "Orientale Basin"; Christina Koch's "dark side" clip carries the note "She says dark side. She means the night
  side."

### 11.6 Facts verified (2026-11-14)

| Fact | Source |
|---|---|
| Artemis II reached 252,756 miles from Earth on April 6, 2026 (past Apollo 13's 248,655) | nasa.gov/blogs/missions/2026/04/06/artemis-ii-flight-day-6-lunar-flyby-updates/ |
| Artemis III: 2027, tests in low Earth orbit | nasa.gov/news-release/nasa-adds-mission-to-artemis-lunar-program-updates-architecture/ |
| Artemis IV: "Early 2028", two crew near the South Pole | nasa.gov/mission/artemis-iv/ |
| Moon Base: "near the lunar South Pole"; Phase One now–2029; about -203 °C in shadowed craters | nasa.gov/reference/moonbase-about/ |
| Coldest: "lower than -410°F (-246°C)" | science.nasa.gov/moon/weather-on-the-moon/ |
| LRO launched June 18, 2009; CRaTER measures cosmic rays | science.nasa.gov/mission/lro/ |
| Integrity, Carroll: not in the IAU Gazetteer | planetarynames.wr.usgs.gov |
| Hammer and feather landed together (Commander David Scott, Apollo 15) | nssdc.gsfc.nasa.gov/planetary/lunar/apollo_15_feather_drop.html |
| Surface gravity 0.165 of Earth's | nssdc.gsfc.nasa.gov/planetary/factsheet/moonfact.html |
| Half the Moon is always lit; lunar eclipse = Earth's shadow, can look reddish | science.nasa.gov/moon/moon-phases/, spaceplace.nasa.gov/eclipses/en/ |
| Regolith: sharp, clingy bits | nasa.gov NASA Knows: What is lunar regolith? |

Not used: a Shackleton location for NASA's Moon Base (the page says "near the lunar South Pole" only).

## 12. Field School: geology after the check ride (0.5, `feat/05-field-school`)

Brief: NASA Space Apps 2026 "Build a Junior Astronaut Mission Trainer". After the check ride the cadet has learned to
keep an outpost alive; Field School teaches what the crews will go out *to do*: observe, read the land, name the rocks
and sample them. Research basis: NASA's Artemis geology training (Evans 2025, NTRS 20250004946: observe and describe,
impact and volcanic processes, sampling, concise reporting); the Artemis II crew's spoken lunar descriptions (NASA STEM
"Artemis II: Observe the Moon": a Cue Card in orbit, a Lunar Log Card in class, 15 key features, the "Lunar Fifteen");
NASA Science pages on lunar craters and composition; Astromaterials 3D sample stories; the Artemis tool set (Naids et
al. 2021) and Apollo practice (Allton, NASA JSC; ALSJ "Working on the Moon").

### 12.1 Structure

- **A second track, after the ride.** `track: "field"`, `unlock_after: "checkride"`. The core count ("Lesson n of 6"),
  the ride's unlock and the cadet's next lesson are unchanged: a Field lesson is never open before qualifying, so it can
  never sit between a cadet and the check ride (`explorer.js` `isField` / `isBonus`; `content.check()` enforces the
  unlock). In the data the four lessons sit after the explorer lessons and before the ride, so the check ride stays the
  map's last stop; once qualified, the map card says "Field School is open" and the lesson eyebrow reads "Field School
  n of 4". A finished Field lesson's patch screen counts Field patches, not core lessons.
- **Each lesson:** a hook (crew audio, or a NASA photo from the optional `nasa_views` pack), a predict step first, at
  most 5 steps, no two of a type in a row, a patch.

| Lesson | Patch | NGSS | Hook | Steps |
|---|---|---|---|---|
| `observe` Eyes of a geologist (pin: Copernicus) | Moon Observer | MS-ESS1-3 | `ohm-crater-ray-systems` 0.9–22.4 s: "brightness, rays, and any albedo or texture variations" | predict "can astronauts see colors?" + after-clip `texture-albedo-across-mare` 35.3–45.7 s ("brown and tan and gray... some green") → find Copernicus → choice "which is a shape word?" → **describe** Copernicus (3 of 5 descriptor kinds) + after-clip `using-geology-terms-describe` 47.3–56.7 s (the crew describing a maple cookie: "structure... color variation and texture") → vocab_match albedo |
| `craters` Craters and lava (pin: Tycho) | Lava Tracker | MS-ESS1-3, HS-ESS1-6 | `crew-choice-irregular-crater` 69.0–92.9 s: a crater "like an erupting kid science experiment volcano" | predict "what made the round craters?" (impacts, not volcanoes) → find Tycho (rays = splashed ejecta) → choice "what are the maria really?" (cooled lava, never water) → predict "the basin or the lava: which came first?" + after-clip `orientale-basin-ejecta-extent` 32.2–42.3 s ("the Mare's must have come after Orientale") → choice "Tycho's rays lie on top: young or old?" |
| `rocks` Moon rocks tell time (pin: Apollo 16) | Rock Hound | HS-ESS1-6 | `whole-moon-imaging-orientale` 211.3–222.4 s: newer craters look sharp, older ones have fallen walls | predict "bright highlands or dark maria: older?" ("bright doesn't always mean young") → **rounds**: name 3 real Apollo samples in 3D (15016 basalt, 60025 anorthosite, 79115 breccia) → choice "what did anorthosite crystals make?" → predict "is 60025 older than 15016?" → find Apollo 16 |
| `fieldkit` Field kit (pin: Shackleton Rim) | Field Ready | MS-ESS1-3, 3-5-ETS1-1 | photo `geology_iceland_2026` (jsc2026e405549: Zena Cardman with NASA geologists in Iceland); without the pack, its one-line description | predict "what is a rake for?" → **rounds**: pick the tool (pebbles: rake; one fist-size rock: tongs; a chip off a boulder: hammer; fine soil: scoop; the soil's layers: drive tube) → choice "why a numbered bag?" → **sequence** readback: photo, describe, sample, bag, call it in |

Misconceptions addressed: craters are volcanoes (`craters` 1, with the crew's own volcano simile as the hook); maria are
water seas (`craters` 3); bright means young (`rocks` 1, set against Tycho's young bright rays in `craters` 5).

### 12.2 New step types (`grade.py` FIELD_TYPES; renderers in `frontend/src/academy/field_steps.js`)

All three build up over turns, like the route: a turn that adds something is `progress` (never a miss) and the reply's
`got` comes back with the next answer (`AttemptInput.got`).

| Type | Author fields | Public | Graded | Progress / miss / shown |
|---|---|---|---|---|
| `describe` | `need` (default 3), `descriptors?`; step `example` | `need`, `cats[{id,label,chips[2]}]` | descriptor *kinds* covered (size, shape, bright or dark, texture, shadows: the Lunar Log Card's prompts and the crew's talking points), by whole-word lists; nothing is "wrong" | progress: "Good: size. Now, what shape is it?" (praise, then ask for the first missing kind); pass: "You noted size, shape and shadows." + success; miss: praise + the question; rung 2 shows the example on the card; shown: CAPCOM says the example |
| `sequence` | `items[{id,label,say}]` | `items` (sorted by label: jumbled) | the names in order in the words (one turn or several), or one chip at a time | progress "Yes: Photo. What comes next?"; a wrong chip is a miss; rung 2 lights the next chip; shown: the whole order |
| `rounds` | `options`, `rounds[{id,prompt,answer,hint,yes,clue?,rock?}]` | options, rounds without answers/hints | the current round's option (words, number or tap) | each right round: the round's `yes` + the next prompt; misses use that round's hint and cross out one of its wrong options; **after 3 misses only that round is shown and the next goes on** (the client resets its miss count on progress), so no round is skipped |

Tap and keyboard only: the describe chips, the sequence chips and the round buttons cover everything. Voice only: the
hands-free script (`tools/handsfree_run.answer_for`) answers each type, and `tests/test_field_school.py` flies all four
lessons by voice. A rock round shows the real sample in a turntable (`media/turntable.js`, shared with the Library's
Moon rocks tray) when the `nasa_views` pack is installed; without it, the round's text clue alone.

### 12.3 Facts and sources (checked 2026-11-17; `learning/concepts.json`)

| On screen / spoken | Source |
|---|---|
| The crew gave spoken and written descriptions, with a Cue Card; 15 key features | nasa.gov/stem-content/artemis-ii-observe-the-moon/ |
| Crew saw brown, tan, gray and green | crew clip `texture-albedo-across-mare` 35–46 s (repo transcript) |
| Impact craters, ejecta, bright rays; Tycho 85 km, 110 million years | science.nasa.gov/moon/lunar-craters/ |
| Maria are cooled lava that flooded basins 4.2 to 1.2 billion years ago; highlands are older crust | science.nasa.gov/moon/composition/ |
| 15016 basalt, gas-bubble holes, 3.4 billion years; 60025 anorthosite, about 4.4 billion years, first crust; 79115 regolith breccia, broken off a boulder by Apollo 17 | Astromaterials 3D `lunar_sample_metadata.json` |
| Artemis tools: hammer, rake, scoop, tongs, drive tube, sample bags | Naids et al. 2021 (NTRS 20210000242) |
| Tongs pick up small rocks; the rake gathers many small rocks; drive tubes keep layers by depth | Allton, NASA JSC (nasa.gov PDF) |
| Bagging, "after" pictures, numbered bags Houston tracked | ALSJ "Working on the Moon" |
| Zena Cardman's Iceland training, July 2026 | images.nasa.gov jsc2026e405549 |

Not shown (unverified or unneeded): the Apollo sample total "382 kg"; "Look ODD"; the names of the Lunar Fifteen (the
NASA page doesn't list them); Copernicus' size (places.json says 93 km, the IAU about 96 km). The station order
(photo, describe, sample, bag, call it in) is a kid-sized routine built from the Apollo practice above and the
Artemis II spoken reports, not a quoted NASA checklist; the lesson calls it "the station order", never NASA's.

### 12.4 Field School in the mission (0.5 part 2, `feat/05-mission-field`)

Three mission tasks put the lessons to work in the cabin (docs/GAMEPLAY.md §13 has the design and numbers). Each task
is a real job from NASA's surface plans, is voice-first, and points back to its lesson on the Now card ("Field School:
Field kit").

| Task | Lesson it uses | What the cadet does | Basis |
|---|---|---|---|
| Sample station (replaces "Take a sample") | `fieldkit` (tools, station order), `observe` (descriptor kinds) | Picks the tool, describes the sample in one line (graded like the lesson's describe step), calls in the bag number; CAPCOM reads it back | Naids et al. 2021 (NTRS 20210000242): Artemis tools and numbered bags; ALSJ bag practice |
| Low-Sun drive (the ice run's navigator) | `observe` (bright and dark, shadows) | Calls a tack away from a 1–2° Sun in the cameras; calls lights before the crater's shadow | Litaker et al., NTRS 20240011393: south-pole lighting for driving |
| Science stop (replan) | `rocks` (bright anorthosite, the first crust) | Chooses what to give up for 15 minutes at a bright rock (light margin or a sample stop) from the sim's numbers; reads back Flight's approval | JETT5 science ops: the science room asks, Flight approves, one CAPCOM voice |

Learning design notes:

- **Predict, then act, then see it counted:** the station's points scale with the description (0.5 to 2.5), so a
  fuller description is worth more, but nothing is "wrong". A wrong tool gets the lesson's own line ("Tongs grab one
  rock.") and the job goes on.
- **Read the data:** the tack side comes from the Sun's real elevation and bearing on the readout, and the replan's
  answer from the light margin (Horizons sunset minus the rover's ETA). A fixed rule ("always tack left", "always use
  the margin") is right only some of the time. The rewards are too small to matter to the balance
  (`tests/test_strategy.py` unchanged).
- **Comms discipline:** the readback is a sequence step (the items in order, over turns), the same grader as the Field
  kit lesson's station-order readback.
- **Honest limits:** the Sun's bearing uses the game's azimuth convention, shared with the window (140° plus one turn
  per lunar day), not a Horizons azimuth. The replan needs Earth up, since the science room is on Earth, so a mission
  that never drives under Earth (Shackleton Rim before Day 6) never sees one. "Maybe anorthosite" stays a maybe: a
  bright rock isn't always anorthosite, and the Rocks lesson says bright doesn't always mean young.

### 12.5 Not done

- **The 216 IAU names** in the pack (`names/moon_names.json`) are not wired into the entity registry or the ear's name
  lists. They exist only when the optional pack is installed, while the registry, the gazetteer and the Director's
  gazetteer evals are built from versioned repo data; wiring them in means runtime-dependent entities across the ear,
  the router and `did_you_mean`, which is not contained. Left for a step that copies a curated subset into
  `places.json` with tests.
- No Mission prep task for Field School (NASA's "Exploring the Moon" Lava Layering activity is the candidate; its
  URL wasn't verified this round).

## 13. Hints that adapt to pauses (0.6, `feat/06-voice-signals`)

The hint ladder (docs/PLAYTEST.md §Guidance, `backend/app/academy/guide.py`) climbs on misses and on "help". Kids who
stall often don't ask. They say "um ..." and guess. From 0.6, a hesitant answer brings the next rung **one step sooner**:
- **What counts.** `backend/app/hesitation.py` reads the ear's own signals for the turn: disfluent words (`disfl`:
  filler, repeat, fragment), the longest pause (`max_pause_s` >= 2.5 s) and a low utterance confidence (`uconf` <
  0.45). Only heard turns count. Typed and tapped answers never do.
- **What it does.**
  - The session puts `hes: true` on the turn's `heard` decision.
  - If that answer is a miss, the client sends `hes: true` with it (`POST /api/academy/attempt`), and the server's
    ladder counts one more miss: the first miss shows rung 2 (the label, a card crossed out, the words on the card)
    instead of rung 1.
  - In the cabin, the Now card's nudge comes at once instead of after 20 s (docs/GAMEPLAY.md §14.3).
- **Caps.**
  - One early rung per step.
  - The reveal ("Here it is") still waits for real misses and ~20 s (`grade.reveal_due`).
  - The check ride has no ladder and ignores it.
- **What it never does.**
  - It never says "you sound unsure", and no line changes.
  - The flag lives for one turn, in memory: it is never in the turn log, the routes or history, a profile or a score.
  - A right answer is a right answer, hesitant or not.

The grown-ups guide says so in one line (`site/guide.html`, "Hints adapt to pauses"), and the About drawer says "Hints
come when you're stuck, and sooner after a long pause."
