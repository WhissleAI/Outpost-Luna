# Data protection impact assessment: safety counts, care flags and crew rotation (2026-11-20)

**Not legal advice.** This is the product team's own assessment, written so a lawyer and a school's data protection
or safeguarding lead can check it quickly. It reads each regime for what it is aimed at; it does not say what a court
or regulator would decide. A lawyer signs off before release to a school or in the EU or UK.

- **Covers:** the weekly safety and talk counts (`backend/app/brain_counts.py`), care flags kept until a grown-up
  acknowledges them (`backend/app/care_flags.py`), the profile id on turn-log lines, and crew rotation
  (`frontend/src/crew.js`). Decisions D1-D4 of `docs/BRAIN_SIGNALS_AUDIT.md`, approved by the owner; this is D10.
- **Design record:** `docs/BRAIN.md` §2, §6, §6a, §6b, §9.
- **Why a DPIA now:** UK AADC standard 2 expects one before processing children's data in a new way; the Colorado
  Privacy Act's minors' amendments (SB 24-041) require a data protection assessment for processing of a known
  minor's data that presents a heightened risk; GDPR Art 35 points to one for systematic monitoring of vulnerable
  people. Persisting care flags and putting counts on a named cadet is that kind of change.

## 1. What is processed, and where

| Data | Where | Who it is about | Kept | Erased by |
|---|---|---|---|---|
| Weekly counts: turns, voice/typed, answered/let pass, room label, days with a turn | `<cache_dir>/brain/counts.json`, this computer, mode 0600 | The cadet profile playing, or on turn in crew rotation | 12 weeks | Reset (both levels), "Clear this cadet's safety counts", age |
| Safety counts by kind (profanity, other filtered, privacy guard, care) and channel (typed, push-to-talk, said to the app, heard in the room) | same file | same | 12 weeks | same |
| Care flags: kind (self_harm or grooming), day, profile id, how many times that day | `<cache_dir>/brain/care.json`, mode 0600 | same | until a grown-up marks it seen; 30 days at most | Mark as seen, Clear, Reset, age |
| Profile id (`p1`..`p6`) on turn-log lines | the turn log, this computer | same | the log's 5 MB rolling cap | "Delete what's saved", Reset |
| Crew rotation state: on/off, the id on turn, the old listening choice | browser `localStorage["outpost-crew"]` | none (an id) | until turned off | Start over |

**Never processed:** the words of a filtered, private or care turn, a tag's confidence, the screen, a time finer than
the day, a call sign or real name in any of these stores, audio, any voiceprint or speaker embedding, any emotion or
trait (`docs/BRAIN.md` §6a; `backend/tests/test_no_emotion.py`).

**Nothing leaves the computer.** There are no accounts and no upload. Whissle receives none of it unless a family or
school hands over a file (today only the developer turn-log import, `make director-import`, which is separate and
consented).

## 2. Purpose and necessity

- **Safety counts (D1):** let a parent or teacher see that the filter and the privacy guard work, and notice a pattern,
  without reading what a child said. Counts by channel exist so the grown-up can tell a cadet's own typed or
  push-to-talk turns from talk merely heard near the app.
- **Care flags (D4):** duty of care. Before D4 a self-harm or grooming cue raised a flag that vanished when the app
  quit, so a grown-up rarely saw it. Persisting kind and day only, until acknowledged, is the smallest record that
  lets a grown-up follow up.
- **Profile id and crew rotation (D3):** put the counts on the right cadet when several share one computer, without
  biometrics. A tap decides whose turn it is.
- **Independent of the turn log (D2):** the turn log (redacted text, on by default) exists to improve the voice guide.
  The grown-ups' counts no longer need it, so a family can turn the log off and keep the safety view.
- **Less would not do:** a single "turns kept private" number (before D9) hid profanity inside privacy; in-memory care
  flags failed their purpose; computer-wide counts mislabel cadets in a class.

## 3. Risks and how the design meets them

| Risk | Likelihood / severity | Mitigation in the design |
|---|---|---|
| A count is read as a judgement of the child ("swears a lot") | Medium / medium | Counts by channel, open-mic labelled "heard near the app", only typed and push-to-talk put on a cadet; no trend wording, no alerts on filtered words, no ranking between cadets; nothing shown to other cadets |
| A classmate's words land on the cadet playing | High on a shared laptop / medium | The channel split; crew rotation makes the turn explicit; while crew rotation is on, listening is hold-to-talk, so open-mic counts do not arise |
| Care flag misses a real cue (false negative read as "all clear") | Medium (recall about 0.5 on indirect phrasing) / high | The page says "no note does not mean all clear"; the app never claims to screen a child; the school's safeguarding policy owns follow-up |
| Care flag is wrong (false positive) | Low (precision about 1.0 on tested phrasing) / medium | Kind and day only, never the words; one gentle line to the child ("Let's take a break. Talk to a grown-up you trust."); 30-day expiry |
| A care flag tied to a child is health data (GDPR Art 9) | Certain if held / high | No history: kept only until a grown-up sees it, 30 days at most; no text; on the device only |
| A child sees another child's data, or the safety notes | Low / medium | Grown-up data sits behind the 3-second hold (a teacher PIN is the next step, D7); the gate shows only a count; the kid page shows no counts |
| Local file read by another user or app | Low / medium | Per-user app data folder, mode 0600, loopback-only API with the per-launch token |
| Profiling (AADC standard 12) or behaviour monitoring | Low as designed / high | Counts of outcomes and of what the app did; no traits, no emotion, no per-cadet off-task rate, no stored hesitation (`docs/BRAIN.md` §6a) |
| Speaker identification creep | Low / high | Crew rotation is a tap; no voiceprints, enrolled or session-only; a design rule in `docs/BRAIN.md` §9.4 |
| Data kept too long | Low / medium | 12 weeks for counts, 30 days for flags, enforced on every read and write by `clean()` |

Residual risk: **low**, provided a school uses the grown-up gate (and, once shipped, the teacher PIN) and its own
safeguarding process.

## 4. Regime by regime

- **COPPA (US, under 13; amended rule, compliance from April 2026).** COPPA governs personal information an operator
  collects from a child. These stores stay on the family's or school's computer and Whissle never receives them, so in
  our reading this is not collection by Whissle. The amended rule's biometric identifiers (voiceprints) are not
  processed: crew rotation avoids them by design. If a future feature sends any of this to Whissle, verifiable
  parental consent (or school authorization), a written retention policy and deletion apply first.
- **FERPA (US schools).** A count a teacher prints and files can become an education record held by the school. That
  is the school's record. Whissle holds none, so it is not acting as a "school official" for these data. The
  cross-computer roll-up stays a local file exchange (D7 follow-up) to keep it that way.
- **UK Age Appropriate Design Code.** Best interests (a duty-of-care flag, no punitive view for the child);
  DPIA (this document); high privacy by default (the counts hold no words and work with the turn log off); data
  minimisation (counts, kinds and days only); detrimental use (no streaks, no nudges, no ranking); profiling off
  (§3, and `docs/BRAIN.md` §6a); parental controls (standard 11: the child is told grown-ups can see how many filtered
  words, never the word: the "How the outpost thinks" card).
- **GDPR-K (EU).** Art 8 consent applies to services offered directly to a child; Art 9 applies to the care flag
  (health) and would apply to a voiceprint (not processed). Even data that never leaves the device is processing that
  Whissle's design determines, so the safe reading treats Whissle as controller for the design and the family or
  school as controller of the device. Art 35: this DPIA. Recital 38: no profiling, no marketing use.
- **EU AI Act.** Art 5(1)(f) bans emotion recognition in education institutions: there is none (D6, test-guarded).
  Annex III point 3 makes high-risk the AI used to evaluate learning outcomes, steer learning, assess the level of
  education, or monitor prohibited behaviour during tests. The safety counts are not used to evaluate or steer a
  child; the brain is a practice record, never for grading (D8, on the Progress sheet). The safety tagger is a content
  filter on the app's own input, not behaviour monitoring of a student.
- **Colorado.** The Student Data Transparency and Security Act (C.R.S. 22-16-101 et seq.) applies to school service
  contract and on-demand providers: no targeted ads, no sale, student profiles only for school purposes, a public list
  of data elements, deletion. §1 above is that list for these stores, and every element has a delete path. The
  Colorado Privacy Act's minors' amendments (SB 24-041, in force October 2025) require this kind of assessment and
  consent before profiling a known minor for decisions with significant effects (none here: no decisions are made
  from the counts) and bar design features that significantly increase use (none: no streak pressure, no rewards
  for time on the app).

## 5. Decisions and actions

- **Ship** D1-D4 as designed: on the device only, counts and kinds, 12 weeks / 30 days, behind the grown-up gate.
- **Privacy notice:** add the §1 table to the app's privacy notice and `docs/SCHOOL_IT.md` before a school pilot.
- **Teacher PIN (D7):** the 3-second hold stops a young child, not an older one; a school should set a PIN.
- **Safeguarding:** a school's designated safeguarding lead, not the app, owns the follow-up of a care flag. Say so in
  the school pack.
- **Review:** repeat this assessment before any feature that sends brain data off the computer (a roll-up that reaches
  Whissle, cloud sync), adds a new safety kind, or identifies speakers.

## Addendum (2026-11-22): adult testers' "Help improve Outpost Luna"

An adult's opt-in, not a child's: Settings → For grown-ups (behind the hold / teacher PIN) → Help improve Outpost Luna
(`backend/app/adult_collect.py`, `docs/ADULT_SESSIONS.md`). Off by default; turned on only after an "I'm an adult, and
I agree" consent screen; tied to the profile that turned it on, so a child's profile on the same computer is never
collected (`backend/tests/test_adult_collect.py`). It keeps the same redacted turn-log text plus what the app said
(call signs redacted) and, only with its own switch, audio clips. Nothing is sent; the export holds only the adult's
collected turns, redacted again, and the adult chooses whether to hand it over. Risk to children: a child using the
adult's profile while it is on; mitigated by the top-bar "Improving" tag, the separate profile the protocol asks for,
and the gate. To check with a lawyer: the consent wording, and retention of handed-over files.

