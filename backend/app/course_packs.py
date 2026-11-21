"""Course packs: download, remove and list the courses that are not built in (docs/COURSES.md §4.2, decision 6).

A course pack is a first-run asset like the crew audio: `course_<id>` in desktop/assets.manifest.json (the same Dropbox
folder and catalog), a deterministic ustar tar with a version, a sha256 for the tar and a size for every file, built by
scripts/asset_pack.py from the course's source (backend/data/courses/<id>.json + courses/<id>/). It installs into the
assets folder as `<assets>/course_<id>/` (course.json + data files + media/), where app/courses.py finds it.

Who does the work:
  - The desktop app (desktop/main/assets.js) downloads, verifies and installs, exactly as for every other asset. The
    backend asks through the flag files it already uses for the Steer voice: `<assets>/.want/<asset>` to download now;
    `<assets>/.remove/<asset>` to delete (assets.js store.remove: move aside, delete, drop the state record). While it
    downloads, `<assets>/.active/<asset>` exists; a failed download leaves `<assets>/.failed/<asset>` with the reason.
  - With no desktop app (a dev checkout, the tests, the iPad shell), the backend installs a pack from a local file: the
    tar in COURSE_PACK_SRC (its file name from the manifest), sha256-checked, extracted and swapped in atomically. The
    iPad has no asset downloader (docs/IPAD.md): its course tars come in the app bundle (COURSE_PACKS_DIR).

Rules: the Moon is built in and never removed; removing the course being played switches to the Moon first; progress
stays (patches are keyed by course, only Reset's "erase progress too" erases them); School network mode blocks a
download whose host is not allowed and says so plainly; a download needs room for the tar and its unpacked files.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import courses

router = APIRouter()
PREFIX = "course_"
SCHOOL_MSG = "School network mode is on, so this course can't download here. Import the offline pack from a USB stick."
DISK_MSG = "Not enough free space for this course: it needs {need} MB, {free} MB free."
NO_SOURCE_MSG = "This course isn't ready to download yet."


def catalog(manifest: Path | None = None) -> list[dict]:
    """The course packs the asset catalog lists: [{id, asset, title, size, unpacked_size, version, sha256, file, url}]."""
    try:
        m = json.loads((manifest or courses.ASSETS_MANIFEST).read_text())
    except (OSError, ValueError):
        return []
    out = []
    for a in m.get("assets", []) if isinstance(m, dict) else []:
        if isinstance(a, dict) and str(a.get("id", "")).startswith(PREFIX) and courses.ID.match(a["id"][len(PREFIX):]):
            out.append({"id": a["id"][len(PREFIX):], "asset": a["id"], "title": a.get("title") or a["id"],
                        "size": int(a.get("size") or 0), "unpacked_size": int(a.get("unpacked_size") or a.get("size") or 0),
                        "version": str(a.get("version") or "1"), "sha256": a.get("sha256"), "file": a.get("file"),
                        "url": a.get("url"), "urls": sources(a), "files": a.get("files") or [],
                        "min_version": str(a["min_version"]) if a.get("min_version") else None,
                        "card": card(a["id"][len(PREFIX):], a.get("course"))})
    return out


CARD_KEYS = ("program", "subject", "grades")


def card(cid: str, meta: dict | None = None) -> dict:
    """What a course says about itself before it is downloaded (the first-run pick, Course storage): {program,
    subject, grades}. From the catalog entry's `course` (scripts/asset_pack.py copies it from the source manifest),
    else from the source manifest in a dev checkout (backend/data/courses/<id>.json), else empty."""
    m = meta if isinstance(meta, dict) else None
    if m is None:
        try:
            m = json.loads((courses.DIR / f"{cid}.json").read_text())
        except (OSError, ValueError):
            m = {}
    return {k: str(m[k]) for k in CARD_KEYS if isinstance(m.get(k), (str, int)) and str(m[k]).strip()}


def entry(cid: str) -> dict | None:
    return next((e for e in catalog() if e["id"] == cid), None)


def _assets() -> Path | None:
    """The desktop app's assets folder (it runs the downloads), or None (no desktop: the local fallback)."""
    from .config import settings
    if os.environ.get("COURSE_PACK_SRC"):
        return None
    env = os.environ.get("ASSETS_DIR")
    return Path(env) if env else settings.assets_dir


def _flag(kind: str, asset: str) -> Path | None:
    a = _assets()
    return a / kind / asset if a else None


def free_bytes() -> int | None:
    d = courses.packs_dir()
    while d is not None and not d.exists() and d.parent != d:
        d = d.parent
    try:
        return shutil.disk_usage(d).free if d is not None else None
    except OSError:
        return None


def sources(a: dict) -> list[str]:
    """The pack's download links in order: its url, then its mirrors (the same tar; desktop/main/assets.js sourcesOf)."""
    out = []
    for u in [a.get("url"), *(a.get("mirrors") if isinstance(a.get("mirrors"), list) else [])]:
        if isinstance(u, str) and u and u not in out:
            out.append(u)
    return out


def school_blocks(urls: str | list[str] | None) -> bool:
    """School network mode is on and none of this pack's hosts (url or a mirror) is on its allow-list
    (docs/SCHOOL_IT.md)."""
    if isinstance(urls, str) or urls is None:
        urls = [urls] if urls else []
    try:
        from . import netgate
        pol = netgate.policy()
        if not pol.get("school_network"):
            return False
        return not any(netgate.url_allowed(u, pol) for u in urls)
    except Exception:   # noqa: BLE001  (unknown policy: let the downloader's own gate decide)
        return False


def state(e: dict) -> dict:
    """{state: installed | downloading | queued | failed | missing, reason?, progress?} for one catalog entry. An installed
    pack may be updating (the desktop app re-downloads an outdated one: `updating`, `progress`) or `outdated` (older than
    the catalog's min_version, waiting for a download)."""
    courses.courses.cache_clear()
    if courses.get(e["id"]) is not None:
        out = {"state": "installed"}
        f = _flag(".active", e["asset"])
        if f is not None and f.exists():
            out["updating"] = True
            if progress(f) is not None:
                out["progress"] = progress(f)
        elif outdated(e):
            out["outdated"] = True
        return out
    for kind, st in ((".active", "downloading"), (".want", "queued")):
        f = _flag(kind, e["asset"])
        if f is not None and f.exists():
            return {"state": st} | ({"progress": progress(f)} if st == "downloading" and progress(f) is not None else {})
    f = _flag(".failed", e["asset"])
    if f is not None and f.exists():
        try:
            why = f.read_text(encoding="utf-8").strip()[:200]
        except OSError:
            why = ""
        return {"state": "failed", "reason": why or "The download stopped. Try again."}
    return {"state": "missing"}


def _vkey(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in str(v or "0").split("."))


def installed_version(asset: str) -> str | None:
    """The version the desktop app installed (its <assets>/state.json record, desktop/main/assets.js commit), or None."""
    a = _assets()
    if a is None:
        return None
    try:
        rec = json.loads((a / "state.json").read_text(encoding="utf-8")).get(asset)
        return str(rec.get("version") or "1") if isinstance(rec, dict) else None
    except (OSError, ValueError, AttributeError):
        return None


def outdated(e: dict) -> bool:
    """The installed copy is older than the catalog's min_version for it: the desktop app's check() calls it "outdated"
    and replaces it on request (a .want flag), keeping the old copy in use until the new one is verified."""
    v = installed_version(e["asset"]) if e.get("min_version") else None
    return v is not None and _vkey(v) < _vkey(e["min_version"])


def progress(f: Path) -> float | None:
    """How far a download is, 0..1: the desktop app writes "<done> <total>" bytes into .active/<asset> (assets.js)."""
    try:
        done, total = (int(x) for x in f.read_text(encoding="utf-8").split()[:2])
    except (OSError, ValueError):
        return None
    return round(min(1.0, max(0.0, done / total)), 3) if total > 0 else None


def downloadable() -> bool:
    """Can this computer download a course pack at all: the desktop app runs the downloads, or a local source folder
    (dev, tests). The iPad shell has neither (docs/IPAD.md), so it never offers one."""
    return _assets() is not None or bool(os.environ.get("COURSE_PACK_SRC"))


def listing() -> dict:
    act = courses.active()
    packs = []
    for e in catalog():
        row = ({k: e[k] for k in ("id", "title", "size", "unpacked_size", "version")} | e["card"] | state(e)
               | {"active": e["id"] == act, "blocked": school_blocks(e["urls"])})
        if row["active"]:
            row["videos"] = _videos()   # [course switch] the playing course's own videos: saved, or on their way
        packs.append(row)
    from .config import settings
    return {"managed": _assets() is not None, "downloadable": downloadable(), "free_bytes": free_bytes(), "packs": packs,
            "school_network": any(p["blocked"] for p in packs) or _school_on(), "assets_dir": bool(settings.assets_dir)}


def _school_on() -> bool:
    try:
        from . import netgate
        return bool(netgate.policy().get("school_network"))
    except Exception:   # noqa: BLE001
        return False


def _videos() -> dict | None:
    try:
        from . import video
        return video.course_progress()
    except Exception:   # noqa: BLE001  (a video hiccup never hides Course storage)
        return None


# ------------------------------------------------------------------------------------------- course switch
def ensure_active() -> dict | None:
    """[course switch] The course just switched to: if its pack is outdated (or its update is not on disk yet), ask the
    desktop app for it now (the .want flag, as Course storage does: same sha256 check and mirrors). The course keeps
    playing from the copy it has meanwhile. Nothing is asked in School network mode when the pack's hosts are blocked,
    and nothing without the desktop app (the local fallback installs on request only). -> the pack's state, or None."""
    cid = courses.active()
    e = entry(cid) if cid != courses.DEFAULT else None
    a = _assets()
    if e is None or a is None:
        return None
    st = state(e)
    if st.get("outdated") and not school_blocks(e["urls"]):
        (a / ".failed" / e["asset"]).unlink(missing_ok=True)
        (a / ".want").mkdir(parents=True, exist_ok=True)
        (a / ".want" / e["asset"]).write_text("")
        st = {"state": "installed", "updating": True}
    return st


def on_course_change() -> None:
    """courses.on_change hook (main.py)."""
    try:
        ensure_active()
    except OSError:
        pass


def active_progress() -> dict:
    """[course switch] What the course being played still needs on this computer, for the course chip and Course
    storage: {course, pack: state | None, videos: app/video.py course_progress(), busy, progress}. busy: something is
    downloading right now (its pack update, or its videos). The Moon: nothing, ever (busy false)."""
    cid = courses.active()
    e = entry(cid) if cid != courses.DEFAULT else None
    pk = state(e) if e is not None else None
    vids = _videos() or {"state": "none", "total": 0, "ready": 0, "progress": 1.0}
    pack_busy = bool(pk and (pk.get("updating") or pk["state"] in ("downloading", "queued")))
    vid_busy = vids.get("state") in ("downloading", "paused")
    prog = (pk or {}).get("progress") if pack_busy else vids.get("progress")
    return {"course": cid, "pack": pk, "videos": vids, "busy": pack_busy or vid_busy,
            "progress": prog if isinstance(prog, (int, float)) else None}


# ------------------------------------------------------------------------------------------- the local fallback
def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _safe_members(t: tarfile.TarFile):
    for m in t.getmembers():
        n = m.name
        if n.startswith("/") or ".." in Path(n).parts or not (m.isfile() or m.isdir()):
            raise ValueError(f"unsafe path in the course pack: {n}")
        yield m


def install_local(e: dict, tar: Path) -> Path:
    """Verify and install a pack tar into the packs folder (atomic: stage, move the old copy aside, swap)."""
    if e.get("sha256") and _sha256(tar) != e["sha256"]:
        raise ValueError("The course file is damaged (sha256). Download it again.")
    packs = courses.packs_dir()
    if packs is None:
        raise ValueError("No folder for course packs on this computer.")
    packs.mkdir(parents=True, exist_ok=True)
    staging, dst, old = packs / f".staging-{e['asset']}", packs / e["asset"], packs / f".old-{e['asset']}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    with tarfile.open(tar) as t:
        t.extractall(staging, members=list(_safe_members(t)))
    for f in e.get("files") or []:
        p = staging / f["path"]
        if not p.is_file() or p.stat().st_size != f["size"]:
            shutil.rmtree(staging, ignore_errors=True)
            raise ValueError(f"The course file is incomplete: {f['path']}.")
    shutil.rmtree(old, ignore_errors=True)
    if dst.exists():
        os.replace(dst, old)
    os.replace(staging, dst)
    shutil.rmtree(old, ignore_errors=True)
    return dst


def remove_local(asset: str) -> bool:
    packs = courses.packs_dir()
    if packs is None or not (packs / asset).exists():
        return False
    old = packs / f".old-{asset}"
    shutil.rmtree(old, ignore_errors=True)
    os.replace(packs / asset, old)
    shutil.rmtree(old, ignore_errors=True)
    return True


# ------------------------------------------------------------------------------------------- the API
@router.get("/api/courses/packs")
def list_packs():
    return listing()


@router.get("/api/courses/active/progress")
def course_progress():
    return active_progress()


@router.post("/api/courses/packs/{cid}/get")
def get_pack(cid: str):
    e = entry(cid)
    if e is None:
        raise HTTPException(404, "That course isn't in the catalog.")
    st = state(e)
    if st["state"] in ("installed", "downloading", "queued"):
        return st
    if school_blocks(e["urls"]):
        raise HTTPException(403, SCHOOL_MSG)
    need, free = e["size"] + e["unpacked_size"], free_bytes()
    if free is not None and free < need:
        raise HTTPException(507, DISK_MSG.format(need=-(-need // 1_000_000), free=free // 1_000_000))
    a = _assets()
    if a is not None:   # the desktop app downloads it (assets.js watchWanted), like the Steer voice
        for kind in (".failed",):
            f = a / kind / e["asset"]
            f.unlink(missing_ok=True)
        (a / ".want").mkdir(parents=True, exist_ok=True)
        (a / ".want" / e["asset"]).write_text("")
        return {"state": "queued"}
    src = Path(os.environ.get("COURSE_PACK_SRC", "")) / str(e.get("file") or "")
    if not os.environ.get("COURSE_PACK_SRC") or not src.is_file():
        raise HTTPException(404, NO_SOURCE_MSG)
    try:
        install_local(e, src)
    except ValueError as x:
        raise HTTPException(422, str(x))
    courses.courses.cache_clear()
    return {"state": "installed"}


@router.post("/api/courses/packs/{cid}/remove")
def remove_pack(cid: str):
    m = courses.get(cid)
    if cid == courses.DEFAULT or (m is not None and m.get("status") != "pack"):
        raise HTTPException(400, "The Moon is built in. It stays.")
    e = entry(cid)
    asset = e["asset"] if e else PREFIX + cid
    if courses.active() == cid:
        courses.set_active(courses.DEFAULT)          # never pull the floor out from under the course being played
    a = _assets()
    if a is not None:
        try:   # out of the registry at once; the desktop app deletes it and its state record (store.remove)
            if (a / asset).exists():
                os.replace(a / asset, a / f".old-{asset}")
        except OSError:
            pass   # Windows: a file is held; the desktop app's remove retries
        for kind in (".want", ".failed"):
            (a / kind / asset).unlink(missing_ok=True)
        (a / ".remove").mkdir(parents=True, exist_ok=True)
        (a / ".remove" / asset).write_text("")
    else:
        remove_local(asset)
    courses.reload_all()
    return {"state": "missing", "active": courses.active()}
