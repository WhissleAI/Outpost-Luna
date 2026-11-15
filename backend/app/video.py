"""NASA video: the catalog, the offline cache and its routes (docs/MEDIA.md).

The catalog (backend/data/video/catalog.json) lists every video the app can show. Two sources:
  nasa_file  a NASA file we download once and play offline in our own player (captions converted to WebVTT)
  youtube    a NASA-channel upload, streamed as a youtube-nocookie embed when online; never cached (YouTube policy III.E.1)

The backend does the downloading, in the dev stack and in the desktop app alike: the renderer only ever talks to our own
origin (desktop/main/permissions.js), and the cache lives in CACHE_DIR/video (the per-user app data folder on the
desktop; backend/data/video_cache in a dev checkout). Downloads resume from a .part file, are checked against the
catalog's size (and sha256 when the catalog has one), then renamed into place. The cache has a cap (VIDEO_CACHE_MB,
default 1024) with least-recently-played eviction; prefetch items are pinned and never evicted. On first online launch
the pinned files download in the background, slowly, pausing while a mission runs or a video streams. Any other NASA
file is streamed through the backend on its first play and cached at the same time ("recently played").

Routes
  GET    /api/video/catalog                  the catalog, each entry + {cached, play_url, captions_src, poster_src}
  GET    /api/video/{id}/available           {"status": "cached" | "online" | "offline"}
  GET    /api/video/{id}/file                the video (Range requests work; cached file, else streamed from NASA)
  GET    /api/video/{id}/captions.vtt        WebVTT captions (converted from SRT once, cached)
  GET    /api/video/{id}/poster              the poster still (cached; a YouTube item uses its NASA fallback's)
  GET    /api/video/cache                    {bytes, cap_bytes, files, pinned_ready, pinned_total, prefetch}
  DELETE /api/video/cache                    Settings → Videos → Clear (pinned files download again next launch)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from .config import settings

router = APIRouter()

SOURCES = ("nasa_file", "youtube")
NASA_HOSTS = ("images-assets.nasa.gov", "images-api.nasa.gov", "svs.gsfc.nasa.gov", "nssdc.gsfc.nasa.gov")
REQUIRED = ("id", "title", "concept", "source", "duration_s", "credit", "music_credit", "prefetch", "age")
ID_RE = re.compile(r"^[a-z0-9_]{2,40}$")
YT_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
UA = "OutpostLuna/1.0 (NASA Space Apps; offline video cache)"
PROBE = {"nasa": "https://images-api.nasa.gov/", "youtube": "https://www.youtube-nocookie.com/"}
PROBE_TTL_S = 20.0
PROBE_FAIL_TTL_S = 5.0     # a failed probe is retried soon: a blip must not pin "offline" for long
PROBE_TIMEOUTS_S = (3.0, 6.0)
MISSION_QUIET_S = 20.0      # a mission clock tick within this long pauses the background prefetch


# ---------------------------------------------------------------- catalog --------------------------------------------
def catalog_path() -> Path:
    return settings.data_dir / "video" / "catalog.json"


_cat: dict = {"key": None, "items": []}


def catalog() -> list[dict]:
    p = catalog_path()
    try:
        key = (str(p), p.stat().st_mtime)
    except OSError:
        return []
    if _cat["key"] != key:
        _cat["items"], _cat["key"] = json.loads(p.read_text(encoding="utf-8")), key
    return _cat["items"]


def item(vid: str) -> dict | None:
    return next((v for v in catalog() if v.get("id") == vid), None)


def _nasa_url(u) -> bool:
    try:
        p = urlparse(str(u))
    except ValueError:
        return False
    return p.scheme == "https" and p.hostname in NASA_HOSTS and " " not in str(u)


def validate(items) -> list[str]:
    """Problems with a catalog (empty = fine). The learning content check and the tests call this."""
    if not isinstance(items, list) or not items:
        return ["catalog must be a non-empty list"]
    out, seen = [], set()
    ids = {v.get("id") for v in items if isinstance(v, dict)}
    for k, v in enumerate(items):
        if not isinstance(v, dict):
            out.append(f"[{k}] not an object")
            continue
        vid = v.get("id", f"[{k}]")
        out += [f"{vid}: missing {f}" for f in REQUIRED if f not in v or v[f] in ("", None)]
        if not ID_RE.match(str(v.get("id", ""))):
            out.append(f"{vid}: id must be lower_snake_case")
        if vid in seen:
            out.append(f"{vid}: duplicate id")
        seen.add(vid)
        src = v.get("source")
        if src not in SOURCES:
            out.append(f"{vid}: source must be one of {SOURCES}")
        if not isinstance(v.get("duration_s"), (int, float)) or not 0 < v.get("duration_s", 0) <= 600:
            out.append(f"{vid}: duration_s must be 1..600")
        if not str(v.get("credit", "")).startswith("NASA"):
            out.append(f"{vid}: credit must start with NASA")
        for f in ("music_credit", "prefetch"):
            if not isinstance(v.get(f), bool):
                out.append(f"{vid}: {f} must be true or false")
        if src == "youtube":
            if not YT_RE.match(str(v.get("youtube_id", ""))):
                out.append(f"{vid}: youtube_id must be an 11-character YouTube id")
            if v.get("file_url") or v.get("prefetch"):
                out.append(f"{vid}: YouTube is never downloaded (no file_url, prefetch false)")
        if src == "nasa_file":
            if not _nasa_url(v.get("file_url")):
                out.append(f"{vid}: file_url must be an https URL on a NASA host {NASA_HOSTS}")
            if v.get("music_credit"):
                out.append(f"{vid}: a music-credited video plays from YouTube, never as a cached file")
            if v.get("youtube_id"):
                out.append(f"{vid}: a nasa_file has no youtube_id")
        for f in ("captions_url", "poster_url"):
            if v.get(f) and not _nasa_url(v[f]):
                out.append(f"{vid}: {f} must be an https URL on a NASA host")
        if v.get("captions_url") and not re.search(r"\.(srt|vtt)$", v["captions_url"], re.I):
            out.append(f"{vid}: captions_url must be .srt or .vtt")
        if v.get("prefetch"):
            if src != "nasa_file" or not v.get("file_url"):
                out.append(f"{vid}: a prefetch item must be a nasa_file with a file_url")
            if not isinstance(v.get("bytes"), int) or v["bytes"] <= 0:
                out.append(f"{vid}: a prefetch item needs its size in bytes (the download check)")
        if v.get("sha256") and not re.fullmatch(r"[0-9a-f]{64}", str(v["sha256"])):
            out.append(f"{vid}: sha256 must be 64 hex characters")
        fb = v.get("fallback")
        if fb is not None:
            if fb == vid or fb not in ids:
                out.append(f"{vid}: fallback {fb!r} is not another catalog id")
            elif next(x for x in items if isinstance(x, dict) and x.get("id") == fb).get("source") != "nasa_file":
                out.append(f"{vid}: fallback {fb!r} must be a nasa_file (it plays offline)")
    return out


# ---------------------------------------------------------------- cache ----------------------------------------------
class DownloadError(Exception):
    pass


class Cancelled(Exception):
    pass


def srt_to_vtt(text: str) -> str:
    """SubRip → WebVTT: the header, '.' for the millisecond comma; cue numbers stay (they are valid cue ids)."""
    t = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").strip()
    if t.startswith("WEBVTT"):
        return t + "\n"
    t = re.sub(r"(\d{1,2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", t)
    return "WEBVTT\n\n" + t + "\n"


def has_cues(vtt: str) -> bool:
    return "-->" in vtt


class Cache:
    """Files by name ({id}.mp4, {id}.vtt, {id}.jpg) in one folder, with index.json: {name: {bytes, used, pinned}}."""

    def __init__(self, root: Path, cap_bytes: int):
        self.root, self.cap = Path(root), int(cap_bytes)
        self.lock = threading.RLock()
        self._name_locks: dict[str, threading.Lock] = {}
        self.idx_path = self.root / "index.json"

    # ---- index ----
    def _load(self) -> dict:
        try:
            d = json.loads(self.idx_path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.idx_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
        _replace(tmp, self.idx_path)

    def path(self, name: str) -> Path:
        if not re.fullmatch(r"[a-z0-9_]+\.(mp4|vtt|jpg)", name):
            raise ValueError(f"bad cache name {name!r}")
        return self.root / name

    def has(self, name: str) -> bool:
        with self.lock:
            return name in self._load() and self.path(name).exists()

    def touch(self, name: str) -> None:
        with self.lock:
            d = self._load()
            if name in d:
                d[name]["used"] = time.time()
                self._save(d)

    def add(self, name: str, pinned: bool = False) -> list[str]:
        with self.lock:
            d = self._load()
            d[name] = {"bytes": self.path(name).stat().st_size, "used": time.time(), "pinned": bool(pinned)}
            self._save(d)
        return self.evict(keep=name)

    def pin(self, name: str, pinned: bool = True) -> None:
        with self.lock:
            d = self._load()
            if name in d:
                d[name]["pinned"] = pinned
                self._save(d)

    def total(self) -> int:
        with self.lock:
            return sum(int(e.get("bytes", 0)) for e in self._load().values())

    def evict(self, keep: str | None = None) -> list[str]:
        """Least recently used first, never a pinned file (nor the one just added), until under the cap."""
        gone = []
        with self.lock:
            d = self._load()
            tot = sum(int(e.get("bytes", 0)) for e in d.values())
            for name, e in sorted(d.items(), key=lambda kv: kv[1].get("used", 0)):
                if tot <= self.cap:
                    break
                if e.get("pinned") or name == keep:
                    continue
                if not _unlink(self.path(name)):
                    continue            # open elsewhere (Windows: a video playing right now); evicted next time
                tot -= int(e.get("bytes", 0))
                d.pop(name)
                gone.append(name)
            if gone:
                self._save(d)
        return gone

    def clear(self) -> int:
        """Delete every cached file. A file the OS holds open (Windows: the video playing right now) stays, and keeps
        its index entry, instead of failing the whole clear; it goes on the next clear or eviction."""
        with self.lock:
            n = 0
            d = self._load()
            kept = {}
            for p in list(self.root.glob("*")) if self.root.exists() else []:
                if p.is_file() and re.search(r"\.(mp4|vtt|jpg|part|tmp)$", p.name):
                    size = p.stat().st_size
                    if _unlink(p):
                        n += size
                    elif p.name in d:
                        kept[p.name] = d[p.name]
            self._save(kept)
            return n

    def stats(self) -> dict:
        with self.lock:
            d = self._load()
        return {"bytes": sum(int(e.get("bytes", 0)) for e in d.values()), "cap_bytes": self.cap, "files": len(d),
                "pinned_bytes": sum(int(e.get("bytes", 0)) for e in d.values() if e.get("pinned"))}

    def name_lock(self, name: str) -> threading.Lock:
        with self.lock:
            return self._name_locks.setdefault(name, threading.Lock())

    # ---- download ----
    def download(self, url: str, name: str, *, size: int | None = None, sha256: str | None = None,
                 pinned: bool = False, pace=None, client: httpx.Client | None = None, chunk: int = 1 << 18) -> Path:
        """Fetch url into name: resume a .part, check the size (and sha256), rename it into place atomically."""
        dest = self.path(name)
        with self.name_lock(name):
            if self.has(name):
                if pinned:
                    self.pin(name)
                return dest
            self.root.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(name + ".part")
            have = part.stat().st_size if part.exists() else 0
            if size and have > size:
                part.unlink()
                have = 0
            own = client is None
            c = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, connect=10.0),
                                       headers={"User-Agent": UA})
            try:
                if not (size and have == size):
                    hdr = {"Range": f"bytes={have}-"} if have else {}
                    with c.stream("GET", url, headers=hdr) as r:
                        if r.status_code == 416 and have:        # nothing left to send: the .part is whole
                            pass
                        elif r.status_code == 206 and have:
                            self._write(r, part, "ab", pace, chunk)
                        elif r.status_code == 200:
                            self._write(r, part, "wb", pace, chunk)   # no resume support: start over
                        else:
                            raise DownloadError(f"{name}: HTTP {r.status_code}")
            except httpx.HTTPError as e:
                raise DownloadError(f"{name}: {type(e).__name__}") from e
            finally:
                if own:
                    c.close()
            got = part.stat().st_size if part.exists() else 0
            if size and got != size:
                if got > size:
                    part.unlink(missing_ok=True)
                raise DownloadError(f"{name}: got {got} bytes, expected {size}")
            if sha256 and file_sha256(part) != sha256:
                part.unlink(missing_ok=True)
                raise DownloadError(f"{name}: sha256 mismatch")
            _replace(part, dest)
        self.add(name, pinned)
        return dest

    @staticmethod
    def _write(r, part: Path, mode: str, pace, chunk: int) -> None:
        with open(part, mode) as f:
            for buf in r.iter_bytes(chunk):
                f.write(buf)
                if pace:
                    f.flush()
                    pace()

    def put_text(self, name: str, text: str, pinned: bool = False) -> Path:
        dest = self.path(name)
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        _replace(tmp, dest)
        self.add(name, pinned)
        return dest


def _unlink(p: Path) -> bool:
    """Delete p; False when the OS refuses. On Windows a file another handle has open (FileResponse streaming it to the
    player, an antivirus scan) cannot be deleted: PermissionError (WinError 32). POSIX unlinks it regardless."""
    try:
        p.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _replace(src: Path, dst: Path, tries: int = 10, wait_s: float = 0.05) -> None:
    """os.replace, retried briefly on PermissionError: on Windows an antivirus scan or a reader can hold dst (or src)
    open for a moment right after it is written. POSIX succeeds the first time."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(wait_s)


def file_sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for buf in iter(lambda: f.read(1 << 20), b""):
            h.update(buf)
    return h.hexdigest()


_cache: Cache | None = None


def cache() -> Cache:
    global _cache
    root = settings.video_cache()
    if _cache is None or _cache.root != root or _cache.cap != settings.video_cache_mb * 1024 * 1024:
        _cache = Cache(root, settings.video_cache_mb * 1024 * 1024)
    return _cache


# ---------------------------------------------------------------- online + availability ------------------------------
_probe: dict[str, tuple[float, bool]] = {}


def online(kind: str = "nasa") -> bool:
    """Can we reach NASA (or YouTube)? One HEAD, remembered for PROBE_TTL_S. VIDEO_OFFLINE=1 forces no."""
    if settings.video_offline:
        return False
    at, ok = _probe.get(kind, (0.0, False))
    if time.monotonic() - at < (PROBE_TTL_S if ok else PROBE_FAIL_TTL_S):
        return ok
    ok = False
    # [vidfix] a slow answer is not "offline": a timeout (busy machine, slow Wi-Fi) gets one more, longer try; only a
    # refused / unresolvable connection, or two timeouts, says offline. Any HTTP answer at all (even 4xx/5xx) is online.
    for t in PROBE_TIMEOUTS_S:
        try:
            httpx.head(PROBE[kind], timeout=t, headers={"User-Agent": UA})
            ok = True
            break
        except httpx.TimeoutException:
            continue
        except httpx.HTTPError:
            break
    _probe[kind] = (time.monotonic(), ok)
    return ok


def names(v: dict) -> dict:
    vid = v["id"]
    return {"video": f"{vid}.mp4", "captions": f"{vid}.vtt", "poster": f"{vid}.jpg"}


def is_cached(v: dict) -> bool:
    return v.get("source") == "nasa_file" and cache().has(names(v)["video"])


def availability(v: dict) -> str:
    if is_cached(v):
        return "cached"
    return "online" if online("youtube" if v.get("source") == "youtube" else "nasa") else "offline"


# ---------------------------------------------------------------- fetching -------------------------------------------
STATE: dict = {"state": "idle", "done": 0, "total": 0, "error": None}
_streamed = [0.0]   # when a video last sent bytes through the backend (the prefetch waits while one streams)
STREAM_QUIET_S = 10.0


def busy() -> bool:
    from .mission import registry
    now = time.monotonic()
    return now - _streamed[0] < STREAM_QUIET_S or now - registry.LAST_ACTIVE[0] < MISSION_QUIET_S


def from_pack(v: dict, kind: str, pinned: bool = False) -> bool:
    """The desktop's installed video asset (settings.video_pack_dir, desktop/main/assets.js) has this file: copy it
    into the cache instead of downloading it. A video must match the catalog's size and sha256."""
    if not settings.video_pack_dir:
        return False
    c, n = cache(), names(v)[kind]
    src = Path(settings.video_pack_dir) / n
    if not src.is_file():
        return False
    if kind == "video" and ((v.get("bytes") and src.stat().st_size != v["bytes"])
                            or (v.get("sha256") and file_sha256(src) != v["sha256"])):
        return False
    with c.name_lock(n):
        if not c.has(n):
            c.root.mkdir(parents=True, exist_ok=True)
            tmp = c.path(n).with_name(n + ".part")
            shutil.copyfile(src, tmp)
            os.replace(tmp, c.path(n))
            c.add(n, pinned)
    return True


def pack_has(v: dict) -> bool:
    return bool(settings.video_pack_dir) and (Path(settings.video_pack_dir) / names(v)["video"]).is_file()


def fetch_captions(v: dict, pinned: bool = False, client: httpx.Client | None = None) -> bool:
    """Captions for v as WebVTT in the cache (SRT converted once). False when it has none (or they are empty)."""
    c, n = cache(), names(v)["captions"]
    if c.has(n):
        if pinned:
            c.pin(n)
        return True
    if from_pack(v, "captions", pinned):
        return True
    if not v.get("captions_url"):
        return False
    try:
        r = (client or httpx).get(v["captions_url"], timeout=20.0, follow_redirects=True, headers={"User-Agent": UA})
        r.raise_for_status()
    except httpx.HTTPError:
        return False
    vtt = srt_to_vtt(r.content.decode("utf-8", "replace"))
    if not has_cues(vtt):
        return False
    c.put_text(n, vtt, pinned)
    return True


def fetch_poster(v: dict, pinned: bool = False, client: httpx.Client | None = None) -> bool:
    c, n = cache(), names(v)["poster"]
    if c.has(n) or from_pack(v, "poster", pinned):
        return True
    if not v.get("poster_url"):
        return False
    try:
        c.download(v["poster_url"], n, pinned=pinned, client=client)
        return True
    except DownloadError:
        return False


def fetch_video(v: dict, pace=None, client: httpx.Client | None = None) -> Path:
    pinned = bool(v.get("prefetch"))
    if from_pack(v, "video", pinned):
        fetch_captions(v, pinned, client)
        fetch_poster(v, pinned, client)
        return cache().path(names(v)["video"])
    p = cache().download(v["file_url"], names(v)["video"], size=v.get("bytes"), sha256=v.get("sha256"),
                         pinned=pinned, pace=pace, client=client)
    fetch_captions(v, pinned, client)
    fetch_poster(v, pinned, client)
    return p


def _pace(stop: threading.Event | None = None, sleep_s: float = 0.02):
    """Low priority: a short rest between chunks, and a full pause while a mission runs or a video streams."""
    def pace():
        if stop is not None and stop.is_set():
            raise Cancelled()
        time.sleep(sleep_s)
        while busy():
            STATE["state"] = "paused"
            if stop is not None and stop.wait(2.0):
                raise Cancelled()
            if stop is None:
                time.sleep(2.0)
        STATE["state"] = "running"
    return pace


def prefetch_all(stop: threading.Event | None = None, pace=None) -> dict:
    """Download every pinned (prefetch) file not cached yet. Blocking: run it in a thread."""
    todo = [v for v in catalog() if v.get("prefetch") and v.get("source") == "nasa_file"]
    STATE.update(state="running", total=len(todo), done=0, error=None)
    pace = pace or _pace(stop)
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, connect=10.0),
                      headers={"User-Agent": UA}) as client:
        for v in todo:
            try:
                fetch_video(v, pace=pace, client=client)
                STATE["done"] += 1
            except Cancelled:
                STATE["state"] = "stopped"
                return dict(STATE)
            except (DownloadError, OSError) as e:
                STATE["error"] = str(e)[:200]
    STATE["state"] = "done" if STATE["done"] == STATE["total"] else "incomplete"
    return dict(STATE)


_stop = threading.Event()


async def prefetch_task(delay_s: float = 15.0, retry_s: float = 300.0) -> None:
    """Started by the app (main.py lifespan): after the app has settled, prefetch the pinned files; offline, try again
    every few minutes (the first ONLINE launch is the one that downloads). Never raises."""
    if not settings.video_prefetch and not settings.video_pack_dir:
        return
    try:
        await asyncio.sleep(delay_s)
        while not _stop.is_set():
            todo = [v for v in catalog() if v.get("prefetch") and not is_cached(v)]
            if not todo:
                STATE.update(state="done", total=sum(1 for v in catalog() if v.get("prefetch")), error=None)
                STATE["done"] = STATE["total"]
                return
            if all(pack_has(v) for v in todo) or (settings.video_prefetch and await asyncio.to_thread(online, "nasa")):
                out = await asyncio.to_thread(prefetch_all, _stop)
                if out["state"] in ("done", "stopped"):
                    return
            else:
                STATE["state"] = "offline"
            await asyncio.sleep(retry_s)
    except Exception as e:  # noqa: BLE001  (a background nicety: never take the app down)
        STATE.update(state="error", error=str(e)[:200])


def stop_prefetch() -> None:
    _stop.set()


# ---------------------------------------------------------------- routes ---------------------------------------------
def _get(vid: str) -> dict:
    v = item(vid)
    if not v:
        raise HTTPException(404, "no such video")
    return v


def public(v: dict) -> dict:
    vid = v["id"]
    local = {"cached": is_cached(v)}
    if v["source"] == "nasa_file":
        local |= {"play_url": f"/api/video/{vid}/file",
                  "captions_src": f"/api/video/{vid}/captions.vtt" if v.get("captions_url") else None}
    fb = item(v["fallback"]) if v.get("fallback") else None
    if v.get("poster_url") or (fb and fb.get("poster_url")):
        local["poster_src"] = f"/api/video/{vid}/poster"
    return {**v, **local}


@router.get("/api/video/catalog")
def video_catalog():
    return [public(v) for v in catalog()]


@router.get("/api/video/cache")
def video_cache_stats():
    pinned = [v for v in catalog() if v.get("prefetch")]
    return {**cache().stats(), "pinned_ready": sum(is_cached(v) for v in pinned), "pinned_total": len(pinned),
            "prefetch": dict(STATE)}


@router.delete("/api/video/cache")
def video_cache_clear():
    freed = cache().clear()
    STATE.update(state="cleared", done=0)
    return {"freed_bytes": freed, **cache().stats()}


@router.get("/api/video/{vid}/available")
async def video_available(vid: str):
    v = _get(vid)
    return {"id": vid, "status": await asyncio.to_thread(availability, v)}


@router.get("/api/video/{vid}/captions.vtt")
async def video_captions(vid: str):
    v = _get(vid)
    n = names(v)["captions"]
    if not cache().has(n) and not (v.get("captions_url") and await asyncio.to_thread(online, "nasa")
                                   and await asyncio.to_thread(fetch_captions, v, bool(v.get("prefetch")))):
        raise HTTPException(404, "no captions")
    cache().touch(n)
    return FileResponse(cache().path(n), media_type="text/vtt; charset=utf-8")


@router.get("/api/video/{vid}/poster")
async def video_poster(vid: str):
    v = _get(vid)
    for x in [v] + ([item(v["fallback"])] if v.get("fallback") else []):
        if not x or not x.get("poster_url"):
            continue
        n = names(x)["poster"]
        if cache().has(n) or (await asyncio.to_thread(online, "nasa")
                              and await asyncio.to_thread(fetch_poster, x, bool(x.get("prefetch")))):
            return FileResponse(cache().path(n), media_type="image/jpeg")
    raise HTTPException(404, "no poster")


_bg: dict[str, threading.Thread] = {}


def _cache_in_background(v: dict) -> None:
    """The first play of a NASA file streams it AND caches it (recently played; pinned if it is a prefetch item)."""
    t = _bg.get(v["id"])
    if t and t.is_alive():
        return
    def run():
        try:
            fetch_video(v)
        except (DownloadError, OSError, ValueError):
            pass
    _bg[v["id"]] = t = threading.Thread(target=run, name=f"video-cache-{v['id']}", daemon=True)
    t.start()


@router.get("/api/video/{vid}/file")
async def video_file(vid: str, request: Request):
    v = _get(vid)
    if v["source"] != "nasa_file":
        raise HTTPException(404, "YouTube videos play in the YouTube player and are never downloaded")
    n = names(v)["video"]
    if cache().has(n):
        cache().touch(n)
        return FileResponse(cache().path(n), media_type="video/mp4")
    if not await asyncio.to_thread(online, "nasa"):
        raise HTTPException(503, "offline and not saved yet")
    _cache_in_background(v)
    return await _proxy(v["file_url"], request.headers.get("range"))


async def _proxy(url: str, rng: str | None) -> Response:
    client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, connect=10.0),
                               headers={"User-Agent": UA})
    try:
        r = await client.send(client.build_request("GET", url, headers={"Range": rng} if rng else {}), stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(502, "NASA did not answer")
    if r.status_code not in (200, 206):
        await r.aclose()
        await client.aclose()
        raise HTTPException(502, f"NASA answered {r.status_code}")
    _streamed[0] = time.monotonic()

    async def body():
        try:
            async for buf in r.aiter_raw():
                _streamed[0] = time.monotonic()
                yield buf
        finally:
            await r.aclose()
            await client.aclose()
    hdr = {k: r.headers[k] for k in ("content-length", "content-range", "accept-ranges") if k in r.headers}
    hdr.setdefault("accept-ranges", "bytes")
    return StreamingResponse(body(), status_code=r.status_code, headers=hdr, media_type="video/mp4")
