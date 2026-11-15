"""OS voices, the pure parts (app/os_voices.py): ranking, novelty filtering, persona roles, the macOS system voice,
rate mapping, word-timing estimation and WAV handling. No OS calls: runs on any machine."""
import io
import struct
import wave

import numpy as np
import pytest

from app import os_voices as ov


def mac(vid, name, loc, gender="female"):
    return {"id": vid, "name": name, "locale": loc, "gender": gender, "quality": ov.mac_quality(vid), "engine": "say"}


MAC = [
    mac("com.apple.voice.compact.en-US.Samantha", "Samantha", "en_US"),
    mac("com.apple.voice.compact.en-GB.Daniel", "Daniel", "en_GB", "male"),
    mac("com.apple.voice.Tara", "Tara (English (India))", "en_IN"),
    mac("com.apple.voice.Tara.premium", "Tara (English (India))", "en_IN"),
    mac("com.apple.voice.Aman.premium", "Aman (English (India))", "en_IN", "male"),
    mac("com.apple.voice.enhanced.en-US.Ava", "Ava", "en_US"),
    mac("com.apple.voice.premium.en-GB.Kate", "Kate", "fr_FR"),          # a premium voice, but not English: dropped
    mac("com.apple.eloquence.en-US.Reed", "Reed (English (US))", "en_US", ""),
    mac("com.apple.voice.compact.fr-FR.Thomas", "Thomas", "fr_FR", "male"),
    # novelty voices, by every spelling macOS uses
    mac("com.apple.speech.synthesis.voice.Bells", "Bells", "en_US"),
    mac("com.apple.speech.synthesis.voice.Deranged", "Wobble", "en_US"),
    mac("com.apple.speech.synthesis.voice.Hysterical", "Jester", "en_US"),
    mac("com.apple.speech.synthesis.voice.Princess", "Superstar", "en_US"),
    mac("com.apple.speech.synthesis.voice.Zarvox", "Zarvox", "en_US", "male"),
    mac("com.apple.speech.synthesis.voice.Fred", "Fred", "en_US", "male"),
    mac("com.apple.speech.synthesis.voice.BadNews", "Bad News", "en_US", "male"),
    # not an Apple voice id at all
    {"id": "org.example.voice.Ava.premium", "name": "Ava", "locale": "en_US", "quality": "premium", "engine": "say"},
]


def test_novelty_and_foreign_voices_never_ranked():
    ids = [v["id"] for v in ov.rank(MAC, "en-US")]
    assert not [i for i in ids if "speech.synthesis.voice" in i], ids
    assert "com.apple.voice.compact.fr-FR.Thomas" not in ids              # English only
    assert "org.example.voice.Ava.premium" not in ids                     # outside the allowlist
    for name in ("Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Wobble", "Jester", "Organ",
                 "Superstar", "Zarvox", "Trinoids", "Whisper", "Good News", "Fred", "Junior", "Ralph", "Kathy"):
        assert ov.is_novelty({"name": name, "id": "com.apple.voice.compact.en-US." + name.replace(" ", "")})


def test_quality_from_both_mac_id_spellings():
    assert ov.mac_quality("com.apple.voice.premium.en-US.Zoe") == ov.mac_quality("com.apple.voice.Tara.premium") == "premium"
    assert ov.mac_quality("com.apple.voice.enhanced.en-US.Evan") == "enhanced"
    assert ov.mac_quality("com.apple.voice.compact.en-US.Samantha") == "compact"
    assert ov.mac_quality("com.apple.eloquence.en-US.Reed") == "eloquence"


def test_premium_first_then_enhanced_then_compact_then_eloquence():
    r = ov.rank(MAC, "en-US")
    assert [v["quality"] for v in r] == ["premium", "premium", "enhanced", "compact", "compact", "eloquence"]
    assert r[0]["id"] == "com.apple.voice.Tara.premium" and r[0]["rank"] == 0   # ties: a woman's voice first
    assert sum(1 for v in r if v["name"].startswith("Tara")) == 1             # Tara + Tara.premium: the best one kept


def test_locale_preference_inside_a_quality_tier():
    vs = [mac("com.apple.voice.compact.en-GB.Daniel", "Daniel", "en_GB"),
          mac("com.apple.voice.compact.en-US.Samantha", "Samantha", "en_US"),
          mac("com.apple.voice.compact.en-IN.Rishi", "Rishi", "en_IN"),
          mac("com.apple.voice.compact.en-ZA.Tessa", "Tessa", "en_ZA")]
    assert [v["locale"] for v in ov.rank(vs, "en-US")] == ["en-US", "en-GB", "en-IN", "en-ZA"]
    assert [v["locale"] for v in ov.rank(vs, "en_IN")] == ["en-IN", "en-US", "en-GB", "en-ZA"]   # the kid's first
    assert [v["locale"] for v in ov.rank(vs, "fr-FR")][0] == "en-US"                              # not English: en-US


def test_windows_neural_beats_onecore_beats_sapi():
    vs = [{"id": "sapi:TTS_MS_EN-US_ZIRA_11.0", "name": "Microsoft Zira Desktop", "locale": "en-US", "quality": "sapi",
           "engine": "sapi"},
          {"id": "winrt:MSTTS_V110_enUS_DavidM", "name": "Microsoft David", "locale": "en-US", "gender": "male",
           "quality": "onecore", "engine": "winrt"},
          {"id": "winrt:MSTTS_V110_enUS_AriaNeural", "name": "Microsoft Aria (Natural)", "locale": "en-US",
           "gender": "female", "quality": "neural", "engine": "winrt"},
          {"id": "winrt:Sample", "name": "Sample TTS Voice", "locale": "en-US", "quality": "onecore", "engine": "winrt"}]
    r = ov.rank(vs, "en-US")
    assert [v["quality"] for v in r] == ["neural", "onecore", "sapi"]
    assert ov.base_name(r[0]["name"]) == "Aria" and ov.base_name(r[2]["name"]) == "Zira"


def test_roles_give_capcom_a_different_voice_when_two_good_ones_exist():
    r = ov.rank(MAC, "en-US")
    roles = ov.assign_roles(r)
    assert roles["guide"] == "com.apple.voice.Tara.premium"
    assert roles["capcom"] == "com.apple.voice.Aman.premium"               # the other gender, same tier
    assert roles["houston"] == "com.apple.voice.enhanced.en-US.Ava"       # a third good voice (one tier down)
    assert set(roles) == set(ov.ROLES)
    one = ov.rank([MAC[0]], "en-US")
    assert set(ov.assign_roles(one).values()) == {MAC[0]["id"]}            # one voice: every role uses it
    assert ov.assign_roles([]) == {}


def test_picker_hides_eloquence_unless_few_voices():
    r = ov.rank(MAC, "en-US")
    assert all(v["quality"] != "eloquence" for v in ov.picker(r))
    little = ov.rank([MAC[0], next(v for v in MAC if "eloquence" in v["id"])], "en-US")
    assert len(ov.picker(little)) == 2


# ---- the macOS Spoken Content system voice ------------------------------------------------------------------------
PREF_FLAT = ["en", {"_type": "Speech.VoiceSelection", "_version": 0, "boundLanguage": "en",
                    "voiceId": "com.apple.siri.natural.Nora"}]


@pytest.mark.parametrize("pref,want", [
    (PREF_FLAT, "com.apple.siri.natural.Nora"),                                        # macOS 26: a flat list
    ({"en": {"voiceId": "com.apple.voice.Tara.premium"}}, "com.apple.voice.Tara.premium"),   # a dict
    (["fr", {"voiceId": "com.apple.voice.compact.fr-FR.Thomas"}, "en-GB", {"voiceId": "x.y.Z"}], "x.y.Z"),
    (None, None), ([], None), ("junk", None), (["en"], None), (["en", {"voiceId": 3}], None), ({"en": "nope"}, None),
])
def test_spoken_content_pref_is_read_defensively(pref, want):
    assert ov.spoken_content_voice(pref) == want


def test_a_siri_system_voice_is_the_default():
    sysv = ov.system_voice_entry("com.apple.siri.natural.Nora", MAC)
    r = ov.rank(MAC + [sysv], "en-US")
    assert r[0]["id"] == ov.SYSTEM_ID and r[0]["name"] == "Your Mac's system voice"
    assert ov.describe(r[0]) == "Nora (Siri)" and ov.voice_name(r[0]) == "Nora (Siri)"
    roles = ov.assign_roles(r, "en-US")
    # a good system voice: guide, CAPCOM and the story share it (no voice flip between live and recorded lines);
    # Houston gets a distinct good voice in the kid's locale family (Ava, en-US enhanced), never Tara/Aman (en-IN)
    assert roles == {"guide": ov.SYSTEM_ID, "capcom": ov.SYSTEM_ID, "story": ov.SYSTEM_ID,
                     "houston": "com.apple.voice.enhanced.en-US.Ava"}
    no_us = [v for v in MAC if "Ava" not in v["id"]]
    r2 = ov.rank(no_us + [sysv], "en-US")
    assert ov.assign_roles(r2, "en-US")["houston"] == ov.SYSTEM_ID       # only en-IN good voices: Houston = system too
    r3 = ov.rank(no_us + [ov.system_voice_entry("com.apple.voice.Tara.premium", no_us)], "en-IN")
    assert ov.assign_roles(r3, "en-IN") == {"guide": ov.SYSTEM_ID, "capcom": ov.SYSTEM_ID, "story": ov.SYSTEM_ID,
                                            "houston": "com.apple.voice.Aman.premium"}   # en-IN kid; never Tara itself


def test_a_premium_system_voice_is_the_default_a_compact_one_is_not():
    prem = ov.rank(MAC + [ov.system_voice_entry("com.apple.voice.Tara.premium", MAC)], "en-US")
    assert prem[0]["id"] == ov.SYSTEM_ID and ov.describe(prem[0]) == "Tara (Premium)"
    comp = ov.rank(MAC + [ov.system_voice_entry("com.apple.voice.compact.en-US.Samantha", MAC)], "en-US")
    assert comp[0]["id"] == "com.apple.voice.Tara.premium"
    assert ov.assign_roles(comp, "en-US")["capcom"] == "com.apple.voice.Aman.premium"   # not a good system voice: ranking
    assert ov.SYSTEM_ID in [v["id"] for v in comp]                           # still offered in Settings
    none = ov.rank(MAC + [ov.system_voice_entry(None, MAC)], "en-US")
    assert none[0]["id"] != ov.SYSTEM_ID and ov.SYSTEM_ID in [v["id"] for v in none]


# ---- rate / pause ---------------------------------------------------------------------------------------------------
def test_rate_factor_follows_rate_z_and_pace():
    assert ov.rate_factor(None) == 1.0
    assert ov.rate_factor({"rate": 4.0}) == ov.rate_factor({"rate": 2.5})       # clamped
    assert ov.rate_factor({"rate": 1.0}, 1.25) > ov.rate_factor({"rate": 1.0}) > ov.rate_factor({"rate": -1.0})
    assert ov.rate_factor({"rate": "fast"}, "x") == 1.0
    assert ov.sentence_pause_ms({"pause": -1.5}) == 0 and 0 < ov.sentence_pause_ms({"pause": 0.6}) <= 500


def test_markup_is_stripped_for_the_voice_and_the_captions():
    t = "<slow><emph>Albedo</emph></slow>: albedo is *40* percent [[rate 400]]."
    assert ov.strip_markup(t) == "Albedo: albedo is 40 percent (rate 400)."
    assert ov.display_words(t) == ["Albedo:", "albedo", "is", "40", "percent", "(rate", "400)."]
    assert ov.pack_key("Copy, *Commander*! Shields to 40%.") == "copy commander shields to 40%"


# ---- word timings ---------------------------------------------------------------------------------------------------
SR = 24000


def speech(segments, sr=SR, seed=0):
    """Noise bursts for words, true silence between them: [(word seconds, gap seconds after)]."""
    rng = np.random.default_rng(seed)
    out, t, truth = [np.zeros(int(0.1 * sr), np.int16)], 0.1, []
    for dur, gap in segments:
        n = int(dur * sr)
        out.append((rng.normal(0, 0.2, n) * np.hanning(n) ** 0.2 * 32767).clip(-32767, 32767).astype(np.int16))
        truth.append((t, t + dur))
        t += dur
        out.append(np.zeros(int(gap * sr), np.int16))
        t += gap
    return np.concatenate(out), truth


def test_timings_cover_the_speech_and_snap_to_real_pauses():
    words = "Good morning, Commander! The rover found ice.".split()
    # the voice ran words together inside phrases and paused at the comma and the "!"
    segs = [(0.25, 0.0), (0.35, 0.22), (0.6, 0.45), (0.12, 0.0), (0.3, 0.0), (0.3, 0.0), (0.3, 0.0)]
    pcm, truth = speech(segs)
    t = ov.estimate_timings(words, pcm, SR)
    assert len(t) == len(words)
    assert all(a <= b for a, b in t) and all(t[i][1] <= t[i + 1][0] + 1e-6 for i in range(len(t) - 1))
    assert abs(t[0][0] - truth[0][0]) < 0.03 and abs(t[-1][1] - truth[-1][1]) < 0.03     # the speech span
    assert abs(t[1][1] - truth[1][1]) < 0.03 and abs(t[2][0] - truth[2][0]) < 0.03       # the comma pause, exactly
    assert abs(t[2][1] - truth[2][1]) < 0.03 and abs(t[3][0] - truth[3][0]) < 0.03       # the sentence pause
    hdr = ov.words_header(t)
    assert hdr.count(",") == len(words) - 1 and all("-" in p for p in hdr.split(","))


def test_timings_weight_long_words_longer_and_survive_silence():
    t = ov.estimate_timings(["I", "understand", "everything"], speech([(1.5, 0)])[0], SR)
    assert (t[1][1] - t[1][0]) > 2 * (t[0][1] - t[0][0])
    silent = ov.estimate_timings(["Hello", "there."], np.zeros(SR, np.int16), SR)
    assert len(silent) == 2 and silent[-1][1] <= 1.0
    assert ov.estimate_timings([], np.zeros(10, np.int16), SR) == []


def test_inserted_silence_is_honoured():
    pcm, truth = speech([(0.3, 0.0), (0.3, 0.8), (0.3, 0.0)])
    t = ov.estimate_timings(["One", "two.", "Three."], pcm, SR, inserted={1: 0.8})
    assert abs(t[2][0] - truth[2][0]) < 0.05


def test_syllables():
    assert ov.syllables("cat") == 1 and ov.syllables("Commander!") == 3 and ov.syllables("40") >= 2
    assert ov.syllables("2.5") > ov.syllables("25") and ov.syllables("percent%") > ov.syllables("percent")


def test_winrt_cues_map_onto_display_words():
    text = "Copy, Commander. Shields to 40 percent."
    words = text.split()
    spans = ov.word_spans(text)
    cues = [(0.0, 0.3, 0, "Copy"), (0.35, 0.9, 6, "Commander"), (1.2, 1.5, 17, "Shields"), (1.5, 1.6, 25, "to"),
            (1.6, 2.0, 28, "40"), (2.0, 2.4, 31, "percent")]
    t = ov.map_cues(words, spans, cues)
    assert t == [(0.0, 0.3), (0.35, 0.9), (1.2, 1.5), (1.5, 1.6), (1.6, 2.0), (2.0, 2.4)]
    no_pos = [(a, b, None, w) for a, b, _, w in cues]                          # no positions: matched by text, in order
    assert ov.map_cues(words, spans, no_pos) == t
    assert ov.map_cues(words, spans, cues[:2]) is None                         # too few cues: estimate instead


def test_insert_silence_shifts_later_words():
    x = np.ones(SR, np.int16)
    y, t = ov.insert_silence(x, SR, [(0.0, 0.4), (0.5, 0.9)], {0: 0.25})
    assert len(y) == SR + SR // 4 and t[0] == (0.0, 0.4) and t[1] == (0.75, 1.15)


# ---- WAV ----------------------------------------------------------------------------------------------------------
def wav_bytes(sr=22050, ch=1, bits=16, extra=b""):
    x = (np.sin(np.arange(sr // 10) / 5) * 10000).astype(np.int16)
    if ch == 2:
        x = np.repeat(x, 2)
    data = x.astype("<i2").tobytes()
    fmt = struct.pack("<HHIIHH", 1, ch, sr, sr * ch * 2, ch * 2, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + extra + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_read_wav_handles_extra_chunks_stereo_and_resampling():
    fllr = b"FLLR" + struct.pack("<I", 7) + b"\0" * 7 + b"\0"        # macOS filler chunk, odd size + pad byte
    x, sr = ov.read_wav(wav_bytes(extra=fllr))
    assert sr == 22050 and x.dtype == np.int16 and len(x) == 2205
    y, sr2 = ov.read_wav(wav_bytes(ch=2))
    assert len(y) == 2205 and sr2 == 22050
    z = ov.resample(x, 22050, 24000)
    assert abs(len(z) - 2400) <= 1
    with wave.open(io.BytesIO(ov.write_wav(z, 24000))) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
    with pytest.raises(ValueError):
        ov.read_wav(b"not a wav at all")
