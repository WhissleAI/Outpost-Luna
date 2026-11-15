"""The ear: words, turns, names, sound events and device-directed speech from Arc Transcriber Space
(WS /v1/stream?ear=arc; the model is app/arcmeta.py's, on libarc + ONNX Runtime, app/nft2.py).

How a turn is heard (one EarStream per connection, the model shared under its lock):
  1. An energy VAD with an adaptive floor (classroom noise at a steady level reads as silence) opens a SEGMENT after
     EAR_ONSET_CHUNKS voiced chunks, with EAR_PREROLL_S of audio before it.
  2. While the segment is open, a partial decode (no events) runs every EAR_PARTIAL_EVERY_S (backing off to
     EAR_PARTIAL_BACKOFF x its own cost, and only on the first EAR_PARTIAL_MAX_S). The first non-empty partial starts
     the TURN. Each partial re-decodes the whole segment, so its cost grows with the turn: at 2x (the old back-off) a
     1.3 s command got one partial at ~0.7 s and the next ~0.15 s before the final, which read as "no streaming".
  3. EAR_END_SILENCE_S of silence (or end_turn / stop, or EAR_MAX_TURN_S) closes it: one full decode gives the final
     words, the names linked to the screen's list, the sound events and the device-directed head.
A segment whose final decode has no words is not a turn: noise, or synthetic speech the model chose not to transcribe
(it is trained to ignore Kokoro-style TTS). Its `arc` message still goes out (speech=false, the sound events, no
device-directed read), so room noise is visible downstream without ever taking the floor. NOTE: the app's own voices
(the Nora voice pack, the macOS OS voice) ARE transcribed when they reach the mic (40/40 clean clips,
tools/ear_compare.py), so the backend's echo check (turn_router.echo_of against what we just said) stays the defence.

Messages (the shapes the browser takes from the Deepgram Flux relay, docs/SESSION_CONTRACT.md, plus names):
  {"t":"turn","state":"start","text"}       the first non-empty partial (or the final, when no partial had words)
  {"t":"words","text","final":false}        the turn so far, written form; a later partial may revise earlier words
  {"t":"arc", ...}                          per closed segment, BEFORE its final words: device_directed (the head
                                            re-mapped onto the router's scale, app_dd), directed_head (raw), directed
                                            (the model's own 0.5 flag), audio_events, speech, names, rtf
  {"t":"words","text","final":true,"spoken","names":[...],"tags":[...],"conf":null,"alts":[]}
                                            text = written form with linked names in the list's spelling ("Artemis
                                            II", "Apollo 12"); spoken = the model's spoken form; names = [{heard,
                                            entity, state: linked|abstain|not_in_list, p, tag, kind}]
  {"t":"turn","state":"end","text"}

Names (docs/LOCAL_EAR.md "Names lists"): the backend sends the screen's list ({"t":"context","names":[{name, kind,
aliases}]}, most relevant first, <= EAR_MAX_NAMES) on every screen change; it takes effect from the next decode.
"""
from __future__ import annotations

import collections
import time

import numpy as np
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import arcmeta
from .nft2 import normalize_entry

SR = arcmeta.SR


class EarSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    ear_end_silence_s: float = 0.5     # silence that closes a turn
    ear_onset_chunks: int = 2          # voiced 80 ms chunks in a row that open a segment
    ear_preroll_s: float = 0.3         # audio kept before the onset
    ear_partial_every_s: float = 0.3   # partial decode cadence while a segment is open (0: no partials)
    ear_partial_backoff: float = 1.25  # ... or this x the last partial's decode cost, whichever is longer
    ear_partial_max_s: float = 8.0     # no partials past this much segment audio (the final still covers it all)
    ear_max_turn_s: float = 15.0       # a segment this long is closed as a turn
    ear_vad_margin_db: float = 6.0
    ear_max_names: int = 40            # the names list cap (the model card: <= 30-50, most relevant first)
    # device_directed for the app = the model's directed head, re-mapped onto the router's scale (DD_MIN 0.5 "talking
    # to someone else" below, DD_STRONG 0.7): head EAR_DD_KNEE -> 0.5 and head EAR_DD_STRONG_AT -> 0.7. The raw head is
    # conservative: real device-directed commands (SLURP) are >= 0.5 only 32% of the time, >= 0.05 67%, while crew talk
    # is >= 0.05 in 11% of clips (tools/ear_compare.py). To be calibrated on real kids' sessions (docs/LOCAL_EAR.md).
    ear_dd_knee: float = 0.05
    ear_dd_strong_at: float = 0.5


ear_settings = EarSettings()


def written(text: str) -> str:
    """Spoken form -> written form (numbers as digits: "shields to forty percent" -> "shields to 40%")."""
    try:
        from .arc_text.written import to_written
        return to_written(text or "").strip()
    except Exception:  # noqa: BLE001
        return (text or "").strip()


def display_text(utt: dict, names: list[dict]) -> str:
    """An utterance's written form with each LINKED name's words replaced by the list entry ("artemis two" ->
    "Artemis II"): the list's spelling is what the app routes and shows (the model card: route on names[].entity)."""
    words = list(utt.get("words") or [])
    if not words:
        return written(utt.get("text") or "")
    toks = [w["w"] for w in words]
    for n in sorted((n for n in names if n.get("state") == "linked" and n.get("entity")), key=lambda n: -n["t0"]):
        idx = [i for i, w in enumerate(words) if w["t0"] >= n["t0"] - 0.05 and w["t1"] <= n["t1"] + 0.05]
        if not idx:
            continue
        a, b = idx[0], idx[-1]
        tail = "".join(c for c in toks[b][::-1] if c in ".,!?;:")[::-1] if toks[b] else ""
        toks[a:b + 1] = [n["entity"] + tail]
    return written(" ".join(t for t in toks if t))


STOP_WORDS = frozenset("a an the to of in on at for and or me us my our this that it its is are was go show take fly "
                       "see find look zoom where what".split())


NUM_EQ = {"i": "1", "one": "1", "first": "1", "ii": "2", "two": "2", "second": "2", "iii": "3", "three": "3",
          "third": "3", "iv": "4", "four": "4", "fourth": "4", "v": "5", "five": "5", "vi": "6", "six": "6",
          "vii": "7", "seven": "7", "viii": "8", "eight": "8", "ix": "9", "nine": "9", "x": "10", "ten": "10",
          "xi": "11", "eleven": "11", "xii": "12", "twelve": "12", "xiii": "13", "thirteen": "13", "xiv": "14",
          "fourteen": "14", "xv": "15", "fifteen": "15", "xvi": "16", "sixteen": "16", "xvii": "17", "seventeen": "17"}


def _toks(s: str) -> list[str]:
    import re
    return [NUM_EQ.get(t, t) for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t]


def guard_names(names: list[dict], utts: list[dict]) -> list[dict]:
    """Fix links that cover only PART of their list entry (the linker matched one word of a two-word name):
      - the words next to it ARE the rest of the name ("Artemis" + "two" for "Artemis II"; numerals, Roman numerals
        and number words count as the same): the link is widened over them, so the turn reads "Artemis II", not
        "Artemis II two";
      - the words next to it CONTRADICT the rest ("South" + "Pole" for "North Pole": 16/16 test clips linked "Pole"
        -> "North Pole", the turn read "South North Pole" and flew north): the link becomes `abstain`, and the director
        routes on the text ("south pole" is a gazetteer alias);
      - a stop word next to it ("the Pole") or nothing at all: the link stays as it is."""
    words = [w for u in utts for w in (u.get("words") or [])]
    out = []
    for n in names:
        n = dict(n)
        if n.get("state") == "linked" and n.get("entity"):
            ent, heard = _toks(n["entity"]), _toks(n.get("heard") or "")
            if heard and len(ent) > len(heard):
                k, tail = len(heard), None
                if ent[-k:] == heard:          # heard is the entry's tail: look at the words just before it
                    miss, tail = ent[:-k], True
                    near = [w for w in words if w["t1"] <= n["t0"] + 0.05][-len(miss):]
                elif ent[:k] == heard:         # heard is the entry's head: look at the words just after it
                    miss, tail = ent[k:], False
                    near = [w for w in words if w["t0"] >= n["t1"] - 0.05][:len(miss)]
                else:
                    miss, near = [], []
                said = [t for w in near for t in _toks(w["w"])]
                if said and said == miss:
                    if tail:
                        n["t0"] = near[0]["t0"]
                    else:
                        n["t1"] = near[-1]["t1"]
                    n["heard"] = " ".join([w["w"] for w in near] + [n.get("heard") or ""] if tail
                                          else [n.get("heard") or ""] + [w["w"] for w in near]).strip()
                elif said and not all(t in STOP_WORDS for t in said):
                    n["state"] = "abstain"
        out.append(n)
    return out


def app_dd(head: float | None, knee: float = 0.05, strong_at: float = 0.5) -> float | None:
    """The directed head (0..1) on the router's scale: [0, knee] -> [0, 0.5], [knee, strong_at] -> [0.5, 0.7],
    [strong_at, 1] -> [0.7, 1]. Monotonic, so the order of turns is kept; only where the thresholds bite moves."""
    if head is None:
        return None
    h = min(1.0, max(0.0, float(head)))
    if h <= knee:
        return round(0.5 * h / knee, 3)
    if h <= strong_at:
        return round(0.5 + 0.2 * (h - knee) / (strong_at - knee), 3)
    return round(0.7 + 0.3 * (h - strong_at) / (1 - strong_at), 3)


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


def _kind(names_list: list[dict], entity: str | None) -> str | None:
    for n in names_list:
        if n["name"] == entity:
            return n.get("kind")
    return None


class EarStream:
    """One live ear. Not thread-safe: call it from one worker thread (routes_meta does); the model has its own lock.
    metadata_only: emit only the `arc` messages (the Deepgram fallback's metadata stream)."""

    def __init__(self, domain: str = "assistant", names=None, s: EarSettings = ear_settings, model=None,
                 metadata_only: bool = False):
        self.cfg, self.domain, self.meta_only = s, domain, metadata_only
        self.m = model if model is not None else arcmeta.STATE["arc"]
        self.vad = Vad(s.ear_vad_margin_db)
        self.names: list[dict] = []
        self.set_names(names or [])
        self.audio_s = 0.0
        self.compute_s = 0.0
        self.pre: collections.deque = collections.deque()
        self.pre_s = 0.0
        self.voiced_run = 0
        self.seg: list[np.ndarray] | None = None
        self.seg_t0 = 0.0
        self.last_voice_s = 0.0
        self.next_partial_s = 0.0
        self.turn_open = False
        self.text = ""
        self.ends: list[dict] = []      # per closed turn: {"at", "last_voice", "reason", "decode_ms"} (latency stats)

    # ---- context ----
    def set_names(self, names) -> int:
        out, seen = [], set()
        for x in names or []:
            n = normalize_entry(x)
            if n and n["name"].lower() not in seen:
                seen.add(n["name"].lower())
                out.append(n)
        self.names = out[: self.cfg.ear_max_names]
        return len(self.names)

    def set_decoder_context(self, names=None, terms=None, topic=None) -> bool:
        """StreamContext hook: the context frame's names -> the list (terms / topic: not used by this model)."""
        if names is not None:
            self.set_names(names)
        return bool(self.names)

    # ---- decoding ----
    def _decode(self, pcm: np.ndarray, partial: bool) -> dict:
        t = time.perf_counter()
        out = self.m.transcribe(pcm, domain=self.domain, no_events=partial, names=self.names)
        dt = time.perf_counter() - t
        self.compute_s += dt
        out["_s"] = dt
        return out

    def _seg_audio(self) -> np.ndarray:
        return np.concatenate(self.seg) if self.seg else np.zeros(0, np.float32)

    def _start(self, text: str) -> list[dict]:
        self.turn_open = True
        return [{"t": "turn", "state": "start", "text": text}]

    def feed_all(self, pcm16: bytes) -> list[dict]:
        x = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        dur = len(x) / SR
        self.audio_s += dur
        quiet = self.vad.quiet(x)
        msgs: list[dict] = []
        if self.seg is None:
            self.pre.append(x)
            self.pre_s += dur
            while self.pre and self.pre_s - len(self.pre[0]) / SR >= self.cfg.ear_preroll_s + dur:
                self.pre_s -= len(self.pre.popleft()) / SR
            self.voiced_run = 0 if quiet else self.voiced_run + 1
            if self.voiced_run >= max(1, self.cfg.ear_onset_chunks):
                self.seg, self.seg_t0 = list(self.pre), self.audio_s - self.pre_s
                self.pre.clear()
                self.pre_s = 0.0
                self.last_voice_s = self.audio_s
                self.next_partial_s = self.audio_s + self.cfg.ear_partial_every_s
            return msgs
        self.seg.append(x)
        if not quiet:
            self.last_voice_s = self.audio_s
        seg_s = self.audio_s - self.seg_t0
        if self.audio_s - self.last_voice_s >= self.cfg.ear_end_silence_s:
            return self._finish("silence")
        if seg_s >= self.cfg.ear_max_turn_s:
            return self._finish("max_turn")
        if (not self.meta_only and self.cfg.ear_partial_every_s > 0 and self.audio_s >= self.next_partial_s
                and seg_s <= self.cfg.ear_partial_max_s):
            out = self._decode(self._seg_audio(), partial=True)
            self.next_partial_s = self.audio_s + max(self.cfg.ear_partial_every_s, self.cfg.ear_partial_backoff * out["_s"])
            t = written(" ".join(u["text"] for u in out["utts"]).strip())
            if t:
                if not self.turn_open:
                    msgs += self._start(t)
                if t != self.text:
                    self.text = t
                    msgs.append({"t": "words", "text": t, "final": False})
        return msgs

    def _finish(self, reason: str) -> list[dict]:
        pcm = self._seg_audio()
        self.seg, self.voiced_run = None, 0
        msgs: list[dict] = []
        if len(pcm) < SR // 10 and not self.turn_open:
            return msgs
        out = self._decode(pcm, partial=False) if len(pcm) >= SR // 10 else {"utts": [], "names": [], "events": [],
                                                                            "_s": 0.0}
        utts = [u for u in out["utts"] if (u.get("text") or "").strip()]
        out["names"] = guard_names(out["names"], utts)
        names = [{"heard": n["heard"], "entity": n["entity"], "state": n["state"], "p": n["p"], "tag": n["tag"],
                  "kind": _kind(self.names, n["entity"])} for n in out["names"]]
        spoken = " ".join(u["text"].strip() for u in utts).strip()
        text = " ".join(display_text(u, out["names"]) for u in utts).strip()
        # the device-directed head over the utterances WITH words only: on a wordless segment (room noise, a TV, our own
        # voice the model chose not to transcribe) it can read high (0.6-0.9 on real noise beds), and "no speech" is
        # never "talking to the app"
        dh = [u["directed_head"] for u in utts if u.get("directed_head") is not None]
        dflag = [u["directed"] for u in utts if u.get("directed") is not None]
        top = lambda k: next((u[k] for u in out["utts"] if u.get(k)), None)  # noqa: E731
        if not self.meta_only and not self.turn_open and text:
            msgs += self._start(text)     # before the arc read: a client resets its per-turn read on "start"
        msgs.append({"t": "arc", "at": round(self.audio_s, 2),
                     "device_directed": app_dd(max(dh), self.cfg.ear_dd_knee, self.cfg.ear_dd_strong_at) if dh else None,
                     "directed_head": round(max(dh), 3) if dh else None,
                     "directed": any(dflag) if dflag else None, "command_complete": None, "speaker": None,
                     "act": top("act"), "intent": top("intent"), "utt_open": False, "speech": bool(spoken),
                     "audio_events": arcmeta.audio_events(out["events"]), "bio_events": [], "cc_events": [],
                     "names": names, "rtf": round(self.compute_s / self.audio_s, 3) if self.audio_s else None})
        if self.meta_only:
            self.turn_open, self.text = False, ""
            return msgs
        if not text and self.turn_open:
            text = self.text           # the final heard nothing the partials did: close on the partial text
        if text:
            msgs.append({"t": "words", "text": text, "final": True, "spoken": spoken, "names": names,
                         "tags": [t for u in utts for t in u["tags"]], "conf": None, "alts": []})
            msgs.append({"t": "turn", "state": "end", "text": text})
            self.ends.append({"at": round(self.audio_s, 3), "last_voice": round(self.last_voice_s, 3),
                              "reason": reason, "decode_ms": round(out["_s"] * 1000, 1)})
        self.turn_open, self.text = False, ""
        return msgs

    def end_turn_all(self) -> list[dict]:
        """Push-to-talk released (or the client's end of speech): close the open segment now."""
        if self.seg is None and not self.turn_open:
            return []
        if self.seg is None:
            self.seg = []
        return self._finish("end_turn")

    def flush_all(self) -> list[dict]:
        msgs = self._finish("stop") if self.seg is not None else []
        return msgs

    def close(self) -> None:
        self.seg = None
