#!/usr/bin/env bash
# Round 8 of the director loop, end to end (docs/DIRECTOR_COVERAGE.md, `make director-r8`):
#   inventory -> real-ear decodes (kid turns + OS-voice / Nora echo + video audio) -> generate (train shards, the coverage
#   sweep, val, tests, every cls_* incl. round 8's and cls_coverage) -> train m and xl -> evaluate both + the shipped
#   weights -> gate each (classes whose feature is not merged report but do not gate: PENDING).
# Nothing is exported: on a PASS, `python3 director_model/loop.py gate --run $RUN/<size> --data $DATA --export`
# is a separate, deliberate step (and DIRECTOR_MODEL stays shadow until the owner flips it).
#   MS_PORT=8298 PROCS=3 bash director_model/run_r8.sh
set -euo pipefail
cd "$(dirname "$0")/.."
BPY=${BACKEND_PY:-uv run --project backend python}
MPY=${MODEL_PY:-uv run python}
DATA=${DATA:-director_model/data/ds_r8}
RUN=${RUN:-director_model/runs/$(date +%Y-%m-%d)-r8}
SHARDS=${SHARDS:-4}
PROCS=${PROCS:-3}
MS_PORT=${MS_PORT:-8298}
TRAIN=${TRAIN:-2400}
COV=${COV:-1200}
PENDING=${PENDING-}          # every round-8 feature is merged: every class set gates
export REAL_EAR_CACHE=${REAL_EAR_CACHE:-$PWD/director_model/cache/real_ear_r8}
GEN="--out $DATA --train $TRAIN --val 200 --test 200 --hf-p 0.3 --cls-n 160 --r8-p 0.35 --cov-sessions $COV --cov-heldout 10"
python3 director_model/loop.py preflight
mkdir -p "$RUN" "$DATA"
echo "[inventory] $(date +%T)"
$BPY director_model/coverage.py
echo "[real ear] $(date +%T)"
$BPY director_model/real_ear.py jobs --budget 900 --val-budget 300 --test-budget 500 --hf-p 0.3 --cls-n 160
(cd model_server && EAR_PARTIAL_EVERY_S=1.2 $MPY ../director_model/real_ear.py decode --procs "$PROCS" --threads 2 --order mix)
python3 director_model/loop.py preflight
echo "[model server :$MS_PORT] $(date +%T)"
(cd model_server && EMBED_MODEL_DIR=${EMBED_MODEL_DIR:-$PWD/models/minilm} STEER_TTS=off ARC_EAR=off ARC_META=off OS_TTS=off \
  $MPY -m uvicorn app.main:app --host 127.0.0.1 --port "$MS_PORT" > /tmp/director-r8-ms.log 2>&1 & echo $! > /tmp/director-r8-ms.pid)
stop_ms() { kill $(lsof -tiTCP:"$MS_PORT" -sTCP:LISTEN 2>/dev/null) 2>/dev/null || true; }   # by port: the pid file can be stale
trap stop_ms EXIT
until curl -sf "localhost:$MS_PORT/health" >/dev/null; do sleep 2; done
export MODEL_SERVER_URL=http://127.0.0.1:$MS_PORT
echo "[gen] $(date +%T)"
pids=()
for i in $(seq 0 $((SHARDS - 1))); do
  $BPY director_model/gen_sessions.py $GEN --shard "$i/$SHARDS" > "$DATA/gen_s$i.log" 2>&1 & pids+=($!)
done
$BPY director_model/gen_sessions.py $GEN --only "val,test_clean,test_asr,test_real,test_ear,test_h40,test_h40_asr,test_q80,test_q80_asr,test_gold,cls_chatter,cls_echo,cls_offer,cls_panel,cls_help,cls_mode,cls_globe,cls_mishear,cls_roomtalk,cls_video_ctrl,cls_video_echo,cls_prep,cls_prep_roomtalk,cls_voice_echo_os,cls_gesture_cooccur,cls_lesson_new,cls_offers_new,cls_coverage,cls_coverage_pending,test_log" > "$DATA/gen_rest.log" 2>&1 & pids+=($!)
for p in "${pids[@]}"; do wait "$p"; done
$BPY director_model/gen_sessions.py --out "$DATA" --merge "$SHARDS"
rm -f "$DATA"/train_s*.npz "$DATA"/train_s*.meta.jsonl
stop_ms
echo "[train] $(date +%T) m + xl"
python3 director_model/train.py --data "$DATA" --out "$RUN/m/cand" --size m --threads 3 > "$RUN/train_m.log" 2>&1 &
pm=$!
python3 director_model/train.py --data "$DATA" --out "$RUN/xl/cand" --size xl --threads 3 --fp-exec 0.5 > "$RUN/train_xl.log" 2>&1 &
px=$!
wait $pm; wait $px
echo "[eval] $(date +%T)"
python3 director_model/evaluate.py --data "$DATA" --weights backend/app/director_model --out "$RUN/eval_shipped.json" > "$RUN/eval_shipped.log" 2>&1 &
pe=$!
for s in m xl; do
  python3 director_model/evaluate.py --data "$DATA" --run "$RUN/$s/cand" --out "$RUN/$s/eval_candidate.json" > "$RUN/$s/eval.log" 2>&1 &
done
wait
for s in m xl; do
  cp "$RUN/eval_shipped.json" "$RUN/$s/eval_shipped.json"
  python3 director_model/loop.py gate --run "$RUN/$s" --data "$DATA" --pending "$PENDING" || true
done
echo "[done] $(date +%T): $RUN/{m,xl}/report.md"
