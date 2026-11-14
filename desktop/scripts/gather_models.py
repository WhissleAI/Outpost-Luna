"""Gather every model file the desktop app needs into desktop/resources/models/ (make desktop-models).

    python desktop/scripts/gather_models.py                    # from this machine (dev checkouts + local HF cache)
    HF_TOKEN=... python desktop/scripts/gather_models.py --from hf          # CI: from Hugging Face, by repo id
    python desktop/scripts/gather_models.py --verify            # check resources/models against desktop/models.lock.json

Layout (what the Electron main process points the model server at; docs/DESKTOP.md):
    arctag/            Arc Tagger v0.3 int8 graph + tokenizer + meta          -> ARCTAG_MODEL_DIR
    arc-v1.1/mini/     Arc v1.1 Mini (heads, trunk, Moonshine Streaming tiny) -> ARC_META_WEIGHTS
    steer-tts-edge/    Steer TTS Edge (onnx/, front/, voices, config) + director.bin -> STEER_TTS_MODEL / STEER_DIRECTOR
    minilm/            all-MiniLM-L6-v2 int8 ONNX + tokenizer                -> EMBED_MODEL_DIR

--from hf has two modes:
  * DESKTOP_MODELS_REPO=<org/repo> (recommended): one private HF repo holding exactly this folder (upload it once with
    --upload). Bit-identical to the dev Mac's bundle.
  * otherwise, each model from its upstream repo at the revision in SOURCES. Arc v1.1 is identical to the local cache;
    Arc Tagger (HF has v0.4.x, the app ships v0.3) and Steer TTS Edge (HF has 2.x; the app's steertts-edge 1.3.0 needs
    the v1 weights) are NOT on HF in the versions the app uses, so --verify fails for them. See docs/DESKTOP.md.
MiniLM is exported locally (model_server/tools/export_embedder.py); from HF it is fetched from the bundle repo only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "desktop/resources/models"
LOCK = ROOT / "desktop/models.lock.json"
HOME = Path.home()


def hf_cache() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    return Path(os.environ.get("HF_HOME", HOME / ".cache/huggingface")) / "hub"


def snap(repo: str, rev: str | None = None) -> Path:
    s = hf_cache() / f"models--{repo.replace('/', '--')}" / "snapshots"
    if rev and (s / rev).exists():
        return s / rev
    found = sorted(s.iterdir(), key=lambda p: p.stat().st_mtime) if s.exists() else []
    if not found:
        sys.exit(f"{repo} is not in the local HF cache ({s})")
    return found[-1]


HEADSTART = HOME / "Desktop/work/whissle/headstart"
STEER_REPO = Path(os.environ.get("STEER_REPO", ROOT.parent / "steer-tts"))   # sibling checkout
ARC_REV = "6f637153ea4953d81811e68168cd29572316d32b"

# dest folder -> list of (dest relative path, local source path)
def local_sources() -> dict[str, list[tuple[str, Path]]]:
    arc = snap("WhissleAI/arc-v1.1", ARC_REV)
    steer = snap("WhissleAI/steer-tts-edge")
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
    return out


# Upstream HF sources for --from hf without a bundle repo: (repo, revision, {dest: path in repo})
SOURCES = {
    "arc-v1.1": ("WhissleAI/arc-v1.1", ARC_REV, None),  # None: allow_patterns mini/*, LICENSE, NOTICE
    "arctag": ("WhissleAI/arc-tagger", "v0.4.1", {"arctag_int8.onnx": "onnx/arctag_int8.onnx",
                                                  "arctag_meta.json": "onnx/arctag_meta.json",
                                                  "tokenizer.json": "onnx/tokenizer.json",
                                                  "LICENSE": "LICENSE", "NOTICE": "NOTICE"}),
    "steer-tts-edge": ("WhissleAI/steer-tts-edge", "main", None),
}
MINILM_NOTICE = ("all-MiniLM-L6-v2 (sentence-transformers), Apache License 2.0, https://huggingface.co/sentence-transformers/"
                 "all-MiniLM-L6-v2. Exported to ONNX and int8-quantised by model_server/tools/export_embedder.py.\n")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def gather_local():
    shutil.rmtree(OUT, ignore_errors=True)
    for folder, files in local_sources().items():
        for rel, src in files:
            if not src.exists():
                sys.exit(f"missing {src}")
            dst = OUT / folder / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src.resolve(), dst)          # dereference HF cache symlinks
    (OUT / "minilm/NOTICE").write_text(MINILM_NOTICE)


def gather_hf():
    from huggingface_hub import hf_hub_download, snapshot_download
    token = os.environ.get("HF_TOKEN")
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    bundle = os.environ.get("DESKTOP_MODELS_REPO")
    if bundle:
        snapshot_download(bundle, revision=os.environ.get("DESKTOP_MODELS_REVISION"), local_dir=OUT, token=token)
        for junk in (OUT / ".cache", OUT / ".gitattributes"):
            shutil.rmtree(junk, ignore_errors=True) if junk.is_dir() else junk.unlink(missing_ok=True)
        return
    for folder, (repo, rev, files) in SOURCES.items():
        dst = OUT / folder
        if files is None:
            pats = ["mini/*", "mini/*/*", "LICENSE", "NOTICE"] if folder == "arc-v1.1" else None
            ign = ["samples/*", "steertts_edge/*", "tests/*", "*.md", "pyproject.toml", ".gitattributes"]
            snapshot_download(repo, revision=rev, local_dir=dst, allow_patterns=pats, ignore_patterns=ign, token=token)
            shutil.rmtree(dst / ".cache", ignore_errors=True)
        else:
            for d, f in files.items():
                p = Path(hf_hub_download(repo, f, revision=rev, token=token))
                (dst / d).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, dst / d)
    print("note: MiniLM is not fetched without DESKTOP_MODELS_REPO; the embedder then fails open (rules + aliases only)")


def manifest() -> dict[str, dict]:
    return {p.relative_to(OUT).as_posix(): {"size": p.stat().st_size, "sha256": sha256(p)}
            for p in sorted(OUT.rglob("*")) if p.is_file()}


def upload(repo: str):
    """Push resources/models to a private HF model repo (creates it). Run by a person, never by CI."""
    from huggingface_hub import HfApi
    api = HfApi(token=os.environ.get("HF_TOKEN"))
    api.create_repo(repo, private=True, exist_ok=True)
    api.upload_folder(repo_id=repo, folder_path=str(OUT), commit_message="Outpost Luna desktop models")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", choices=("local", "hf"), default="local")
    ap.add_argument("--verify", action="store_true", help="only compare resources/models with models.lock.json")
    ap.add_argument("--write-lock", action="store_true", help="record resources/models in models.lock.json")
    ap.add_argument("--upload", metavar="ORG/REPO", help="upload resources/models to a private HF repo")
    a = ap.parse_args()
    if a.upload:
        return upload(a.upload)
    if not a.verify:
        gather_local() if a.src == "local" else gather_hf()
    m = manifest()
    total = sum(v["size"] for v in m.values())
    for folder in sorted({k.split("/")[0] for k in m}):
        n = sum(v["size"] for k, v in m.items() if k.startswith(folder + "/"))
        print(f"  {folder:16s} {n / 1e6:7.1f} MB")
    print(f"  {'total':16s} {total / 1e6:7.1f} MB in {OUT}")
    if a.write_lock:
        LOCK.write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
        print(f"wrote {LOCK}")
    elif LOCK.exists():
        want = json.loads(LOCK.read_text())
        bad = sorted(k for k in set(want) | set(m) if want.get(k, {}).get("sha256") != m.get(k, {}).get("sha256"))
        if bad:
            print(f"models differ from {LOCK.name} ({len(bad)} files): {bad[:12]}")
            if os.environ.get("DESKTOP_MODELS_STRICT", "1") == "1":
                sys.exit(1)
        else:
            print(f"models match {LOCK.name}")


if __name__ == "__main__":
    main()
