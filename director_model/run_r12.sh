#!/usr/bin/env bash
# Round 12 of the director loop: the same scripts as round 11 (ds_r11b), every set regenerated with the ear's real
# read-out replayed (backend/app/director_model/replay.py) and no invented command_complete; 261 features.
#   relist (round 11's jobs, today's names lists) -> decode (<= 2 procs, nice) -> generate every set
#   -> train xl and s -> gate_r12.py: rules / r10 / r11 / r12 per class, and the routed config (r10 in hot + echo)
# Shipping is a separate, deliberate step (export.py, then gate_r12.py --cand-weights on the export).
#   ARC_SPACE_DIR=... ARC_LIB=... BACKEND_PY=... MODEL_PY=... MS_PORT=8351 R11=.../wt-moon-r11/director_model \
#     bash director_model/run_r12.sh
set -euo pipefail
cd "$(dirname "$0")/.."
BPY=${BACKEND_PY:-backend/.venv/bin/python}
MPY=${MODEL_PY:-model_server/.venv/bin/python}
R11=${R11:?round 11 director_model dir (its caches and runs)}
DATA=${DATA:-director_model/data/ds_r12}
RUN=${RUN:-director_model/runs/$(date +%Y-%m-%d)-r12}
MS_PORT=${MS_PORT:-8351}
STEPS=${STEPS:-2200}
POL='{"veto": null, "ignore_min_words": 3}'
C=$PWD/director_model/cache
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1} VECLIB_MAXIMUM_THREADS=${OMP_NUM_THREADS:-1}
GEN="--out $DATA --train 2400 --val 200 --test 200 --hf-p 0.3 --cls-n 160 --r8-p 0.35 --cov-sessions 1200 --cov-heldout 10"
mkdir -p "$RUN" "$DATA"
if [ -z "${SKIP_DECODE:-}" ]; then
for c in "" _harsh _odd; do
  REAL_EAR_CACHE=$C/real_ear_r12$c $BPY director_model/real_ear.py relist --src "$R11/cache/real_ear_r11$c"
  (cd model_server && REAL_EAR_CACHE=$C/real_ear_r12$c EAR_PARTIAL_EVERY_S=3.0 OMP_NUM_THREADS=4 \
    $( [ "$c" = _harsh ] && echo VB_CHAIN=harsh ) $( [ "$c" = _odd ] && echo VB_ODD=1 ) \
    nice -n 10 $MPY ../director_model/real_ear.py decode --procs 2 --threads 4 --order r12)
done
fi
if [ -z "${SKIP_GEN:-}" ]; then
(cd model_server && STEER_TTS=off ARC_EAR=off ARC_META=off OS_TTS=off \
  nice -n 10 $MPY -m uvicorn app.main:app --host 127.0.0.1 --port "$MS_PORT" > "../$RUN/ms.log" 2>&1 &)
stop_ms() { kill $(lsof -tiTCP:"$MS_PORT" -sTCP:LISTEN 2>/dev/null) 2>/dev/null || true; }
trap stop_ms EXIT
until curl -sf "localhost:$MS_PORT/health" >/dev/null; do sleep 2; done
export MODEL_SERVER_URL=http://127.0.0.1:$MS_PORT REAL_EAR_CACHE=$C/real_ear_r12
pids=()
for i in 0 1 2; do
  nice -n 10 $BPY director_model/gen_sessions.py $GEN --shard "$i/3" > "$DATA/gen_s$i.log" 2>&1 & pids+=($!)
done
SETS=val,test_clean,test_asr,test_real,test_voice_heldout,test_ear,test_h40,test_h40_asr,test_q80,test_q80_asr,test_gold
SETS=$SETS,cls_chatter,cls_echo,cls_offer,cls_panel,cls_help,cls_mode,cls_globe,cls_mishear,cls_roomtalk,cls_video_ctrl
SETS=$SETS,cls_video_echo,cls_prep,cls_prep_roomtalk,cls_voice_echo_os,cls_gesture_cooccur,cls_lesson_new,cls_offers_new
SETS=$SETS,cls_coverage
nice -n 10 $BPY director_model/gen_sessions.py $GEN --only "$SETS" > "$DATA/gen_rest.log" 2>&1 & pids+=($!)
for p in "${pids[@]}"; do wait "$p"; done
for c in harsh odd; do
  nice -n 10 $BPY director_model/gen_sessions.py --out "$DATA" --only "stress_$c" --stress-cache "$C/real_ear_r12_$c" \
    --stress-name "stress_$c" --stress-mode $( [ $c = harsh ] && echo ho || echo items ) > "$DATA/gen_stress_$c.log" 2>&1
done
stop_ms
fi
for size in xl s; do
  nice -n 10 python3 director_model/train.py --data "$DATA" --out "$RUN/$size/cand" --size $size --threads 4 \
    --steps "$STEPS" --fp-exec 0.5 > "$RUN/train_$size.log" 2>&1
  nice -n 10 python3 director_model/gate_r12.py --data "$DATA" --r10 backend/app/director_model \
    --r11 "$R11/runs/2026-11-16-r11/xl/cand" --cand "$RUN/$size/cand" --policy "$POL" --memo "$RUN/memo" \
    --tag "r12$size" --report stress_harsh,stress_odd --out "$RUN/$size/gate_r12.json" > "$RUN/$size/gate_r12.log" 2>&1
done
