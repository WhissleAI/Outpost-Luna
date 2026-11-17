"""Check every URL in backend/data/video/catalog.json against the live NASA servers (docs/MEDIA.md).

    uv run python tools/video_catalog.py            # HEAD every file, caption and poster; sizes; caption cues
    uv run python tools/video_catalog.py --pin      # also download the pinned files (resumable) and write their
                                                    # exact `bytes` and `sha256` into the catalog

Never run by the app; a maintainer runs it when the catalog changes. YouTube ids are checked with YouTube's public
oEmbed endpoint (the uploader must be a NASA channel).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import video  # noqa: E402

UA = {"User-Agent": video.UA}


def head(c: httpx.Client, url: str) -> tuple[int, int | None]:
    try:
        r = c.head(url)
        n = r.headers.get("content-length")
        return r.status_code, int(n) if n else None
    except httpx.HTTPError as e:
        return 0, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true", help="download the pinned files and record bytes + sha256")
    a = ap.parse_args()
    path = video.catalog_path()
    items = json.loads(path.read_text(encoding="utf-8"))
    bad = 0
    with httpx.Client(follow_redirects=True, timeout=30.0, headers=UA, verify=video.tls()) as c:
        for v in items:
            if v["source"] == "youtube":
                r = c.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={v['youtube_id']}", "format": "json"})
                who = r.json().get("author_name", "?") if r.status_code == 200 else f"HTTP {r.status_code}"
                ok = r.status_code == 200 and who.startswith("NASA")
                bad += not ok
                print(f"{'ok ' if ok else 'BAD'} {v['id']:<20} youtube {v['youtube_id']}  {who}")
                continue
            st, n = head(c, v["file_url"])
            ok = st == 200 and (not v.get("bytes") or n == v["bytes"])
            cap = "-"
            if v.get("captions_url"):
                r = c.get(v["captions_url"])
                cues = video.has_cues(video.srt_to_vtt(r.text)) if r.status_code == 200 else False
                cap = f"{r.status_code} {'cues' if cues else 'EMPTY'}"
                ok = ok and cues
            pst = head(c, v["poster_url"])[0] if v.get("poster_url") else "-"
            bad += not ok
            print(f"{'ok ' if ok else 'BAD'} {v['id']:<20} file {st} {n} bytes  captions {cap}  poster {pst}")
            if a.pin and v.get("prefetch") and st == 200:
                v["bytes"] = n
                p = video.cache().download(v["file_url"], video.names(v)["video"], size=n, pinned=True, client=c)
                v["sha256"] = video.file_sha256(p)
                video.fetch_captions(v, True, c)
                video.fetch_poster(v, True, c)
                print(f"    cached {p} sha256 {v['sha256'][:16]}…")
    if a.pin:
        path.write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    probs = video.validate(items)
    for p in probs:
        print("catalog:", p)
    return 1 if bad or probs else 0


if __name__ == "__main__":
    sys.exit(main())
