"""Arc Tagger v0.3 through its C API (ctypes), with a small pool of handles per domain.

The C library is arc-tagger-c (`arctag_create_ex`, `arctag_tag_text`, ...). One handle holds one stream's state and
is not thread-safe, so requests borrow a handle from a per-domain pool and reset it before returning it.
"""
from __future__ import annotations

import ctypes
import json
import queue
import threading
from contextlib import contextmanager
from pathlib import Path


class _Opts(ctypes.Structure):
    _fields_ = [("size", ctypes.c_size_t), ("precision", ctypes.c_int), ("threads", ctypes.c_int),
                ("model_file", ctypes.c_char_p), ("backend", ctypes.c_int)]


class ArcTagger:
    EMIT = "entity,number,pii,events,intent,act,safety,state"

    def __init__(self, lib_path: Path, model_dir: Path, domains: list[str], pool_size: int = 2):
        if not lib_path.exists():
            raise FileNotFoundError(f"Arc Tagger library not found: {lib_path} (set ARCTAG_LIB)")
        if not (model_dir / "arctag_int8.onnx").exists():
            raise FileNotFoundError(f"Arc Tagger model not found in {model_dir} (set ARCTAG_MODEL_DIR)")
        L = ctypes.CDLL(str(lib_path))
        L.arctag_options_init.argtypes = [ctypes.POINTER(_Opts)]
        L.arctag_create_ex.argtypes = [ctypes.c_char_p, ctypes.POINTER(_Opts), ctypes.c_char_p, ctypes.c_size_t]
        L.arctag_create_ex.restype = ctypes.c_void_p
        for fn in ("arctag_tag_text", "arctag_info"):
            getattr(L, fn).restype = ctypes.c_void_p
        L.arctag_tag_text.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        L.arctag_info.argtypes = [ctypes.c_void_p]
        L.arctag_set_option.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        L.arctag_set_option.restype = ctypes.c_int
        L.arctag_reset.argtypes = [ctypes.c_void_p]
        L.arctag_destroy.argtypes = [ctypes.c_void_p]
        L.arctag_free_str.argtypes = [ctypes.c_void_p]
        L.arctag_last_error.argtypes = [ctypes.c_void_p]
        L.arctag_last_error.restype = ctypes.c_char_p
        self.L, self.model_dir = L, model_dir
        self.pools: dict[str, queue.Queue] = {}
        self._all: list[int] = []
        self._lock = threading.Lock()
        for d in domains:
            q: queue.Queue = queue.Queue()
            for _ in range(pool_size):
                q.put(self._create(d))
            self.pools[d] = q

    def _create(self, domain: str) -> int:
        o = _Opts()
        self.L.arctag_options_init(ctypes.byref(o))
        o.precision, o.backend = 1, 1  # int8, native backend (no ONNX Runtime)
        err = ctypes.create_string_buffer(512)
        h = self.L.arctag_create_ex(str(self.model_dir).encode(), ctypes.byref(o), err, 512)
        if not h:
            raise RuntimeError(f"arctag_create_ex failed: {err.value.decode(errors='replace')}")
        for k, v in (("domain", domain), ("emit", self.EMIT)):
            if self.L.arctag_set_option(h, k.encode(), v.encode()) != 0:
                raise ValueError(f"arctag_set_option({k}={v}) failed")
        with self._lock:
            self._all.append(h)
        return h

    def _take(self, h, p) -> dict:
        if not p:
            e = self.L.arctag_last_error(h)
            raise RuntimeError(f"arctag call failed: {e.decode(errors='replace') if e else 'unknown'}")
        try:
            return json.loads(ctypes.string_at(p).decode("utf-8"))
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

    def tag_text(self, text: str, domain: str) -> dict:
        with self.handle(domain) as h:
            return self._take(h, self.L.arctag_tag_text(h, text.encode()))

    def info(self) -> dict:
        d = next(iter(self.pools))
        with self.handle(d) as h:
            return self._take(h, self.L.arctag_info(h))

    def close(self):
        with self._lock:
            for h in self._all:
                self.L.arctag_destroy(h)
            self._all.clear()
