"""Server TTS for the guide channel (docs/SESSION_CONTRACT.md §4, docs/VOICE_STEERING.md).

GET  /api/tts?text=…&voice=guide|capcom|story|houston[&style=<json>][&i=&n=&next=]  → audio, cached on disk by hash
POST /api/tts {text, voice, style?, i?, n?, next?}                                      → the same

Engines (TTS_ENGINE=os|deepgram, default os; the kid's Settings can add Steer in front, style.tts_engine = "steer"):
  steer     Steer TTS Edge on the model server (POST /v1/tts/steer), the optional engine: the whole style (tag, controls,
            emphasis markup, the performance director's plan) and the model's own word timings. → audio/wav
  os        The operating system's own offline voice on the model server (POST /v1/tts; macOS `say`, Windows WinRT /
            SAPI): the persona's role (or the kid's chosen voice) at the style's rate and pauses. → audio/wav + word
            timings
  deepgram  Deepgram Aura-2 over REST. → audio/mpeg
Fallback chain: [steer →] os → deepgram (when DEEPGRAM_API_KEY is set) → 503 {"fallback":"browser"} (speechSynthesis).
Steer not downloaded yet (or failing): the line is spoken by the OS voice, with X-TTS-Fallback saying why. The recorded
voice pack never speaks with Steer selected (steering.pack_allowed): every line renders live in Steer.

`style` is the `say.style` the Director sent (backend/app/steering.py); without one the persona's default style is
used, so `/api/tts?text=&voice=` keeps working. `i`/`n`/`next` place the sentence in its text (the client splits long
text into sentences and asks for one at a time, prefetching the next; a sentence with a next one ends on a short gap).
The cache key holds the engine, the concrete OS voice, the text and the style, so a re-steered line or a newly
installed voice never plays a stale rendering.

The browser plays this as in-page audio, so Chrome's echo canceller can subtract it from the mic.
"""
from __future__ import annotations

import hashlib
import math
import re
import json
import os
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import loudness, narration, steering
from .config import settings
from .local_guard import auth_headers

router = APIRouter()

SPEAK_URL = "https://api.deepgram.com/v1/speak"
MAX_CHARS = 600
Persona = Literal["guide", "capcom", "story", "houston"]
# Deepgram Aura-2 voices (the fallback engine): a warm guide, a crisp CAPCOM, a younger voice for the hardware's story.
VOICES: dict[str, str] = {
    "guide": "aura-2-thalia-en",    # warm, clear, friendly
    "capcom": "aura-2-orion-en",    # calm, crisp male: mission control
    "story": "aura-2-iris-en",      # young, cheerful
    "houston": "aura-2-orion-en",
}
MEDIA = {"os": ("audio/wav", ".wav"), "steer": ("audio/wav", ".wav"), "deepgram": ("audio/mpeg", ".mp3")}

CACHE_DIR: Path | None = None     # tests point this elsewhere; default data_dir/tts_cache (gitignored)
PREF_KEYS = ("tts_voice", "speed", "expr", "volume", "pack", "tts_engine", "steer_voice")
PACK_PERSONAS = ("guide", "capcom")   # the recorded voice pack covers these (docs/VOICE_PACK.md); Houston, story: live
MASTER_VERSION = 4                # in the cache key: bump when the delivery baseline or the mastering changes


def cache_dir() -> Path:
    return CACHE_DIR or settings.tts_cache()


def cache_path(model: str, text: str, style: dict | None = None, engine: str = "deepgram") -> Path:
    """Engine + voice/model + text + style (canonical JSON) → one file. Deepgram ignores style (it can't steer)."""
    key = f"{model}\n{text}" if engine == "deepgram" else \
        f"{engine}\n{model}\n{text}\n{json.dumps(style or {}, sort_keys=True, separators=(',', ':'))}"
    h = hashlib.sha256(key.encode()).hexdigest()[:32]
    return cache_dir() / f"{h}{MEDIA[engine][1]}"


def clean_style(voice: str, text: str, style: dict | None) -> dict:
    """The client's style (from the Director) made safe, or the persona default. Only what reaches the engine.
    Settings ride on the style (docs/VOICES.md): `tts_voice` (an installed OS voice id or a persona role), `speed` (the rate
    setting, applied in speak()), `expr` (expressiveness 0–1, steering.with_expressiveness) and `volume` (the master
    volume, 1 = the loudness target; applied in speak())."""
    prefs = {k: style[k] for k in PREF_KEYS if k in style} if isinstance(style, dict) else {}
    if not isinstance(style, dict) or not (set(style) - set(PREF_KEYS)):
        style = steering.style_for(voice, text)   # none, or only Settings: the persona default style, with them
    elif "tag" not in style:   # the client named only the situation (e.g. a badge line it wrote itself)
        sit = style.get("situation") if style.get("situation") in steering.SITUATIONS else None
        persona = style.get("voice") if style.get("voice") in steering.VOICES else voice
        style = steering.style_for(persona, text, situation=sit,
                                   vocab=style.get("vocab") if isinstance(style.get("vocab"), list) else None)
    persona = style.get("voice") if style.get("voice") in steering.VOICES else voice
    tag = str(style.get("tag") or "none")
    if tag in steering.FORBIDDEN:
        tag = steering.PERSONA_BASE[persona]["tag"]
    ctrl = {}
    for k, v in (style.get("controls") or {}).items():
        try:
            ctrl[str(k)] = round(max(-steering.CONTROL_LIMIT, min(steering.CONTROL_LIMIT, float(v))), 2)
        except (TypeError, ValueError):
            continue
    out = {"voice": persona, "tts_voice": steering.VOICES[persona], "tag": tag, "controls": ctrl}
    if style.get("situation") in steering.SITUATIONS:       # picks the loudness target and the slow-line baseline
        out["situation"] = style["situation"]
    emph = [str(w)[:40] for w in (style.get("emph") or []) if str(w).strip()][:4]
    if emph:
        out["emph"] = emph
    vocab = [str(w)[:40] for w in (style.get("vocab") or []) if str(w).strip()][:3]   # a11y: vocab words (§4b)
    if vocab:
        out["vocab"] = vocab
    if style.get("guidance"):
        out["guidance"] = max(1.0, min(2.0, float(style["guidance"])))
    perf = style.get("perform")
    if isinstance(perf, dict):
        out["perform"] = {"genre": str(perf.get("genre") or "children"),
                          "strength": max(0.0, min(1.0, float(perf.get("strength", 0.7))))}
    # ---- Settings (docs/VOICES.md) ----
    from . import voices
    if voices.allowed(prefs.get("tts_voice")):
        out["tts_voice"] = prefs["tts_voice"]
    if "expr" in prefs:
        e = steering.clamp_expr(prefs["expr"])
        out["tag"], out["controls"], p2 = steering.with_expressiveness(out["tag"], out["controls"], out.get("perform"), e)
        if p2 is not None:
            out["perform"] = p2
        out["expr"] = e
    try:
        sp = float(prefs["speed"]) if prefs.get("speed") is not None else None
    except (TypeError, ValueError):
        sp = None
    if sp is not None and sp == sp:
        out["speed"] = round(max(0.5, min(2.0, sp)), 2)
    try:
        vol = float(prefs["volume"]) if prefs.get("volume") is not None else None
    except (TypeError, ValueError):
        vol = None
    if vol is not None and vol == vol and abs(vol - 1.0) > 1e-3:
        out["volume"] = round(max(0.0, min(2.0, vol)), 2)
    if prefs.get("pack") is False:
        out["pack"] = False
    if prefs.get("tts_engine") == "steer":       # Settings -> Voice: Steer TTS (the optional engine)
        out["tts_engine"] = "steer"
        out["steer_voice"] = prefs["steer_voice"] if voices.steer_allowed(prefs.get("steer_voice")) else \
            steering.STEER_VOICES.get(persona, steering.STEER_VOICES["guide"])
        out["pack"] = False
    return out


# ---- the recorded voice pack (docs/VOICE_PACK.md) ----------------------------------------------------------------------
def pack_version() -> str:
    """Changes whenever the pack's index changes (a re-recorded clip must not be shadowed by the TTS cache)."""
    try:
        st = (settings.voice_pack() / "index.json").stat()
        return f"{st.st_mtime_ns:x}-{st.st_size:x}"
    except OSError:
        return ""


def use_pack(st: dict, pace: float) -> bool:
    """A line may come from the voice pack: the Settings toggle is on (and no other voice was picked: the client and
    the session send pack=false then), the persona is the guide or CAPCOM, the kid's pace is 1x (a clip is never
    time-stretched; any other pace is rendered live), the line is not a slow explain / vocab line, and a pack exists.
    CAPCOM keeps no separate voice while the pack speaks: its live lines use the guide voice too, so the character
    never switches voices between a recorded line and a live one."""
    from . import voices
    return (st.get("pack") is not False and st.get("voice") in PACK_PERSONAS and abs(pace - 1.0) < 1e-3
            and st.get("situation") not in steering.SLOW_SITUATIONS and not st.get("vocab")
            and st.get("tts_voice") in ("guide", "capcom", voices.roles().get("guide")) and bool(pack_version()))


def gain_for_volume(volume: float | None) -> float:
    """Master volume (1 = 100% = the loudness target) → gain in dB into the limiter: up to +6 dB above, down to -30."""
    try:
        v = float(volume if volume is not None else 1.0)
    except (TypeError, ValueError):
        v = 1.0
    if v <= 0.03:
        return loudness.MIN_GAIN_DB
    return round(max(loudness.MIN_GAIN_DB, min(loudness.MAX_GAIN_DB, 20 * math.log10(v))), 2)


def target_lufs(st: dict) -> float:
    return loudness.TARGET_LUFS + (loudness.ALARM_LUFS_OFFSET if st.get("situation") in steering.ALARM_SITUATIONS else 0)


def _remap_words(words: str, keep) -> str:
    """Word timings (ms) after cap_gaps removed samples: each time maps to the kept samples before it."""
    if not words or keep is None:
        return words
    import numpy as np
    sr, kept = keep
    c = np.concatenate([[0], np.cumsum(kept)])
    n = len(kept)

    def m(ms):
        i = min(n, max(0, int(round(int(ms) * sr / 1000))))
        return int(round(c[i] * 1000 / sr))
    out = []
    for pair in words.split(","):
        a, b = pair.split("-")
        out.append(f"{m(a)}-{max(m(a), m(b))}")
    return ",".join(out)


def finish(audio: bytes, st: dict, words: str, last: bool, limiter: bool = False) -> tuple[bytes, str, dict | None]:
    """The final stage for every OS-voice render (§4d): cut only pathological silences (the voice's own pauses stay),
    then one clean gain to the loudness target (+2 LU for alarms, + the kid's volume) with a -1 dBTP true-peak ceiling:
    no limiter or compressor on the OS voices (a peaky line plays slightly under target instead).
    Fails open: audio that isn't 16-bit WAV goes out as it came."""
    try:
        x, sr = loudness.read_wav(audio)
    except Exception:  # noqa: BLE001
        return audio, words, None
    y, kept = loudness.cap_gaps(x, sr, max_gap_s=st.get("gap_s", steering.GAP_FAST_S),
                                tail_s=0.05 if last else 0.22, with_mask=True)
    # Steer (limiter=True, as before the OS voices): its peaks are steady, a -1 dBTP look-ahead limiter holds them
    y, info = loudness.master(y, sr, target_lufs(st), gain_for_volume(st.get("volume")), limiter=limiter)
    return loudness.write_wav(y, sr), _remap_words(words, (sr, kept)), info


async def _synth(model: str, text: str) -> bytes:
    """One Deepgram Aura call. Raises httpx.HTTPError (or RuntimeError on a non-audio reply)."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(SPEAK_URL, params={"model": model, "encoding": "mp3"},
                         headers={"Authorization": f"Token {settings.deepgram_api_key}"}, json={"text": text})
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"deepgram speak {r.status_code}: {r.text[:160]}")
    return r.content


async def _os_tts(text: str, style: dict, place: dict) -> tuple[bytes, str, str]:
    """One OS-voice render on the model server → (wav, word timings header). Raises on any failure (the caller falls
    back). The model server strips the emphasis markup and uses the rate / pause controls (model_server/app/tts_os.py)."""
    marked = bool(style.get("emph") or style.get("vocab"))
    body = {"text": steering.apply_markup(text, style.get("emph"), style.get("vocab")) if marked else text,
            "voice": style["tts_voice"], "tag": style["tag"], "controls": style["controls"] or None,
            "markup": marked}
    if style.get("pace", 1.0) != 1.0:
        body["pace"] = style["pace"]
    if style.get("guidance"):
        body["guidance"] = style["guidance"]
    if style.get("pack_on"):
        body["pack"] = True
    if style.get("perform"):
        body["perform"] = {**style["perform"], **{k: v for k, v in place.items() if v is not None}}
    async with httpx.AsyncClient(base_url=settings.model_server_url, timeout=settings.tts_timeout_s, headers=auth_headers()) as c:
        r = await c.post("/v1/tts", json=body)
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"os tts {r.status_code}: {r.text[:160]}")
    return r.content, r.headers.get("X-TTS-Words", ""), r.headers.get("X-TTS-Engine", "os")


async def _steer(text: str, style: dict, place: dict) -> tuple[bytes, str]:
    """One Steer TTS Edge render on the model server → (wav, word timings header). Raises on any failure (the caller
    falls back to the OS voice). Restored from before 7ea1bad."""
    marked = bool(style.get("emph") or style.get("vocab"))
    body = {"text": steering.apply_markup(text, style.get("emph"), style.get("vocab")) if marked else text,
            "voice": style["steer_voice"], "tag": style["tag"], "controls": style["controls"] or None,
            "markup": marked}
    if style.get("pace", 1.0) != 1.0:
        body["pace"] = style["pace"]
    if style.get("guidance"):
        body["guidance"] = style["guidance"]
    if style.get("perform"):
        body["perform"] = {**style["perform"], **{k: v for k, v in place.items() if v is not None}}
    async with httpx.AsyncClient(base_url=settings.model_server_url, timeout=settings.tts_timeout_s, headers=auth_headers()) as c:
        r = await c.post("/v1/tts/steer", json=body)
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"steer tts {r.status_code}: {r.text[:160]}")
    return r.content, r.headers.get("X-Steer-Words", "")


# ---- a11y: word timings for captions (docs/ACCESSIBILITY.md) -----------------------------------------------------------
WORDS_RE = re.compile(r"^(\d+-\d+)(,\d+-\d+)*$")


def words_path(p: Path) -> Path:
    """The word-timing sidecar next to a cached rendering."""
    return p.with_suffix(".words")


def engine_path(p: Path) -> Path:
    """Which engine made a cached OS rendering ("pack" for a voice-pack clip), for X-TTS-Engine on a cache hit."""
    return p.with_suffix(".engine")


def clean_words(raw: str | None) -> str:
    """Only a well-formed 'start-end,…' (ms) list passes through to the client."""
    raw = (raw or "").strip()
    return raw if raw and len(raw) < 8000 and WORDS_RE.match(raw) else ""


def _store(p: Path, audio: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(audio)
    tmp.replace(p)


async def speak(text: str, voice: str = "guide", style: dict | None = None, i: int | None = None,
                n: int | None = None, next_text: str | None = None, speed: float | None = None):
    text = " ".join(text.split())
    if not text:
        return JSONResponse({"error": "empty text"}, status_code=422)
    # The narration rule (narration.py): every engine speaks the spoken form ("mSv" -> "millisieverts"); the word
    # timings are mapped back onto the display words, which the captions show.
    display, text = text, narration.spoken(text)
    next_text = narration.spoken(next_text) if next_text else next_text
    reasons: list[str] = []
    engines = ["deepgram"] if settings.tts_engine == "deepgram" else ["os", "deepgram"]   # "steer" (old .env) = os
    if "os" in engines and isinstance(style, dict) and style.get("tts_engine") == "steer":
        engines.insert(0, "steer")              # the kid picked Steer (Settings): first, the OS voice behind it
    from . import voices
    if "os" in engines:
        await voices.refresh()
    for engine in engines:
        if engine in ("os", "steer"):
            st = clean_style(voice, text, style)
            speed = speed if speed is not None else st.pop("speed", None)   # an explicit ?speed= wins over Settings
            st.pop("speed", None)
            # the delivery baseline + the kid's speed (§4d): faster at 1x; vocab / explain lines stay slow on purpose
            slow = st.get("situation") in steering.SLOW_SITUATIONS or bool(st.get("vocab"))
            st["controls"], pace, st["gap_s"] = steering.delivery(st["controls"], speed, slow)
            if pace != 1.0:
                st["pace"] = pace
            place = {"para_index": i, "para_len": n, "next": " ".join((next_text or "").split())[:MAX_CHARS] or None}
            if engine == "steer":
                for k in ("pack", "tts_voice", "tts_engine"):
                    st.pop(k, None)
                model, key = st["steer_voice"], {**st, **{k: v for k, v in place.items() if v is not None},
                                                 "master": MASTER_VERSION}
            else:
                st.pop("tts_engine", None)
                st.pop("steer_voice", None)
                if use_pack(st, pace):
                    st["pack_on"] = pack_version()
                    st["tts_voice"] = "guide"                       # CAPCOM speaks in the guide voice with the pack
                st.pop("pack", None)
                st["tts_voice"] = voices.resolve(st["tts_voice"])     # the role -> this machine's voice for it
                model, key = st["tts_voice"], {**st, "voice_tag": voices.cache_tag(st["tts_voice"]), **{k: v for k, v in place.items() if v is not None},
                                                 "master": MASTER_VERSION}
        else:
            if not settings.deepgram_api_key:
                reasons.append("deepgram: DEEPGRAM_API_KEY is not set")
                continue
            st, model, key = None, VOICES[voice], None
        p = cache_path(model, text, key, engine)
        media = MEDIA[engine][0]
        headers = {"Cache-Control": "public, max-age=604800", "X-TTS-Voice": model, "X-TTS-Engine": engine,
                   "Access-Control-Expose-Headers": "X-TTS-Words, X-TTS-Engine, X-TTS-Style, X-TTS-Speed, X-TTS-Loudness"}
        if st:
            headers["X-TTS-Speed"] = f"{speed or 1} pace={st.get('pace', 1.0)} rate={st['controls'].get('rate', 0)}"
        if st:
            headers["X-TTS-Style"] = f"{st['tag']} " + ",".join(f"{k}={v}" for k, v in st["controls"].items())
        if reasons:
            headers["X-TTS-Fallback"] = "; ".join(reasons)[:200]
        if p.exists():
            wp, ep = words_path(p), engine_path(p)
            w = clean_words(wp.read_text()) if wp.exists() else ""
            if ep.exists():
                headers["X-TTS-Engine"] = ep.read_text().strip()[:16] or engine
            return Response(p.read_bytes(), media_type=media,
                            headers={**headers, "X-TTS-Cache": "hit", **({"X-TTS-Words": w} if w else {})})
        try:
            if engine == "steer":
                audio, words = await _steer(text, st, place)
                audio, words, info = finish(audio, st, clean_words(words), last=not place.get("next"), limiter=True)
                if info and info.get("lufs") is not None:
                    headers["X-TTS-Loudness"] = f"{info['lufs']} LUFS {info['tp']} dBTP"
            elif engine == "os":
                res = await _os_tts(text, st, place)
                res = res if isinstance(res, tuple) else (res, "")
                audio, words = res[0], res[1]
                made_by = res[2] if len(res) > 2 and res[2] in ("pack", "say", "winrt", "sapi") else "os"
                headers["X-TTS-Engine"] = "pack" if made_by == "pack" else "os"
                audio, words, info = finish(audio, st, clean_words(words), last=not place.get("next"))
                words = narration.display_timings(display, text, words)
                if info and info.get("lufs") is not None:
                    headers["X-TTS-Loudness"] = f"{info['lufs']} LUFS {info['tp']} dBTP"
            else:
                audio, words = await _synth(model, text), ""
        except Exception as e:  # noqa: BLE001 - any upstream failure means "next engine"
            reasons.append(f"{engine}: {str(e)[:160]}")
            continue
        _store(p, audio)
        words = clean_words(words)
        if words:
            words_path(p).write_text(words)
        if engine == "os":
            engine_path(p).write_text(headers["X-TTS-Engine"])
        return Response(audio, media_type=media,
                        headers={**headers, "X-TTS-Cache": "miss", **({"X-TTS-Words": words} if words else {})})
    no_engine = all(r.startswith("deepgram: DEEPGRAM_API_KEY") for r in reasons)
    return JSONResponse({"error": "tts unavailable" if no_engine else "tts failed", "reason": "; ".join(reasons)[:300],
                         "fallback": "browser"}, status_code=503 if no_engine else 502)


def _parse_style(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


@router.get("/api/tts")
async def tts(text: str = Query(..., min_length=1, max_length=MAX_CHARS), voice: Persona = "guide",
              style: str | None = Query(None, max_length=2000), i: int | None = Query(None, ge=0, le=200),
              n: int | None = Query(None, ge=1, le=200), next: str | None = Query(None, max_length=MAX_CHARS),  # noqa: A002
              speed: float | None = Query(None, ge=0.5, le=2.0)):
    return await speak(text, voice, _parse_style(style), i, n, next, speed)


class TTSBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_CHARS)
    voice: Persona = "guide"
    style: dict | None = None
    i: int | None = Field(None, ge=0, le=200)
    n: int | None = Field(None, ge=1, le=200)
    next: str | None = Field(None, max_length=MAX_CHARS)
    speed: float | None = Field(None, ge=0.5, le=2.0)


@router.post("/api/tts")
async def tts_post(b: TTSBody):
    return await speak(b.text, b.voice, b.style, b.i, b.n, b.next, b.speed)
