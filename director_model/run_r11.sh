#!/usr/bin/env bash
# Round 11 of the director loop: the Mac voice bank as the "real-voice" data (voice_bank.py; owner decision: no real kid
# recordings exist, so the Mac's own voices + noise, decoded by the real ear, are treated as real).
#   jobs (--r11: Mac-voice train / val / held-out-voice / echo-bank jobs) -> decode (<= 2 procs, nice)
#   -> generate train shards + train_cov + val + test_voice_heldout (every other set: ds_r10's, symlinked, unchanged)
#   -> train xl (r10's recipe) and s -> gate_vs.py: each class vs the rules AND vs the shipped r10 weights, every set
# Nothing is exported here: shipping weights is a separate, deliberate step (export.py, then gate_vs.py on the export).
#   ARC_SPACE_DIR=... ARC_LIB=... BACKEND_PY=... MODEL_PY=... MS_PORT=8341 R10_DATA=.../ds_r10 bash director_model/run_r11.sh
set -euo pipefail
cd "$(dirname "$0")/.."
BPY=${BACKEND_PY:-backend/.venv/bin/python}
MPY=${MODEL_PY:-model_server/.venv/bin/python}
DATA=${DATA:-director_model/data/ds_r11b}
R10_DATA=${R10_DATA:?ds_r10 (its test / class sets are reused as they are)}
RUN=${RUN:-director_model/runs/$(date +%Y-%m-%d)-r11}
MS_PORT=${MS_PORT:-8341}
STEPS=${STEPS:-2200}
POL='{"veto": null, "ignore_min_words": 3}'
export REAL_EAR_CACHE=${REAL_EAR_CACHE:-$PWD/director_model/cache/real_ear_r11}   # r9/r10 decodes symlinked in
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-1} VECLIB_MAXIMUM_THREADS=${OMP_NUM_THREADS:-1}
GEN="--out $DATA --train 2400 --val 200 --test 200 --hf-p 0.3 --cls-n 160 --r8-p 0.35 --cov-sessions 1200 --cov-heldout 10"
mkdir -p "$RUN" "$DATA"
for f in "$R10_DATA"/test_* "$R10_DATA"/cls_*; do ln -sf "$f" "$DATA/"; done
if [ -z "${SKIP_GEN:-}" ]; then
nice -n 10 $BPY director_model/real_ear.py jobs --budget 900 --val-budget 300 --test-budget 500 --hf-p 0.3 --cls-n 160 \
  --train 2400 --val 200 --r11 --r11-train 4500 --r11-variants 800 --ho-sessions 55
(cd model_server && EAR_PARTIAL_EVERY_S=3.0 OMP_NUM_THREADS=4 nice -n 10 \
  $MPY ../director_model/real_ear.py decode --procs 2 --threads 4 --order r11)
(cd model_server && STEER_TTS=off ARC_EAR=off ARC_META=off OS_TTS=off \
  nice -n 10 $MPY -m uvicorn app.main:app --host 127.0.0.1 --port "$MS_PORT" > "../$RUN/ms.log" 2>&1 &)
stop_ms() { kill $(lsof -tiTCP:"$MS_PORT" -sTCP:LISTEN 2>/dev/null) 2>/dev/null || true; }
trap stop_ms EXIT
until curl -sf "localhost:$MS_PORT/health" >/dev/null; do sleep 2; done
export MODEL_SERVER_URL=http://127.0.0.1:$MS_PORT
pids=()
for i in 0 1 2; do
  nice -n 10 $BPY director_model/gen_sessions.py $GEN --shard "$i/3" > "$DATA/gen_s$i.log" 2>&1 & pids+=($!)
done
nice -n 10 $BPY director_model/gen_sessions.py $GEN --only val,test_voice_heldout > "$DATA/gen_rest.log" 2>&1 & pids+=($!)
for p in "${pids[@]}"; do wait "$p"; done
stop_ms
fi
for size in xl s; do
  nice -n 10 python3 director_model/train.py --data "$DATA" --out "$RUN/$size/cand" --size $size --threads 3 \
    --steps "$STEPS" --fp-exec 0.5 > "$RUN/train_$size.log" 2>&1
  nice -n 10 python3 director_model/gate_vs.py --data "$DATA" --base backend/app/director_model --cand "$RUN/$size/cand" \
    --policy "$POL" --out "$RUN/$size/gate_vs.json" > "$RUN/$size/gate_vs.log" 2>&1
done
