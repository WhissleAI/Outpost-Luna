#!/usr/bin/env bash
# Round 10 of the director loop: the FULL gate on the new ear (all round-8 sets rebuilt, not round 9's 9 of 28) and
# the per-class enable (DIRECTOR_MODEL=guarded; runtime.situation / evaluate.class_gate).
#   jobs -> decode (reuses round 9's cache) -> generate -> train xl only (2,200 steps, --fp-exec 0.5)
#   -> evaluate: the shipped r4 s with its current policy (veto off, min3) and the r10 xl + min3, each with the
#   per-class gate. Nothing is exported: shipping weights / a class list is a separate, deliberate step.
#   ARC_SPACE_DIR=... ARC_LIB=... BACKEND_PY=... MODEL_PY=... MS_PORT=8331 bash director_model/run_r10.sh
set -euo pipefail
cd "$(dirname "$0")/.."
BPY=${BACKEND_PY:-backend/.venv/bin/python}
MPY=${MODEL_PY:-.venv/bin/python}
DATA=${DATA:-director_model/data/ds_r10}
RUN=${RUN:-director_model/runs/$(date +%Y-%m-%d)-r10}
SHARDS=${SHARDS:-3}
PROCS=${PROCS:-2}
MS_PORT=${MS_PORT:-8331}
TRAIN=${TRAIN:-2400}
COV=${COV:-1200}
STEPS=${STEPS:-2200}
POL='{"veto": null, "ignore_min_words": 3}'
export REAL_EAR_CACHE=${REAL_EAR_CACHE:-$PWD/director_model/cache/real_ear_r9}
GEN="--out $DATA --train $TRAIN --val 200 --test 200 --hf-p 0.3 --cls-n 160 --r8-p 0.35 --cov-sessions $COV --cov-heldout 10"
python3 director_model/loop.py preflight
mkdir -p "$RUN" "$DATA"
if [ -z "${SKIP_GEN:-}" ]; then
$BPY director_model/coverage.py
$BPY director_model/real_ear.py jobs --budget 900 --val-budget 300 --test-budget 500 --hf-p 0.3 --cls-n 160
(cd model_server && EAR_PARTIAL_EVERY_S=${EAR_PARTIAL_EVERY_S:-3.0} OMP_NUM_THREADS=2 \
  $MPY ../director_model/real_ear.py decode --procs "$PROCS" --threads 2 --order test_first)
(cd model_server && STEER_TTS=off ARC_EAR=off ARC_META=off OS_TTS=off \
  $MPY -m uvicorn app.main:app --host 127.0.0.1 --port "$MS_PORT" > "../$RUN/ms.log" 2>&1 &)
stop_ms() { kill $(lsof -tiTCP:"$MS_PORT" -sTCP:LISTEN 2>/dev/null) 2>/dev/null || true; }
trap stop_ms EXIT
until curl -sf "localhost:$MS_PORT/health" >/dev/null; do sleep 2; done
export MODEL_SERVER_URL=http://127.0.0.1:$MS_PORT
pids=()
for i in $(seq 0 $((SHARDS - 1))); do
  $BPY director_model/gen_sessions.py $GEN --shard "$i/$SHARDS" > "$DATA/gen_s$i.log" 2>&1 & pids+=($!)
done
$BPY director_model/gen_sessions.py $GEN --only "val,test_clean,test_asr,test_real,test_ear,test_h40,test_h40_asr,test_q80,test_q80_asr,test_gold,cls_chatter,cls_echo,cls_offer,cls_panel,cls_help,cls_mode,cls_globe,cls_mishear,cls_roomtalk,cls_video_ctrl,cls_video_echo,cls_prep,cls_prep_roomtalk,cls_voice_echo_os,cls_gesture_cooccur,cls_lesson_new,cls_offers_new,cls_coverage,cls_coverage_pending,test_log" > "$DATA/gen_rest.log" 2>&1 & pids+=($!)
for p in "${pids[@]}"; do wait "$p"; done
$BPY director_model/gen_sessions.py --out "$DATA" --merge "$SHARDS"
stop_ms
fi
# the shipped r4 s, as it runs today (its policy + veto off + min3), and its per-class gate
python3 director_model/evaluate.py --data "$DATA" --weights backend/app/director_model --policy "$POL" --class-gate \
  --out "$RUN/eval_shipped.json" > "$RUN/eval_shipped.log" 2>&1
python3 director_model/train.py --data "$DATA" --out "$RUN/xl/cand" --size xl --threads 4 --steps "$STEPS" \
  --fp-exec 0.5 > "$RUN/train_xl.log" 2>&1
python3 director_model/evaluate.py --data "$DATA" --run "$RUN/xl/cand" --policy "$POL" --class-gate \
  --out "$RUN/xl/eval_candidate.json" > "$RUN/xl/eval_candidate.log" 2>&1
