#!/usr/bin/env bash
# Round 15 of the director loop (director_model/RESULTS.md, Round 15): the "raw" feature set (perception + state only,
# features.raw_feats), the reply-line / entity pointer heads and the option / nav-argument slot heads, trained on
# sessions generated WITH the embedder loaded. Shadow only: nothing here changes what ships.
#   jobs (fresh: no earlier cache on this machine) -> relist --all (today's names lists, no hot list) -> r13 + r14 jobs
#   -> decode (5 procs; the ABI 2 ear, our playback fed as its reference, warmed canceller) -> generate every set
#   (embedder + tagger loaded; the pre-routing perception per turn) -> r15_labels.py (candidates, embeddings, labels)
#   -> train raw xl (+ the r15 heads) -> gate_r15.py vs what ships (r12 routed) -> export weights_r15 (shadow file)
#   BACKEND_PY=... MODEL_PY=... ARC_SPACE_DIR=.../nft2 ARC_LIB=.../libarc.dylib ARCTAG_LIB=... ARCTAG_MODEL_DIR=...
#   EMBED_MODEL_DIR=.../minilm APP_ASSETS=<empty dir> bash director_model/run_r15.sh
# Round 15 ran a REDUCED round (train 1600 + 800 coverage sessions, no stress sets; RESULTS.md says what the full one
# needs). APP_ASSETS pointed at an empty folder: the NASA video / crew-clip beds fall back to room noise (the app's
# own asset folder is never read by this pipeline).
set -euo pipefail
cd "$(dirname "$0")/.."
BPY=${BACKEND_PY:-backend/.venv/bin/python}
MPY=${MODEL_PY:-model_server/.venv/bin/python}
abs() { python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$1"; }
BPY=$(abs "$BPY"); MPY=$(abs "$MPY")
DATA=${DATA:-director_model/data/ds_r15}
RUN=${RUN:-director_model/runs/$(date +%Y-%m-%d)-r15}
MS_PORT=${MS_PORT:-8371}
STEPS=${STEPS:-2200}
TRAIN=${TRAIN:-1600}
COV=${COV:-800}
POL='{"veto": null, "ignore_min_words": 3}'
export REAL_EAR_CACHE=${REAL_EAR_CACHE:-$PWD/director_model/cache/real_ear_r15}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1} VECLIB_MAXIMUM_THREADS=${OMP_NUM_THREADS:-1}
GEN="--out $DATA --train $TRAIN --val 200 --test 200 --hf-p 0.3 --cls-n 160 --r8-p 0.35 --cov-sessions $COV"
GEN="$GEN --cov-heldout 10 --r13-p 0.6"
mkdir -p "$RUN" "$DATA"
if [ -z "${SKIP_DECODE:-}" ]; then
: "${ARC_SPACE_DIR:?}" "${ARC_LIB:?}"
$BPY director_model/real_ear.py jobs --train "$TRAIN" --val 200 --test 200 --budget 500 --val-budget 300 \
  --test-budget 500 --hf-p 0.3 --cls-n 160 --r11 --r11-train 3000 --r11-variants 400 --ho-sessions 55
$BPY director_model/real_ear.py relist --all --src "$REAL_EAR_CACHE"
(cd director_model && $BPY real_ear.py r13 --train "$TRAIN" --val 200 --hf-p 0.3 --r13-p 0.6 --cls-n 160 && \
  $BPY real_ear.py r14 --train "$TRAIN" --val 200 --test 200 --hf-p 0.3)
grep -v '"group": "echo_bank"' "$REAL_EAR_CACHE/jobs.jsonl" > "$REAL_EAR_CACHE/jobs.tmp"   # ear analysis only
mv "$REAL_EAR_CACHE/jobs.tmp" "$REAL_EAR_CACHE/jobs.jsonl"
(cd model_server && OMP_NUM_THREADS=2 nice -n 10 $MPY ../director_model/real_ear.py decode --procs 5 --threads 2 \
  --order r14 > "../$RUN/decode.log" 2>&1)
fi
if [ -z "${SKIP_GEN:-}" ]; then
: "${ARCTAG_LIB:?}" "${EMBED_MODEL_DIR:?}"
(cd model_server && STEER_TTS=off ARC_EAR=off ARC_META=off OS_TTS=off \
  nice -n 5 $MPY -m uvicorn app.main:app --host 127.0.0.1 --port "$MS_PORT" > "../$RUN/ms.log" 2>&1 &)
stop_ms() { kill $(lsof -tiTCP:"$MS_PORT" -sTCP:LISTEN 2>/dev/null) 2>/dev/null || true; }
trap stop_ms EXIT
until curl -sf "localhost:$MS_PORT/health" >/dev/null; do sleep 2; done
export MODEL_SERVER_URL=http://127.0.0.1:$MS_PORT
SETS=val,test_clean,test_asr,test_real,test_voice_heldout,test_ear,test_h40,test_h40_asr,test_q80,test_q80_asr,test_gold
SETS=$SETS,cls_chatter,cls_echo,cls_offer,cls_panel,cls_help,cls_mode,cls_globe,cls_mishear,cls_roomtalk,cls_video_ctrl
SETS=$SETS,cls_video_echo,cls_prep,cls_prep_roomtalk,cls_voice_echo_os,cls_gesture_cooccur,cls_lesson_new,cls_offers_new
SETS=$SETS,cls_coverage,cls_lesson_answer
pids=()
nice -n 10 $BPY director_model/gen_sessions.py $GEN --only "$SETS" > "$DATA/gen_rest.log" 2>&1 & pids+=($!)
for i in 0 1 2; do
  nice -n 10 $BPY director_model/gen_sessions.py $GEN --shard "$i/3" > "$DATA/gen_s$i.log" 2>&1 & pids+=($!)
done
for p in "${pids[@]}"; do wait "$p"; done
$BPY director_model/r15_labels.py --data "$DATA" > "$RUN/r15_labels.log" 2>&1
stop_ms
fi
nice -n 10 python3 director_model/train.py --data "$DATA" --out "$RUN/xl/cand" --size xl --threads 4 --steps "$STEPS" \
  --fp-exec 0.5 --feats raw --r15 > "$RUN/train_xl.log" 2>&1
nice -n 10 python3 director_model/gate_r15.py --data "$DATA" --ship backend/app/director_model --cand "$RUN/xl/cand" \
  --policy "$POL" --memo "$RUN/memo" --tag r15xl --out "$RUN/xl/gate_r15.json" --policy-out "$RUN/xl/policy.json" \
  > "$RUN/xl/gate_r15.log" 2>&1
# the shadow file (never routed, never consulted by a decision): backend/app/director_model/weights_r15.*
python3 director_model/export.py --run "$RUN/xl/cand" --data "$DATA" --name weights_r15 --policy-json "$RUN/xl/policy.json"
