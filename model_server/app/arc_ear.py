"""Arc as the ear: words, turns and metadata from one local model (WS /v1/stream?ear=arc).

Arc v1.1 Mini with its decoder loaded (arcmeta.load, ARC_EAR=on) runs the built-in transcript (`transcript="builtin"`),
so one stream gives the words, the endpoint and the metadata heads. Each connection gets its own Arc stream (per-stream
state; the weights are shared and loaded once).

Messages (the shapes the browser already takes from the Deepgram Flux relay, docs/SESSION_CONTRACT.md):
  {"t":"words","text","final"}   the whole current turn so far, in written form ("shields to 40"); a later partial may
                                 revise earlier words; final=true once per turn, with the decoded final transcript
  {"t":"turn","state":"start"|"eager"|"end"|"resumed","text"}
      start    first non-empty partial of a turn (Arc's first voiced words)
      eager    silence >= EAGER_SILENCE_S and Arc's command_complete p >= EAGER_CC_P (the turn sounds finished)
      resumed  voiced audio again after eager, before end
      end      Arc closed the utterance (its own pause rule), or silence >= EAR_END_SILENCE_S (0.5 s) -> Stream.end_turn()
  {"t":"arc",...}                metadata summary, as in metadata-only mode (arcmeta.MetaStream._summary)

Silence is an energy VAD per chunk with an adaptive floor (Arc's own segmenter rule: quiet = below floor + margin, the
floor being the 10th percentile of the last ~24 s), so classroom noise at a steady level reads as silence.
"""
from __future__ import annotations

import time

import numpy as np
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import arcmeta

SR = arcmeta.SR


class EarSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    arc_ear: str = "on"              # on: load Arc's decoder so /v1/stream?ear=arc works (~+0 MB: it ships in mini/)
    ear_eager_silence_s: float = 0.25
    ear_eager_cc_p: float = 0.5
    ear_end_silence_s: float = 0.5   # eval: 0.6 -> p50 958 ms, 0.5 -> 880 ms (docs/LOCAL_EAR.md)
    ear_pause_s: float = 0.5          # Arc segmenter: pause that closes an utterance >= min_s
    ear_short_pause_s: float = 0.6    # ... and one shorter than min_s
    ear_partial_every_s: float = 0.3
    ear_vad_margin_db: float = 6.0
    ear_auto_prev: bool = False       # Arc context memory: feed back what was said earlier


ear_settings = EarSettings()


def written(text: str) -> str:
    try:
        from arc_audio.written import to_written
        return to_written(text or "").strip()
    except Exception:  # noqa: BLE001
        return (text or "").strip()


def with_written(out: dict) -> list[dict]:
    """Final utterances with Arc's own written form attached (`written`): numbers as digits AND names linked to the
    context list in the list's spelling ("Malapart" -> "Malapert", "captain" -> "CAPCOM"). transcript_written has one
    entry per new transcript utterance; when the counts disagree, fall back to text-only written()."""
    us = list(out.get("transcript") or [])
    tw = list(out.get("transcript_written") or [])
    if len(tw) == len(us):
        return [dict(u, written=w.get("text") or "") for u, w in zip(us, tw)]
    return us


class Vad:
    """Energy VAD with an adaptive floor, per chunk."""

    def __init__(self, margin_db: float = 6.0):
        self.hist: list[float] = []
        self.margin = margin_db

    def quiet(self, x: np.ndarray) -> bool:
        db = 10 * np.log10(float(np.mean(x * x)) + 1e-10)
        self.hist = (self.hist + [db])[-300:]
        floor = float(np.percentile(self.hist, 10)) if len(self.hist) >= 12 else -60.0
        return db < max(-50.0, floor + self.margin) or db < -55.0


class TurnTracker:
    """Arc stream outputs + VAD -> words / turn messages. Pure logic (no model), unit-tested with fake outputs."""

    def __init__(self, s=ear_settings):
        self.cfg = s
        self.in_turn = False
        self.eager = False
        self.text = ""             # current turn text (written form)
        self.last_voice_s = 0.0
        self.now = 0.0
        self.cc = 0.0
        self.turn_start_s = None
        self.ends: list[dict] = []  # {"at","last_voice","reason"} for latency stats

    def _start(self, text: str) -> list[dict]:
        self.in_turn, self.eager, self.turn_start_s = True, False, self.now
        return [{"t": "turn", "state": "start", "text": text}]

    def on_audio(self, now_s: float, chunk_s: float, quiet: bool) -> list[dict]:
        self.now = now_s
        out = []
        if not quiet:
            self.last_voice_s = now_s
            if self.in_turn and self.eager:
                self.eager = False
                out.append({"t": "turn", "state": "resumed", "text": self.text})
        return out

    def silence_s(self) -> float:
        return max(0.0, self.now - self.last_voice_s)

    def on_arc(self, out: dict) -> list[dict]:
        msgs = []
        lv = ((out.get("live") or {}).get("utt") or {})
        if lv.get("command_complete") is not None:
            self.cc = float(lv["command_complete"])
        for e in out.get("events") or []:
            if e.get("tag") == arcmeta.CC and e.get("p") is not None:
                self.cc = max(self.cc, float(e["p"]))
        for u in with_written(out):
            msgs += self.final(u, "arc_pause")
        tp = out.get("transcript_partial")
        if tp and not tp.get("final"):
            t = written(tp.get("text", ""))
            if t:
                if not self.in_turn:
                    msgs += self._start(t)
                if t != self.text:
                    self.text = t
                    msgs.append({"t": "words", "text": t, "final": False})
        return msgs

    def final(self, u: dict, reason: str) -> list[dict]:
        t = (u.get("written") or "").strip() or written(u.get("text", ""))
        if not t and not self.in_turn:
            return []
        if not self.in_turn:
            msgs = self._start(t)
        else:
            msgs = []
        t = t or self.text
        msgs += [{"t": "words", "text": t, "final": True}, {"t": "turn", "state": "end", "text": t}]
        self.ends.append({"at": round(self.now, 3), "last_voice": round(self.last_voice_s, 3), "reason": reason})
        self.in_turn, self.eager, self.text, self.cc = False, False, "", 0.0
        return msgs

    def tick(self) -> tuple[list[dict], bool]:
        """After a chunk: eager now? Returns (messages, end_turn_needed)."""
        if not self.in_turn:
            return [], False
        sil = self.silence_s()
        if sil >= self.cfg.ear_end_silence_s:
            return [], True
        if not self.eager and sil >= self.cfg.ear_eager_silence_s and self.cc >= self.cfg.ear_eager_cc_p:
            self.eager = True
            return [{"t": "turn", "state": "eager", "text": self.text}], False
        return [], False

    def force_end(self, out: dict, reason: str) -> list[dict]:
        """Results of Stream.end_turn() / flush(): the final(s), or close the turn on the last partial text."""
        msgs = []
        us = [u for u in with_written(out) if (u.get("text") or "").strip()]
        for u in us:
            msgs += self.final(u, reason)
        if not us and self.in_turn:
            msgs += self.final({"text": self.text}, reason + "_partial")
        return msgs


class EarStream(arcmeta.MetaStream):
    """One live Arc ear. Not thread-safe: call it from one worker thread only (routes_meta does)."""

    def __init__(self, domain: str = "assistant", names=None, s=ear_settings):
        self.domain = domain
        self.last_key = None
        self.compute_s = 0.0
        self.audio_s = 0.0
        self.vad = Vad(s.ear_vad_margin_db)
        self.turns = TurnTracker(s)
        self.s = self._open(names)

    def _open(self, names=None):
        c = self.turns.cfg
        return arcmeta.STATE["arc"].stream(
            domain=self.domain, transcript="builtin", partials=True, fallback=None, events="all", names=names or None,
            partial_every_s=c.ear_partial_every_s, auto_prev=c.ear_auto_prev,
            segmenter=dict(pause_s=c.ear_pause_s, short_pause_s=c.ear_short_pause_s))

    def set_decoder_context(self, names=None, terms=None, topic=None) -> bool:
        """Context frame -> Arc. Stream.set_context fills the decoder prompt (names + terms, ~40 tokens, in order) and
        set_names (StreamContext) the linker; the name-list snap and the decoder's name-bias trie are only built from
        `names` in Arc.stream(), so they are rebuilt here too (that is what turns "Malapart" into "Malapert" in the
        written final). The backend sends its Tier A list before any audio, so the worker is idle when the trie swaps."""
        self.s.set_context(names=names or None, terms=terms or None, topic=topic or None, auto_prev=self.turns.cfg.ear_auto_prev)
        if names and self.audio_s == 0 and hasattr(self, "domain"):
            # before any audio (the backend's Tier A frame): reopen the Arc stream with the names, which is the only way
            # to get the name linker's records + snap into transcript_written (set_names / a later kb swap don't)
            self.s.close()
            self.s = self._open(names)
            self.s.set_context(names=names, terms=terms or None, topic=topic or None, auto_prev=self.turns.cfg.ear_auto_prev)
            return True
        if names:
            try:
                from arc_audio.api import Arc
                from arc_audio.kbsnap import KB
                self.s.kb = KB(Arc._kb(names))
                if getattr(self.s, "tr", None) is not None:
                    self.s.a._set_bias(self.s.tr, names, True)
            except Exception:  # noqa: BLE001 (context never breaks the stream)
                pass
        return True

    def add_words(self, words) -> None:   # no external words in ear mode
        return None

    def _timed(self, fn, *a):
        t = time.perf_counter()
        out = fn(*a)
        self.compute_s += time.perf_counter() - t
        return out

    def feed_all(self, pcm16: bytes) -> list[dict]:
        x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        self.audio_s += len(x) / SR
        msgs = self.turns.on_audio(self.audio_s, len(x) / SR, self.vad.quiet(x))
        out = self._timed(self.s.feed, x)
        msgs += self.turns.on_arc(out)
        more, need_end = self.turns.tick()
        msgs += more
        if need_end:
            msgs += self.turns.force_end(self._timed(self.s.end_turn), "silence")
        m = self._summary(out)
        if m:
            msgs.append(m)
        return msgs

    def end_turn_all(self) -> list[dict]:
        out = self._timed(self.s.end_turn)
        msgs = self.turns.on_arc({k: v for k, v in out.items() if k != "transcript_partial"})
        return msgs + self.turns.force_end({}, "end_turn")

    def flush_all(self) -> list[dict]:
        out = self._timed(self.s.flush)
        msgs = self.turns.on_arc({k: v for k, v in out.items() if k != "transcript_partial"})
        msgs += self.turns.force_end({}, "stop")
        m = self._summary(out, force=True)
        if m:
            m["final"] = True
            msgs.append(m)
        return msgs
