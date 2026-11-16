"""Speech from the operating system's own offline voices, behind the model server: POST /v1/tts, GET /v1/tts/voices.

Engines (OS_TTS_ENGINE=auto picks the first that works on this machine):
    say     macOS: /usr/bin/say renders to a temp WAV (24 kHz mono 16-bit). At the voice's own pace no `-r` at all
            (a forced rate ruins Siri / premium prosody); another pace -> `-r` relative to the voice's measured native
            words/min. Extra sentence pauses as `[[slnc ms]]`; the voice's own pauses are never shortened. Word timings are estimated (os_voices.estimate_timings).
    winrt   Windows 10/11: Windows.Media.SpeechSynthesis (the OneCore voices) through pywinrt, with real word-boundary
            cues (IncludeWordBoundaryMetadata). In-process, no PowerShell.
    sapi    Windows fallback: SAPI 5 (SAPI.SpVoice through comtypes, in-process). Word timings estimated.
Loading fails open: /health carries the reason and /v1/tts answers 503, so the backend falls back to Deepgram (when a
key is set), then the browser voice. OS_TTS=off turns it off; OS_TTS_ENGINE=say|winrt|sapi forces one.

Request (all but `text` optional; the shape the backend has always sent):
    {text, voice, tag, controls:{rate, pause, …}, guidance, markup, perform:{…, next}, pace}
`voice` is a persona role (guide | capcom | houston | story) or an OS voice id from GET /v1/tts/voices; an unknown id
falls back to the guide's voice. `controls.rate` and `pace` set the speaking rate, a positive `controls.pause` adds
silence between sentences, `perform.next` leaves a short gap at the end (the floor plays sentence by sentence). The
style tag, the other controls, guidance and markup have no OS equivalent: markup is stripped, the rest ignored.
Reply: audio/wav (24 kHz mono 16-bit PCM) + X-TTS-Voice, X-TTS-Voice-Name, X-TTS-Engine, X-TTS-Timing (os | estimated),
X-TTS-Words ('startMs-endMs,…' per display word), X-TTS-Ms, X-TTS-RTF, X-TTS-Rate, X-TTS-Pause-Ms, X-TTS-Pace.
"""
from __future__ import annotations

import collections
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import os_voices as ov
from . import voice_pack
from .config import settings

router = APIRouter()
SR = 24000
TAIL_S = 0.22                  # the gap left after a floor sentence that has a next one
WARM_TEXT = "Ready."
CATALOG_TTL_S = 30.0           # re-list the installed voices at most this often (a parent may add one while it runs)
STATE: dict = {"engine": None, "error": None, "voices": [], "roles": {}, "locale": "", "load_s": None, "warm_ms": None,
               "listed_at": 0.0, "lock": threading.Lock()}
_MEMO: collections.OrderedDict = collections.OrderedDict()
MEMO_MAX = 96
# The voice pack (app/voice_pack.py, docs/VOICE_PACK.md): fixed lines pre-recorded with Siri Voice 1. A callable
# os_voices.pack_key(text) -> {pcm, sr, words, voice, voice_name} or None, asked before the engine renders when the
# request opts in (`pack`), the kid's pace is 1x, the line has no inserted pauses and the voice is the default guide's.
PACK_LOOKUP = voice_pack.lookup


# ================================================================================================= engines
class SayEngine:
    """macOS `say`. Voices listed through NSSpeechSynthesizer (JavaScript for Automation), whose ids `say -v` takes."""
    name, timing = "say", "estimated"
    JXA = ('ObjC.import("AppKit");var v=$.NSSpeechSynthesizer.availableVoices,o=["LOCALE|"+'
           'ObjC.unwrap($.NSLocale.currentLocale.localeIdentifier)];for(var i=0;i<v.count;i++){var id=v.objectAtIndex(i),'
           'a=$.NSSpeechSynthesizer.attributesForVoice(id);o.push([ObjC.unwrap(id),ObjC.unwrap(a.objectForKey("VoiceName")),'
           'ObjC.unwrap(a.objectForKey("VoiceLocaleIdentifier")),ObjC.unwrap(a.objectForKey("VoiceGender"))].join("|"))}'
           'o.join("\\n")')

    def __init__(self):
        if sys.platform != "darwin" or not shutil.which("say"):
            raise RuntimeError("macOS `say` not available")
        self.pool = ThreadPoolExecutor(2, thread_name_prefix="say")
        self._native: dict = {}

    def list_voices(self) -> tuple[list[dict], str]:
        try:
            out = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", self.JXA], capture_output=True,
                                 text=True, timeout=20, check=True).stdout
            voices, loc = parse_jxa(out)
        except (OSError, subprocess.SubprocessError):
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=20).stdout
            voices, loc = parse_say_list(out), os.environ.get("LANG", "")
        return voices + [ov.system_voice_entry(system_voice_id(), voices)], loc

    def render(self, sentences: list[str], voice: str, factor: float, pause_ms: int, tight: bool):
        # At the voice's own pace (factor within NATIVE_BAND of 1) `say` gets NO -r: Siri / premium voices lose their
        # prosody under a forced rate. Otherwise -r is relative to the voice's measured native rate (native_wpm).
        wpm = None if ov.is_native_rate(factor) else int(max(90, min(360, round(self.native_wpm(voice) * factor))))
        sep = f" [[slnc {pause_ms}]] " if pause_ms else " "
        data = self._say(sep.join(sentences), voice, wpm)
        pcm, sr = ov.read_wav(data)
        return pcm, sr, None, {"wpm": wpm or "native"}

    def _say(self, text: str, voice: str, wpm: int | None) -> bytes:
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="outpost-tts-")
        os.close(fd)
        try:
            pick = [] if voice == ov.SYSTEM_ID else ["-v", voice]     # no -v: the Spoken Content system voice
            rate = ["-r", str(wpm)] if wpm else []
            r = subprocess.run(["say", *pick, *rate, "-o", path, "--file-format=WAVE", f"--data-format=LEI16@{SR}"],
                               input=text.encode(), capture_output=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError(f"say failed ({r.returncode}): {r.stderr.decode(errors='replace')[:200]}")
            with open(path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def native_wpm(self, voice: str) -> float:
        """The voice's own speaking rate (words/min of speech), measured once per voice (and per system voice behind
        "system") by rendering CALIBRATION with no -r. Falls back to OS_TTS_WPM."""
        key = (voice, system_voice_id() if voice == ov.SYSTEM_ID else None)
        if key not in self._native:
            try:
                pcm, sr = ov.read_wav(self._say(ov.CALIBRATION, voice, None))
                self._native[key] = ov.measure_wpm(ov.CALIBRATION, pcm, sr) or float(settings.os_tts_wpm)
            except Exception:  # noqa: BLE001
                return float(settings.os_tts_wpm)
        return self._native[key]


def system_voice_id() -> str | None:
    """The Spoken Content system voice for English (com.apple.Accessibility SpokenContentDefaultVoiceSelectionsByLanguage),
    or None when the pref is missing or unreadable."""
    import plistlib
    try:
        out = subprocess.run(["/usr/bin/defaults", "export", "com.apple.Accessibility", "-"], capture_output=True,
                             timeout=10).stdout
        return ov.spoken_content_voice(plistlib.loads(out).get("SpokenContentDefaultVoiceSelectionsByLanguage"))
    except Exception:  # noqa: BLE001 - no pref, no defaults tool, a malformed plist
        return None


def parse_jxa(out: str) -> tuple[list[dict], str]:
    voices, loc = [], ""
    for ln in out.splitlines():
        p = ln.split("|")
        if p[0] == "LOCALE":
            loc = p[1] if len(p) > 1 else ""
            continue
        if len(p) < 3 or not p[0]:
            continue
        g = (p[3] if len(p) > 3 else "").replace("VoiceGender", "").lower()
        voices.append({"id": p[0], "name": p[1] or p[0], "locale": p[2], "gender": g if g in ("female", "male") else "",
                       "quality": ov.mac_quality(p[0]), "engine": "say"})
    return voices, loc


_SAY_LINE = re.compile(r"^(?P<name>.+?)\s{2,}(?P<loc>[a-z]{2,3}_[A-Za-z0-9]+)\s+#")


def parse_say_list(out: str) -> list[dict]:
    """`say -v '?'` fallback: no ids, so the name is the id (and the quality unknown: compact)."""
    voices = []
    for ln in out.splitlines():
        m = _SAY_LINE.match(ln.replace("\t", "  "))
        if m:
            name = m["name"].strip()
            voices.append({"id": f"com.apple.voice.compact.{name}", "say_name": name, "name": name, "locale": m["loc"],
                           "gender": "", "quality": "compact", "engine": "say"})
    return voices


def _token_tail(token_id: str) -> str:
    return re.split(r"[\\/]", str(token_id))[-1]


class WinRTEngine:
    """Windows.Media.SpeechSynthesis: the OneCore voices, with real word timings. One worker thread owns the
    synthesizer (WinRT calls block in `.get()`; the thread is in the multi-threaded apartment)."""
    name, timing = "winrt", "os"

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("WinRT speech is Windows-only")
        self.pool = ThreadPoolExecutor(1, thread_name_prefix="winrt")
        self.pool.submit(self._init).result(timeout=30)

    def _init(self):
        try:
            import winrt.runtime as rt
            rt.init_apartment(rt.MTA)
        except Exception:  # noqa: BLE001 - already initialised on this thread, or an older runtime
            pass
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader
        self.SpeechSynthesizer, self.DataReader = SpeechSynthesizer, DataReader
        try:
            from winrt.windows.media.core import SpeechCue
            self.SpeechCue = SpeechCue
        except Exception:  # noqa: BLE001
            self.SpeechCue = None
        self.synth = SpeechSynthesizer()
        self.info = {}

    def list_voices(self) -> tuple[list[dict], str]:
        return self.pool.submit(self._list).result(timeout=30)

    def _list(self):
        out = []
        for v in self.SpeechSynthesizer.all_voices:
            vid = "winrt:" + _token_tail(v.id)
            self.info[vid] = v
            name = str(v.display_name)
            g = int(getattr(v.gender, "value", v.gender))   # VoiceGender: 0 male, 1 female
            natural = "natural" in name.lower() or "neural" in str(v.id).lower()
            out.append({"id": vid, "name": name, "locale": str(v.language), "gender": "female" if g == 1 else "male",
                        "quality": "neural" if natural else "onecore", "engine": "winrt"})
        return out, windows_locale()

    def render(self, sentences, voice, factor, pause_ms, tight):
        return self.pool.submit(self._render, " ".join(sentences), voice, factor, tight).result(timeout=60)

    def _render(self, text, voice, factor, tight):
        s = self.synth
        if voice in self.info:
            s.voice = self.info[voice]
        o = s.options
        o.include_word_boundary_metadata = True
        o.speaking_rate = float(max(0.5, min(6.0, (1.0 if ov.is_native_rate(factor) else factor) * settings.os_tts_winrt_rate)))
        try:   # Windows 10 1709+: shorter pauses at punctuation for the brisk delivery
            from winrt.windows.media.speechsynthesis import SpeechPunctuationSilence
            o.punctuation_silence = SpeechPunctuationSilence.DEFAULT   # natural pauses, never shortened
        except Exception:  # noqa: BLE001
            pass
        stream = s.synthesize_text_to_stream_async(text).get()
        n = int(stream.size)
        reader = self.DataReader(stream.get_input_stream_at(0))
        reader.load_async(n).get()
        buf = bytearray(n)
        reader.read_bytes(buf)
        cues = []
        for track in stream.timed_metadata_tracks:
            if str(getattr(track, "id", "")) not in ("SpeechWord", "") and len(stream.timed_metadata_tracks) > 1:
                continue
            for c in track.cues:
                c = self.SpeechCue._from(c) if self.SpeechCue is not None and hasattr(self.SpeechCue, "_from") else c
                cues.append(cue_tuple(c))
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass
        pcm, sr = ov.read_wav(bytes(buf))
        return pcm, sr, cues, {"rate": o.speaking_rate}


def _secs(t) -> float:
    """A WinRT TimeSpan as pywinrt projects it (datetime.timedelta), or 100 ns ticks, or None."""
    if t is None:
        return 0.0
    if hasattr(t, "total_seconds"):
        return float(t.total_seconds())
    if hasattr(t, "duration"):
        return float(t.duration) / 1e7
    return float(t) / 1e7


def cue_tuple(c) -> tuple[float, float, int | None, str]:
    a = _secs(getattr(c, "start_time", None))
    d = _secs(getattr(c, "duration", None))
    pos = getattr(c, "start_position_in_input", None)
    pos = getattr(pos, "value", pos)
    return a, a + d, (int(pos) if pos is not None else None), str(getattr(c, "text", "") or "")


SAPI_LCID = {"409": "en-US", "809": "en-GB", "c09": "en-AU", "1009": "en-CA", "1809": "en-IE", "4009": "en-IN",
             "1409": "en-NZ", "1c09": "en-ZA", "4809": "en-SG"}
SAFT24K16MONO, SSFM_CREATE_FOR_WRITE, SVSF_IS_NOT_XML = 26, 3, 16


class SapiEngine:
    """SAPI 5 through comtypes (late-bound, so nothing is generated on disk), on one worker thread."""
    name, timing = "sapi", "estimated"

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("SAPI is Windows-only")
        self.pool = ThreadPoolExecutor(1, thread_name_prefix="sapi")
        self.pool.submit(self._init).result(timeout=30)

    def _init(self):
        import comtypes
        import comtypes.client as cc
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except Exception:  # noqa: BLE001 - already initialised
            pass
        self.cc = cc
        self.voice = cc.CreateObject("SAPI.SpVoice", dynamic=True)
        self.tokens = {}

    def list_voices(self):
        return self.pool.submit(self._list).result(timeout=30)

    def _list(self):
        out, toks = [], self.voice.GetVoices()
        for i in range(toks.Count):
            t = toks.Item(i)
            vid = "sapi:" + _token_tail(t.Id)
            self.tokens[vid] = t
            lang = str(t.GetAttribute("Language") or "").split(";")[0].lower()
            out.append({"id": vid, "name": str(t.GetAttribute("Name") or t.GetDescription()),
                        "locale": SAPI_LCID.get(lang, ""), "gender": str(t.GetAttribute("Gender") or "").lower(),
                        "quality": "sapi", "engine": "sapi"})
        return out, windows_locale()

    def render(self, sentences, voice, factor, pause_ms, tight):
        return self.pool.submit(self._render, " ".join(sentences), voice, factor).result(timeout=60)

    def _render(self, text, voice, factor):
        import math
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="outpost-tts-")
        os.close(fd)
        try:
            fmt = self.cc.CreateObject("SAPI.SpAudioFormat", dynamic=True)
            fmt.Type = SAFT24K16MONO
            st = self.cc.CreateObject("SAPI.SpFileStream", dynamic=True)
            st.Format = fmt
            st.Open(path, SSFM_CREATE_FOR_WRITE, False)
            if voice in self.tokens:
                self.voice.Voice = self.tokens[voice]
            self.voice.Rate = 0 if ov.is_native_rate(factor) else \
                int(max(-10, min(10, round(10 * math.log(max(factor, 0.1)) / math.log(3)))))
            self.voice.AudioOutputStream = st
            try:
                self.voice.Speak(text, SVSF_IS_NOT_XML)
            finally:
                st.Close()
            with open(path, "rb") as f:
                data = f.read()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        pcm, sr = ov.read_wav(data)
        return pcm, sr, None, {"rate": self.voice.Rate}


def windows_locale() -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
            return buf.value
    except Exception:  # noqa: BLE001
        pass
    return ""


ENGINES = {"say": SayEngine, "winrt": WinRTEngine, "sapi": SapiEngine}
AUTO = {"darwin": ("say",), "win32": ("winrt", "sapi")}


# ================================================================================================= catalog
def refresh_catalog(force: bool = False) -> None:
    eng = STATE["engine"]
    if eng is None or (not force and time.monotonic() - STATE["listed_at"] < CATALOG_TTL_S):
        return
    raw, loc = eng.list_voices()
    kid = ov.norm_locale(settings.os_tts_locale or loc)
    ranked = ov.rank(raw, kid)
    STATE["voices"], STATE["roles"], STATE["locale"] = ranked, ov.assign_roles(ranked, kid), kid
    STATE["by_id"] = {v["id"]: v for v in ranked}
    STATE["listed_at"] = time.monotonic()


def resolve(voice: str | None) -> dict:
    """A persona role or an installed voice id -> the voice. Unknown / blocked ids fall back to the guide's voice."""
    by_id, roles = STATE.get("by_id") or {}, STATE["roles"]
    if voice in by_id:
        return by_id[voice]
    if voice in roles:
        return by_id[roles[voice]]
    return by_id[roles["guide"]]


def load() -> None:
    """Pick the engine, list and rank the voices, render a warm-up line. Never raises: the reason goes to /health."""
    t = time.perf_counter()
    STATE.update(engine=None, error=None, voices=[], roles={}, by_id={}, listed_at=0.0, warm_ms=None)
    _MEMO.clear()
    if settings.os_tts.lower() != "on":
        STATE["error"] = "OS_TTS=off"
        return
    want = settings.os_tts_engine.lower()
    names = AUTO.get(sys.platform, ()) if want == "auto" else (want,)
    errs = []
    for n in names:
        try:
            STATE["engine"] = ENGINES[n]()
            refresh_catalog(force=True)
            if not STATE["voices"]:
                raise RuntimeError("no usable English voice installed")
            break
        except Exception as e:  # noqa: BLE001 - try the next engine
            errs.append(f"{n}: {type(e).__name__}: {e}"[:200])
            STATE["engine"] = None
    if STATE["engine"] is None:
        STATE["error"] = "; ".join(errs) or f"no OS voice engine for {sys.platform}"
    else:
        try:
            w = time.perf_counter()
            render(TTSRequest(text=WARM_TEXT, voice="guide"), memo=False)   # first call loads the voice
            STATE["warm_ms"] = round((time.perf_counter() - w) * 1000)
        except Exception as e:  # noqa: BLE001
            STATE["error"] = f"warm-up failed: {type(e).__name__}: {e}"[:300]
            STATE["engine"] = None
    STATE["load_s"] = round(time.perf_counter() - t, 2)


def health() -> dict:
    return {**_health(), **voice_pack.health()}


def _health() -> dict:
    eng, roles = STATE["engine"], STATE["roles"]
    g = (STATE.get("by_id") or {}).get(roles.get("guide")) if roles else None
    return {"tts": {"loaded": eng is not None, "error": STATE["error"], "engine": eng.name if eng else None,
                    "timing": eng.timing if eng else None, "voice": g["id"] if g else None,
                    "voice_name": ov.voice_name(g) if g else None, "voices": len(STATE["voices"]),
                    "roles": roles, "locale": STATE["locale"], "load_s": STATE["load_s"], "warm_ms": STATE["warm_ms"]}}


# ================================================================================================= render
class Perform(BaseModel):
    model_config = ConfigDict(extra="ignore")
    genre: str | None = None
    strength: float | None = None
    para_index: int | None = Field(None, ge=0)
    para_len: int | None = Field(None, ge=1)
    next: str | None = Field(None, max_length=600)


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str = Field(..., min_length=1, max_length=1200)
    voice: str | None = None
    tag: str | None = None                       # accepted, no OS equivalent
    controls: dict[str, float] | None = None     # rate and pause are used
    guidance: float | None = None                # accepted, no OS equivalent
    markup: bool = False                         # markup is always stripped
    perform: Perform | None = None               # only `next` is used (the end gap)
    pace: float = Field(1.0, ge=0.5, le=2.0, description="The kid's speed (>1 faster)")
    pack: bool = Field(False, description="May a recorded voice-pack clip answer (the backend decides: docs/VOICE_PACK.md)")


def render(req: TTSRequest, memo: bool = True) -> tuple[bytes, dict]:
    eng = STATE["engine"]
    v = resolve(req.voice)
    plain = ov.strip_markup(" ".join(req.text.split()))
    if not plain:
        raise HTTPException(400, "nothing to say")
    words = plain.split()
    sentences = ov.split_sentences(plain) or [plain]
    factor = ov.rate_factor(req.controls, req.pace)
    pause = ov.sentence_pause_ms(req.controls)
    tight = False      # a negative `pause` never shortens an OS voice's own pauses (only a positive one adds silence)
    tail = TAIL_S if (req.perform and req.perform.next) else 0.0
    key = json.dumps([eng.name, v["id"], v.get("system_voice"), plain, factor, pause, tight, tail])
    if PACK_LOOKUP is not None and pack_ok(req, v, pause):
        hit = PACK_LOOKUP(ov.pack_key(plain))
        if hit and pack_voice_matches(hit, v):
            return pack_reply(hit, words, v, sentences, tail)
    if memo and key in _MEMO:
        _MEMO.move_to_end(key)
        return _MEMO[key][0], {**_MEMO[key][1], "memo": "hit"}
    # the word after which each sentence ends (for the inserted pauses)
    inserted, n = {}, 0
    for s in sentences[:-1]:
        n += len(s.split())
        if pause:
            inserted[n - 1] = pause / 1000
    pcm, sr, cues, extra = eng.render(sentences, v.get("say_name") or v["id"], factor, pause, tight)
    if sr != SR:
        pcm = ov.resample(pcm, sr, SR)          # cue times are in seconds: unchanged
    times = ov.map_cues(words, ov.word_spans(" ".join(sentences)), cues) if cues else None
    timing = "os" if times else "estimated"
    if times is None:
        times = ov.estimate_timings(words, pcm, SR, rate=factor, inserted=inserted if eng.name == "say" else None)
    if eng.name != "say" and inserted:             # say already put the silence in ([[slnc]])
        pcm, times = ov.insert_silence(pcm, SR, times, inserted)
    if tail:
        pcm = np.concatenate([pcm, np.zeros(int(SR * tail), np.int16)])
    info = {"voice": v["id"], "voice_name": ov.voice_name(v), "engine": eng.name, "timing": timing,
            "rate": factor, "pause_ms": round(tail * 1000) if tail else pause, "sentences": len(sentences),
            "words": ov.words_header(times), "dur_s": len(pcm) / SR, **extra}
    wav = ov.write_wav(pcm, SR)
    if memo:
        _MEMO[key] = (wav, info)
        while len(_MEMO) > MEMO_MAX:
            _MEMO.popitem(last=False)
    return wav, {**info, "memo": "miss"}


def pack_ok(req: TTSRequest, v: dict, pause: int) -> bool:
    """A pack clip may answer: the caller opted in, the kid's pace is 1x (a clip is never time-stretched: any other pace
    renders live), no extra sentence pauses (slow explain / vocab lines), and the voice is this machine's default guide
    voice (a kid who picked another voice hears that voice, live)."""
    return bool(req.pack) and abs(float(req.pace or 1.0) - 1.0) < 1e-3 and not pause and \
        v["id"] == (STATE.get("roles") or {}).get("guide")


def pack_voice_matches(hit: dict, v: dict) -> bool:
    """A recorded clip plays only when the live guide voice IS the voice it was recorded in (the macOS Siri voice
    "Nora"). Otherwise a Windows voice, or a Mac set to another system voice, would alternate between the studio
    clips and the live voice line by line. Different voice -> every line live, in one voice."""
    pv = (hit.get("voice") or "").lower()
    if not pv:
        return True
    ids = {str(v.get("id") or "").lower(), str(v.get("system_voice") or "").lower()}
    if pv in ids:
        return True
    name = (hit.get("voice_name") or "").lower()
    vn = " ".join(str(v.get(k) or "") for k in ("name", "system_name")).lower()
    return bool(name) and any(t in vn for t in ("nora",) if t in name)


def pack_reply(hit: dict, words: list[str], v: dict, sentences: list[str], tail: float) -> tuple[bytes, dict]:
    """A clip in the live reply's shape: 24 kHz mono WAV, the end gap when a sentence follows, word timings (the
    recorded ones when they cover the same display words, else estimated on the clip)."""
    pcm = ov.resample(hit["pcm"], hit["sr"], SR)
    stored = ov.parse_words(hit.get("words") or "")
    times = stored if stored and len(stored) == len(words) else ov.estimate_timings(words, pcm, SR)
    if tail:
        pcm = np.concatenate([pcm, np.zeros(int(SR * tail), np.int16)])
    return ov.write_wav(pcm, SR), {"voice": v["id"], "voice_name": hit.get("voice_name") or ov.voice_name(v),
                                   "engine": "pack", "timing": "estimated", "rate": 1.0,
                                   "pause_ms": round(tail * 1000) if tail else 0, "sentences": len(sentences),
                                   "words": ov.words_header(times), "dur_s": len(pcm) / SR, "memo": "pack"}


@router.post("/v1/tts")
async def tts_route(req: TTSRequest):
    if STATE["engine"] is None:
        raise HTTPException(503, f"OS voice not available: {STATE['error']}")
    t = time.perf_counter()
    try:
        wav, info = await run_in_threadpool(render, req)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - an engine failure: the backend falls back
        raise HTTPException(502, f"OS voice render failed: {type(e).__name__}: {e}"[:300])
    ms = (time.perf_counter() - t) * 1000
    return Response(wav, media_type="audio/wav", headers={
        "X-TTS-Voice": info["voice"], "X-TTS-Voice-Name": info["voice_name"], "X-TTS-Engine": info["engine"],
        "X-TTS-Timing": info["timing"], "X-TTS-Words": info["words"], "X-TTS-Ms": f"{ms:.0f}",
        "X-TTS-RTF": f"{ms / 1000 / max(info['dur_s'], 1e-3):.3f}", "X-TTS-Rate": f"{info['rate']:.2f}",
        "X-TTS-Pause-Ms": str(info["pause_ms"]), "X-TTS-Sentences": str(info["sentences"]),
        "X-TTS-Pace": f"{req.pace:.2f}", "X-TTS-Memo": info["memo"],
        "Access-Control-Expose-Headers": "X-TTS-Words, X-TTS-Voice, X-TTS-Engine"})


@router.get("/v1/tts/voices")
async def voices():
    if STATE["engine"] is None:
        raise HTTPException(503, f"OS voice not available: {STATE['error']}")
    try:
        await run_in_threadpool(refresh_catalog)
    except Exception:  # noqa: BLE001 - keep the last good list
        pass
    pick = {v["id"] for v in ov.picker(STATE["voices"])}
    return {"engine": STATE["engine"].name, "timing": STATE["engine"].timing, "locale": STATE["locale"],
            "default": STATE["roles"].get("guide"), "roles": STATE["roles"],
            "voices": [{"id": v["id"], "name": ov.base_name(v["name"]), "full_name": v["name"], "locale": v["locale"],
                        "gender": v.get("gender") or "", "quality": v["quality"], "desc": ov.describe(v),
                        "rank": v["rank"], "picker": v["id"] in pick, "system_voice": v.get("system_voice")} for v in STATE["voices"]]}
