#!/usr/bin/env bash
# Round 7 run of the director loop, split so the shared machine is used in parallel (docs/DIRECTOR_LOOP.md):
# train shards + the remaining sets -> merge -> train m and xl -> evaluate both + the shipped weights.
# The gate itself is `python3 director_model/loop.py gate --run <run> --data <data>` per candidate (no --export).
#   MODEL_SERVER_URL=http://127.0.0.1:8291 BACKEND_PY=... bash director_model/run_r7.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${BACKEND_PY:-python3}
DATA=${DATA:-director_model/data/ds_r7}
RUN=${RUN:-director_model/runs/2026-11-14-r7}
SHARDS=${SHARDS:-6}
TRAIN=${TRAIN:-2400}
GEN="--out $DATA --train $TRAIN --val 200 --test 200 --hf-p 0.3 --cls-n 160"
mkdir -p "$RUN" "$DATA"
echo "[gen] $(date +%T) $SHARDS train shards + val / cls / test_real"
pids=()
for i in $(seq 0 $((SHARDS - 1))); do
  $PY director_model/gen_sessions.py $GEN --shard "$i/$SHARDS" > "$DATA/gen_s$i.log" 2>&1 & pids+=($!)
done
ONLY="val,test_real,cls_chatter,cls_echo,cls_offer,cls_panel,cls_help,cls_mode,cls_globe,cls_mishear,cls_roomtalk"
$PY director_model/gen_sessions.py $GEN --only "$ONLY" > "$DATA/gen_rest.log" 2>&1 & pids+=($!)
for p in "${pids[@]}"; do wait "$p"; done
$PY director_model/gen_sessions.py --out "$DATA" --merge "$SHARDS"
rm -f "$DATA"/train_s*.npz "$DATA"/train_s*.meta.jsonl
echo "[train] $(date +%T) m + xl"
python3 director_model/train.py --data "$DATA" --out "$RUN/m/cand" --size m --threads 3 > "$RUN/train_m.log" 2>&1 &
pm=$!
python3 director_model/train.py --data "$DATA" --out "$RUN/xl/cand" --size xl --threads 3 > "$RUN/train_xl.log" 2>&1 &
px=$!
wait $pm; wait $px
echo "[eval] $(date +%T)"
python3 director_model/evaluate.py --data "$DATA" --weights backend/app/director_model --out "$RUN/eval_shipped.json" > "$RUN/eval_shipped.log" 2>&1 &
pe=$!
python3 director_model/evaluate.py --data "$DATA" --run "$RUN/m/cand" --out "$RUN/m/eval_candidate.json" > "$RUN/m/eval.log" 2>&1 &
p1=$!
python3 director_model/evaluate.py --data "$DATA" --run "$RUN/xl/cand" --out "$RUN/xl/eval_candidate.json" > "$RUN/xl/eval.log" 2>&1 &
p2=$!
wait $pe; wait $p1; wait $p2
cp "$RUN/eval_shipped.json" "$RUN/m/eval_shipped.json"
cp "$RUN/eval_shipped.json" "$RUN/xl/eval_shipped.json"
echo "[done] $(date +%T)"
