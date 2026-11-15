# Director loop: keep training the Director

The Director routes every turn: it answers, acts, navigates or stays quiet. The learned Director
(`backend/app/director_model/`) gets better only from turns it has not seen yet, so we keep feeding it:

1. real use, from families who opt in (the turn log);
2. today's failure classes, made into generated sessions and held-out sets;
3. a retrain that ships only when it beats both the rules and the weights already shipped.

```
make director-loop                                   # import -> real ear -> generate -> train -> evaluate -> gate -> export
make director-loop LOG=~/Downloads/turnlog           # the same, with a family's turn log imported first
make director-import LOG=~/Downloads/turnlog         # import only (writes data/real_turns.json + data/review/review.jsonl)
```

Every run writes `director_model/runs/<date>/report.md` (the before / after table and the gate decision) and
`gate.json`. Only those two are committed. Model files, datasets and decodes stay local.

## Cadence

- **After every playtest.** Ask the family to turn on Settings → Listening → "Help improve the voice guide" before
  the session. Copy the turn log folder afterwards, with their consent. Run `make director-loop LOG=<folder>`.
- **Weekly otherwise**, and whenever the router changes (new intents or screens) or a new Arc Mini / Arc Tagger
  ships (`NEW_EAR=1`, see `director_model/RETRAIN.md`).
- Read `report.md`. A FAIL keeps the shipped weights and lists each set that blocked the update. Fix the data or the
  rules, then run again. Do not lower the gate.

## 1. The turn log (privacy model)

**Off by default.** The Settings switch is "Help improve the voice guide" (`prefs.improve`). It is stored per cadet
profile on the device, like every other setting. Only an explicit `true` turns logging on (`normalizePrefs`,
`session.clean_prefs`). With it off, nothing is written.

**What one turn holds.** All of it is text, written by `backend/app/turnlog.py`:

| field | content |
|---|---|
| `text` | The heard words, lowercased, after redaction (below). A turn the privacy guard caught is stored as `<private>`. |
| `arc` | Arc's `device_directed`, `command_complete` and dialogue act. |
| `frame` | The client's screen: the screen name, the step type and options, the pending offer, the lesson id and step. |
| `audio` | Booleans and a share: was our voice playing or on air, and how much the words overlap our recent lines. The audio itself is never stored. |
| `router` | The router's outcome, reason and intent. |
| `director` | What the rules decided, what the model decided (act and probability), the override, the final act, and whether a confirm was asked. |
| `t`, `day` | Seconds since the session's first logged turn, and the calendar day. No clock time. |
| `s`, `id` | A random per-session tag. It is never the session id. |

**Outcome signals** are separate lines that point back to their turn by `ref`:

| signal | when it is written |
|---|---|
| `repeat` | The kid said almost the same words again within 10 s. |
| `negate` | "no", "stop", "back" or "not that" within 6 s. |
| `retap` | The same tap twice within 6 s, right after a turn. |
| `hint` | The lesson step went to retry or hint right after a turn the router sent to it as the answer. |
| `confirm_cancel` / `confirm_yes` | How a confirm we asked for was answered. |

**Redaction**, before anything is written (`turnlog.redact`):

- Call signs: the 12 built-in ones, plus the kid's own when the client sends it.
- Names after "my name is", "call me", "I'm called", "my call sign is".
- Anything after "I live at/on/in", "my address is", "my school is".
- Phone-like numbers. Short numbers stay, because "shields to 40" is the signal we need.

**Never stored:** audio, names, the session id, the device, and clock times.

**Storage.** The log lives in `<app data>/turnlog/turns.jsonl`. The desktop app keeps it in its per-user cache folder;
`TURNLOG_DIR` overrides the location. The file rotates to `turns.1.jsonl` at 2.5 MB, so the folder never holds much
more than 5 MB.

`GET /api/turnlog` returns the size and turn count. `DELETE /api/turnlog`, the "Delete what's saved" button in
Settings, erases the log.

**Leaving the device.** The app never uploads the log. A developer reads it only when a family hands the folder over.

The import (`director_model/import_logs.py`) behaves as follows:

- It skips `<private>` turns and any text that still carries a redaction tag.
- Imported turns go to `director_model/data/real_turns.json` and `data/review/`. Both are git-ignored and never
  committed.
- Delete them when the family asks, or when the playtest is over.

## 2. Import: weak labels from outcome signals

`make director-import LOG=<folder or .jsonl>` gives each logged turn a gold act and a confidence:

| what happened | label | confidence |
|---|---|---|
| ignored, then repeated, and the repeat was acted on without a complaint | the repeat's act (the ignore was wrong) | 0.75 |
| ignored, no complaint | ignore | 0.8 when Arc said not directed or the words were chatter, else 0.65 |
| a lesson answer that went to hint, and the words were chatter ("oh it's", "okay") | ignore | 0.75 |
| a lesson answer that went to hint, real words | nudge (a wrong answer) | 0.6 |
| acted, then no / stop / back / retap / cancelled confirm, on chatter or a not-directed turn | ignore | 0.6 |
| acted, then no / stop / back / retap / cancelled confirm | ask_clarify | 0.45 → review |
| acted, then repeated | the act | 0.45 → review |
| acted, confirmed | the act | 0.9 |
| acted, no signal | the act | 0.7 |

Turns below 0.6 go to `data/review/review.jsonl` instead of training. To correct one:

1. Set its `fix` to `ignore`, `answer`, `command`, `navigate`, `ask_clarify`, `nudge` or `skip`.
2. Append the line to `data/review/reviewed.jsonl`.

The next import applies reviewed labels at confidence 1.0. They also replace an earlier weak label for the same turn.

The generator plays imported turns as they were heard, in their screen frame, with their device_directed. They are
split by a hash of the words: about 75 % train, 10 % val, 15 % `test_log`, a held-out set the gate checks once it
exists.

## 3. Today's failure classes (generation + eval sets)

`director_model/pools.py` (`cls_item`) and `gen_sessions.py` (`handsfree_script`, the `cls_*` sets) produce hands-free
sessions. Each item sends the client's screen frame, so the router sees exactly what the app sees:

| set | what | gold |
|---|---|---|
| `cls_chatter` | Short room chatter during any lesson step: "oh, it's", "okay", "alright". | ignore: never an answer, never a miss |
| `cls_echo` | The app's own words heard between two back-to-back CAPCOM lines. The lines are sometimes one queued sequence (`more`), sometimes two separate decisions. | ignore |
| `cls_offer` | "next" or "yes" (or "no") 0.02–0.3 s after the offer line ended. | navigate |
| `cls_panel` | "open the comm panel" next to "turn off the radio". | navigate vs the command |
| `cls_help` | Voice bar, tour, help, "what do I do", repeat, slower. | navigate |
| `cls_mode` | "go to mission", "back to the map", "open the library", said in the middle of a lesson step. | navigate |
| `cls_globe` | The 6 globe step types answered by voice: predict, globe_side, terminator, compare, route, earth_view. | the grader on the clean words |
| `cls_mishear` | Kid lines heard through the real Arc ear, for example "eyes" for "ice". | the kid's intent |
| `cls_roomtalk` (round 7) | Room talk Arc Tagger rates device-directed (drawn 0.75–0.98): swearing, exclamations, sibling talk ("shit shit oh", "oh my god", "give it back"), on any screen. | ignore |

The real ear (`real_ear.py`) renders these turns in memory with held-out Steer voices and decodes them with Arc. It
also renders the app's own lines in the app's voices (Aurora `voice_1085`, CAPCOM `voice_0213`, Beacon `voice_0644`),
so the echo set hears what the ear really makes of our speech. No WAV is ever written.

Round 7: every real-ear job carries its screen frame and that screen's hot lists (`backend/app/hotlist.py`), and the
decoder gets them as the app sends them, so the decodes are what the biased ear hears. The final words carry the
ear's n-best, confidence and hot-list match, which the generator replays (features `ear_*`).

**Outcome signals in generation (round 7).** Where no turn log exists, the generator simulates the "ignored, then
repeated" signal from its own errors: when the router ignores a train / val turn whose gold is not ignore, the kid says
it again (`--repeat-p`, 0.5) through the ear again, with the same gold. The features `rep_prev`, `prev_ignored`,
`prev_acted`, `neg_now` carry the signal at serving time too.

## 4. What the model may do (unchanged rule: a wrong action costs more than a missed one)

- **Features.** The hands-free features (screen, step type, offer, router outcome, navigation intent, on-air timing,
  echo of recent lines, chatter) are appended after the round-5 block. Older weights read their own prefix
  (`features.F_R5`), so new code never breaks shipped weights.
- **New act.** `navigate` is appended to the act list (round 6).
- **Navigation head (round 7).** A `nav` head names WHICH navigation (`features.NAV_INTENTS`: take / decline the offer,
  map, library, mission, take command, each panel, help, tour, repeat, slower, settings, ...). On a turn the router did
  not navigate, the model may navigate (`runtime.nav_policy`, `Session._model_nav`) when p(act = navigate) and p(intent)
  are both ≥ `nav`, fit on val to add no wrong actions; only intents it can run without an argument (not a lesson or a
  site), and taking an offer only while one is on screen. A wrong navigation now counts as a wrong action in the eval,
  for the rules too, and a navigate act is right only with the right intent.
- **Round-7 features** (appended, `F_R6` = 216 → 236): the screen's hot-list match per tier (exact hits and sound-alike
  score), the ear's confidence / n-best / rescoring / matched tier, the grader passing only on its sound-alike repair,
  the router's navigation inside a longer turn, and the outcome signals above. device_directed is one feature among
  these, never the deciding one.
- **Lesson answers.** On a turn the router sent to a lesson step as its answer, the model may only silence it
  (`answer_policy`). It needs p(ignore) ≥ `answer_ignore`, fit on val to add no lost answers. The default is off.
- **Everything else is as in `RETRAIN.md`.** The guard wins. A rules command stands unless vetoed. The model fills
  only when sure. The rules decide every turn the model does not take.

## 5. The gate (`director_model/loop.py gate`)

The candidate is trained with thresholds fit on val. The shipped weights run exactly as they run in the app: the
numpy runtime with their own policy (`evaluate.py --weights`). Both are scored on the same freshly generated sets.

The new weights ship only if criteria 1–4 hold on **every** held-out set and criterion 5 holds overall. The sets are `test_clean`, `test_asr`, `test_real`,
`test_ear`, `test_h40`(+asr), `test_q80`(+asr), `test_gold`, every `cls_*` (round 7 adds `cls_roomtalk`) and `test_log`.

1. Guarded `on` wrong actions ≤ the rules (the `RETRAIN.md` switch-on criterion).
2. Guarded `on` act accuracy ≥ the rules.
3. The privacy-guard rows are unchanged.
4. No class regresses: on `cls_*` and `test_log`, act accuracy ≥ the shipped weights' and wrong actions ≤ theirs.
5. Worth shipping: summed over all sets, no more wrong actions and no fewer right acts than the shipped weights. This
   stops a retrain that is only "as good as the rules" from replacing a better model.

On a PASS, the old weights are copied to `runs/<date>/weights_before/` for rollback, and `export.py` writes the new
`weights.*` and the parity fixture. On a FAIL nothing changes. The report says why.

## 6. Limits

- **Proxy signals, not ground truth.** Weak labels are only a proxy. A "no" may answer CAPCOM's question rather than
  complain. That is why low-confidence turns go to a person, and why reviewed labels beat weak ones.
- **No real children in the generated sets.** Kid voices are TTS. Until enough families opt in, `test_log` is empty and
  the gate rests on generated sets.
- **Rules fixes shrink what is left for the model.** When the router learns a class (for example
  `grade.plausible` silencing lesson chatter), the rules column rises and the model's room on that class shrinks.
  The gate still checks it never falls below.

## 7. Round 8: coverage and collection

- The capability × flow inventory and the round-8 plan and gate are in `docs/DIRECTOR_COVERAGE.md`:
  `director_model/coverage.json`, `make director-coverage`, `make director-r8`.
- Real data is collected with the kit in `docs/DIRECTOR_COLLECTION.md`: a 15-minute guided, consented, local session
  (`make director-collect`), imported with `collect_import.py`.
