"""Build the first-run asset pack: one .tar per downloadable asset, the offline zip, and desktop/assets.manifest.json.

    make asset-pack                         # = uv run --project backend python scripts/asset_pack.py
    python scripts/asset_pack.py --check    # only verify desktop/build/assets against the manifest
    make ear-model                          # dev: just download the ear into model_server/models/arc-space

The desktop installer ships code only (Electron, the embedded Python, libarc, ONNX Runtime via the Python wheel, tiny
fallbacks). Everything big is an ASSET that the app downloads on first launch (desktop/main/assets.js) from the public
links in the manifest, or imports from the offline zip ("Import offline pack": one file from Dropbox or a USB stick).

Assets (id -> what, where it is installed under <per-user data>/assets/<id>/, required or optional):
    ear        Arc Transcriber Space nft2/ + LICENSE + NOTICE (CC BY-NC 4.0)   required   ARC_SPACE_DIR=<ear>/nft2
    tagger     Arc Tagger v0.3 int8 + tokenizer + meta + LICENSE + NOTICE     required   ARCTAG_MODEL_DIR
    embedder   all-MiniLM-L6-v2 int8 ONNX + tokenizer + NOTICE (Apache-2.0)    required   EMBED_MODEL_DIR
    voice      the recorded Nora voice pack (clips/, index.json, lines.json)   required   VOICE_PACK_DIR
    crew       trimmed Artemis II crew audio (audio/*.mp3, trim.json), NASA    optional   MEDIA_AUDIO_DIR
    videos     the pinned NASA videos (<id>.mp4/.vtt/.jpg), NASA               optional   VIDEO_PACK_DIR

Each tar is deterministic (sorted, mtime 0, uid/gid 0), so rebuilding from the same sources gives the same sha256 and
the manifest's public links stay valid. A tar whose sha256 changes loses its url (null) until scripts/upload_assets.py
uploads it again. Sources (env overrides in brackets):
    ear       [ARC_SPACE_SRC] a folder with LICENSE, NOTICE, nft2/ (WhissleAI/arc-transcriber-space at EAR_REVISION);
              default model_server/models/arc-space; missing files are downloaded from Hugging Face at EAR_REVISION
    tagger    [ARCTAG_MODEL_DIR] default ~/Desktop/work/whissle/headstart/models/arctag
    embedder  [EMBED_MODEL_DIR] default model_server/models/minilm (model_server/tools/export_embedder.py)
    voice     backend/data/voice_pack
    crew      backend/data/media/desktop (make media-desktop)
    videos    [VIDEO_CACHE_SRC] an app video cache folder whose files match the catalog's sha256, else nasa.gov
Stdlib only, except the videos' SRT -> WebVTT conversion, which reuses backend/app/video.py (run under the backend env).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("ASSET_OUT", ROOT / "desktop/build/assets"))
MANIFEST = ROOT / "desktop/assets.manifest.json"
PACK = "v2"
OFFLINE_ZIP = f"outpost-luna-assets-{PACK}.zip"
EAR_REPO = "WhissleAI/arc-transcriber-space"
EAR_REVISION = "176d32449b070893739db21e15ea5320af005a68"
HF = f"https://huggingface.co/{EAR_REPO}/resolve/{EAR_REVISION}/"
EAR_FILES = [
    "LICENSE", "NOTICE", "NAMES_LISTS.md",
    "nft2/adapters.safetensors", "nft2/config.json", "nft2/model.q4.safetensors", "nft2/tags.json",
    "nft2/decoder/LICENSE", "nft2/decoder/config.json", "nft2/decoder/generation_config.json",
    "nft2/decoder/model.safetensors", "nft2/decoder/processor_config.json", "nft2/decoder/tokenizer.json",
    "nft2/decoder/tokenizer_config.json",
    "nft2/encoder_onnx/config.json", "nft2/encoder_onnx/decoder.onnx", "nft2/encoder_onnx/encoder.onnx",
    "nft2/encoder_onnx/encoder.weights", "nft2/encoder_onnx/encoder_first.onnx", "nft2/encoder_onnx/frontend.npz",
    "nft2/encoder_onnx/joint_enc.onnx", "nft2/encoder_onnx/joint_net.onnx", "nft2/encoder_onnx/tokenizer.model",
    "nft2/encoder_onnx/tokens.txt",
]
MINILM_NOTICE = ("all-MiniLM-L6-v2 (sentence-transformers), Apache License 2.0, https://huggingface.co/sentence-transformers/"
                 "all-MiniLM-L6-v2. Exported to ONNX and int8-quantised by model_server/tools/export_embedder.py.\n")
NASA_NOTICE = ("NASA media. NASA audio, images and video are generally not subject to copyright in the United States "
               "(https://www.nasa.gov/nasa-brand-center/images-and-media/). Not endorsed by NASA. Credits per item: "
               "backend/data/index/clips.json (crew audio) and backend/data/video/catalog.json (videos).\n")
UA = "outpost-luna-asset-pack"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fetch(url: str, dst: Path, want_sha: str | None = None) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        for b in iter(lambda: r.read(1 << 20), b""):
            f.write(b)
    if want_sha and sha256_file(tmp) != want_sha:
        tmp.unlink()
        sys.exit(f"sha256 mismatch for {url}")
    tmp.replace(dst)


# ------------------------------------------------------------------------------------------------- sources
def src_ear() -> list[tuple[str, Path | bytes]]:
    base = Path(os.environ.get("ARC_SPACE_SRC", ROOT / "model_server/models/arc-space"))
    for rel in EAR_FILES:
        if not (base / rel).exists():
            print(f"  ear: downloading {rel} from Hugging Face @ {EAR_REVISION[:7]}", flush=True)
            fetch(HF + rel, base / rel)
    return [(rel, base / rel) for rel in EAR_FILES]


def src_tagger():
    d = Path(os.environ.get("ARCTAG_MODEL_DIR", Path.home() / "Desktop/work/whissle/headstart/models/arctag"))
    return [(f, d / f) for f in ("arctag_int8.onnx", "arctag_meta.json", "tokenizer.json", "LICENSE", "NOTICE")]


def src_embedder():
    d = Path(os.environ.get("EMBED_MODEL_DIR", ROOT / "model_server/models/minilm"))
    return [("model.int8.onnx", d / "model.int8.onnx"), ("tokenizer.json", d / "tokenizer.json"),
            ("NOTICE", MINILM_NOTICE.encode())]


def src_voice():
    d = ROOT / "backend/data/voice_pack"
    return [("index.json", d / "index.json"), ("lines.json", d / "lines.json")] + \
        [(f"clips/{p.name}", p) for p in sorted((d / "clips").glob("*.mp3"))]


def src_crew():
    d = ROOT / "backend/data/media/desktop"
    if not (d / "trim.json").exists():
        sys.exit("backend/data/media/desktop/trim.json missing: run `make data media-desktop` first")
    return [("trim.json", d / "trim.json"), ("NOTICE", NASA_NOTICE.encode())] + \
        [(f"audio/{p.name}", p) for p in sorted((d / "audio").glob("*.mp3"))]


def src_videos():
    cat = json.loads((ROOT / "backend/data/video/catalog.json").read_text(encoding="utf-8"))
    pins = [v for v in cat if v.get("prefetch") and v.get("source") == "nasa_file"]
    have = Path(os.environ.get("VIDEO_CACHE_SRC", Path.home() / "Library/Application Support/Outpost Luna/cache/video"))
    stage = OUT / "src-videos"
    out: list = [("NOTICE", NASA_NOTICE.encode())]
    for v in pins:
        vid, mp4 = v["id"], stage / f"{v['id']}.mp4"
        if not (mp4.exists() and sha256_file(mp4) == v["sha256"]):
            if (have / mp4.name).exists() and sha256_file(have / mp4.name) == v["sha256"]:
                stage.mkdir(parents=True, exist_ok=True)
                mp4.write_bytes((have / mp4.name).read_bytes())
            else:
                print(f"  videos: downloading {vid} ({v['bytes'] / 1e6:.0f} MB) from NASA", flush=True)
                fetch(v["file_url"], mp4, v["sha256"])
        out.append((mp4.name, mp4))
        for ext, key in (("vtt", "captions_url"), ("jpg", "poster_url")):
            p = stage / f"{vid}.{ext}"
            if not p.exists():
                if (have / p.name).exists():
                    p.write_bytes((have / p.name).read_bytes())
                elif v.get(key):
                    fetch(v[key], p)
                    if ext == "vtt":   # SRT -> WebVTT, exactly as the app's cache stores it
                        sys.path.insert(0, str(ROOT / "backend"))
                        from app.video import has_cues, srt_to_vtt
                        vtt = srt_to_vtt(p.read_bytes().decode("utf-8", "replace"))
                        if has_cues(vtt):
                            p.write_text(vtt, encoding="utf-8")
                        else:
                            p.unlink()
            if p.exists():
                out.append((p.name, p))
    return out


# id, title, required, source, licence files, env var + subfolder the app points at
ASSETS = [
    ("ear", "Speech model (Arc Transcriber Space)", True, src_ear, ["LICENSE", "NOTICE"], "ARC_SPACE_DIR", "nft2"),
    ("tagger", "Safety tagger (Arc Tagger)", True, src_tagger, ["LICENSE", "NOTICE"], "ARCTAG_MODEL_DIR", ""),
    ("embedder", "Knowledge search (MiniLM)", True, src_embedder, ["NOTICE"], "EMBED_MODEL_DIR", ""),
    ("voice", "Nora's recorded voice", True, src_voice, [], "VOICE_PACK_DIR", ""),
    ("crew", "Artemis II crew audio", False, src_crew, ["NOTICE"], "MEDIA_AUDIO_DIR", ""),
    ("videos", "NASA videos", False, src_videos, ["NOTICE"], "VIDEO_PACK_DIR", ""),
]


def tarinfo(name: str, size: int) -> tarfile.TarInfo:
    ti = tarfile.TarInfo(name)
    ti.size, ti.mtime, ti.mode, ti.uid, ti.gid, ti.uname, ti.gname = size, 0, 0o644, 0, 0, "", ""
    return ti


def write_tar(dst: Path, files: list[tuple[str, Path | bytes]]) -> list[dict]:
    """ustar, regular files only, sorted: the app's tar reader (desktop/main/assets.js) reads exactly this."""
    listing = []
    tmp = dst.with_name(dst.name + ".part")
    with tarfile.open(tmp, "w", format=tarfile.USTAR_FORMAT) as t:
        for rel, src in sorted(files, key=lambda x: x[0]):
            if isinstance(src, bytes):
                t.addfile(tarinfo(rel, len(src)), io.BytesIO(src))
                listing.append({"path": rel, "size": len(src)})
            else:
                if not src.exists():
                    sys.exit(f"missing source for {dst.name}: {src}")
                n = src.stat().st_size
                with open(src, "rb") as f:
                    t.addfile(tarinfo(rel, n), f)
                listing.append({"path": rel, "size": n})
    tmp.replace(dst)
    return listing


def build(only: set[str] | None) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    old = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {"assets": []}
    old_by = {a["id"]: a for a in old.get("assets", [])}
    assets = []
    for aid, title, req, src, lic, env, sub in ASSETS:
        prev = old_by.get(aid)
        if only and aid not in only and prev:
            assets.append(prev)
            continue
        t = time.time()
        files = src()
        stem = f"{aid}-{EAR_REVISION[:7]}" if aid == "ear" else aid
        fname = f"outpost-luna-{PACK}-{stem}.tar"
        listing = write_tar(OUT / fname, files)
        sha, size = sha256_file(OUT / fname), (OUT / fname).stat().st_size
        url = prev.get("url") if prev and prev.get("sha256") == sha else None
        a = {"id": aid, "title": title, "required": req, "file": fname, "url": url, "sha256": sha, "size": size,
             "unpacked_size": sum(x["size"] for x in listing), "n_files": len(listing), "env": env, "subdir": sub,
             "licence": lic, "files": listing}
        if aid == "ear":   # until the Dropbox upload, or if it ever fails: the same files straight from Hugging Face
            a["source"] = {"repo": EAR_REPO, "revision": EAR_REVISION, "licence": "CC BY-NC 4.0"}
            a["fallback"] = {"kind": "files", "base": HF,
                             "files": [{"path": x["path"], "size": x["size"],
                                        "sha256": sha256_file(dict(files)[x["path"]])} for x in listing]}
        assets.append(a)
        print(f"  {aid:9s} {size / 1e6:8.1f} MB  {len(listing):4d} files  {sha[:12]}  {'url kept' if url else 'NEW (upload)'}"
              f"  {time.time() - t:.0f} s", flush=True)
    m = {"schema": 1, "pack": PACK,
         "note": "First-run assets for Outpost Luna (scripts/asset_pack.py; downloaded by desktop/main/assets.js).",
         "folder": f"/Outpost Luna/assets/{PACK}/", "assets": assets,
         "offline_pack": old.get("offline_pack") or {"file": OFFLINE_ZIP, "url": None, "sha256": None, "size": None}}
    return m


def write_zip(m: dict) -> dict:
    """The offline pack: every asset tar + this manifest, stored (the tars are already dense)."""
    dst = OUT / OFFLINE_ZIP
    tmp = dst.with_name(dst.name + ".part")
    inner = {k: v for k, v in m.items() if k != "offline_pack"}
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        zi = zipfile.ZipInfo("assets.manifest.json", date_time=(1980, 1, 1, 0, 0, 0))
        z.writestr(zi, json.dumps(inner, indent=1) + "\n")
        for a in m["assets"]:
            zi = zipfile.ZipInfo(a["file"], date_time=(1980, 1, 1, 0, 0, 0))
            with open(OUT / a["file"], "rb") as f, z.open(zi, "w", force_zip64=a["size"] > 2**31) as w:
                for b in iter(lambda: f.read(1 << 20), b""):
                    w.write(b)
    tmp.replace(dst)
    sha, size = sha256_file(dst), dst.stat().st_size
    prev = m.get("offline_pack") or {}
    return {"file": OFFLINE_ZIP, "url": prev.get("url") if prev.get("sha256") == sha else None, "sha256": sha, "size": size}


def check(m: dict) -> int:
    bad = 0
    for a in m["assets"] + [m["offline_pack"]]:
        p = OUT / a["file"]
        ok = p.exists() and p.stat().st_size == a["size"] and sha256_file(p) == a["sha256"]
        print(f"  {'ok ' if ok else 'BAD'} {a['file']}  url={'yes' if a.get('url') else 'NO'}")
        bad += not ok
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated asset ids to rebuild (others keep their manifest entry)")
    ap.add_argument("--no-zip", action="store_true", help="skip the offline zip")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--fetch-ear", action="store_true",
                    help="only download the ear model (dev: model_server/models/arc-space, or ARC_SPACE_SRC)")
    a = ap.parse_args()
    if a.fetch_ear:
        src_ear()
        print(f"ear model ready: {Path(os.environ.get('ARC_SPACE_SRC', ROOT / 'model_server/models/arc-space'))}/nft2")
        return
    if a.check:
        sys.exit(1 if check(json.loads(MANIFEST.read_text())) else 0)
    print(f"asset pack {PACK} -> {OUT}", flush=True)
    m = build(set(a.only.split(",")) if a.only else None)
    if not a.no_zip:
        m["offline_pack"] = write_zip(m)
        print(f"  offline   {m['offline_pack']['size'] / 1e6:8.1f} MB  {OFFLINE_ZIP}")
    req = sum(x["size"] for x in m["assets"] if x["required"])
    print(f"  required download {req / 1e6:.0f} MB, optional {sum(x['size'] for x in m['assets'] if not x['required']) / 1e6:.0f} MB")
    MANIFEST.write_text(json.dumps(m, indent=1) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
