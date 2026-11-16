"""Arc Transcriber Space (nft2) through libarc (C) + ONNX Runtime: the ear's model, without torch.

libarc is built from desktop/vendor/libarc (CMake; `make desktop-libarc`) as libarc.dylib / arc.dll / libarc.so. The
binding is generated from its header (include/arc.h -> app/_arc_ffi.py, cffi out-of-line ABI mode,
model_server/tools/gen_bindings.py): no hand-written signatures or struct layouts here. Loading checks the library's
arc_abi_version() against the header's ARC_ABI_VERSION and refuses another ABI.

libarc links no ONNX Runtime: `arc_ort_set_library()` points it at the PINNED runtime the build put next to it
(<libarc's folder>/onnxruntime/: libonnxruntime.1.32.0.dylib / onnxruntime.dll / libonnxruntime.so.1.32.0 with
onnxruntime.json, from desktop/vendor/libarc/onnxruntime.lock.json), sha256-checked here at load. Dev fallbacks, only
when asked: ARC_ORT_FROM_WHEEL=1 uses the pip onnxruntime wheel's copy, ARC_ORT_LIB=<path> any library.

    m = Nft2(lib, "…/arc-transcriber-space/nft2", threads=4)
    m.set_names([{"name": "Tycho", "kind": "lunar_feature"}, {"name": "Artemis II", "kind": "mission",
                  "aliases": ["Artemis 2"]}])
    out = m.transcribe(pcm_f32_16k)       # {"utts": [...], "names": [...], "numbers": [...], "events": [...], ...}

The model folder is checked against the asset manifest's sha256 first (app/model_verify.py; a damaged file refuses
the load and asks the desktop app for a fresh copy). One model runs one call at a time (libarc's rule): calls take
`m.lock`. The names list is the model's until changed (biasing, the decoder's kb prompt, linking). Output is plain
dicts (see `_result`); the transcript is SPOKEN form ("apollo twelve") with the decoder's casing and punctuation; route
on names[i]["entity"], never on raw words.
"""
from __future__ import annotations

import ctypes
import glob
import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

from ._arc_ffi import ffi
from ._cdefs import DEFINES
from .model_verify import sha256_file, verify_asset

SR = 16000
KINDS = {"lunar_feature", "site", "celestial", "spacecraft", "vehicle", "mission", "crew", "person", "place",
         "organization", "product", "team", "law"}
ABI_VERSION = int(DEFINES["_arc_ffi"]["ARC_ABI_VERSION"])          # the header the binding was generated from
ORT_LOCK = Path(__file__).resolve().parents[2] / "desktop/vendor/libarc/onnxruntime.lock.json"   # a clone only


class AbiMismatch(RuntimeError):
    """libarc was built from another arc.h than the binding: rebuild it (or regenerate the binding)."""


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "on", "true", "yes")


_LOADED: list = []


def open_library(path: Path):
    """dlopen libarc through the generated binding, then check its ABI. -> cffi lib. The library is loaded with ctypes
    first, exactly as the hand-written binding did (ctypes.CDLL(path): on Windows its default flags search the DLL's
    own folder), and that handle is handed to cffi, so the loading rules stay the ones the Windows build was verified
    with."""
    h = ctypes.CDLL(str(path))
    _LOADED.append(h)      # the ctypes handle stays referenced (libraries are never unloaded)
    return _check_abi(path, _adopt(h, path))


def _adopt(h, path: Path):
    """The cffi lib over an already loaded library (ffi.dlopen(<void * handle>)); by path if this cffi refuses one."""
    try:
        return ffi.dlopen(ffi.cast("void *", h._handle))
    except (TypeError, OSError, ffi.error):
        return ffi.dlopen(str(path))


def _check_abi(path: Path, L):
    try:
        got = L.arc_abi_version()
    except (AttributeError, ffi.error):   # cffi: symbol not in the library
        raise AbiMismatch(f"{path} has no arc_abi_version(): it was built before the ABI check (rebuild it: "
                          "make desktop-libarc)") from None
    if got != ABI_VERSION:
        raise AbiMismatch(f"{path} is libarc ABI {got} ({ffi.string(L.arc_version()).decode()}), this model server "
                          f"was generated for ABI {ABI_VERSION} ({DEFINES['_arc_ffi']['ARC_VERSION']}): rebuild libarc "
                          "from this checkout (make desktop-libarc) or reinstall the app")
    return L


def ort_library(lib: Path | None = None) -> tuple[Path | None, dict]:
    """The ONNX Runtime library libarc should load and where it came from: ({"source": "pinned", "version", "sha256"}
    | {"source": "env"} | {"source": "wheel"}). Pinned: <libarc's folder>/onnxruntime/onnxruntime.json (also its
    parent's, for a multi-config build's Release/ folder). Dev only: ARC_ORT_LIB, ARC_ORT_FROM_WHEEL=1."""
    if os.environ.get("ARC_ORT_LIB"):
        return Path(os.environ["ARC_ORT_LIB"]), {"source": "env"}
    if _truthy(os.environ.get("ARC_ORT_FROM_WHEEL")):
        return wheel_ort_library(), {"source": "wheel"}
    if lib is not None:
        for d in (lib.parent / "onnxruntime", lib.parent.parent / "onnxruntime"):
            j = d / "onnxruntime.json"
            if j.is_file():
                meta = json.loads(j.read_text(encoding="utf-8"))
                return d / meta["lib"], {"source": "pinned", "version": meta["version"], "sha256": meta["sha256"]}
    return None, {"source": "pinned"}


def resolve_ort(lib: Path, ort: Path | str | None = None) -> tuple[Path, dict]:
    """ort_library() + its checks: the pinned runtime must exist at the sha256 its onnxruntime.json gives. Raises
    RuntimeError with what to do; the dev fallbacks (ARC_ORT_LIB, ARC_ORT_FROM_WHEEL=1, an explicit `ort`) are not
    hashed."""
    if ort:
        return Path(ort), {"source": "argument"}
    path, info = ort_library(lib)
    if path is None:
        if info["source"] == "wheel":
            raise RuntimeError("ARC_ORT_FROM_WHEEL=1 but the onnxruntime wheel is not installed")
        raise RuntimeError(f"ONNX Runtime {pinned_ort_version() or '(pinned)'} not found next to libarc "
                           f"({lib.parent / 'onnxruntime'}): rebuild libarc (make desktop-libarc) or reinstall the "
                           "app. Dev only: ARC_ORT_FROM_WHEEL=1 runs on the pip wheel's copy")
    if info["source"] == "pinned":
        if not path.is_file():
            raise RuntimeError(f"ONNX Runtime library missing: {path} (rebuild libarc or reinstall the app)")
        got = sha256_file(path)
        if got != info["sha256"] and not _signed_in_app_bundle(path):
            raise RuntimeError(f"ONNX Runtime library {path} is damaged or not the pinned build (sha256 {got[:12]}…, "
                               f"expected {info['sha256'][:12]}…): reinstall the app (or rebuild libarc)")
    return path, info


def _signed_in_app_bundle(path: Path) -> bool:
    """macOS release builds re-sign every Mach-O inside the .app, which rewrites the pinned dylib's signature bytes, so
    its sha256 no longer equals the lock's. There the bundle's own code signature is the integrity check: accept the
    file when `codesign --verify --strict` passes for it (a tampered or unsigned file fails). The engine still checks
    the runtime reports the pinned version after loading. Elsewhere (Windows, Linux, a clone) the sha256 rule stands."""
    if sys.platform != "darwin" or ".app/Contents/" not in str(path):
        return False
    import subprocess
    try:
        r = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", str(path)], capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def wheel_ort_library() -> Path | None:
    """The ONNX Runtime shared library inside the installed `onnxruntime` wheel (dev fallback: ARC_ORT_FROM_WHEEL=1)."""
    import importlib.util
    spec = importlib.util.find_spec("onnxruntime")      # found, not imported: libarc loads only the C library
    if spec is None or not spec.origin:
        return None
    capi = Path(spec.origin).parent / "capi"
    pats = {"darwin": ["libonnxruntime.*.dylib", "libonnxruntime.dylib"], "win32": ["onnxruntime.dll"]}.get(
        sys.platform, ["libonnxruntime.so.*", "libonnxruntime.so"])
    for pat in pats:
        hits = sorted(glob.glob(str(capi / pat)))
        if hits:
            return Path(hits[-1])
    return None


def pinned_ort_version() -> str | None:
    """The version onnxruntime.lock.json pins (a clone; the app reads it from onnxruntime.json next to libarc)."""
    try:
        return json.loads(ORT_LOCK.read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        return None


def _s(p) -> str | None:
    return None if p == ffi.NULL else ffi.string(p).decode("utf-8", "replace")


def _f(x: float, nd: int = 3):
    return None if x is None or x < 0 else round(float(x), nd)


def _words(p, n: int) -> list[dict]:
    out = []
    for k in range(n):
        w = p[k]
        d = {"w": _s(w.text), "t0": round(w.start, 3), "t1": round(w.end, 3)}
        if w.tag != ffi.NULL:
            d["tag"], d["tag_begin"] = _s(w.tag), bool(w.tag_begin)
        out.append(d)
    return out


def _result(r) -> dict:
    utts = []
    for i in range(r.n_utts):
        u = r.utts[i]
        utts.append({
            "t0": round(u.start, 3), "t1": round(u.end, 3), "text": _s(u.text) or "",
            "decoder_text": _s(u.decoder_text),
            "tags": [{"tag": _s(t.tag), "b": t.word_begin, "e": t.word_end, "text": _s(t.text)}
                     for t in (u.tags[k] for k in range(u.n_tags))],
            "words": _words(u.words, u.n_words),
            "device_directed": _f(u.device_directed), "command_complete": _f(u.command_complete),
            "directed_head": _f(u.directed_head), "directed": None if u.directed < 0 else bool(u.directed),
            "intent": {"label": _s(u.intent.label), "p": _f(u.intent.p)} if u.intent.label != ffi.NULL else None,
            "act": {"label": _s(u.act.label), "p": _f(u.act.p)} if u.act.label != ffi.NULL else None,
        })
    names = []
    for i in range(r.n_names):
        n = r.names[i]
        names.append({"t0": round(n.start, 3), "t1": round(n.end, 3), "tag": _s(n.tag), "heard": _s(n.heard),
                      "entity": _s(n.entity), "kb_index": n.kb_index, "state": _s(n.state), "p": _f(n.p),
                      "src": _s(n.src), "via": _s(n.via), "show": bool(n.show)})
    numbers = []
    for i in range(r.n_numbers):
        n = r.numbers[i]
        numbers.append({"t0": round(n.start, 3), "t1": round(n.end, 3), "kind": _s(n.kind), "unit": _s(n.unit),
                        "heard": _s(n.heard), "value": n.value if n.has_value else None,
                        "value2": n.value2 if n.has_value2 else None, "state": _s(n.state)})
    events = [{"label": _s(e.label), "t0": round(e.start, 3), "t1": round(e.end, 3), "p": round(e.p, 4)}
              for e in (r.events[k] for k in range(r.n_events))]
    return {"utts": utts, "names": names, "numbers": numbers, "events": events, "audio_s": round(r.audio_s, 3),
            "wall_ms": round(r.wall_ms, 1)}


class Nft2:
    """One loaded Arc Transcriber Space model (libarc). Thread-safe by a lock: one call at a time."""

    def __init__(self, lib: Path | str, model_dir: Path | str, threads: int = 4, ort: Path | str | None = None,
                 verify: bool = True):
        self.lib_path, self.dir = Path(lib), Path(model_dir)
        if not self.lib_path.exists():
            raise FileNotFoundError(f"libarc not found: {self.lib_path} (make desktop-libarc)")
        if not (self.dir / "config.json").exists():
            raise FileNotFoundError(f"Arc Transcriber Space model not found: {self.dir} (needs nft2/config.json)")
        # model files at the manifest's sha256 (the asset's folder is nft2/'s parent: "nft2/config.json", ...)
        self.verify = verify_asset("ear", self.dir.parent, "The speech model (Arc Transcriber Space)") if verify \
            else {"verified": False, "reason": "not asked"}
        self.L = L = open_library(self.lib_path)
        self.abi, self.version = L.arc_abi_version(), _s(L.arc_version())
        ort, self.ort_info = resolve_ort(self.lib_path, ort)
        if L.arc_ort_set_library(str(ort).encode()) != 0:
            raise RuntimeError(f"ONNX Runtime: {_s(L.arc_ort_error())}")
        self.ort = ort
        err = ffi.new("char[]", 1024)
        t = time.perf_counter()
        m = L.arc_nft2_create(str(self.dir).encode(), int(threads), err, len(err))
        if m == ffi.NULL:
            raise RuntimeError(f"arc_nft2_create: {ffi.string(err).decode('utf-8', 'replace')}")
        self.m = m
        self.load_s = round(time.perf_counter() - t, 2)
        self.backend = _s(L.arc_nft2_backend())
        want = self.ort_info.get("version")
        if want and self.backend != f"onnxruntime {want}":
            self.close()
            raise RuntimeError(f"ONNX Runtime: {ort} reports {self.backend!r}, the pin is {want}")
        self.lock = threading.RLock()
        self.names: list[dict] = []
        self._names_key = None
        self._keep: list = []      # the C side copies names / context, but keep the last buffers alive anyway

    def info(self) -> dict:
        """For /health: library ABI + version, the runtime and where it came from, the model check."""
        return {"abi": self.abi, "libarc": self.version, "backend": self.backend, "ort": str(self.ort),
                "ort_source": self.ort_info["source"], "verify": self.verify}

    def close(self) -> None:
        with getattr(self, "lock", threading.RLock()):
            if self.m is not None:
                self.L.arc_nft2_destroy(self.m)
                self.m = None

    # ---- context ----
    def set_names(self, names: list[dict]) -> int:
        """[{"name", "kind", "aliases"?, "group"?}] in priority order (the first ~10-15 reach the decoder prompt)."""
        ns = [n for n in (normalize_entry(x) for x in names or []) if n]
        arr = ffi.new("arc_name_entry[]", max(1, len(ns)))
        keep: list = [arr]
        for i, n in enumerate(ns):
            strs = [ffi.new("char[]", n["name"].encode())]
            arr[i].name = strs[0]
            for field in ("kind", "group"):
                if n.get(field):
                    c = ffi.new("char[]", n[field].encode())
                    strs.append(c)
                    setattr(arr[i], field, c)
            al = [ffi.new("char[]", a.encode()) for a in n.get("aliases") or []]
            ap = ffi.new("const char *[]", al or [ffi.NULL])
            arr[i].aliases, arr[i].n_aliases = ap, len(al)
            keep += strs + al + [ap]
        with self.lock:
            rc = self.L.arc_nft2_set_names(self.m, arr, len(ns))
            self._keep = keep
            self.names = ns
            self._names_key = None
        if rc != 0:
            raise RuntimeError(f"arc_nft2_set_names: {_s(self.L.arc_last_error())}")
        return len(ns)

    def set_context(self, prev: str | None = None, dom: str | None = None, auto_prev: bool = False) -> None:
        c = ffi.new("arc_nft2_context *")      # zeroed: no kb, speakers, numbers, entities
        keep = [c]
        if dom is not None:
            keep.append(ffi.new("char[]", dom.encode()))
            c.dom = keep[-1]
        if prev:
            keep.append(ffi.new("char[]", prev.encode()))
            c.prev = keep[-1]
        c.auto_prev = int(auto_prev)
        with self.lock:
            self.L.arc_nft2_set_context(self.m, c)

    # ---- decoding ----
    def transcribe(self, pcm: np.ndarray, domain: str = "assistant", no_events: bool = False, no_bias: bool = False,
                   names: list[dict] | None = None) -> dict:
        """A whole clip (16 kHz mono float32). Up to 20 s is one utterance; longer clips are segmented by Arc."""
        x = np.ascontiguousarray(pcm, dtype=np.float32)
        o = ffi.new("arc_nft2_options *")
        dom = ffi.new("char[]", domain.encode())
        o.domain, o.no_bias, o.no_events = dom, int(no_bias), int(no_events)
        waited = time.perf_counter()
        with self.lock:
            _lock_wait((time.perf_counter() - waited) * 1000)   # [#92] another stream holding the model
            if names is not None and repr(names) != self._names_key:
                self.set_names(names)
                self._names_key = repr(names)
            t = time.perf_counter()
            r = self.L.arc_nft2_transcribe(self.m, ffi.from_buffer("float[]", x), len(x), o)
            ms = (time.perf_counter() - t) * 1000
            if r == ffi.NULL:
                raise RuntimeError(f"arc_nft2_transcribe: {_s(self.L.arc_last_error())}")
            try:
                out = _result(r)
            finally:
                self.L.arc_result_free(r)
        out["ms"] = round(ms, 1)
        return out


def _lock_wait(ms: float) -> None:
    try:
        from . import diag
        diag.METRICS.observe("ear_lock_wait_ms", ms)
    except ImportError:   # tools that load this file on its own
        pass


# ------------------------------------------------------------------------------------------------- names lists
def normalize_entry(x) -> dict | None:
    """A names-list entry as libarc takes it. Strings become {"name": s, "kind": "place"}: the notes say `kind` is
    required (tagging drops a lot without it), so the caller should send kinds; this keeps old string lists working."""
    if isinstance(x, str):
        x = {"name": x}
    if not isinstance(x, dict) or not str(x.get("name") or "").strip():
        return None
    kind = str(x.get("kind") or "place").strip().lower()
    out = {"name": str(x["name"]).strip(), "kind": kind if kind in KINDS else "place"}
    al = [str(a).strip() for a in x.get("aliases") or [] if str(a).strip()]
    if al:
        out["aliases"] = al[:12]
    if x.get("group"):
        out["group"] = str(x["group"])
    return out
