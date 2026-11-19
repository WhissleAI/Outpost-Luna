# UX audit 2: "act, then check the app noticed"

Branch `fix/ux-audit-2`, on `origin/main` 2d1c09b (rc/4), with `main` 62cf988 merged in. The owner kept getting lost.
Their latest catch was the cabin's Now strip, which said "Set power, then End shift." before and after they changed the
power, so the app never acknowledged it. Earlier audits checked that each screen worked. This one checks that every action
gets noticed.

**Method.** `frontend/tools/ux_audit2.py` drives the real app headless: Playwright, 1280×720, the real backend on :8411,
Vite on :5311 and the model server on :8200 (read-only). For each action a kid could take (a button, a typed or spoken
phrase, a key, a wrong try), it probes the screen before the action, 1 s after it, and once it settles. A probe records:

- the instruction lines: prompt, do-line, intro, feedback, map beat, patch line and Now strip;
- the voice bar: state, words and caption;
- the cards, toasts, sheets, pressed states and the globe's centre;
- what was spoken (hooked on `floor.say`).

It flags three things:

- no visible reaction within 1 s;
- an instruction line still word for word the same after the action that did what it asked;
- the same line spoken twice in a row.

Every flag was then judged by hand from the screenshot and the log. Many "instruction unchanged" flags are correct
behaviour: opening Settings doesn't change the lesson's prompt. A typed turn takes the same session path as a spoken one
(the router decides), so typed phrases stand in for voice.

Run it:
```
uv run --with playwright --with pillow python frontend/tools/ux_audit2.py --base http://localhost:5311 --out /tmp/a2 [--only first,lessons,ride,library,settings,errors,returning]
```

Screenshots are in `docs/img/audit2/` (640 px JPEGs). The machine ran at a load average of about 56 throughout (other
agents' decode jobs), and the model server was down for part of the first pass. Timing flags ("no reaction in 1 s") were
re-checked by hand before counting.

## Summary

| | moments audited | real issues (in my scope) | of them: silent / no reaction | stale, wrong or said twice | mission / cabin (routed) |
|---|---|---|---|---|---|
| **Before** (2d1c09b) | 201 | 23 | 10 | 13 | 3 (M1–M3) |
| **After** (this branch) | 201 | 0 | 0 | 0 | 3 (M1–M3), not fixed here |

"Real issues" counts moments where a kid would get no acknowledgement, a stale or wrong instruction, or the same thing
twice: rows 4, 5, 11, 12, 13, 14, 15, 21, 22, 23, 30, 31, 36, 45, 49, 60, 66, 71 and 74 below, plus the four parts of the
P0. Tool artefacts are excluded: a styled radio the tool clicked at the wrong spot, and the 3D cabin stalling headless
captures on the loaded machine. The after-pass re-ran first launch, the map, the Library and the ride start. The lesson
fixes are covered by unit tests (`tests/audit2.test.js`) and the router tests.

The P0 the coordinator raised mid-audit is done and is the branch's first commit (f829202). It covered room chatter that
flickered the voice bar and printed overheard words, profanity included. See [P0](#p0-room-chatter-on-the-voice-bar).

## The moments

**Reacted?** is whether the screen visibly changed within 1 s. **Instruction updated?** is whether every line that tells
the kid what to do now matches the new state. "n/a" means the action doesn't touch an instruction.

### First launch → call sign → map

| # | Screen | Action | Reacted? | Instruction updated? | Verdict | Fix |
|---|---|---|---|---|---|---|
| 1 | Home | first launch | yes | yes: "Pick your call sign", spoken once | ok | |
| 2 | Home | tap a call-sign chip | yes: the field and chip pressed | n/a | ok | |
| 3 | Home | Pick for me (shuffle) | yes: 3 new chips | n/a | ok | |
| 4 | Home | clear the field, press Start | **no** (focus only) | **no** | **said nothing** | "Type a call sign, or tap one." under the field (`#aCsErr`); clears as they type |
| 5 | Home | type "hello there" in the voice bar | **no**: the text vanished, router `ignore` without a notice | **no** | **silent** | the router answers a typed turn on the call-sign screen; a short name goes into the field and CAPCOM says "Got it. Tap Start to use it." |
| 6 | Home | press M (mic) | yes: mic state | n/a | ok | |
| 7 | Home | "call me Nova" | yes: the map | yes: Step 1 of 4 beat, Next-up card, welcome spoken | ok | |
| 8 | Map | "what do I do?" | yes: spoken | the line named "Start lesson" | ok here | (see 11) |
| 9 | Map | tap pin 3 (not next) | yes: the card switches to it | yes: "Lesson 3 of 6 · …" | ok | |
| 10 | Map | tap the same pin again | yes: the lesson opens | yes | ok | |
| 11 | Map (1+ patches) | "what do I do?" | yes | **wrong**: said "Tap Start lesson…" while the button read **Continue** | **contradiction** | `ctaFor()` is the only source for the button label, and help names that label |
| 12 | Map (6 patches) | "what do I do?" / the card | yes | the ride's button said "Continue" | confusing | the check ride's button is **Fly check ride**; help says "Tap Fly check ride. One solo shift, then you take command." |
| 13 | Map (returning, 3 patches) | open | yes | **no "where am I" line**: the beat showed only at 0 patches and before the ride | **lost** | the beat is state-driven at every point: "1 of 6 lessons done. Next: Lessons from Apollo." |
| 14 | Map | call-sign chip → "Zed" → Use it | yes | said "Copy that, Cadet. Welcome to Flight School." **again** | odd | "Copy that, Cadet. Call sign saved." |
| 15 | Map | Tab / arrows (keyboard mode) | yes: ring and hint chip | n/a | **legend over the NASA credit** (measured overlap: legend 12–221 × 677–708, credit 16–296 × 668–704) | while the legend shows, the credit lines move up 40 px (school.css) |
| 16 | Map | H, Esc | yes: help sheet | n/a | ok | |
| 17 | Map | N (next) | yes: lesson 1 | yes | ok | |
| 18 | Map | S, C, C | yes: Settings, then the "Captions off/on" toast | n/a | ok | |

Before: `img/audit2/before-empty-start.jpg`, `before-legend-over-credit.jpg`, `before-returning-no-beat.jpg`.
After: `after-empty-start.jpg`, `after-legend-clear.jpg`, `after-map-progress-beat.jpg`.

### Lessons (every step type, wrong tries, help, mic, mode switches)

These cover lesson 1 (intent, earth_view, predict, globe_side, intent), lesson 2 (vocab_match, choice, predict, route,
choice) and lesson 3's choice step. The keywords, compare, terminator, command, tap and vocab_fill steps share the same
card and the same help, answer and Next code, and `tests/audit2.test.js` checks help for every course step.

A second pass over lessons 3–6 was invalidated. Mid-run the page reset to a fresh cadet on lesson 1. The Vite log shows
another worktree's browser requesting files from this server (:5311), so the reset came from outside this run. The comms
step that looked wrong in that run was re-checked by hand: "I heard you" → "Roger. Copy means I heard you." and Next.

| # | Screen | Action | Reacted? | Instruction updated? | Verdict | Fix |
|---|---|---|---|---|---|---|
| 19 | Any step | open | yes | yes: prompt, "New" intro the first time, do-line | ok | |
| 20 | Step 1 | Brief, Brief again | yes: opens and closes | n/a | ok | |
| 21 | Every step | "what do I do?" | yes | **the do-line twice**: the card showed "Tap Yes, No or Sometimes, or say it" as the do-line **and** inside the feedback box | **said twice** | the feedback box shows only the hint (the do-line is already above it) |
| 22 | predict, globe_side | "what do I do?" | yes | spoken "Guess first. Any guess is fine. Guess first. Then we'll see." and "Drag the Moon to turn it, or tap a side. Tap Far, or drag the Moon around." | **said twice** | `helpLine()` drops the do-line when the hint repeats it; a test checks every course step |
| 23 | intent / globe_side | tap empty space | **no** | no | **silent** | "Tap on the Moon" chip on the voice bar (`globe onMiss`) |
| 24 | intent | tap a wrong place | yes: "Not quite. Tap inside the gold ring." | yes: hint ladder | ok | |
| 25 | choice / vocab | tap a wrong answer | yes: crossed out, "Not that one. …" | yes | ok | |
| 26 | Step 1 | mic off / on | yes: bar state | n/a | ok | |
| 27 | earth_view | Library tab mid-step, then Flight School | yes | yes: same step, same feedback | ok | |
| 28 | choice | "open the library" mid-step, then "go back" | yes | yes: resumes | ok | |
| 29 | Any step | the answer | yes: feedback, Next, Moon marks | yes: the do-line goes, Next shows | ok | |
| 30 | Answered step | "pancakes" | **no**: router `ignore` without a notice | n/a | **silent** | a typed turn the router can't use shows "Didn't catch that" (`turn_router.route`, `notice` for `not heard`) |
| 31 | Open step | "next" before answering | **no** (the router took `next`; Academy did nothing) | **no** | **silent** | "Answer this one first." + the hint, which also shows on the card |
| 32 | Answered step | "next" / Next | yes | yes | ok | |
| 33 | Last step | the answer | yes: patch | yes: "1 of 7 patches. 6 lessons to go." + offer | ok | |
| 34 | Patch | "what do I do?" | yes | yes | ok | |
| 35 | Patch | "next" | yes: next lesson | yes | ok | |
| 36 | Lesson | **"back to the map"** | **no**: router `ignore (not_an_answer)` | **no** | **stuck** (the audit itself got stuck here) | "back to / go to / take me to / show me the map" are `map` intents |
| 37 | Returning cadet | Mission tab mid-lesson, then back | yes | yes: resumed at the step | ok | |
| 38 | Returning cadet | reload mid-lesson | yes: the map | the map's Next-up is that lesson | ok (by design: a reload starts at the map) | |

Before: `img/audit2/before-help-twice.jpg`.

### Check ride → qualified

| # | Screen | Action | Reacted? | Instruction updated? | Verdict | Fix |
|---|---|---|---|---|---|---|
| 39 | Map (6 patches) | open | yes | yes: "Step 2 of 4 · Check ride" | ok | |
| 40 | Map (6 patches) | Start check ride | yes: the ride cabin and card | yes: "Check ride · Step 1 of 5" | ok | |
| 41 | Ride steps | "what do I do?" / "um what" / the order | headless: the 3D cabin stalled captures on the loaded machine | | not judged here | covered end to end by `handsfree_run.py` (5 of 5 orders, qualified) |

The ride's cabin is mission code (`createCabin(…, {mode: "ride"})`). The card around it is the same lesson card audited
above.

### Library: tour, cards, Find it

| # | Screen | Action | Reacted? | Instruction updated? | Verdict | Fix |
|---|---|---|---|---|---|---|
| 42 | Library | tab / "what do I do?" | yes | yes | ok | |
| 43 | Library | Far side, Near side, Places, Hardware | yes: globe and pressed state | n/a | ok | |
| 44 | Library | tap the Moon | yes: "That spot is 8° north…" | n/a | ok | |
| 45 | Library | tap empty space | **no** | n/a | **silent** | "Tap on the Moon" chip |
| 46 | Library | ask "where did Apollo 11 land?" | yes: card, crew button | n/a | ok | |
| 47 | Library | card ×, Hear the crew | yes | n/a | ok | |
| 48 | Library | Tour, Next stop | yes | yes: "Tour · stop 2 of 8" | ok | |
| 49 | Tour | **"next" by voice** | yes, but **the tour stopped** ("Tour stopped") | **wrong** | **contradiction** | the `heard` decision cancelled the tour before its own `next` ran; tour-step intents keep it (the session now sends `intent` on `heard`) |
| 50 | Tour | Stop; Tour again, then × | yes | yes | ok | |
| 51 | Find it | open, wrong place, Show me, Next, × | yes: "That's Reiner Gamma. Keep looking.", the globe flies | yes: "Find 2 of 5" | ok | |
| 52 | Library | Library tab again (back), Esc | yes: back to the map | yes | ok | |
| 53 | Map | "library", "flight school" | yes (with the session) | yes | ok | |

Before: `img/audit2/before-tour-next-stops.jpg`. After: `after-tour-next.jpg`.

### Settings, cadets, About

| # | Screen | Action | Reacted? | Instruction updated? | Verdict | Fix |
|---|---|---|---|---|---|---|
| 54 | Settings | gear, S, "open settings"; every section | yes | n/a | ok | |
| 55 | Voice | pick a voice, speed, expressiveness, describe | yes: checked, "In use: …" | n/a | ok | |
| 56 | Sound | volume, alarms (live %), flash, vibrate | yes | n/a | ok | |
| 57 | Listening | Hands-free / Hold to talk, filter, improve | yes: the help line under it follows the choice | yes | ok | |
| 58 | Reading | captions, line length, text size ("bigger text" by voice says "Text size 150 percent."), easy-read | yes | n/a | ok | |
| 59 | Display | theme, high contrast, less motion, graphics | yes | n/a | ok | |
| 60 | Display | **Reset voice bar position** (already at home) | **no** | n/a | **silent** | the button says "Voice bar is back at the bottom" for 2 s |
| 61 | Camera & gestures, Keyboard | switches | yes | n/a | ok | |
| 62 | Cadets | Add a cadet | yes: reload to home | yes | ok | |
| 63 | Cadets | Switch | yes: reload as them | yes | ok | |
| 64 | Cadets | Reset my patches ×1, ×2 | yes: "Tap again…", then the map at 0/7 | yes: the first-map beat returns | ok | |
| 65 | Help | Show me around (outside the cabin) | yes: goes to Mission | | ok | |
| 66 | Help | **Pick a place → Go there**, from the Flight School map | **no**: the map swallowed the tap | **no** | **silent** | outside a tap step it opens the place in the Library |
| 67 | Settings | Esc, scrim click | yes | n/a | ok | |
| 68 | About | open, Esc | yes | n/a | ok | |
| 69 | Top bar | theme button ×2 | yes | n/a | ok | |

### Error states, warming, returning

| # | Screen | Action | Reacted? | Instruction updated? | Verdict | Fix |
|---|---|---|---|---|---|---|
| 70 | Offline (no `/api/places`) | open, then tabs | yes: "Can't reach Outpost Luna · Trying again" | yes: recovers on its own | ok | |
| 71 | Flight School offline (`/api/academy/course` fails) | open, wait | yes | **"Close the app and open it again." and a dead end** | **stuck** | retries every 3 s; "Trying again. If this stays, close the app and open it again." |
| 72 | Warming (`/api/health` not ready) | mic, typing "next" | yes: "Starting voice…", typing works | yes | ok | |
| 73 | Mic blocked | mic, typing | yes: "Mic blocked", "Mic is blocked. Type instead." | yes | ok | |
| 74 | Any | the session socket misses its 3 s ready (slow boot, software GL, loaded machine) | the app silently fell back to `/api/ask` **for good**: no router, so chatter was graded and typed "library" or "next" got "I don't know that one yet" | | **broken** (found with the P0) | the socket retries with a back-off and reconnects after a close |
| 75 | Map (returning) | open | see 13 | | | |

### Cross-screen transitions

By tab, voice and key, every pair of Flight School (map / lesson / patch), Library and Mission (picker): `mode_switch.py`,
`keys_e2e`, the audit's tab and voice rows (27, 28, 37, 52, 53) and Esc (rows 16, 17). The only failures were 36
("back to the map") and 49 (the tour). Both are fixed.

## P0: room chatter on the voice bar

This was reported mid-audit: the packaged app "keeps flickering badly", and the bar showed the overheard words "Oh." and
"Shit. Shit." Fixed in f829202.

- **One displayed-state machine** (`voice.js` `DISPLAY`). Every state the bar shows stays up at least 600 ms, and a request
  superseded inside that window never paints. The border glow and the orb follow the displayed state.
- **Overheard words never show.** An open-mic turn shows no words and no "Hearing you" until the router accepts it, and an
  ignored turn leaves no trace in the bar, caption or transcript. Space (push-to-talk) and the Web Speech fallback are
  explicit, so their words show at once, masked.
- **"Thinking" only for a turn that was taken.** It shows after a non-ignore decision, or 450 ms with no decision. Filler,
  echo, a low `device_directed` and rude turns never start it. A decision that arrives before the client's own turn end
  (from the ear relay) is cached and used.
- **Profanity is masked everywhere kid text shows** (bar, captions, the transcript store and view, the card's "you
  asked"). Arc Tagger's safety tags are the first layer (`backend/app/safety.py`, `on` and `p ≥ thr`). The offline word
  list is the backstop (`frontend/src/profanity.js`). A rude or toxic turn is never graded, never routed as a question and
  never shown.
- **Crisis or grooming cue:** one gentle CAPCOM line ("Let's take a break. Talk to a grown-up you trust.") and a flag at
  `GET /api/safety/flags`, with no words.
- **PII tags** only keep the words out of the turn log. The tagger's PII tag fires on almost everything.
- **Tagger misses** go to `docs/ARC_FEEDBACK.md` for the Arc team. On the owner's own "shit shit oh" the tagger returned
  no profanity tag, a 0.99 `pii.leak` and `device_directed` 0.91.
- **Tagger latency.** The tagger call is capped at 300 ms a turn, so a busy model server never holds up routing.
- **Check:** `frontend/tools/chatter_steady.py` feeds the ear "Oh.", "um", two adults talking and the profanity on the
  map, a lesson, the Library and the cabin. It asserts 0 overheard words, no Thinking and ≤ 1 state change, then checks
  that a directed question still shows its words and is answered. Result: **PASS**.

## Mission / cabin findings (for routing, not fixed here)

The mission agent on `feat/mission-gameplay` owns these.

| # | Where | What | Why it matters | Suggested fix |
|---|---|---|---|---|
| M1 | Cabin, Now strip (`mission/objective.js`) | The owner's catch is confirmed in code. `nowObjective()` returns `first_shift` ("Set power, then End shift.") from the shift number alone. Changing power never changes the line, and nothing says "Power set". | The strip repeats an instruction the kid has already done. | Make the objective depend on what the kid did. After the first allocation: "Power set. Now press End shift." Acknowledge each order on the strip for about 2 s ("Heaters up: done") before the next objective. |
| M2 | Mission tab, cadet not qualified | The picker greets them as "Pick a site, Commander Nova…" although they haven't passed the check ride. | It breaks the story arc (STORY.md: qualified → picker). | Show the picker with a "Cadet: fly your check ride first, or try it now" line, or send them to Flight School with one line. |
| M3 | `mission/ui.js` line 534 (`radio("kid", text)`, no-session path) | The cabin radio log shows the kid's raw text. The session path is masked in `main.js` (`radioKid`); this one isn't. | Profanity could show in the cabin log when the session is down. | `maskProfanity(text)` there (`frontend/src/profanity.js`). |
| M4 | Check ride, headless | On a loaded machine the ride cabin stalls Playwright captures for more than 20 s. | Not a kid-facing bug, but it makes the ride hard to audit automatically. | Pause the render loop on `document.hidden`, and cap the ride cabin's frame rate when nothing moves. |

## Verify

| Check | Result |
|---|---|
| Backend `pytest` | 793 passed, 2 skipped (after the P0). Router, safety and session suites re-run after the audit fixes. |
| Frontend `node --test` | 132 pass, including `profanity`, `voice_display` and `audit2` (help never repeats; copy budgets; every CSS file keeps its `@import`s first) |
| `chatter_steady.py` | PASS |
| `ux_audit2.py` | before and after above |
| `tools/handsfree_run.py` (live, text mode, :8411 + :8200) | **PASS** (replies to noise: 0, "I don't know" only for the real question, qualified, cabin tour 12/12 by voice). An earlier run FAILed on "replies to noise: 1" at load 56. The new per-turn safety-tagger call (uncapped) slowed the "yes" to Take command, so its reply landed in the next noise turn's window. The call is now capped at 300 ms (`safety.TAGGER_BUDGET_S`); past that, the word list decides alone. |
