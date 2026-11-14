"""Gather every model file the desktop app needs into desktop/resources/models/ (make desktop-models). Stdlib only.

    python desktop/scripts/gather_models.py                    # auto: local files if all present, else the package
    python desktop/scripts/gather_models.py --from package     # download the public model package (fresh machine)
    python desktop/scripts/gather_models.py --from local       # copy from this dev machine (HF cache + checkouts)
    python desktop/scripts/gather_models.py --verify           # check resources/models against desktop/models.lock.json
    python desktop/scripts/gather_models.py --pack             # write desktop/build/outpost-luna-models-vN.tar (to publish)

Layout (what the Electron main process points the model server at; docs/DESKTOP.md):
    arctag/            Arc Tagger v0.3 int8 graph + tokenizer + meta          -> ARCTAG_MODEL_DIR
    arc-v1.1/mini/     Arc v1.1 Mini (heads, trunk, Moonshine Streaming tiny) -> ARC_META_WEIGHTS
    steer-tts-edge/    Steer TTS Edge v1 (onnx/, front/, voices, config) + director.bin -> STEER_TTS_MODEL / STEER_DIRECTOR
    minilm/            all-MiniLM-L6-v2 int8 ONNX + tokenizer                -> EMBED_MODEL_DIR

The package is the one source every build can reach: a tar of exactly this folder, pinned by sha256 below, and every
file is then checked again against desktop/models.lock.json. Hugging Face is not used: two of the four models (Arc Tagger
v0.3, Steer TTS Edge v1) are no longer on the Hub in the versions the app runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "desktop/resources"
OUT = RES / "models"
BUILD = ROOT / "desktop/build"
LOCK = ROOT / "desktop/models.lock.json"
HOME = Path.home()

# The public model package (v1 = models.lock.json as committed). A new package needs a new URL, sha256 and lock file.
PACKAGE = {
    "name": "outpost-luna-models-v1.tar",
    "url": "https://www.dropbox.com/scl/fi/h1pbtl1w9jxe0cn6ie247/outpost-luna-models-v1.tar"
           "?rlkey=wkqo5r8dh2ednpb9agzdjz3yk&dl=1",
    "sha256": "c9cb030dd01a3ac3987b1ad9323e185e3b18020c6d2b5805b91db7e232bfc707",
    "size": 119352320,
}


# ------------------------------------------------------------------------------------------------- local (dev machine)
def hf_cache() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    return Path(os.environ.get("HF_HOME", HOME / ".cache/huggingface")) / "hub"


def snap(repo: str, rev: str | None = None) -> Path | None:
    s = hf_cache() / f"models--{repo.replace('/', '--')}" / "snapshots"
    if rev and (s / rev).exists():
        return s / rev
    found = sorted(s.iterdir(), key=lambda p: p.stat().st_mtime) if s.exists() else []
    return found[-1] if found else None


HEADSTART = HOME / "Desktop/work/whissle/headstart"
STEER_REPO = Path(os.environ.get("STEER_REPO", ROOT.parent / "steer-tts"))   # sibling checkout
ARC_REV = "6f637153ea4953d81811e68168cd29572316d32b"
MINILM_NOTICE = ("all-MiniLM-L6-v2 (sentence-transformers), Apache License 2.0, https://huggingface.co/sentence-transformers/"
                 "all-MiniLM-L6-v2. Exported to ONNX and int8-quantised by model_server/tools/export_embedder.py.\n")


def local_sources() -> dict[str, list[tuple[str, Path]]] | None:
    """dest folder -> [(dest relative path, source)], or None when this machine does not have them all."""
    arc, steer = snap("WhissleAI/arc-v1.1", ARC_REV), snap("WhissleAI/steer-tts-edge")
    if arc is None or steer is None:
        return None
    tag = Path(os.environ.get("ARCTAG_MODEL_DIR", HEADSTART / "models/arctag"))
    minilm = Path(os.environ.get("EMBED_MODEL_DIR", ROOT / "model_server/models/minilm"))
    out = {
        "arctag": [(f, tag / f) for f in ("arctag_int8.onnx", "arctag_meta.json", "tokenizer.json", "LICENSE", "NOTICE")],
        "arc-v1.1": [("LICENSE", arc / "LICENSE"), ("NOTICE", arc / "NOTICE")]
                    + [(p.relative_to(arc).as_posix(), p) for p in sorted((arc / "mini").rglob("*")) if p.is_file()],
        "steer-tts-edge": [(p.relative_to(steer).as_posix(), p) for p in sorted(steer.rglob("*")) if p.is_file()]
                          + [("director.bin", STEER_REPO / "c/models/steer-tts-edge/director.bin")],
        "minilm": [("model.int8.onnx", minilm / "model.int8.onnx"), ("tokenizer.json", minilm / "tokenizer.json")],
    }
    return out if all(src.exists() for files in out.values() for _, src in files) else None


def gather_local(srcs):
    shutil.rmtree(OUT, ignore_errors=True)
    for folder, files in srcs.items():
        for rel, src in files:
            dst = OUT / folder / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src.resolve(), dst)          # dereference HF cache symlinks
    (OUT / "minilm/NOTICE").write_text(MINILM_NOTICE)


# ------------------------------------------------------------------------------------------------- package (any machine)
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def download(url: str, dst: Path):
    tmp = dst.with_suffix(dst.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "outpost-luna-build"})
    t, n, last = time.time(), 0, 0.0
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or PACKAGE["size"])
        for b in iter(lambda: r.read(1 << 20), b""):
            f.write(b)
            n += len(b)
            if time.time() - last > 2:
                last = time.time()
                print(f"  {n / 1e6:6.0f} / {total / 1e6:.0f} MB", flush=True)
    tmp.replace(dst)
    print(f"  downloaded {n / 1e6:.0f} MB in {time.time() - t:.0f} s", flush=True)


def gather_package():
    """Download (or reuse desktop/build/<name>, or DESKTOP_MODELS_TAR), check its sha256, unpack into resources/."""
    tar = Path(os.environ.get("DESKTOP_MODELS_TAR", BUILD / PACKAGE["name"]))
    if tar.exists() and sha256(tar) != PACKAGE["sha256"]:
        print(f"{tar} has the wrong sha256; downloading again")
        tar.unlink()
    if not tar.exists():
        BUILD.mkdir(parents=True, exist_ok=True)
        tar = BUILD / PACKAGE["name"]
        print(f"downloading the model package ({PACKAGE['size'] / 1e6:.0f} MB)", flush=True)
        download(os.environ.get("DESKTOP_MODELS_URL", PACKAGE["url"]), tar)
        got = sha256(tar)
        if got != PACKAGE["sha256"]:
            tar.unlink()
            sys.exit(f"model package sha256 mismatch: got {got}, want {PACKAGE['sha256']} (download damaged or replaced)")
    print(f"model package sha256 ok ({tar.name})")
    shutil.rmtree(OUT, ignore_errors=True)
    with tarfile.open(tar) as t:
        for m in t.getmembers():   # only regular files and dirs under models/, nothing absolute or with ..
            if not (m.isfile() or m.isdir()) or m.name.startswith("/") or ".." in Path(m.name).parts \
                    or Path(m.name).parts[0] != "models":
                sys.exit(f"unexpected entry in the model package: {m.name}")
        t.extractall(RES)
    if os.environ.get("DESKTOP_KEEP_MODELS_TAR", "1") == "0":
        tar.unlink()


def pack():
    """Write the package from resources/models (after --verify passes); upload it and update PACKAGE by hand."""
    BUILD.mkdir(parents=True, exist_ok=True)
    dst = BUILD / PACKAGE["name"]
    with tarfile.open(dst, "w", format=tarfile.PAX_FORMAT) as t:
        t.add(OUT, arcname="models", filter=lambda ti: (setattr(ti, "uid", 0), setattr(ti, "gid", 0),
                                                        setattr(ti, "uname", ""), setattr(ti, "gname", ""), ti)[-1])
    print(f"{dst}: {dst.stat().st_size} bytes, sha256 {sha256(dst)}")


# ------------------------------------------------------------------------------------------------- lock
def manifest() -> dict[str, dict]:
    return {p.relative_to(OUT).as_posix(): {"size": p.stat().st_size, "sha256": sha256(p)}
            for p in sorted(OUT.rglob("*")) if p.is_file()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", choices=("auto", "local", "package"), default=os.environ.get("DESKTOP_MODELS_FROM", "auto"))
    ap.add_argument("--verify", action="store_true", help="only compare resources/models with models.lock.json")
    ap.add_argument("--write-lock", action="store_true", help="record resources/models in models.lock.json")
    ap.add_argument("--pack", action="store_true", help="tar resources/models into desktop/build for publishing")
    a = ap.parse_args()
    if a.pack:
        return pack()
    if not a.verify:
        srcs = local_sources() if a.src in ("auto", "local") else None
        if a.src == "local" and srcs is None:
            sys.exit("--from local: this machine does not have every model file (use --from package)")
        if srcs is not None:
            print("models: from this machine's HF cache and checkouts")
            gather_local(srcs)
        else:
            print("models: from the public model package")
            gather_package()
    m = manifest()
    for folder in sorted({k.split("/")[0] for k in m}):
        n = sum(v["size"] for k, v in m.items() if k.startswith(folder + "/"))
        print(f"  {folder:16s} {n / 1e6:7.1f} MB")
    print(f"  {'total':16s} {sum(v['size'] for v in m.values()) / 1e6:7.1f} MB in {OUT}")
    if a.write_lock:
        LOCK.write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
        print(f"wrote {LOCK}")
        return
    want = json.loads(LOCK.read_text())
    bad = sorted(k for k in set(want) | set(m) if want.get(k, {}).get("sha256") != m.get(k, {}).get("sha256"))
    if bad:
        sys.exit(f"models differ from {LOCK.name} ({len(bad)} files): {bad[:12]}")
    print(f"models match {LOCK.name} ({len(m)} files)")


if __name__ == "__main__":
    main()
