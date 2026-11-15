"""Arc Transcriber Space (nft2) through libarc (C) + ONNX Runtime: the ear's model, without torch.

libarc is built from desktop/vendor/libarc (CMake; `make desktop-libarc`) as libarc.dylib / arc.dll / libarc.so. It links
no ONNX Runtime: `arc_ort_set_library()` points it at the runtime the Python `onnxruntime` wheel already ships
(onnxruntime/capi/libonnxruntime.*.dylib, onnxruntime.dll, libonnxruntime.so.*), so the app carries one copy.

    m = Nft2(lib, "…/arc-transcriber-space/nft2", threads=4)
    m.set_names([{"name": "Tycho", "kind": "lunar_feature"}, {"name": "Artemis II", "kind": "mission",
                  "aliases": ["Artemis 2"]}])
    out = m.transcribe(pcm_f32_16k)       # {"utts": [...], "names": [...], "numbers": [...], "events": [...], ...}

One model runs one call at a time (libarc's rule): calls take `m.lock`. The names list is the model's until changed
(biasing, the decoder's kb prompt, linking). Output is plain dicts (see `_result`); the transcript is SPOKEN form
("apollo twelve") with the decoder's casing and punctuation; route on names[i]["entity"], never on raw words.
"""
from __future__ import annotations

import ctypes as C
import glob
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

SR = 16000
KINDS = {"lunar_feature", "site", "celestial", "spacecraft", "vehicle", "mission", "crew", "person", "place",
         "organization", "product", "team", "law"}

c_char_p, c_int, c_float, c_double = C.c_char_p, C.c_int, C.c_float, C.c_double


class Tag(C.Structure):
    _fields_ = [("tag", c_char_p), ("word_begin", c_int), ("word_end", c_int), ("text", c_char_p)]


class Word(C.Structure):
    _fields_ = [("text", c_char_p), ("start", c_float), ("end", c_float), ("tag", c_char_p), ("tag_begin", c_int)]


class Label(C.Structure):
    _fields_ = [("label", c_char_p), ("p", c_float)]


class Utt(C.Structure):
    _fields_ = [("start", c_float), ("end", c_float), ("text", c_char_p), ("n_tags", c_int), ("tags", C.POINTER(Tag)),
                ("device_directed", c_float), ("command_complete", c_float), ("intent", Label), ("act", Label),
                ("directed_head", c_float), ("n_words", c_int), ("words", C.POINTER(Word)), ("n_alts", c_int),
                ("alts", C.POINTER(c_char_p)), ("alt_scores", C.POINTER(c_float)), ("decoder_text", c_char_p),
                ("directed", c_int)]


class Name(C.Structure):
    _fields_ = [("start", c_float), ("end", c_float), ("tag", c_char_p), ("heard", c_char_p), ("entity", c_char_p),
                ("kb_index", c_int), ("state", c_char_p), ("p", c_float), ("model_entity", c_char_p),
                ("model_p", c_float), ("src", c_char_p), ("via", c_char_p), ("snap_score", c_float),
                ("span_p", c_float), ("show", c_int), ("n_words", c_int), ("words", C.POINTER(Word))]


class Number(C.Structure):
    _fields_ = [("start", c_float), ("end", c_float), ("kind", c_char_p), ("unit", c_char_p), ("heard", c_char_p),
                ("has_value", c_int), ("has_value2", c_int), ("value", c_double), ("value2", c_double),
                ("value_int", c_int), ("value2_int", c_int), ("state", c_char_p), ("kind_head", c_char_p),
                ("has_value_model", c_int), ("value_model", c_double)]


class Event(C.Structure):
    _fields_ = [("label", c_char_p), ("start", c_float), ("end", c_float), ("p", c_float)]


class Result(C.Structure):
    _fields_ = [("n_utts", c_int), ("utts", C.POINTER(Utt)), ("n_events", c_int), ("events", C.POINTER(Event)),
                ("n_names", c_int), ("names", C.POINTER(Name)), ("n_numbers", c_int), ("numbers", C.POINTER(Number)),
                ("audio_s", c_float), ("wall_ms", c_float)]


class NameEntry(C.Structure):
    _fields_ = [("name", c_char_p), ("kind", c_char_p), ("group", c_char_p), ("aliases", C.POINTER(c_char_p)),
                ("n_aliases", c_int)]


class Context(C.Structure):
    _fields_ = [("dom", c_char_p), ("prev", c_char_p), ("auto_prev", c_int), ("kb", C.POINTER(c_char_p)),
                ("kb_kind", C.POINTER(c_char_p)), ("n_kb", c_int), ("speakers", C.c_void_p), ("n_speakers", c_int),
                ("numbers", C.c_void_p), ("n_numbers", c_int), ("entities", C.c_void_p), ("n_entities", c_int)]


class Options(C.Structure):
    _fields_ = [("domain", c_char_p), ("no_bias", c_int), ("no_events", c_int)]


def ort_library() -> Path | None:
    """The ONNX Runtime shared library inside the installed `onnxruntime` wheel (ARC_ORT_LIB overrides)."""
    if os.environ.get("ARC_ORT_LIB"):
        return Path(os.environ["ARC_ORT_LIB"])
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


def _s(b) -> str | None:
    return None if b is None else b.decode("utf-8", "replace")


def _f(x: float, nd: int = 3):
    return None if x is None or x < 0 else round(float(x), nd)


def _words(p, n: int) -> list[dict]:
    out = []
    for k in range(n):
        w = p[k]
        d = {"w": _s(w.text), "t0": round(w.start, 3), "t1": round(w.end, 3)}
        if w.tag:
            d["tag"], d["tag_begin"] = _s(w.tag), bool(w.tag_begin)
        out.append(d)
    return out


def _result(r: Result) -> dict:
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
            "intent": {"label": _s(u.intent.label), "p": _f(u.intent.p)} if u.intent.label else None,
            "act": {"label": _s(u.act.label), "p": _f(u.act.p)} if u.act.label else None,
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

    def __init__(self, lib: Path | str, model_dir: Path | str, threads: int = 4, ort: Path | str | None = None):
        self.lib_path, self.dir = Path(lib), Path(model_dir)
        if not self.lib_path.exists():
            raise FileNotFoundError(f"libarc not found: {self.lib_path} (make desktop-libarc)")
        if not (self.dir / "config.json").exists():
            raise FileNotFoundError(f"Arc Transcriber Space model not found: {self.dir} (needs nft2/config.json)")
        self.L = L = C.CDLL(str(self.lib_path))
        L.arc_ort_set_library.argtypes, L.arc_ort_set_library.restype = [c_char_p], c_int
        L.arc_ort_error.restype = c_char_p
        L.arc_nft2_create.argtypes = [c_char_p, c_int, c_char_p, C.c_size_t]
        L.arc_nft2_create.restype = C.c_void_p
        L.arc_nft2_destroy.argtypes = [C.c_void_p]
        L.arc_nft2_backend.restype = c_char_p
        L.arc_nft2_set_names.argtypes, L.arc_nft2_set_names.restype = [C.c_void_p, C.POINTER(NameEntry), c_int], c_int
        L.arc_nft2_set_context.argtypes, L.arc_nft2_set_context.restype = [C.c_void_p, C.POINTER(Context)], c_int
        L.arc_nft2_transcribe.argtypes = [C.c_void_p, C.POINTER(c_float), C.c_size_t, C.POINTER(Options)]
        L.arc_nft2_transcribe.restype = C.POINTER(Result)
        L.arc_result_free.argtypes = [C.POINTER(Result)]
        L.arc_last_error.restype = c_char_p
        ort = Path(ort) if ort else ort_library()
        if ort is None:
            raise RuntimeError("ONNX Runtime library not found (pip onnxruntime, or set ARC_ORT_LIB)")
        if L.arc_ort_set_library(str(ort).encode()) != 0:
            raise RuntimeError(f"ONNX Runtime: {_s(L.arc_ort_error())}")
        self.ort = ort
        err = C.create_string_buffer(1024)
        t = time.perf_counter()
        self.m = L.arc_nft2_create(str(self.dir).encode(), int(threads), err, len(err))
        if not self.m:
            raise RuntimeError(f"arc_nft2_create: {err.value.decode('utf-8', 'replace')}")
        self.load_s = round(time.perf_counter() - t, 2)
        self.backend = _s(L.arc_nft2_backend())
        self.lock = threading.RLock()
        self.names: list[dict] = []
        self._names_key = None
        self._keep: list = []      # the C side copies names / context, but keep the last buffers alive anyway

    def close(self) -> None:
        with self.lock:
            if self.m:
                self.L.arc_nft2_destroy(self.m)
                self.m = None

    # ---- context ----
    def set_names(self, names: list[dict]) -> int:
        """[{"name", "kind", "aliases"?, "group"?}] in priority order (the first ~10-15 reach the decoder prompt)."""
        ns = [n for n in (normalize_entry(x) for x in names or []) if n]
        arr = (NameEntry * max(1, len(ns)))()
        keep = []
        for i, n in enumerate(ns):
            al = [a.encode() for a in n.get("aliases") or []]
            ap = (c_char_p * max(1, len(al)))(*al)
            keep.append(ap)
            arr[i] = NameEntry(n["name"].encode(), (n.get("kind") or "").encode() or None,
                               (n.get("group") or "").encode() or None, ap, len(al))
        with self.lock:
            rc = self.L.arc_nft2_set_names(self.m, arr, len(ns))
            self._keep = [arr, keep]
            self.names = ns
            self._names_key = None
        if rc != 0:
            raise RuntimeError(f"arc_nft2_set_names: {_s(self.L.arc_last_error())}")
        return len(ns)

    def set_context(self, prev: str | None = None, dom: str | None = None, auto_prev: bool = False) -> None:
        c = Context(dom.encode() if dom is not None else None, prev.encode() if prev else None, int(auto_prev),
                    None, None, 0, None, 0, None, 0, None, 0)
        with self.lock:
            self.L.arc_nft2_set_context(self.m, C.byref(c))

    # ---- decoding ----
    def transcribe(self, pcm: np.ndarray, domain: str = "assistant", no_events: bool = False, no_bias: bool = False,
                   names: list[dict] | None = None) -> dict:
        """A whole clip (16 kHz mono float32). Up to 20 s is one utterance; longer clips are segmented by Arc."""
        x = np.ascontiguousarray(pcm, dtype=np.float32)
        o = Options(domain.encode(), int(no_bias), int(no_events))
        with self.lock:
            if names is not None and repr(names) != self._names_key:
                self.set_names(names)
                self._names_key = repr(names)
            t = time.perf_counter()
            r = self.L.arc_nft2_transcribe(self.m, x.ctypes.data_as(C.POINTER(c_float)), len(x), C.byref(o))
            ms = (time.perf_counter() - t) * 1000
            if not r:
                raise RuntimeError(f"arc_nft2_transcribe: {_s(self.L.arc_last_error())}")
            try:
                out = _result(r.contents)
            finally:
                self.L.arc_result_free(r)
        out["ms"] = round(ms, 1)
        return out


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
