"""Model files checked against the asset manifest's sha256 at load (issue #85), not only when they were downloaded.

    verify_asset("ear", home)      # home: the asset's folder (manifest paths are relative to it: "nft2/config.json")

Where the expected sha256 come from, first match wins:
  1. <assets>/state.json (desktop/main/assets.js, the folder above `home`): the record of the asset installed there,
     when its file list carries sha256 (the manifest's `files`, copied at install). Exactly the installed version.
  2. the asset manifest (ARC_ASSETS_MANIFEST, else the app's bundled copy, else desktop/assets.manifest.json in a
     clone): the asset's `files` sha256, or its `fallback.files` (the ear's per-file Hugging Face list). Used only when
     the installed version is that manifest's (state.json absent, or its tar sha256 equal to the manifest's).
  3. none: the asset loads, reported `verified: false` with the reason (a dev folder of another revision, ...).

A file that differs (missing, other size, other sha256) refuses the load with ModelIntegrityError. In the desktop app
(the folder is one assets.js installed: state.json lists it) the damaged files are moved aside (`<name>.damaged`) so
the app's own check (sizes) sees the asset as corrupt, and <assets>/.want/<id> asks the app to download it again at
once (desktop/main/main.js watchWanted); the next launch repairs it in any case (a required asset that is not
"installed" is fetched before the servers start). In a clone the message says how to fetch it again.

ARC_VERIFY=off skips the check (dev only; /health then says `verified: false`, reason "ARC_VERIFY=off").
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MS = Path(__file__).resolve().parents[1]           # model_server/ (a clone) or <resources>/app/model_server (the app)
CHUNK = 4 << 20
DEV_FETCH = {"ear": "make ear-model (or delete the folder and run it again)",
             "tagger": "copy a fresh Arc Tagger model folder (ARCTAG_MODEL_DIR)",
             "embedder": "make models"}


class ModelIntegrityError(RuntimeError):
    """A model file does not match the manifest's sha256: the model is not loaded."""


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(CHUNK):
            h.update(b)
    return h.hexdigest()


def manifest_paths() -> list[Path]:
    env = os.environ.get("ARC_ASSETS_MANIFEST")
    return ([Path(env)] if env else []) + [MS.parents[1] / "assets.manifest.json",      # the app: <resources>/
                                            MS.parent / "desktop/assets.manifest.json"]  # a clone


def _files_with_sha(entries) -> dict[str, tuple[int | None, str]] | None:
    out = {}
    for f in entries or []:
        if not isinstance(f, dict) or not f.get("path"):
            continue
        if not f.get("sha256"):
            return None
        out[str(f["path"])] = (f.get("size"), str(f["sha256"]).lower())
    return out or None


def expected(asset_id: str, home: Path) -> tuple[dict[str, tuple[int | None, str]] | None, str]:
    """({relative path: (size, sha256)}, where from) for the asset installed in `home`; (None, reason) when unknown."""
    state_rec = None
    sp = home.parent / "state.json"
    if home.name == asset_id and sp.is_file():
        try:
            state_rec = json.loads(sp.read_text(encoding="utf-8")).get(asset_id)
        except (OSError, ValueError):
            state_rec = None
    if state_rec:
        got = _files_with_sha(state_rec.get("files"))
        if got:
            return got, f"{sp} ({asset_id} v{state_rec.get('version', '1')})"
    for mp in manifest_paths():
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        a = next((x for x in m.get("assets", []) if x.get("id") == asset_id), None)
        if a is None:
            continue
        if state_rec and state_rec.get("sha256") != a.get("sha256"):
            return None, (f"installed {asset_id} v{state_rec.get('version', '?')} is not the version in {mp.name} and "
                          "its install record has no per-file sha256")
        got = _files_with_sha(a.get("files")) or _files_with_sha((a.get("fallback") or {}).get("files"))
        if got:
            return got, f"{mp} ({asset_id} v{a.get('version', '1')})"
        return None, f"{mp} lists no per-file sha256 for {asset_id}"
    return None, "no asset manifest found (ARC_ASSETS_MANIFEST)"


def _check(home: Path, rel: str, size: int | None, sha: str) -> str | None:
    p = home.joinpath(*rel.split("/"))
    try:
        st = p.stat()
    except OSError:
        return f"{rel}: missing"
    if size is not None and st.st_size != size:
        return f"{rel}: {st.st_size} bytes, expected {size}"
    got = sha256_file(p)
    return None if got == sha else f"{rel}: sha256 {got[:12]}…, expected {sha[:12]}…"


def verify_asset(asset_id: str, home: Path, title: str | None = None, repair: bool = True) -> dict:
    """Check every listed file of the asset in `home`. -> {"verified", "source"|"reason", "files", "verify_s"};
    raises ModelIntegrityError (after asking the app for a fresh copy, when it is the app's) on any mismatch."""
    title = title or asset_id
    if os.environ.get("ARC_VERIFY", "on").strip().lower() in ("off", "0", "false", "no"):
        return {"verified": False, "reason": "ARC_VERIFY=off"}
    t = time.perf_counter()
    want, src = expected(asset_id, home)
    if want is None:
        return {"verified": False, "reason": src}
    with ThreadPoolExecutor(max_workers=min(4, len(want))) as ex:   # hashlib releases the GIL on large reads
        bad = [b for b in ex.map(lambda kv: _check(home, kv[0], *kv[1]), sorted(want.items())) if b]
    secs = round(time.perf_counter() - t, 2)
    if not bad:
        return {"verified": True, "source": src, "files": len(want), "verify_s": secs}
    raise ModelIntegrityError(f"{title} is damaged: {'; '.join(bad[:4])}{' …' if len(bad) > 4 else ''} "
                              f"(checked against {src}). " + _repair(asset_id, home, [b.split(':')[0] for b in bad], repair))


def _repair(asset_id: str, home: Path, rels: list[str], repair: bool) -> str:
    """Hand a damaged app asset back to the app for a fresh download; the message's last sentence says what happens."""
    assets = home.parent
    managed = home.name == asset_id and (assets / "state.json").is_file()
    if not managed:
        return f"Fetch it again: {DEV_FETCH.get(asset_id, 'download the asset again')}."
    if not repair:
        return "Outpost Luna downloads it again on its next launch."
    for rel in rels:
        p = home.joinpath(*rel.split("/"))
        try:
            if p.exists():
                os.replace(p, p.with_name(p.name + ".damaged"))   # the app's size check now calls it corrupt
        except OSError:
            pass
    try:
        (assets / ".want").mkdir(exist_ok=True)
        (assets / ".want" / asset_id).write_text("")
    except OSError:
        return "Outpost Luna downloads it again on its next launch."
    return "Outpost Luna is downloading it again now; restart the app when it is done (the next launch also repairs it)."
