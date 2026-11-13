"""Word-timed, diarized transcripts for the crew clips with Deepgram nova-3 (pre-recorded).

Writes data/transcripts_dg/<stem>.json in the same shape `build_index.words_of()` reads:
  {"source": "deepgram nova-3", "keyterms": [...], "speakers": n,
   "segments": [{"start", "end", "speaker", "text", "words": [{"word","start","end","speaker","confidence"}]}]}
One segment per Deepgram utterance. Skips clips that already have a transcript (pass --force to redo).

  uv run python -m pipeline.transcribe_deepgram [--force] [stem ...]
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.config import settings  # noqa: E402
from app.gazetteer import Gazetteer  # noqa: E402
from app.keyterms import clip_keyterms  # noqa: E402

URL = "https://api.deepgram.com/v1/listen"
PARAMS = {"model": "nova-3", "language": "en", "diarize": "true", "smart_format": "true", "punctuate": "true",
          "utterances": "true"}
OUT = settings.data_dir / "transcripts_dg"


def normalize(resp: dict, keyterms: list[str] | None = None) -> dict:
    """Deepgram response -> {"source", "segments": [{"words": [...]}]} (one segment per utterance)."""
    def word(w: dict) -> dict:
        return {"word": w.get("punctuated_word") or w["word"], "start": round(w["start"], 3),
                "end": round(w["end"], 3), "speaker": w.get("speaker", 0), "confidence": round(w["confidence"], 3)}

    res = resp["results"]
    utts = res.get("utterances") or []
    if utts:
        segs = [{"start": round(u["start"], 3), "end": round(u["end"], 3), "speaker": u.get("speaker", 0),
                 "text": u.get("transcript", ""), "words": [word(w) for w in u.get("words", [])]} for u in utts]
    else:
        alt = res["channels"][0]["alternatives"][0]
        segs = [{"text": alt.get("transcript", ""), "words": [word(w) for w in alt.get("words", [])]}]
    speakers = sorted({w["speaker"] for s in segs for w in s["words"]})
    return {"source": "deepgram nova-3", "keyterms": keyterms or [], "speakers": len(speakers),
            "duration": resp.get("metadata", {}).get("duration"), "segments": segs}


def transcribe(audio: Path, keyterms: list[str], key: str) -> dict:
    params = list(PARAMS.items()) + [("keyterm", k) for k in keyterms]
    r = httpx.post(URL, params=params, content=audio.read_bytes(), timeout=300,
                   headers={"Authorization": f"Token {key}", "Content-Type": "audio/mpeg"})
    if r.status_code >= 400:
        raise RuntimeError(f"Deepgram {r.status_code}: {r.text[:300]}")
    return normalize(r.json(), keyterms)


def main(argv: list[str]) -> None:
    if not settings.deepgram_api_key:
        sys.exit("DEEPGRAM_API_KEY is not set (put it in .env).")
    force = "--force" in argv
    only = {a for a in argv if not a.startswith("--")}
    gaz = Gazetteer(settings.data_dir / "places.json")
    clips = json.loads((settings.data_dir / "clips_manifest.json").read_text())["clips"]
    OUT.mkdir(parents=True, exist_ok=True)
    todo = []
    for c in clips:
        audio = settings.data_dir / "media/audio" / f"{c['stem']}.mp3"
        dest = OUT / f"{c['stem']}.json"
        if (only and c["stem"] not in only and c["id"] not in only) or (dest.exists() and not force):
            continue
        if not audio.exists():
            print(f"skip {c['stem']}: no audio (run `make data`)")
            continue
        todo.append((c, audio, dest))

    def run(job):
        c, audio, dest = job
        try:
            d = transcribe(audio, clip_keyterms(c["title"], gaz), settings.deepgram_api_key)
        except Exception as e:  # noqa: BLE001 - report and keep going
            return f"FAIL {c['stem']}: {e}"
        dest.write_text(json.dumps(d, ensure_ascii=False))
        n = sum(len(s["words"]) for s in d["segments"])
        return f"{c['id']:<36} {n:>5} words  {d['speakers']} speakers  {len(d['segments']):>3} utterances"

    with ThreadPoolExecutor(4) as pool:
        for line in pool.map(run, todo):
            print(line)
    print(f"done: {len(todo)} clips -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
