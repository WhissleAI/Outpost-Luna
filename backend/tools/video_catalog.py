"""Check every URL in backend/data/video/catalog.json against the live NASA servers (docs/MEDIA.md).

    uv run python tools/video_catalog.py            # HEAD every file, caption and poster; sizes; caption cues
    uv run python tools/video_catalog.py --pin      # also download the pinned files (resumable) and write their
                                                    # exact `bytes` and `sha256` into the catalog
    uv run python tools/video_catalog.py --derive   # (re)build the NASA pack_files: download each one's NASA original
                                                    # (origin_url, checked against origin_sha256), re-encode it with
                                                    # ffmpeg (`derive`), grab a poster, then pin bytes + sha256
    uv run python tools/video_catalog.py --pack [--only a,b]   # the video pack's lighter copies of pinned NASA files
                                                    # (`pack`: {derive, bytes, sha256}): the NASA file (VIDEO_ORIG_SRC,
                                                    # the dev cache, or nasa.gov; checked against its sha256) re-encoded
                                                    # with pack.derive into LOCAL_DIR/pack/<id>.mp4, bytes + sha256 pinned

Never run by the app; a maintainer runs it when the catalog changes. YouTube ids are checked with YouTube's public
oEmbed endpoint (the uploader must be a NASA channel, or the channel NON_NASA_YOUTUBE names for that id).

pack_file items live in LOCAL_DIR (backend/data/video/local, not in git; VIDEO_LOCAL_SRC overrides): <id>.mp4 and,
when the entry says so, <id>.vtt (captions: true) and <id>.jpg (poster: true). scripts/asset_pack.py puts them in the
video pack. A third-party video used with permission is dropped in there by hand (docs/MEDIA.md); --pin records it.
Downloads go to the dev video cache (CACHE_DIR/video), never to an installed app's folder.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import video  # noqa: E402

UA = {"User-Agent": video.UA}
LOCAL_DIR = Path(os.environ.get("VIDEO_LOCAL_SRC", Path(__file__).resolve().parents[1] / "data/video/local"))


def head(c: httpx.Client, url: str) -> tuple[int, int | None]:
    try:
        r = c.head(url)
        n = r.headers.get("content-length")
        return r.status_code, int(n) if n else None
    except httpx.HTTPError:
        return 0, None


def derive(c: httpx.Client, v: dict) -> None:
    """NASA original -> LOCAL_DIR/<id>.mp4 (+ .jpg): the re-encode the video pack carries."""
    ff = shutil.which("ffmpeg")
    if not ff:
        sys.exit("--derive needs ffmpeg on PATH")
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    src = LOCAL_DIR / (v["id"] + ".orig" + Path(v["origin_url"]).suffix)
    if not (src.exists() and video.file_sha256(src) == v.get("origin_sha256")):
        print(f"    downloading {v['origin_url']}", flush=True)
        with c.stream("GET", v["origin_url"]) as r, open(src, "wb") as f:
            r.raise_for_status()
            for b in r.iter_bytes(1 << 20):
                f.write(b)
    got = video.file_sha256(src)
    if v.get("origin_sha256") and got != v["origin_sha256"]:
        sys.exit(f"{v['id']}: the NASA original changed (sha256 {got}); check it, then update origin_sha256")
    v["origin_sha256"] = got
    out = LOCAL_DIR / f"{v['id']}.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-i", str(src), *shlex.split(v["derive"]), str(out)], check=True)
    if v.get("poster"):
        t = min(20, max(1, int(v.get("duration_s", 10) * 0.3)))
        subprocess.run([ff, "-v", "error", "-y", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-q:v", "4",
                        "-vf", "scale=-2:576", str(LOCAL_DIR / f"{v['id']}.jpg")], check=True)
    src.unlink()
    print(f"    derived {out} ({out.stat().st_size / 1e6:.1f} MB)")


def original(c: httpx.Client, v: dict) -> Path:
    """A pinned NASA file, checked against the catalog's sha256: VIDEO_ORIG_SRC (e.g. an installed app's video pack),
    else the dev video cache, else downloaded into the dev cache."""
    name = video.names(v)["video"]
    for d in [Path(x) for x in os.environ.get("VIDEO_ORIG_SRC", "").split(os.pathsep) if x] + [video.cache().root]:
        p = d / name
        if p.is_file() and p.stat().st_size == v["bytes"] and video.file_sha256(p) == v["sha256"]:
            return p
    print(f"    downloading {v['file_url']}", flush=True)
    return video.cache().download(v["file_url"], name, size=v["bytes"], sha256=v["sha256"], pinned=True, client=c)


def pack(c: httpx.Client, v: dict) -> None:
    """NASA file -> LOCAL_DIR/pack/<id>.mp4 with pack.derive (the video pack's copy; captions and poster unchanged)."""
    ff = shutil.which("ffmpeg")
    if not ff:
        sys.exit("--pack needs ffmpeg on PATH")
    out = LOCAL_DIR / "pack" / f"{v['id']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    src = original(c, v)
    tmp = out.with_name(out.stem + ".part.mp4")
    subprocess.run([ff, "-v", "error", "-y", "-i", str(src), *shlex.split(v["pack"]["derive"]), str(tmp)], check=True)
    tmp.replace(out)
    v["pack"]["bytes"], v["pack"]["sha256"] = out.stat().st_size, video.file_sha256(out)
    print(f"    pack copy {out} ({v['bytes'] / 1e6:.1f} -> {out.stat().st_size / 1e6:.1f} MB)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true", help="download the pinned files and record bytes + sha256")
    ap.add_argument("--derive", action="store_true", help="rebuild the NASA pack_files from their originals (ffmpeg)")
    ap.add_argument("--pack", action="store_true", help="rebuild the video pack's lighter copies of NASA files (ffmpeg)")
    ap.add_argument("--only", default="", help="--pack: these ids only (comma list)")
    a = ap.parse_args()
    path = video.catalog_path()
    items = json.loads(path.read_text(encoding="utf-8"))
    bad = 0
    only = {x for x in a.only.split(",") if x}
    if a.pack:
        with httpx.Client(follow_redirects=True, timeout=60.0, headers=UA, verify=video.tls()) as c:
            for v in items:
                if v.get("pack") and (not only or v["id"] in only):
                    pack(c, v)
        path.write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        probs = video.validate(items)
        for p in probs:
            print("catalog:", p)
        return 1 if probs else 0
    with httpx.Client(follow_redirects=True, timeout=60.0, headers=UA, verify=video.tls()) as c:
        for v in items:
            if v["source"] == "youtube":
                r = c.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/watch?v={v['youtube_id']}", "format": "json"})
                who = r.json().get("author_name", "?") if r.status_code == 200 else f"HTTP {r.status_code}"
                want = video.NON_NASA_YOUTUBE.get(v["youtube_id"])
                ok = r.status_code == 200 and (who == want if want else who.startswith("NASA"))
                bad += not ok
                print(f"{'ok ' if ok else 'BAD'} {v['id']:<20} youtube {v['youtube_id']}  {who}")
                continue
            if v["source"] == "pack_file":
                if a.derive and v.get("nasa") is not False:
                    derive(c, v)
                p = LOCAL_DIR / f"{v['id']}.mp4"
                if a.derive or (a.pin and p.exists()):
                    v["bytes"], v["sha256"] = p.stat().st_size, video.file_sha256(p)
                ok = p.exists() and p.stat().st_size == v.get("bytes") and video.file_sha256(p) == v.get("sha256")
                extra = "" if v.get("nasa") is False else f"  origin {head(c, v['origin_url'])[0]}"
                for f, ext in (("captions", "vtt"), ("poster", "jpg")):
                    if v.get(f) and not (LOCAL_DIR / f"{v['id']}.{ext}").exists():
                        ok, extra = False, extra + f"  MISSING {v['id']}.{ext}"
                bad += not ok
                print(f"{'ok ' if ok else 'BAD'} {v['id']:<20} pack_file {p} {v.get('bytes')} bytes{extra}")
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
    if a.pin or a.derive:
        path.write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    probs = video.validate(items)
    for p in probs:
        print("catalog:", p)
    pinned = sum(v.get("bytes", 0) for v in items if v.get("prefetch"))
    print(f"pinned videos: {sum(1 for v in items if v.get('prefetch'))}, {pinned / 1e6:.1f} MB (the video pack, before "
          "captions and posters)")
    return 1 if bad or probs else 0


if __name__ == "__main__":
    sys.exit(main())
