# Speech learning: read, vocab, summary

Status: **v1 shipped** (branch `feat/speech-learning-steps`). Three course-agnostic step types and an offline feedback
engine, plus one sample lesson per type in the Moon course. The optional local-LLM rewrite is a **documented spike, off**
(§4).

Where the idea came from: a teammate's list, via the owner. "Read a short article and answer questions; vocabulary
quizzes; free-form response (a spoken summary of a video or an article you watched, with feedback). Educational uses
for speech technology are the most rewarding."

House rules this keeps: offline and on-device; School network mode (no new hosts, nothing leaves the computer);
COPPA / school privacy (counts only, never what a cadet said); no model or vendor names in product copy; the course's
reading level (owner decision 2, `docs/COURSES.md` §7); voice, typing, keys and controller all work.

**Contents**
- §1 [What learners and teachers get](#1-what-learners-and-teachers-get)
- §2 [The three step types](#2-the-three-step-types)
- §3 [Feedback engine v1 (no LLM)](#3-feedback-engine-v1-no-llm)
- §4 [The LLM option: evaluation and decision](#4-the-llm-option-evaluation-and-decision)
- §5 [Progress, the Brain and privacy](#5-progress-the-brain-and-privacy)
- §6 [Authoring a step](#6-authoring-a-step)
- §7 [Files and tests](#7-files-and-tests)
- §8 [What's next](#8-whats-next)

---

## 1. What learners and teachers get

**Learners**
- **Read like a scientist** (Moon, `reading`). A short passage about ice in the Moon's dark craters, built only from
  facts already checked in `learning/concepts.json`. Then three questions: one to pick, one to answer in a word or two,
  one to find the sentence. **Listen** has the app's voice read the passage. **Read it aloud** lets the cadet read it
  themselves: the ear counts the words read right, the pace (words a minute), up to three words to try again, and
  rereads. It never labels the reader ("You read 64 of 80 words. That's about 92 words a minute. Words to try again:
  stage.").
- **Word lab** (Moon, `wordlab`). Space words from their meaning: say the word or tap it. Sound-alike traps
  (crater / *creator*, lava / *larva*, terminator / *exterminator*) are options too, and saying one never passes: CAPCOM
  says what that word means ("Close! A larva is a baby insect. Try again."). One item asks the cadet to use a word in
  a sentence (spoken or typed), or to pick the sentence that uses it right. Words come back by spaced repetition.
- **Tell it back** (Moon, `retell`). Watch the Apollo 15 hammer-and-feather video, then tell what happened in your own
  words, by voice (the app listens until you stop, or say "that's it") or by typing. The feedback is 2-3 short
  sentences: the key points you told, and one more key point. It is never a grade and never "wrong". If nothing on topic
  comes, CAPCOM asks one key point's question ("What happened when they landed?"), and after three tries shows a model
  summary and the lesson goes on.

**Teachers and parents**
- Settings → For grown-ups → Progress gains a **Reading and speaking** block per cadet, per course: passages read,
  questions answered, read-aloud sessions and words read, words practised / learned / to review, summaries told and key
  points. Counts only.
- The steps are data (§6). A course (Archaeology, grades 9-12) gets the same steps at its own reading level: the feedback
  budget follows the course (`feedback.LEVELS`).

## 2. The three step types

All three build up over turns like Field School (`got` comes back with the next answer), so one question or word is
graded at a time and each gets its own hint ladder. Room talk and fillers are never a try (`speech.plausible`). A rude
turn is never graded (`safety.has_profanity`, before grading, for the summary's long text too).

| Type | The cadet does | Voice | Typing | Keys / controller | Graded by |
|---|---|---|---|---|---|
| `read` | reads a passage, answers 2-4 questions | answers, option keys ("B"), "sentence seven", or reads part of the sentence back | the card's box or the voice bar | lettered option buttons; the sentences become numbered buttons for a find question | `speech.grade_read`: option match; keyword groups; sentence by tap, number or overlap |
| `vocab` | says or picks the word for a meaning; uses a word in a sentence | the word (the ear's spelling is fuzzy-matched, but a trap must never sound closer) | the box | numbered word / sentence buttons | `speech.grade_vocab`: `vocab.said_score` against the term and every trap and option |
| `summary` | watches a video or reads an article, then tells it back | collected until a quiet gap (4.5 s, 6+ words), Done, or "that's it" | the box | Watch, Done, Start over, the box | `speech.grade_summary` + the embedder and the tagger (§3) |

Read it aloud (`POST /api/academy/fluency`): the passage and the heard words are aligned (semi-global alignment with
fuzzy word matches, free gaps at the start and end, `speech.align`). Words correct = passage words matched in the part
read; skipped = unmatched content words inside that part; rereads = an extra word that repeats one just read. The pace
uses the ear's own speaking time (`speech_s` on its final words, relayed by `voice.js` as a numbers-only
`outpost:ear-final` event), else the clock. Under 5 seconds, or fewer than 3 matched words, gives no pace and asks to
try again. The words are not stored or returned.

## 3. Feedback engine v1 (no LLM)

**Coverage.** A summary step's rubric is a list of key points, each with a label (a clause the template can say), a
question (`ask`), accepted phrasings (`say`) and optional names (`terms`). A point counts as told when any of:
1. **Words**: a phrasing's content words are in the summary (stemmed, fuzzy for ear spellings: "droped a hamer" counts).
2. **Meaning**: the local MiniLM embedder (`models_client.embed`) puts a span of the summary within cosine 0.62 of a
   phrasing (`routes.SUMMARY_SIM`). This catches "nothing up there slowed it" for "no air".
3. **Mentions**: Arc Tagger (kids domain) marks one of the point's `terms` as a mention ("Apollo 15", "David Scott").

Both model paths fail open: with the model server off, the words alone decide. Points add up over turns.

**Template.** `feedback.template`: an opener ("Nice summary."), "You said A and B." (or one sentence per point when two
long points would break the budget), and "One more key point: C." (or "That covers every key point."). The words come
only from the rubric's labels, so it can't state a fact the lesson doesn't hold. Budgets per course: Moon 14 words a
sentence and 36 in all; Archaeology 20 and 50.

**Guard** (`feedback.guard`; the template passes its own guard, tested): 2-3 sentences within the budgets; no grade
words ("wrong", "score", "grade", "fail"...), no model words ("AI", "model", "assistant"); no markup or links; the
profanity list and Arc Tagger's kids safety tags (mask or care) reject; every number must be in the rubric or the
cadet's words; at most one content word from outside the rubric, the cadet's words and a small list of warm words;
the missing point must be named; a covered point must be named; an untold point must not be praised as told.

## 4. The LLM option: evaluation and decision

The idea: a small local instruct model rewrites the rubric result (covered labels, one missing label, the cadet's own
words) into the same 2-3 sentence shape, a little warmer and closer to what the cadet said. It may only rewrite: no
chat, no new facts. Its output goes through `feedback.guard` (above, including Arc Tagger safety) and falls back to the
template on any failure (off, slow, down, unsafe, off-rubric). The server must be on loopback
(`feedback.llm_url` refuses any other host), so School network mode is untouched and nothing leaves the computer.

LLM_EVAL_RESULTS

## 5. Progress, the Brain and privacy

- Counts live in the cadet Brain's store (`brain_store.js`, `"outpost-brain"`, a per-cadet progress key: it moves with
  the cadet's profile, "Start over" keeps it, "Erase progress too" erases it) as its `speech` section:
  `{c: {<course>: {read, questions, aloud, aloud_words, summaries, points, words: {<word>: {box, due, n}}}}}`.
  `brain_store.clean()` keeps the section through `speech_store.parse()`, which drops anything that isn't a count, a
  YYYY-MM-DD date or a lower-case glossary word.
- **Spaced repetition**: a Leitner box per word (0-4; due after 0, 1, 3, 7, 14 days). Right moves up a box; a miss or
  a trap puts it back in box 1; "learned" is box 3 or more. The vocab step asks due words first, then new ones, then
  the rest (`speech_store.planFor`); the server keeps only valid item ids from the client's plan. Item ids are the word
  in lower case (checked), so the client never needs the answers to plan.
- The course of a lesson is its id prefix (`archaeology:dating`); bare ids are the Moon.
- Never stored: what the cadet said or typed, the passage they read aloud, the feedback lines. The fluency endpoint
  returns counts only. The client view of a step has no answers (no correct option, no terms of word items, no traps,
  no rubric phrasings).

## 6. Authoring a step

```json
{"type": "read", "passage": {"title": "...", "text": "2-12 sentences", "source": {"title": "...", "url": "https://..."}},
 "questions": [
   {"id": "q1", "kind": "choice", "prompt": "...", "options": [{"id": "a", "label": "...", "say": ["..."]}], "answer": "a", "hint": "...", "yes": "..."},
   {"id": "q2", "kind": "say", "prompt": "...", "any": [["word", "phrase"]], "answer_line": "...", "hint": "..."},
   {"id": "q3", "kind": "find", "prompt": "Find the sentence that ...", "answer": 6, "hint": "..."}]}

{"type": "vocab", "ask": 4, "items": [
   {"id": "lava", "term": "lava", "kind": "word", "distractors": ["regolith"], "traps": [{"word": "larva", "note": "A larva is a baby insect."}]},
   {"id": "regolith", "term": "regolith", "kind": "sentence", "sentences": [{"label": "...", "ok": true}, {"label": "...", "ok": false}]}]}

{"type": "summary", "source": {"kind": "video", "media": "<catalog id>"} | {"kind": "article", "passage": {...}},
 "need": 2, "example": "a model summary, 30 words or fewer",
 "points": [{"id": "air", "label": "the Moon has no air to slow the feather", "ask": "Why didn't the feather float down slowly?",
             "say": ["no air", "nothing to slow it"], "terms": []}]}
```

`content.check()` runs `speech.check_step` on every step: passage sources, 2-4 questions, prompt / hint budgets, answers
among options, sentence indexes, vocab ids, define lines and trap notes, summary points (labels and asks 10 words or
fewer), `need`, the example, the video id. Word items without `define` use the glossary meaning.

## 7. Files and tests

| Part | File |
|---|---|
| Graders, fluency, client view, checks | `backend/app/academy/speech.py` |
| Feedback template, guard, optional rewrite | `backend/app/academy/feedback.py` |
| Attempt / hint / fluency routes | `backend/app/academy/routes.py` (`_speech_attempt`, `speech_help`, `/api/academy/fluency`) |
| Lessons and the passage | `backend/data/academy/course.json` (`reading`, `wordlab`, `retell`), `backend/data/learning/reading.json` |
| Renderers | `frontend/src/academy/speech_steps.js` (+ `school.css`) |
| Counts and spaced repetition | `frontend/src/academy/speech_store.js`, `frontend/src/brain_store.js` (`speech` section) |
| Progress | `frontend/src/progress.js` (`speechHtml`) |
| Hands-free answers | `backend/tools/handsfree_run.py` (`answer_for`) |
| LLM spike | `backend/tools/summary_llm_eval.py` |

Tests: `backend/tests/test_speech_steps.py` (every grader, fluency, the template and guard, the safety fallback and
every rewrite failure, loopback-only, the routes, hands-free play of each lesson to its patch);
`frontend/tests/speech_steps.test.js` (renderers, the summary collector, spaced repetition, counts, the Brain store
keeping the section, Progress); `frontend/tests/e2e/speech_e2e.py` (each sample lesson to its patch in the real app by
taps, typing and keys; trap caught; read-aloud counts; feedback never a grade; the Brain keeps counts and no words;
screenshots at 1440x900 and 1280x720).

## 8. What's next

- **Archaeology**: one `read` step from an NPS Mesa Verde passage once `feat/archaeology-content` lands (the step type
  and the grades 9-12 budgets are ready; nothing course-specific is in code).
- The learned Director sees `read`, `vocab`, `summary` as unknown step types ("none"), like Field School's types did,
  until a retrain appends them to `STEP_TYPES`.
- Calibrate `SUMMARY_SIM` on real kid summaries (opt-in playtests only), and measure the ear's read-aloud word accuracy
  on kid voices before showing the pace to teachers as anything more than a count.
