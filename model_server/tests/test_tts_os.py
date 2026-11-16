"""POST /v1/tts + GET /v1/tts/voices on the OS voices (app/tts_os.py): the reply contract, the macOS `say` command line
and system-voice pref, and the Windows engines with WinRT / comtypes mocked (sys.platform faked, as in
test_platform_win.py). A last test renders for real when this machine is a Mac."""
import datetime
import io
import re
import struct
import sys
import types
import wave

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import os_voices as ov
from app import tts_os
from app.config import settings

SR = 24000


def tone_wav(seconds, sr=SR, gaps=()):
    x = (np.sin(np.arange(int(seconds * sr)) / 7) * 9000).astype(np.int16)
    for a, b in gaps:
        x[int(a * sr):int(b * sr)] = 0
    return ov.write_wav(x, sr)


@pytest.fixture
def fresh(monkeypatch):
    saved = dict(tts_os.STATE)
    tts_os._MEMO.clear()
    monkeypatch.setattr(tts_os, "PACK_LOOKUP", None)
    yield
    tts_os.STATE.clear()
    tts_os.STATE.update(saved)
    tts_os._MEMO.clear()


class FakeEngine:
    name, timing = "say", "estimated"

    def __init__(self):
        self.calls = []

    def list_voices(self):
        return [{"id": "com.apple.voice.Tara.premium", "name": "Tara (English (India))", "locale": "en_IN",
                 "gender": "female", "quality": "premium", "engine": "say"},
                {"id": "com.apple.voice.Aman.premium", "name": "Aman (English (India))", "locale": "en_IN",
                 "gender": "male", "quality": "premium", "engine": "say"},
                {"id": "com.apple.speech.synthesis.voice.Bells", "name": "Bells", "locale": "en_US",
                 "quality": "compact", "engine": "say"}], "en_US"

    def render(self, sentences, voice, factor, pause_ms, tight):
        self.calls.append((sentences, voice, factor, pause_ms))
        n = sum(len(s.split()) for s in sentences)
        return ov.read_wav(tone_wav(0.3 * n, sr=22050))[0], 22050, None, {"wpm": 180}


@pytest.fixture
def client(fresh, monkeypatch):
    eng = FakeEngine()
    monkeypatch.setitem(tts_os.ENGINES, "fake", lambda: eng)
    monkeypatch.setattr(settings, "os_tts_engine", "fake")
    monkeypatch.setattr(settings, "os_tts", "on")
    tts_os.load()
    app = FastAPI()
    app.include_router(tts_os.router)
    with TestClient(app) as c:
        c.engine = eng
        yield c


def pcm(body):
    with wave.open(io.BytesIO(body)) as w:
        assert (w.getnchannels(), w.getsampwidth()) == (1, 2)
        return np.frombuffer(w.readframes(w.getnframes()), "<i2"), w.getframerate()


def test_reply_contract_wav_headers_and_word_timings(client):
    text = "Copy, *Commander*. Shields to 40 percent."
    r = client.post("/v1/tts", json={"text": text, "voice": "capcom", "tag": "confidence", "markup": True,
                                     "controls": {"rate": 1.0, "loud": 0.4, "f0_iqr": 2}, "guidance": 1.5})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    x, sr = pcm(r.content)
    assert sr == SR and len(x) > SR
    assert r.headers["x-tts-voice"] == "com.apple.voice.Aman.premium"        # CAPCOM's role on this machine
    assert r.headers["x-tts-engine"] == "say" and r.headers["x-tts-timing"] == "estimated"
    words = [tuple(int(v) for v in p.split("-")) for p in r.headers["x-tts-words"].split(",")]
    assert len(words) == len(ov.display_words(text)) == 6
    assert all(a <= b for a, b in words) and words[-1][1] <= len(x) / SR * 1000 + 1
    assert "X-TTS-Words" in r.headers["access-control-expose-headers"]
    assert client.engine.calls[-1][0] == ["Copy, Commander.", "Shields to 40 percent."]   # markup stripped


def test_rate_pause_and_end_gap(client):
    client.post("/v1/tts", json={"text": "One. Two.", "controls": {"rate": -2, "pause": 0.6}, "pace": 0.8})
    _, voice, factor, pause = client.engine.calls[-1]
    assert voice == "com.apple.voice.Tara.premium" and factor < 0.6 and pause > 0
    a = client.post("/v1/tts", json={"text": "Hello there."})
    b = client.post("/v1/tts", json={"text": "Hello there.", "perform": {"next": "Next one.", "strength": 0.7}})
    assert len(pcm(b.content)[0]) - len(pcm(a.content)[0]) == int(SR * tts_os.TAIL_S)
    assert b.headers["x-tts-pause-ms"] == str(round(tts_os.TAIL_S * 1000))


def test_unknown_or_blocked_voice_falls_back_to_the_guide(client):
    for v in ("voice_1085", "com.apple.speech.synthesis.voice.Bells", None):
        r = client.post("/v1/tts", json={"text": "Hi.", "voice": v})
        assert r.status_code == 200 and r.headers["x-tts-voice"] == "com.apple.voice.Tara.premium"


def test_repeated_lines_come_from_memory(client):
    n = len(client.engine.calls)
    a = client.post("/v1/tts", json={"text": "Mission complete."})
    b = client.post("/v1/tts", json={"text": "Mission complete."})
    assert a.content == b.content and b.headers["x-tts-memo"] == "hit" and len(client.engine.calls) == n + 1


def test_voice_pack_answers_only_when_asked_at_1x_in_the_guide_voice(client, monkeypatch):
    asked = []

    def pack(key):
        asked.append(key)
        pcm = ov.read_wav(tone_wav(0.8, sr=22050))[0]
        g = tts_os.resolve(None)   # the clip was recorded in this machine's guide voice (the Mac case)
        return {"pcm": pcm, "sr": 22050, "words": "10-200,220-400,420-700", "voice": g.get("system_voice") or g["id"],
                "voice_name": "Siri Voice 1 (Nora)"} if key == "all clear commander" else None
    monkeypatch.setattr(tts_os, "PACK_LOOKUP", pack)
    n = len(client.engine.calls)
    r = client.post("/v1/tts", json={"text": "All clear, *Commander*.", "pack": True})
    assert r.status_code == 200 and r.headers["x-tts-engine"] == "pack" and len(client.engine.calls) == n
    assert r.headers["x-tts-words"] == "10-200,220-400,420-700" and r.headers["x-tts-voice-name"] == "Siri Voice 1 (Nora)"
    assert abs(len(pcm(r.content)[0]) / SR - 0.8) < 0.01
    nx = client.post("/v1/tts", json={"text": "All clear, Commander.", "pack": True, "perform": {"next": "Go."}})
    assert len(pcm(nx.content)[0]) - len(pcm(r.content)[0]) == int(SR * tts_os.TAIL_S)   # the end gap, as live
    for body in ({"text": "All clear, Commander."},                                    # not asked for
                 {"text": "All clear, Commander.", "pack": True, "pace": 1.25},        # the kid's pace: live
                 {"text": "All clear, Commander.", "pack": True, "voice": "capcom"},   # not the guide's voice
                 {"text": "All clear, Commander.", "pack": True, "controls": {"pause": 0.6}}):   # slow line
        assert client.post("/v1/tts", json=body).headers["x-tts-engine"] == "say"
    client.post("/v1/tts", json={"text": "Something new.", "pack": True})
    assert asked[-1] == "something new" and client.engine.calls[-1][0] == ["Something new."]


def test_voice_pack_is_skipped_when_the_guide_voice_is_another_voice(client, monkeypatch):
    """Windows (or a Mac set to another system voice): the guide voice is not the pack's Nora, so every line is
    spoken live in one voice instead of alternating between studio clips and the live voice."""
    def pack(key):
        pcm = ov.read_wav(tone_wav(0.8, sr=22050))[0]
        return {"pcm": pcm, "sr": 22050, "words": "", "voice": "com.apple.siri.natural.Nora",
                "voice_name": "Siri Voice 1 (Nora)"}
    monkeypatch.setattr(tts_os, "PACK_LOOKUP", pack)
    g = tts_os.resolve(None)
    assert not tts_os.pack_voice_matches({"voice": "com.apple.siri.natural.Nora", "voice_name": "Siri Voice 1 (Nora)"},
                                         {**g, "id": "MSTTS_V110_enUS_ZiraM", "system_voice": None, "name": "Microsoft Zira"})
    assert tts_os.pack_voice_matches({"voice": "com.apple.siri.natural.Nora"},
                                     {"id": "system", "system_voice": "com.apple.siri.natural.Nora", "name": "Nora (Siri)"})
    if (g.get("system_voice") or g["id"]).lower() != "com.apple.siri.natural.nora":
        r = client.post("/v1/tts", json={"text": "All clear, Commander.", "pack": True})
        assert r.headers["x-tts-engine"] != "pack"


def test_voice_pack_module_reads_a_fixture_pack(tmp_path, monkeypatch):
    import json
    import soundfile as sf
    from app import voice_pack as vp
    (tmp_path / "clips").mkdir()
    x = ov.read_wav(tone_wav(1.2, sr=22050))[0]
    sf.write(str(tmp_path / "clips/a.mp3"), x, 22050, format="MP3", subtype="MPEG_LAYER_III")
    (tmp_path / "index.json").write_text(json.dumps({"voice": "com.apple.siri.natural.Nora", "voice_name": "Nora",
                                                     "clips": {"ready": {"file": "clips/a.mp3", "words": "0-500"},
                                                               "gone": {"file": "clips/missing.mp3"}}}))
    monkeypatch.setattr(settings, "voice_pack_dir", tmp_path)
    monkeypatch.setattr(settings, "voice_pack", "on")
    vp.STATE["mtime"] = None
    hit = vp.lookup("ready")
    assert hit["sr"] == 22050 and abs(len(hit["pcm"]) / 22050 - 1.2) < 0.06 and hit["words"] == "0-500"
    assert vp.lookup("gone") is None and vp.lookup("nope") is None
    assert vp.health()["voice_pack"]["clips"] == 2
    monkeypatch.setattr(settings, "voice_pack", "off")
    assert vp.lookup("ready") is None


def test_voices_list_roles_and_health(client):
    v = client.get("/v1/tts/voices").json()
    assert v["engine"] == "say" and v["default"] == v["roles"]["guide"] == "com.apple.voice.Tara.premium"
    assert v["roles"]["capcom"] == "com.apple.voice.Aman.premium"
    assert [x["name"] for x in v["voices"]] == ["Tara", "Aman"]               # Bells never listed
    assert v["voices"][0]["desc"] == "Premium · India · female" and v["voices"][0]["picker"]
    h = tts_os.health()["tts"]
    assert h["loaded"] and h["voice_name"] == "Tara" and h["warm_ms"] is not None and h["voices"] == 2


def test_off_and_no_engine_fail_open(fresh, monkeypatch):
    monkeypatch.setattr(settings, "os_tts", "off")
    tts_os.load()
    assert tts_os.health()["tts"] == {**tts_os.health()["tts"], "loaded": False, "error": "OS_TTS=off"}
    app = FastAPI()
    app.include_router(tts_os.router)
    with TestClient(app) as c:
        assert c.post("/v1/tts", json={"text": "Hi."}).status_code == 503
        assert c.get("/v1/tts/voices").status_code == 503
    monkeypatch.setattr(settings, "os_tts", "on")
    monkeypatch.setattr(settings, "os_tts_engine", "auto")
    monkeypatch.setattr(sys, "platform", "linux")
    tts_os.load()
    assert not tts_os.health()["tts"]["loaded"] and "linux" in tts_os.health()["tts"]["error"]


# ---- macOS: the `say` command line and the Spoken Content system voice ------------------------------------------------
def test_say_command_line_rate_pauses_and_system_voice(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        out = cmd[cmd.index("-o") + 1]
        open(out, "wb").write(tone_wav(1.0))
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(tts_os.shutil, "which", lambda n: "/usr/bin/say")
    monkeypatch.setattr(tts_os.subprocess, "run", run)
    e = tts_os.SayEngine()
    monkeypatch.setattr(e, "native_wpm", lambda v: 180.0)                      # the voice's measured own rate
    x, sr, cues, info = e.render(["One.", "Two."], "com.apple.voice.Tara.premium", 1.2, 300, False)
    cmd, text = calls[-1]
    assert cmd[:3] == ["say", "-v", "com.apple.voice.Tara.premium"] and cmd[cmd.index("-r") + 1] == str(info["wpm"])
    assert info["wpm"] == round(180 * 1.2) and f"--data-format=LEI16@{SR}" in cmd   # relative to the native rate
    assert text == b"One. [[slnc 300]] Two." and sr == SR and cues is None
    e.render(["Hi."], ov.SYSTEM_ID, 1.0, 0, False)
    assert "-v" not in calls[-1][0]                                            # the system voice: no -v at all


def test_no_rate_flag_at_1x_pace(monkeypatch):
    """At the kid's 1x pace (and small persona / situation nudges) `say` gets no -r: the voice's own rate and phrasing.
    A forced rate made Siri sound processed (4.06 s vs its own 5.0 s on a sample line)."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        open(cmd[cmd.index("-o") + 1], "wb").write(tone_wav(1.0))
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(tts_os.shutil, "which", lambda n: "/usr/bin/say")
    monkeypatch.setattr(tts_os.subprocess, "run", run)
    e = tts_os.SayEngine()
    for f in (1.0, ov.rate_factor({}, 1.0), ov.rate_factor({"rate": 0.3}, 1.0), ov.rate_factor({"rate": -0.2}, 1.0)):
        _, _, _, info = e.render(["Hello there."], ov.SYSTEM_ID, f, 0, True)
        assert "-r" not in calls[-1] and info["wpm"] == "native"
    e.render(["Hello there."], ov.SYSTEM_ID, ov.rate_factor({}, 1.5), 0, False)   # the kid's 1.5x: relative -r
    assert "-r" in calls[-1]
    assert calls[-2][calls[-2].index("-o") + 1] != calls[-1][calls[-1].index("-o") + 1]


def test_negative_pause_never_tightens(client):
    client.post("/v1/tts", json={"text": "One, two. Three.", "controls": {"pause": -1.5}})
    _, _, factor, pause = client.engine.calls[-1]
    assert pause == 0 and factor == 1.0


def test_system_voice_pref_read_and_made_the_default(monkeypatch):
    import plistlib
    pref = {"SpokenContentDefaultVoiceSelectionsByLanguage": [
        "en", {"_type": "Speech.VoiceSelection", "boundLanguage": "en", "voiceId": "com.apple.siri.natural.Nora"}]}
    jxa = ("LOCALE|en_US\ncom.apple.voice.Tara.premium|Tara (English (India))|en_IN|VoiceGenderFemale\n"
           "com.apple.voice.compact.en-US.Samantha|Samantha|en_US|VoiceGenderFemale\n"
           "com.apple.speech.synthesis.voice.Bells|Bells|en_US|VoiceGenderMale\n")

    def run(cmd, **kw):
        if cmd[0].endswith("defaults"):
            return types.SimpleNamespace(returncode=0, stdout=plistlib.dumps(pref), stderr=b"")
        return types.SimpleNamespace(returncode=0, stdout=jxa, stderr="")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(tts_os.shutil, "which", lambda n: "/usr/bin/say")
    monkeypatch.setattr(tts_os.subprocess, "run", run)
    voices, loc = tts_os.SayEngine().list_voices()
    r = ov.rank(voices, loc)
    assert r[0]["id"] == ov.SYSTEM_ID and ov.describe(r[0]) == "Nora (Siri)"
    assert [v["id"] for v in r][1:] == ["com.apple.voice.Tara.premium", "com.apple.voice.compact.en-US.Samantha"]
    # no pref (or an unreadable one): still offered, never the default
    pref = {}
    voices, _ = tts_os.SayEngine().list_voices()
    r = ov.rank(voices, loc)
    assert r[0]["id"] == "com.apple.voice.Tara.premium" and ov.SYSTEM_ID in [v["id"] for v in r]


# ---- Windows: WinRT mocked -------------------------------------------------------------------------------------------
def fake_winrt(monkeypatch, voices=None, fail=False):
    """The pywinrt modules tts_os imports, backed by a fake synthesizer that renders 16 kHz WAV with word cues."""
    rec = {"rate": None, "text": None, "voice": None}

    class Info:
        def __init__(self, vid, name, lang, gender):
            self.id, self.display_name, self.language, self.gender, self.description = vid, name, lang, gender, name

    class Op:
        def __init__(self, v):
            self.v = v

        def get(self):
            return self.v

    class Cue:
        def __init__(self, a, d, pos, text):
            self.start_time, self.duration = datetime.timedelta(seconds=a), datetime.timedelta(seconds=d)
            self.start_position_in_input, self.text = pos, text

    class Stream:
        def __init__(self, text):
            ms = [(m.start(), m.group()) for m in re.finditer(r"\S+", text)]
            self.cues = [Cue(0.05 + 0.4 * i, 0.3, p, w.strip(".,!?")) for i, (p, w) in enumerate(ms)]
            self.wav = tone_wav(0.05 + 0.4 * len(ms), sr=16000)
            self.size = len(self.wav)
            self.timed_metadata_tracks = [types.SimpleNamespace(id="SpeechWord", cues=self.cues)]

        def get_input_stream_at(self, pos):
            return self.wav

        def close(self):
            pass

    class Options:
        include_word_boundary_metadata = False
        speaking_rate = 1.0
        punctuation_silence = 0

    class SpeechSynthesizer:
        all_voices = voices if voices is not None else [
            Info(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_enUS_ZiraM",
                 "Microsoft Zira", "en-US", 1),
            Info(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_enUS_MarkM",
                 "Microsoft Mark", "en-US", 0),
            Info(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_frFR_JulieM",
                 "Microsoft Julie", "fr-FR", 1)]

        def __init__(self):
            if fail:
                raise OSError("class not registered")
            self.options, self.voice = Options(), None

        def synthesize_text_to_stream_async(self, text):
            rec.update(rate=self.options.speaking_rate, text=text, voice=self.voice and self.voice.display_name,
                       words=self.options.include_word_boundary_metadata)
            return Op(Stream(text))

    class DataReader:
        def __init__(self, src):
            self.src = src

        def load_async(self, n):
            return Op(n)

        def read_bytes(self, buf):
            buf[:] = self.src

    class SpeechCue:
        @staticmethod
        def _from(c):
            return c

    mods = {
        "winrt": types.ModuleType("winrt"),
        "winrt.runtime": types.SimpleNamespace(init_apartment=lambda t: None, MTA=1),
        "winrt.windows": types.ModuleType("winrt.windows"),
        "winrt.windows.media": types.ModuleType("winrt.windows.media"),
        "winrt.windows.media.speechsynthesis": types.SimpleNamespace(
            SpeechSynthesizer=SpeechSynthesizer, SpeechPunctuationSilence=types.SimpleNamespace(MIN=1, DEFAULT=0)),
        "winrt.windows.media.core": types.SimpleNamespace(SpeechCue=SpeechCue),
        "winrt.windows.storage": types.ModuleType("winrt.windows.storage"),
        "winrt.windows.storage.streams": types.SimpleNamespace(DataReader=DataReader),
    }
    for k, v in mods.items():
        monkeypatch.setitem(sys.modules, k, v)
    monkeypatch.setattr(tts_os, "windows_locale", lambda: "en-US")
    return rec


def test_winrt_engine_real_word_timings_and_rate(fresh, monkeypatch):
    rec = fake_winrt(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(settings, "os_tts", "on")
    monkeypatch.setattr(settings, "os_tts_engine", "auto")
    tts_os.load()
    h = tts_os.health()["tts"]
    assert h["loaded"] and h["engine"] == "winrt" and h["timing"] == "os", h
    assert h["roles"]["guide"] == "winrt:MSTTS_V110_enUS_ZiraM" and h["roles"]["capcom"] == "winrt:MSTTS_V110_enUS_MarkM"
    assert h["voices"] == 2                                                   # French Julie is not offered
    wav, info = tts_os.render(tts_os.TTSRequest(text="Copy, Commander. Shields to *40* percent.", voice="capcom",
                                                controls={"rate": 2.0, "pause": -1.5}))
    assert rec["voice"] == "Microsoft Mark" and rec["words"] and rec["rate"] == pytest.approx(2 ** 0.5, rel=0.01)
    assert rec["text"] == "Copy, Commander. Shields to 40 percent."
    assert info["engine"] == "winrt" and info["timing"] == "os"
    got = [tuple(int(v) for v in p.split("-")) for p in info["words"].split(",")]
    assert got == [(round((0.05 + 0.4 * i) * 1000), round((0.35 + 0.4 * i) * 1000)) for i in range(6)]
    x, sr = pcm(wav)
    assert sr == SR and abs(len(x) / SR - (0.05 + 0.4 * 6)) < 0.01             # 16 kHz resampled to 24 kHz


def test_winrt_inserted_pause_shifts_the_cues(fresh, monkeypatch):
    fake_winrt(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(settings, "os_tts_engine", "winrt")
    tts_os.load()
    _, plain = tts_os.render(tts_os.TTSRequest(text="One. Two."))
    _, slow = tts_os.render(tts_os.TTSRequest(text="One. Two.", controls={"pause": 1.0}))
    a = [int(p.split("-")[0]) for p in plain["words"].split(",")]
    b = [int(p.split("-")[0]) for p in slow["words"].split(",")]
    assert b[0] == a[0] and b[1] - a[1] == ov.sentence_pause_ms({"pause": 1.0})


def test_winrt_missing_falls_back_to_sapi(fresh, monkeypatch):
    fake_winrt(monkeypatch, fail=True)
    spoke = {}

    class Token:
        def __init__(self, tid, name, lang):
            self.Id, self.name, self.lang = tid, name, lang

        def GetAttribute(self, k):
            return {"Name": self.name, "Language": self.lang, "Gender": "Female"}[k]

        def GetDescription(self):
            return self.name

    class Tokens:
        items = [Token(r"HKLM\...\TTS_MS_EN-US_ZIRA_11.0", "Microsoft Zira Desktop", "409"),
                 Token(r"HKLM\...\TTS_MS_DE-DE_HEDDA_11.0", "Microsoft Hedda Desktop", "407")]
        Count = 2

        def Item(self, i):
            return self.items[i]

    class FileStream:
        Format = None

        def Open(self, path, mode, events):
            self.path = path

        def Close(self):
            open(self.path, "wb").write(tone_wav(1.2))

    class Voice:
        Rate, Voice, AudioOutputStream = 0, None, None

        def GetVoices(self):
            return Tokens()

        def Speak(self, text, flags):
            spoke.update(text=text, flags=flags, rate=self.Rate, voice=self.Voice.name)

    def create(prog, dynamic=False):
        assert dynamic                                    # late-bound: nothing generated on disk
        return {"SAPI.SpVoice": Voice, "SAPI.SpFileStream": FileStream,
                "SAPI.SpAudioFormat": lambda: types.SimpleNamespace(Type=None)}[prog]()
    cc = types.SimpleNamespace(CreateObject=create)
    comtypes = types.SimpleNamespace(CoInitializeEx=lambda f: None, COINIT_MULTITHREADED=0, client=cc)
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setitem(sys.modules, "comtypes.client", cc)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(settings, "os_tts", "on")
    monkeypatch.setattr(settings, "os_tts_engine", "auto")
    tts_os.load()
    h = tts_os.health()["tts"]
    assert h["loaded"] and h["engine"] == "sapi" and h["voices"] == 1 and h["voice_name"] == "Zira"
    _, info = tts_os.render(tts_os.TTSRequest(text="<b>Hello</b> there.", controls={"rate": 4}, pace=1.5))
    assert spoke["voice"] == "Microsoft Zira Desktop" and spoke["text"] == "Hello there."
    assert spoke["flags"] == tts_os.SVSF_IS_NOT_XML and 0 < spoke["rate"] <= 10
    assert info["timing"] == "estimated" and info["words"].count(",") == 1


# ---- this Mac, for real -----------------------------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform != "darwin", reason="macOS `say` only")
def test_real_mac_render(fresh, monkeypatch):
    monkeypatch.setattr(settings, "os_tts", "on")
    monkeypatch.setattr(settings, "os_tts_engine", "say")
    tts_os.load()
    if tts_os.STATE["engine"] is None:
        pytest.skip(f"say unavailable: {tts_os.STATE['error']}")
    assert all(not ov.is_novelty(v) for v in tts_os.STATE["voices"])
    wav, info = tts_os.render(tts_os.TTSRequest(text="The rover found ice near the crater.", voice="capcom"))
    x, sr = pcm(wav)
    assert sr == SR and 1.0 < len(x) / SR < 6 and np.abs(x).max() > 1000
    ends = [int(p.split("-")[1]) for p in info["words"].split(",")]
    assert len(ends) == 7 and ends[-1] <= len(x) / SR * 1000 + 1 and ends == sorted(ends)
