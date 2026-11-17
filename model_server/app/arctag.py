"""Arc Tagger 0.5 through its C API, with a small pool of handles per domain.

The C library is arc-tagger-c (`arctag_create_ex`, `arctag_tag_text`, ...), built from desktop/vendor/arctag. The
binding is generated from its header (include/arctag.h -> app/_arctag_ffi.py, cffi out-of-line ABI mode,
model_server/tools/gen_bindings.py), and loading checks arctag_version() against the header's ARCTAG_VERSION_MAJOR /
MINOR (the library has no separate ABI number; 0.x minors change the API). The model folder is checked against the
asset manifest's sha256 at load (app/model_verify.py). One handle holds one stream's state and is not thread-safe, so
requests borrow a handle from a per-domain pool and reset it before returning it.

Kid turns use the `kids` domain (0.5.0, docs/KIDS.md upstream): the assistant model input with thresholds fitted on short
kid turns plus the guard layer (profanity / insult / threat as utterance safety tags, PII only with evidence, backstops
for self-harm, grooming, sexual content, jailbreak). `command_context` (per call) gates model-only safety tags of a
cockpit command ("kill the heaters"). Its thresholds come from arctag_kids.json in the model folder when there is one,
else the library's built-in copy (src/kids_thr.inc, the same values: desktop/vendor/arctag/arctag_kids.json pins the
Hugging Face file). The other domains give byte-identical output to the 0.3 library on the same model files.
"""
from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from ._arctag_ffi import ffi
from ._cdefs import DEFINES
from .model_verify import verify_asset

HEADER_VERSION = (int(DEFINES["_arctag_ffi"]["ARCTAG_VERSION_MAJOR"]), int(DEFINES["_arctag_ffi"]["ARCTAG_VERSION_MINOR"]))


def load_library(lib_path: Path) -> ctypes.CDLL:
    """libarctag.dylib (macOS), libarctag.so (Linux) or arctag.dll (Windows; built by desktop/vendor/arctag/CMakeLists.txt
    with ARCTAG_BUILD_SHARED so the API is exported). On Windows the DLL's folder joins the DLL search path, so a
    dependency next to it (none today beyond the C runtime) resolves without touching PATH."""
    if sys.platform == "win32":  # untested on Windows (docs/DESKTOP.md)
        os.add_dll_directory(str(lib_path.resolve().parent))
        return ctypes.CDLL(str(lib_path), winmode=0)
    return ctypes.CDLL(str(lib_path))


_LOADED: list = []


def open_library(lib_path: Path):
    """load_library + the generated binding over the same handle + the version check. -> cffi lib."""
    h = load_library(lib_path)
    _LOADED.append(h)      # the ctypes handle stays referenced (libraries are never unloaded)
    try:
        L = ffi.dlopen(ffi.cast("void *", h._handle))
    except (TypeError, OSError, ffi.error):   # this cffi does not take a handle: by path (same file, already loaded)
        L = ffi.dlopen(str(lib_path))
    try:
        v = ffi.string(L.arctag_version()).decode()
    except (AttributeError, ffi.error):   # cffi: symbol not in the library
        raise RuntimeError(f"{lib_path} has no arctag_version(): not an Arc Tagger library") from None
    try:
        got = tuple(int(x) for x in v.split(".")[:2])
    except ValueError:
        got = None
    if got != HEADER_VERSION:
        raise RuntimeError(f"{lib_path} is Arc Tagger {v}, this model server's binding is for "
                           f"{HEADER_VERSION[0]}.{HEADER_VERSION[1]}.x (desktop/vendor/arctag/include/arctag.h): "
                           "rebuild it (make desktop-arctag) or reinstall the app")
    return L


def _str(p) -> str:
    return ffi.string(p).decode("utf-8", "replace") if p != ffi.NULL else ""


class ArcTagger:
    EMIT = "entity,number,pii,events,intent,act,safety,state"

    def __init__(self, lib_path: Path, model_dir: Path, domains: list[str], pool_size: int = 2):
        if not lib_path.exists():
            raise FileNotFoundError(f"Arc Tagger library not found: {lib_path} (set ARCTAG_LIB)")
        if not (model_dir / "arctag_int8.onnx").exists():
            raise FileNotFoundError(f"Arc Tagger model not found in {model_dir} (set ARCTAG_MODEL_DIR)")
        self.verify = verify_asset("tagger", model_dir, "The Arc Tagger model")
        self.L, self.model_dir = open_library(lib_path), model_dir
        self.version = _str(self.L.arctag_version())
        self.pools: dict[str, queue.Queue] = {}
        self._all: list = []
        self._lock = threading.Lock()
        self.streams = 0  # live dedicated stream handles (open_stream)
        for d in domains:
            q: queue.Queue = queue.Queue()
            for _ in range(pool_size):
                q.put(self._create(d))
            self.pools[d] = q

    def _create(self, domain: str, emit: str | None = None):
        o = ffi.new("arctag_options *")
        self.L.arctag_options_init(o)
        o.precision, o.backend = self.L.ARCTAG_INT8, self.L.ARCTAG_BACKEND_NATIVE  # int8, no ONNX Runtime
        err = ffi.new("char[]", 512)
        h = self.L.arctag_create_ex(str(self.model_dir).encode(), o, err, 512)
        if h == ffi.NULL:
            raise RuntimeError(f"arctag_create_ex failed: {_str(err)}")
        for k, v in (("domain", domain), ("emit", emit if emit is not None else self.EMIT)):
            if not v:
                continue
            if self.L.arctag_set_option(h, k.encode(), v.encode()) != 0:
                raise ValueError(f"arctag_set_option({k}={v}) failed")
        with self._lock:
            self._all.append(h)
        return h

    def _take(self, h, p) -> dict:
        if p == ffi.NULL:
            raise RuntimeError(f"arctag call failed: {_str(self.L.arctag_last_error(h)) or 'unknown'}")
        try:
            return json.loads(ffi.string(p).decode("utf-8"))
        finally:
            self.L.arctag_free_str(p)

    @contextmanager
    def handle(self, domain: str):
        if domain not in self.pools:
            raise KeyError(f"domain {domain!r} not loaded; loaded: {sorted(self.pools)}")
        h = self.pools[domain].get()
        try:
            yield h
        finally:
            self.L.arctag_reset(h)
            self.pools[domain].put(h)

    def tag_text(self, text: str, domain: str, command_context: bool | None = None) -> dict:
        """One text through a pooled handle. command_context (kids domain): the turn is a command on a game screen, so
        the guard gates model-only safety tags; it is set for this call only (the handle goes back with it off)."""
        with self.handle(domain) as h:
            if command_context is None:
                return self._take(h, self.L.arctag_tag_text(h, text.encode()))
            self.set_option(h, "command_context", "on" if command_context else "off")
            try:
                return self._take(h, self.L.arctag_tag_text(h, text.encode()))
            finally:
                self.L.arctag_set_option(h, b"command_context", b"off")

    def info(self) -> dict:
        d = next(iter(self.pools))
        with self.handle(d) as h:
            return self._take(h, self.L.arctag_info(h))

    # --- dedicated stream handles (one per WebSocket; never pooled, so stream state survives between calls) ---

    def open_stream(self, domain: str, emit: str | None = None):
        """A fresh handle owned by one caller. Raises KeyError for a domain this server didn't load."""
        if domain not in self.pools:
            raise KeyError(f"domain {domain!r} not loaded; loaded: {sorted(self.pools)}")
        h = self._create(domain, emit)
        with self._lock:
            self.streams += 1
        return h

    def close_stream(self, h):
        with self._lock:
            if h in self._all:
                self._all.remove(h)
                self.streams -= 1
            else:
                return  # already destroyed by close()
        self.L.arctag_destroy(h)

    def err(self, h) -> str:
        return _str(self.L.arctag_last_error(h))

    def set_option(self, h, key: str, value: str):
        if self.L.arctag_set_option(h, key.encode(), str(value).encode()) != 0:
            raise ValueError(f"arctag_set_option({key}={value}) failed: {self.err(h)}")

    def push_words(self, h, payload: bytes):
        """payload: a JSON list of words, or {"words", "from"?, "endpoint"?} (see Head Start's server/tagger.py)."""
        if self.L.arctag_push_words(h, payload) != 0:
            raise ValueError(f"arctag_push_words failed: {self.err(h)}")

    def poll(self, h) -> dict:
        return self._take(h, self.L.arctag_poll(h))

    def tag_text_on(self, h, text: str) -> dict:
        return self._take(h, self.L.arctag_tag_text(h, text.encode()))

    def reset(self, h):
        self.L.arctag_reset(h)

    def info_on(self, h) -> dict:
        return self._take(h, self.L.arctag_info(h))

    def close(self):
        with self._lock:
            for h in self._all:
                self.L.arctag_destroy(h)
            self._all.clear()
