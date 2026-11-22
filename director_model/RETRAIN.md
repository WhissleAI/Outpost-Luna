# Retraining the Director for a new Arc model

The Director reads Arc's streams: **Arc Mini's ear** (words, partials, turns, `device_directed`, `command_complete`)
and **Arc Tagger** (acts, PII, numbers, mentions, `command_complete`). When the Arc team ships a new Arc Mini or Arc
Tagger, those streams change: different words, different errors, different tag probabilities. Redo the Director like
this, then compare with the last row of `RESULTS.md`.

## One command

```
make director-retrain                       # defaults: data director_model/data/ds, run director_model/runs/latest, size m
make director-retrain DM_SIZE=s DM_GEN_ARGS="--train 3000 --val 300 --test 300"
```

`make director-retrain` first runs `make director-real-ear`: it renders every generated kid turn (jobs from the
same seeds as the generator) with Steer TTS Edge and decodes the audio with the **real Arc ear** (in process,
model_server's `EarStream` = `/v1/stream?ear=arc`, Tier A context), cached under `director_model/cache/real_ear/`
(gitignored, text only: `dec/` decodes, ~5 KB per turn; the audio is rendered in memory, seeded, never written).
**New Arc Mini: `make director-retrain NEW_EAR=1`** drops `dec/` and re-renders + re-decodes (~1 clip/s with 6
workers x 2 threads). The generator replays these
decodes (words, partials, eager/end, Arc's device_directed) for the noised turns (`--real-p`, default 0.9) and builds
`test_real`: held-out sessions (unseen templates / card questions) heard through held-out voices.

It starts a private model server on :8290 (never :8200, the live one), refits the ASR error model, regenerates the
sessions, trains, evaluates, exports `backend/app/director_model/weights.{npz,json}` + the parity fixture, and runs the
runtime tests. Step by step:

## 1. Re-run the ear on the eval audio (new Arc Mini)

The eval clips, references and runner live in `backend/tests/fixtures/ear_eval/` (40 kid-style lines x 2 Steer
voices, half with classroom noise).

```
# the audio is not in git: render it once with Steer TTS (render.py, same folder) if audio/ is missing
cd model_server && uv run python ../backend/tests/fixtures/ear_eval/eval_arc.py --cond none,tier_a,mission
```
(`eval_arc.py` loads Arc Mini in-process from the model server env; point that env at the new Arc Mini.)

That writes `results_arc_*.json` (ref vs hyp per clip, per condition). Add the new file to `SOURCES` at the top of
`director_model/ear_errors.py` (the first entry is the current ear; the ear-eval test set `test_ear` reads the files
named in `gen_sessions.py`, `ear_rows("test", [...])`).

## 2. Refit the ASR error model

```
uv run --project backend python director_model/ear_errors.py build      # -> director_model/data/error_model.json
```

Fitted on the **odd** item ids only; the even ids stay the held-out `test_ear` set (the new model's real decodes).
Check the printed substitution count and tail rate: a better ear has fewer subs and a lower `tail_rate_noisy`.

## 3. Re-featurize: regenerate the sessions

New Arc Tagger: point the model server at the new tagger (`ARCTAG_LIB`, `ARCTAG_MODEL_DIR`, see
`model_server/app/config.py`). The generator calls the real tagger and the real embedder for every turn, so the
`tag_*` features and the rules teacher pick up the new model automatically.

```
cd model_server && EMBED_MODEL_DIR=<minilm dir> OS_TTS=off ARC_EAR=off ARC_META=off \
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8290
MODEL_SERVER_URL=http://127.0.0.1:8290 uv run --project backend python director_model/gen_sessions.py \
    --out director_model/data/ds --train 3000 --val 300 --test 300
```

**The embedder must be loaded** (`EMBED_MODEL_DIR` above: the app has it, so the `ent_*` / embedding features and the
rules teacher depend on it). Since round 14 `gen_sessions.py` asks the model server's `/health` first and stops with an
error naming why when the embedder is missing or not loaded (rounds 12 and 13 trained on the brain's embedding
fallbacks without noticing). `--allow-no-embedder` generates anyway, with a warning, for a deliberate comparison only.

If the knowledge cards changed, refresh their question snapshot first (`director_model/data/card_questions.json`;
the one-liner is in the round-1 notes of `RESULTS.md`). If `features.py` changed (a new Arc output became a feature),
`F` changes: everything downstream must be retrained (the runtime refuses weights with a different `F`).

## 4. Retrain, evaluate, export

```
python3 director_model/train.py --data director_model/data/ds --out director_model/runs/<name> --size m
python3 director_model/evaluate.py --data director_model/data/ds --run director_model/runs/<name>
python3 director_model/export.py --run director_model/runs/<name> --data director_model/data/ds \
    --eval director_model/runs/<name>/eval.json
cd backend && uv run pytest -q
```

## 5. Compare against the last RESULTS row

Append a round to `RESULTS.md` with the same table. The default is `DIRECTOR_MODEL=on` (since round 4) with the rules
as fallback. Ship new weights only if the guarded `on` rows (evaluate.py prints them; thresholds are refit on val by
`fit_policy`) still meet the switch-on criteria in `RESULTS.md`: wrong/50 <= the rules on EVERY held-out set
(test_clean, test_asr, test_real, test_ear, test_h40(+asr), test_gold), act accuracy >= the rules on every set, and
the guard/PII rows unchanged. Otherwise keep the previous weights, or set `DIRECTOR_MODEL=shadow`, and read
`/api/director/stats` on real sessions.

## Round 6 on: the continuous loop

`make director-loop` (docs/DIRECTOR_LOOP.md) wraps steps 1-5 for routine retrains:

- It imports opt-in turn logs (`LOG=...`), then renders and decodes the new turns with the real ear.
- It generates hands-free sessions and the round-6 class sets (`cls_*`, `test_log`) on top of the sets above.
- It trains a candidate. It evaluates the candidate and the shipped weights (numpy runtime, their own policy) on the
  same data.
- It exports only if the gate passes: these switch-on criteria on every set, plus no class regression vs the shipped
  weights.

Features are append-only (`features.F_R5`): older weights read their prefix, so a code change never forces a retrain.
Keep it that way. Add new Arc outputs at the end of `FEATS`, never in the middle.

## Round 14: echo and kid-over-playback decodes

- `real_ear.py r14` adds jobs (groups `overplay_train` / `_val` / `_test`) for every kid turn the generator says over
  our playback, rendered with one of the app's lines under it and that line fed as the ear's reference. Decode them with
  `real_ear.py decode --order r14`; the generator then replays them for those turns (their live `playback_leak`).
- The `echo` / `echo2` items replay the app-voice decodes' full message stream (with the leak / barge read-out).
- The simulated speaker -> mic path is the calibrated laptop (`render_r8.SPEAKER_PROFILE`, default `laptop`);
  `SPEAKER_PROFILE=r13` reproduces round-13 renders. `real_ear.py leak --n 60 --profiles r13,laptop` (model server env)
  measures the own-line leak each gives (the real laptop: median 0.75, `docs/ARC_ABI2.md` section 8). Re-decode the
  echo-bed jobs (`NEW_EAR=1` or a fresh cache) after changing the profile: cached decodes keep the old path.

## Round 15: the raw feature set and the shadow file

- `features.raw_feats` (`--feats raw` in `train.py`) is a second feature set: perception and state only (the ear's
  words, names / link p, decoder agreement, ABI 2 read-outs, dd; Arc Tagger's acts / intents / span types / PII; the
  embedder's vector of the words; the entity layer; our own audio; screen / lesson / mission state; timing). No regex
  flag, mission NLU, router outcome or grader result. The legacy set is unchanged and stays the default, so every
  shipped file still loads. A raw file says `"feat_set": "raw"` in its json.
- A raw turn end reads the record the Session takes BEFORE routing (`runtime.Shadow.perceive`, one call in
  `session._turn`), with the tagger read and the embedder vector fetched there on every path. The generator records it
  too (`rec["raw"]`), so train and serve read the same thing. Generating a raw dataset therefore needs the model
  server's tagger AND embedder.
- `train.py --r15` adds the reply-line and entity pointer heads and the option / nav-argument slot heads. They need
  `r15_labels.py` (candidates + their embeddings + labels) run on the dataset first. `gate_r15.py` gates the raw
  candidate against what ships and reports the new heads; `export.py --name weights_r15` writes the shadow file.
- `weights_r15.*` is SHADOW ONLY: the runtime steps it on every event and logs what it would do (turn log
  `director.r15`, `/api/director/stats` `r15`); no decision reads it. `DIRECTOR_R15=off` unloads it (and stops the
  pre-routing tagger / embedder read). `director_model/run_r15.sh` is the whole round.
