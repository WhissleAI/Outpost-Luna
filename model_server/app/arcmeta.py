"""Arc v1.1 Mini audio metadata (ARC_META=mini|off), the same model and package Head Start loads.

Two live modes share one loaded model (weights loaded once, per-stream state):
  metadata (MetaStream, /v1/stream): external-transcript mode: the words come from someone else (Deepgram live, Whisper
    offline) and Arc only listens to the audio for its heads: utterance act / intent, device_directed, command_complete,
    speaker, audio events (laughter, cheer, ...) and bio events. Never falls back to its own transcript (fallback=None).
  ear (arc_ear.EarStream, /v1/stream?ear=arc): Arc's own decoder gives the words and the turns as well. Needs the
    decoder (ARC_EAR=on, the default); ARC_EAR=off loads the heads only (load_decoder=False), as before.

Emotion: Arc v1.1 Mini lists affect.emotion.* in tags.json (experimental) but its readout exposes none of them for any
domain, even with include_experimental=True, and the STT-meta-1B weights are not on this machine. So EMOTION stays off
(see docs/REVAMP.md section 10). Age / gender are never emitted: this is a kids' app.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import numpy as np
from pydantic_settings import BaseSettings, SettingsConfigDict

SR = 16000
CC = "discourse.assistant.command_complete"
DD = "discourse.assistant.device_directed"


ARC_REPO, ARC_REVISION = "WhissleAI/arc-v1.1", "6f637153ea4953d81811e68168cd29572316d32b"


def weights_dir() -> Path | None:
    """Where Arc v1.1 Mini loads from. Never a repo id: Arc.from_pretrained would then download."""
    if meta_settings.arc_meta_weights is not None:
        return meta_settings.arc_meta_weights
    from .config import hf_snapshot
    return hf_snapshot(ARC_REPO, "mini/config.json", prefer=ARC_REVISION)


class MetaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    arc_meta: str = "mini"   # mini | off
    # A folder with mini/ (config.json, tags.json, *.safetensors, moonshine-streaming-tiny/). Default: the Arc v1.1
    # snapshot in the local HF cache (the one Head Start's ARC_T_WEIGHTS points at). The desktop app sets its bundled copy.
    arc_meta_weights: Path | None = None
    arc_meta_threads: int = 4
    meta_max_sessions: int = 4
    emotion: str = "off"     # on | off (on is not possible yet: see module docstring)


meta_settings = MetaSettings()

EMOTION_REASON = ("Arc v1.1 Mini has no emotion output (affect.emotion.* is in tags.json but not in the readout for any "
                  "domain); STT-meta-1B weights are not in the local HF cache. See docs/REVAMP.md section 10.")

STATE: dict = {"arc": None, "error": None, "load_s": None, "sessions": 0, "decoder": False, "rss_mb": None,
               "rss_delta_mb": None}
_lock = threading.Lock()


def load() -> None:
    """Load Arc v1.1 Mini at startup. Fails open: the reason goes to /health."""
    v = meta_settings.arc_meta.strip().lower()
    if v != "mini":
        STATE["error"] = f"ARC_META={v} (disabled)"
        return
    t = time.perf_counter()
    rss0 = _rss_mb()
    try:
        from arc_audio import Arc

        from .arc_ear import ear_settings
        dec = ear_settings.arc_ear.strip().lower() == "on"
        wdir = weights_dir()
        if wdir is None or not (wdir / "mini/config.json").exists():
            raise FileNotFoundError(f"Arc v1.1 Mini weights not found ({wdir or ARC_REPO + ' not in the HF cache'}); "
                                    "set ARC_META_WEIGHTS to a folder with mini/")
        STATE["arc"] = Arc.from_pretrained(str(wdir), backbone="mini", device="cpu",
                                           threads=meta_settings.arc_meta_threads, load_decoder=dec)
        STATE["decoder"] = dec
        warm = np.zeros(SR, np.float32)
        STATE["arc"].predict(warm, domain="assistant", transcript="external", words=[], fallback=None,
                             return_frames=False)
        if dec:   # warm the decoder path too, so the first ear connection doesn't pay for it
            ws = STATE["arc"].stream(domain="assistant", transcript="builtin", partials=True, fallback=None)
            rng = np.random.default_rng(0)
            for i in range(10):
                ws.feed(rng.standard_normal(1600).astype(np.float32) * (0.05 if i < 5 else 0.0005))
            ws.flush()
            ws.close()
    except Exception as e:  # noqa: BLE001
        STATE["arc"] = None
        STATE["error"] = f"{type(e).__name__}: {e}"[:300]
    STATE["load_s"] = round(time.perf_counter() - t, 2)
    STATE["rss_mb"] = _rss_mb()
    if rss0 is not None and STATE["rss_mb"] is not None:
        STATE["rss_delta_mb"] = round(STATE["rss_mb"] - rss0, 1)


def _rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e6, 1)
    except Exception:  # noqa: BLE001
        return None


def health() -> dict:
    return {
        "arc_meta": {"loaded": STATE["arc"] is not None, "error": STATE["error"], "model": "arc-v1.1 mini",
                     "load_s": STATE["load_s"], "sessions": STATE["sessions"],
                     "max_sessions": meta_settings.meta_max_sessions},
        "arc_ear": {"available": STATE["arc"] is not None and STATE["decoder"], "decoder_loaded": STATE["decoder"],
                    "load_s": STATE["load_s"], "rss_after_load_mb": STATE["rss_mb"], "rss_load_delta_mb": STATE["rss_delta_mb"],
                    "rss_now_mb": _rss_mb()},
        "emotion": {"loaded": False, "enabled": False, "reason": EMOTION_REASON},
    }


# ------------------------------------------------------------------------------------------------------------ awe
# Awe heuristic (0..1 per utterance), for "crew moments" highlights:
#   events: for scene.laughter / scene.cheer / scene.applause (weight 1.0) and scene.scream (0.6: gasps and shrieks of
#           surprise land there, but it also fires on noise), the utterance's max p MINUS the clip's median of that
#           label over all utterances, x2, clipped to 0..1. Relative, because these experimental events saturate on
#           air-to-ground radio audio (laughter p>0.9 through most of a clip); an absolute p would mark everything.
#           A single-utterance call (and the live stream) has no clip baseline and uses the raw p.
#   words:  exclamation words (wow, whoa, amazing, beautiful, incredible, gosh, awesome, ...) and words ending in
#           "!", 0.35 each, capped at 1
#   awe = 0.35 * events + 0.65 * words, rounded to 2 places.
# Uncalibrated; it ranks moments within a clip, it is not a probability.
AWE_EVENTS = {"scene.laughter": 1.0, "scene.cheer": 1.0, "scene.applause": 1.0, "scene.scream": 0.6}
AWE_WORDS = re.compile(r"^(wow+|whoa+|woah|amazing|incredible|beautiful|gorgeous|spectacular|awesome|unbelievable|"
                       r"gosh|cool|stunning|magnificent|wonderful|holy|yay|ooh+)$", re.I)
EVENT_MIN_P = 0.3


def _words_score(words: list[dict]) -> float:
    n = 0
    for w in words:
        raw = str(w.get("w", ""))
        tok = re.sub(r"[^\w']", "", raw)
        if raw.endswith("!") or AWE_WORDS.match(tok or "-"):
            n += 1
    return min(1.0, 0.35 * n)


def _awe_events(audio_events: list[dict]) -> dict[str, float]:
    return {e["label"]: e["p"] for e in audio_events if e["label"] in AWE_EVENTS}


def awe_score(audio_events: list[dict], words: list[dict], baseline: dict[str, float] | None = None) -> float:
    ev = 0.0
    for lab, p in _awe_events(audio_events).items():
        x = p if baseline is None else min(1.0, max(0.0, 2 * (p - baseline.get(lab, 0.0))))
        ev = max(ev, AWE_EVENTS[lab] * x)
    return round(0.35 * ev + 0.65 * _words_score(words), 2)


# ------------------------------------------------------------------------------------------------------------ offline
def norm_words(words) -> list[dict]:
    out = []
    for w in words or []:
        t0, t1 = float(w.get("t0", w.get("start", 0.0))), float(w.get("t1", w.get("end", 0.0)))
        txt = str(w.get("w", w.get("word", ""))).strip()
        if txt:
            out.append({"w": txt, "t0": t0, "t1": max(t1, t0)})
    return out


def _events_in(evs: list[dict], t0: float, t1: float) -> list[dict]:
    """Audio events overlapping [t0, t1], merged per label (max p), meta.* (channel, room, snr) left out."""
    best: dict[str, dict] = {}
    for e in evs:
        lab = e.get("label") or e.get("tag")
        if not lab or lab.startswith("meta.") or lab == "scene.silence" or (e.get("p") or 0) < EVENT_MIN_P:
            continue
        if e["end"] < t0 or e["start"] > t1:
            continue
        b = best.get(lab)
        if b is None or e["p"] > b["p"]:
            best[lab] = {"label": lab, "t0": e["start"], "t1": e["end"], "p": round(float(e["p"]), 3)}
    return sorted(best.values(), key=lambda x: -x["p"])


def _bio_in(bio: list[dict], t0: float, t1: float) -> list[dict]:
    return [{"tag": b.get("tag"), "t": b.get("t"), "p": b.get("p")} for b in bio
            if b.get("t") is not None and t0 <= b["t"] <= t1 and (b.get("p") or 0) >= EVENT_MIN_P]


def _label(g: dict | None):
    return None if not g else {"label": g.get("label"), "p": g.get("p")}


def predict(wav: np.ndarray, words=None, domain: str = "assistant", events: str = "default") -> dict:
    arc = STATE["arc"]
    if arc is None:
        raise RuntimeError(f"Arc metadata not loaded: {STATE['error']}")
    ws = norm_words(words)
    t = time.perf_counter()
    out = arc.predict(wav, domain=domain, transcript="external", words=ws, fallback=None, return_frames=False,
                      events="all" if events == "all" else "default")
    ms = (time.perf_counter() - t) * 1000
    aev, bio = out.get("audio_events") or [], out.get("bio_events") or []
    utts = []
    for u in out.get("utterances") or []:
        t0, t1 = float(u["start"]), float(u["end"])
        g = u.get("groups") or {}
        uw = [w for w in ws if w["t1"] >= t0 - 0.2 and w["t0"] <= t1 + 0.2]
        ae = _events_in(aev, t0, t1)
        utts.append({
            "t0": t0, "t1": t1, "speaker": u.get("speaker"),
            "act": _label(g.get("discourse.act")), "intent": _label(g.get("discourse.intent")),
            "device_directed": (u.get("tags") or {}).get(DD),
            "audio_events": ae, "bio_events": _bio_in(bio, t0, t1),
            "text": " ".join(w["w"] for w in uw),
            "_w": uw,
        })
    base = {}
    if len(utts) >= 3:
        for lab in AWE_EVENTS:
            base[lab] = float(np.median([_awe_events(u["audio_events"]).get(lab, 0.0) for u in utts]))
    for u in utts:
        u["awe"] = awe_score(u["audio_events"], u.pop("_w"), base if len(utts) >= 3 else None)
    dur = len(wav) / SR
    return {"model": "arc-v1.1 mini", "domain": domain, "audio_s": round(dur, 2), "ms": round(ms, 1),
            "rtf": round(ms / 1000 / dur, 3) if dur else None, "utterances": utts,
            "command_complete": [{"t": e.get("t"), "p": e.get("p")} for e in out.get("events") or []
                                 if e.get("tag") == CC]}


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


class MetaStream:
    """One live session. Not thread-safe: call it from one worker thread only (routes_meta does)."""

    def __init__(self, domain: str = "assistant"):
        self.s = STATE["arc"].stream(domain=domain, transcript="external", name_source="word",
                                     interim_source="deepgram", partials=False, fallback=None, events="all")
        self.last_key = None
        self.compute_s = 0.0
        self.audio_s = 0.0

    def add_words(self, words) -> None:
        ws = norm_words(words)
        if ws:
            self.s.add_words(ws)

    def feed(self, pcm16: bytes) -> dict | None:
        x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        t = time.perf_counter()
        out = self.s.feed(x)
        self.compute_s += time.perf_counter() - t
        self.audio_s += len(x) / SR
        return self._summary(out)

    def end_turn(self) -> dict | None:
        return self._summary(self.s.end_turn(), force=True)

    def flush(self) -> dict | None:
        return self._summary(self.s.flush(), force=True)

    def close(self) -> None:
        try:
            self.s.close()
        except Exception:  # noqa: BLE001
            pass

    def _summary(self, out: dict, force: bool = False) -> dict | None:
        lv = out.get("live") or {}
        u = lv.get("utt") or {}
        sp = lv.get("speaker") or {}
        top = lambda xs: (xs or [None])[0]  # noqa: E731
        ae = [{"label": e.get("label"), "t0": e.get("start"), "t1": e.get("end"), "p": e.get("p")}
              for e in out.get("audio_events") or []
              if not str(e.get("label", "")).startswith("meta.") and (e.get("p") or 0) >= EVENT_MIN_P]
        bio = [{"tag": b.get("tag"), "t": b.get("t"), "p": b.get("p")} for b in out.get("bio_events") or []]
        cc_ev = [{"t": e.get("t"), "p": e.get("p")} for e in out.get("events") or [] if e.get("tag") == CC]
        cc = u.get("command_complete")
        dd = u.get("device_directed")
        m = {"t": "arc", "at": lv.get("t"),
             "command_complete": None if cc is None else round(float(cc), 3),
             "device_directed": None if dd is None else round(float(dd), 3),
             "speaker": sp.get("id"), "act": top(u.get("act")), "intent": top(u.get("intent")),
             "utt_open": bool(u), "audio_events": ae, "bio_events": bio, "cc_events": cc_ev,
             "rtf": round(self.compute_s / self.audio_s, 3) if self.audio_s else None}
        key = (m["command_complete"], m["device_directed"], m["speaker"], (m["act"] or {}).get("label"),
               m["utt_open"], bool(ae), bool(bio), bool(cc_ev))
        if not force and key == self.last_key:
            return None
        self.last_key = key
        return m
