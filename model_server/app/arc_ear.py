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
libarc ABI 2 adds (docs/ARC_ABI2.md): on the final words `uconf`, `min_wconf`, `wconf`, `nbest`, `walts`, `almost`,
`quantities`, `clean_text`, `disfl`, `n_dropped` (and, live, `playback_leak`, `playback`, `barge`, `eot`); live mode
also sends {"t":"entity"} (a list name / sound-alike / quantity as soon as it is stable), {"t":"eot","p"} and
{"t":"barge_in"} (the kid talking over our playback). `conf` / `alts` stay null / [] (the shipped Director weights).

Names (docs/LOCAL_EAR.md "Names lists"): the backend sends the screen's list ({"t":"context","names":[{name, kind,
aliases}]}, most relevant first, <= EAR_MAX_NAMES) on every screen change; it takes effect from the next decode.
"""
from __future__ import annotations

import collections
import time

import numpy as np
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import arcmeta, diag
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
    ear_max_names: int = 80            # the names list cap (the model card: <= 30-50, most relevant first). 80 since the
    #                                    signals audit: the Moon screens carry every place AND every piece of hardware
    #                                    (backend names_list.MAX_MOON); docs/SPEECH_SIGNALS_AUDIT.md has the re-decode
    # device_directed for the app = the model's directed head, re-mapped onto the router's scale (DD_MIN 0.5 "talking
    # to someone else" below, DD_STRONG 0.7): head EAR_DD_KNEE -> 0.5 and head EAR_DD_STRONG_AT -> 0.7. The raw head is
    # conservative: real device-directed commands (SLURP) are >= 0.5 only 32% of the time, >= 0.05 67%, while crew talk
    # is >= 0.05 in 11% of clips (tools/ear_compare.py). To be calibrated on real kids' sessions (docs/LOCAL_EAR.md).
    ear_dd_knee: float = 0.05
    ear_dd_strong_at: float = 0.5
    # libarc ABI 2 (arc_transcriber 0aa792f): sound-alike "almost" names, an RNNT n-best beam (the words stay the
    # greedy decode's), and the live stream (partials decoded one 560 ms chunk at a time instead of re-decoding the
    # segment; early entity / end-of-turn / barge-in events; the playback reference for echo).
    ear_almost: bool = True
    ear_nbest: int = 4
    ear_live: bool = True               # False: the re-decode partial loop (ear_partial_every_s) and one final decode
    ear_stream_max_s: float = 60.0      # live: a stream keeps its audio; past this, reopened when idle and quiet
    # playback_leak >= this marks an utterance as our own audio (0: libarc's 0.7). 0.85 since the real-laptop calibration
    # (docs/ARC_ABI2.md section 8: echo vs kid-over-playback AUC 0.72 on real echo, not the simulation's 0.95). The
    # backend decides on the leak itself (session.ear_playback, PLAYBACK_THRESHOLD); this only sets the `playback` flag.
    ear_playback_threshold: float = 0.85
    ear_echo_decode: bool = False       # decode finals from the echo-cancelled audio (measured: docs/ARC_ABI2.md)
    ear_ref_keep_s: float = 3.0         # playback reference kept to re-feed a reopened stream


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


def agreement(a: str, b: str) -> float:
    """Word agreement of two hypotheses of the same audio (the RNNT words and the Arc decoder's text), 0..1: matched
    words (difflib) over the longer one, after lower-casing and dropping punctuation. Arc gives no per-word confidence;
    two decoders agreeing is the closest thing it has (calibration in docs/SPEECH_SIGNALS_AUDIT.md)."""
    import difflib
    import re
    x, y = re.findall(r"[a-z0-9']+", (a or "").lower()), re.findall(r"[a-z0-9']+", (b or "").lower())
    if not x and not y:
        return 1.0
    sm = difflib.SequenceMatcher(a=x, b=y, autojunk=False)
    return round(sum(m.size for m in sm.get_matching_blocks()) / max(len(x), len(y)), 3)


def link_view(n: dict, names_list: list[dict]) -> dict:
    """One linked name as the backend gets it: the decision (state, entity, p) plus the linker's evidence."""
    out = {"heard": n.get("heard"), "entity": n.get("entity"), "state": n.get("state"), "p": n.get("p"),
           "tag": n.get("tag"), "kind": _kind(names_list, n.get("entity"))}
    for k in ("t0", "t1", "via", "src", "model_entity", "model_p", "span_p"):
        if n.get(k) is not None:
            out[k] = n[k]
    return out


def _kind(names_list: list[dict], entity: str | None) -> str | None:
    for n in names_list:
        if n["name"] == entity:
            return n.get("kind")
    return None


BARGE_TAIL_S = 0.15   # barge-in events this close to (or after) the end of our playback are its echo tail


def almost_view(n: dict) -> dict:
    """A sound-alike name (options.almost): heard words that sound like a list entry. Never linked: a "Did you mean"
    offer at most (backend director._link)."""
    return {"heard": n.get("heard"), "candidate": n.get("candidate"), "p": n.get("candidate_p"),
            "kb_index": n.get("candidate_kb_index"), "t0": n.get("t0"), "t1": n.get("t1")}


def abi2_view(utts: list[dict], names: list[dict]) -> dict:
    """The ABI 2 read-outs of a turn's utterances, under keys of their own: the round-7 `conf` / `alts` the shipped
    Director weights read stay null / [] (docs/ARC_ABI2.md "Director"). Written forms where the app parses text."""
    words = [w for u in utts for w in (u.get("words") or [])]
    wc = [w.get("conf") for w in words]
    uc = [u["conf"] for u in utts if u.get("conf") is not None]
    out = {
        "wconf": [None if c is None else round(c, 3) for c in wc] if any(c is not None for c in wc) else None,
        "uconf": round(min(uc), 4) if uc else None,      # the least sure utterance of the turn
        "min_wconf": round(min(c for c in wc if c is not None), 4) if any(c is not None for c in wc) else None,
        "nbest": [{"text": written(a["text"] or ""), "p": a.get("p")} for u in utts for a in (u.get("nbest") or [])
                  if a.get("text")][:4],
        "walts": [{"i": i, "w": w["w"], "alts": w["alts"], "p": w.get("alt_p")} for i, w in enumerate(words)
                  if w.get("alts")],
        "clean_text": written(" ".join((u.get("clean_text") if u.get("clean_text") is not None else u.get("text") or "")
                                       for u in utts).strip()) or None,
        "disfl": [{"i": i, "w": w["w"], "kind": w["disfl"]} for i, w in enumerate(words) if w.get("disfl")],
        "quantities": [q for u in utts for q in (u.get("quantities") or [])],
        "n_dropped": sum(int(u.get("n_dropped") or 0) for u in utts),
        "almost": [almost_view(n) for n in names if n.get("state") == "almost" and n.get("candidate")],
    }
    return out


def _overlaps(a0: float, a1: float, b0: float, b1: float, slack: float = 0.2) -> bool:
    return a0 < b1 + slack and b0 < a1 + slack


class EarStream:
    """One live ear. Not thread-safe: call it from one worker thread (routes_meta does); the model has its own lock.
    metadata_only: emit only the `arc` messages (the Deepgram fallback's metadata stream).

    Live mode (ear_live, libarc ABI 2): a libarc stream (app/nft2.py Nft2Stream, options.live) is fed every chunk.
    Its PARTIAL events are the turn's partial words (no re-decoding), ENTITY events go out early ({"t":"entity"}),
    EOT gives the end-of-turn probability ({"t":"eot"}), and with the app's playback fed as a reference
    (feed_ref) BARGE_IN ({"t":"barge_in"}) and each utterance's playback_leak / playback. Turns are still opened and
    closed by this file's VAD (the backend's turn contract): at a turn's close the stream's open utterance is closed
    (end_turn, for its echo leak) and the segment gets the classic clip decode (words, names, sound events, the
    device-directed head: the read the router and the Director were built on). The stream keeps its audio, so it is
    reopened when idle past EAR_STREAM_MAX_S (and the reference still in flight is fed to the new one)."""

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
        # live stream state
        self.live = bool(s.ear_live) and not metadata_only and hasattr(self.m, "L")
        self.st = None                  # app.nft2.Nft2Stream
        self.st_t0 = 0.0                # this ear's audio time at the stream's time 0
        self.refs: collections.deque = collections.deque()   # (t, pcm): playback reference, ear time
        self.ref_until = 0.0            # ear time the last reference ends
        self.barge_at: float | None = None
        self.eot: float | None = None
        self.eot_sent_at = -1.0
        self.first_partial_at: float | None = None
        self.partials: list[dict] = []  # live: (ear time, text) of each partial in the open turn (latency stats)
        self.st_finals: list[dict] = []  # live: the stream's FINAL events (utt, t, playback leak / kind)
        self.barge_ps: list[tuple[float, float]] = []   # live: (ear time, p) of recent barge-in events

    # ---- context ----
    def set_names(self, names) -> int:
        out, seen = [], set()
        for x in names or []:
            n = normalize_entry(x)
            if n and n["name"].lower() not in seen:
                seen.add(n["name"].lower())
                out.append(n)
        changed = out[: self.cfg.ear_max_names] != getattr(self, "names", None)
        self.names = out[: self.cfg.ear_max_names]
        st = getattr(self, "st", None)
        if st is not None and changed:   # mid-stream: the open utterance's bias switches now (arc_nft2_stream_set_names)
            try:
                st.set_names(self.names)
            except Exception:  # noqa: BLE001 - the next final still uses the list (use_names)
                st.names = self.names
        return len(self.names)

    def set_decoder_context(self, names=None, terms=None, topic=None) -> bool:
        """StreamContext hook: the context frame's names -> the list (terms / topic: not used by this model)."""
        if names is not None:
            self.set_names(names)
        return bool(self.names)

    # ---- decoding ----
    def _decode(self, pcm: np.ndarray, partial: bool) -> dict:
        t = time.perf_counter()
        if partial:
            out = self.m.transcribe(pcm, domain=self.domain, no_events=True, names=self.names)
        else:
            out = self.m.transcribe(pcm, domain=self.domain, no_events=False, names=self.names,
                                    almost=self.cfg.ear_almost, nbest=self.cfg.ear_nbest)
        dt = time.perf_counter() - t
        self.compute_s += dt
        out["_s"] = dt
        kind = "partial" if partial else "final"   # [#92] decode latency + real-time factor (app/diag.py)
        diag.METRICS.observe("ear_decode_ms", dt * 1000, kind=kind)
        if len(pcm):
            diag.METRICS.observe("ear_rtf", dt / (len(pcm) / SR), bounds=diag.RATIO, kind=kind)
        return out

    def _seg_audio(self) -> np.ndarray:
        return np.concatenate(self.seg) if self.seg else np.zeros(0, np.float32)

    def _start(self, text: str) -> list[dict]:
        self.turn_open = True
        return [{"t": "turn", "state": "start", "text": text}]

    # ---- the live stream ----
    def _open_stream(self, prefeed: np.ndarray | None = None) -> None:
        from .nft2 import Nft2Stream
        t = time.perf_counter()
        self.st = Nft2Stream(self.m, names=self.names, domain=self.domain, almost=self.cfg.ear_almost,
                             nbest=self.cfg.ear_nbest, live=True, playback_threshold=self.cfg.ear_playback_threshold,
                             echo_decode=self.cfg.ear_echo_decode)
        pre = 0.0 if prefeed is None else len(prefeed) / SR
        self.st_t0 = self.audio_s - pre
        self.st_finals = []
        for rt, pcm in list(self.refs):     # the playback still in flight, on the new stream's clock
            end = rt + len(pcm) / SR
            if end <= self.st_t0:
                continue
            cut = max(0, int(round((self.st_t0 - rt) * SR)))
            self.st.feed_ref(pcm[cut:], max(0.0, rt - self.st_t0))
        if prefeed is not None and len(prefeed):
            self.st.feed(prefeed)           # the audio just before (a segment's pre-roll); its events are not used
        self.compute_s += time.perf_counter() - t

    def _close_stream(self) -> None:
        if self.st is not None:
            try:
                self.st.close()
            finally:
                self.st = None

    def feed_ref(self, pcm: np.ndarray, at: float | None = None) -> None:
        """The app's playback as it goes to the speaker (16 kHz mono float), `at` = this ear's audio time (s) when its
        first sample plays (None: right after the previous reference, or now)."""
        if not self.live:
            return
        x = np.ascontiguousarray(pcm, dtype=np.float32)
        if not len(x):
            return
        t = float(at) if at is not None else max(self.ref_until, self.audio_s)
        self.refs.append((t, x))
        self.ref_until = max(self.ref_until, t + len(x) / SR)
        keep = self.cfg.ear_ref_keep_s
        while self.refs and self.refs[0][0] + len(self.refs[0][1]) / SR < self.audio_s - keep:
            self.refs.popleft()
        if self.st is not None:
            rel = t - self.st_t0
            if rel < 0:
                x = x[int(round(-rel * SR)):]
                rel = 0.0
            if len(x):
                tt = time.perf_counter()
                self.st.feed_ref(x, rel)
                self.compute_s += time.perf_counter() - tt

    def playing(self) -> bool:
        return self.ref_until > self.audio_s

    def _events(self, evs: list[dict]) -> list[dict]:
        """libarc stream events -> messages (only while one of our segments is open, except finals / barge-in)."""
        msgs: list[dict] = []
        for e in evs:
            et = e["type"]
            at = round(self.st_t0 + e["t"], 3)
            if et == "final":
                self.st_finals.append({"utt": e["utt"], "t": at, "p": e.get("p"), "kind": e.get("kind")})
                del self.st_finals[:-32]
            elif et == "barge_in":
                # the speaker's echo tail outlives the reference by up to its reverb: a "barge-in" after our playback
                # ended is that tail, not the kid (measured: one at the very end of every clean echo)
                if at > self.ref_until - BARGE_TAIL_S:
                    continue
                if self.barge_at is None:
                    self.barge_at = at
                if e.get("p") is not None:
                    self.barge_ps.append((at, float(e["p"])))
                    del self.barge_ps[:-16]
                msgs.append({"t": "barge_in", "at": at, "p": e.get("p")})
            elif self.seg is None:
                continue
            elif et == "partial":
                txt = written(e.get("text") or "")
                if txt:
                    if self.first_partial_at is None:
                        self.first_partial_at = self.audio_s
                    self.partials.append({"at": round(self.audio_s, 3), "text": txt})
                    if not self.turn_open:
                        msgs += self._start(txt)
                    if txt != self.text:
                        self.text = txt
                        msgs.append({"t": "words", "text": txt, "final": False, "n_stable": e.get("n_stable"),
                                     "eot": self.eot})
            elif et == "entity":
                d = {"t": "entity", "at": at, "kind": e.get("kind"), "heard": e.get("text"), "entity": e.get("entity"),
                     "p": e.get("p")}
                if e.get("kind") == "quantity":
                    d.update(qtype=e.get("qtype"), value=e.get("value"), unit=e.get("unit"), relative=e.get("relative"))
                elif e.get("kb_index", -1) >= 0:
                    d["kb_index"] = e["kb_index"]
                msgs.append(d)
            elif et == "eot":
                self.eot = e.get("p")
                if self.eot is not None and self.audio_s - self.eot_sent_at >= 0.25:
                    self.eot_sent_at = self.audio_s
                    msgs.append({"t": "eot", "at": at, "p": self.eot})
        return msgs

    def _stream_feed(self, x: np.ndarray) -> list[dict]:
        if self.st is None:
            # (re)open with the pre-roll this ear still holds, so a segment that opens now is in the stream whole
            pre = np.concatenate(list(self.pre)) if self.pre else None
            self._open_stream(pre[:-len(x)] if pre is not None and len(pre) > len(x) else None)
        t = time.perf_counter()
        _, evs = self.st.feed(x)
        dt = time.perf_counter() - t
        self.compute_s += dt
        diag.METRICS.observe("ear_live_feed_ms", dt * 1000)
        return self._events(evs)

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
            if self.live:
                if self.st is not None and self.st.audio_s >= self.cfg.ear_stream_max_s and quiet and not self.playing():
                    self._close_stream()       # idle: a short stream keeps each flush cheap (reopened below)
                msgs += self._stream_feed(x)
            self.voiced_run = 0 if quiet else self.voiced_run + 1
            if self.voiced_run >= max(1, self.cfg.ear_onset_chunks):
                self.seg, self.seg_t0 = list(self.pre), self.audio_s - self.pre_s
                self.pre.clear()
                self.pre_s = 0.0
                self.last_voice_s = self.audio_s
                self.next_partial_s = self.audio_s + self.cfg.ear_partial_every_s
                self.barge_at = self.barge_at if self.playing() else None
                self.first_partial_at, self.partials = None, []
            return msgs
        self.seg.append(x)
        if self.live:
            msgs += self._stream_feed(x)
        if not quiet:
            self.last_voice_s = self.audio_s
        seg_s = self.audio_s - self.seg_t0
        if self.audio_s - self.last_voice_s >= self.cfg.ear_end_silence_s:
            return msgs + self._finish("silence")
        if seg_s >= self.cfg.ear_max_turn_s:
            return msgs + self._finish("max_turn")
        if (not self.live and not self.meta_only and self.cfg.ear_partial_every_s > 0
                and self.audio_s >= self.next_partial_s and seg_s <= self.cfg.ear_partial_max_s):
            out = self._decode(self._seg_audio(), partial=True)
            self.next_partial_s = self.audio_s + max(self.cfg.ear_partial_every_s, self.cfg.ear_partial_backoff * out["_s"])
            t = written(" ".join(u["text"] for u in out["utts"]).strip())
            if t:
                if self.first_partial_at is None:
                    self.first_partial_at = self.audio_s
                self.partials.append({"at": round(self.audio_s, 3), "text": t})
                if not self.turn_open:
                    msgs += self._start(t)
                if t != self.text:
                    self.text = t
                    msgs.append({"t": "words", "text": t, "final": False})
        return msgs

    def _final_live(self, pcm: np.ndarray) -> tuple[dict, list[dict]]:
        """Live: close the stream's open utterance (its echo leak), then ONE clip decode of the segment for the final read
        (words, names, events, the directed head): exactly the classic final. Measured: a flush of the stream gives the
        same words but a different directed head (it reads the stream's own utterances and context; 29 of 672 turns
        crossed DD_MIN, commands lost 6-11 points), so the read the router and the Director see stays the clip's."""
        t = time.perf_counter()
        _, evs = self.st.end_turn()
        msgs = self._events(evs)
        dt = time.perf_counter() - t
        self.compute_s += dt
        a0 = self.seg_t0 - 0.2
        leaks = [f["p"] for f in self.st_finals if f.get("p") is not None and f["t"] >= a0]
        kinds = [f.get("kind") for f in self.st_finals if f.get("p") is not None and f["t"] >= a0]
        out = self._decode(pcm, partial=False)
        out["_s"] += dt
        leak = max(leaks) if leaks else None
        for u in out["utts"]:
            u["playback_leak"] = leak
            u["playback"] = None if leak is None else any(k == "playback" for k in kinds)
        return out, msgs

    def _finish(self, reason: str) -> list[dict]:
        pcm = self._seg_audio()
        self.seg, self.voiced_run = None, 0
        msgs: list[dict] = []
        if len(pcm) < SR // 10 and not self.turn_open:
            return msgs
        if self.live and self.st is not None and len(pcm) >= SR // 10:
            out, ev_msgs = self._final_live(pcm)
            msgs += [m for m in ev_msgs if m["t"] == "barge_in"]
        else:
            out = self._decode(pcm, partial=False) if len(pcm) >= SR // 10 else {"utts": [], "names": [], "events": [],
                                                                                "_s": 0.0}
        utts = [u for u in out["utts"] if (u.get("text") or "").strip()]
        out["names"] = guard_names(out["names"], utts)
        almost = [n for n in out["names"] if n.get("state") == "almost"]
        linked_names = [n for n in out["names"] if n.get("state") != "almost"]   # names[] keeps its old meaning
        names = [link_view(n, self.names) for n in linked_names]
        spoken = " ".join(u["text"].strip() for u in utts).strip()
        # the Arc decoder's own text (its inline tags are moved onto the RNNT words; the words are the RNNT's): a
        # second hypothesis from the same audio. Where it holds a list name the words lack ("Fly to Tycho" vs "Fly
        # to"), the backend can offer it. NOT sent as `alts`: the round-7 Director features read `alts` / `conf` and
        # the shipped weights were trained with both empty (docs/SPEECH_SIGNALS_AUDIT.md section 4).
        dec = " ".join((u.get("decoder_text") or "").strip() for u in utts).strip()
        text = " ".join(display_text(u, linked_names) for u in utts).strip()
        # the device-directed head over the utterances WITH words only: on a wordless segment (room noise, a TV, our own
        # voice the model chose not to transcribe) it can read high (0.6-0.9 on real noise beds), and "no speech" is
        # never "talking to the app"
        dh = [u["directed_head"] for u in utts if u.get("directed_head") is not None]
        dflag = [u["directed"] for u in utts if u.get("directed") is not None]
        top = lambda k: next((u[k] for u in out["utts"] if u.get(k)), None)  # noqa: E731
        leaks = [u["playback_leak"] for u in out["utts"] if u.get("playback_leak") is not None]
        if not self.meta_only and not self.turn_open and text:
            msgs += self._start(text)     # before the arc read: a client resets its per-turn read on "start"
        msgs.append({"t": "arc", "at": round(self.audio_s, 2),
                     "device_directed": app_dd(max(dh), self.cfg.ear_dd_knee, self.cfg.ear_dd_strong_at) if dh else None,
                     "directed_head": round(max(dh), 3) if dh else None,
                     "directed": any(dflag) if dflag else None, "command_complete": None, "speaker": None,
                     "act": top("act"), "intent": top("intent"), "utt_open": False, "speech": bool(spoken),
                     "audio_events": arcmeta.audio_events(out["events"]), "bio_events": [], "cc_events": [],
                     "names": names, "rtf": round(self.compute_s / self.audio_s, 3) if self.audio_s else None,
                     "playback_leak": round(max(leaks), 3) if leaks else None})
        if self.meta_only:
            self.turn_open, self.text = False, ""
            return msgs
        if not text and self.turn_open:
            text = self.text           # the final heard nothing the partials did: close on the partial text
        if text:
            w = {"t": "words", "text": text, "final": True, "spoken": spoken, "names": names,
                 "tags": [t for u in utts for t in u["tags"]], "conf": None, "alts": [],
                 "decoder_text": dec or None, "agree": agreement(spoken, dec) if dec else None}
            w.update(abi2_view(utts, almost))
            if self.live:
                pb = [u.get("playback") for u in utts if u.get("playback") is not None]
                w.update(playback_leak=round(max(leaks), 3) if leaks else None, playback=any(pb) if pb else None,
                         barge=self.barge_at is not None and self.barge_at >= self.seg_t0 - 0.3, eot=self.eot)
                bps = [p for t, p in self.barge_ps if t >= self.seg_t0 - 0.3]
                w["barge_p"] = round(max(bps), 3) if bps else None
            msgs.append(w)
            msgs.append({"t": "turn", "state": "end", "text": text})
            self.ends.append({"at": round(self.audio_s, 3), "last_voice": round(self.last_voice_s, 3),
                              "reason": reason, "decode_ms": round(out["_s"] * 1000, 1),
                              "first_partial": self.first_partial_at, "seg_t0": round(self.seg_t0, 3),
                              "partials": len(self.partials)})
            diag.METRICS.inc("ear_turns", end=reason)
        elif not spoken:
            diag.METRICS.inc("ear_segments_no_speech")
        self.turn_open, self.text = False, ""
        self.barge_at, self.eot, self.first_partial_at, self.partials = None, None, None, []
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
        self._close_stream()
