"""Arc audio metadata for every crew clip: POST /v1/meta on the model server with the clip's Whisper words.

Writes data/index/audio_meta.json = {clip_id: {utterances: [...], awe_peaks: [{t, score}]}}.
Run with the model server up (`make models`): `make meta`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from app.config import settings
from app.local_guard import auth_headers  # noqa: E402  (LUNA_TOKEN, when the model server has one)

DATA = Path(__file__).resolve().parents[1] / "data"
AWE_MIN = 0.5      # utterances at or above this awe score are peaks


def words_for(stem: str) -> list[dict]:
    for d in sorted(DATA.glob("transcripts*")):
        p = d / f"{stem}.json"
        if p.exists():
            tr = json.loads(p.read_text())
            return [{"w": w["word"].strip(), "t0": w["start"], "t1": w["end"]}
                    for s in tr.get("segments", []) for w in s.get("words", []) if w.get("word", "").strip()]
    return []


def main() -> int:
    clips = json.loads((DATA / "clips_manifest.json").read_text())["clips"]
    out, url = {}, settings.model_server_url.rstrip("/") + "/v1/meta"
    with httpx.Client(timeout=300, headers=auth_headers()) as c:
        for clip in clips:
            audio = next((DATA / "media/audio").glob(f"{clip['stem']}.*"), None)
            if audio is None:
                print(f"skip {clip['id']}: no audio", file=sys.stderr)
                continue
            words = words_for(clip["stem"])
            r = c.post(url, files={"audio": (audio.name, audio.read_bytes())},
                       data={"words": json.dumps(words), "domain": "talk", "events": "all"})
            r.raise_for_status()
            m = r.json()
            utts = m["utterances"]
            peaks = sorted(({"t": round((u["t0"] + u["t1"]) / 2, 2), "t0": u["t0"], "t1": u["t1"], "score": u["awe"]}
                            for u in utts if u["awe"] >= AWE_MIN), key=lambda p: -p["score"])
            out[clip["id"]] = {"stem": clip["stem"], "model": m["model"], "domain": m["domain"],
                               "utterances": utts, "awe_peaks": peaks}
            print(f"{clip['id']:12s} {m['audio_s']:6.1f}s  {len(utts):3d} utts  {len(peaks):2d} awe peaks  "
                  f"{m['ms']:7.0f} ms  rtf {m['rtf']}")
    dst = DATA / "index/audio_meta.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, indent=1))
    print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
