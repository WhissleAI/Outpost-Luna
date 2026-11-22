# Director loop: keep training the Director

The Director routes every turn: it answers, acts, navigates or stays quiet. The learned Director
(`backend/app/director_model/`) gets better only from turns it has not seen yet, so we keep feeding it:

1. real use (the turn log, on by default since 0.4.3), and playtests a grown-up runs with consent (turn log + audio);
2. today's failure classes, made into generated sessions and held-out sets;
3. a retrain that ships only when it beats both the rules and the weights already shipped.

```
make director-loop                                   # import -> real ear -> generate -> train -> evaluate -> gate -> export
make director-loop LOG=~/Downloads/turnlog           # the same, with a family's turn log imported first
make director-import LOG=~/Downloads/turnlog         # import only (writes data/real_turns.json + data/review/review.jsonl)
make director-import LOG=~/Downloads/outpost-luna-playtest-2026-11-19.zip   # a playtest export (also its audio clips)
make director-eval-real LOG=<folder | .jsonl | .zip> # the shipped routed config vs the rules on those real turns
```

Every run writes `director_model/runs/<date>/report.md` (the before / after table and the gate decision) and
`gate.json`. Only those two are committed. Model files, datasets and decodes stay local.

## Cadence

- **After every playtest.** A grown-up opens Settings → For grown-ups → Voice log and playtest → Start playtest,
  confirms permission, and plays. Afterwards: Export playtest (one zip, saved where they choose). With their consent,
  run `make director-eval-real LOG=<zip>` (how the shipped Director did on real turns) and
  `make director-loop LOG=<zip>`.
- **Any family log** (the turn log is on by default): copy the turn log folder, with consent, and import it the same way.
- **Weekly otherwise**, and whenever the router changes (new intents or screens) or a new Arc Mini / Arc Tagger
  ships (`NEW_EAR=1`, see `director_model/RETRAIN.md`).
- Read `report.md`. A FAIL keeps the shipped weights and lists each set that blocked the update. Fix the data or the
  rules, then run again. Do not lower the gate.

## 1. The turn log (privacy model)

**On by default since 0.4.3** (it was opt-in and off before; the Director had never heard a real kid). The Settings
switch is Listening → "Help improve the voice guide" (`prefs.improve`), stored per cadet profile on the device, like
every other setting. Settings → For grown-ups → "Voice log and playtest" says plainly that it is on and what it keeps.

- **Turning it off sticks.** An explicit off stays off.
- **Existing installs keep their setting (0.5.2).** Only a new install (no saved prefs) starts with it on. Prefs saved
  before 0.4.3 (no `improve_v`) keep exactly what they stored: off stays off, an old opt-in stays on (`normalizePrefs`).
  0.4.3–0.5.1 switched such saves on once; 0.5.2 stops doing that. A save that 0.4.3–0.5.1 already marked
  (`improve_v: 2`) keeps its current value.
- **The backend logs only on the client's word.** It logs when the client's prefs say `improve: true` (the app sends
  its prefs on every connect) or while a playtest runs. A client that never sends prefs (headless tools, the
  generator) writes nothing.

**What one turn holds.** All of it is text, written by `backend/app/turnlog.py` (`v` 2 since 0.4.3; the importer reads
1 and 2):

| field | content |
|---|---|
| `text` | The heard words, lowercased, after redaction (below). A turn the privacy guard caught is stored as `<private>`. |
| `arc` | Arc's `device_directed`, `command_complete` and dialogue act. |
| `frame` | The client's screen: the screen name, the step type and options, the pending offer, the lesson id and step. |
| `audio` | Booleans and a share: was our voice playing or on air, and how much the words overlap our recent lines. The audio itself is never in the log. |
| `router` | The router's outcome, reason and intent. |
| `director` | What the rules decided (`rules`; `rules_est` when the model overrode and the rules never ran, estimated from the parse), the model's act and p (`model`, `p`), the override, the final act, whether a confirm was asked, the order that ran (`cmd`: type and app slots only). v2: `mode`, the weights (`weights`), the primary model's own choice (`shadow`), each routed file's (`routed`), and which file each path consulted (`picked`: the class's turn, the navigation fill, the lesson-answer silencing; null = the rules). |
| `ear` (v2) | The ear's ABI 2 read-out on the final words, numbers and enums only: `uconf`, `min_wconf`, `eot`, `dropped`, decoder agreement (`agree`, `dec`), name links (`names`: p, state, kind; never the name), almost matches (p only), quantities (kind, small values), disfluency count, `playback_leak` / `playback`, `barge` / `barge_p`, `speech_s` / `max_pause_s` / `end_silence_s`. Null for typed turns. |
| `seen` (v2) | What the learned Director saw at the turn end (`features.record`, numbers and flags only): the situation class (`cls`: hot / short / echo / video / quiet), the bare-turn guard (`bare`), and the e13 / link / hot / entity views. |
| `room` (v2) | The room-state estimate (calm / busy / too loud) and its numbers, when the session has the estimator (`session.room_state`); null until it ships. |
| `wav` (v2) | Only in a playtest: the file name of this turn's audio clip (`playtest/<turn id>.wav`). |
| `trace` | The turn graph's per-node trace ([`TURN_GRAPH.md`](TURN_GRAPH.md), `turnlog.trace_view`): node names, milliseconds, the node each decision node chose, and small views (router outcome / reason / intent, the director handler that answered, the model's act and p). Names, numbers and code enums only, never words. The importer ignores it. |
| `t`, `day` | Seconds since the session's first logged turn, and the calendar day. No clock time. |
| `s`, `id` | A random per-session tag. It is never the session id. |

**Outcome signals** are separate lines that point back to their turn by `ref`:

| signal | when it is written |
|---|---|
| `repeat` | The kid said almost the same words again within 10 s. |
| `negate` | "no", "stop", "back" or "not that" within 6 s. |
| `retap` | The same tap twice within 6 s, right after a turn. |
| `hint` | The lesson step went to retry or hint right after a turn the router sent to it as the answer. |
| `pass` (v2) | The lesson step passed right after a turn the router sent to it as the answer. |
| `undo` (v2) | The next order within 20 s took the order back: a cancel, the same switch flipped, power moved back. |
| `confirm_cancel` / `confirm_yes` | How a confirm we asked for was answered. |

**Redaction**, before anything is written (`turnlog.redact`, `ear_view`, `seen_view`):

- Call signs: the 12 built-in ones, plus the kid's own when the client sends it.
- Names after "my name is", "call me", "I'm called", "my call sign is".
- Anything after "I live at/on/in", "my address is", "my school is".
- Phone-like numbers. Short numbers stay, because "shields to 40" is the signal we need.
- The v2 fields hold numbers, booleans and short enum labels only. The ear's words, spoken form, decoder text, clean
  text, name candidates and entities never enter them (`backend/tests/test_turnlog_v2.py` plants a name, a call sign
  and a sound-alike candidate and checks none reach the log).

**Never stored:** audio (outside a playtest), names, the session id, the device, and clock times.

**Storage.** The log lives in `<app data>/turnlog/turns.jsonl`. The desktop app keeps it in its per-user cache folder;
`TURNLOG_DIR` overrides the location. The file rotates to `turns.1.jsonl` at 2.5 MB, so the folder never holds much
more than 5 MB.

`GET /api/turnlog` returns the size, turn count and playtest clips. `DELETE /api/turnlog`, the "Delete what's saved"
button in Settings → Listening, erases the log and any playtest audio.

**Leaving the device.** The app never uploads the log. A developer reads it only when a family hands the folder (or a
playtest export) over.

The import (`director_model/import_logs.py`) behaves as follows:

- It skips `<private>` turns and any text that still carries a redaction tag.
- Imported turns go to `director_model/data/real_turns.json` and `data/review/`; playtest clips to
  `data/real_audio/`. All are git-ignored and never committed.
- Delete them when the family asks, or when the playtest is over.

## 1b. Playtest session (grown-ups, with audio)

Settings → For grown-ups (behind the 3-second hold) → **Voice log and playtest** → Start playtest.

1. **Consent.** A short screen: each thing the child says is saved as audio; it stays on this computer; it stops when
   you press Stop or close the app. "Start playtest" stays disabled until the grown-up ticks "I'm the parent or
   guardian, or I have their permission." The backend refuses to start without that consent
   (`POST /api/playtest/start {"consent": true}` with the page's own header).
2. **While it runs.** The turn log is on even if the switch was off. The mic relay (`/ws/listen`) keeps the last 40 s
   of the mic audio it already sends to the ear, in memory, and cuts each heard turn (1 s before the ear's turn start
   to its end). The turn log writes it as `turnlog/playtest/<turn id>.wav` (16 kHz mono) and names it in the turn's
   `wav`. A private turn (the privacy guard) never gets audio. A small **PLAYTEST** tag with a red lamp shows in the
   top bar.
3. **Export playtest…** writes ONE zip where the grown-up chooses: a save dialog in the desktop app
   (`desktop/main/playtest.js`), a download in the browser build. The zip holds `turns.jsonl` (+ `turns.1.jsonl`),
   `playtest/*.wav`, `manifest.json` (format, app version, turn log version, day, counts) and a README.
4. **Off again** when the grown-up presses Stop, when the page closes (a reload, a profile switch), after 3 hours, and
   when the app quits (the playtest lives in the backend process only). The audio stays until "Delete what's saved".

**On the developer's side:**

```
make director-import LOG=outpost-luna-playtest-2026-11-19.zip   # labels + data/real_audio/<zip>/{*.wav,clips.jsonl}
cd model_server && uv run python ../director_model/import_logs.py decode --audio ../director_model/data/real_audio/<zip>
python3 director_model/import_logs.py retest                    # data/real_retest.json: held-out real-turn decodes
make director-eval-real LOG=outpost-luna-playtest-2026-11-19.zip
```

The importer reads zip members by name only (never extracting paths). `decode` runs each clip through the app's own
ear (`EarStream`) and stores the decode in the real-ear cache form, so the generator replays the real message stream
(`gen_sessions` set `test_log_audio`). `retest` keeps only clips whose words hash to the held-out split (`--all` for a
report-only set that may overlap training words).

## 1c. The class gate on real turns (`make director-eval-real`)

`director_model/eval_real.py` needs no model run: a v2 turn carries what the app decided live on every path. Per
situation class (plus `nav` and `answer`, and `all`), it prints turns, act ok and wrong actions for the rules and for
the shipped config, and the extra wrong actions (shipped wrong where the rules were right). Gold is the import's weak
label at ≥ 0.6, or a reviewed label. It says which weights and mode decided the turns, and warns when that is not what
this checkout ships. v1 turns count under `unknown`.

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
- **No real children in the generated sets.** Kid voices are TTS. Until real logs and playtests arrive, `test_log` and
  `test_log_audio` are empty and the gate rests on generated sets.
- **Rules fixes shrink what is left for the model.** When the router learns a class (for example
  `grade.plausible` silencing lesson chatter), the rules column rises and the model's room on that class shrinks.
  The gate still checks it never falls below.

## 7. Round 8: coverage and collection

- The capability × flow inventory and the round-8 plan and gate are in `docs/DIRECTOR_COVERAGE.md`:
  `director_model/coverage.json`, `make director-coverage`, `make director-r8`.
- Real data is collected with the kit in `docs/DIRECTOR_COLLECTION.md`: a 15-minute guided, consented, local session
  (`make director-collect`), imported with `collect_import.py`.
