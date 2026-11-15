"""Steering policy (backend/app/steering.py) and /api/tts engine selection, fallback and cache key."""
import pytest
from fastapi.testclient import TestClient

from app import steering, tts, voices
from app.config import settings
from app.director import decision, decisions_for
from app.main import app

S = steering.style_for


# ---- the table: each situation → expected tag / control direction ------------------------------------------------------
@pytest.mark.parametrize("situation,tag,check", [
    ("storm_alert", "determined", lambda c: c["rate"] > 0 and c["loud"] > 0),
    ("storm_warning", "emphasis", lambda c: c["loud"] > 0),
    ("all_clear", "relief", lambda c: True),
    ("night_low_power", "serenity", lambda c: c["rate"] < 0 and c["loud"] < 0),
    ("explain", "enunciated", lambda c: c["rate"] < 0),
    ("awe", "amazement", lambda c: c["f0_iqr"] > 0),
    ("badge", "pride", lambda c: c["loud"] > 0),
    ("retry", "sympathy", lambda c: c["rate"] < 0),
    ("story", "nostalgia", lambda c: c["rate"] < 0),
    ("readback", "confidence", lambda c: c["rate"] > 0),
])
def test_situation_table(situation, tag, check):
    st = S("capcom", "Okay.", situation=situation)
    assert st["tag"] == tag and check(st["controls"])


def test_personas_have_distinct_tts_voices():
    assert len(set(steering.VOICES.values())) == 4
    assert S("capcom")["tag"] == "confidence" and S("capcom")["controls"]["rate"] > 0
    assert S("story")["tts_voice"] == steering.VOICES["story"]
    assert S("guide", "A crater.", situation="story")["voice"] == "story"   # a hardware story speaks as the hardware


@pytest.mark.parametrize("emotion,tag", [("frustrated", "sympathy"), ("confused", "serenity"), ("excited", "excited")])
def test_kid_affect(emotion, tag):
    st = S("guide", "Craters are holes.", emotion=emotion)
    assert st["tag"] == tag
    if emotion != "excited":
        assert st["controls"]["rate"] < 0 and st["controls"]["pause"] > 0


def test_upset_kid_during_alarm_keeps_alert_tag_but_slows():
    st = S("capcom", "Storm is here!", situation="storm_alert", emotion="scared")
    assert st["tag"] == "determined" and st["controls"]["rate"] < 0 and "loud" not in st["controls"]


def test_excited_kid_does_not_hype_a_calm_line():
    assert S("capcom", "Save power.", situation="night_low_power", emotion="excited")["tag"] == "serenity"


def test_question_rises():
    assert S("guide", "Do you want to see it?")["controls"]["f0_end"] >= 1.5
    assert "f0_end" not in S("guide", "Here it is.")["controls"]


def test_readback_emphasizes_numbers_and_place():
    st = S("capcom", "Copy, commander. Setting the shields to 40% at Shackleton.", situation="readback",
           places=["Shackleton"])
    assert st["markup"] and st["emph"] == ["40", "Shackleton"]
    assert S("capcom", "Shields to 40. Shields now get 40%.", situation="readback")["emph"] == ["40"]   # once each
    assert steering.apply_emphasis("Shields to 40% at Shackleton.", st["emph"]) == "Shields to *40*% at *Shackleton*."
    assert steering.apply_emphasis("Go to Mare Tranquillitatis.", ["Mare Tranquillitatis"]) == \
        "Go to <emph>Mare Tranquillitatis</emph>."


def test_forbidden_tags_never_chosen():
    for situation in [None, *steering.SITUATIONS]:
        for emo in [None, *steering.AFFECT, "angry"]:
            for v in steering.PERSONAS:
                assert S(v, "Hmm?", situation=situation, emotion=emo)["tag"] not in steering.FORBIDDEN
    for bad in ("anger", "contempt", "disgust", "sarcasm", "panic", "disappointment"):
        assert S("guide", "No.", tag=bad)["tag"] not in steering.FORBIDDEN
        assert tts.clean_style("guide", "No.", {"tag": bad})["tag"] not in steering.FORBIDDEN


def test_controls_are_clamped():
    st = S("guide", "x", controls={"rate": 9, "loud": -9})
    assert st["controls"]["rate"] == steering.CONTROL_LIMIT and st["controls"]["loud"] == -steering.CONTROL_LIMIT


# ---- the Director carries style -----------------------------------------------------------------------------------------
def test_every_say_decision_has_style():
    d = decision("say", text="Hello cadet.", voice="guide")
    assert d["style"]["tts_voice"] == steering.VOICES["guide"] and "situation" not in d


def test_decisions_for_maps_actions_to_situations():
    says = lambda r, ctx=None: [d for d in decisions_for(r, "q", ctx or {}) if d["t"] == "say"][0]["style"]
    assert says({"action": "say", "say": "Regolith: moon dust.", "source": "glossary"})["tag"] == "enunciated"
    assert says({"action": "play", "say": "Listen!", "source": "sounds"})["tag"] == "amazement"
    rb = says({"action": "command", "say": "Copy, commander. Shields to 40%.", "source": "mission", "state": {}})
    assert rb["voice"] == "capcom" and rb["emph"] == ["40"]
    assert says({"action": "houston", "say": "Houston here. Go.", "source": "mission", "state": {}})["voice"] == "houston"
    assert says({"action": "say", "say": "Craters.", "source": "llm"}, {"emotion": "frustrated"})["tag"] == "sympathy"
    st = says({"action": "status", "say": "Storm.", "source": "mission", "state": {"env": {"storm": {"active": True}}}})
    assert st["tag"] == "determined"


def test_academy_attempt_styles():
    from app.academy.routes import _decisions
    retry = [d for d in _decisions("l1", 0, "retry", "Not quite. Try again!") if d["t"] == "say"][0]
    badge = [d for d in _decisions("l1", 2, "passed", "You earned it!", badge=True) if d["t"] == "say"][0]
    assert retry["style"]["tag"] == "sympathy" and badge["style"]["tag"] == "pride"


# ---- /api/tts: engine selection, fallback, cache key ---------------------------------------------------------------------
@pytest.fixture
def engines(monkeypatch, tmp_path):
    calls = {"os": [], "deepgram": [], "os_ok": True}

    async def os_tts(text, style, place):
        calls["os"].append((text, style, place))
        if not calls["os_ok"]:
            raise RuntimeError("os tts 503: not loaded")
        return b"RIFFfake-wav:" + style["tag"].encode()

    async def dg(model, text):
        calls["deepgram"].append((model, text))
        return b"ID3fake-mp3"

    monkeypatch.setattr(tts, "_os_tts", os_tts)
    monkeypatch.setattr(tts, "_synth", dg)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "c")
    monkeypatch.setattr(settings, "tts_engine", "os")
    monkeypatch.setattr(settings, "deepgram_api_key", "k")
    return calls


def test_os_voice_is_default_engine_and_returns_wav(engines):
    with TestClient(app) as c:
        r = c.get("/api/tts", params={"text": "Copy that.", "voice": "capcom"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert r.headers["x-tts-engine"] == "os" and r.headers["x-tts-voice"] == voices.resolve("capcom")
    assert voices.resolve("capcom") != steering.VOICES["capcom"]          # the role became this machine's voice
    assert engines["os"][0][1]["tag"] == "confidence" and not engines["deepgram"]


def test_style_param_reaches_the_engine_and_keys_the_cache(engines):
    import json
    calm = json.dumps(S("capcom", "Shields up.", situation="night_low_power"))
    alert = json.dumps(S("capcom", "Shields up.", situation="storm_alert"))
    with TestClient(app) as c:
        a = c.get("/api/tts", params={"text": "Shields up.", "voice": "capcom", "style": calm})
        b = c.get("/api/tts", params={"text": "Shields up.", "voice": "capcom", "style": alert})
        a2 = c.get("/api/tts", params={"text": "Shields up.", "voice": "capcom", "style": calm})
        p = c.post("/api/tts", json={"text": "Shields up.", "voice": "capcom", "style": json.loads(alert)})
    assert a.headers["x-tts-cache"] == b.headers["x-tts-cache"] == "miss"     # a new style = a new rendering
    assert a2.headers["x-tts-cache"] == p.headers["x-tts-cache"] == "hit"
    assert [s["tag"] for _, s, _ in engines["os"]] == ["serenity", "determined"]
    k1 = tts.cache_path("v", "t", {"tag": "relief"}, "os")
    assert k1 != tts.cache_path("v", "t", {"tag": "pride"}, "os") and k1.suffix == ".wav"


def test_sentence_place_reaches_the_engine(engines):
    with TestClient(app) as c:
        c.get("/api/tts", params={"text": "One.", "voice": "guide", "i": 0, "n": 2, "next": "Two."})
    assert engines["os"][0][2] == {"para_index": 0, "para_len": 2, "next": "Two."}


def test_os_voice_down_falls_back_to_deepgram(engines):
    engines["os_ok"] = False
    with TestClient(app) as c:
        r = c.get("/api/tts", params={"text": "Copy.", "voice": "capcom"})
    assert r.status_code == 200 and r.headers["x-tts-engine"] == "deepgram"
    assert r.headers["content-type"] == "audio/mpeg" and "os" in r.headers["x-tts-fallback"]


def test_both_down_tells_the_browser(engines, monkeypatch):
    engines["os_ok"] = False
    monkeypatch.setattr(settings, "deepgram_api_key", "")
    with TestClient(app) as c:
        r = c.get("/api/tts", params={"text": "Copy."})
    assert r.status_code == 502 and r.json()["fallback"] == "browser"


def test_engine_deepgram_skips_the_os_voice(engines, monkeypatch):
    monkeypatch.setattr(settings, "tts_engine", "deepgram")
    with TestClient(app) as c:
        r = c.get("/api/tts", params={"text": "Copy.", "voice": "houston"})
    assert r.headers["x-tts-engine"] == "deepgram" and not engines["os"]


def test_old_query_shape_still_works(engines):
    with TestClient(app) as c:
        assert c.get("/api/tts", params={"text": "Hi.", "voice": "story"}).status_code == 200
        assert c.get("/api/tts", params={"text": "Hi.", "voice": "pirate"}).status_code == 422
        assert c.get("/api/tts", params={"text": "Hi.", "style": "{not json"}).status_code == 200
