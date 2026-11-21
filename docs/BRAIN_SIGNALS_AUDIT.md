# Brain signals audit: what the cadet's brain records, and what it could be (2026-11-20)

The owner asked: in the brain, are we recording profanity, safety and intent statistics, the way Arc already reads
them, to build a real brain of the cadet? Every signal from the Arc Transcriber ear (tags, links), Arc Tagger and the
Director, audited for what it could become, with kids' regulation in mind.

This is a design audit and proposal. Nothing here is implemented. Code references are to `origin/main` at `b5570bd`.
This is not legal advice. Every regulatory note says what the rule is aimed at; a lawyer signs off before anything
that crosses the line ships.

**Short answer: no.**
- The brain keeps lesson outcomes as counts (`frontend/src/brain_store.js`), vocabulary boxes and reading counts
  (`academy/speech_store.js`), and a few things the app learned about the cadet's voice (`backend/app/learn/`).
- Profanity is masked and dropped, and never counted on its own. Today it is merged with privacy into one number,
  "turns kept private".
- Care flags (self-harm, grooming) live in memory and are gone when the app quits.
- Intent, act, device_directed, link, disfluency, barge-in and room readings are used per turn and then forgotten. The
  only place they are kept is the opt-in turn log, which exists to retrain the Director. It is per computer, not per
  cadet.
- That is on purpose: `docs/BRAIN.md` §2 and §6 is a no-profiling policy (UK Age Appropriate Design Code). This
  document shows how much more the brain could hold, and marks each idea as fitting that policy or crossing it.

Legend used below:
- **[fits]** fits the current policy: counts of outcomes, or of what the app did. No trait, no inference about the child.
- **[grey]** fits on paper, but needs a careful label, a short retention, or a notice to the child.
- **[CROSSES]** profiling or behaviour monitoring under the policy as written. Karan decides.

## 1. Every signal the stack produces per turn

Each part gives: what it produces, who uses it, and whether anything is kept.

### 1.1 The ear (Arc Transcriber Space, libarc ABI 2)

Source: `model_server/app/arc_ear.py`, relayed by `backend/app/listen.py`, held on the session as `k["ear"]`
(`backend/app/session.py:73` `EAR_ABI2`, `:459`).

- **Words, partials, `spoken` form, `clean_text`.** Used by the router, Director, mission NLU, screen. Kept only as
  redacted text in the turn log (`turnlog.py:357`).
- **Name links** `{entity, state, p, kind}`. Used by `director._link` (acts only at p ≥ 0.99), the voice bar, the
  entity memory, Director features. Turn log keeps p, state and kind, never the name (`turnlog.py:119-121`).
  Reliability: p = 1.0 is right 85-93 % of the time; under 1.0 it is close to a coin flip
  (`docs/SPEECH_SIGNALS_AUDIT.md` §3).
- **Almost-matches, quantities, n-best, decoder text and agreement.** Used by the Director and learning. Turn log keeps
  p, kinds and small numbers only (`turnlog.py:122-141`).
- **Disfluency (`disfl`: filler / repeat / fragment), `uconf`, `max_pause_s`.** Used by `hesitation.hesitant`
  (`backend/app/hesitation.py:30-44`) to bring the next hint sooner, once per step. Never stored, never shown
  (`hesitation.py:15-17`). The turn log keeps a disfluency count and uconf as Director features
  (`turnlog.py:111-133`).
- **`device_directed` (dd).** Gates the router, barge-in, the room-talk check, the Director. Turn log keeps it.
  Reliability: AUC 0.70 on round-11 synthetic kid turns. At the 0.5 gate it keeps 93 % of directed turns and 78 % of
  room talk (`docs/SPEECH_SIGNALS_AUDIT.md` §3).
- **`playback_leak`, `barge_in` and its p.** Used by the echo drop and barge-in. Reliability on a real laptop: leak AUC
  0.72; Arc's BARGE_IN fires on 64 % of our own lines with no kid present (`docs/ARC_ABI2.md` §8).
- **End of turn (`eot`), pace numbers.** Used by on-device learning (`learn/habits.py`).
- **Speaker: always None. Act and intent from the ear: always None** (`docs/SPEECH_SIGNALS_AUDIT.md` §2).
- **Emotion: never produced.** `{"t":"emotion"}` is always unavailable (`arcmeta.py`), but the plumbing still exists:
  `session.py:488` stores a label and `session.py:964` passes it to the brain. It is dead code.
- **Audio events (p ≥ 0.3).** Produced, used by nothing (`arcmeta.py:191-199`).

### 1.2 Arc v2 room read-outs (shadow only)

Source: `model_server/app/arc_room.py`, `docs/ARC_V2.md` §7. Kept on the turn read as `room`, never used by a rule,
the router, safety or the Director.

- Utterance act (question / command / confirmation / chatter / statement): 58 % right on 209 labelled kid turns.
- Addressee (device / other_person / reading_aloud), BETA: said "device" on only 65 % of turns that were all to the
  device.
- Safety, 15 classes, BETA: a class over threshold on 17.8 % of benign kid turns (`pii.leak` 78, `profanity.strong` 25,
  `toxicity.hate_identity` 16 of 752).

Not usable for any brain statistic yet.

### 1.3 Arc Tagger

Source: `model_server/app/arctag.py`, `backend/app/readout.py`.

- **Read-out (`assistant` domain):** act, intent, mentions, numbers, PII spans, `hard_pii`, `complete`
  (`readout.py:7-27`). Only on turns routed question / order, about 52 % of turn ends. Used by the Director (features,
  `_link`, the privacy guard) and mission NLU. Kept: the act list only (`turnlog.py:358-359`). Intent is used by the
  Director model and never kept.
- **Safety (`kids` domain), every turn, 0.3 s budget** (`safety.py:105-115`). Classes `safety.profanity*`,
  `toxicity*`, `child.inappropriate`, `crisis.self_harm`, `child.grooming_cue`, `pii*`. Reliability: in the kids
  domain on 1,500 round-11 texts, 36 tagged, all real; on indirect self-harm phrasing, precision 1.00 and recall
  about 0.5 (`docs/ARC_FEEDBACK.md`, "Status"). `pii.leak` used to fire on almost every short turn. That was fixed
  in 0.5, but it is still treated as "keep out of the log" only.

### 1.4 Safety decision

Source: `backend/app/safety.py:118-129` `classify`, called at `session.py:722-735`.

- **`mask`** = the word list (`safety.py:27-33`, same list in `frontend/src/profanity.js`) or a mask tag. The router
  ignores the turn silently (`turn_router.py:999-1000`, reason `safety`). The screen masks the word. The turn log stores
  the turn as `"<private>"`, `guard: true` (`session.py:758`, `turnlog.py:392-393`). **Not counted anywhere as profanity.**
- **`care`** = a crisis or grooming tag or phrase. CAPCOM says the care line. `Session.flags` gets
  `{kind, tags, screen, ts}` (`session.py:729-732`), capped at 50, **in memory only**. The turn returns before the
  turn log starts (`session.py:734` vs `:751`), so a care turn is never logged. `GET /api/safety/flags` lists them
  (`main.py:213-218`).
- **`pii`** = a PII tag. The words stay out of the turn log; the turn still runs.

### 1.5 Privacy guard (Director)

`director.NAME_GIVEN` and `director._hard_pii` (`director.py:25`, `:151`, `:447`; `session.py:970-972`). Says "Let's
keep names and addresses private." The turn is logged `<private>`. The count is merged into the same `guarded` number
as profanity.

### 1.6 Router

`backend/app/turn_router.py:985-1104` `route()`. Per turn it gives an outcome (ignore / navigate / answer / order /
question), a reason, and an intent for navigation. Reasons that matter for regulation:
- `safety`: rude or unsafe;
- `crew_talk`, `not_directed`, `chatter`, `room_yes_no`, `callsign_other`: talk not meant for the app;
- `echo`, `speaking`: our own voice, or talking while CAPCOM talks;
- `filler`, `not_an_answer`, `too_short`, `unclear`.

Kept: `router.{outcome, reason, intent}` in the turn log (`turnlog.py:373`). `brain.py` reads only `outcome`, so it can
tell "answered" from "let pass", but not why.

### 1.7 Director (rules + learned model)

`backend/app/director.py`, `director_model/runtime.py` (guarded mode: r12 xl in "quiet", r10 in hot and echo). Per
turn it gives the act it chose (answer / ignore / ask_clarify / command / confirm), p, and which model decided.
Kept: `director` and `seen` in the turn log (`session.py:767-778`). Reliability: the model reads kids' acts better than
the rules, but acts wrongly more often outside the guarded classes (`director_model/RESULTS.md`). It is a decision
signal, not a measure of the child.

### 1.8 Floor, barge-in, room

- **Barge-in:** the client decides (`frontend/src/barge.js`). `frontend/src/bargelog.js` keeps the last 200 stops,
  barges and holds **in page memory**, with text. Never persisted, never in the brain.
- **Room state:** `frontend/src/room.js` gives calm / busy / loud and open / hold / type, from the noise floor, room-talk
  turns and failed turns. Only the label goes to the server; the turn log copies it (`turnlog.py:377`, `:453-464`).
  Thresholds were set on fixtures, not a real classroom (`docs/HANDSFREE.md`, "Caveats").

### 1.9 On-device learning (per cadet)

`backend/app/learn/`, `profile-<id>.json`, mode 0600. It keeps name aliases the cadet confirmed, the end-of-turn
wait (0.5-0.8 s), yes / no words, and the "Did you mean" thresholds (`learn/habits.py:1-14`). Per computer
(`device.json`): the echo path. The profile id is real and reaches the server on every connect (`prefs.js:134`,
`session.py:153-155`).

### 1.10 Lessons, speech, missions

- **Lesson results:** `outpost:lesson-result` (`academy/ui.js:804-806`) feeds `brain_store.record`
  (`brain.js:24`): per lesson, steps, first, helped, shown, misses, pause and secs, plus up to 60 practice days.
  Per cadet, in localStorage.
- **Server side:** the session forwards only status and step_type (`main.js:242`). These become the turn log's
  `hint` / `pass` signals (`turnlog.py:439-446`).
- **Speech learning:** reading, questions, read-aloud sessions and words read right, summaries, and vocabulary
  Leitner boxes per glossary word (`academy/speech_store.js`). Per cadet.
- **Missions:** `outpost-missions-flown:<call sign>`. Debriefs (stars, grade, objectives, good calls) are computed live
  and not kept. Readbacks never count (`mission/readback.py:15-16`).
- **Entity memory:** what was talked about, per session, in memory (`session.py:236-237`).

### 1.11 What the grown-ups' page reads today

`GET /api/brain/summary` (`backend/app/brain.py`) returns:
- talk counts from the turn log (per computer);
- `guarded` (profanity and privacy together);
- care flags (all sessions since the app started);
- adapted counts (per cadet).

## 2. Gaps and bugs found on the way

1. **Signals ignore the day window.** `brain.talk_counts` counts `k:"signal"` lines before the `since` check, and
   signal lines carry no `day` (`brain.py:46-49`, `turnlog.py:448-450`). Hint, pass, repeat, negate and undo are
   all-time, while turns are the last N days.
2. **Profanity is not separable from privacy in the summary,** although the log already separates them:
   `router.reason == "safety"` is a masked turn, and `guard` without it is a privacy turn. `brain.py` reads
   `router.outcome` only.
3. **Care flags vanish on quit,** cover every session (not per cadet), and their turns never reach the log. A grown-up
   who opens Progress tomorrow sees 0.
4. **`GET /api/safety/flags` has no local-token check** (`main.py:213-218`), unlike `/api/brain/summary`
   (`brain.py:111`). LocalGuard (loopback, Host / Origin) still applies. Low risk, but it is the most sensitive
   endpoint.
5. **The turn log has no profile id,** though `sess.prefs["profile"]` is right there. This is the whole per-cadet gap
   (§5).
6. **Dead emotion plumbing** (`session.py:488`, `:964`, `belief.kid.emotion`). The policy says no emotion inference.
   Deleting the path makes that promise checkable in code.
7. **The docs disagree on the turn-log default.** `docs/BRAIN.md` §1 says "Opt-in"; the client turns it on by default
   since 0.4.3 (`prefs.js:23`, `:90`); a session.py comment says "off by default" (`session.py:229`). The redacted
   text of kids' turns, logged on by default (on the device only), is the one place the AADC "high privacy by
   default" standard bites (§8, decision D2).
8. **The turn log's redacted text keeps everything a regex did not catch.** A first name said without "my name is",
   a teacher's name, a street name without "I live on". It is on the device, capped at 5 MB, and deletable, but it is
   words.

## 3. What the brain could be

Each idea gives:
- **Source:** where the signal comes from.
- **Reliability:** how far it can be trusted, with numbers where the docs have them.
- **Kid sees / grown-up sees.**
- **Keep:** how long it is kept.
- **Line:** which policy line it touches.

### 3.1 Learning

**L1. Mastery per concept, not just per lesson.** [fits]
- Source: give each graded step a `concept` id (`backend/data/learning/concepts.json`, 31 concepts today; the
  Archaeology pack has its own), and count first / helped / shown per concept in `brain_store`.
- Reliability:
  - tapped and typed answers are exact;
  - spoken answers go through the ear, which loses 49 % of 1-word and 21 % of 2-word turns on synthetic kid voices
    (`ARC_FEEDBACK.md`, short turns), so some "misses" are the ear;
  - record `via: voice|tap|typed` and count a voice miss as a miss only when the grader heard a plausible try (it
    already ignores non-tries).
- Kid sees: the star map at concept level ("You know: craters, regolith. Still glowing: radiation").
- Grown-up sees: independently / with support / not yet, per concept, with the NGSS hooks.
- Keep: while the profile exists. Erased by Reset progress.
- Line: an outcome record, the same kind of thing as today's lesson table. AADC allows processing needed for the
  core service. It must stay a practice record, not a grade (see L5 and §8, EU AI Act).

**L2. Retrieval (spaced review) per concept.** [fits]
- Source: extend the vocabulary Leitner boxes (`speech_store.js`, `BOX_DAYS [0,1,3,7,14]`) to concepts. A concept
  right on first try moves up a box; a miss moves it back to box 1.
- Reliability: as L1.
- Kid sees: a "Due for a quick review" star, and the app opens that step first.
- Grown-up sees: "Remembered after a week: 8 of 11 concepts."
- Keep: box and due date only (a day, never a time).
- Line: an adaptive feature for the core service; this is what AADC "profiling for the core service" allows. Tell the
  kid in plain words ("The outpost brings back ideas you haven't seen in a while").

**L3. Vocabulary in the cadet's own speech.** [CROSSES, mildly]
- Source: the entity memory and the ear's name links on the cadet's own questions. Count, per entity id, how often
  the cadet used a glossary or catalogue word unprompted (not in a step's options).
- Reliability: count only links at p = 1.0 (85-93 % right; under that it is a coin flip). Typed text is exact.
- Kid sees: "Words you use: Tycho, regolith, terminator."
- Grown-up sees: a count of words used, not which.
- Keep: the 20 most recent ids.
- Line: derived from free speech, this is an interests profile. AADC defines profiling to include evaluating
  interests. It is benign and stays on the device, but it is profiling. A safer variant is [fits]: count only words
  from the course glossary, used in an answer to a step that asked for one.

**L4. Reading and speaking practice.** [fits as volume; CROSSES as a level]
- Source: `speech_store` `read`, `aloud`, `aloud_words`, `summaries`, `points` (already kept).
- Reliability: words read right come from the ear. WER is about 32-35 % on synthetic kid voices
  (`SPEECH_SIGNALS_AUDIT.md` §5), and real kids will be worse, so it cannot be a reading level.
- Kid sees: "You read 4 passages aloud this week."
- Grown-up sees: volume per week.
- Keep: per course while the profile exists.
- Line: a words-correct-per-minute or reading-level score is an ability assessment from an AI. That crosses the
  policy, and in an EU school it is an Annex III high-risk use (§8). Recommend: never a level.

**L5. Mission decisions as counts.** [fits]
- Source: debrief good calls, shelter on time, objectives met, readbacks good (`mission/gameplay.py`, `readback.py`).
  This is `BRAIN.md` §8's open item.
- Reliability: the sim is exact; a readback by voice depends on the ear.
- Kid sees: "Good calls: 12."
- Grown-up sees: per mission type.
- Keep: per profile.
- Line: fine as counts. Readbacks were designed to "never score" (`readback.py:15`), so counting them changes that
  design. Show them to the kid only.

### 3.2 Self-regulation and turn-taking

These are the ones schools will ask for, and they are where the line sits. Each signal can be reported two ways:
- as what the app did, which is [fits];
- or as a trait of the child, which is [CROSSES].

**R1. Turn-taking with CAPCOM (barge-in).**
- Source: the client's barge decisions (`barge.js`, `bargelog.js` reasons `speech` / `command` / `ptt`). Today these
  are in page memory only.
- Reliability: the client's decision is decent. The ear's own BARGE_IN fires on 64 % of our lines with nobody talking
  (`ARC_ABI2.md` §8), so never count the ear's flag.
- As the app's action [fits]: "CAPCOM stopped to let you talk: 9 times." This teaches that the kid always wins the
  floor, which is the design (`SESSION_CONTRACT.md` §3).
- As a trait [CROSSES]: "Interrupts often." Don't.
- Keep: a weekly count, 12 weeks.

**R2. Talking to the app vs the room.**
- Source: router reasons `not_directed`, `crew_talk`, `chatter`, `room_yes_no`, `callsign_other` (already in the turn
  log).
- Reliability: weak. dd AUC is 0.70 and was measured on synthetic room talk, and 78 % of room talk passes the 0.5
  gate. It also cannot tell this cadet's side talk from a classmate's.
- Room level [fits]: "The room was busy for 12 of 40 minutes; the app switched to hold-to-talk twice." That is the
  room state, already shown as calm / busy / loud counts.
- Per-cadet "off-task talk" rate [CROSSES]: behaviour monitoring of a child. Under the EU AI Act, AI that monitors
  students' behaviour in education is high-risk (Annex III 3). Recommend: never per cadet.

**R3. Pace and wait time.** [fits as today]
- Source: `learn/habits.py` `end_silence_s`.
- Already shown as the app's action ("The outpost waits for you"). Keep it that way. "Slow responder" crosses.

**R4. Persistence after mistakes.** [grey]
- Source: `brain_store`. Steps passed after at least one miss and not shown (`helped`), against steps where the
  cadet asked to be shown or skipped.
- Reliability: exact for taps and typing; voice misses carry the L1 caveat.
- Kid sees, as praise [fits]: "You kept going on 6 tricky steps." Effort praise, no score. Don't make it a streak (an
  AADC nudge).
- Grown-up sees: the same count.
- A "gives up" or "grit" label [CROSSES]. The count is fine; the label is the line.

**R5. Help-seeking.** [fits]
- Source: the `help` intent, "show me", and the hint rungs (`brain_store` `helped`, `shown`, `pause`).
- Grown-up sees: "Asked for help 5 times; the app offered 3 early hints after a long pause." Asking for help is a
  skill. Report it as something good.

**R6. Hesitation itself.** [CROSSES; recommend never]
- Source: `hesitation.hesitant` (fillers, long pauses, low uconf).
- Today it is a one-turn flag, never stored. Storing it makes a confidence or anxiety proxy. The disfluency signal
  mixes the ear's errors with the child's speech, and on a child who stammers it would point at a disability (special
  category data under GDPR Art 9). Keep it never stored. Only the app's early-hint count (`pause`) stays.

**R7. Emotion.** [CROSSES; recommend never]
- There is no emotion head, and the dead plumbing should go (§2 item 6).
- The EU AI Act (Art 5(1)(f)) prohibits inferring emotions of people in education institutions. It has applied since
  February 2025. If Outpost Luna is ever used in an EU school, any emotion feature is banned there, not just
  discouraged.

### 3.3 Safety

**S1. Filtered-word counts (profanity, toxicity, inappropriate).** [grey]
- Source: the `mask` decision (`safety.classify`).
- Store one enum per masked turn: `kind` = `profanity | toxicity | inappropriate`, from the tag class; a word-list
  hit is `profanity`. Store a `via` band:
  - **typed** or **PTT** (Space held: the cadet meant it);
  - **open mic, directed** (dd ≥ dd_strong);
  - **open mic, room** (everything else).
- Store nothing else: never the word, never the turn text (already `<private>`), never a time finer than the day.
- Reliability:
  - the word list is exact on the words the ear wrote, but the ear mishears ("shirt" vs the other word);
  - the kids-domain tagger tagged 36 of 1,500 round-11 texts, all real, and recall on short swears was near zero
    before 0.5;
  - **the owner's own case was room talk** ("shit shit oh" from the room, dd 0.91, `ARC_FEEDBACK.md`).

  So an open-mic count says "heard near the app", not "said by the cadet". Only typed and PTT can be put on a
  cadet.
- Kid sees: nothing per count. The "How the outpost thinks" card gains one line: "If a rude word is heard, the outpost
  hides it. Grown-ups can see how many times, never the word." AADC standard 11: when a parent can monitor, the
  child must be told.
- Grown-up sees: per week, "Filtered words: 3 typed, 1 said to the app, 5 heard in the room." A trend arrow over 4
  weeks, never a comparison between cadets.
- Keep: weekly buckets, 12 weeks, then gone. Reset and "Delete what's saved" clear them.
- Where: a new small aggregate next to the turn log, so it works when the turn log is off. Writing it does not need
  the log on. The counts are safety, not training data.

**S2. Privacy events.** [fits]
- Source: the Director's privacy guard (`NAME_GIVEN`, `hard_pii`), counted separately from S1.
- Leave the tagger's `pii` out of this count. It still keeps text out of the log, but its false-positive history makes
  it a poor statistic.
- Kid sees: "The outpost kept your name private 2 times." Good AI-literacy feedback.
- Grown-up sees: the same.
- Keep: as S1.

**S3. Care flags.** [grey; this is a duty-of-care decision]
- Source: `crisis.self_harm`, `child.grooming_cue`, tag or phrase.
- Reliability: precision 1.00, recall about 0.5 on indirect phrasings (Arc team). The phrase lists are narrow on
  purpose. The app can't diagnose, and a missed cue must never read as "all clear".
- Today: in memory, lost on quit, so a grown-up rarely sees it.
- Options (decision D4):
  - **a.** Keep it in memory, as now.
  - **b.** Persist `{kind, day}` per cadet until a grown-up acknowledges it on the Progress page, and for 30 days at
    most. Show a badge on the grown-ups' entry ("1 safety note") behind the 3-second hold.
  - **c.** b, plus an on-screen card for a grown-up in the room at the moment it happens.
- Never the words, in any option. A grown-up who needs more talks with the child (`BRAIN.md` §2).
- Line: a self-harm cue tied to a child is plausibly health data (GDPR Art 9). That argues for b with a short expiry,
  not for a history. Persisting it is defensible as duty of care and safeguarding, but it needs to be in the privacy
  notice, and schools will want their safeguarding lead, not the app, to own the follow-up.

**S4. Trends over time.** [grey]
- Weekly counts for S1-S3 over 12 weeks. Any "rising" wording is a judgement, so show the numbers and let the grown-up
  read them.
- No automatic alert on a filtered-word trend. Care flags (S3) are the only things that alert.

### 3.4 Engagement

**E1. Days, minutes, sessions.** [fits] Already kept (`days`, `secs`). "Days in a row" already carries no penalty.
Keep it so: no "don't break your streak" lines (AADC nudge techniques).

**E2. What the cadet chooses.** [grey]
- Source: router outcomes. Lessons vs missions vs library questions vs explore, as counts per week.
- Grown-up sees: "Asked 14 questions in the Library."
- Counts of activity fit. A "curiosity score", or ranking topics by interest, is profiling (see L3).

**E3. Voice vs typing.** [fits] Already shown per device. It becomes per cadet with §5.

## 4. Profanity and safety statistics: the concrete design

One new store. It is safety, not learning, and it works whether the turn log is on or off.

- **File:** `<cache_dir>/safety/counts.json`, mode 0600, written atomically like `learn/store.py`.
- **Shape:** `{v:1, weeks: {"2026-W47": {"<profile>": {mask: {profanity: {typed, ptt, directed, room}, toxicity: {...},
  inappropriate: {...}}, privacy: n, care: n}}}}`.
- **What it may hold:** whole numbers, ISO weeks, profile ids, and fixed enums. A `clean()` on every write, the way
  `brain_store.clean` and `learn/store.py ALLOWED` work, so a bug cannot widen it.
- **Written from:** `session._turn` right after `safety.classify` (`session.py:727`), with the profile from
  `self.prefs["profile"]`.
- **Read by:** `GET /api/brain/summary` (with the local token), per profile.
- **Not written:** the word, the text, the tag p, the screen, the time of day.
- **Erased by:** Reset, "Delete what's saved", deleting a cadet, and turning 12 weeks old.
- **Tests:** the same "no words" test `brain.py` has (`test_summary_has_no_words_names_or_call_signs`).

Bugs to fix in the same change: §2 items 1-4.

## 5. Per device vs per cadet

Today:
- **Per cadet:** lesson and speech counts (`brain_store`, localStorage per profile), on-device learning
  (`profile-<id>.json`), call-sign mission counts.
- **Per computer:** the turn log, talk counts, room counts, `guarded`, care flags (per app run, at that).

The gap is small. The client already sends `profile` on every connect (`prefs.js:134`), and the session keeps it
(`session.py:153-155`). Add `profile` to the turn-log record and to `Session.flags`, and `brain.py` can filter by it.

What it can't fix: the profile is whoever is selected, not whoever spoke. On a shared laptop in a classroom, open-mic
turns from classmates land on the active cadet. Hence the S1 `via` bands, and the rule that only typed and PTT turns
are put on a cadet.

True per-speaker attribution needs speaker recognition. Arc's plan has a session-local enrolled `speaker.id`
(`ARC_MULTISTREAM_PLAN.md` §3, "2-4 kids on one device"). A voiceprint is a biometric identifier:
- COPPA's 2025 rule lists biometric identifiers, including voiceprints, as personal information;
- under GDPR Art 9 it is special-category data when used to identify;
- Illinois BIPA and Texas CUBI require written consent.

[CROSSES] by a wide margin, even session-only. Recommend the non-biometric path in §6 (crew rotation) instead.

## 6. Classroom and teacher regulation

### What exists today

There is no multi-voice classroom mode in the sense of telling voices apart. Speaker is always None. What
`feat/classroom-teacher` (#165) shipped:
- **Room state** (`room.js`, `docs/HANDSFREE.md`): automatic calm / busy / loud. Busy makes the filter stricter, then
  asks for hold-to-talk; loud offers typing. It is never a setting, and only ever stricter than the cadet's choice.
- **Crew-talk gate** (`turn_router.py:1039-1042`): on predict and choice steps, a spoken pick counts only at
  dd ≥ dd_strong. Two kids debating "yes / no" never pick for them. The bar offers the kid's exact answer back as a
  one-tap chip.
- **`callsign_other`:** on the call-sign screen, a name that isn't for us is ignored.
- **Class lessons:** teacher-authored packs, stored locally and validated (`backend/app/academy/class_routes.py`,
  `classpacks.py`, `frontend/src/class_editor.js`).
- **Cadet profiles:** up to 6 per computer, switched in Settings, with a page reload (`prefs.js:173-201`).
- **Grown-ups' page:** behind a 3-second hold. One printable card per cadet. Talk, safety and room counts are this
  computer's, shown on the active cadet's card.
- **School network setting** (`docs/SCHOOL_IT.md`).

### What teacher regulation would need

In order of value against risk:

1. **Crew rotation (non-biometric attribution).** [fits]
   - A class mode where the cadets on one computer are named on screen, and the active one switches with a tap or a
     controller button, with no reload. CAPCOM says "Nova, your turn."
   - Each turn and count lands on the cadet whose turn it is. PTT per cadet makes it exact.
   - This gives per-cadet counts in a classroom without a voiceprint, and it teaches turn-taking, which is the
     regulation goal.
2. **A teacher PIN** on top of the 3-second hold. The hold stops a 7-year-old, not a 12-year-old. Safety counts and
   care flags need a real gate in a school.
3. **A class summary on one computer:** all profiles on this computer, one printable page, counts only. No ranking,
   alphabetical by call sign.
4. **A class roll-up across computers** without us. Each computer exports a signed counts-only file (no text, no
   words, profile ids and call signs only), and the teacher imports them on the teacher's computer. Nothing reaches
   Whissle, which keeps Whissle out of FERPA's "school official" role and out of the Colorado contract-provider duties
   (§8). `BRAIN.md` §8 lists this as out of scope today.
5. **A live room indicator for the teacher:** "Room: busy, hold-to-talk on" on the teacher's view. It is the existing
   room state, shown, and it is about the room, not a child.
6. **Session limits and quiet hours:** a teacher-set end time, after which CAPCOM wraps up. Regulation of use, no data.
7. **A care-flag workflow** (S3 option b or c), routed to the adult in the room. The school's safeguarding policy
   decides the rest.

Not recommended: per-cadet "off-task" or "disruption" counts (R2), any emotion or engagement-from-face signal, and
cross-cadet rankings.

## 7. Retention summary (proposed)

- Lesson, concept and speech counts: while the profile exists. Erased by Reset progress.
- Practice days: 60 most recent (as now).
- Safety counts (S1, S2): weekly, 12 weeks.
- Care flags (S3): until acknowledged, 30 days at most.
- Turn log: 5 MB rolling (as now). Optionally an age cap (90 days) on top of the size cap.
- On-device learning: as now (45-day half-life on aliases, Settings reset).
- Never kept: hesitation, emotion, audio outside Playtest, words in any brain store, times finer than a day.

## 8. The regulatory map

These are design readings of what each regime is aimed at, not legal opinions.

- **COPPA (US, under 13), as amended in 2025** (compliance from April 2026).
  - What it covers: personal information an operator collects from a child. Data that stays on the device and never
    reaches Whissle is mostly outside "collection".
  - What changes that: the developer turn-log import (`make director-import`), any roll-up that reaches us, or
    Playtest audio a family hands over. Those are collection: verifiable parental consent, a written retention
    policy, and deletion.
  - The amended rule lists biometric identifiers, including voiceprints, as personal information (§5).
  - The FTC's audio-file policy (voice used only as a replacement for typed text, then deleted) fits the live ear.
    It does not fit stored clips.
- **FERPA (US schools).**
  - Records a school keeps about a student are education records. A printed Progress page a teacher files becomes
    one; that is the school's business.
  - If Whissle never receives the data, Whissle is not a "school official" holding records. Keep roll-ups local
    (§6 item 4).
- **UK Age Appropriate Design Code.** The 15 standards. The ones that bite here:
  - best interests;
  - DPIA (a DPIA is expected before adding S1-S3 or crew rotation);
  - high privacy by default (the turn log being on by default, §2 item 7);
  - data minimisation;
  - detrimental use;
  - profiling off by default unless there is a compelling reason, with safeguards (L3, R2, R6, R7 cross this);
  - nudge techniques (streaks);
  - parental controls: tell the child when they are monitored (S1's "How the outpost thinks" line).
- **GDPR-K (EU).**
  - Art 8: consent age 13-16 by member state, for services offered directly to a child.
  - Recital 38 and Art 22: children merit specific protection, especially against profiling.
  - Art 9: health data (care flags, a stammer from disfluency) and biometric data for identification (speaker ID) are
    special categories.
  - Data that never leaves the device still counts as processing if Whissle determines it, so a DPIA is the safe
    reading.
- **EU AI Act.**
  - Art 5(1)(f) prohibits emotion recognition in education institutions (R7).
  - Annex III point 3 makes these high-risk:
    - AI used to evaluate learning outcomes, or to steer the learning process, in education;
    - AI used to assess the level of education a person will receive;
    - AI used to monitor and detect prohibited student behaviour during tests.

    That is the line for L4's reading level, R2 per cadet, and any "mastery" figure a school uses to grade. Keep the
    brain a practice record the kid and family own, not an assessment the school acts on.
- **Colorado.**
  - The Student Data Transparency and Security Act (C.R.S. 22-16-101 et seq.) governs school service contract
    providers and on-demand providers. It bans targeted ads and selling. It allows student profiles only for school
    purposes. It requires a public list of the data elements collected, and deletion.
  - The Colorado Privacy Act's minors' amendments (SB 24-041, in force October 2025) require a data protection
    assessment and consent before profiling a known minor for decisions with significant effects. They also bar
    design features that significantly increase use.
  - Again, data that never reaches Whissle keeps most of this off. A published data-element list
    (`docs/BRAIN.md` §1 is close to one) is cheap and good for the Colorado archaeology pilot.

The pattern across all of them: counts of outcomes, kept on the device, deletable, explained to the child, is the safe
zone. Traits, emotions, behaviour scores, voiceprints, and anything that reaches Whissle are where consent,
assessments and bans begin.

## 9. Decisions for Karan

1. **D1. Count profanity at all?** Recommend yes, as S1: weekly counts by kind and `via` band, never words, 12 weeks,
   the kid told in "How the outpost thinks". Open-mic counts labelled "heard near the app".
2. **D2. Turn log on by default?** It keeps redacted kid text, on by default since 0.4.3. That conflicts with AADC
   "high privacy by default" and with `docs/BRAIN.md` saying "opt-in". Options: default off for new installs; or keep
   it on but make the safety and brain counts independent of it (§4), so turning it off costs the grown-ups nothing.
3. **D3. Per-cadet tagging:** add `profile` to the turn log and flags (cheap, [fits]). And **crew rotation** for
   classrooms (§6 item 1) instead of speaker ID. Recommend both, and **no voiceprints**.
4. **D4. Care flags:** in memory (today), or persist `{kind, day}` per cadet until acknowledged, 30 days at most
   (option b, recommended), or b plus an in-room card (c).
5. **D5. Concept mastery and spaced review (L1, L2):** recommend yes. It is the biggest learning gain and fits the
   policy.
6. **D6. Things that cross the policy:**
   - L3 own-speech vocabulary (or its glossary-only variant, which fits);
   - L4 reading level;
   - R2 per-cadet room talk;
   - R4 "persistence" as a label;
   - R6 stored hesitation;
   - R7 emotion.

   Recommend: none of them, and delete the dead emotion plumbing so "no emotion" is provable.
7. **D7. Teacher features:** a PIN, a class summary per computer, and a local file roll-up across computers (nothing
   to Whissle). Recommend PIN + class summary first. The roll-up comes once a pilot school asks.
8. **D8. EU schools:** if they are a target, decide now that the brain is never used for grading (Annex III). Say so
   on the printable page ("a practice record, not an assessment").
9. **D9. Fix now regardless:**
   - the signal day-window bug;
   - profanity and privacy split in the summary;
   - a local-token check on `/api/safety/flags`;
   - the `docs/BRAIN.md` turn-log default wording.
10. **D10. A DPIA:** write a short one (AADC standard 2, Colorado SB 24-041) before shipping S1-S3 or crew rotation.
    `docs/BRAIN.md` §2 and this document are most of its inputs.
