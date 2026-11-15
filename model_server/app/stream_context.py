"""Side-channel context for WS /v1/stream: what the app knows, sent next to the audio (docs/STREAMS.md).

client -> {"t":"context","mission":{...State subset...},"names":[...],"terms":[...],"telemetry":{...}|[...]}
server -> {"t":"context_ack","v":n,"names":k,"terms":k,"names_to_arc":bool,"terms_to_arc":false,"at_audio_s":s}

names: the screen's names list for Arc Transcriber Space ([{"name","kind","aliases"}], most relevant first; plain strings
are taken as kind "place"). They go to the stream's EarStream.set_names (ear and metadata modes alike) and are used from
the next decode: RNNT biasing, the decoder's kb prompt (the first ~10-15) and linking (the `names` on the final words).
terms / topic: recorded only (this model's context has no free-term slot). mission / telemetry: recorded only,
time-aligned to the audio fed so far (`at_audio_s`). The latest context is attached to every emitted `arc` message as
`context` (version, counts, the latest telemetry frame).
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
            sn = getattr(ms, "set_names", None)
            if callable(sn):
                try:
                    sn(self.names)
                    self.names_to_arc = True
                except Exception:  # noqa: BLE001 (context never breaks the stream)
                    self.names_to_arc = False
        if isinstance(msg.get("terms"), list):
            self.terms = [str(x) for x in msg["terms"]][:MAX_NAMES]
        if isinstance(msg.get("topic"), str):
            self.topic = msg["topic"][:80] or None
        return {"t": "context_ack", "v": self.v, "names": len(self.names), "terms": len(self.terms),
                "names_to_arc": self.names_to_arc, "terms_to_arc": self.terms_to_arc,
                "topic_to_arc": False, "at_audio_s": at}

    def decorate(self, out: dict | None) -> dict | None:
        if out and out.get("t") == "arc" and self.v:
            out["context"] = {"v": self.v, "names": len(self.names), "terms": len(self.terms),
                              "telemetry": self.frames[-1]["frame"] if self.frames else None}
        return out
