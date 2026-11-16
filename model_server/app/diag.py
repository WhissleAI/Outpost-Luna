"""Local diagnostics (issue #92, docs/DIAGNOSTICS.md): structured logs, metrics and a daily summary. The same file in
backend/app and model_server/app (a test checks the copies stay identical, like local_guard.py).

Everything stays on this computer: nothing in this module opens a socket.

  JSON-lines log   LOG.event("ear_stream_close", audio_s=12.3, turns=2)  ->  <LUNA_LOG_DIR>/<svc>.jsonl
                   one object per line: {"ts", "level", "svc", "event", **fields}. Every field goes through scrub()
                   first: transcripts, names, audio and tokens never reach the file. Rotated at LOG_MAX_BYTES (5 MB),
                   LOG_KEEP files per service (<svc>.jsonl, <svc>.jsonl.1 ... .4). No LUNA_LOG_DIR (a bare `make
                   backend`, the test suites): nothing is written.
  Metrics          METRICS.inc("turns", ear="arc") / METRICS.observe("ear_decode_ms", 42.0, kind="final"): counters and
                   fixed-bucket histograms in memory; METRICS.snapshot() is what GET /metrics answers (p50/p95/p99).
  Daily summary    every FLUSH_S and at shutdown, what was counted since the last flush is merged into
                   <LUNA_DATA_DIR>/metrics/daily-<svc>.json: one bucket per local day, the last KEEP_DAYS days.

The metrics endpoints are token-protected (authorized()): with LUNA_TOKEN set (the desktop app), a GET needs the token
as the cookie (the app's own page), the X-Luna-Token header or a Bearer, like a WebSocket or a POST (docs/SECURITY.md).
"""
from __future__ import annotations

import atexit
import datetime as _dt
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_KEEP = 5
KEEP_DAYS = 30
FLUSH_S = 60.0
MAX_STR = 300
SCRUBBED = "[scrubbed]"

# ------------------------------------------------------------------------------------------------------------ scrub
# Keys whose VALUES never reach a log or a bundle: what the kid said or typed, names heard, audio, secrets.
SENSITIVE_KEYS = frozenset({
    "text", "transcript", "words", "word", "spoken", "heard", "entity", "names", "name", "utterance", "utts", "said",
    "say", "readback", "question", "answer", "query", "q", "prompt", "message", "callsign", "call_sign", "audio",
    "pcm", "wav", "samples", "token", "luna_token", "x-luna-token", "authorization", "cookie", "set-cookie",
    "password", "secret", "api_key"})
SENSITIVE_SUFFIXES = ("token", "secret", "password", "_key", "cookie", "_text", "_words")
_SECRET_AFTER = re.compile(r"(?i)(bearer\s+|luna_token=|x-luna-token[\"']?\s*[:=]\s*[\"']?|token[\"']?\s*[:=]\s*[\"']?)"
                           r"[A-Za-z0-9._~+/=-]{6,}")
_LONG_RUN = re.compile(r"[A-Za-z0-9_-]{32,}")
_HEX = re.compile(r"[0-9a-fA-F]+")


def sensitive_key(k) -> bool:
    k = str(k).lower()
    return k in SENSITIVE_KEYS or k.endswith(SENSITIVE_SUFFIXES)


def _home() -> str:
    try:
        return str(Path.home())
    except Exception:  # noqa: BLE001
        return ""


def scrub_str(s: str, limit: int | None = MAX_STR) -> str:
    """Secrets out of free text: the live LUNA_TOKEN, anything after Bearer / luna_token= / token:, any 32+ character
    token-like run that is not plain hex (a sha256 stays readable), and the home folder (-> ~: the account name)."""
    tok = os.environ.get("LUNA_TOKEN", "")
    if tok:
        s = s.replace(tok, SCRUBBED)
    s = _SECRET_AFTER.sub(lambda m: m.group(1) + SCRUBBED, s)
    s = _LONG_RUN.sub(lambda m: m.group(0) if _HEX.fullmatch(m.group(0)) else SCRUBBED, s)
    home = _home()
    if home and len(home) > 1:
        s = s.replace(home, "~")
    if limit and len(s) > limit:
        s = s[:limit] + "…"
    return s


def scrub(v, limit: int | None = MAX_STR, _depth: int = 0):
    """A JSON-able copy of v with every sensitive key's value replaced and every string cleaned (scrub_str)."""
    if _depth > 12:
        return SCRUBBED
    if isinstance(v, dict):
        return {str(k): (SCRUBBED if sensitive_key(k) and x not in (None, "", [], {}) else scrub(x, limit, _depth + 1))
                for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [scrub(x, limit, _depth + 1) for x in list(v)[:200]]
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "[bytes]"
    if isinstance(v, str):
        return scrub_str(v, limit)
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, float):
        return v if v == v and abs(v) != float("inf") else None
    return scrub_str(repr(v), limit)


# -------------------------------------------------------------------------------------------------------------- log
class JsonLog:
    """Append-only JSON lines, size-capped with rotation. Thread-safe; never raises (logging must not break a turn)."""

    def __init__(self, svc: str = "app", log_dir: str | Path | None = None, max_bytes: int = LOG_MAX_BYTES,
                 keep: int = LOG_KEEP):
        self.svc, self._dir, self.max_bytes, self.keep = svc, log_dir, max_bytes, max(1, keep)
        self._lock = threading.Lock()

    @property
    def dir(self) -> Path | None:
        d = self._dir if self._dir is not None else os.environ.get("LUNA_LOG_DIR")
        return Path(d) if d else None

    @property
    def path(self) -> Path | None:
        d = self.dir
        return d / f"{self.svc}.jsonl" if d else None

    def files(self) -> list[Path]:
        p = self.path
        if p is None:
            return []
        return [x for x in [p] + [Path(f"{p}.{i}") for i in range(1, self.keep)] if x.exists()]

    def _rotate(self, p: Path) -> None:
        for i in range(self.keep - 1, 0, -1):
            src = Path(f"{p}.{i - 1}") if i > 1 else p
            dst = Path(f"{p}.{i}")
            if src.exists():
                os.replace(src, dst)
        if self.keep == 1 and p.exists():
            p.unlink()

    def event(self, event: str, level: str = "info", **fields) -> dict:
        rec = {"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
               "level": level, "svc": self.svc, "event": str(event)[:80]}
        rec.update({k: v for k, v in scrub(fields).items() if k not in rec})
        p = self.path
        if p is None:
            return rec
        line = (json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            with self._lock:
                p.parent.mkdir(parents=True, exist_ok=True)
                size = p.stat().st_size if p.exists() else 0
                if size and size + len(line) > self.max_bytes:
                    self._rotate(p)
                with open(p, "ab") as f:
                    f.write(line)
        except OSError:
            pass
        return rec

    def error(self, event: str, **fields) -> dict:
        return self.event(event, level="error", **fields)

    def warning(self, event: str, **fields) -> dict:
        return self.event(event, level="warning", **fields)


# ---------------------------------------------------------------------------------------------------------- metrics
LAT_MS = (1, 2, 5, 10, 20, 35, 50, 75, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 10000, 20000)
RATIO = (0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 5.0)


class Hist:
    """Fixed-bucket histogram: counts per upper bound (+ one overflow bucket), n, sum, max. Quantiles are estimated by
    linear interpolation inside the bucket (exact enough for p50 / p95 / p99 of latencies)."""

    def __init__(self, bounds=LAT_MS):
        self.le = tuple(float(b) for b in bounds)
        self.c = [0] * (len(self.le) + 1)
        self.n, self.sum, self.max = 0, 0.0, 0.0

    def observe(self, v: float) -> None:
        v = float(v)
        i = next((i for i, b in enumerate(self.le) if v <= b), len(self.le))
        self.c[i] += 1
        self.n += 1
        self.sum += v
        self.max = max(self.max, v)

    def quantile(self, q: float) -> float | None:
        if not self.n:
            return None
        rank, seen = q * self.n, 0
        for i, k in enumerate(self.c):
            if k and seen + k >= rank:
                hi = min(self.le[i] if i < len(self.le) else self.max, self.max)
                lo = min(self.le[i - 1] if i > 0 else 0.0, hi)
                return round(lo + (hi - lo) * max(0.0, rank - seen) / k, 3)
            seen += k
        return round(self.max, 3)

    def summary(self) -> dict:
        return {"n": self.n, "p50": self.quantile(0.5), "p95": self.quantile(0.95), "p99": self.quantile(0.99),
                "mean": round(self.sum / self.n, 3) if self.n else None, "max": round(self.max, 3) if self.n else None}

    def raw(self) -> dict:
        return {"le": list(self.le), "c": list(self.c), "n": self.n, "sum": round(self.sum, 3), "max": round(self.max, 3)}

    @classmethod
    def from_raw(cls, d: dict) -> "Hist":
        h = cls(d.get("le") or LAT_MS)
        c = list(d.get("c") or [])
        if len(c) == len(h.c):
            h.c = [int(x) for x in c]
        h.n, h.sum, h.max = int(d.get("n") or 0), float(d.get("sum") or 0.0), float(d.get("max") or 0.0)
        return h

    def merge(self, other: "Hist") -> None:
        if other.le != self.le:
            return
        self.c = [a + b for a, b in zip(self.c, other.c)]
        self.n += other.n
        self.sum += other.sum
        self.max = max(self.max, other.max)


def key(name: str, labels: dict) -> str:
    """'ear_decode_ms' + {kind: final} -> 'ear_decode_ms{kind=final}' (labels sorted)."""
    if not labels:
        return name
    return name + "{" + ",".join(f"{k}={labels[k]}" for k in sorted(labels)) + "}"


class Metrics:
    """In-process counters, gauges and histograms. `pending` holds what changed since the last daily flush."""

    def __init__(self, svc: str = "app"):
        self.svc = svc
        self.started = time.time()
        self._lock = threading.Lock()
        self.counters: dict[str, float] = {}
        self.hists: dict[str, Hist] = {}
        self.gauges: dict[str, float] = {}
        self._pc: dict[str, float] = {}
        self._ph: dict[str, Hist] = {}

    def inc(self, name: str, n: float = 1, **labels) -> None:
        k = key(name, labels)
        with self._lock:
            self.counters[k] = self.counters.get(k, 0) + n
            self._pc[k] = self._pc.get(k, 0) + n

    def observe(self, name: str, v: float | None, bounds=LAT_MS, **labels) -> None:
        if v is None:
            return
        k = key(name, labels)
        with self._lock:
            for d in (self.hists, self._ph):
                if k not in d:
                    d[k] = Hist(bounds)
                d[k].observe(v)

    def gauge(self, name: str, v: float | None, **labels) -> None:
        with self._lock:
            self.gauges[key(name, labels)] = v

    def error(self, code: str) -> None:
        """Errors by code: errors{code=decode_timeout}."""
        self.inc("errors", code=str(code)[:60])

    def take_pending(self) -> tuple[dict, dict]:
        with self._lock:
            c, h = self._pc, self._ph
            self._pc, self._ph = {}, {}
        return c, h

    def snapshot(self) -> dict:
        with self._lock:
            counters = dict(sorted(self.counters.items()))
            hists = {k: h.summary() for k, h in sorted(self.hists.items())}
            gauges = dict(sorted(self.gauges.items()))
        return {"svc": self.svc, "pid": os.getpid(), "started_at": _iso(self.started),
                "uptime_s": round(time.time() - self.started, 1), "rss_mb": rss_mb(), "counters": counters,
                "histograms": hists, "gauges": gauges}

    def reset(self) -> None:
        with self._lock:
            self.counters.clear(), self.hists.clear(), self.gauges.clear(), self._pc.clear(), self._ph.clear()


def _iso(t: float) -> str:
    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def rss_mb() -> dict:
    """This process's resident memory in MB: {"now", "peak"}. psutil when installed (the model server), else the OS's
    own call (Linux /proc, macOS task_info, Windows GetProcessMemoryInfo). Never raises."""
    out: dict = {"now": None, "peak": None}
    try:
        import psutil  # type: ignore
        out["now"] = round(psutil.Process().memory_info().rss / 2**20, 1)
    except Exception:  # noqa: BLE001
        try:
            out["now"] = _rss_now()
        except Exception:  # noqa: BLE001
            pass
    try:
        if sys.platform != "win32":
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            out["peak"] = round(peak / (2**20 if sys.platform == "darwin" else 2**10), 1)
    except Exception:  # noqa: BLE001
        pass
    return out


def _rss_now() -> float | None:
    import ctypes
    if sys.platform.startswith("linux"):
        pages = int(Path("/proc/self/statm").read_text().split()[1])
        return round(pages * os.sysconf("SC_PAGE_SIZE") / 2**20, 1)
    if sys.platform == "darwin":
        class Info(ctypes.Structure):
            _fields_ = [("virtual_size", ctypes.c_uint64), ("resident_size", ctypes.c_uint64),
                        ("resident_size_max", ctypes.c_uint64), ("user_time", ctypes.c_uint32 * 2),
                        ("system_time", ctypes.c_uint32 * 2), ("policy", ctypes.c_int32),
                        ("suspend_count", ctypes.c_int32)]
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        libc.mach_task_self.restype = ctypes.c_uint32
        info, count = Info(), ctypes.c_uint32(ctypes.sizeof(Info) // 4)
        if libc.task_info(libc.mach_task_self(), 20, ctypes.byref(info), ctypes.byref(count)) != 0:  # MACH_TASK_BASIC_INFO
            return None
        return round(info.resident_size / 2**20, 1)
    if sys.platform == "win32":
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return round(c.WorkingSetSize / 2**20, 1)
    return None


# ----------------------------------------------------------------------------------------------------- daily summary
def data_dir() -> Path | None:
    d = os.environ.get("LUNA_DATA_DIR")
    return Path(d) if d else None


def daily_path(svc: str, base: Path | None = None) -> Path | None:
    base = base if base is not None else data_dir()
    return base / "metrics" / f"daily-{svc}.json" if base else None


def merge_daily(doc: dict | None, counters: dict, hists: dict, day: str, keep_days: int = KEEP_DAYS) -> dict:
    """doc (a daily-<svc>.json) + one flush's counters / histograms into `day`'s bucket; days past keep_days dropped.
    Each histogram is kept raw (to merge later) with its p50 / p95 / p99 alongside (to read)."""
    doc = doc if isinstance(doc, dict) and isinstance(doc.get("days"), dict) else {"format": 1, "days": {}}
    b = doc["days"].setdefault(day, {"counters": {}, "histograms": {}})
    bc, bh = b.setdefault("counters", {}), b.setdefault("histograms", {})
    for k, v in counters.items():
        bc[k] = bc.get(k, 0) + v
    for k, h in hists.items():
        cur = Hist.from_raw(bh[k]["raw"]) if isinstance(bh.get(k), dict) and "raw" in bh[k] else Hist(h.le)
        cur.merge(h)
        bh[k] = {**cur.summary(), "raw": cur.raw()}
    for d in sorted(doc["days"])[:-keep_days] if len(doc["days"]) > keep_days else []:
        del doc["days"][d]
    doc["updated_at"] = _iso(time.time())
    return doc


def flush(metrics: "Metrics", path: Path | None = None) -> bool:
    """Merge what `metrics` counted since the last flush into today's bucket (atomic write). False: nothing written."""
    path = path if path is not None else daily_path(metrics.svc)
    c, h = metrics.take_pending()
    if path is None or not (c or h):
        return False
    try:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        doc = merge_daily(doc, c, h, _dt.date.today().isoformat())
        doc["svc"] = metrics.svc
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------------------------------------------- singletons
LOG = JsonLog()
METRICS = Metrics()
_flusher: dict = {"thread": None, "stop": None}


def setup(svc: str, **fields) -> None:
    """At startup (each server's lifespan): name the service, log `start`, flush the daily summary every FLUSH_S."""
    LOG.svc = METRICS.svc = svc
    LOG.event("start", pid=os.getpid(), python=sys.version.split()[0], platform=sys.platform, **fields)
    if _flusher["thread"] is None and data_dir() is not None:
        stop = threading.Event()

        def loop():
            while not stop.wait(FLUSH_S):
                flush(METRICS)
        t = threading.Thread(target=loop, name="diag-flush", daemon=True)
        t.start()
        _flusher.update(thread=t, stop=stop)
        atexit.register(flush, METRICS)


def shutdown() -> None:
    LOG.event("stop", uptime_s=round(time.time() - METRICS.started, 1))
    flush(METRICS)
    if _flusher["stop"] is not None:
        _flusher["stop"].set()
        _flusher.update(thread=None, stop=None)


def authorized(headers) -> bool:
    """The metrics endpoints' rule: with LUNA_TOKEN set, the token is needed even for a GET (cookie, header or Bearer,
    the local_guard rules); without it (dev, tests) the guard's Host / Origin checks are the only ones."""
    from .local_guard import LocalGuard
    return LocalGuard(None, token=os.environ.get("LUNA_TOKEN", "")).token_ok({k.lower(): v for k, v in headers.items()})


def metrics_router(path: str, gauges=None):
    """GET <path>: this process's METRICS.snapshot() (gauges(): live values to set first, e.g. open streams); 401
    without the token (authorized())."""
    r = APIRouter()

    @r.get(path)
    def metrics(request: Request):
        if not authorized(request.headers):
            raise HTTPException(401, "missing or wrong local token")
        if gauges is not None:
            try:
                for k, v in gauges().items():
                    METRICS.gauge(k, v)
            except Exception:  # noqa: BLE001 (a gauge never breaks the endpoint)
                pass
        return METRICS.snapshot()
    return r
