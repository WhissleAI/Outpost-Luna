"""The ear's model: Arc Transcriber Space (WhissleAI/arc-transcriber-space, nft2/) on libarc + ONNX Runtime (app/nft2.py).

One model, loaded once at startup (ARC_EAR=on, the default; ARC_EAR=off or ARC_META=off skips it), serves:
  ear       WS /v1/stream?ear=arc (app/arc_ear.py): words, turns, names linked to the screen's list, sound events and
            the device-directed flag, from the kid's microphone
  metadata  WS /v1/stream (no ear=arc; the Deepgram fallback path): the same stream, only its `arc` messages
  offline   POST /v1/meta (backend/pipeline/build_audio_meta.py): per-utterance events, device-directed and awe

It replaced Arc v1.1 Mini on torch + transformers (and the round-7 hot-list logits processor): ~0.85 GB of RAM instead of
~2.3 GB, a ~2 s load, and no torch in the installer. The model is trained to ignore synthetic (Kokoro-style) TTS, so test it
with real voices; the app's own Siri/Nora voices are still transcribed (the router's echo check handles those).

Emotion: none (the model has no emotion head). Age / gender are never emitted: this is a kids' app.
"""
from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path

import numpy as np
from pydantic_settings import BaseSettings, SettingsConfigDict

SR = 16000
MODEL = "arc-transcriber-space nft2"
ARC_REPO, ARC_REVISION = "WhissleAI/arc-transcriber-space", "176d32449b070893739db21e15ea5320af005a68"
MS = Path(__file__).resolve().parents[1]                     # model_server/
LIB_NAMES = {"darwin": ["libarc.dylib"], "win32": ["arc.dll", "libarc.dll"]}.get(sys.platform, ["libarc.so"])


class MetaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    arc_ear: str = "on"            # on | off: load the model
    arc_meta: str = "on"           # (kept for old env files: off also skips the load)
    # The nft2/ folder (config.json, adapters.safetensors, model.q4.safetensors, tags.json, decoder/, encoder_onnx/).
    # Default: model_server/models/arc-space/nft2 (make ear-model), else the HF cache. The desktop app sets its download.
    arc_space_dir: Path | None = None
    # libarc (desktop/vendor/libarc, make desktop-libarc). Default: desktop/build/libarc, else model_server/models/native.
    arc_lib: Path | None = None
    arc_threads: int = 4
    meta_max_sessions: int = 4
    emotion: str = "off"


meta_settings = MetaSettings()

EMOTION_REASON = "Arc Transcriber Space has no emotion output."

STATE: dict = {"arc": None, "error": None, "load_s": None, "sessions": 0, "decoder": False, "rss_mb": None,
               "rss_delta_mb": None, "model_dir": None, "lib": None, "backend": None, "engine": None,
               "resets": 0, "last_reset": None}   # the decode watchdog (app/decode_watchdog.py, #87)
_lock = threading.Lock()


def model_dir() -> Path | None:
    if meta_settings.arc_space_dir is not None:
        return meta_settings.arc_space_dir
    p = MS / "models/arc-space/nft2"
    if (p / "config.json").exists():
        return p
    from .config import hf_snapshot
    s = hf_snapshot(ARC_REPO, "nft2/config.json", prefer=ARC_REVISION)
    return s / "nft2" if s else None


def lib_path() -> Path | None:
    if meta_settings.arc_lib is not None:
        return meta_settings.arc_lib
    for d in (MS.parent / "desktop/build/libarc", MS.parent / "desktop/build/libarc/Release", MS / "models/native",
              MS.parent / "desktop/resources/native"):
        for n in LIB_NAMES:
            if (d / n).exists():
                return d / n
    return None


def load() -> None:
    """Load the model at startup. Fails open: the reason goes to /health."""
    if "off" in (meta_settings.arc_ear.strip().lower(), meta_settings.arc_meta.strip().lower()):
        STATE["error"] = "ARC_EAR=off (disabled)"
        return
    t = time.perf_counter()
    rss0 = _rss_mb()
    try:
        from .nft2 import Nft2
        d, lib = model_dir(), lib_path()
        if d is None or not (d / "config.json").exists():
            raise FileNotFoundError(f"Arc Transcriber Space not found ({d or ARC_REPO + ' not downloaded'}); "
                                    "set ARC_SPACE_DIR to its nft2/ folder")
        if lib is None:
            raise FileNotFoundError("libarc not built (make desktop-libarc) or ARC_LIB not set")
        m = Nft2(lib, d, threads=meta_settings.arc_threads)
        rng = np.random.default_rng(0)      # warm every path once, so the first kid turn doesn't pay for it
        m.transcribe((rng.standard_normal(SR) * 0.01).astype(np.float32))
        STATE.update(arc=m, decoder=True, model_dir=str(d), lib=str(lib), backend=m.backend, engine=m.info(),
                     error=None)   # a load that works clears an earlier failure (a reload after a hung decode)
        _load_room(d)
    except Exception as e:  # noqa: BLE001
        STATE["arc"] = None
        STATE["error"] = f"{type(e).__name__}: {e}"[:300]
    STATE["load_s"] = round(time.perf_counter() - t, 2)
    STATE["rss_mb"] = _rss_mb()
    if rss0 is not None and STATE["rss_mb"] is not None:
        STATE["rss_delta_mb"] = round(STATE["rss_mb"] - rss0, 1)


def _load_room(d: Path) -> None:
    """Arc Transcriber Space v2's room read-outs (nft2/room.onnx, app/arc_room.py) next to the ear; EAR_ROOM=off skips
    them. Fails open: the ear never depends on them."""
    import os
    from . import arc_room
    if os.environ.get("EAR_ROOM", "shadow").strip().lower() in ("off", "0", "false", "no"):
        arc_room.STATE.update(room=None, error="EAR_ROOM=off")
        return
    if arc_room.STATE["room"] is None:
        arc_room.load(d, threads=1)


def _wheel_version() -> str | None:
    """The pip onnxruntime wheel's version (the embedder and Steer TTS run on it): pinned to the same version as the
    runtime next to libarc (desktop/vendor/libarc/onnxruntime.lock.json, model_server/tests/test_bindings.py)."""
    try:
        from importlib.metadata import version
        return version("onnxruntime")
    except Exception:  # noqa: BLE001
        return None


def _rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e6, 1)
    except Exception:  # noqa: BLE001
        return None


def health() -> dict:
    up = STATE["arc"] is not None
    return {
        "arc_meta": {"loaded": up, "error": STATE["error"], "model": MODEL, "load_s": STATE["load_s"],
                     "sessions": STATE["sessions"], "max_sessions": meta_settings.meta_max_sessions},
        "arc_ear": {"available": up, "model": MODEL, "revision": ARC_REVISION[:7], "backend": STATE["backend"],
                    "decoder_loaded": up, "load_s": STATE["load_s"], "rss_after_load_mb": STATE["rss_mb"],
                    "rss_load_delta_mb": STATE["rss_delta_mb"], "rss_now_mb": _rss_mb(),
                    # libarc ABI / version, the ONNX Runtime it runs on (pinned | wheel | env) and the model files'
                    # sha256 check (app/nft2.py, app/model_verify.py)
                    "engine": STATE["engine"], "ort_wheel": _wheel_version()},
        "arc_room": _room_health(),
        "emotion": {"loaded": False, "enabled": False, "reason": EMOTION_REASON},
        "watchdog": {"resets": STATE["resets"], "last_reset": STATE["last_reset"]},
    }


def _room_health() -> dict:
    from . import arc_room
    return arc_room.health()


def reset_after_hang(model, reason: str, reload=None) -> bool:
    """The decode watchdog gave up on a call into `model` (app/decode_watchdog.py): drop that handle, so no new
    session queues behind the stuck call, and load a fresh one in the background (the stuck thread keeps the old one
    until it returns, if it ever does). False when `model` is no longer the live handle (another stream reset it)."""
    with _lock:
        if model is None or STATE["arc"] is not model:
            return False
        STATE["arc"] = None
        STATE["error"] = f"reloading after a hung decode ({reason})"[:300]
        STATE["resets"] += 1
        STATE["last_reset"] = {"at": round(time.time()), "reason": reason[:200]}
    from . import diag   # [#92] model resets, in the metrics and the log
    diag.METRICS.inc("model_resets", model="arc_ear")
    diag.LOG.warning("model_reset", model="arc_ear", reason=reason)
    threading.Thread(target=reload or _reload, name="arc-reload", daemon=True).start()
    return True


def _reload() -> None:
    load()
    if STATE["arc"] is not None:
        STATE["error"] = None


# ------------------------------------------------------------------------------------------------------------ events
# Sound events the app reacts to. meta.* are channel facts (telephone, narrowband, clipping): kept out of audio_events
# (they're on every NASA radio clip), but `meta.degraded_audio` etc. still reach /v1/meta callers through `channel`.
EVENT_MIN_P = 0.3


def audio_events(evs: list[dict], t0: float | None = None, t1: float | None = None) -> list[dict]:
    """Non-meta sound events (>= EVENT_MIN_P) overlapping [t0, t1], merged per label (max p)."""
    best: dict[str, dict] = {}
    for e in evs or []:
        lab = e.get("label") or ""
        if not lab or lab.startswith("meta.") or lab == "scene.silence" or (e.get("p") or 0) < EVENT_MIN_P:
            continue
        if t0 is not None and (e["t1"] < t0 or e["t0"] > t1):
            continue
        b = best.get(lab)
        if b is None or e["p"] > b["p"]:
            best[lab] = {"label": lab, "t0": e["t0"], "t1": e["t1"], "p": round(float(e["p"]), 3)}
    return sorted(best.values(), key=lambda x: -x["p"])


# ------------------------------------------------------------------------------------------------------------ awe
# Awe heuristic (0..1 per utterance), for "crew moments" highlights:
#   events: for scene.laughter / scene.cheer / scene.applause (weight 1.0) and scene.scream (0.6), the utterance's max p
#           MINUS the clip's median of that label over all utterances, x2, clipped to 0..1 (relative: radio audio
#           saturates some events); a single-utterance call has no baseline and uses the raw p.
#   words:  exclamation words (wow, whoa, amazing, ...) and words ending in "!", 0.35 each, capped at 1
#   awe = 0.35 * events + 0.65 * words. Uncalibrated; it ranks moments within a clip.
AWE_EVENTS = {"scene.laughter": 1.0, "scene.cheer": 1.0, "scene.applause": 1.0, "scene.scream": 0.6}
AWE_WORDS = re.compile(r"^(wow+|whoa+|woah|amazing|incredible|beautiful|gorgeous|spectacular|awesome|unbelievable|"
                       r"gosh|cool|stunning|magnificent|wonderful|holy|yay|ooh+)$", re.I)


def _words_score(words: list[dict]) -> float:
    n = 0
    for w in words:
        raw = str(w.get("w", ""))
        tok = re.sub(r"[^\w']", "", raw)
        if raw.endswith("!") or AWE_WORDS.match(tok or "-"):
            n += 1
    return min(1.0, 0.35 * n)


def _awe_events(evs: list[dict]) -> dict[str, float]:
    return {e["label"]: e["p"] for e in evs if e["label"] in AWE_EVENTS}


def awe_score(evs: list[dict], words: list[dict], baseline: dict[str, float] | None = None) -> float:
    ev = 0.0
    for lab, p in _awe_events(evs).items():
        x = p if baseline is None else min(1.0, max(0.0, 2 * (p - baseline.get(lab, 0.0))))
        ev = max(ev, AWE_EVENTS[lab] * x)
    return round(0.35 * ev + 0.65 * _words_score(words), 2)


def norm_words(words) -> list[dict]:
    out = []
    for w in words or []:
        t0, t1 = float(w.get("t0", w.get("start", 0.0))), float(w.get("t1", w.get("end", 0.0)))
        txt = str(w.get("w", w.get("word", ""))).strip()
        if txt:
            out.append({"w": txt, "t0": t0, "t1": max(t1, t0)})
    return out


def predict(wav: np.ndarray, words=None, domain: str = "assistant", events: str = "default", names=None) -> dict:
    """A whole clip: the model's own utterances (or, with `words`, the caller's words grouped into them) with their
    sound events, device-directed head and awe. Shape kept from the Arc v1.1 Mini version (build_audio_meta.py)."""
    m = STATE["arc"]
    if m is None:
        raise RuntimeError(f"Arc not loaded: {STATE['error']}")
    ws = norm_words(words)
    t = time.perf_counter()
    out = m.transcribe(wav, domain=domain, names=names or [])
    ms = (time.perf_counter() - t) * 1000
    utts = []
    for u in out["utts"]:
        t0, t1 = float(u["t0"]), float(u["t1"])
        uw = [w for w in ws if w["t1"] >= t0 - 0.2 and w["t0"] <= t1 + 0.2] if ws else u["words"]
        utts.append({"t0": t0, "t1": t1, "speaker": None, "act": u["act"], "intent": u["intent"],
                     "device_directed": u["directed_head"], "directed": u["directed"],
                     "audio_events": audio_events(out["events"], t0, t1), "bio_events": [],
                     "text": " ".join(w["w"] for w in uw), "transcript": u["text"], "_w": uw})
    base = {}
    if len(utts) >= 3:
        for lab in AWE_EVENTS:
            base[lab] = float(np.median([_awe_events(u["audio_events"]).get(lab, 0.0) for u in utts]))
    for u in utts:
        u["awe"] = awe_score(u["audio_events"], u.pop("_w"), base if len(utts) >= 3 else None)
    dur = len(wav) / SR
    return {"model": MODEL, "domain": domain, "audio_s": round(dur, 2), "ms": round(ms, 1),
            "rtf": round(ms / 1000 / dur, 3) if dur else None, "utterances": utts, "names": out["names"],
            "channel": sorted({e["label"] for e in out["events"] if e["label"].startswith("meta.") and e["p"] >= 0.5}),
            "command_complete": []}


# ------------------------------------------------------------------------------------------------------------ live
def admit() -> bool:
    with _lock:
        if STATE["arc"] is None or STATE["sessions"] >= meta_settings.meta_max_sessions:
            return False
        STATE["sessions"] += 1
        return True


def release() -> None:
    with _lock:
        STATE["sessions"] = max(0, STATE["sessions"] - 1)
