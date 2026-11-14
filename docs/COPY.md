# Outpost Luna copy deck

Every word on screen and every word spoken. Short, clear, warm, and there for a reason.

**Where copy lives**
- On screen: `frontend/src/story.js`. Templates read from it and never hardcode story text.
- The story arc, transitions, cabin tour and the "Now" strip: `story.js` (`TRANSITION`, `PICKER`, `TOUR`, `NOW`, `HELP`), described in `docs/STORY.md`.
- Lessons: `backend/data/academy/course.json`.
- CAPCOM radio: `backend/app/mission/capcom.py`.
- Guide: `backend/app/director.py`.
- Sim events: `backend/app/mission/sim.py`.
- Session alerts: `backend/app/session.py`.

**Tests**
- `backend/tests/test_copy.py`: no emoji; every spoken line is 20 words or fewer; course still valid.
- `frontend/tests/copy.test.js`: story.js budgets; a typed call sign is never spoken.

## 1. Voice

| We are | We are not |
|---|---|
| A calm mission controller who likes you | A cheerleader |
| Plain words with real NASA facts | A lecture |
| Wonder: "Behind the Moon, the crew watched Earth rise." | Hype: "Amazing!!! Great job!!!" |
| One idea, then stop | Instructions repeated on every screen |

**CAPCOM speaks in radio rhythm.** Lead with the confirmation, then say the thing in as few words as you can, then say what it costs. Each sentence carries one idea.

> Copy. Radiation shields up 20 percent. Less for the life support.

**Houston** opens with "Houston here." It speaks only when Earth is up. When Earth is down, Houston says nothing, and CAPCOM tells the kid it is their call.

**The guide** is the Moon explorer voice. It gives one fact and an invitation, such as "Tap one to hear its story."

## 2. Rules and word budgets

### On screen

| Element | Budget |
|---|---|
| Headline | 2 to 6 words |
| Supporting line | 1 line of 12 words or fewer. No paragraphs. |
| Button | 1 to 3 words, starting with a verb: "Take command", "Fly again", "Use it" |
| Lesson card blurb | 12 words or fewer |
| Hint shown under a step | 10 words or fewer. Example phrases are allowed on screen. |

Also on screen:
- No emoji anywhere, including inside strings. Icons and patches come from the art set.
- No "what to do next" chatter. A screen that already shows a button does not also explain the button.

### Spoken

| Element | Budget |
|---|---|
| Any spoken line | 20 words or fewer. Most lines are under 12. |
| Step success | 8 words or fewer |
| Step fail | 6 words or fewer, because the hint is added after the second miss |
| Fail + "Hint:" + hint | 20 words or fewer |
| Lesson brief | 1 or 2 sentences, 15 words or fewer |

Also when speaking:
- Give one idea per sentence.
- **No example commands in spoken fallbacks** ("I don't know that one yet", "Say again?"). The open mic hears our speakers, so a spoken example would come back as a new turn. Example commands go on the card (`director.TRY`).
- **Say an offer once, as a question:** "Ready for the next lesson?" "Fly again?" Don't add "Say yes" or "Say next". The router already accepts yes and next for any pending offer.
- **Speak numbers with their unit:** "40 percent", "14.2 of 50 mSv".

### Kids 7 to 12

- Use plain words and short sentences.
- The real space words stay: albedo, regolith, terminator, mare, mSv. The first time one appears, gloss it in about 6 words:
  - Regolith is the Moon's dusty soil.
  - A mare is a dark plain of old lava.
  - The terminator is where day meets night.
  - An mSv measures radiation dose.
- Ground every line in real sources (NASA first). Every fact in `course.json` keeps its source, and its numbers match the cited data. `content.check()` enforces this.

### Accuracy

Source for these rules: `docs/ACCURACY_AUDIT.md` and `docs/ARTEMIS_REFERENCE.md` on `feat/artemis-ref`.

**Artemis**
- Artemis II flew its crew around the Moon in April 2026.
- NASA restructured Artemis on 2026-02-27:
  - **Artemis III (2027) is a crewed test flight in Earth orbit, with no landing.** Never call it the first landing.
  - **The first crewed landing is planned for Artemis IV (2028).** Always say "planned".
  - NASA has not confirmed the Artemis IV landing site. Never say where it will land.
- **No crew has landed at the south pole.** The approved line is "No crew has landed at the south pole yet."
- Landing regions: cite NASA's **2024** list of 9, which includes Malapert Massif and de Gerlache Rim 2. Shackleton's rim and Connecting Ridge are not on it.

**Storms**
- At the Moon, the hazard is a **solar particle storm**: fast protons from the Sun. Never write "G5", "Kp", or "geomagnetic storm at the outpost". Those scales measure Earth's magnetic field, and the Moon has none.
- For May 2024, use Earth as context: "the real May 2024 storm, which gave Earth huge auroras".
- Particles from a storm arrive within minutes to a few hours, not on a fixed "6 hours".

**What's real, and what we claim**
- **Never over-claim.** Don't write "everything uses real NASA data" or "every fact shows its NASA source".
  - Some data is not NASA's: the baseline dose comes from China's Chang'e 4, and some numbers come from science papers.
  - Some rules are game choices: the dose is doubled, and the shields are pretend.
  - The approved line is `SOURCES_LINE`: "Built on NASA open data, plus a few science papers. Some outpost tech is pretend, and we label it."
- **Pretend tech gets a tag.** Use `PRETEND_TECH` ("Pretend tech") with `PRETEND_TECH_TIP` ("Made up for the game. Real crews don't have this.").
  - It applies to the powered radiation shields, the greenhouse, the rim-to-floor power cable and the rim relay.
  - Never say "the plan is" for something NASA has not planned. Real crews in Orion build a storm shelter out of their supply bags. A soil-covered base is a studied idea.
- CAPCOM and Houston are played by the game.

**Endorsement**
- Never imply NASA endorsement. The credit line is exact and must not change:
  **"Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA."**

### Call sign

- **Never speak a typed call sign.** It might be a real name.
  - Speak `callSign.spoken()`, which returns a preset or "Commander".
  - Show `callSign.shown()`.
- Only the 12 presets in `CALLSIGNS` are ever said aloud.

### Numbers

- Every number must come from data, never typed in by hand.
  - In a fact, the number must appear in the cited data file. `content.check()` enforces this.
  - In a sim or CAPCOM line, interpolate the sim's own value. For example, a storm's "Radiation 4x normal" is `ev['dose_multiplier']`, the same value `dose_rate()` multiplies by.
  - If a number can't be derived, leave it out.
- Round the way a kid would read it: "about 21 km wide", "157 hours".

## 3. Writing a lesson (`course.json`)

Use this checklist for any new or redesigned lesson. `backend/tests/test_copy.py` and `content.check()` enforce the starred (★) rules.

### Copy fields

| Field | Seen or heard | Rule |
|---|---|---|
| `title` | Under the patch stop on the course map; also spoken by voice ("lesson power from the sun") | ★ 6 words or fewer. **24 characters or fewer**. Plain words, title case not required. Must be unique: the router matches titles by voice. |
| `brief` | Spoken at lesson start, after the story beat and "Ready, Nova?"; shown inside the brief disclosure | ★ 20 words or fewer. Aim for 15 or fewer, in **1 or 2 sentences**. One idea, the why. No welcome ("Welcome, cadet…"); the beat does that. |
| `steps[].prompt` | The 20px question on screen, and spoken | ★ 20 words or fewer. **90 characters or fewer**. A question or one order. Never "say it, or tap…": the panel's "how" line covers input. |
| `steps[].success` | Spoken and shown after a pass | 8 words or fewer. Radio word first ("Roger.", "Copy.", "Correct.", "Yes."), then the payoff fact. |
| `steps[].fail` | Spoken and shown on a miss | 6 words or fewer. Kind and specific: "Not quite. Look lower." Never "Wrong". |
| `steps[].hint` | After 2 misses: spoken as `fail + " Hint: " + hint`, also shown | ★ fail + hint is 20 words or fewer. The hint is 10 words or fewer. It nudges toward the answer and doesn't quote the exact order (the open mic hears it back). |
| `steps[].capcom` | The order CAPCOM speaks in a readback step | Starts with "Commander,", then the order. |
| `accept.options[].label` | An answer row (52px), which the kid can also say | 6 words or fewer. Labels within a step share no key words: a spoken label matches by its words. |
| `facts[].text` | "NASA facts" disclosure, and the guide's lesson card | ★ Has a `source {title,url}`, and its numbers appear in its `from` files. One sentence where you can. |
| `library.label` | Button | 1 to 3 words, verb first: "Open Surveyor 3". |
| `badge.name` | The patch name | 1 to 2 words: "Sun Tracker", "Ice Hunter". |

### Hard constraints, which are matching logic and not copy

- **Keyword (readback) steps** must keep the order **in double quotes** inside `prompt`:
  `CAPCOM: "Send the rover for ice." Start your readback with roger.`
  The paraphrase matcher (`grade.references`) and the hands-free test both read the quoted text.
- **Don't put quotes in other keyword prompts.** Quotes there would become references.
- **Never change these:** ids, `accept` (except option labels; see the label rule above), `from`, or `source`.

### Space words

- First use in a lesson: give a 6-word gloss in the success line.
  - "Yes. A mare is a dark plain of old lava."
  - "Right. Regolith, the Moon's dusty soil."
- After that, use the word plainly.

### Tone per step type

| Step type | How to write it |
|---|---|
| choice | Ask a real question with one clearly right answer. Wrong options are plausible, never silly. |
| tap / intent | Say what to find, plus one visual landmark ("inside the gold ring"). |
| command | A situation, then the need: "Night is coming. Move power to the heaters so the pipes don't freeze." |
| clip | "Listen to Jim Lovell." Then the question. |

## 4. Mission lines that UX wires

| Key | When it is said | Rule |
|---|---|---|
| `CAPCOM.missionStart` | Once, when the outpost comes online | Spoken with `callSign.spoken()` |
| `CAPCOM.firstShift` | **First mission only.** Said once right after `missionStart`, and again only after a silence with no order yet. Never more than that. | 12 words or fewer: "Set your power, then end the shift." |
| `RIDE.mars` | **On screen only**, on the check-ride result card. The backend also sends it as `fact` on the ride's `done` reply. | Never spoken |
| `OFFER.*` | Once, after the line it follows | Never add "Say yes" or "Say next" |

## 5. Glossary: one word for one thing

| Term | Use it for | Don't say |
|---|---|---|
| **Outpost Luna** | The south-pole base the kid runs | base camp, station, colony |
| **Flight School** | The Academy: 6 lessons and the check ride (7 patches) | academy, course, training center |
| **Lesson** | One Flight School unit | module, level, mission |
| **Patch** | What a lesson earns, the cloth mission patch | badge, trophy, medal, star |
| **Check ride** | The final solo test, 2 days at Shackleton Rim | final exam, boss level |
| **Cadet** / **Commander** | The kid, before and after qualifying | player, user, astronaut |
| **Call sign** | The kid's radio name | nickname, username |
| **CAPCOM** | The kid's mentor and radio voice (capsule communicator) | AI, assistant, bot, coach |
| **Houston** | Mission Control on Earth, which answers after the radio delay | NASA (as a speaker), base |
| **Shift** | 6 hours of mission time ("end shift") | turn, round, tick |
| **Day** | Mission day, from 1 to 10 | sol (that is Mars) |
| **Comm window** | When Earth is up and the radio works | signal, connection |
| **Shelter** | The regolith-covered storm shelter | bunker, safe room |
| **Shields** | The radiation shields (a power load) | force field |
| **Life support** | Air and water. On screen it can be shortened to "air". | oxygen (only when it means O2) |
| **Readback** | Repeating an order so both sides know it is right | echo, repeat-after-me |
| **Debrief** | The end-of-mission review | results, score screen |
| **Standing order** | A rule the kid sets: "if a storm comes, shelter" | automation, macro |

Radio words are taught in Lesson 2 and used everywhere after it:

| Word | Meaning |
|---|---|
| **Copy** | I heard you |
| **Roger** | Received |
| **Say again** | Repeat that |
| **Negative** | No, not that |
| **Confirmed** | Done as asked |

## 6. Before → after: the worst 30

| # | Where | Before | After |
|---|---|---|---|
| 1 | CAPCOM readback | Copy, commander. Moving 20 percent of power to the radiation shields. That leaves less for the life support. Shields now gets 40% of the power. | Copy. Radiation shields up 20 percent. Less for the life support. Shields now at 40%. |
| 2 | Check-ride result | …Check ride complete. Power 62%, life support 71%, dose 3.4 of 50 mSv. 4 of 4 orders right. On Mars, Houston would answer 6–44 minutes later. You are qualified, Commander! | Copy. Rover rolling out for ice. Check ride done. 4 of 4 orders right. You're qualified, Commander. (The Mars fact moves to the result card as `fact`.) |
| 3 | Mission start (spoken) | Outpost Luna is online at Malapert Massif, Nova. Day 1. Check your power levers, then say "end shift". | Outpost Luna is online at Malapert Massif. Day one, Nova. |
| 4 | Academy patch offer | Patch earned, Nova: Sun Tracker! Next up: Radiation and solar storms. Say next when you're ready. | Patch earned: Sun Tracker. Nice work, Nova. Ready for the next lesson? |
| 5 | Debrief offer | …Your grade is B, with 812 points. Want to fly again? Say fly again. | Nice flying, Nova. Grade B, 812 points. Fly again? |
| 6 | Flight School sub | Short lessons with CAPCOM. Earn a patch for each one, then fly your first solo shift and take command of Outpost Luna at the lunar south pole. | Earn a patch for each lesson. Then take command. |
| 7 | Mission brief | Welcome to Outpost Luna, Commander Nova. Pick a site, then keep power, life support and radiation safe for ten days. | Pick a site, Commander Nova. Keep the crew safe for ten days. |
| 8 | Lesson 1 brief | Welcome, cadet. Artemis III, the first landing near the Moon's south pole, hasn't happened yet. You're training to help run Outpost Luna, a base next to a crater called Shackleton. | The next crews will land near the south pole, by a crater called Shackleton. |
| 9 | Check-ride brief | This is your check ride: your first solo shift at Outpost Luna, two days at Shackleton Rim on the real mission simulator. A real solar storm is on its way. Give good orders and you earn the Mission Commander badge. | Your check ride: two days at Shackleton Rim. A real solar storm is coming. |
| 10 | Rover dispatch (sim) | Rover rolling out to collect ice. Back in about 10 hours. Charging it used 10% battery, and the drivers get extra radiation while outside. | Rover back in about 10 hours. It used 10% battery. |
| 11 | Storm event | SOLAR STORM! This is a real event: the X5.8 flare of 2024-05-10 (severity 3 of 3), replayed in your mission. Radiation is 4x normal. | Solar storm! The real 2024-05-10 flare. Radiation 4x normal. |
| 12 | Houston, out of contact | No answer. Earth is below the horizon, so the radio can't reach Houston right now. We have to decide on our own! | No answer. Earth has set, so Houston can't hear us. Your call, Commander. |
| 13 | Confirm prompt | That puts 95% of all power into shields and almost nothing else. Are you sure? Say yes to confirm or no to cancel. | That puts 95% into shields, almost nothing else. Are you sure? |
| 14 | Shelter (sim) | Crew is in the shelter under the regolith. Much less radiation, but no science and the outpost idles. | Crew in the shelter. Much less radiation, but science stops. |
| 15 | Status: dose | The crew has had 14.2 mSv of radiation so far, out of a safe limit of 50. An mSv is a unit for radiation dose. Right now it goes up by 0.35 every hour. | Crew dose: 14.2 of 50 mSv. An mSv measures radiation dose. Rising 0.35 an hour. |
| 16 | Status: all | (five systems, about 45 words) | Battery at 54 percent. Air and water at 22 percent. Crew dose: 14.2 of 50 mSv. |
| 17 | Hint (spoken) | Not quite. The south pole is at the very bottom of the Moon. Hint: Try saying: show me the south pole. | Not quite. Look lower. Hint: The south pole is at the very bottom. |
| 18 | Lesson 1 step 1 | The near side always faces Earth. Now show me the south pole: say it, or tap the very bottom of the Moon. | The near side always faces Earth. Now find the south pole. |
| 19 | Guide: far side | This is the far side. It always faces away from Earth, so nobody saw it until spacecraft flew around. | The far side. It always faces away from Earth. |
| 20 | Guide: privacy | Let's keep names and addresses private! Ask me about a place on the Moon instead. | Let's keep names and addresses private. Ask me about the Moon. |
| 21 | Guide: say again | Sorry, I didn't catch that. Can you say it again? | Say again? I missed that. |
| 22 | Guide: misconception | Not cheese! The Moon is made of rock and dust. But the crew did say one place looked yellow, like a snowy mountain. | Not cheese. The Moon is rock and dust. But the crew saw one spot look yellow. |
| 23 | Tour: hardware | People have left lots of hardware on the Moon: landers, rovers, science tools and crash sites. Tap one to hear its story! | Landers, rovers, science tools and crash sites. Tap one to hear its story. |
| 24 | Callback: low power | Remember Lesson 3? Batteries are low. Remember Lesson 3: no Sun means batteries only. Turn down what you don't need. | Remember Lesson 3? Battery's low. Turn down what you don't need. |
| 25 | Callback: life support | Flight School Lesson 5 covers this. Life support is low. Lesson 5: send the rover for ice. | Lesson 5 covers this. Life support is low. The rover can fetch ice. |
| 26 | Lesson-card patches | Emoji patches: moon, radio, sun, shield, ice cube, scroll, book, rocket | (none; the art set draws patches, with the letter glyph as fallback) |
| 27 | Call-sign picker | Every astronaut has a radio name. CAPCOM will use yours. It stays on this device. / That's me / Surprise me | Your radio name. It stays on this device. / Use it / Pick for me |
| 28 | Low battery alert | It's dark and the battery is low. Let's save power together. | Dark, and the battery's low. Let's save power. |
| 29 | Sim: sunset | The Sun just slipped below the horizon. Batteries only until it comes back. | Sunset. Batteries only until the Sun returns. |
| 30 | Shift report | Day 3, shift 2. (two events) Power 62%, life support 71%, dose 3.4 of 50 mSv. | Day 3, shift 2. (latest event) Power 62%, air 71%, dose 3.4 mSv. |

## 7. Keys for UX templates (`story.js`)

Templates should import these keys and not hardcode the words.

| Key | Text |
|---|---|
| `CALLSIGN_COPY.say` | Spoken when the picker opens. Replaces "Every astronaut has a call sign. Pick yours!". |
| `CALLSIGN_COPY.edit` | "Change call sign" |
| `SCHOOL.continue`, `.ride`, `.next`, `.solo`, `.shelf`, `.notYet`, `.progress(n,total)`, `.minutes(m)`, `.track(k,title)`, `.earned(name)` | Lesson catalog labels |
| `WHY_TITLE`, `WHY` | The "Why this matters" box |
| `OFFER.nextLesson`, `.ride`, `.mission`, `.flyAgain`, `.nextStep` | Spoken offers, said once each |
| `DEBRIEF.grade(cs, grade, points)` | Spoken and shown. Speak it with `callSign.spoken()`. |
| `DEBRIEF.close` | "Back" |

Two places currently speak with `callSign.shown()` where they should speak with `callSign.spoken()`:
- `CAPCOM.missionBrief`
- `CAPCOM.missionStart`

If the mission UI's `say` reads the brief card aloud, it must pass `callSign.spoken()`.

New keys from the accuracy round:

| Key | Text |
|---|---|
| `SOURCES_LINE` | The honest sourcing line, for About and Debrief |
| `PRETEND_TECH`, `PRETEND_TECH_TIP` | The tag and tooltip for game-only hardware |
| `STORM.name`, `STORM.may2024` | "Solar particle storm", plus the Earth-auroras context line |
| `RIDE.mars` | The Mars fact, for the check-ride result card |
| `CAPCOM.firstShift` | The first-shift coach line |

## 8. About dialog (`index.html`): exact text for the UX lead

These replace the Artemis III framing and the over-claims (audit #1, #3, #10). Swap each one in as written.

**Header `<p>`** (replaces "A voice game for kids 7 to 12. Artemis III hasn't landed yet: …"):

> A voice game for kids 7 to 12. No crew has landed at the Moon's south pole yet. Train at Flight School, then run Outpost Luna, a base there.

**Flight School paragraph** (replaces "Flight School is short lessons with CAPCOM: … not endorsed by NASA."):

> Flight School is short lessons with CAPCOM: the south pole, radio talk, solar power, radiation, air and ice, and lessons from Apollo. Answer by voice, typing or tapping. A hint comes after two misses. Every fact shows its source. The last lesson is a check ride: two days on the mission simulator, with a solar particle storm based on the real May 2024 storm, the one that gave Earth huge auroras. Pass it to earn the Mission Commander patch. Patches and your call sign stay on this device. The story is inspired by NASA's Artemis program. Artemis I flew uncrewed in 2022. Artemis II flew its crew around the Moon in April 2026. Artemis III, planned for 2027, is a crewed test flight in Earth orbit. The first crew landing is planned for Artemis IV in 2028, and NASA hasn't picked the site yet. Built on NASA open data, plus a few science papers. Some outpost tech is pretend, and we label it. CAPCOM and Houston are played by the game.

**Credit line:** keep it exactly as `CREDIT`.

**Data table row "LRO LOLA"** (audit, `index.html` table): the Use cell becomes

> How much sunlight each site gets (LRO LOLA and Kaguya illumination studies)

**Data table row "NASA DONKI"**: the Use cell becomes

> Real solar storms and particle events, with their real dates
