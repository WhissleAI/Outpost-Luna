"""The OS voices the app speaks with, rendered to files (never played).

Which voices: exactly the app's rules. The ranking, allowlist, novelty blocklist and persona roles are imported from
the app's own model_server/app/os_voices.py (pure functions, numpy only), so this kit uses the voices the app would.
The engines mirror model_server/app/tts_os.py:

    say     macOS /usr/bin/say -o <file> (renders to a file: silent). Voice "system" = no -v (the Spoken Content voice,
            which can be a Siri voice). The app's own pace: no -r.
    winrt   Windows 10/11 OneCore voices (Windows.Media.SpeechSynthesis via pywinrt), speaking_rate 1.0.
    sapi    Windows SAPI 5 desktop voices (comtypes), Rate 0. The app's fallback engine.
    fake    --dry-run: synthetic tones, no OS speech at all.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SR = 24000


def _load_ov():
    p = REPO / "model_server" / "app" / "os_voices.py"
    if not p.exists():
        return None
    spec = importlib.util.spec_from_file_location("outpost_os_voices", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ov = _load_ov()


def read_wav_float(path_or_bytes) -> tuple[np.ndarray, int]:
    import soundfile as sf
    import io
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else str(path_or_bytes)
    x, sr = sf.read(src, dtype="float32", always_2d=True)
    return x.mean(axis=1), sr


# ================================================================================================= engines
class SayEngine:
    name = "say"
    JXA = ('ObjC.import("AppKit");var v=$.NSSpeechSynthesizer.availableVoices,o=["LOCALE|"+'
           'ObjC.unwrap($.NSLocale.currentLocale.localeIdentifier)];for(var i=0;i<v.count;i++){var id=v.objectAtIndex(i),'
           'a=$.NSSpeechSynthesizer.attributesForVoice(id);o.push([ObjC.unwrap(id),ObjC.unwrap(a.objectForKey("VoiceName")),'
           'ObjC.unwrap(a.objectForKey("VoiceLocaleIdentifier")),ObjC.unwrap(a.objectForKey("VoiceGender"))].join("|"))}'
           'o.join("\\n")')

    def __init__(self):
        if sys.platform != "darwin" or not shutil.which("say"):
            raise RuntimeError("macOS `say` not available")

    def list_voices(self) -> tuple[list[dict], str]:
        out = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", self.JXA], capture_output=True,
                             text=True, timeout=30).stdout
        voices, loc = [], ""
        for ln in out.splitlines():
            p = ln.split("|")
            if p[0] == "LOCALE":
                loc = p[1] if len(p) > 1 else ""
                continue
            if len(p) < 3 or not p[0]:
                continue
            g = (p[3] if len(p) > 3 else "").replace("VoiceGender", "").lower()
            voices.append({"id": p[0], "name": p[1] or p[0], "locale": p[2],
                           "gender": g if g in ("female", "male") else "",
                           "quality": ov.mac_quality(p[0]) if ov else "standard", "engine": "say"})
        sysv = system_voice_id()
        if ov:
            voices.append(ov.system_voice_entry(sysv, voices))
        else:
            voices.append({"id": "system", "name": "System voice", "locale": "en-US", "engine": "say",
                           "quality": "standard"})
        return voices, loc

    def render(self, text: str, voice: str) -> tuple[np.ndarray, int]:
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="arc-collect-")
        os.close(fd)
        try:
            pick = [] if voice == "system" else ["-v", voice]
            r = subprocess.run(["say", *pick, "-o", path, "--file-format=WAVE", f"--data-format=LEI16@{SR}"],
                               input=text.encode(), capture_output=True, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(f"say failed ({r.returncode}): {r.stderr.decode(errors='replace')[:200]}")
            return read_wav_float(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


def system_voice_id() -> str | None:
    if not ov:
        return None
    import plistlib
    try:
        out = subprocess.run(["/usr/bin/defaults", "export", "com.apple.Accessibility", "-"], capture_output=True,
                             timeout=10).stdout
        return ov.spoken_content_voice(plistlib.loads(out).get("SpokenContentDefaultVoiceSelectionsByLanguage"))
    except Exception:  # noqa: BLE001
        return None


def _tail(token_id: str) -> str:
    return re.split(r"[\\/]", str(token_id))[-1]


class WinRTEngine:
    name = "winrt"

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("WinRT speech is Windows-only")
        try:
            import winrt.runtime as rt
            rt.init_apartment(rt.MTA)
        except Exception:  # noqa: BLE001
            pass
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer
        from winrt.windows.storage.streams import DataReader
        self.SpeechSynthesizer, self.DataReader = SpeechSynthesizer, DataReader
        self.synth = SpeechSynthesizer()
        self.info = {}

    def list_voices(self):
        out = []
        for v in self.SpeechSynthesizer.all_voices:
            vid = "winrt:" + _tail(v.id)
            self.info[vid] = v
            name = str(v.display_name)
            g = int(getattr(v.gender, "value", v.gender))
            natural = "natural" in name.lower() or "neural" in str(v.id).lower()
            out.append({"id": vid, "name": name, "locale": str(v.language), "gender": "female" if g == 1 else "male",
                        "quality": "neural" if natural else "onecore", "engine": "winrt"})
        return out, ""

    def render(self, text, voice):
        s = self.synth
        if voice in self.info:
            s.voice = self.info[voice]
        s.options.speaking_rate = 1.0
        stream = s.synthesize_text_to_stream_async(text).get()
        n = int(stream.size)
        reader = self.DataReader(stream.get_input_stream_at(0))
        reader.load_async(n).get()
        buf = bytearray(n)
        reader.read_bytes(buf)
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass
        return read_wav_float(bytes(buf))


class SapiEngine:
    name = "sapi"
    LCID = {"409": "en-US", "809": "en-GB", "c09": "en-AU", "1009": "en-CA", "1809": "en-IE", "4009": "en-IN",
            "1409": "en-NZ", "1c09": "en-ZA", "4809": "en-SG"}

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("SAPI is Windows-only")
        import comtypes
        import comtypes.client as cc
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except Exception:  # noqa: BLE001
            pass
        self.cc = cc
        self.voice = cc.CreateObject("SAPI.SpVoice", dynamic=True)
        self.tokens = {}

    def list_voices(self):
        out, toks = [], self.voice.GetVoices()
        for i in range(toks.Count):
            t = toks.Item(i)
            vid = "sapi:" + _tail(t.Id)
            self.tokens[vid] = t
            lang = str(t.GetAttribute("Language") or "").split(";")[0].lower()
            out.append({"id": vid, "name": str(t.GetAttribute("Name") or t.GetDescription()),
                        "locale": self.LCID.get(lang, ""), "gender": str(t.GetAttribute("Gender") or "").lower(),
                        "quality": "sapi", "engine": "sapi"})
        return out, ""

    def render(self, text, voice):
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="arc-collect-")
        os.close(fd)
        try:
            fmt = self.cc.CreateObject("SAPI.SpAudioFormat", dynamic=True)
            fmt.Type = 26                                        # SAFT24kHz16BitMono
            st = self.cc.CreateObject("SAPI.SpFileStream", dynamic=True)
            st.Format = fmt
            st.Open(path, 3, False)                              # SSFMCreateForWrite
            if voice in self.tokens:
                self.voice.Voice = self.tokens[voice]
            self.voice.Rate = 0
            self.voice.AudioOutputStream = st
            try:
                self.voice.Speak(text, 16)                       # SVSFIsNotXML
            finally:
                st.Close()
            return read_wav_float(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


class FakeEngine:
    """--dry-run: a few made-up voices that 'speak' harmonic syllable bursts (about 3 words/s). Never calls the OS."""
    name = "fake"

    def list_voices(self):
        return [{"id": "fake:alpha", "name": "Alpha", "locale": "en-US", "gender": "female", "quality": "premium",
                 "engine": "fake"},
                {"id": "fake:bravo", "name": "Bravo", "locale": "en-GB", "gender": "male", "quality": "enhanced",
                 "engine": "fake"},
                {"id": "fake:charlie", "name": "Charlie", "locale": "en-AU", "gender": "female",
                 "quality": "standard", "engine": "fake"}], "en-US"

    def render(self, text, voice):
        f0 = {"fake:alpha": 190.0, "fake:bravo": 110.0}.get(voice, 160.0)
        words = max(1, len(text.split()))
        rng = np.random.default_rng(abs(hash((text, voice))) % (2 ** 32))
        parts = []
        for _ in range(words):
            n = int(SR * rng.uniform(0.18, 0.32))
            t = np.arange(n) / SR
            f = f0 * (1 + 0.1 * np.sin(2 * np.pi * 3 * t))
            ph = 2 * np.pi * np.cumsum(f) / SR
            x = sum(np.sin(k * ph) / k for k in range(1, 6)) * np.hanning(n)
            parts += [x, np.zeros(int(SR * rng.uniform(0.04, 0.12)))]
        return (np.concatenate(parts) * 0.2).astype(np.float32), SR


ENGINES = {"say": SayEngine, "winrt": WinRTEngine, "sapi": SapiEngine}
AUTO = {"darwin": ("say",), "win32": ("winrt", "sapi")}


def load_engines(dry_run: bool, which: str = "auto") -> tuple[list, list[str]]:
    """The engines to render with. auto: macOS `say`; Windows: WinRT AND SAPI (the app uses WinRT, SAPI is its fallback;
    both are voices the app can speak with). Returns (engines, notes)."""
    if dry_run:
        return [FakeEngine()], ["dry run: synthetic voices"]
    names = AUTO.get(sys.platform, ()) if which == "auto" else tuple(w.strip() for w in which.split(",") if w.strip())
    engines, notes = [], []
    for n in names:
        try:
            engines.append(ENGINES[n]())
        except Exception as e:  # noqa: BLE001
            notes.append(f"{n}: not available ({str(e)[:120]})")
    return engines, notes


def app_voices(engines: list, kid_locale: str | None = None) -> tuple[list[dict], dict, list[str]]:
    """Every voice the app can use here: listed by the engines, then the app's own allowlist + ranking (os_voices.rank:
    English, no novelty voices, one entry per name+locale+engine). Each gets `in_picker` (offered in Settings) and its
    persona roles. Returns (voices, roles, notes)."""
    listed, notes, loc = [], [], ""
    for e in engines:
        try:
            v, l = e.list_voices()
            listed += v
            loc = loc or l
        except Exception as ex:  # noqa: BLE001
            notes.append(f"{e.name}: listing failed ({str(ex)[:120]})")
    if ov is None or any(e.name == "fake" for e in engines):
        if ov is None:
            notes.append("model_server/app/os_voices.py not found: using every English voice, unranked")
        ranked = [v for v in listed if str(v.get("locale", "")).lower().replace("_", "-").startswith("en")]
        roles = {}
        picks = set(v["id"] for v in ranked[:12])
    else:
        ranked = ov.rank(listed, kid_locale or loc)
        roles = ov.assign_roles(ranked, kid_locale or loc)
        picks = set(v["id"] for v in ov.picker(ranked))
    by_role: dict[str, list[str]] = {}
    for r, vid in roles.items():
        by_role.setdefault(vid, []).append(r)
    for v in ranked:
        v["in_picker"] = v["id"] in picks
        v["roles"] = by_role.get(v["id"], [])
    return ranked, roles, notes


def engine_for(engines: list, voice: dict):
    for e in engines:
        if e.name == voice.get("engine"):
            return e
    return engines[0]


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:80] or "voice"
