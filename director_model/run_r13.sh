#!/usr/bin/env bash
# Round 13 of the director loop: round 12's jobs re-decoded with the libarc ABI 2 ear (the ABI 2 read-outs replayed by
# backend/app/director_model/replay.py into the e13_* slots), plus the round-13 items (pools_r13.py: lesson answers,
# room talk naming a control); 275 features.
#   relist (round 12's jobs, today's names lists) + r13 jobs -> decode (5 procs, nice; our playback fed as the ear's
#   reference) -> generate every set (+ cls_lesson_answer) -> train xl and s -> gate_r13.py vs what ships (r12 routed)
# Shipping is a separate, deliberate step (export.py, gate_r13.py --cand-weights on the export, the backend suite).
#   BACKEND_PY=... MODEL_PY=... R12=.../wt-moon-r12/director_model bash director_model/run_r13.sh
set -euo pipefail
cd "$(dirname "$0")/.."
BPY=${BACKEND_PY:-backend/.venv/bin/python}
MPY=${MODEL_PY:-model_server/.venv/bin/python}
abs() { python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$1"; }
BPY=$(abs "$BPY"); MPY=$(abs "$MPY")
R12=${R12:?round 12 director_model dir (its decode caches)}
DATA=${DATA:-director_model/data/ds_r13}
RUN=${RUN:-director_model/runs/$(date +%Y-%m-%d)-r13}
MS_PORT=${MS_PORT:-8361}
STEPS=${STEPS:-2200}
POL='{"veto": null, "ignore_min_words": 3}'
C=$PWD/director_model/cache
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1} VECLIB_MAXIMUM_THREADS=${OMP_NUM_THREADS:-1}
GEN="--out $DATA --train 2400 --val 200 --test 200 --hf-p 0.3 --cls-n 160 --r8-p 0.35 --cov-sessions 1200 --cov-heldout 10"
GEN="$GEN --r13-p 0.6"
mkdir -p "$RUN" "$DATA"
if [ -z "${SKIP_DECODE:-}" ]; then
for c in "" _harsh _odd; do
  REAL_EAR_CACHE=$C/real_ear_r13$c $BPY director_model/real_ear.py relist --src "$R12/cache/real_ear_r12$c"
done
(cd director_model && REAL_EAR_CACHE=$C/real_ear_r13 $BPY real_ear.py r13 --train 2400 --val 200 --hf-p 0.3 \
  --r13-p 0.6 --cls-n 160)
# ARC_SPACE_DIR: the pinned ear (176d324, sha-verified at load); ARC_LIB: libarc ABI 2 built from this checkout. The
# ear runs with the app's defaults (EAR_LIVE=1, EAR_ALMOST=1, EAR_NBEST=0 as shipped since 0.3.10).
: "${ARC_SPACE_DIR:?}" "${ARC_LIB:?}"
for c in "" _harsh _odd; do
  (cd model_server && env REAL_EAR_CACHE=$C/real_ear_r13$c OMP_NUM_THREADS=2 \
    $( [ "$c" = _harsh ] && echo VB_CHAIN=harsh ) $( [ "$c" = _odd ] && echo VB_ODD=1 ) \
    nice -n 10 $MPY ../director_model/real_ear.py decode --procs 5 --threads 2 --order r13 > "../$RUN/decode$c.log" 2>&1)
done
fi
if [ -z "${SKIP_GEN:-}" ]; then
# Arc Tagger 0.5 (ARCTAG_LIB: `make desktop-arctag`, or desktop/build/arctag); the embedder is not loaded, as in round 12
: "${ARCTAG_LIB:?}"
(cd model_server && STEER_TTS=off ARC_EAR=off ARC_META=off OS_TTS=off \
  nice -n 10 $MPY -m uvicorn app.main:app --host 127.0.0.1 --port "$MS_PORT" > "../$RUN/ms.log" 2>&1 &)
stop_ms() { kill $(lsof -tiTCP:"$MS_PORT" -sTCP:LISTEN 2>/dev/null) 2>/dev/null || true; }
trap stop_ms EXIT
until curl -sf "localhost:$MS_PORT/health" >/dev/null; do sleep 2; done
export MODEL_SERVER_URL=http://127.0.0.1:$MS_PORT REAL_EAR_CACHE=$C/real_ear_r13
pids=()
for i in 0 1 2; do
  nice -n 10 $BPY director_model/gen_sessions.py $GEN --shard "$i/3" > "$DATA/gen_s$i.log" 2>&1 & pids+=($!)
done
SETS=val,test_clean,test_asr,test_real,test_voice_heldout,test_ear,test_h40,test_h40_asr,test_q80,test_q80_asr,test_gold
SETS=$SETS,cls_chatter,cls_echo,cls_offer,cls_panel,cls_help,cls_mode,cls_globe,cls_mishear,cls_roomtalk,cls_video_ctrl
SETS=$SETS,cls_video_echo,cls_prep,cls_prep_roomtalk,cls_voice_echo_os,cls_gesture_cooccur,cls_lesson_new,cls_offers_new
SETS=$SETS,cls_coverage,cls_lesson_answer
nice -n 10 $BPY director_model/gen_sessions.py $GEN --only "$SETS" > "$DATA/gen_rest.log" 2>&1 & pids+=($!)
for p in "${pids[@]}"; do wait "$p"; done
for c in harsh odd; do
  nice -n 10 $BPY director_model/gen_sessions.py --out "$DATA" --only "stress_$c" --stress-cache "$C/real_ear_r13_$c" \
    --stress-name "stress_$c" --stress-mode $( [ $c = harsh ] && echo ho || echo items ) > "$DATA/gen_stress_$c.log" 2>&1
done
stop_ms
fi
for size in xl s; do
  nice -n 10 python3 director_model/train.py --data "$DATA" --out "$RUN/$size/cand" --size $size --threads 4 \
    --steps "$STEPS" --fp-exec 0.5 > "$RUN/train_$size.log" 2>&1
  nice -n 10 python3 director_model/gate_r13.py --data "$DATA" --ship backend/app/director_model \
    --cand "$RUN/$size/cand" --policy "$POL" --memo "$RUN/memo" --tag "r13$size" --report stress_harsh,stress_odd \
    --out "$RUN/$size/gate_r13.json" > "$RUN/$size/gate_r13.log" 2>&1
done
