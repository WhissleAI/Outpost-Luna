#!/usr/bin/env bash
# Transcribes every clip in media/audio with word timestamps into transcripts/.
# Uses mlx_whisper (Apple Silicon). Stand-in for Arc Transcriber until that is wired in.
set -euo pipefail
cd "$(dirname "$0")/../data"
mkdir -p transcripts
for f in media/audio/*.mp3; do
  out=transcripts/$(basename "${f%.mp3}").json
  [ -s "$out" ] && continue
  echo "✎ $f"
  mlx_whisper "$f" --model mlx-community/whisper-large-v3-turbo --word-timestamps True \
    --output-format json --output-dir transcripts --language en >/dev/null
done
echo "Now run: make index"
