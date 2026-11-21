# My Brain

My Brain is the cadet's own page about two things: what they've learned, and how the outpost works with them. It has
a grown-up side in Settings → For grown-ups → Progress.

It grew out of the old cadet area, the call-sign chip on the Flight School map. That chip now opens My Brain, and My
Brain has "Change call sign".

- **Cadet side:** `frontend/src/brain.js`, styled in `brain.css`. It opens from:
  - the top bar's **My Brain** button;
  - the call-sign chip on the map;
  - **B** on the keyboard, or focus plus A on a controller;
  - voice: "my brain", "what have I learned", "how does the outpost think" (the `brain` intent in
    `backend/app/turn_router.py` NAV).
- **Grown-up side:** `frontend/src/progress.js`, which renders `brain.js` `practiceHtml` and `computerHtml`.
- **The one new store:** `frontend/src/brain_store.js` (§5).
- **Grown-up counts:** `backend/app/brain.py`, `GET /api/brain/summary` (§4).
- **Tests:** `frontend/tests/brain.test.js` and `backend/tests/test_brain.py`.

## 0. Why the name "My Brain"

- **It's the owner's word, and a cadet gets it without reading.** "My Brain" is what I've learned and what I know.
- **"My" makes it the cadet's.** Nobody is watching them; it's their own page. Under "How the outpost thinks", the
  app explains its own side in the same plain words.
- **Rejected names:**
  - "Flight Log" fits the console look, but reads as a list of flights. It also hides the voice and how-it-thinks parts.
  - "Progress" is the grown-ups' word and stays theirs.
- **The space look carries through.** The star map is a night-sky constellation of big ideas, and the top-bar icon is
  a star.

## 1. What the system already knows and decides, per turn

Everything below runs on the device. The left column is the part of the system; the right column is what it does and
what it keeps.

| Part | What it does (and keeps) |
|---|---|
| **The ear: Arc Transcriber Space, libarc ABI 2** (`model_server/app/arc_ear.py`, `docs/ARC_ABI2.md`, `docs/LOCAL_EAR.md`) | Gives words and partials, name links with p (`link_view`), almost-matches (`almost_view`), disfluency, quantities, word confidence, leak and barge-in. `device_directed` drives the router gates. Speaker is always None, and the ear's act/intent are None (`docs/SPEECH_SIGNALS_AUDIT.md` §2). The v2 room read-outs are shadow only (`arc_room.py`). Per turn and in memory (`backend/app/session.py` `EAR_ABI2`). Never stores words. |
| **Entity layer** (`docs/ENTITY_LAYER.md` §3) | `EntityMemory` is per session and in memory only. |
| **Arc Tagger** (`model_server/app/arctag.py`, `backend/app/readout.py`, `backend/app/safety.py`) | Uses domain `kids` for safety and `assistant` for the Director read-out. Finds act, intent, mentions, numbers, PII and `hard_pii` (address, phone, email, card, ID, date of birth, handle). `safety.classify` gives `mask` (the turn is ignored), `care` (CAPCOM's "Let's take a break. Talk to a grown-up you trust."; an entry in the safety ledger, `backend/app/safety_ledger.py`, per cadet and day, kept 30 days, `GET /api/safety/flags`) and `pii` (kept out of the log). |
| **Privacy guard** (`backend/app/director.py` `_hard_pii`, `NAME_GIVEN`) | Says "Let's keep names and addresses private." Highest floor priority (`docs/SESSION_CONTRACT.md` §3). A guarded turn is logged as `"text":"<private>"` with `guard: true` and never a clip (`backend/app/turnlog.py` `finish`). |
| **Screen masking** (`frontend/src/profanity.js` `maskProfanity`) | Masks rude words in on-screen kid text. Stores nothing. |
| **Session Director** (`docs/SESSION_CONTRACT.md`) | Streams in, typed decisions out, under the floor rules: one voice at a time, the kid always wins, never talk over the kid, silence is fine. The learned model (`backend/app/director_model/runtime.py`) runs in `guarded` mode: r12 xl on "quiet", r10 on hot and echo (`director_model/RESULTS.md` round 12). The privacy guard always wins. |
| **On-device learning** (`docs/ON_DEVICE_LEARNING.md`, `backend/app/learn/`) | Learns per cadet: name aliases (2 confirmations, or 1 at p ≥ 0.85; cap 24; 45-day half-life), the end-of-turn wait (0.5 to 0.8 s), pace and yes/no words. Learns per computer: the echo path. Kept in `profile-<id>.json` and `device.json`, mode 0600. Shown in Settings → What the app has learned (`frontend/src/learning_ui.js`). |
| **Turn log v2** (`backend/app/turnlog.py`) | On by default through `prefs.improve` (a grown-up can turn it off), or during a grown-up's Playtest session. Redacted text (`<callsign>`, `<name>`, `<address>`, `<number>`), with numbers and enums only for the ear, room, router and Director. Every turn and signal carries the cadet `profile`, the `course` and the `day`; a private turn carries `guard_kind` (pii, name, language, unkind). Signals: repeat, negate, retap, hint, pass, undo, confirm. Kept 30 days and capped at 5 MB total. `DELETE /api/turnlog` empties it. |
| **Safety ledger** (`backend/app/safety_ledger.py`) | What the safety path acted on, per cadet profile and day: `{day, kind: language / unkind / care / personal_info / unsafe_request, source: tagger / wordlist / phrase, screen, course, n}`. Never words. Care entries 30 days, others 60. Mode 0600. Cleared by Reset. Never in a Playtest export. |
| **Room state** (`frontend/src/room.js`) | Calm, busy or loud, plus a listen mode (open, hold, offer, type). Only the label is sent. The turn log copies the label. |
| **0.6 voice signals** (`docs/GAMEPLAY.md` §14) | Radio readback (`backend/app/mission/readback.py`): in-session praise or a nudge, never counted. Hesitation (`backend/app/hesitation.py`): fillers, a pause of 2.5 s or more, or low confidence move the hint ladder one rung early, once per step. The pause itself is never stored or shown. |
| **Learning data** | The course (`backend/data/academy/course.json`, 13 lessons). Sourced facts (`backend/data/learning/concepts.json`, 31 concepts, no lesson mapping). `atm-academy` holds patches, qualified, and the half-done step. `outpost-missions-flown:<call sign>`. Debriefs are computed live (stars, grade, objectives, good calls, physics "numbers" lines) and not kept. The paused mission is `saves/mission.json`. Class lessons. |

**What was missing for learning analysis:** how a step went. Tries, first-try right, with a hint, or shown were all in
memory and gone when the lesson ended. So §5 adds one small on-device aggregate of counts.

## 2. Rules from kids' privacy law (and what they mean here)

| Rule | Where it comes from | What it means for My Brain |
|---|---|---|
| Collect the minimum and keep it on the device. A parent can review and delete it. | COPPA (US), GDPR Art. 8 and the UK Age Appropriate Design Code ("data minimisation", "default settings", "parental controls") | Only counts and lesson ids are added, on this computer. Nothing is sent. Every number has a delete path (§6). |
| No profiling by default. No nudges to share more. | UK AADC "profiling" and "nudge techniques" | No personality, ability or emotion inference. There is no "slow", "anxious" or "struggling". The app reports its own actions ("gave 2 hints early after a long pause") and outcomes ("first try"), not traits. |
| Be open with the child, in words they understand. | UK AADC "transparency"; AI-transparency norms for minors | "How the outpost thinks" explains the listen → check → keep private → take turns loop in four lines. The cadet sees what was learned about their voice. |
| School records belong to the school and the family. | FERPA (US schools) | The printable report stays on the device. A teacher prints it; nothing goes to us. There are no accounts, and call signs aren't real names (story.js `CALLSIGNS`). |
| Safety without surveillance | Duty of care; AADC "best interests" | Grown-ups see how many turns were kept private or filtered, never the words. A care cue shows as a dated banner (no words), kept 30 days on this computer. |
| Audio only with consent | `docs/DIRECTOR_LOOP.md` §1b, `frontend/src/playtest_ui.js` | Playtest audio needs a grown-up's tick ("I'm the parent or guardian, or I have their permission."), turns itself off after 3 h, and has its own export and delete. My Brain never reads audio. |

These are design rules, not legal advice. A school's own policy still applies.

## 3. The cadet's page

Simple and motivating, with no surveillance feel. The cadet only ever sees **their own** learning and **the app's own**
behaviour.

| Signal | Where it comes from | What we show | Who sees it | Why it helps learning | Privacy note |
|---|---|---|---|---|---|
| Stars (big ideas) | course + `atm-academy` badges + practice counts | A star map. Each lesson's big idea is a star: lit once its patch is earned, glowing while practising, dim when not yet | The cadet | Shows learning as a growing sky, not a score. The next star is visible | Lesson ids only |
| Patches, missions | `atm-academy`, `outpost-missions-flown:<cs>` | Counts | The cadet | Recognises effort across both modes | Already kept |
| Days in a row | practice counts `days` | A small number | The cadet | Builds a habit without a penalty. Yesterday still counts until tomorrow | Dates only, no times |
| Try next | `progress.js` `summarize` (the same order the app opens lessons in) | Up to two lines, and "Go to Flight School" | The cadet | One clear next step | None |
| Names the app learned | `GET /api/learn` `learned.aliases` | "You say “ticko”. The outpost knows you mean Tycho." (up to 3) | The cadet, on this computer | The app adapting to them feels like teamwork, and they keep using Moon names | The kid's own words, shown back only to them and never sent. Grown-ups remove them in What the app has learned |
| End-of-turn wait | `learned.habits.end_silence_s` (after 5+ turns) | "You take a moment before you answer. The outpost waits for you." | The cadet | Tells a thinker the pause is fine | Says what the app does, never what the child is |
| How the outpost thinks | static copy | Four cards: it listens; it checks who you're talking to; it keeps your words private; it takes turns | The cadet | AI literacy: knowing when a machine listens and what it keeps | — |

## 4. The grown-ups' page (Settings → For grown-ups → Progress)

It sits behind the 3-second grown-up hold, one card per cadet, and is printable.

| Signal | Where it comes from | What we show | Who sees it | Why it's useful for learning | Privacy note |
|---|---|---|---|---|---|
| Concept mastery | practice counts (§5) | A table per lesson: steps, first try (and %), with help, shown, minutes, the big idea and its NGSS hooks | Grown-ups | Tries → first-try right → with a hint is the classic mastery ladder, and it shows which ideas stuck | Counts only |
| Time on task | practice counts `secs`, each step capped at 5 min | Minutes per lesson, and a total | Grown-ups | Effort in real time; a walk away doesn't inflate it | Rounded seconds |
| Hardest lessons | `brain.js` `hardest` (3+ steps, most help) | "Needed the most help: …" (up to 2) | Grown-ups | Where to sit with them | No ranking of children |
| Hint use and pauses | `misses`, `pause` | "N tries weren't right yet. The app gave N hints early, after a long pause." | Grown-ups | Shows that hesitation-aware hints are working | Counts the app's action. The pause itself is never stored |
| Practice days | `days` (60 at most) | "Practised on N days" | Grown-ups | Regularity | Dates only |
| Speaking participation | `GET /api/brain/summary` `talk` (turn log, when on) | Turns, voice vs typed, answered vs let pass, room calm/busy/loud, for this cadet in the course being played | Grown-ups, on the playing cadet's card | Voice confidence, and whether a busy room pushes to typing | Never reads the log's text |
| The app had to try again | turn-log signals repeat / negate / undo / retap | "The app had to try again N times (x% of turns) … That is the app's miss, not the cadet's." The % only from 10 turns | Grown-ups | Shows where the app misheard or misrouted | Echo and not-meant-for-the-app turns are left out |
| Help-seeking, persistence | practice counts `asks`, `helped`, `shown` | "Asked for help N times." "After a hint, solved it N times; the app showed the answer M times (x%)." The % only from 3 steps | Grown-ups; the cadet sees only good news ("You kept going after a hint N times.") | Asking and persisting are skills to grow | Counts only |
| Common mix-ups | practice counts `traps` (`backend/app/academy/routes.py` `mixup_of`) | Up to 3, each seen at least twice: "Layers, step 3: named the pit before the layers it cuts (2 times)." | Grown-ups | The misconception, not the child, is the target | Kinds only, never the answer given |
| Mission decisions | debriefs (`GET /api/mission/{id}/debrief`) | Stars, grade, objectives, Try next (unchanged from #165) | Grown-ups | Applying science to safety calls | Live only, not kept |
| Safety summary | turn log `guard` / `guard_kind`, safety ledger | "N turns kept private …", "Kept private: N with personal information, M with a name." Language / unkind counts per week only when a grown-up ticks "Show language and kindness counts" (off by default) | Grown-ups | Reassurance that the guard works; a pattern a grown-up chose to see | Never the words; echoes and talk not meant for the app are left out |
| Care banner | safety ledger `care` (`GET /api/safety/flags`) | At the top of Progress: "The guide suggested a break and a trusted grown-up on <day>." plus what the guide said and help resources. Dismissible; the entry stays 30 days | Grown-ups, every cadet on this computer | A grown-up learns about it on their next visit, even after the app was closed | The day only; never the words |
| What the app adapted | `learn` `describe(include_aliases=False)` | Names learned (count), the end-of-turn wait | Grown-ups | Explains why the app feels different for this cadet | The names themselves are in What the app has learned (remove or reset, one tap each) |
| Data controls | existing sections | Pointers: Voice log and playtest (on/off, delete, export), What the app has learned (remove/reset), Reset (erase progress too) | Grown-ups | — | Every stored item has a delete |

### How this maps to learning-program reporting

- **A standards-style list.** Each NASA lesson carries its big idea and the NGSS performance expectations the
  curriculum cites (`docs/LEARNING_DESIGN.md` §1, §11.2, §12):
  - 1-ESS1-1, 5-ESS1-2, MS-ESS1-1, MS-ESS1-3, HS-ESS1-6;
  - 5-PS2-1;
  - MS-ETS1-1, MS-ETS1-2, 3-5-ETS1-1.

  These are hooks, not an alignment review, and the sheet says so. Class lessons list by pack.
- **Mastery evidence.** First-try right, then with a hint, then shown is the evidence a teacher's rubric asks for
  ("independently / with support / not yet").
- **Printable.** "Print" gives one cadet per page on light paper (`progress.css` `@media print`). No accounts and no
  export to us, so it fits FERPA.

## 5. The one new store: practice counts (`frontend/src/brain_store.js`)

- **Key:** `localStorage["outpost-brain"]`, per cadet (prefs.js `PROFILE_KEYS`, so it moves with the profile).
- **Shape:** `{v:1, course:"moon", lessons:{<lessonId>:{steps, first, helped, shown, misses, pause, secs, asks, traps?:{"<kind>@<step>": n}}}, days:[YYYY-MM-DD…≤60]}`.
  `asks` counts the cadet asking for help (the hint ladder, `academy/ui.js` `climbHelp`, status "asked"); `traps` counts
  a miss's misconception kind (pit, soundalike, order, sequence, pick: the reply's `mixup`, at most 12 per lesson).
- **What feeds it:** the Academy's `outpost:lesson-result` event (`frontend/src/academy/ui.js` `answer`). That event
  now also carries `lesson`, `shown`, `misses`, `helped`, `hes`, `step_s` and `ride`. The session still forwards only
  `status` and `step_type` to the turn log.
- **What counts:**
  - "hint" is a miss (plus `pause` when the app hinted early).
  - "passed" counts as first, helped or shown.
  - A missed check-ride order counts as shown.
  - Videos and predict guesses never count, and neither do "progress", "ignored" or "help".
  - `helped` means the hint rung rose above the glow the step starts with (`baseRung`).
- **Sanitised** on read and on write (`clean`): known ids, whole numbers and real dates only. A hand-edited value
  can't carry text into a view (`tests/brain.test.js` "clean").
- **Reset:**
  - It's a progress key (reset.js `PROGRESS_KEYS`), so Start over keeps it and "Erase progress too" erases it.
  - Settings → Cadets → Reset progress clears it with the patches.
  - Switching cadets snapshots it with the rest.

## 6. What we do NOT show, and why

| Not shown | Why |
|---|---|
| Any transcript, the redacted turn text, the words a filter caught | Data minimisation; words a child said are not a report |
| Emotion, confidence, "hesitant", pace as a trait, ability labels | No profiling (AADC); the signals aren't diagnoses and would mislead |
| The privacy guard's or care flag's content | Safety without surveillance; a grown-up who needs more talks with the child |
| Rankings or comparisons between cadets | Best interests; it's not a leaderboard |
| Per-turn timelines, times of day | Not needed for learning; finer than a day is not kept |
| Ear internals (dd, link p, almost-matches), Director model numbers | Engineering signals (diagnostics, `docs/DIAGNOSTICS.md`), not learning ones |
| Anything to the cadet about another cadet | Each cadet sees only their own page |

## 7. Backend: `GET /api/brain/summary?profile=p1&days=30` (`backend/app/brain.py`)

- **Loopback only:** the `LocalGuard` middleware on every route (`backend/app/main.py`), plus the local token like
  `GET /api/learn` (`diag.authorized`).
- **Query:** `?profile=p1&course=moon&days=30&sensitive=0`. `profile` and `course` filter the turn log's lines (a line
  from before profiles were logged belongs to no cadet). `sensitive=1` is sent only when the grown-up ticked "Show
  language and kindness counts".
- **Returns** `{days, profile, course, talk:{turns, voice, typed, answered, passed_by, days, room:{calm,busy,loud}, signals:{hint,pass,repeat,negate,undo,retap,confirm_cancel}, retried, min_n, shadow:{interruptions}}, safety:{guarded, guard:{pii,name[,language,unkind]}, care[, weekly]}, adapted:{names, wait_s, turns, waits_longer}, log:{turns, bytes, retain_days}, words:false}`.
  `shadow` is logged and returned but never rendered (P2).
- **Date window:** signal lines carry their own `day`, so signals are counted inside the window like turns (before,
  "last 30 days" signals were all-time).
- **Reads only** the turn log's `k`, `src`, `day`, `profile`, `course`, `router.outcome` / `reason`, `arc.dd`,
  `audio.echo_share`, `ear.barge`, `room.state`, `guard` / `guard_kind` and the signal `sig` / `ref`. Never
  `text`, alias heard forms or call signs (`backend/tests/test_brain.py`
  `test_summary_has_no_words_names_or_call_signs`).

## 8. What's left

- **Per-concept mastery below the lesson.** Lessons cite `concepts.json` facts but steps don't name a concept. A
  `concept` field on steps would give a finer table.
- **Mission decisions as counts** (shelter on time, readbacks). Debriefs are live only, so a small aggregate like §5
  would keep them.
- **A teacher roll-up across computers.** Out of scope: nothing leaves the device.

## 9. Screenshots

These are the cadet's side and the grown-ups' side at 1440x900 and 1280x720. `frontend/tests/e2e/brain_e2e.py --out`
makes them again.

![My Brain, 1440x900](img/brain/brain_cadet_1440x900.jpg)
![My Brain, 1280x720](img/brain/brain_cadet_1280x720.jpg)
![My Brain: voice and how the outpost thinks](img/brain/brain_cadet_bottom_1280x720.jpg)
![Grown-ups: Practice](img/brain/brain_grownup_1440x900.jpg)
![Grown-ups: Practice, 1280x720](img/brain/brain_grownup_1280x720.jpg)
![Grown-ups: talk, safety, adapted, controls](img/brain/brain_grownup_computer_1280x720.jpg)

## 10. Design principles (feat/brain-signals)

The Brain is meant to help grown-ups support three kinds of regulation in kids: **self-regulation** (taking a break,
asking for help, sticking with it), **behaviour and safety** (what the safety path did), and **learning** (what stuck,
what got mixed up). It does that under these rules:

1. **Per learner, per course.** Every count is for one cadet profile (p1…p6) in one course. Never across children.
2. **Counts and rates only.** Never words, transcripts, answers given or audio.
3. **Report the app's actions and outcomes, never traits.** "The guide suggested a break", "the app had to try again",
   "kept a turn private for language". Never "aggressive", "at risk", "rude", "anxious", "slow".
4. **Behaviour metrics skip echoes and talk not meant for the app.** A turn the router marked `echo`, a heard turn
   mostly made of what the app just said (`echo_share` ≥ 0.6), or a heard turn with `device_directed` < 0.5 never
   counts toward signals, guard categories or interruptions. The safety ledger applies the same rule to every kind
   except care.
5. **Minimum N before a rate.** 10 turns for talk rates, 3 steps for persistence, 2 for a mix-up.
6. **Sensitive categories off by default.** Language / unkind counts are shown only when a grown-up ticks "Show
   language and kindness counts" in For grown-ups (this computer's choice, cleared by Reset). Interruptions are logged in
   shadow mode and not shown at all.
7. **Care flags on, sticky for 30 days, then deleted.** A grown-up sees the banner on their next visit and may dismiss
   it; the entry itself stays until its 30 days are up.
8. **Everything expires.** Safety-ledger counts 60 days, care 30, the turn log 30, practice days 60.
9. **No emotion inference.** The ear has no emotion head (`model_server/app/arcmeta.py`). The old emotion paths
   (`session.EMOTION_INPUT`, `main.js` `EMOTION_INPUT`, `steering.AFFECT`) are quarantined behind flags that are off.
10. **On this device only.** Cleared by Reset. The safety ledger is never in a Playtest export.

## 11. Signals → Brain

Every signal the app has, what it does live, where (if anywhere) it is kept, who sees it, and its default.

| Signal | Source | Live use | Stored where | Shown to whom | Default | False-positive risk |
|---|---|---|---|---|---|---|
| Lesson grade (first / helped / shown / miss) | `academy/routes.py` attempt | Hint ladder | `outpost-brain` lessons (per cadet) | Grown-ups (table); cadet (stars) | On | Low: graded by the step's own rubric |
| Early hint after a long pause | `hesitation.py` + `ui.js` `hes` | One rung early | `outpost-brain` `pause` (count) | Grown-ups | On | Medium: a pause may be thinking; reported as the app's action |
| Help asked | `ui.js` `climbHelp` | Next hint rung | `outpost-brain` `asks` | Grown-ups; cadet (positive line) | On | Low |
| Misconception kind | `routes.py` `mixup_of` (pit, soundalike, order, sequence, pick) | The "why" line | `outpost-brain` `traps` | Grown-ups (≥2) ; cadet only "you worked through a tricky mix-up" | On | Medium: a mis-hear can look like a wrong pick |
| Repeat / negate / undo / retap | `turnlog.SessionLog` | None (outcome labels) | Turn log signals (day, profile, course) | Grown-ups ("the app had to try again") | On with the turn log | Medium: "no" may be conversational; echo turns excluded |
| Lesson pass / hint after a spoken answer | `turnlog.SessionLog.lesson` | None | Turn log signals | Grown-ups (counts) | On with the turn log | Low |
| Confirm yes / cancel | `turnlog.SessionLog.finish` | Confirm flow | Turn log signals | Not shown (cancel counted in `signals`) | On with the turn log | Low |
| Help intent in the router | `turn_router.py` NAV a11y | Opens help | Not aggregated (the lesson's `asks` covers it) | — | — | — |
| Privacy guard (pii / name) | `safety.classify` pii, `director.NAME_GIVEN` / `_hard_pii` | Private line, turn text not kept | Turn log `guard_kind`; safety ledger `personal_info` | Grown-ups (counts) | On | Medium: false PII flags on normal text (`docs/ARC_FEEDBACK.md`) |
| Language (word list / tagger profanity) | `safety.classify` mask | Turn ignored, never graded | Turn log `guard_kind=language`; safety ledger `language` | Grown-ups, weekly, only with the toggle | **Off** | Medium: song lyrics, a sibling, a video heard back (echo / dd excluded) |
| Unkind (tagger toxicity) | `safety.classify` mask | Turn ignored | Turn log `guard_kind=unkind`; safety ledger `unkind` | Grown-ups, weekly, only with the toggle | **Off** | High: the tagger mis-tags (`docs/ARC_FEEDBACK.md`) |
| Unsafe request (tagger child.inappropriate) | `safety.classify` mask | Turn ignored | Safety ledger `unsafe_request` | Not shown yet (kept 60 days) | Off | High |
| Care (crisis / grooming cue) | tagger or the phrase lists | CARE_LINE, nothing else | Safety ledger `care` (30 days, sticky) | Grown-ups: banner with the day | **On** | Medium: "kill myself" as a game joke; we prefer a false banner to a missed one |
| Room state | `room.js` | Gates, hold-to-talk | Turn log `room` | Grown-ups (counts) | On | Low |
| Interruptions (barge-in) | the ear `barge` | Stops playback | Turn log `ear.barge` | **Not shown** (shadow, `talk.shadow`) | Shadow | High: echo, siblings |
| Emotion | none (no head) | **None**: quarantined | Nothing | Nothing | Off | n/a |
| Learned names, end-of-turn wait | `app/learn` | Recognition, waits | `profile-<id>.json` | Cadet; grown-ups (counts) | On | Low |
