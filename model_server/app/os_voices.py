"""The operating system's own offline voices: ranking, persona roles, text clean-up, word-timing estimation, WAV I/O.

Pure functions only (no OS calls), so every rule here is unit-tested on any machine; app/tts_os.py does the talking.

Ranking (docs/VOICES.md):
    quality   premium > enhanced > neural / OneCore > standard > compact / SAPI > Eloquence
    locale    the kid's locale, then en-US, then en-GB / en-AU / en-IE / en-IN / en-CA / en-NZ, then any other English
    never     novelty voices (blocklist by name) and anything outside the per-engine allowlist; English only
"""
from __future__ import annotations

import io
import math
import re
import struct
import wave

import numpy as np

# ---- voice ranking -----------------------------------------------------------------------------------------------------
TIERS = {"siri": 7, "premium": 6, "enhanced": 5, "neural": 4, "onecore": 3, "standard": 3, "compact": 2, "sapi": 2, "eloquence": 1}
QUALITY_LABEL = {"siri": "Siri", "premium": "Premium", "enhanced": "Enhanced", "neural": "Natural", "onecore": "Standard",
                 "standard": "Standard", "compact": "Compact", "sapi": "Classic", "eloquence": "Basic"}
EN_ORDER = ("en-US", "en-GB", "en-AU", "en-IE", "en-IN", "en-CA", "en-NZ")
LOCALE_NAMES = {"en-US": "US", "en-GB": "UK", "en-AU": "Australia", "en-IE": "Ireland", "en-IN": "India",
                "en-CA": "Canada", "en-NZ": "New Zealand", "en-ZA": "South Africa", "en-SG": "Singapore"}
# macOS novelty / joke voices (and their file-id spellings), plus Windows test voices. Never picked, never listed.
NOVELTY = frozenset(n.lower() for n in (
    "Albert", "Bad News", "BadNews", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Wobble", "Deranged", "Jester",
    "Hysterical", "Organ", "Pipe Organ", "Superstar", "Princess", "Zarvox", "Trinoids", "Whisper", "Good News",
    "GoodNews", "Fred", "Junior", "Ralph", "Kathy", "Agnes", "Bruce", "Vicki", "Victoria", "Sample TTS Voice"))
# Engine allowlists: an id outside these prefixes is never used, whatever its name.
MAC_PREFIXES = ("com.apple.voice.", "com.apple.eloquence.", "com.apple.speech.synthesis.voice.", "com.apple.ttsbundle.")


def norm_locale(loc: str | None) -> str:
    """'en_US', 'en-us', 'en_IN@rg=inzzzz' -> 'en-US'. '' for nothing."""
    s = str(loc or "").split("@")[0].split(".")[0].replace("_", "-").strip()
    if not s:
        return ""
    parts = s.split("-")
    return parts[0].lower() + ("-" + parts[1].upper() if len(parts) > 1 and parts[1] else "")


def base_name(name: str) -> str:
    """'Tara (English (India))' -> 'Tara'; 'Microsoft Zira Desktop' -> 'Zira'; 'Microsoft Aria (Natural)' -> 'Aria'."""
    s = re.sub(r"\s*\(.*$", "", str(name or "")).strip()
    s = re.sub(r"^Microsoft\s+", "", s)
    s = re.sub(r"\s+(Desktop|Online|Mobile)$", "", s)
    return s.split(" - ")[0].strip() or str(name or "").strip()


def mac_quality(vid: str) -> str:
    v = vid.lower()     # both spellings: com.apple.voice.premium.en-US.Zoe and com.apple.voice.Tara.premium
    if v.endswith(".premium") or ".premium." in v:
        return "premium"
    if v.endswith(".enhanced") or ".enhanced." in v:
        return "enhanced"
    if v.startswith("com.apple.eloquence."):
        return "eloquence"
    if ".compact." in v or v.startswith("com.apple.speech.synthesis.voice."):
        return "compact"
    return "standard"


def is_novelty(v: dict) -> bool:
    name = str(v.get("name") or "")
    vid = str(v.get("id") or "")
    tail = vid.rsplit(".", 1)[-1].lower() if vid.startswith("com.apple.speech.synthesis.voice.") else ""
    return name.lower() in NOVELTY or base_name(name).lower() in NOVELTY or tail in NOVELTY


def allowed(v: dict) -> bool:
    """Allowlist + blocklist: English, a known engine's id shape, not a novelty voice."""
    if not norm_locale(v.get("locale")).startswith("en"):
        return False
    if is_novelty(v):
        return False
    eng = v.get("engine")
    vid = str(v.get("id") or "")
    if eng == "say":
        return vid == SYSTEM_ID or vid.startswith(MAC_PREFIXES)
    if eng in ("winrt", "sapi"):
        return bool(vid)
    return False


# ---- macOS: the Spoken Content "System voice" -----------------------------------------------------------------------
# `say` without -v speaks with the voice the user picked in System Settings → Accessibility → Spoken Content → System
# voice. That can be a Siri voice, which apps cannot name (`say -v com.apple.siri…` fails, NSSpeechSynthesizer does
# not list it), so the system voice is its own entry: id "system", rendered with no -v.
SYSTEM_ID = "system"
SYSTEM_NAME = "Your Mac's system voice"


def spoken_content_voice(pref, lang: str = "en") -> str | None:
    """The voice id in com.apple.Accessibility SpokenContentDefaultVoiceSelectionsByLanguage for `lang`. Shapes seen:
    a flat list [lang, {voiceId…}, lang, {…}] (macOS 26), or a dict {lang: {voiceId…}}; anything else -> None."""
    pairs = []
    if isinstance(pref, dict):
        pairs = list(pref.items())
    elif isinstance(pref, (list, tuple)):
        pairs = [(pref[i], pref[i + 1]) for i in range(0, len(pref) - 1, 2)]
    for want in (lang, None):          # the exact language first, then any English selection
        for k, sel in pairs:
            if not isinstance(k, str) or not isinstance(sel, dict):
                continue
            if (k == want) or (want is None and k.lower().startswith("en")):
                vid = sel.get("voiceId") or sel.get("VoiceIdentifier")
                if isinstance(vid, str) and vid:
                    return vid
    return None


def system_voice_entry(voice_id: str | None, listed: list[dict]) -> dict:
    """The "system" catalog entry. Its quality follows the voice behind it: a Siri voice outranks everything (so it is
    the default), a premium / enhanced voice ranks just above that voice's own entry, anything else (or an unreadable
    pref) just below a compact voice: listed, never the default."""
    vid = voice_id or ""
    by_id = {v["id"]: v for v in listed}
    if vid.startswith("com.apple.siri."):
        name = vid.rsplit(".", 1)[-1]
        quality, label, tier = "siri", f"{name} (Siri)", TIERS["siri"]
    elif vid in by_id:
        q = by_id[vid].get("quality") or mac_quality(vid)
        label = f"{base_name(by_id[vid]['name'])} ({QUALITY_LABEL.get(q, q)})"
        quality, tier = q, TIERS.get(q, 0) + (0.5 if q in ("premium", "enhanced") else -0.5)
    else:
        quality, label, tier = "standard", "", TIERS["compact"] - 0.5
    return {"id": SYSTEM_ID, "name": SYSTEM_NAME, "voice_label": label, "system_voice": vid or None, "locale": "en",
            "gender": by_id.get(vid, {}).get("gender", ""), "quality": quality, "engine": "say", "tier": tier}


def locale_rank(loc: str, kid: str | None) -> int:
    loc, kid = norm_locale(loc), norm_locale(kid)
    if kid and kid.startswith("en") and loc == kid:
        return 0
    if loc in EN_ORDER:
        return 1 + EN_ORDER.index(loc)
    return 1 + len(EN_ORDER)


def rank(voices: list[dict], kid_locale: str | None = None) -> list[dict]:
    """Filter (allowlist, no novelty, English), de-duplicate (one entry per name + locale: the best quality), sort best
    first. Each voice gets `tier` and `rank` (0 = the default)."""
    best: dict[tuple, dict] = {}
    for v in voices:
        if not allowed(v):
            continue
        v = {**v, "locale": norm_locale(v.get("locale")), "tier": v.get("tier", TIERS.get(v.get("quality"), 0))}
        k = (base_name(v.get("name", "")).lower(), v["locale"], v.get("engine"))
        if k not in best or v["tier"] > best[k]["tier"]:
            best[k] = v
    # ties (same quality, same locale preference): a woman's voice first, as the app's guide has always been (CAPCOM
    # then gets the man's voice, assign_roles), then by name
    out = sorted(best.values(), key=lambda v: (-v["tier"], locale_rank(v["locale"], kid_locale),
                                               GENDER_ORDER.get(v.get("gender") or "", 2),
                                               base_name(v.get("name", "")).lower(), v["id"]))
    for i, v in enumerate(out):
        v["rank"] = i
    return out


GENDER_ORDER = {"female": 0, "male": 1}
PICKER_MAX = 12


def picker(ranked: list[dict]) -> list[dict]:
    """The voices Settings offers: the ranked list without the low-quality Eloquence voices (unless fewer than three
    better ones exist), at most PICKER_MAX."""
    better = [v for v in ranked if v["tier"] > TIERS["eloquence"]]
    return (better if len(better) >= 3 else ranked)[:PICKER_MAX]


ROLES = ("guide", "capcom", "houston", "story")


GOOD_QUALITY = ("siri", "premium", "enhanced")
HOUSTON_LOCALES = ("en-US", "en-GB")


def assign_roles(ranked: list[dict], kid_locale: str | None = None) -> dict[str, str]:
    """Persona -> voice id.

    A good system voice (Siri, premium or enhanced) at the top: the guide, CAPCOM and the story all speak in it, so a
    character never flips voices (Flight School and Mission talk through CAPCOM; the recorded voice pack is the system
    voice too: docs/VOICE_PACK.md). Houston, a separate radio voice, gets a distinct good voice in the kid's locale family
    (the kid's own locale, then en-US, en-GB), never the voice behind the system voice; without one, it is the system
    voice as well.

    Otherwise (no good system voice: the ranking below): the guide gets the best voice. CAPCOM gets a different good voice (one quality tier at most
    below the guide's; another gender first), Houston a third, else CAPCOM's; the story voice a fourth, else the
    guide's. With one voice installed every role uses it."""
    if not ranked:
        return {}
    g = ranked[0]
    if g.get("id") == SYSTEM_ID and g.get("quality") in GOOD_QUALITY:
        fam = [l for l in (norm_locale(kid_locale), *HOUSTON_LOCALES) if l and l.startswith("en")]
        cands = [v for v in ranked[1:] if v.get("quality") in GOOD_QUALITY and v["locale"] in fam
                 and v["id"] != g.get("system_voice") and v["id"] != SYSTEM_ID]
        cands.sort(key=lambda v: (fam.index(v["locale"]), -v["tier"], v["rank"] if "rank" in v else 0))
        hou = cands[0]["id"] if cands else SYSTEM_ID
        return {"guide": SYSTEM_ID, "capcom": SYSTEM_ID, "houston": hou, "story": SYSTEM_ID}
    good = [v for v in ranked[1:] if v["tier"] >= max(TIERS["compact"], g["tier"] - 1)]
    cap = next((v for v in good if v.get("gender") and g.get("gender") and v["gender"] != g["gender"]),
               good[0] if good else g)
    used = {g["id"], cap["id"]}
    hou = next((v for v in good if v["id"] not in used), cap)
    used.add(hou["id"])
    sto = next((v for v in good if v["id"] not in used), g)
    return {"guide": g["id"], "capcom": cap["id"], "houston": hou["id"], "story": sto["id"]}


def describe(v: dict) -> str:
    """A short Settings line: 'Premium · India · female'; for the system voice, the voice behind it ('Nora (Siri)')."""
    if v.get("id") == SYSTEM_ID:
        return v.get("voice_label") or "The voice set in System Settings"
    bits = [QUALITY_LABEL.get(v.get("quality"), ""), LOCALE_NAMES.get(v.get("locale"), v.get("locale", ""))]
    if v.get("gender") in ("female", "male"):
        bits.append(v["gender"])
    return " · ".join(b for b in bits if b)


# ---- rate / pause mapping ----------------------------------------------------------------------------------------------
RATE_Z_PER_OCTAVE = 4.0      # the backend's speed slope (backend/app/steering.py SPEED_RATE_SLOPE): z 4 = 2x


def rate_factor(controls: dict | None, pace: float = 1.0) -> float:
    """The style's `rate` z-score and the kid's pace -> one speed multiplier (1 = the voice's base rate)."""
    try:
        z = max(-2.5, min(2.5, float((controls or {}).get("rate", 0.0))))
    except (TypeError, ValueError):
        z = 0.0
    try:
        p = max(0.5, min(2.0, float(pace or 1.0)))
    except (TypeError, ValueError):
        p = 1.0
    return round(max(0.5, min(2.2, p * 2 ** (z / RATE_Z_PER_OCTAVE))), 3)


# Within this band of 1x the OS voice speaks at its own rate (no `say -r`, WinRT rate 1, SAPI 0): the persona and
# situation nudges (CAPCOM +0.3 z ~ 1.05x) are not worth a forced rate, which degrades Siri / premium prosody audibly.
NATIVE_BAND = 0.08
CALIBRATION = ("The Moon always shows Earth the same face. Shackleton crater sits at the south pole, "
               "and its rim gets sunlight on most days.")


def is_native_rate(factor: float) -> bool:
    return abs(float(factor) - 1.0) < NATIVE_BAND


def measure_wpm(text: str, pcm: np.ndarray, sr: int) -> float | None:
    """Words per minute of a rendering, over its speech span (leading / trailing silence excluded)."""
    t0, t1, _ = silences(pcm, sr)
    n = len(text.split())
    return round(n / (t1 - t0) * 60, 1) if t1 - t0 > 0.5 and n else None


def sentence_pause_ms(controls: dict | None) -> int:
    """Extra silence between sentences from the `pause` z-score: only a positive z adds (slow, explaining lines);
    a negative one is the voice's own pauses (the backend caps long gaps anyway)."""
    try:
        z = float((controls or {}).get("pause", 0.0))
    except (TypeError, ValueError):
        z = 0.0
    return int(min(500, round(160 * z))) if z > 0 else 0


# ---- the voice-pack seam ---------------------------------------------------------------------------------------------
def pack_key(text: str) -> str:
    """A fixed line's voice-pack key (app/voice_pack.py): markup stripped, lower case, letters, digits, % and single
    spaces only. backend/tools/voice_pack_lines.py keys the manifest with this same function."""
    return " ".join(re.sub(r"[^a-z0-9%]+", " ", strip_markup(text).lower()).split())


# ---- text -------------------------------------------------------------------------------------------------------------
_MARK = re.compile(r"</?[a-zA-Z]+[^>]*>|\*")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“'‘(\[])")


def strip_markup(text: str) -> str:
    """The app's emphasis markup (`*word*`, `<emph>…</emph>`, `<slow>…</slow>`) and any embedded-command brackets
    removed: the OS voices read plain text."""
    t = _MARK.sub("", text)
    t = t.replace("[[", "(").replace("]]", ")")
    return " ".join(t.split())


def display_words(text: str) -> list[str]:
    """The words a caption shows: the sentence without markup, split on whitespace."""
    return strip_markup(text).split()


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s.strip()]


def parse_words(header: str) -> list[tuple[float, float]] | None:
    """'start-end,…' (ms) -> [(start s, end s)]; None when malformed."""
    try:
        out = []
        for p in str(header or "").split(","):
            a, b = p.split("-")
            out.append((int(a) / 1000, int(b) / 1000))
        return out or None
    except ValueError:
        return None


def words_header(times: list[tuple[float, float]]) -> str:
    """Compact ASCII header: 'start-end' in ms per display word, comma separated."""
    return ",".join(f"{round(a * 1000)}-{round(max(a, b) * 1000)}" for a, b in times)


# ---- word timings: an estimate anchored on the audio ---------------------------------------------------------------
_VOWELS = re.compile(r"[aeiouy]+")


def syllables(word: str) -> float:
    """A rough syllable count for one display token, digits read out ('40' ~ 2, '2.5' ~ 3, '%' ~ 2)."""
    w = word.lower()
    n = 0.0
    digits = re.findall(r"\d", w)
    if digits:
        n += 1.4 * len(digits) + (1 if re.search(r"\d[.,]\d", w) else 0)
    letters = re.sub(r"[^a-z]", "", w)
    if letters:
        groups = len(_VOWELS.findall(letters))
        if letters.endswith("e") and not letters.endswith(("le", "ee")) and groups > 1:
            groups -= 1
        n += max(1, groups)
    n += 2 * w.count("%")
    return max(1.0, n)


def word_weight(word: str) -> float:
    letters = len(re.sub(r"[^A-Za-z0-9]", "", word))
    return syllables(word) + 0.12 * letters


SENT_PAUSE_S, CLAUSE_PAUSE_S = 0.34, 0.16


def pause_after(word: str) -> float:
    """The nominal pause after a token, from its trailing punctuation (seconds at rate 1)."""
    w = word.rstrip("\"”’')]")
    if w.endswith(("...", "…")) or w[-1:] in ".!?":
        return SENT_PAUSE_S
    if w[-1:] in ",;:" or word in ("—", "–", "-"):
        return CLAUSE_PAUSE_S
    return 0.0


def silences(pcm: np.ndarray, sr: int, min_s: float = 0.08, frame_s: float = 0.01) -> tuple[float, float, list]:
    """(speech start s, speech end s, [(start, end) of inner silences >= min_s]) by frame energy (-32 dB of the
    loudest frame). Whole-clip span when the clip is silent."""
    x0 = np.asarray(pcm)
    x = x0.astype(np.float32)
    if x0.dtype.kind in "iu":
        x = x / 32768.0
    hop = max(1, int(sr * frame_s))
    n = len(x) // hop
    if n == 0:
        return 0.0, len(x) / max(sr, 1), []
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    thr = max(rms.max() * 10 ** (-32 / 20), 1e-4)
    voiced = rms > thr
    if not voiced.any():
        return 0.0, len(x) / sr, []
    first, last = int(np.argmax(voiced)), int(n - 1 - np.argmax(voiced[::-1]))
    out, run = [], None
    for i in range(first, last + 1):
        if not voiced[i]:
            run = i if run is None else run
        elif run is not None:
            if (i - run) * frame_s >= min_s:
                out.append((run * frame_s, i * frame_s))
            run = None
    return first * frame_s, (last + 1) * frame_s, out


def estimate_timings(words: list[str], pcm: np.ndarray, sr: int, rate: float = 1.0,
                     inserted: dict[int, float] | None = None) -> list[tuple[float, float]]:
    """Word times for a render that gave none (macOS `say`, SAPI): the rendered speech span is spread over the words by
    syllable/character weight, with punctuation pauses; each sentence / clause break then snaps to the nearest real
    silence in the audio, so errors cannot build up across a long line. `inserted` = {word index: seconds of silence
    we put after that word} (e.g. `[[slnc]]`), which is known exactly."""
    if not words:
        return []
    t0, t1, gaps = silences(pcm, sr)
    span = max(t1 - t0, 1e-3)
    inserted = inserted or {}
    w = [word_weight(x) for x in words]
    p = [(pause_after(x) / max(rate, 0.3) if i < len(words) - 1 else 0.0) + inserted.get(i, 0.0)
         for i, x in enumerate(words)]
    talk = span - sum(p)
    if talk < 0.35 * span:              # the voice paused less than we guessed: shrink the pauses, keep the words
        scale = 0.65 * span / max(sum(p), 1e-6)
        p = [x * scale for x in p]
        talk = span - sum(p)
    k = talk / sum(w)
    est, t = [], t0
    for wi, pi in zip(w, p):
        est.append([t, t + k * wi])
        t += k * wi + pi
    # snap each break to a real silence: unused gap whose centre is nearest the guess, within a tolerance
    breaks = [i for i in range(len(words) - 1) if p[i] > 0]
    tol = max(0.25, 0.12 * span)
    used, anchors = set(), {}
    for i in breaks:
        mid = (est[i][1] + est[i + 1][0]) / 2
        best = min((g for g in range(len(gaps)) if g not in used), default=None,
                   key=lambda g: abs((gaps[g][0] + gaps[g][1]) / 2 - mid))
        if best is not None and abs((gaps[best][0] + gaps[best][1]) / 2 - mid) <= tol:
            # keep breaks in order: an anchor must not jump behind an earlier one
            prev = max((anchors[j][1] for j in anchors), default=t0)
            if gaps[best][0] >= prev:
                used.add(best)
                anchors[i] = gaps[best]
    # lay the words out phrase by phrase between anchors
    out = [None] * len(words)
    cuts = sorted(anchors)
    start, s_t = 0, t0
    for c in cuts + [len(words) - 1]:
        end_t = anchors[c][0] if c in anchors else t1
        idx = list(range(start, c + 1))
        units = [w[i] * k for i in idx]
        inner = [p[i] for i in idx[:-1]]
        tot = sum(units) + sum(inner)
        f = (end_t - s_t) / tot if tot > 0 else 0.0
        t = s_t
        for j, i in enumerate(idx):
            a = t
            t += units[j] * f
            out[i] = (round(a, 3), round(t, 3))
            if j < len(inner):
                t += inner[j] * f
        if c in anchors:
            s_t = anchors[c][1]
        start = c + 1
    return out


def map_cues(display: list[str], spans: list[tuple[int, int]], cues: list[tuple[float, float, int | None, str]]
             ) -> list[tuple[float, float]] | None:
    """Real word-boundary cues (WinRT: start s, end s, char position in the input, text) -> one time per display word.
    `spans` are each display word's [start, end) character offsets in the text that was spoken. Cues land on the word
    whose span holds their position, else in order by text. A word no cue hit borrows its neighbour's edge. None when
    the cues cover too few words to trust (the caller then estimates)."""
    if not display or not cues:
        return None
    hit: dict[int, list] = {}
    nxt = 0
    for a, b, pos, txt in cues:
        k = None
        if pos is not None:
            k = next((i for i, (s, e) in enumerate(spans) if s <= pos < e), None)
        if k is None:
            t = re.sub(r"\W", "", str(txt or "")).lower()
            k = next((i for i in range(nxt, len(display)) if re.sub(r"\W", "", display[i]).lower() == t), None)
        if k is None:
            continue
        nxt = k + 1
        if k in hit:
            hit[k][1] = max(hit[k][1], b)
        else:
            hit[k] = [a, b]
    if len(hit) < max(1, math.ceil(0.6 * len(display))):
        return None
    out: list[tuple[float, float]] = []
    for i in range(len(display)):
        if i in hit:
            out.append((round(hit[i][0], 3), round(max(hit[i][0], hit[i][1]), 3)))
        else:
            t = out[-1][1] if out else min(v[0] for v in hit.values())
            out.append((t, t))
    return out


def word_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


# ---- WAV ----------------------------------------------------------------------------------------------------------------
def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    """Any PCM WAV (16/24/32-bit int or 32-bit float, any channels, extra chunks such as macOS FLLR / LIST, a streaming
    data size) -> (int16 mono, sample rate)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV")
    pos, fmt, pcm = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8: pos + 8 + size] if size != 0xFFFFFFFF else data[pos + 8:]
        if cid == b"fmt ":
            tag, ch, sr, _, _, bits = struct.unpack_from("<HHIIHH", body, 0)
            if tag == 0xFFFE and len(body) >= 26:           # WAVE_FORMAT_EXTENSIBLE: the sub-format's tag
                tag = struct.unpack_from("<H", body, 24)[0]
            fmt = (tag, ch, sr, bits)
        elif cid == b"data":
            pcm = body
            if size == 0xFFFFFFFF or pos + 8 + size > len(data):
                break
        pos += 8 + size + (size & 1)
    if fmt is None or pcm is None:
        raise ValueError("WAV without fmt/data")
    tag, ch, sr, bits = fmt
    if tag == 3 and bits == 32:
        x = np.frombuffer(pcm[: len(pcm) // 4 * 4], "<f4")
        x = np.clip(x, -1, 1) * 32767
    elif tag == 1 and bits == 16:
        x = np.frombuffer(pcm[: len(pcm) // 2 * 2], "<i2").astype(np.float32)
    elif tag == 1 and bits == 32:
        x = np.frombuffer(pcm[: len(pcm) // 4 * 4], "<i4").astype(np.float32) / 65536
    elif tag == 1 and bits == 24:
        b = np.frombuffer(pcm[: len(pcm) // 3 * 3], np.uint8).reshape(-1, 3).astype(np.int32)
        x = ((b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)) << 8 >> 8).astype(np.float32) / 256
    elif tag == 1 and bits == 8:
        x = (np.frombuffer(pcm, np.uint8).astype(np.float32) - 128) * 256
    else:
        raise ValueError(f"unsupported WAV format tag={tag} bits={bits}")
    if ch > 1:
        x = x[: len(x) // ch * ch].reshape(-1, ch).mean(axis=1)
    return np.clip(np.round(x), -32768, 32767).astype(np.int16), int(sr)


def resample(x: np.ndarray, sr: int, to: int) -> np.ndarray:
    if sr == to or not len(x):
        return x
    from math import gcd

    from scipy.signal import resample_poly
    g = gcd(sr, to)
    y = resample_poly(x.astype(np.float32), to // g, sr // g)
    return np.clip(np.round(y), -32768, 32767).astype(np.int16)


def write_wav(x: np.ndarray, sr: int) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.asarray(x, np.int16).astype("<i2").tobytes())
    return b.getvalue()


def insert_silence(x: np.ndarray, sr: int, times: list[tuple[float, float]], after: dict[int, float]
                   ) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """Splice `after[i]` seconds of silence into the audio midway between word i and word i+1, shifting later times."""
    if not after or not times:
        return x, times
    cuts = []
    for i, s in sorted(after.items()):
        if 0 <= i < len(times) - 1 and s > 0:
            cuts.append(((times[i][1] + times[i + 1][0]) / 2, s, i))
    if not cuts:
        return x, times
    parts, prev = [], 0
    for t, s, _ in cuts:
        k = min(len(x), max(prev, int(round(t * sr))))
        parts += [x[prev:k], np.zeros(int(round(s * sr)), np.int16)]
        prev = k
    parts.append(x[prev:])
    out, shift, j = [], 0.0, 0
    for i, (a, b) in enumerate(times):
        out.append((round(a + shift, 3), round(b + shift, 3)))
        while j < len(cuts) and cuts[j][2] == i:
            shift += cuts[j][1]
            j += 1
    return np.concatenate(parts), out


def voice_name(v: dict) -> str:
    """What a header / log calls the voice: 'Tara', or for the system voice the voice behind it ('Nora (Siri)')."""
    if v.get("id") == SYSTEM_ID:
        return v.get("voice_label") or SYSTEM_NAME
    return base_name(v.get("name", ""))
