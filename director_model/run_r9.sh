#!/usr/bin/env bash
# Round 9 of the director loop: the Director on the NEW ear (Arc Transcriber Space, libarc + ONNX Runtime, #20).
#   jobs -> decode with the shipped ear (model_server/app/arc_ear.EarStream, the same class /v1/stream?ear=arc uses)
#   -> generate (train shards, val, tests, class sets) -> train s + xl (--fp-exec) -> evaluate (full guarded policy
#   AND the ignore-only policy) + the shipped weights -> gate.
# The ear needs its model and libarc: point ARC_SPACE_DIR at an nft2/ folder (e.g. the desktop app's downloaded asset)
# and ARC_LIB at libarc (desktop/build/libarc or the app's Resources/native). Nothing is exported: on a PASS,
# `python3 director_model/loop.py gate --run $RUN/<size> --data $DATA --export` is a separate, deliberate step.
#   ARC_SPACE_DIR=... ARC_LIB=... MS_PORT=8281 PROCS=4 bash director_model/run_r9.sh
# Round 9 as run (2026-11-15) did only the held-out half of this under a 2-hour deadline: see RESULTS.md, Round 9.
set -euo pipefail
cd "$(dirname "$0")/.."
BPY=${BACKEND_PY:-backend/.venv/bin/python}
MPY=${MODEL_PY:-.venv/bin/python}
DATA=${DATA:-director_model/data/ds_r9}
RUN=${RUN:-director_model/runs/$(date +%Y-%m-%d)-r9}
SHARDS=${SHARDS:-4}
PROCS=${PROCS:-4}
MS_PORT=${MS_PORT:-8281}
TRAIN=${TRAIN:-2400}
COV=${COV:-1200}
export REAL_EAR_CACHE=${REAL_EAR_CACHE:-$PWD/director_model/cache/real_ear_r9}
GEN="--out $DATA --train $TRAIN --val 200 --test 200 --hf-p 0.3 --cls-n 160 --r8-p 0.35 --cov-sessions $COV --cov-heldout 10"
python3 director_model/loop.py preflight
mkdir -p "$RUN" "$DATA"
$BPY director_model/coverage.py
$BPY director_model/real_ear.py jobs --budget 900 --val-budget 300 --test-budget 500 --hf-p 0.3 --cls-n 160
# One partial every 3 s: the decode cost is in the re-decodes (each partial re-decodes the open segment); the final
# words and turn events, which the Director's features use, are unchanged.
(cd model_server && EAR_PARTIAL_EVERY_S=${EAR_PARTIAL_EVERY_S:-3.0} OMP_NUM_THREADS=2 \
  $MPY ../director_model/real_ear.py decode --procs "$PROCS" --threads 2 --order test_first)
(cd model_server && STEER_TTS=off ARC_EAR=off ARC_META=off OS_TTS=off \
  $MPY -m uvicorn app.main:app --host 127.0.0.1 --port "$MS_PORT" > /tmp/director-r9-ms.log 2>&1 &)
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
python3 director_model/train.py --data "$DATA" --out "$RUN/s/cand" --size s --threads 3 --steps 2400 > "$RUN/train_s.log" 2>&1
python3 director_model/train.py --data "$DATA" --out "$RUN/xl/cand" --size xl --threads 3 --steps 2800 --fp-exec 0.5 > "$RUN/train_xl.log" 2>&1
python3 director_model/evaluate.py --data "$DATA" --weights backend/app/director_model --out "$RUN/eval_shipped.json"
for s in s xl; do
  python3 director_model/evaluate.py --data "$DATA" --run "$RUN/$s/cand" --out "$RUN/$s/eval_candidate.json"
  python3 director_model/evaluate.py --data "$DATA" --run "$RUN/$s/cand" --ignore-only --out "$RUN/$s/eval_ignore_only.json"
  cp "$RUN/eval_shipped.json" "$RUN/$s/eval_shipped.json"
  python3 director_model/loop.py gate --run "$RUN/$s" --data "$DATA" || true
done
