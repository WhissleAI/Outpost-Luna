"""Side-channel context for WS /v1/stream: what the app knows, sent next to the audio (docs/STREAMS.md).

client -> {"t":"context","mission":{...State subset...},"names":[...],"terms":[...],"telemetry":{...}|[...]}
server -> {"t":"context_ack","v":n,"names":k,"terms":k,"names_to_arc":bool,"terms_to_arc":false,"at_audio_s":s}

Ear mode (/v1/stream?ear=arc, arc_ear.EarStream, decoder loaded): names, terms and topic go to the decoder's context
memory (Stream.set_context: names + terms fill the prompt's ~40-token list slot in order, so put the likeliest first)
and names also to the linker (set_names). The ack then says terms_to_arc / topic_to_arc true.

What reaches Arc v1.1 in metadata mode (external-transcript mode, see arcmeta.MetaStream):
  names     -> Stream.set_names(): the name linker / snap checks the external words' name spans against this list.
               (MetaStream's summary does not emit Arc's `names` records yet, so the effect is not visible downstream.)
  terms     -> recorded only. Arc's terms/topic/previous_text are *decoder* context (Stream.set_context), and the decoder
               is not loaded here (load_decoder=False): the call would be a no-op.
  mission / telemetry -> recorded only, time-aligned to the audio fed so far (`at_audio_s`). No Arc head reads them.
The latest context is attached to every emitted `arc` message as `context` (version, counts, the latest telemetry
frame), so a consumer can join model output with the game state it was heard in.
"""
from __future__ import annotations

import time
from collections import deque

MAX_NAMES = 200
MAX_FRAMES = 600   # ~10 min of 1 Hz telemetry


class StreamContext:
    """Latest context for one stream. Call update() on the stream's worker thread (it may touch the Arc stream)."""

    def __init__(self):
        self.v = 0
        self.mission: dict | None = None
        self.names: list = []
        self.terms: list[str] = []
        self.frames: deque = deque(maxlen=MAX_FRAMES)
        self.names_to_arc = False
        self.terms_to_arc = False
        self.topic: str | None = None
        self.t0 = time.monotonic()

    def update(self, msg: dict, ms=None) -> dict:
        self.v += 1
        at = round(getattr(ms, "audio_s", 0.0) or 0.0, 2) if ms is not None else None
        if isinstance(msg.get("mission"), dict):
            self.mission = msg["mission"]
            self.frames.append({"at_audio_s": at, "wall_s": round(time.monotonic() - self.t0, 2), "frame": msg["mission"]})
        tel = msg.get("telemetry")
        for f in (tel if isinstance(tel, list) else [tel] if isinstance(tel, dict) else []):
            if isinstance(f, dict):
                self.frames.append({"at_audio_s": at, "wall_s": round(time.monotonic() - self.t0, 2), "frame": f})
        if isinstance(msg.get("names"), list):
            self.names = [n for n in msg["names"] if isinstance(n, (str, dict))][:MAX_NAMES]
            self.names_to_arc = False
            s = getattr(ms, "s", None)   # the arc_audio Stream inside arcmeta.MetaStream
            if s is not None and callable(getattr(s, "set_names", None)):
                try:
                    s.set_names(self.names)
                    self.names_to_arc = True
                except Exception:  # noqa: BLE001 (context never breaks the stream)
                    self.names_to_arc = False
        if isinstance(msg.get("terms"), list):
            self.terms = [str(x) for x in msg["terms"]][:MAX_NAMES]
        if isinstance(msg.get("topic"), str):
            self.topic = msg["topic"][:80] or None
        dec = getattr(ms, "set_decoder_context", None)   # ear mode only: the decoder is loaded
        if callable(dec) and any(k in msg for k in ("names", "terms", "topic")):
            try:
                self.terms_to_arc = bool(dec(names=self.names, terms=self.terms, topic=self.topic))
            except Exception:  # noqa: BLE001
                self.terms_to_arc = False
        return {"t": "context_ack", "v": self.v, "names": len(self.names), "terms": len(self.terms),
                "names_to_arc": self.names_to_arc, "terms_to_arc": self.terms_to_arc,
                "topic_to_arc": self.terms_to_arc and bool(self.topic), "at_audio_s": at}

    def decorate(self, out: dict | None) -> dict | None:
        if out and out.get("t") == "arc" and self.v:
            out["context"] = {"v": self.v, "names": len(self.names), "terms": len(self.terms),
                              "telemetry": self.frames[-1]["frame"] if self.frames else None}
        return out
